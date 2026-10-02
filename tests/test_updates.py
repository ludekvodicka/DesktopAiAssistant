"""The application's side of self-update: Qt host, bridge, tray entry, stage hook and helper entry.

The update logic itself is tested with the shared member; these tests cover what this
application adds around it.
"""

import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
import winreg
import pytest
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication
import desktop_ai_assistant
from desktop_ai_assistant import __version__
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.controller import Controller
from desktop_ai_assistant.install_registration import InstallRegistration
from desktop_ai_assistant.shared.desktop.autoupdate.feed import UpdateFeedGithub
from desktop_ai_assistant.shared.desktop.autoupdate.installer import UpdateInstaller
from desktop_ai_assistant.shared.desktop.autoupdate.manager import UpdateManager
from desktop_ai_assistant.shared.desktop.autoupdate.runtime import UpdateResolution, UpdateTargetFolder
from desktop_ai_assistant.shared.desktop.autoupdate.stager import UpdateStager
from desktop_ai_assistant.shared.desktop.autoupdate.status import (
    UpdateAvailable,
    UpdateChecking,
    UpdateCurrent,
    UpdateDownloading,
    UpdateFailed,
    UpdateIdle,
    UpdateInstalling,
    UpdateOff,
    UpdateReady,
    UpdateRelease,
    UpdateStatus,
)
from desktop_ai_assistant.shared.desktop.autoupdate.tests.support import (
    LATEST,
    OWNER,
    REPO,
    ZIP_PATTERN,
    FakeTransport,
    ManualHost,
    file_urls,
    release_json,
    with_sums,
    write_tree,
    zip_bytes,
)
from desktop_ai_assistant.shared.desktop.autoupdate.transport import UpdateTransport
from desktop_ai_assistant.update_stage import UpdateStage
from desktop_ai_assistant.updates import QtUpdateHost, Updates
from test_settings_layout import named_item

ROOT = Path(__file__).resolve().parents[1]
NEW = "9.9.0"
RELEASE = UpdateRelease(NEW, None, None, None)
TOP = "DemoApp"
PACKAGE = zip_bytes({
    f"{TOP}/DemoApp.exe": b"new app",
    f"{TOP}/DemoHost.exe": b"new helper",
    f"{TOP}/browser-extension/manifest.json": json.dumps({"name": "demo", "key": "PUBLIC"}).encode(),
})
FILES = with_sums({ZIP_PATTERN.format(version=NEW): PACKAGE})


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class RecordingInstaller(UpdateInstaller):
    """Records helper launches instead of starting a process."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.launches: list[tuple[bool, tuple[str, ...]]] = []

    def launch(self, staged, target, relaunch, relaunch_args) -> None:
        self.launches.append((relaunch, relaunch_args))

    def take_outcome(self, running, target):
        return None


def build(tmp_path: Path, app, busy=lambda: False, installed=None, notified=None):
    """Updates around a manager that installs into a folder target, driven by a manual host."""
    host = ManualHost()
    transport = FakeTransport({LATEST: release_json(NEW, FILES)}, file_urls(NEW, FILES))
    program = write_tree(tmp_path / "Programs" / TOP, installed or {f"{TOP}.exe": b"old app"})
    installer = RecordingInstaller(tmp_path / "updates")
    quits: list[bool] = []
    manager = UpdateManager(
        running="1.0.0", resolution=UpdateResolution("automatic", "Packaged Windows build."),
        target=UpdateTargetFolder(program, ZIP_PATTERN, TOP, "DemoApp.exe", "DemoHost.exe"),
        host=host, feed=UpdateFeedGithub(OWNER, REPO, transport),
        stager=UpdateStager(transport, tmp_path / "updates", UpdateStage.prepare),
        installer=installer, release_page=Updates.release_page,
        on_quit=lambda: quits.append(True), clock=host.clock)
    updates = Updates(manager, busy, notified or tmp_path / "update-notified.txt", app)
    return updates, manager, host, installer, quits


def ready(tmp_path: Path, app, **options):
    updates, manager, host, installer, quits = build(tmp_path, app, **options)
    manager.start()
    host.run_jobs()
    host.advance(45)
    host.run_jobs()
    assert isinstance(manager.status.state, UpdateReady)
    return updates, manager, host, installer, quits


def status(state, release_page=True):
    return UpdateStatus("1.0.0", "automatic", release_page, state)


def run_until(app, done, timeout_ms=5000):
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: done() and loop.quit())
    poll.start(10)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    poll.stop()


class TestTrayEntry:
    @pytest.mark.parametrize("state,expected", [
        (UpdateOff("Development run."), ("", False, None)),
        (UpdateIdle(), ("Check for updates", True, "check")),
        (UpdateCurrent(1.0), ("Check for updates", True, "check")),
        (UpdateFailed("offline", None), ("Check for updates", True, "check")),
        (UpdateAvailable(RELEASE), (f"Version {NEW} available", True, "open_release")),
        (UpdateChecking(), ("Checking for updates", False, None)),
        (UpdateDownloading(RELEASE, 41.6, 416, 1000, 10.0), (f"Downloading {NEW} (42%)", False, None)),
        (UpdateReady(RELEASE), (f"Restart to install {NEW}", True, "install")),
        (UpdateInstalling(RELEASE), ("Restarting to install", False, None)),
    ])
    def test_every_state_has_its_entry(self, state, expected):
        assert Updates.tray_entry(status(state)) == expected

    def test_available_without_a_release_page_checks_again(self):
        assert Updates.tray_entry(status(UpdateAvailable(RELEASE), release_page=False)) == (
            f"Version {NEW} available", True, "check")

    def test_an_unknown_state_raises(self):
        with pytest.raises(ValueError, match="Unknown update state"):
            Updates.tray_entry(status(object()))


class TestSourceRun:
    def test_updates_are_off_hidden_and_never_touch_the_network(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))

        def no_network(*args, **kwargs):
            raise AssertionError("a source run must not reach the network")

        for name in ("get_json", "get_text", "download"):
            monkeypatch.setattr(UpdateTransport, name, no_network)
        updates = Updates.create(app, busy=lambda: False)
        updates.start()
        app.processEvents()
        assert updates.text == "Updates off"
        assert updates.tone == "muted"
        assert updates.actions == ["open_release"]
        assert not updates.trayVisible
        assert list(tmp_path.iterdir()) == []

    def test_release_pages_stay_on_the_public_repository(self):
        assert Updates.release_page("1.2.3") == (
            "https://github.com/ludekvodicka/DesktopAiAssistant/releases/tag/v1.2.3")
        assert Updates.release_page(None) == (
            "https://github.com/ludekvodicka/DesktopAiAssistant/releases/latest")


class TestBridge:
    def test_properties_follow_the_manager(self, app, tmp_path):
        updates, manager, host, installer, quits = build(tmp_path, app)
        changes = []
        updates.changed.connect(lambda: changes.append(updates.text))
        assert (updates.text, updates.tone, updates.actions) == ("Version 1.0.0", "muted", ["check"])
        assert (updates.trayText, updates.trayEnabled, updates.trayVisible) == ("Check for updates", True, True)
        manager.start()
        host.run_jobs()
        host.advance(45)
        assert updates.trayText == "Checking for updates" and not updates.trayEnabled
        host.run_jobs()
        assert updates.text == f"Version {NEW} ready"
        assert updates.detail == "Installs on restart or on the next quit."
        assert updates.tone == "ready"
        assert updates.actions == ["install", "open_release"]
        assert updates.notes == "Fixes."
        assert (updates.trayText, updates.trayEnabled) == (f"Restart to install {NEW}", True)
        assert changes[0] == "Checking for updates" and changes[-1] == f"Version {NEW} ready"

    def test_the_staged_folder_carries_installer_files_and_the_extension_identity(self, app, tmp_path):
        installed = {
            f"{TOP}.exe": b"old app", "unins000.exe": b"uninstaller", "unins000.dat": b"file log",
            "browser-extension/manifest.json": json.dumps({"name": "demo"}).encode(),
        }
        ready(tmp_path, app, installed=installed)
        staged = tmp_path / "Programs" / f"{TOP}.staged"
        assert (staged / "unins000.exe").read_bytes() == b"uninstaller"
        assert (staged / "unins000.dat").read_bytes() == b"file log"
        assert "key" not in json.loads((staged / "browser-extension/manifest.json").read_text("utf-8"))

    def test_install_while_busy_is_refused_and_stays_ready(self, app, tmp_path):
        updates, manager, host, installer, quits = ready(tmp_path, app, busy=lambda: True)
        refusals = []
        updates.refused.connect(refusals.append)
        updates.install()
        host.advance(1)
        assert refusals == ["Stop the running action before installing the update."]
        assert isinstance(manager.status.state, UpdateReady)
        assert installer.launches == [] and quits == []

    def test_install_relaunches_with_the_current_arguments_and_quits(self, app, tmp_path):
        updates, manager, host, installer, quits = ready(tmp_path, app)
        updates.set_relaunch_args(lambda: ["--settings"])
        updates.trayActivate()
        assert isinstance(manager.status.state, UpdateInstalling)
        host.advance(1)
        assert installer.launches == [(True, ("--settings",))]
        assert quits == [True]
        assert not updates.quit(False, None)
        assert len(installer.launches) == 1

    def test_the_balloon_fires_once_per_release(self, app, tmp_path):
        balloons = []
        notified = tmp_path / "update-notified.txt"
        # The second run stands for a restart that finds the same release staged again.
        for folder in ("first", "second"):
            updates, manager, host, installer, quits = build(tmp_path / folder, app, notified=notified)
            updates.balloon.connect(lambda title, message: balloons.append((title, message)))
            manager.start()
            host.run_jobs()
            host.advance(45)
            host.run_jobs()
            assert isinstance(manager.status.state, UpdateReady)
        assert balloons == [("Update ready", f"Version {NEW} installs on restart or on the next quit.")]
        assert notified.read_text("utf-8") == NEW


class TestQuit:
    def test_session_end_never_installs(self, app, tmp_path):
        updates, manager, host, installer, quits = ready(tmp_path, app)
        assert not updates.quit(True, None)
        assert not updates.quit(True, ["--settings"])
        assert installer.launches == []

    def test_a_plain_quit_installs_without_relaunch(self, app, tmp_path):
        updates, manager, host, installer, quits = ready(tmp_path, app)
        assert not updates.quit(False, None)
        assert installer.launches == [(False, ())]

    def test_restart_app_goes_through_the_helper(self, app, tmp_path):
        updates, manager, host, installer, quits = ready(tmp_path, app)
        assert updates.quit(False, ["--settings"])
        assert installer.launches == [(True, ("--settings",))]

    def test_without_a_ready_update_the_plain_restart_stays(self, app, tmp_path):
        updates, manager, host, installer, quits = build(tmp_path, app)
        assert not updates.quit(False, [])
        assert installer.launches == []


class TestQtUpdateHost:
    def test_results_and_errors_arrive_on_the_gui_thread(self, app):
        host = QtUpdateHost()
        gui = threading.get_ident()
        seen = {}

        def fail():
            raise ValueError("boom")

        host.run_in_background(
            threading.get_ident,
            lambda worker: seen.update(worker=worker, done=threading.get_ident()),
            lambda error: seen.update(unexpected=error))
        host.run_in_background(fail, lambda result: seen.update(unexpected=result),
                               lambda error: seen.update(error=error, failed=threading.get_ident()))
        run_until(app, lambda: "done" in seen and "failed" in seen)
        assert "unexpected" not in seen
        assert seen["worker"] != gui
        assert seen["done"] == gui and seen["failed"] == gui
        assert str(seen["error"]) == "boom"

    def test_a_cancelled_timer_never_fires(self, app):
        host = QtUpdateHost()
        fired = []
        cancel = host.call_later(0.01, lambda: fired.append("cancelled"))
        host.call_later(0.05, lambda: fired.append("kept"))
        cancel()
        run_until(app, lambda: fired)
        assert fired == ["kept"]
        cancel()


class TestUpdateStage:
    def manifest(self, folder: Path, value: dict) -> Path:
        path = folder / "browser-extension/manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), "utf-8")
        return path

    def test_an_installed_key_is_kept(self, tmp_path):
        staged = self.manifest(tmp_path / "staged", {"name": "new", "key": "NEW"})
        self.manifest(tmp_path / "installed", {"name": "old", "key": "OLD"})
        UpdateStage.prepare(tmp_path / "staged", tmp_path / "installed")
        assert json.loads(staged.read_text("utf-8")) == {"name": "new", "key": "OLD"}

    def test_an_absent_key_stays_absent(self, tmp_path):
        staged = self.manifest(tmp_path / "staged", {"name": "new", "key": "NEW"})
        self.manifest(tmp_path / "installed", {"name": "old"})
        UpdateStage.prepare(tmp_path / "staged", tmp_path / "installed")
        assert json.loads(staged.read_text("utf-8")) == {"name": "new"}

    def test_uninstaller_files_are_copied(self, tmp_path):
        staged = write_tree(tmp_path / "staged", {"App.exe": b"new"})
        write_tree(tmp_path / "installed", {"unins000.exe": b"exe", "unins000.dat": b"dat", "other.dat": b"x"})
        UpdateStage.prepare(staged, tmp_path / "installed")
        assert sorted(path.name for path in staged.iterdir()) == ["App.exe", "unins000.dat", "unins000.exe"]

    def test_a_portable_folder_is_left_alone(self, tmp_path):
        staged = self.manifest(tmp_path / "staged", {"name": "new", "key": "NEW"})
        (tmp_path / "installed").mkdir()
        UpdateStage.prepare(tmp_path / "staged", tmp_path / "installed")
        assert json.loads(staged.read_text("utf-8")) == {"name": "new", "key": "NEW"}
        assert sorted(path.name for path in (tmp_path / "staged").iterdir()) == ["browser-extension"]


class TestInstallRegistration:
    @pytest.fixture
    def key(self):
        name = rf"Software\DesktopAiAssistantTests\{uuid.uuid4().hex}"
        yield name
        for path in (name, name.rsplit("\\", 1)[0]):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass

    def entry(self, key, location):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, "InstallLocation", 0, winreg.REG_SZ, location)
            winreg.SetValueEx(handle, "DisplayVersion", 0, winreg.REG_SZ, "0.1.0")

    def version(self, key):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return winreg.QueryValueEx(handle, "DisplayVersion")[0]

    def test_the_own_entry_gets_the_running_version(self, tmp_path, key):
        # Setup writes the folder with a trailing backslash.
        self.entry(key, str(tmp_path) + "\\")
        assert InstallRegistration.sync(tmp_path, "9.9.0", key)
        assert self.version(key) == "9.9.0"

    def test_a_foreign_entry_is_left_alone(self, tmp_path, key):
        self.entry(key, str(tmp_path / "elsewhere"))
        assert not InstallRegistration.sync(tmp_path, "9.9.0", key)
        assert self.version(key) == "0.1.0"

    def test_a_missing_entry_returns_false(self, tmp_path, key):
        assert not InstallRegistration.sync(tmp_path, "9.9.0", key)

    def test_the_app_id_matches_the_installer_script(self):
        script = (ROOT / "packaging/installer.iss").read_text("ascii")
        match = re.search(r"^AppId=\{(\{[0-9A-F-]{36}\})$", script, re.M)
        assert match and match.group(1) == InstallRegistration.app_id
        assert InstallRegistration.uninstall_key.endswith(InstallRegistration.app_id + "_is1")


class TestSettings:
    def test_the_overview_shows_the_update_group_and_the_sidebar_shows_the_version(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
        config = copy.deepcopy(DEFAULT)
        config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
        (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
        backend = Controller(app)
        backend.monitor.stop()
        updates = Updates.create(app, busy=lambda: False)
        qml = QQmlApplicationEngine()
        warnings = []
        qml.warnings.connect(lambda items: warnings.extend(str(item) for item in items))
        qml.rootContext().setContextProperty("backend", backend)
        qml.rootContext().setContextProperty("updates", updates)
        qml.load(QUrl.fromLocalFile(str(Path(desktop_ai_assistant.__file__).parent / "qml/Settings.qml")))
        window = qml.rootObjects()[0]
        try:
            window.show()
            for _ in range(12):
                app.processEvents()
                time.sleep(0.01)
            assert named_item(window.contentItem(), "updatePanel").property("title") == "Updates"
            assert named_item(window.contentItem(), "updateText").property("text") == "Updates off"
            assert named_item(window.contentItem(), "updateRelease").property("visible")
            assert not named_item(window.contentItem(), "updateInstall").property("visible")
            indicator = named_item(window.contentItem(), "updateIndicator")
            assert indicator.property("text") == "WINDOWS PREVIEW  " + __version__
            assert not warnings, warnings
        finally:
            backend.close()
            app.removeNativeEventFilter(backend.hotkeys)
            import shiboken6
            shiboken6.delete(qml)


class TestHelperEntry:
    def test_apply_update_exits_before_qt_and_the_native_host(self, tmp_path):
        manifest = tmp_path / "pending.json"
        manifest.write_text("not json", encoding="utf-8")
        probe = (
            "import runpy, sys\n"
            "sys.argv = ['DesktopAiHost.exe', '--apply-update', sys.argv[1]]\n"
            "try:\n"
            "    runpy.run_path('packaging/host_entry.py', run_name='__main__')\n"
            "except SystemExit as stop:\n"
            "    print(stop.code, 'PySide6' in sys.modules, 'desktop_ai_assistant.bridge' in sys.modules)\n"
        )
        result = subprocess.run([sys.executable, "-c", probe, str(manifest)], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        assert result.stdout.split() == ["2", "False", "False"], result.stderr
        assert (tmp_path / "helper.log").is_file()
        assert json.loads((tmp_path / "result.json").read_text("utf-8"))["installed"] is False

    def test_the_host_still_reports_its_version(self):
        result = subprocess.run([sys.executable, "packaging/host_entry.py", "--version"], cwd=ROOT,
                                capture_output=True, text=True, timeout=60)
        assert result.stdout.strip() == __version__, result.stderr
