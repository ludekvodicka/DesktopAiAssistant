import json
import os
from pathlib import Path

import pytest

from ..installer import UpdateInstaller
from ..manifest import UpdateManifest, UpdateOutcome
from ..processes import UpdateProcesses
from ..runtime import UpdateTargetFile, UpdateTargetFolder
from ..stager import UpdateStaged
from .support import FILE_PATTERN, ZIP_PATTERN, write_tree


@pytest.fixture
def spawned(monkeypatch):
    calls: list[tuple[list[str], Path]] = []

    def spawn(argv, cwd):
        calls.append((list(argv), cwd))

    monkeypatch.setattr(UpdateProcesses, "spawn_detached", staticmethod(spawn))
    return calls


def file_setup(tmp_path: Path, onefile_parent: bool):
    root = tmp_path / "updates"
    source = write_tree(root / "1.2.0", {"Demo-App.exe": b"new"}) / "Demo-App.exe"
    target = UpdateTargetFile(tmp_path / "app" / "Demo-App.exe", FILE_PATTERN, onefile_parent)
    return root, UpdateStaged("1.2.0", source), target


def folder_setup(tmp_path: Path):
    root = tmp_path / "updates"
    program = tmp_path / "Programs" / "DemoApp"
    staged = write_tree(tmp_path / "Programs" / "DemoApp.staged",
                        {"DemoApp.exe": b"app", "DemoHelper.exe": b"helper"})
    target = UpdateTargetFolder(program, ZIP_PATTERN, "DemoApp", "DemoApp.exe", "DemoHelper.exe")
    return root, UpdateStaged("1.2.0", staged), target


def test_file_kind_waits_for_own_and_parent_pid(tmp_path, spawned):
    root, staged, target = file_setup(tmp_path, onefile_parent=True)
    UpdateInstaller(root).launch(staged, target, relaunch=True, relaunch_args=("--x",))
    pending = root / "pending.json"
    assert spawned == [([str(staged.source), "--apply-update", str(pending)], root)]
    manifest = UpdateManifest.read(pending)
    assert manifest.wait_pids == (os.getpid(), os.getppid())
    assert (manifest.kind, manifest.source, manifest.target) == ("file", staged.source,
                                                                 target.path)
    assert (manifest.executable, manifest.relaunch, manifest.relaunch_args) == (None, True,
                                                                                ("--x",))
    assert (manifest.wait_seconds, manifest.swap_seconds) == (120, 60)
    assert (manifest.result, manifest.log) == (root / "result.json", root / "helper.log")


def test_file_kind_without_parent_waits_for_itself(tmp_path, spawned):
    root, staged, target = file_setup(tmp_path, onefile_parent=False)
    UpdateInstaller(root).launch(staged, target, relaunch=False, relaunch_args=())
    manifest = UpdateManifest.read(root / "pending.json")
    assert manifest.wait_pids == (os.getpid(),)
    assert not manifest.relaunch


def test_folder_kind_copies_the_helper_out(tmp_path, spawned):
    root, staged, target = folder_setup(tmp_path)
    UpdateInstaller(root).launch(staged, target, relaunch=True, relaunch_args=())
    helper = root / "helper" / "1.2.0" / "DemoHelper.exe"
    assert helper.read_bytes() == b"helper"
    assert spawned == [([str(helper), "--apply-update", str(root / "pending.json")], root)]
    manifest = UpdateManifest.read(root / "pending.json")
    assert (manifest.kind, manifest.source, manifest.executable) == ("folder", staged.source,
                                                                     "DemoApp.exe")
    assert manifest.wait_pids == (os.getpid(),)


def test_spawn_failure_propagates(tmp_path, monkeypatch):
    def refuse(argv, cwd):
        raise OSError("blocked")

    monkeypatch.setattr(UpdateProcesses, "spawn_detached", staticmethod(refuse))
    root, staged, target = file_setup(tmp_path, onefile_parent=False)
    with pytest.raises(OSError, match="blocked"):
        UpdateInstaller(root).launch(staged, target, relaunch=True, relaunch_args=())
    assert not (root / "pending.json").exists()
    assert UpdateInstaller(root).take_outcome("1.1.0", target) is None


def test_orphaned_pending_of_the_running_version_counts_as_installed(tmp_path, spawned):
    root, staged, target = file_setup(tmp_path, onefile_parent=False)
    UpdateInstaller(root).launch(staged, target, relaunch=False, relaunch_args=())
    assert UpdateInstaller(root).take_outcome("1.2.0", target) == UpdateOutcome(True, "1.2.0",
                                                                                None)


def test_take_outcome_reads_and_removes_the_result(tmp_path):
    root = tmp_path / "updates"
    UpdateOutcome(False, "1.2.0", "locked").write(root / "result.json")
    root.joinpath("pending.json").write_text("{}")
    installer = UpdateInstaller(root)
    assert installer.take_outcome("1.1.0", None) == UpdateOutcome(False, "1.2.0", "locked")
    assert not (root / "result.json").exists()
    assert not (root / "pending.json").exists()
    assert installer.take_outcome("1.1.0", None) is None


def test_orphaned_pending_counts_as_failed(tmp_path, spawned):
    root, staged, target = file_setup(tmp_path, onefile_parent=False)
    UpdateInstaller(root).launch(staged, target, relaunch=False, relaunch_args=())
    outcome = UpdateInstaller(root).take_outcome("1.1.0", target)
    assert outcome == UpdateOutcome(False, "1.2.0", "The previous update did not finish.")


def test_broken_pending_and_result(tmp_path):
    root = tmp_path / "updates"
    root.mkdir()
    (root / "pending.json").write_text("broken")
    assert UpdateInstaller(root).take_outcome("1.1.0", None) == UpdateOutcome(
        False, None, "The previous update did not finish.")
    (root / "result.json").write_text("broken")
    outcome = UpdateInstaller(root).take_outcome("1.1.0", None)
    assert outcome is not None and not outcome.installed and outcome.version is None
    assert not (root / "result.json").exists()


def test_prune_removes_old_versions_helpers_and_leftovers(tmp_path):
    root = tmp_path / "updates"
    write_tree(root, {
        "1.0.0/a.exe": b"x", "1.1.0/a.exe": b"x", "1.2.0/a.exe": b"x",
        "helper/1.1.0/h.exe": b"x", "helper/1.2.0/h.exe": b"x", "notes/keep.txt": b"x",
    })
    program = write_tree(tmp_path / "app", {"Demo-App.exe": b"run", "Demo-App.exe.old": b"o",
                                            "Demo-App.exe.new": b"n"})
    target = UpdateTargetFile(program / "Demo-App.exe", FILE_PATTERN, onefile_parent=False)
    UpdateInstaller(root).take_outcome("1.1.0", target)
    assert sorted(path.name for path in root.iterdir()) == ["1.2.0", "helper", "notes"]
    assert sorted(path.name for path in (root / "helper").iterdir()) == ["1.2.0"]
    assert sorted(path.name for path in program.iterdir()) == ["Demo-App.exe"]


def test_prune_keeps_a_newer_staged_folder(tmp_path):
    root, staged, target = folder_setup(tmp_path)
    root.mkdir()
    (root / "staged.json").write_text(json.dumps({"version": "1.2.0", "sha256": "a" * 64}))
    write_tree(tmp_path / "Programs", {"DemoApp.staged.part/x": b"x", "DemoApp.old/x": b"x"})
    UpdateInstaller(root).take_outcome("1.1.0", target)
    assert staged.source.is_dir()
    assert (root / "staged.json").is_file()
    assert sorted(path.name for path in (tmp_path / "Programs").iterdir()) == ["DemoApp.staged"]


@pytest.mark.parametrize("marker", [{"version": "1.1.0"}, None])
def test_prune_removes_a_staged_folder_that_is_not_newer(tmp_path, marker):
    root, staged, target = folder_setup(tmp_path)
    root.mkdir()
    if marker is not None:
        (root / "staged.json").write_text(json.dumps(marker))
    UpdateInstaller(root).take_outcome("1.1.0", target)
    assert not staged.source.exists()
    assert not (root / "staged.json").exists()
