from collections.abc import Callable
from pathlib import Path

import pytest

from ..errors import UpdateHttpError
from ..feed import UpdateFeedGithub
from ..installer import UpdateInstaller
from ..manager import UpdateManager, UpdateProgress
from ..manifest import UpdateOutcome
from ..runtime import UpdateResolution, UpdateTargetFile
from ..stager import UpdateStaged, UpdateStager
from ..status import (
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
from ..view import UpdateView
from .support import (
    FILE_PATTERN,
    LATEST,
    OWNER,
    REPO,
    FakeTransport,
    ManualHost,
    file_urls,
    release_json,
    with_sums,
)

RUNNING = "1.1.0"
NEW = "1.2.0"
NEW_FILE = FILE_PATTERN.format(version=NEW)
RELEASE = UpdateRelease(NEW, f"Demo {NEW}", "2026-01-02T03:04:05Z", "Fixes.")
FILES = with_sums({NEW_FILE: b"new build bytes"})


class RecordingInstaller(UpdateInstaller):
    def __init__(self, root: Path, outcome: UpdateOutcome | None = None,
                 error: OSError | None = None) -> None:
        super().__init__(root)
        self.outcome = outcome
        self.error = error
        self.launches: list[tuple[UpdateStaged, object, bool, tuple[str, ...]]] = []
        self.outcome_calls = 0

    def launch(self, staged, target, relaunch, relaunch_args) -> None:
        if self.error is not None:
            raise self.error
        self.launches.append((staged, target, relaunch, relaunch_args))

    def take_outcome(self, running, target) -> UpdateOutcome | None:
        self.outcome_calls += 1
        return self.outcome


class RecordingStager(UpdateStager):
    def __init__(self, transport: FakeTransport, root: Path) -> None:
        super().__init__(transport, root)
        self.calls = 0
        self.cancelled: Callable[[], bool] | None = None

    def stage(self, candidate, asset, target, progress, cancelled) -> UpdateStaged:
        self.calls += 1
        self.cancelled = cancelled
        return super().stage(candidate, asset, target, progress, cancelled)


class Rig:
    def __init__(self, tmp_path: Path, responses: dict[str, object], files: dict[str, bytes],
                 mode="automatic", installer: RecordingInstaller | None = None,
                 release_page=lambda version: f"https://github.com/{OWNER}/{REPO}/releases/"
                 + (f"tag/v{version}" if version else "latest")) -> None:
        self.host = ManualHost()
        self.transport = FakeTransport(responses, files)
        self.installer = installer or RecordingInstaller(tmp_path / "updates")
        self.stager = RecordingStager(self.transport, tmp_path / "updates")
        self.target = UpdateTargetFile(tmp_path / "app" / "Demo-App.exe", FILE_PATTERN,
                                       onefile_parent=False)
        self.quits = 0
        self.manager = UpdateManager(
            running=RUNNING, resolution=UpdateResolution(mode, "Test reason."),
            target=self.target, host=self.host,
            feed=UpdateFeedGithub(OWNER, REPO, self.transport), stager=self.stager,
            installer=self.installer, release_page=release_page, on_quit=self.quit,
            clock=self.host.clock)
        self.seen: list[UpdateStatus] = []
        self.manager.subscribe(self.seen.append)

    def quit(self) -> None:
        self.quits += 1

    def started(self) -> "Rig":
        self.manager.start()
        self.host.run_jobs()
        return self

    def background_check(self) -> None:
        self.host.advance(45)
        self.host.run_jobs()

    @property
    def state(self):
        return self.manager.status.state

    def checks(self) -> int:
        return self.transport.calls.count(LATEST)


def published(tmp_path, version=NEW, files=FILES, **options) -> Rig:
    return Rig(tmp_path, {LATEST: release_json(version, files)}, file_urls(version, files),
               **options)


def ready(tmp_path, **options) -> Rig:
    rig = published(tmp_path, **options).started()
    rig.background_check()
    assert rig.state == UpdateReady(RELEASE)
    return rig


def test_first_check_after_45_s_then_120_min_after_each_completed_check(tmp_path):
    rig = published(tmp_path, version=RUNNING, files=with_sums({})).started()
    rig.host.advance(44.9)
    rig.host.run_jobs()
    assert rig.checks() == 0
    rig.host.advance(0.1)
    rig.host.run_jobs()
    assert rig.checks() == 1
    assert rig.state == UpdateCurrent(45.0)
    rig.host.advance(120 * 60 - 1)
    rig.host.run_jobs()
    assert rig.checks() == 1
    rig.host.advance(1)
    rig.host.run_jobs()
    assert rig.checks() == 2


def test_manual_check_rearms_the_interval(tmp_path):
    rig = published(tmp_path, version=RUNNING, files=with_sums({})).started()
    rig.host.advance(30)
    rig.manager.check()
    rig.host.run_jobs()
    assert rig.checks() == 1
    rig.host.advance(120 * 60 - 1)
    rig.host.run_jobs()
    assert rig.checks() == 1
    rig.host.advance(1)
    rig.host.run_jobs()
    assert rig.checks() == 2


def test_background_failure_keeps_the_previous_state(tmp_path):
    rig = Rig(tmp_path, {LATEST: UpdateHttpError(403, LATEST)}, {}).started()
    rig.background_check()
    assert rig.state == UpdateIdle()
    assert UpdateChecking() in [status.state for status in rig.seen]


def test_background_failure_after_a_failure_keeps_the_failure(tmp_path):
    rig = Rig(tmp_path, {LATEST: UpdateHttpError(500, LATEST)}, {}).started()
    rig.manager.check()
    rig.host.run_jobs()
    rig.host.advance(120 * 60)
    rig.host.run_jobs()
    assert rig.state == UpdateFailed("The update server answered HTTP 500.", None)


def test_manual_failure_shows_failed_with_check_again(tmp_path):
    rig = Rig(tmp_path, {LATEST: UpdateHttpError(403, LATEST)}, {}).started()
    rig.manager.check()
    rig.host.run_jobs()
    assert rig.state == UpdateFailed("The update server answered HTTP 403.", None)
    view = UpdateView.describe(rig.manager.status)
    assert view.actions == ("check", "open_release")


def test_offline_message_is_readable(tmp_path):
    rig = Rig(tmp_path, {LATEST: OSError("network down")}, {}).started()
    rig.manager.check()
    rig.host.run_jobs()
    assert rig.state == UpdateFailed("network down", None)


def test_manual_check_during_a_background_check_takes_it_over(tmp_path):
    rig = Rig(tmp_path, {LATEST: UpdateHttpError(403, LATEST)}, {}).started()
    rig.host.advance(45)
    assert rig.state == UpdateChecking()
    rig.manager.check()
    assert len(rig.host.jobs) == 1
    rig.host.run_jobs()
    assert isinstance(rig.state, UpdateFailed)


def test_notify_mode_shows_available(tmp_path):
    rig = published(tmp_path, mode="notify").started()
    rig.background_check()
    assert rig.state == UpdateAvailable(RELEASE)
    assert rig.stager.calls == 0


def test_automatic_mode_downloads_then_is_ready(tmp_path):
    rig = published(tmp_path).started()
    rig.background_check()
    states = [status.state for status in rig.seen]
    downloading = [state for state in states if isinstance(state, UpdateDownloading)]
    assert downloading[0] == UpdateDownloading(RELEASE, 0.0, 0, len(b"new build bytes"), 0.0)
    assert downloading[-1].percent == 100.0
    # The fake clock stands still, so only the first and the final progress are published.
    assert len(downloading) == 3
    assert states[-1] == UpdateReady(RELEASE)
    assert UpdateView.describe(rig.manager.status).actions == ("install", "open_release")


def test_older_or_equal_release_is_current(tmp_path):
    rig = published(tmp_path, version=RUNNING).started()
    rig.background_check()
    assert rig.state == UpdateCurrent(45.0)


def test_no_published_release_is_current(tmp_path):
    rig = Rig(tmp_path, {LATEST: UpdateHttpError(404, LATEST)}, {}).started()
    rig.manager.check()
    rig.host.run_jobs()
    assert rig.state == UpdateCurrent(0.0)


@pytest.mark.parametrize("files", [
    with_sums({"Other-1.2.0.zip": b"x"}),
    {NEW_FILE: b"new build bytes"},
])
def test_release_without_the_asset_or_sums_is_available(tmp_path, files):
    rig = published(tmp_path, files=files).started()
    rig.background_check()
    assert rig.state == UpdateAvailable(RELEASE)
    assert rig.stager.calls == 0


def test_failed_download_shows_failed_with_the_release(tmp_path):
    bad = {**FILES, NEW_FILE: b"tampered bytes!"}
    rig = Rig(tmp_path, {LATEST: release_json(NEW, FILES)}, file_urls(NEW, bad)).started()
    rig.background_check()
    assert rig.state == UpdateFailed(f"{NEW_FILE} does not match SHA256SUMS.txt.", RELEASE)


def test_no_check_while_ready(tmp_path):
    rig = ready(tmp_path)
    rig.manager.check()
    rig.host.advance(120 * 60)
    rig.host.run_jobs()
    assert rig.checks() == 1
    assert rig.state == UpdateReady(RELEASE)


def test_install_paints_then_launches_then_quits(tmp_path):
    rig = ready(tmp_path)
    rig.manager.install(("--settings",))
    assert rig.state == UpdateInstalling(RELEASE)
    assert rig.installer.launches == []
    rig.host.advance(0.25)
    assert len(rig.installer.launches) == 1
    staged, target, relaunch, args = rig.installer.launches[0]
    assert (staged.version, target, relaunch, args) == (NEW, rig.target, True, ("--settings",))
    assert rig.quits == 1
    assert not rig.manager.install_on_quit()


def test_install_spawn_failure_shows_failed_and_keeps_running(tmp_path):
    rig = ready(tmp_path, installer=RecordingInstaller(tmp_path / "updates",
                                                       error=OSError("blocked")))
    rig.manager.install()
    rig.host.advance(0.25)
    assert rig.state == UpdateFailed("The installer could not start: blocked", RELEASE)
    assert rig.quits == 0
    assert not rig.manager.install_on_quit()


def test_install_outside_ready_does_nothing(tmp_path):
    rig = published(tmp_path).started()
    rig.manager.install()
    rig.host.advance(1)
    assert rig.state == UpdateIdle()
    assert rig.installer.launches == []


def test_install_on_quit_without_relaunch(tmp_path):
    rig = ready(tmp_path)
    assert rig.manager.install_on_quit()
    _staged, _target, relaunch, args = rig.installer.launches[0]
    assert (relaunch, args) == (False, ())
    assert rig.quits == 0
    assert not rig.manager.install_on_quit()


def test_install_on_quit_with_relaunch(tmp_path):
    rig = ready(tmp_path)
    assert rig.manager.install_on_quit(("--settings",))
    _staged, _target, relaunch, args = rig.installer.launches[0]
    assert (relaunch, args) == (True, ("--settings",))


def test_install_on_quit_spawn_failure_returns_false(tmp_path):
    rig = ready(tmp_path, installer=RecordingInstaller(tmp_path / "updates",
                                                       error=OSError("blocked")))
    assert not rig.manager.install_on_quit()
    assert rig.state == UpdateReady(RELEASE)


def test_install_on_quit_outside_ready_returns_false(tmp_path):
    rig = published(tmp_path, mode="notify").started()
    assert not rig.manager.install_on_quit()
    rig.background_check()
    assert rig.state == UpdateAvailable(RELEASE)
    assert not rig.manager.install_on_quit()
    assert rig.installer.launches == []


def test_startup_failed_outcome_with_its_version(tmp_path):
    outcome = UpdateOutcome(False, NEW, "The update could not replace the program: locked")
    rig = published(tmp_path, installer=RecordingInstaller(tmp_path / "u", outcome)).started()
    assert rig.state == UpdateFailed(outcome.message, UpdateRelease(NEW, None, None, None))
    assert rig.manager.release_page_url() == (
        f"https://github.com/{OWNER}/{REPO}/releases/tag/v{NEW}")


def test_startup_failed_outcome_without_a_version(tmp_path):
    outcome = UpdateOutcome(False, None, None)
    rig = published(tmp_path, installer=RecordingInstaller(tmp_path / "u", outcome)).started()
    assert rig.state == UpdateFailed("The previous update did not finish.", None)
    assert rig.manager.release_page_url() == f"https://github.com/{OWNER}/{REPO}/releases/latest"


def test_startup_success_outcome_keeps_idle(tmp_path):
    outcome = UpdateOutcome(True, RUNNING, None)
    rig = published(tmp_path, installer=RecordingInstaller(tmp_path / "u", outcome)).started()
    assert rig.state == UpdateIdle()


def test_off_mode_never_touches_transport_stager_or_installer(tmp_path):
    rig = published(tmp_path, mode="off")
    assert rig.state == UpdateOff("Test reason.")
    rig.started()
    rig.manager.check()
    rig.host.advance(10 * 3600)
    rig.host.run_jobs()
    assert rig.manager.install_on_quit() is False
    assert (rig.transport.calls, rig.stager.calls, rig.installer.outcome_calls) == ([], 0, 0)
    assert rig.host.timers == []


def test_stop_cancels_the_timers(tmp_path):
    rig = published(tmp_path).started()
    rig.manager.stop()
    rig.host.advance(10 * 3600)
    rig.host.run_jobs()
    assert rig.checks() == 0


def test_stop_cancels_a_running_download(tmp_path):
    rig = published(tmp_path).started()
    rig.host.advance(45)
    rig.host.run_next()
    assert isinstance(rig.state, UpdateDownloading)
    rig.host.run_next()
    assert rig.stager.cancelled is not None
    assert not rig.stager.cancelled()
    rig.manager.stop()
    assert rig.stager.cancelled()
    assert rig.host.timers == []


def test_no_notifications_after_stop(tmp_path):
    rig = published(tmp_path).started()
    rig.host.advance(45)
    rig.host.run_next()
    seen: list[UpdateStatus] = []
    rig.manager.subscribe(seen.append)
    rig.manager.stop()
    rig.host.run_jobs()
    assert seen == []


def test_release_page_must_be_https_on_an_allowed_host(tmp_path):
    rig = published(tmp_path, release_page=lambda _version: "http://github.com/x")
    assert rig.manager.release_page_url() is None
    rig = published(tmp_path, release_page=lambda _version: "https://example.com/x")
    assert rig.manager.release_page_url() is None
    rig = published(tmp_path, release_page=None)
    assert rig.manager.release_page_url() is None
    assert UpdateView.describe(rig.manager.status).actions == ("check",)


def test_unsubscribe_stops_notifications(tmp_path):
    rig = published(tmp_path)
    seen: list[UpdateStatus] = []
    unsubscribe = rig.manager.subscribe(seen.append)
    unsubscribe()
    rig.manager.check()
    assert seen == []


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_progress_is_throttled_and_reports_speed():
    clock = Clock()
    published_numbers: list[tuple[float, int, int, float]] = []
    meter = UpdateProgress(1000, clock, published_numbers.append)
    clock.now = 100.1
    meter.update(100)
    clock.now = 100.2
    meter.update(200)
    clock.now = 100.36
    meter.update(300)
    clock.now = 100.4
    meter.update(1000)
    assert [numbers[1] for numbers in published_numbers] == [100, 300, 1000]
    percent, transferred, total, speed = published_numbers[-1]
    assert (percent, transferred, total) == (100.0, 1000, 1000)
    assert speed == pytest.approx(2500.0)
