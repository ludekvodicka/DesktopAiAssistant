"""Self-update through the shared autoupdate member, in this application's Qt binding.

The member decides and does everything that needs no Qt: when to check, what to download,
how to verify and how to swap. This module supplies the event loop it runs on, the facts only
this application knows (repository, release file names, program folder) and what the tray
and Settings show.
"""

import functools
import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import shiboken6
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from . import __version__
from .config import data_dir
from .shared.desktop.autoupdate.feed import UpdateFeedGithub
from .shared.desktop.autoupdate.installer import UpdateInstaller
from .shared.desktop.autoupdate.manager import UpdateManager
from .shared.desktop.autoupdate.runtime import UpdateRuntime, UpdateRuntimeFacts, UpdateTargetFolder
from .shared.desktop.autoupdate.stager import UpdateStager
from .shared.desktop.autoupdate.status import (
    UpdateAvailable,
    UpdateChecking,
    UpdateCurrent,
    UpdateDownloading,
    UpdateFailed,
    UpdateIdle,
    UpdateInstalling,
    UpdateOff,
    UpdateReady,
    UpdateStatus,
)
from .shared.desktop.autoupdate.transport import UpdateTransport
from .shared.desktop.autoupdate.view import UpdateAction, UpdateView, UpdateViewModel
from .update_stage import UpdateStage

log = logging.getLogger(__name__)


class QtUpdateHost(QObject):
    """The member's UpdateHost on the Qt event loop of the thread that creates it."""

    _posted = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # A bound method of an object on the GUI thread: an emit from a worker thread is
        # queued onto the GUI thread, an emit from the GUI thread runs at once.
        self._posted.connect(self._run)

    def call_later(self, seconds: float, callback: Callable[[], None]) -> Callable[[], None]:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.timeout.connect(timer.deleteLater)
        timer.start(round(seconds * 1000))

        def cancel() -> None:
            if shiboken6.isValid(timer):
                timer.stop()
                timer.deleteLater()

        return cancel

    def run_in_background[T](self, work: Callable[[], T], on_done: Callable[[T], None],
                             on_error: Callable[[Exception], None]) -> None:
        def run() -> None:
            try:
                result = work()
            except Exception as error:
                # partial binds the error now: the except name is unbound after the block.
                self.post(functools.partial(on_error, error))
                return
            self.post(functools.partial(on_done, result))

        threading.Thread(target=run, name="update-worker", daemon=True).start()

    def post(self, callback: Callable[[], None]) -> None:
        self._posted.emit(callback)

    def _run(self, callback: Callable[[], None]) -> None:
        callback()


class Updates(QObject):
    """What the tray and Settings see of the updater: view model, actions, balloon and quit hook."""

    changed = Signal()
    balloon = Signal(str, str)
    refused = Signal(str)

    owner = "ludekvodicka"
    repository = "DesktopAiAssistant"
    _manager: UpdateManager
    _busy: Callable[[], bool]
    _notified: Path
    _relaunch_args: Callable[[], list[str]]
    _status: UpdateStatus
    _view: UpdateViewModel

    def __init__(self, manager: UpdateManager, busy: Callable[[], bool], notified: Path,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._busy = busy
        self._notified = notified
        self._relaunch_args = lambda: []
        self._status = manager.status
        self._view = UpdateView.describe(manager.status)
        manager.subscribe(self._on_status)

    @staticmethod
    def create(parent: QObject, busy: Callable[[], bool]) -> "Updates":
        """The updater with this application's facts; off in a source run."""
        frozen = getattr(sys, "frozen", False)
        target = UpdateTargetFolder(
            Path(sys.executable).parent, "DesktopAiAssistant-{version}-win-x64.zip",
            "DesktopAiAssistant", "DesktopAiAssistant.exe", "DesktopAiHost.exe") if frozen else None
        root = data_dir() / "updates"
        transport = UpdateTransport(f"DesktopAiAssistant/{__version__}")
        facts = UpdateRuntimeFacts(frozen, sys.platform, target)
        manager = UpdateManager(
            running=__version__,
            resolution=UpdateRuntime.resolve(facts, UpdateRuntime.writable),
            target=target,
            host=QtUpdateHost(parent),
            feed=UpdateFeedGithub(Updates.owner, Updates.repository, transport),
            stager=UpdateStager(transport, root, UpdateStage.prepare),
            installer=UpdateInstaller(root),
            release_page=Updates.release_page,
            on_quit=QApplication.quit,
        )
        return Updates(manager, busy, data_dir() / "update-notified.txt", parent)

    @staticmethod
    def release_page(version: str | None) -> str:
        base = f"https://github.com/{Updates.owner}/{Updates.repository}/releases"
        return f"{base}/tag/v{version}" if version else f"{base}/latest"

    @staticmethod
    def tray_entry(status: UpdateStatus) -> tuple[str, bool, UpdateAction | None]:
        """Text, enabled state and click action of the tray menu item."""
        match status.state:
            case UpdateOff():
                return "", False, None
            case UpdateIdle() | UpdateCurrent() | UpdateFailed():
                return "Check for updates", True, "check"
            case UpdateAvailable(release=release):
                action: UpdateAction = "open_release" if status.release_page else "check"
                return f"Version {release.version} available", True, action
            case UpdateChecking():
                return "Checking for updates", False, None
            case UpdateDownloading(release=release, percent=percent):
                return f"Downloading {release.version} ({int(percent + 0.5)}%)", False, None
            case UpdateReady(release=release):
                return f"Restart to install {release.version}", True, "install"
            case UpdateInstalling():
                return "Restarting to install", False, None
            case _:
                raise ValueError(f"Unknown update state: {status.state!r}")

    def set_relaunch_args(self, provider: Callable[[], list[str]]) -> None:
        """Arguments for the relaunched build after Restart and install, asked at click time."""
        self._relaunch_args = provider

    def start(self) -> None:
        self._manager.start()

    @Property(str, notify=changed)
    def text(self) -> str:
        return self._view.text

    @Property(str, notify=changed)
    def detail(self) -> str:
        return self._view.detail or ""

    @Property(str, notify=changed)
    def tone(self) -> str:
        return self._view.tone

    @Property(str, notify=changed)
    def notes(self) -> str:
        release = self._view.release
        return (release.notes or "") if release is not None else ""

    @Property("QVariantList", notify=changed)
    def actions(self) -> list[str]:
        return list(self._view.actions)

    @Property(str, notify=changed)
    def trayText(self) -> str:
        return Updates.tray_entry(self._status)[0]

    @Property(bool, notify=changed)
    def trayEnabled(self) -> bool:
        return Updates.tray_entry(self._status)[1]

    @Property(bool, notify=changed)
    def trayVisible(self) -> bool:
        return not isinstance(self._status.state, UpdateOff)

    @Slot()
    def check(self) -> None:
        self._manager.check()

    @Slot()
    def install(self) -> None:
        if self._busy():
            self.refused.emit("Stop the running action before installing the update.")
            return
        self._manager.install(tuple(self._relaunch_args()))

    @Slot()
    def openReleasePage(self) -> None:
        url = self._manager.release_page_url()
        if url is not None:
            QDesktopServices.openUrl(QUrl(url))

    @Slot()
    def trayActivate(self) -> None:
        action = Updates.tray_entry(self._status)[2]
        match action:
            case "check":
                self.check()
            case "install":
                self.install()
            case "open_release":
                self.openReleasePage()
            case None:
                return
            case _:
                raise ValueError(f"Unknown update action: {action}")

    def quit(self, session_ending: bool, relaunch: list[str] | None) -> bool:
        """From aboutToQuit: True when the helper will start the application again.

        A ready update installs on a normal quit; relaunch is None for a plain quit and the
        restart arguments for Restart app. Nothing installs while the OS session ends.
        """
        launched = False if session_ending else self._manager.install_on_quit(
            None if relaunch is None else tuple(relaunch))
        self._manager.stop()
        return launched and relaunch is not None

    def _on_status(self, status: UpdateStatus) -> None:
        self._status = status
        self._view = UpdateView.describe(status)
        if isinstance(status.state, UpdateReady):
            self._notify_once(status.state.release.version)
        self.changed.emit()

    def _notify_once(self, version: str) -> None:
        # A restart that reuses the staged copy reaches ready again: one balloon per release.
        try:
            notified = self._notified.read_text("utf-8").strip()
        except OSError:
            notified = None
        if notified == version:
            return
        try:
            self._notified.write_text(version, "utf-8")
        except OSError as error:
            log.warning("Could not remember the update notice: %s", error)
        self.balloon.emit("Update ready",
                          f"Version {version} installs on restart or on the next quit.")
