import json
from pathlib import Path

import pytest

from ..errors import UpdateManifestError
from ..manifest import UpdateManifest, UpdateOutcome

# Exactly what a schema 1 build writes; later builds must keep reading it.
SCHEMA_1_FOLDER = """{"schema": 1, "version": "0.4.1", "kind": "folder",
 "source": "D:/Apps/Programs/DemoApp.staged",
 "target": "D:/Apps/Programs/DemoApp", "executable": "DemoApp.exe",
 "wait_pids": [7340], "wait_seconds": 120, "swap_seconds": 60,
 "relaunch": true, "relaunch_args": ["--settings"],
 "result": "D:/Apps/DemoApp/updates/result.json",
 "log": "D:/Apps/DemoApp/updates/helper.log"}"""


def manifest(tmp_path: Path, **changes) -> UpdateManifest:
    fields = dict(
        schema=1, version="1.2.0", kind="file", source=tmp_path / "s" / "Demo.exe",
        target=tmp_path / "t" / "Demo.exe", executable=None, wait_pids=(10, 20),
        wait_seconds=120.0, swap_seconds=60.0, relaunch=True, relaunch_args=("--a", "b c"),
        result=tmp_path / "result.json", log=tmp_path / "helper.log")
    fields.update(changes)
    return UpdateManifest(**fields)


def test_round_trip(tmp_path):
    original = manifest(tmp_path)
    original.write(tmp_path / "pending.json")
    assert UpdateManifest.read(tmp_path / "pending.json") == original
    assert not (tmp_path / "pending.json.tmp").exists()


def test_schema_1_fixture_is_read(tmp_path):
    path = tmp_path / "pending.json"
    path.write_text(SCHEMA_1_FOLDER, "utf-8")
    read = UpdateManifest.read(path)
    assert read.kind == "folder"
    assert read.executable == "DemoApp.exe"
    assert read.wait_pids == (7340,)
    assert read.relaunch_args == ("--settings",)
    assert read.target == Path("D:/Apps/Programs/DemoApp")


def broken(tmp_path: Path, mutate) -> Path:
    data = json.loads(SCHEMA_1_FOLDER)
    mutate(data)
    path = tmp_path / "pending.json"
    path.write_text(json.dumps(data), "utf-8")
    return path


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(schema=2),
    lambda data: data.update(schema=True),
    lambda data: data.pop("schema"),
    lambda data: data.update(kind="disk"),
    lambda data: data.update(executable=None),
    lambda data: data.pop("target"),
    lambda data: data.update(wait_pids=["1"]),
    lambda data: data.update(relaunch="yes"),
    lambda data: data.update(swap_seconds="60"),
])
def test_invalid_manifests_raise(tmp_path, mutate):
    with pytest.raises(UpdateManifestError):
        UpdateManifest.read(broken(tmp_path, mutate))


def test_broken_json_raises(tmp_path):
    path = tmp_path / "pending.json"
    path.write_text("{not json", "utf-8")
    with pytest.raises(UpdateManifestError, match="cannot be read"):
        UpdateManifest.read(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(UpdateManifestError):
        UpdateManifest.read(tmp_path / "missing.json")


def test_outcome_round_trip_and_timestamp(tmp_path):
    path = tmp_path / "result.json"
    UpdateOutcome(False, "1.2.0", "locked").write(path)
    assert UpdateOutcome.read(path) == UpdateOutcome(False, "1.2.0", "locked")
    data = json.loads(path.read_text("utf-8"))
    assert data["schema"] == 1
    assert data["finished_at"].endswith("Z")


def test_outcome_reader_ignores_unknown_fields(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"schema": 7, "installed": True, "version": "2.0.0",
                                "message": None, "extra": [1, 2]}), "utf-8")
    assert UpdateOutcome.read(path) == UpdateOutcome(True, "2.0.0", None)


def test_outcome_without_installed_raises(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"version": "2.0.0"}), "utf-8")
    with pytest.raises(UpdateManifestError):
        UpdateOutcome.read(path)
