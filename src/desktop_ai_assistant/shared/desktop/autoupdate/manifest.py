import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .const import UpdateConst
from .errors import UpdateManifestError


class UpdateJson:
    """Typed field access for the cross-version files; any mismatch is an UpdateManifestError."""

    @staticmethod
    def load(path: Path) -> dict[str, object]:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError) as error:
            raise UpdateManifestError(f"{path.name} cannot be read: {error}") from error
        if not isinstance(data, dict):
            raise UpdateManifestError(f"{path.name} does not hold an object.")
        return data

    @staticmethod
    def save(path: Path, data: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".tmp")
        partial.write_text(json.dumps(data, indent=2), "utf-8")
        partial.replace(path)

    @staticmethod
    def text(data: dict[str, object], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str):
            raise UpdateManifestError(f"Field {key} is not text.")
        return value

    @staticmethod
    def optional_text(data: dict[str, object], key: str) -> str | None:
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            raise UpdateManifestError(f"Field {key} is not text.")
        return value

    @staticmethod
    def flag(data: dict[str, object], key: str) -> bool:
        value = data.get(key)
        if not isinstance(value, bool):
            raise UpdateManifestError(f"Field {key} is not a boolean.")
        return value

    @staticmethod
    def number(data: dict[str, object], key: str) -> float:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise UpdateManifestError(f"Field {key} is not a number.")
        return float(value)

    @staticmethod
    def items(data: dict[str, object], key: str, kind: type) -> tuple:
        value = data.get(key)
        if not isinstance(value, list) or not all(
                isinstance(item, kind) and not isinstance(item, bool) for item in value):
            raise UpdateManifestError(f"Field {key} is not a list of {kind.__name__}.")
        return tuple(value)


@dataclass(frozen=True)
class UpdateManifest:
    """Written by the running build, read by the helper of the new build: schema 1 forever."""

    schema: int
    version: str
    kind: Literal["file", "folder"]
    # The staged file, or <target>.staged for a folder.
    source: Path
    target: Path
    # Folder kind: the program to relaunch, relative to target.
    executable: str | None
    wait_pids: tuple[int, ...]
    wait_seconds: float
    swap_seconds: float
    relaunch: bool
    relaunch_args: tuple[str, ...]
    result: Path
    log: Path

    def write(self, path: Path) -> None:
        UpdateJson.save(path, {
            "schema": self.schema,
            "version": self.version,
            "kind": self.kind,
            "source": self.source.as_posix(),
            "target": self.target.as_posix(),
            "executable": self.executable,
            "wait_pids": list(self.wait_pids),
            "wait_seconds": self.wait_seconds,
            "swap_seconds": self.swap_seconds,
            "relaunch": self.relaunch,
            "relaunch_args": list(self.relaunch_args),
            "result": self.result.as_posix(),
            "log": self.log.as_posix(),
        })

    @staticmethod
    def read(path: Path) -> "UpdateManifest":
        data = UpdateJson.load(path)
        schema = data.get("schema")
        if schema not in UpdateConst.manifest_schemas_readable or isinstance(schema, bool):
            raise UpdateManifestError(f"Unsupported update manifest schema: {schema!r}")
        kind = data.get("kind")
        match kind:
            case "file":
                executable = UpdateJson.optional_text(data, "executable")
            case "folder":
                executable = UpdateJson.text(data, "executable")
            case _:
                raise UpdateManifestError(f"Unknown update target kind: {kind!r}")
        return UpdateManifest(
            schema=int(schema),
            version=UpdateJson.text(data, "version"),
            kind=kind,
            source=Path(UpdateJson.text(data, "source")),
            target=Path(UpdateJson.text(data, "target")),
            executable=executable,
            wait_pids=UpdateJson.items(data, "wait_pids", int),
            wait_seconds=UpdateJson.number(data, "wait_seconds"),
            swap_seconds=UpdateJson.number(data, "swap_seconds"),
            relaunch=UpdateJson.flag(data, "relaunch"),
            relaunch_args=UpdateJson.items(data, "relaunch_args", str),
            result=Path(UpdateJson.text(data, "result")),
            log=Path(UpdateJson.text(data, "log")),
        )


@dataclass(frozen=True)
class UpdateOutcome:
    """Written by the helper; read by the next start of either build. Unknown fields are ignored."""

    installed: bool
    # None when the helper could not read its manifest.
    version: str | None
    message: str | None

    def write(self, path: Path) -> None:
        UpdateJson.save(path, {
            "schema": UpdateConst.manifest_schema,
            "version": self.version,
            "installed": self.installed,
            "message": self.message,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    @staticmethod
    def read(path: Path) -> "UpdateOutcome":
        data = UpdateJson.load(path)
        return UpdateOutcome(
            installed=UpdateJson.flag(data, "installed"),
            version=UpdateJson.optional_text(data, "version"),
            message=UpdateJson.optional_text(data, "message"),
        )
