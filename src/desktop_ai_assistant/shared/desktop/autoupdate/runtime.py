import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .files import UpdateFiles
from .status import UpdateMode


@dataclass(frozen=True)
class UpdateTargetFile:
    # The running file, replaced in place under its own name.
    path: Path
    # Asset name with a {version} field, for example "Example-{version}-x64.exe".
    asset_pattern: str
    # Windows PyInstaller one-file build: the bootloader parent holds the file as well.
    onefile_parent: bool


@dataclass(frozen=True)
class UpdateTargetFolder:
    # The program folder, swapped as a whole.
    path: Path
    asset_pattern: str
    # The zip's single top folder, stripped while staging.
    top_folder: str
    # Relaunched after the swap, relative to the folder.
    executable: str
    # Self-contained one-file program in the folder that runs the swap.
    helper: str


type UpdateTarget = UpdateTargetFile | UpdateTargetFolder


@dataclass(frozen=True)
class UpdateRuntimeFacts:
    frozen: bool
    platform: str
    target: UpdateTarget | None


@dataclass(frozen=True)
class UpdateResolution:
    mode: UpdateMode
    reason: str


class UpdateRuntime:
    @staticmethod
    def resolve(facts: UpdateRuntimeFacts, writable: Callable[[Path], bool]) -> UpdateResolution:
        if not facts.frozen:
            return UpdateResolution(
                "off", "Development run: install a packaged release to get updates.")
        target = facts.target
        match facts.platform:
            case "darwin" if target is None:
                return UpdateResolution(
                    "notify", "Unsigned macOS build: download new versions from the release page.")
            case "linux" if target is None:
                return UpdateResolution(
                    "notify", "Unpacked Linux build: download new versions from the release page.")
            case "win32" if target is None:
                return UpdateResolution(
                    "notify",
                    "This build does not update itself: "
                    "download new versions from the release page.")
            case "win32" | "linux" if target is not None and not writable(
                    UpdateRuntime.swap_folder(target)):
                return UpdateResolution(
                    "notify",
                    "The program folder is not writable: "
                    "download new versions from the release page.")
            case "win32":
                return UpdateResolution("automatic", "Packaged Windows build.")
            case "linux":
                return UpdateResolution("automatic", "Packaged Linux build.")
            case "darwin":
                raise ValueError("Self-install is not supported on macOS")
            case _:
                raise ValueError(f"Unsupported update platform: {facts.platform}")

    @staticmethod
    def writable(folder: Path) -> bool:
        try:
            handle, probe = tempfile.mkstemp(prefix=".update-probe-", dir=folder)
            os.close(handle)
            Path(probe).unlink()
        except OSError:
            return False
        return True

    @staticmethod
    def swap_folder(target: UpdateTarget) -> Path:
        """Receives .new, .staged and .old: the file's folder or the folder's parent."""
        return target.path.parent

    @staticmethod
    def staged_folder(target: UpdateTargetFolder) -> Path:
        return UpdateFiles.sibling(target.path, ".staged")
