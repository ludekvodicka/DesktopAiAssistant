from dataclasses import dataclass
from typing import Literal

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
    UpdateStatus,
)

type UpdateTone = Literal["muted", "working", "attention", "ready", "failed"]
type UpdateAction = Literal["check", "install", "open_release"]


@dataclass(frozen=True)
class UpdateViewModel:
    text: str
    detail: str | None
    tone: UpdateTone
    actions: tuple[UpdateAction, ...]
    release: UpdateRelease | None


class UpdateView:
    @staticmethod
    def describe(status: UpdateStatus) -> UpdateViewModel:
        link: tuple[UpdateAction, ...] = ("open_release",) if status.release_page else ()
        match status.state:
            case UpdateOff(reason=reason):
                return UpdateViewModel("Updates off", reason, "muted", link, None)
            case UpdateIdle():
                return UpdateViewModel(f"Version {status.running}", None, "muted", ("check",), None)
            case UpdateChecking():
                return UpdateViewModel("Checking for updates", None, "working", (), None)
            case UpdateCurrent():
                return UpdateViewModel(
                    "Up to date", f"Version {status.running}", "muted", ("check",), None)
            case UpdateAvailable(release=release):
                return UpdateViewModel(
                    f"Version {release.version} available", None, "attention", (*link, "check"),
                    release)
            case UpdateDownloading(release=release, percent=percent):
                # int(x + 0.5) rounds like JavaScript Math.round, which the Electron view uses.
                return UpdateViewModel(
                    f"Downloading {release.version} ({int(percent + 0.5)}%)", None, "working", (),
                    release)
            case UpdateReady(release=release):
                return UpdateViewModel(
                    f"Version {release.version} ready", "Installs on restart or on the next quit.",
                    "ready", ("install", *link), release)
            case UpdateInstalling(release=release):
                return UpdateViewModel("Restarting to install", None, "working", (), release)
            case UpdateFailed(message=message, release=release):
                return UpdateViewModel(
                    "Update failed", message, "failed", ("check", *link), release)
            case _:
                raise ValueError(f"Unknown update state: {status.state!r}")
