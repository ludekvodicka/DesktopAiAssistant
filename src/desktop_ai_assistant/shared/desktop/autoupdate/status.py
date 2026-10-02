from dataclasses import dataclass
from typing import Literal

type UpdateMode = Literal["automatic", "notify", "off"]


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    name: str | None
    date: str | None
    notes: str | None


@dataclass(frozen=True)
class UpdateOff:
    reason: str


@dataclass(frozen=True)
class UpdateIdle:
    pass


@dataclass(frozen=True)
class UpdateChecking:
    pass


@dataclass(frozen=True)
class UpdateCurrent:
    checked_at: float


@dataclass(frozen=True)
class UpdateAvailable:
    release: UpdateRelease


@dataclass(frozen=True)
class UpdateDownloading:
    release: UpdateRelease
    percent: float
    transferred: int
    total: int
    bytes_per_second: float


@dataclass(frozen=True)
class UpdateReady:
    release: UpdateRelease


@dataclass(frozen=True)
class UpdateInstalling:
    release: UpdateRelease


@dataclass(frozen=True)
class UpdateFailed:
    message: str
    release: UpdateRelease | None


type UpdateState = (
    UpdateOff
    | UpdateIdle
    | UpdateChecking
    | UpdateCurrent
    | UpdateAvailable
    | UpdateDownloading
    | UpdateReady
    | UpdateInstalling
    | UpdateFailed
)


@dataclass(frozen=True)
class UpdateStatus:
    running: str
    mode: UpdateMode
    # Only whether a release page exists; the URL stays in the manager.
    release_page: bool
    state: UpdateState
