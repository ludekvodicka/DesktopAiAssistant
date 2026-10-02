import subprocess
import sys
import time

import pytest

from .. import processes
from ..processes import UpdateProcesses

ABSENT_PID = 2_147_483_644


def test_waits_for_a_real_short_lived_child():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    started = time.monotonic()
    try:
        assert UpdateProcesses.wait_for_exit([child.pid], 20)
    finally:
        child.wait()
    assert time.monotonic() - started >= 0.2


def test_times_out_while_the_child_runs():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert not UpdateProcesses.wait_for_exit([child.pid], 0.2)
    finally:
        child.kill()
        child.wait()


def test_a_missing_pid_counts_as_gone():
    assert UpdateProcesses.wait_for_exit([ABSENT_PID], 1)


def test_unsupported_platform_raises(monkeypatch):
    monkeypatch.setattr(processes.sys, "platform", "sunos5")
    with pytest.raises(ValueError, match="Unsupported platform"):
        UpdateProcesses.wait_for_exit([], 1)
    with pytest.raises(ValueError, match="Unsupported platform"):
        UpdateProcesses.spawn_detached(["x"], cwd=None)


def test_spawn_detached_starts_a_real_program(tmp_path):
    marker = tmp_path / "marker.txt"
    # Written to a side file and renamed, so the test never reads a created but still empty file.
    code = (f"import os; open({str(marker) + '.part'!r}, 'w').write('started'); "
            f"os.replace({str(marker) + '.part'!r}, {str(marker)!r})")
    UpdateProcesses.spawn_detached([sys.executable, "-c", code], cwd=tmp_path)
    deadline = time.monotonic() + 15
    while not marker.is_file() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.read_text() == "started"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows job objects")
def test_breakaway_refusal_falls_back(monkeypatch, tmp_path):
    calls: list[int] = []

    def popen(argv, creationflags, **options):
        calls.append(creationflags)
        assert options["cwd"] == tmp_path
        assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        if creationflags & subprocess.CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError("access denied")

    monkeypatch.setattr(processes.subprocess, "Popen", popen)
    UpdateProcesses.spawn_detached(["demo.exe", "--x"], cwd=tmp_path)
    assert len(calls) == 2
    assert calls[0] & subprocess.CREATE_BREAKAWAY_FROM_JOB
    assert not calls[1] & subprocess.CREATE_BREAKAWAY_FROM_JOB
    assert calls[1] & subprocess.DETACHED_PROCESS


def test_posix_spawn_starts_a_new_session(monkeypatch, tmp_path):
    calls: list[dict] = []
    monkeypatch.setattr(processes.sys, "platform", "linux")
    monkeypatch.setattr(processes.subprocess, "Popen",
                        lambda argv, **options: calls.append({"argv": argv, **options}))
    UpdateProcesses.spawn_detached(["demo", "--x"], cwd=tmp_path)
    assert calls[0]["argv"] == ["demo", "--x"]
    assert calls[0]["start_new_session"] is True
    assert calls[0]["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize(("stat_line", "zombie"), [
    ("4242 (my app (2)) Z 1 4242 4242 0 -1", True),
    ("4242 (my app) S 1 4242 4242 0 -1", False),
])
def test_zombie_state_is_read_after_the_command_name(monkeypatch, stat_line, zombie):
    monkeypatch.setattr(processes.Path, "read_text", lambda _self, *_args, **_kw: stat_line)
    assert UpdateProcesses._is_zombie(4242) is zombie


def test_no_proc_entry_is_not_a_zombie(monkeypatch):
    def missing(_self, *_args, **_kw):
        raise FileNotFoundError

    monkeypatch.setattr(processes.Path, "read_text", missing)
    assert UpdateProcesses._is_zombie(4242) is False
