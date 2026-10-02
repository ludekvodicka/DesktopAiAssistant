import contextlib
import logging
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from .const import UpdateConst
from .errors import UpdateManifestError
from .files import UpdateFiles
from .manifest import UpdateManifest, UpdateOutcome
from .processes import UpdateProcesses

log = logging.getLogger(__name__)


class UpdateRetry:
    @staticmethod
    def until[T](seconds: float, action: Callable[[], T]) -> T:
        """Retries an OSError with backoff: scanners, Explorer and short-lived hosts let go."""
        deadline = time.monotonic() + seconds
        delay = UpdateConst.retry_first_seconds
        while True:
            try:
                return action()
            except FileNotFoundError:
                raise
            except OSError as error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                log.info("Retrying after %s", error)
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, UpdateConst.retry_longest_seconds)


class UpdateHelper:
    """The new build in --apply-update mode: wait for the app, swap, relaunch, write the result."""

    @staticmethod
    def requested(argv: Sequence[str]) -> bool:
        return UpdateConst.helper_flag in argv

    @staticmethod
    def main(argv: Sequence[str]) -> int:
        """0 installed, 1 failed with a result written, 2 manifest missing or unreadable."""
        args = list(argv)
        if UpdateConst.helper_flag not in args:
            return 2
        position = args.index(UpdateConst.helper_flag) + 1
        if position >= len(args):
            return 2
        manifest_path = Path(args[position])
        with UpdateHelper.logging_to(manifest_path.with_name("helper.log")):
            try:
                manifest = UpdateManifest.read(manifest_path)
            except UpdateManifestError as error:
                log.error("Unreadable update manifest: %s", error)
                with contextlib.suppress(OSError):
                    UpdateOutcome(False, None, str(error)).write(
                        manifest_path.with_name("result.json"))
                return 2
        with UpdateHelper.logging_to(manifest.log):
            return UpdateHelper.apply(manifest)

    @staticmethod
    def apply(manifest: UpdateManifest) -> int:
        log.info("Installing %s into %s", manifest.version, manifest.target)
        if not UpdateProcesses.wait_for_exit(manifest.wait_pids, manifest.wait_seconds):
            log.error("The application did not exit within %s s", manifest.wait_seconds)
            UpdateHelper.write_outcome(
                manifest, UpdateOutcome(False, manifest.version, "The application did not exit."))
            return 1
        try:
            UpdateHelper.swap(manifest)
        except Exception as error:
            log.exception("Swap failed")
            # Written before the relaunch: the restored old build reads it at start.
            UpdateHelper.write_outcome(manifest, UpdateOutcome(
                False, manifest.version, f"The update could not replace the program: {error}"))
            UpdateHelper.relaunch_if(manifest)
            return 1
        UpdateHelper.write_outcome(manifest, UpdateOutcome(True, manifest.version, None))
        log.info("Installed %s", manifest.version)
        UpdateHelper.relaunch_if(manifest)
        UpdateFiles.remove_quietly(UpdateFiles.sibling(manifest.target, ".old"))
        return 0

    @staticmethod
    def write_outcome(manifest: UpdateManifest, outcome: UpdateOutcome) -> None:
        # A result the helper cannot write must not keep the user's program from starting again.
        try:
            outcome.write(manifest.result)
        except OSError:
            log.exception("Could not write the update result")

    @staticmethod
    def swap(manifest: UpdateManifest) -> None:
        match manifest.kind:
            case "file":
                UpdateHelper.swap_file(manifest)
            case "folder":
                UpdateHelper.swap_folder(manifest)
            case _:
                raise ValueError(f"Unknown target kind: {manifest.kind}")

    @staticmethod
    def swap_file(manifest: UpdateManifest) -> None:
        target = manifest.target
        new, old = UpdateFiles.sibling(target, ".new"), UpdateFiles.sibling(target, ".old")
        UpdateFiles.remove_quietly(new)
        # Copied into the target folder so both renames stay on one volume.
        shutil.copy2(manifest.source, new)
        try:
            match sys.platform:
                case "win32":
                    UpdateFiles.remove_quietly(old)
                    UpdateRetry.until(manifest.swap_seconds, lambda: target.replace(old))
                    try:
                        UpdateRetry.until(manifest.swap_seconds, lambda: new.replace(target))
                    except OSError:
                        UpdateRetry.until(manifest.swap_seconds, lambda: old.replace(target))
                        raise
                case "linux":
                    new.chmod(0o755)
                    # Atomic; a process still running the old file keeps its inode.
                    UpdateRetry.until(manifest.swap_seconds, lambda: os.replace(new, target))
                case _:
                    raise ValueError(f"Self-install is not supported on {sys.platform}")
        finally:
            UpdateFiles.remove_quietly(new)

    @staticmethod
    def swap_folder(manifest: UpdateManifest) -> None:
        target, staged = manifest.target, manifest.source
        old = UpdateFiles.sibling(target, ".old")
        UpdateFiles.remove_quietly(old)
        UpdateRetry.until(manifest.swap_seconds, lambda: target.rename(old))
        try:
            UpdateRetry.until(manifest.swap_seconds, lambda: staged.rename(target))
        except OSError:
            UpdateRetry.until(manifest.swap_seconds, lambda: old.rename(target))
            raise

    @staticmethod
    def relaunch_if(manifest: UpdateManifest) -> None:
        if not manifest.relaunch:
            return
        match manifest.kind:
            case "file":
                program = manifest.target
            case "folder":
                program = manifest.target / (manifest.executable or "")
            case _:
                raise ValueError(f"Unknown target kind: {manifest.kind}")
        try:
            UpdateProcesses.spawn_detached([str(program), *manifest.relaunch_args],
                                           cwd=program.parent)
        except OSError:
            log.exception("Relaunch of %s failed", program)

    @staticmethod
    @contextlib.contextmanager
    def logging_to(path: Path) -> Iterator[None]:
        # Windowed builds have no stderr, so the helper log is the only trace of a failed swap.
        package = logging.getLogger(__package__)
        handler: logging.Handler
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
        except OSError:
            handler = logging.NullHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        previous_level = package.level
        package.setLevel(logging.INFO)
        package.addHandler(handler)
        try:
            yield
        finally:
            package.removeHandler(handler)
            package.setLevel(previous_level)
            handler.close()
