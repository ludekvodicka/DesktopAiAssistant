"""Proves that a built program swaps itself in helper mode.

    python -m <package>.verify file <built program> [--scratch DIR]
    python -m <package>.verify folder <built folder> --executable X --helper Y [--scratch DIR]

Release workflows run it on the real artifacts; it never relaunches the program.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .const import UpdateConst
from .files import UpdateFiles
from .manifest import UpdateManifest, UpdateOutcome


@dataclass(frozen=True)
class UpdateVerifyOptions:
    kind: Literal["file", "folder"]
    built: Path
    executable: str | None
    helper: str | None
    scratch: Path


class UpdateVerifyError(Exception):
    pass


class UpdateVerify:
    placeholder = b"previous build\n"
    holder_seconds = 3
    blocked_swap_seconds = 3
    run_timeout_seconds = 300

    @staticmethod
    def main(argv: Sequence[str]) -> int:
        options = UpdateVerify.parse(argv)
        try:
            match options.kind:
                case "file":
                    UpdateVerify.file(options.built, options.scratch)
                case "folder":
                    if options.executable is None or options.helper is None:
                        raise UpdateVerifyError("folder needs --executable and --helper")
                    UpdateVerify.folder(options.built, options.executable, options.helper,
                                        options.scratch)
                case _:
                    raise UpdateVerifyError(f"Unknown target kind: {options.kind}")
        except UpdateVerifyError as error:
            print(f"UPDATE HELPER CHECK FAILED: {error}", file=sys.stderr, flush=True)
            return 1
        print("UPDATE HELPER VERIFIED", flush=True)
        return 0

    @staticmethod
    def parse(argv: Sequence[str]) -> UpdateVerifyOptions:
        parser = argparse.ArgumentParser(prog="verify", description="Prove the update helper.")
        parser.add_argument("kind", choices=("file", "folder"))
        parser.add_argument("built", type=Path)
        parser.add_argument("--executable")
        parser.add_argument("--helper")
        parser.add_argument("--scratch", type=Path, default=Path(tempfile.gettempdir()))
        args = parser.parse_args(list(argv))
        return UpdateVerifyOptions(args.kind, args.built.resolve(), args.executable, args.helper,
                                   args.scratch.resolve())

    @staticmethod
    def file(built: Path, scratch: Path) -> None:
        UpdateVerify.require(built.is_file(), f"{built} is not a file")
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
                prefix="u", dir=scratch, ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            target = UpdateVerify.write(root / "t" / built.name, UpdateVerify.placeholder)
            staged = UpdateVerify.copy(built, root / "s" / built.name)
            holder = subprocess.Popen(
                [sys.executable, "-c", f"import time; time.sleep({UpdateVerify.holder_seconds})"])
            # Reaped while the helper waits: an unreaped exited child still looks alive on POSIX.
            threading.Thread(target=holder.wait, daemon=True).start()
            try:
                outcome = UpdateVerify.run(staged, UpdateVerify.manifest(
                    root, "file", staged, target, (holder.pid,), 60, None))
            finally:
                holder.kill()
                holder.wait()
            UpdateVerify.require(outcome.installed, f"file swap: {outcome.message}")
            UpdateVerify.require(target.read_bytes() == built.read_bytes(), "file content swapped")
            UpdateVerify.require(not UpdateFiles.sibling(target, ".old").exists(),
                                 "old copy removed")
            if sys.platform == "win32":
                UpdateVerify.blocked_file_swap(root, staged)

    @staticmethod
    def blocked_file_swap(root: Path, staged: Path) -> None:
        target = UpdateVerify.write(root / "b" / staged.name, UpdateVerify.placeholder)
        with target.open("rb"):
            outcome = UpdateVerify.run(staged, UpdateVerify.manifest(
                root, "file", staged, target, (), UpdateVerify.blocked_swap_seconds, None))
        UpdateVerify.require(not outcome.installed, "a held file fails the swap")
        UpdateVerify.require(target.read_bytes() == UpdateVerify.placeholder,
                             "a held file stays unchanged")
        UpdateVerify.require(not UpdateFiles.sibling(target, ".new").exists(),
                             "no .new after a failed swap")

    @staticmethod
    def folder(built: Path, executable: str, helper: str, scratch: Path) -> None:
        UpdateVerify.require((built / executable).is_file(), f"{built} has no {executable}")
        UpdateVerify.require((built / helper).is_file(), f"{built} has no {helper}")
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
                prefix="u", dir=scratch, ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            target = UpdateVerify.placeholder_folder(root / "t" / built.name)
            staged = UpdateFiles.sibling(target, ".staged")
            shutil.copytree(built, staged)
            program = UpdateVerify.copy(staged / helper, root / "h" / helper)
            if sys.platform == "win32":
                UpdateVerify.blocked_folder_swap(root, program, staged, target, executable)
            outcome = UpdateVerify.run(program, UpdateVerify.manifest(
                root, "folder", staged, target, (), 60, executable))
            UpdateVerify.require(outcome.installed, f"folder swap: {outcome.message}")
            UpdateVerify.require((target / executable).is_file(), "new folder in place")
            UpdateVerify.require(not staged.exists(), "staged folder consumed")
            UpdateVerify.require(not UpdateFiles.sibling(target, ".old").exists(),
                                 "old folder removed")

    @staticmethod
    def blocked_folder_swap(root: Path, program: Path, staged: Path, target: Path,
                            executable: str) -> None:
        # Runs first and reuses the same staged copy, so a large build is copied once.
        with (target / "previous.bin").open("rb"):
            outcome = UpdateVerify.run(program, UpdateVerify.manifest(
                root, "folder", staged, target, (), UpdateVerify.blocked_swap_seconds,
                executable))
        UpdateVerify.require(not outcome.installed, "a held folder fails the swap")
        UpdateVerify.require((target / "previous.bin").read_bytes() == UpdateVerify.placeholder,
                             "a held folder stays unchanged")
        UpdateVerify.require(staged.is_dir(), "staged folder kept after a failed swap")

    @staticmethod
    def manifest(root: Path, kind: Literal["file", "folder"], source: Path, target: Path,
                 pids: tuple[int, ...], swap: float, executable: str | None) -> Path:
        path = root / "pending.json"
        UpdateFiles.remove_quietly(root / "result.json")
        UpdateManifest(
            schema=UpdateConst.manifest_schema, version="0.0.0", kind=kind, source=source,
            target=target, executable=executable, wait_pids=pids, wait_seconds=60,
            swap_seconds=swap, relaunch=False, relaunch_args=(), result=root / "result.json",
            log=root / "helper.log",
        ).write(path)
        return path

    @staticmethod
    def run(program: Path, manifest: Path) -> UpdateOutcome:
        env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1",
               # CI runners may lack FUSE; an AppImage then extracts itself instead of mounting.
               "APPIMAGE_EXTRACT_AND_RUN": "1"}
        try:
            completed = subprocess.run(
                [str(program), UpdateConst.helper_flag, str(manifest)], cwd=manifest.parent,
                env=env, timeout=UpdateVerify.run_timeout_seconds, check=False,
                stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UpdateVerifyError(f"{program.name} did not run: {error}") from error
        result = manifest.with_name("result.json")
        if not result.is_file():
            UpdateVerify.show_log(manifest)
            raise UpdateVerifyError(
                f"{program.name} wrote no result (exit code {completed.returncode})")
        outcome = UpdateOutcome.read(result)
        if completed.returncode != (0 if outcome.installed else 1):
            UpdateVerify.show_log(manifest)
            raise UpdateVerifyError(f"unexpected exit code {completed.returncode}")
        return outcome

    @staticmethod
    def show_log(manifest: Path) -> None:
        log = manifest.with_name("helper.log")
        if log.is_file():
            print(log.read_text("utf-8", "replace"), file=sys.stderr, flush=True)

    @staticmethod
    def require(condition: bool, what: str) -> None:
        if not condition:
            raise UpdateVerifyError(what)

    @staticmethod
    def write(path: Path, data: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    @staticmethod
    def copy(source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination

    @staticmethod
    def placeholder_folder(path: Path) -> Path:
        UpdateVerify.write(path / "previous.bin", UpdateVerify.placeholder)
        return path


if __name__ == "__main__":
    raise SystemExit(UpdateVerify.main(sys.argv[1:]))
