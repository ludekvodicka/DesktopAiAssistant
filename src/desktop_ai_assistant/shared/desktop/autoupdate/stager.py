import json
import shutil
import stat
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .checksums import UpdateChecksums
from .const import UpdateConst
from .errors import UpdateIntegrityError
from .feed import UpdateAsset, UpdateCandidate
from .files import UpdateFiles
from .runtime import UpdateRuntime, UpdateTarget, UpdateTargetFile, UpdateTargetFolder
from .transport import UpdateTransport
from .version import UpdateVersion


@dataclass(frozen=True)
class UpdateStaged:
    """Private to the manager, never part of UpdateStatus."""

    version: str
    source: Path


class UpdateStager:
    marker_name = "staged.json"
    _transport: UpdateTransport
    _root: Path
    _prepare: Callable[[Path, Path], None] | None

    def __init__(self, transport: UpdateTransport, root: Path,
                 prepare: Callable[[Path, Path], None] | None = None) -> None:
        self._transport = transport
        self._root = root
        # prepare(staged, installed): the app adjusts a staged folder before it becomes final.
        self._prepare = prepare

    def stage(self, candidate: UpdateCandidate, asset: UpdateAsset, target: UpdateTarget,
              progress: Callable[[int], None], cancelled: Callable[[], bool]) -> UpdateStaged:
        sums_asset = candidate.asset(UpdateConst.checksums_asset)
        if sums_asset is None:
            raise UpdateIntegrityError("The release has no SHA256SUMS.txt.")
        sums = self._transport.get_text(sums_asset.url, UpdateConst.checksums_limit_bytes)
        expected = UpdateChecksums.expected(sums, asset.name)
        version = candidate.release.version
        self._prune_other_versions(version)
        match target:
            case UpdateTargetFile():
                source = self._fetch(asset, expected, self._root / version, progress, cancelled)
                return UpdateStaged(version, source)
            case UpdateTargetFolder():
                return self._stage_folder(version, asset, expected, target, progress, cancelled)
            case _:
                raise ValueError(f"Unknown update target: {target!r}")

    def _fetch(self, asset: UpdateAsset, expected: str, folder: Path,
               progress: Callable[[int], None], cancelled: Callable[[], bool]) -> Path:
        final = folder / asset.name
        if final.is_file() and UpdateFiles.sha256(final) == expected:
            return final
        folder.mkdir(parents=True, exist_ok=True)
        partial = UpdateFiles.sibling(final, ".part")
        actual = self._transport.download(asset.url, partial, asset.size, progress, cancelled)
        if actual != expected:
            partial.unlink(missing_ok=True)
            raise UpdateIntegrityError(f"{asset.name} does not match SHA256SUMS.txt.")
        partial.replace(final)
        if sys.platform != "win32":
            final.chmod(0o755)
        return final

    def _stage_folder(self, version: str, asset: UpdateAsset, expected: str,
                      target: UpdateTargetFolder, progress: Callable[[int], None],
                      cancelled: Callable[[], bool]) -> UpdateStaged:
        # Beside the program folder, not in the cache: deep builds pass the Windows path limit.
        staged = UpdateRuntime.staged_folder(target)
        marker = self._root / UpdateStager.marker_name
        if UpdateStager.marker_matches(marker, version, expected) and (
                staged / target.helper).is_file():
            return UpdateStaged(version, staged)
        archive = self._fetch(asset, expected, self._root / version, progress, cancelled)
        partial = UpdateFiles.sibling(staged, ".part")
        shutil.rmtree(partial, ignore_errors=True)
        marker.unlink(missing_ok=True)
        try:
            UpdateStager.extract(archive, partial, target.top_folder)
            for required in (target.executable, target.helper):
                if not (partial / required).is_file():
                    raise UpdateIntegrityError(f"The update package has no {required}.")
            if self._prepare is not None:
                self._prepare(partial, target.path)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        shutil.rmtree(staged, ignore_errors=True)
        partial.rename(staged)
        marker.write_text(json.dumps({"version": version, "sha256": expected}), "utf-8")
        # A scanner may still hold the archive; the next prune removes what stays.
        UpdateFiles.remove_quietly(archive)
        return UpdateStaged(version, staged)

    def _prune_other_versions(self, version: str) -> None:
        if not self._root.is_dir():
            return
        for entry in self._root.iterdir():
            if entry.is_dir() and entry.name != version and UpdateVersion.parse(entry.name):
                UpdateFiles.remove_quietly(entry)

    @staticmethod
    def marker_matches(marker: Path, version: str, expected: str) -> bool:
        try:
            data = json.loads(marker.read_text("utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(data, dict) and data.get("version") == version and data.get(
            "sha256") == expected

    @staticmethod
    def extract(archive: Path, destination: Path, top_folder: str) -> None:
        prefix = top_folder + "/"
        destination.mkdir(parents=True)
        root = destination.resolve()
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                name = entry.filename
                parts = PurePosixPath(name).parts
                # PurePosixPath drops empty parts, so "Top//x" would pass as an absolute path.
                if (not name.startswith(prefix) or "\\" in name or ".." in parts
                        or "" in name.split("/")[:-1]
                        or any(":" in part for part in parts)):
                    raise UpdateIntegrityError(f"Unexpected path in the update package: {name}")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UpdateIntegrityError(
                        f"Links are not allowed in the update package: {name}")
                relative = name.removeprefix(prefix)
                if not relative:
                    continue
                path = destination / relative
                if not path.resolve().is_relative_to(root):
                    raise UpdateIntegrityError(f"Unexpected path in the update package: {name}")
                if entry.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, path.open("wb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if sys.platform != "win32" and mode & 0o111:
                    path.chmod(0o755)
