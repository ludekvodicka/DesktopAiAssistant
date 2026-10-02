import json
import logging
import os
import shutil
from pathlib import Path

from .const import UpdateConst
from .errors import UpdateManifestError
from .files import UpdateFiles
from .manifest import UpdateManifest, UpdateOutcome
from .processes import UpdateProcesses
from .runtime import UpdateRuntime, UpdateTarget, UpdateTargetFile, UpdateTargetFolder
from .stager import UpdateStaged, UpdateStager
from .version import UpdateVersion


class UpdateInstaller:
    _root: Path

    def __init__(self, root: Path) -> None:
        self._root = root

    def launch(self, staged: UpdateStaged, target: UpdateTarget, relaunch: bool,
               relaunch_args: tuple[str, ...]) -> None:
        """Writes pending.json and starts the helper; OSError when it cannot start."""
        match target:
            case UpdateTargetFile():
                # The verified new build runs itself as the helper.
                kind, helper, executable = "file", staged.source, None
                pids = (os.getpid(), os.getppid()) if target.onefile_parent else (os.getpid(),)
            case UpdateTargetFolder():
                kind, executable, pids = "folder", target.executable, (os.getpid(),)
                # Copied out, so the helper never runs from a folder it renames.
                helper = self._root / "helper" / staged.version / target.helper
                helper.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staged.source / target.helper, helper)
            case _:
                raise ValueError(f"Unknown update target: {target!r}")
        pending = self._root / "pending.json"
        UpdateManifest(
            schema=UpdateConst.manifest_schema, version=staged.version, kind=kind,
            source=staged.source, target=target.path, executable=executable, wait_pids=pids,
            wait_seconds=UpdateConst.helper_wait_seconds, swap_seconds=UpdateConst.swap_seconds,
            relaunch=relaunch, relaunch_args=relaunch_args, result=self._root / "result.json",
            log=self._root / "helper.log",
        ).write(pending)
        try:
            UpdateProcesses.spawn_detached([str(helper), UpdateConst.helper_flag, str(pending)],
                                           cwd=self._root)
        except OSError:
            # Without a helper there is no update in progress to report at the next start.
            UpdateFiles.remove_quietly(pending)
            raise

    def take_outcome(self, running: str, target: UpdateTarget | None) -> UpdateOutcome | None:
        """Reads and removes the previous helper's result, then prunes leftovers; best effort."""
        result, pending = self._root / "result.json", self._root / "pending.json"
        outcome = None
        if result.is_file():
            try:
                outcome = UpdateOutcome.read(result)
            except UpdateManifestError as error:
                outcome = UpdateOutcome(False, None, f"The previous update left no result: {error}")
        elif pending.is_file():
            version = UpdateInstaller.pending_version(pending)
            # A helper that swapped but could not write its result leaves the new build running.
            outcome = (UpdateOutcome(True, version, None) if version == running else
                       UpdateOutcome(False, version, "The previous update did not finish."))
        for leftover in (result, pending):
            UpdateFiles.remove_quietly(leftover)
        try:
            self._prune(running, target)
        except OSError as error:
            logging.getLogger(__name__).warning("Update cleanup failed: %s", error)
        return outcome

    @staticmethod
    def pending_version(pending: Path) -> str | None:
        try:
            return UpdateManifest.read(pending).version
        except UpdateManifestError:
            return None

    def _prune(self, running: str, target: UpdateTarget | None) -> None:
        current = UpdateVersion.parse(running)
        if current is None:
            return
        if self._root.is_dir():
            for entry in self._root.iterdir():
                if entry.is_dir() and UpdateInstaller._not_newer(entry.name, current):
                    UpdateFiles.remove_quietly(entry)
        helpers = self._root / "helper"
        if helpers.is_dir():
            for entry in helpers.iterdir():
                if UpdateInstaller._not_newer(entry.name, current):
                    UpdateFiles.remove_quietly(entry)
        if target is None:
            return
        for suffix in (".old", ".new"):
            UpdateFiles.remove_quietly(UpdateFiles.sibling(target.path, suffix))
        match target:
            case UpdateTargetFile():
                pass
            case UpdateTargetFolder():
                staged = UpdateRuntime.staged_folder(target)
                UpdateFiles.remove_quietly(UpdateFiles.sibling(staged, ".part"))
                marker = self._root / UpdateStager.marker_name
                if not UpdateInstaller._marker_newer(marker, current):
                    UpdateFiles.remove_quietly(staged)
                    UpdateFiles.remove_quietly(marker)
            case _:
                raise ValueError(f"Unknown update target: {target!r}")

    @staticmethod
    def _not_newer(name: str, current: tuple[int, int, int]) -> bool:
        version = UpdateVersion.parse(name)
        return version is not None and version <= current

    @staticmethod
    def _marker_newer(marker: Path, current: tuple[int, int, int]) -> bool:
        try:
            data = json.loads(marker.read_text("utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        version = UpdateVersion.parse(str(data.get("version", "")))
        return version is not None and version > current
