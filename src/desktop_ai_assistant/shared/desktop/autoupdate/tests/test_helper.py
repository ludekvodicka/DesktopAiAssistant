import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from .. import helper as helper_module
from ..helper import UpdateHelper
from ..manifest import UpdateManifest, UpdateOutcome
from ..processes import UpdateProcesses
from .support import write_tree

# Captured before tests patch sys.platform, which is the one global sys module.
ON_WINDOWS = sys.platform == "win32"


def file_manifest(tmp_path: Path, **changes) -> Path:
    source = write_tree(tmp_path / "s", {"Demo.exe": b"new build"}) / "Demo.exe"
    target = write_tree(tmp_path / "t", {"Demo.exe": b"old build"}) / "Demo.exe"
    return write_manifest(tmp_path, kind="file", source=source, target=target, executable=None,
                          **changes)


def folder_manifest(tmp_path: Path, **changes) -> Path:
    target = write_tree(tmp_path / "Programs" / "DemoApp", {"DemoApp.exe": b"old", "x.dll": b"o"})
    staged = write_tree(tmp_path / "Programs" / "DemoApp.staged",
                        {"DemoApp.exe": b"new", "lib/y.dll": b"n"})
    return write_manifest(tmp_path, kind="folder", source=staged, target=target,
                          executable="DemoApp.exe", **changes)


def write_manifest(tmp_path: Path, **fields) -> Path:
    values = dict(schema=1, version="1.2.0", wait_pids=(), wait_seconds=5.0, swap_seconds=0.6,
                  relaunch=False, relaunch_args=(), result=tmp_path / "updates" / "result.json",
                  log=tmp_path / "updates" / "helper.log")
    values.update(fields)
    path = tmp_path / "updates" / "pending.json"
    UpdateManifest(**values).write(path)
    return path


def run(path: Path) -> tuple[int, UpdateOutcome]:
    code = UpdateHelper.main(["--apply-update", str(path)])
    return code, UpdateOutcome.read(path.with_name("result.json"))


@pytest.fixture
def spawned(monkeypatch):
    calls: list[tuple[list[str], Path, bool]] = []

    def spawn(argv, cwd):
        calls.append((list(argv), cwd, (cwd.parent / "updates").exists()))

    monkeypatch.setattr(UpdateProcesses, "spawn_detached", staticmethod(spawn))
    return calls


def test_requested_only_with_the_flag():
    assert UpdateHelper.requested(["app.exe", "--apply-update", "m.json"])
    assert not UpdateHelper.requested(["app.exe", "chrome-extension://abc/"])


@pytest.mark.parametrize("argv", [[], ["--apply-update"], ["--other", "x"]])
def test_missing_manifest_argument_exits_2(argv):
    assert UpdateHelper.main(argv) == 2


def test_unreadable_manifest_exits_2_and_writes_a_result_beside_it(tmp_path):
    path = tmp_path / "updates" / "pending.json"
    path.parent.mkdir()
    path.write_text("{broken", "utf-8")
    assert UpdateHelper.main(["--apply-update", str(path)]) == 2
    outcome = UpdateOutcome.read(tmp_path / "updates" / "result.json")
    assert not outcome.installed and outcome.version is None
    assert "Unreadable update manifest" in (tmp_path / "updates" / "helper.log").read_text()


def test_file_swap_on_windows_renames_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(helper_module.sys, "platform", "win32")
    # The one global sys.platform is patched, so the real wait would call another OS's API.
    monkeypatch.setattr(UpdateProcesses, "wait_for_exit", staticmethod(lambda _pids, _t: True))
    path = file_manifest(tmp_path)
    assert run(path) == (0, UpdateOutcome(True, "1.2.0", None))
    assert sorted(entry.name for entry in (tmp_path / "t").iterdir()) == ["Demo.exe"]
    assert (tmp_path / "t" / "Demo.exe").read_bytes() == b"new build"
    assert "Installed 1.2.0" in (tmp_path / "updates" / "helper.log").read_text()


def test_file_swap_on_linux_replaces_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(helper_module.sys, "platform", "linux")
    # The one global sys.platform is patched, so the real wait would call another OS's API.
    monkeypatch.setattr(UpdateProcesses, "wait_for_exit", staticmethod(lambda _pids, _t: True))
    path = file_manifest(tmp_path)
    assert run(path)[0] == 0
    target = tmp_path / "t" / "Demo.exe"
    assert target.read_bytes() == b"new build"
    assert sorted(entry.name for entry in (tmp_path / "t").iterdir()) == ["Demo.exe"]
    if not ON_WINDOWS:
        assert stat.S_IMODE(target.stat().st_mode) == 0o755


def test_folder_swap(tmp_path):
    path = folder_manifest(tmp_path)
    assert run(path)[0] == 0
    programs = tmp_path / "Programs"
    assert sorted(entry.name for entry in programs.iterdir()) == ["DemoApp"]
    assert (programs / "DemoApp" / "DemoApp.exe").read_bytes() == b"new"
    assert (programs / "DemoApp" / "lib" / "y.dll").read_bytes() == b"n"
    assert not (programs / "DemoApp" / "x.dll").exists()


def test_failed_second_rename_rolls_the_file_back(tmp_path, monkeypatch):
    monkeypatch.setattr(helper_module.sys, "platform", "win32")
    # The one global sys.platform is patched, so the real wait would call another OS's API.
    monkeypatch.setattr(UpdateProcesses, "wait_for_exit", staticmethod(lambda _pids, _t: True))
    path = file_manifest(tmp_path, swap_seconds=0.3)
    new = tmp_path / "t" / "Demo.exe.new"
    original = Path.replace

    def replace(self, destination):
        if self == new:
            raise PermissionError("held by a scanner")
        return original(self, destination)

    monkeypatch.setattr(Path, "replace", replace)
    code, outcome = run(path)
    assert code == 1
    assert not outcome.installed
    assert "held by a scanner" in (outcome.message or "")
    assert sorted(entry.name for entry in (tmp_path / "t").iterdir()) == ["Demo.exe"]
    assert (tmp_path / "t" / "Demo.exe").read_bytes() == b"old build"


def test_failed_second_rename_rolls_the_folder_back(tmp_path, monkeypatch):
    path = folder_manifest(tmp_path, swap_seconds=0.3)
    staged = tmp_path / "Programs" / "DemoApp.staged"
    original = Path.rename

    def rename(self, destination):
        if self == staged:
            raise PermissionError("held by a host")
        return original(self, destination)

    monkeypatch.setattr(Path, "rename", rename)
    assert run(path)[0] == 1
    programs = tmp_path / "Programs"
    assert sorted(entry.name for entry in programs.iterdir()) == ["DemoApp", "DemoApp.staged"]
    assert (programs / "DemoApp" / "DemoApp.exe").read_bytes() == b"old"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows holds open files")
def test_held_file_exhausts_the_retry_and_keeps_the_target(tmp_path):
    path = file_manifest(tmp_path, swap_seconds=0.6)
    target = tmp_path / "t" / "Demo.exe"
    started = time.monotonic()
    with target.open("rb"):
        code, outcome = run(path)
    assert time.monotonic() - started >= 0.5
    assert code == 1 and not outcome.installed
    assert target.read_bytes() == b"old build"
    assert sorted(entry.name for entry in (tmp_path / "t").iterdir()) == ["Demo.exe"]


def test_app_that_does_not_exit_fails_without_swap(tmp_path):
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        path = file_manifest(tmp_path, wait_pids=(app.pid,), wait_seconds=0.3)
        assert run(path) == (1, UpdateOutcome(False, "1.2.0", "The application did not exit."))
    finally:
        app.kill()
        app.wait()
    assert (tmp_path / "t" / "Demo.exe").read_bytes() == b"old build"


def test_relaunch_argv_cwd_and_environment(tmp_path, monkeypatch):
    from .. import processes

    calls: list[tuple[list[str], dict]] = []

    def popen(argv, **options):
        calls.append((argv, options))

    monkeypatch.setattr(processes.subprocess, "Popen", popen)
    # A file swap exists only on Windows and Linux; a macOS runner takes the Linux path here.
    monkeypatch.setattr(helper_module.sys, "platform", "linux")
    monkeypatch.setattr(UpdateProcesses, "wait_for_exit", staticmethod(lambda _pids, _t: True))
    path = file_manifest(tmp_path, relaunch=True, relaunch_args=("--settings", "a b"))
    assert run(path)[0] == 0
    target = tmp_path / "t" / "Demo.exe"
    argv, options = calls[0]
    assert argv == [str(target), "--settings", "a b"]
    assert options["cwd"] == target.parent
    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_folder_relaunch_runs_the_executable(tmp_path, spawned):
    path = folder_manifest(tmp_path, relaunch=True)
    assert run(path)[0] == 0
    program = tmp_path / "Programs" / "DemoApp" / "DemoApp.exe"
    assert spawned[0][:2] == ([str(program)], program.parent)


def test_failed_swap_relaunches_the_old_build_after_writing_the_result(tmp_path, monkeypatch):
    path = folder_manifest(tmp_path, relaunch=True, swap_seconds=0.3)
    staged = tmp_path / "Programs" / "DemoApp.staged"
    original = Path.rename

    def rename(self, destination):
        if self == staged:
            raise PermissionError("held")
        return original(self, destination)

    monkeypatch.setattr(Path, "rename", rename)
    result_at_spawn: list[bool] = []

    def spawn(argv, cwd):
        result_at_spawn.append((tmp_path / "updates" / "result.json").is_file())

    monkeypatch.setattr(UpdateProcesses, "spawn_detached", staticmethod(spawn))
    assert run(path)[0] == 1
    assert result_at_spawn == [True]
    assert (tmp_path / "Programs" / "DemoApp" / "DemoApp.exe").read_bytes() == b"old"


def test_no_relaunch_when_not_asked(tmp_path, spawned, monkeypatch):
    # A file swap exists only on Windows and Linux; a macOS runner takes the Linux path here.
    monkeypatch.setattr(helper_module.sys, "platform", "linux")
    monkeypatch.setattr(UpdateProcesses, "wait_for_exit", staticmethod(lambda _pids, _t: True))
    assert run(file_manifest(tmp_path))[0] == 0
    assert spawned == []


def test_macos_raises_and_keeps_the_target(tmp_path, monkeypatch):
    monkeypatch.setattr(helper_module.sys, "platform", "darwin")
    # The one global sys.platform is patched, so the real wait would call another OS's API.
    monkeypatch.setattr(UpdateProcesses, "wait_for_exit", staticmethod(lambda _pids, _t: True))
    path = file_manifest(tmp_path)
    with pytest.raises(ValueError, match="not supported on darwin"):
        UpdateHelper.swap(UpdateManifest.read(path))
    code, outcome = run(path)
    assert code == 1 and not outcome.installed
    assert sorted(entry.name for entry in (tmp_path / "t").iterdir()) == ["Demo.exe"]
    assert (tmp_path / "t" / "Demo.exe").read_bytes() == b"old build"


def relaunch_script(folder: Path, name: str) -> Path:
    match sys.platform:
        case "win32":
            script = folder / f"{name}.cmd"
            script.write_text('@echo off\r\necho relaunched %*> "%~dp0marker.txt"\r\n')
        case "linux" | "darwin":
            script = folder / f"{name}.sh"
            script.write_text('#!/bin/sh\necho "relaunched $*" > "$(dirname "$0")/marker.txt"\n')
            script.chmod(0o755)
        case _:
            raise ValueError(f"Unsupported platform: {sys.platform}")
    return script


def helper_command() -> tuple[list[str], Path]:
    module = UpdateHelper.__module__
    top = Path(sys.modules[module].__file__ or "").resolve().parents[module.count(".")]
    code = ("import importlib, sys; "
            f"sys.exit(importlib.import_module({module!r}).UpdateHelper.main(sys.argv[1:]))")
    return [sys.executable, "-c", code], top


@pytest.mark.skipif(sys.platform == "darwin", reason="no self-install on macOS")
def test_real_helper_process_waits_swaps_and_relaunches(tmp_path):
    target_folder = tmp_path / "t"
    target_folder.mkdir()
    target = relaunch_script(target_folder, "app")
    target.write_text(target.read_text().replace("relaunched", "old build"))
    source = relaunch_script(tmp_path, "app")
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    # Reaped while the helper waits: an exited child that nobody reaps still looks alive on POSIX.
    threading.Thread(target=app.wait, daemon=True).start()
    path = write_manifest(tmp_path, kind="file", source=source, target=target, executable=None,
                          wait_pids=(app.pid,), wait_seconds=30.0, swap_seconds=10.0,
                          relaunch=True, relaunch_args=("--settings",))
    command, top = helper_command()
    completed = subprocess.run([*command, "--apply-update", str(path)], cwd=top, timeout=60,
                               env={**os.environ, "PYTHONPATH": str(top)})
    app.wait()
    assert completed.returncode == 0, (path.with_name("helper.log")).read_text()
    assert UpdateOutcome.read(path.with_name("result.json")).installed
    marker = target_folder / "marker.txt"
    deadline = time.monotonic() + 15
    while not marker.is_file() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.read_text().strip() == "relaunched --settings"
    assert not (target_folder / f"{target.name}.old").exists()
