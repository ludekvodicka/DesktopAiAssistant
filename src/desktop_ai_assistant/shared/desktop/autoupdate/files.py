import contextlib
import hashlib
import shutil
from pathlib import Path


class UpdateFiles:
    @staticmethod
    def sibling(path: Path, suffix: str) -> Path:
        return path.with_name(path.name + suffix)

    @staticmethod
    def remove_quietly(path: Path) -> None:
        """Best effort: a leftover held by another process is retried at the next start."""
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
            return
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)

    @staticmethod
    def sha256(path: Path) -> str:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
