import contextlib
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path


class UpdateProcesses:
    """Platform adapter: waiting for processes to exit and starting detached programs."""

    poll_seconds = 0.1

    @staticmethod
    def wait_for_exit(pids: Sequence[int], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        match sys.platform:
            case "win32":
                return UpdateProcesses._wait_windows(pids, deadline)
            case "linux" | "darwin":
                return UpdateProcesses._wait_posix(pids, deadline)
            case _:
                raise ValueError(f"Unsupported platform: {sys.platform}")

    @staticmethod
    def spawn_detached(argv: Sequence[str], cwd: Path) -> None:
        # A frozen PyInstaller child must start as a new program, not inherit the parent's runtime.
        env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
        common = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL,
                  "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        match sys.platform:
            case "win32":
                flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                try:
                    subprocess.Popen(list(argv),
                                     creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                                     **common)
                except PermissionError:
                    # The parent's job object forbids breakaway; the child then stays in the job.
                    subprocess.Popen(list(argv), creationflags=flags, **common)
            case "linux" | "darwin":
                subprocess.Popen(list(argv), start_new_session=True, **common)
            case _:
                raise ValueError(f"Unsupported platform: {sys.platform}")

    @staticmethod
    def _wait_windows(pids: Sequence[int], deadline: float) -> bool:
        import ctypes
        from ctypes import wintypes

        synchronize = 0x00100000
        wait_object_0 = 0
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        for pid in pids:
            handle = kernel32.OpenProcess(synchronize, False, pid)
            if not handle:
                continue  # a PID that cannot be opened belongs to no running process
            try:
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if kernel32.WaitForSingleObject(handle, remaining) != wait_object_0:
                    return False
            finally:
                kernel32.CloseHandle(handle)
        return True

    @staticmethod
    def _wait_posix(pids: Sequence[int], deadline: float) -> bool:
        waiting = set(pids)
        while waiting:
            for pid in list(waiting):
                # Reaps the PID if it is an exited child of this process, which kill(0) still sees.
                with contextlib.suppress(ChildProcessError):
                    os.waitpid(pid, os.WNOHANG)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    waiting.discard(pid)
                except PermissionError:
                    pass
                else:
                    if UpdateProcesses._is_zombie(pid):
                        waiting.discard(pid)
            if not waiting:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(UpdateProcesses.poll_seconds)
        return True

    @staticmethod
    def _is_zombie(pid: int) -> bool:
        """An exited process whose parent has not reaped it yet; Linux only, no /proc elsewhere."""
        try:
            stat_line = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            return False
        # The state follows the command name, which is in parentheses and may contain spaces.
        return stat_line.rpartition(")")[2].split()[:1] == ["Z"]
