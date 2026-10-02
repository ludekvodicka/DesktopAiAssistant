import dataclasses
import logging
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from typing import Literal

from .const import UpdateConst
from .errors import UpdateError
from .feed import UpdateAsset, UpdateCandidate, UpdateFeedGithub
from .host import UpdateHost
from .installer import UpdateInstaller
from .manifest import UpdateOutcome
from .runtime import UpdateResolution, UpdateTarget
from .stager import UpdateStaged, UpdateStager
from .status import (
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
    UpdateState,
    UpdateStatus,
)
from .version import UpdateVersion

log = logging.getLogger(__name__)

type UpdateTrigger = Literal["background", "manual"]


class UpdateProgress:
    """Worker-side download meter; publishes at most every progress interval."""

    _total: int
    _clock: Callable[[], float]
    _publish: Callable[[tuple[float, int, int, float]], None]
    _started: float
    _published: float

    def __init__(self, total: int, clock: Callable[[], float],
                 publish: Callable[[tuple[float, int, int, float]], None]) -> None:
        self._total = total
        self._clock = clock
        self._publish = publish
        self._started = clock()
        self._published = float("-inf")

    def update(self, transferred: int) -> None:
        now = self._clock()
        interval = UpdateConst.progress_interval_seconds
        if transferred < self._total and now - self._published < interval:
            return
        self._published = now
        elapsed = now - self._started
        percent = transferred * 100.0 / self._total if self._total else 0.0
        speed = transferred / elapsed if elapsed > 0 else 0.0
        self._publish((percent, transferred, self._total, speed))


class UpdateManager:
    """Single-threaded state machine: every method and callback runs on the host thread."""

    _target: UpdateTarget | None
    _host: UpdateHost
    _feed: UpdateFeedGithub
    _stager: UpdateStager
    _installer: UpdateInstaller
    _release_page: Callable[[str | None], str] | None
    _on_quit: Callable[[], None]
    _clock: Callable[[], float]
    _status: UpdateStatus
    _listeners: list[Callable[[UpdateStatus], None]]
    _trigger: UpdateTrigger
    _cancel_timer: Callable[[], None] | None
    _staged: UpdateStaged | None
    _stopped: bool

    def __init__(self, *, running: str, resolution: UpdateResolution, target: UpdateTarget | None,
                 host: UpdateHost, feed: UpdateFeedGithub, stager: UpdateStager,
                 installer: UpdateInstaller, release_page: Callable[[str | None], str] | None,
                 on_quit: Callable[[], None], clock: Callable[[], float] = time.time) -> None:
        self._target = target
        self._host = host
        self._feed = feed
        self._stager = stager
        self._installer = installer
        self._release_page = release_page
        self._on_quit = on_quit
        self._clock = clock
        initial: UpdateState = (UpdateOff(resolution.reason) if resolution.mode == "off"
                                else UpdateIdle())
        self._status = UpdateStatus(running, resolution.mode, release_page is not None, initial)
        self._listeners = []
        self._trigger = "background"
        self._cancel_timer = None
        self._staged = None
        self._stopped = False

    @property
    def status(self) -> UpdateStatus:
        return self._status

    def subscribe(self, listener: Callable[[UpdateStatus], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def start(self) -> None:
        if self._status.mode == "off":
            return
        running, target = self._status.running, self._target
        self._host.run_in_background(lambda: self._installer.take_outcome(running, target),
                                     self._apply_outcome, self._cleanup_failed)
        self._schedule(UpdateConst.initial_delay_seconds)

    def stop(self) -> None:
        self._stopped = True
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    def check(self) -> None:
        self._check("manual")

    def install(self, relaunch_args: tuple[str, ...] = ()) -> None:
        state = self._status.state
        if not isinstance(state, UpdateReady):
            return
        self._set(UpdateInstalling(state.release))
        # A short delay lets the UI paint "Restarting to install" before the windows close.
        self._host.call_later(UpdateConst.install_paint_seconds,
                              lambda: self._launch(state.release, relaunch_args))

    def install_on_quit(self, relaunch_args: tuple[str, ...] | None = None) -> bool:
        """Starts the helper for a ready update while the app quits; None means no relaunch."""
        state = self._status.state
        if not isinstance(state, UpdateReady):
            return False
        staged, target = self._ready_parts()
        try:
            self._installer.launch(staged, target, relaunch=relaunch_args is not None,
                                   relaunch_args=relaunch_args or ())
        except OSError as error:
            log.warning("Install on quit could not start: %s", error)
            return False
        self._set(UpdateInstalling(state.release))
        return True

    def release_page_url(self) -> str | None:
        if self._release_page is None:
            return None
        url = self._release_page(UpdateManager._release_of(self._status.state))
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in UpdateConst.allowed_hosts:
            log.warning("Refusing release page outside the allowed hosts: %s", url)
            return None
        return url

    @staticmethod
    def message(error: Exception) -> str:
        match error:
            case UpdateError():
                return str(error)
            case TimeoutError():
                return "The update server did not answer in time."
            case urllib.error.URLError(reason=reason):
                return f"The update server could not be reached: {reason}"
            case _:
                return str(error) or type(error).__name__

    def _check(self, trigger: UpdateTrigger) -> None:
        previous = self._status.state
        match previous:
            case UpdateChecking():
                # A manual check during a background check takes it over, so its failure shows.
                if trigger == "manual":
                    self._trigger = "manual"
                return
            case UpdateOff() | UpdateDownloading() | UpdateReady() | UpdateInstalling():
                return
            case UpdateIdle() | UpdateCurrent() | UpdateAvailable() | UpdateFailed():
                pass
            case _:
                raise ValueError(f"Unknown update state: {previous!r}")
        self._trigger = trigger
        self._set(UpdateChecking())
        self._host.run_in_background(self._feed.latest, self._checked,
                                     lambda error: self._check_failed(previous, error))

    def _checked(self, candidate: UpdateCandidate | None) -> None:
        self._schedule(UpdateConst.interval_seconds)
        if candidate is None or not UpdateVersion.is_newer(candidate.release.version,
                                                           self._status.running):
            self._set(UpdateCurrent(self._clock()))
            return
        target = self._target
        asset = self._asset(candidate)
        match self._status.mode:
            case "notify":
                self._set(UpdateAvailable(candidate.release))
            case "automatic" if asset is None or target is None:
                # No installable asset or no SHA256SUMS.txt: the release page is still useful.
                self._set(UpdateAvailable(candidate.release))
            case "automatic":
                self._download(candidate, asset, target)
            case "off":
                raise ValueError("An off build never checks for updates")
            case _:
                raise ValueError(f"Unknown update mode: {self._status.mode}")

    def _check_failed(self, previous: UpdateState, error: Exception) -> None:
        self._schedule(UpdateConst.interval_seconds)
        match self._trigger:
            case "background":
                # Offline, rate limited or 5xx is no update failure: the UI keeps what it showed.
                log.info("Background update check failed: %s", error)
                self._set(previous)
            case "manual":
                self._set(UpdateFailed(UpdateManager.message(error), None))
            case _:
                raise ValueError(f"Unknown check trigger: {self._trigger}")

    def _asset(self, candidate: UpdateCandidate) -> UpdateAsset | None:
        if self._target is None or candidate.asset(UpdateConst.checksums_asset) is None:
            return None
        return candidate.asset(self._target.asset_pattern.format(version=candidate.release.version))

    def _download(self, candidate: UpdateCandidate, asset: UpdateAsset,
                  target: UpdateTarget) -> None:
        release = candidate.release
        self._set(UpdateDownloading(release, 0.0, 0, asset.size, 0.0))
        meter = UpdateProgress(
            asset.size, self._clock,
            lambda numbers: self._host.post(lambda: self._progress(release, numbers)))
        self._host.run_in_background(
            lambda: self._stager.stage(candidate, asset, target, meter.update,
                                       lambda: self._stopped),
            lambda staged: self._staged_ready(release, staged),
            lambda error: self._set(UpdateFailed(UpdateManager.message(error), release)))

    def _progress(self, release: UpdateRelease, numbers: tuple[float, int, int, float]) -> None:
        state = self._status.state
        if not isinstance(state, UpdateDownloading) or state.release != release:
            return
        self._set(UpdateDownloading(release, *numbers))

    def _staged_ready(self, release: UpdateRelease, staged: UpdateStaged) -> None:
        self._staged = staged
        self._set(UpdateReady(release))

    def _launch(self, release: UpdateRelease, relaunch_args: tuple[str, ...]) -> None:
        staged, target = self._ready_parts()
        try:
            self._installer.launch(staged, target, relaunch=True, relaunch_args=relaunch_args)
        except OSError as error:
            self._set(UpdateFailed(f"The installer could not start: {error}", release))
            return
        # The helper waits for this process to exit before it swaps the files.
        self._on_quit()

    def _ready_parts(self) -> tuple[UpdateStaged, UpdateTarget]:
        if self._staged is None or self._target is None:
            raise ValueError("A ready update has no staged files or no target")
        return self._staged, self._target

    def _apply_outcome(self, outcome: UpdateOutcome | None) -> None:
        if outcome is None or outcome.installed:
            return
        if not isinstance(self._status.state, UpdateIdle):
            log.info("Previous update failed: %s", outcome.message)
            return
        release = (UpdateRelease(outcome.version, None, None, None)
                   if outcome.version else None)
        self._set(UpdateFailed(outcome.message or "The previous update did not finish.", release))

    def _cleanup_failed(self, error: Exception) -> None:
        log.warning("Reading the previous update outcome failed: %s", error)

    def _schedule(self, seconds: float) -> None:
        if self._cancel_timer is not None:
            self._cancel_timer()
        self._cancel_timer = None
        if self._stopped:
            return
        self._cancel_timer = self._host.call_later(seconds, self._timer_fired)

    def _timer_fired(self) -> None:
        # Armed before the check so a skipped check (downloading, ready) still keeps the cycle.
        self._schedule(UpdateConst.interval_seconds)
        self._check("background")

    def _set(self, state: UpdateState) -> None:
        self._status = dataclasses.replace(self._status, state=state)
        # After stop() the app is shutting down; its widgets may already be gone.
        if self._stopped:
            return
        for listener in list(self._listeners):
            listener(self._status)

    @staticmethod
    def _release_of(state: UpdateState) -> str | None:
        match state:
            case UpdateOff() | UpdateIdle() | UpdateChecking() | UpdateCurrent():
                return None
            case (UpdateAvailable(release=release) | UpdateDownloading(release=release)
                  | UpdateReady(release=release) | UpdateInstalling(release=release)):
                return release.version
            case UpdateFailed(release=release):
                return release.version if release is not None else None
            case _:
                raise ValueError(f"Unknown update state: {state!r}")
