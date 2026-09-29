import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil
import pytest
import win32api
import win32con
import win32gui
import win32process
from PySide6.QtCore import QLockFile
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.providers import terminate
from desktop_ai_assistant.winapi import foreground, send_keys


@pytest.mark.parametrize("batch", [False, True])
def test_restart_releases_instance_and_starts_new_process(tmp_path, batch):
    settings = copy.deepcopy(DEFAULT)
    settings.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    settings["bindings"] = [{"key": "Ctrl+Alt+F9", "action": "restart", "profile": ""}]
    (tmp_path / "settings.json").write_text(json.dumps(settings), "utf-8")
    env = dict(os.environ, DESKTOP_AI_DATA=str(tmp_path))
    env.pop("DESKTOP_AI_RUN_LOOP", None)
    project = Path(__file__).resolve().parents[1]
    command = ["cmd.exe", "/d", "/c", str(project / "run.bat")] if batch else [sys.executable, "-m", "desktop_ai_assistant", "--settings"]
    process = subprocess.Popen(command, cwd=project, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    lock = QLockFile(str(tmp_path / "instance.lock"))
    pids = set()
    parent = 0

    def wait_pid(previous=0):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            win32gui.PumpWaitingMessages()
            pid, _, _ = lock.getLockInfo()
            if pid > 0 and pid != previous and psutil.pid_exists(pid):
                pids.add(pid)
                time.sleep(0.8)
                return pid
            time.sleep(0.03)
        raise AssertionError("Restart did not acquire the instance lock with a new PID")

    try:
        first = wait_pid()
        parent = win32gui.CreateWindowEx(0, "STATIC", "Owned restart test", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                       50, 50, 300, 160, 0, 0, 0, None)
        own = win32api.GetCurrentThreadId()
        other, _ = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
        if own != other:
            win32process.AttachThreadInput(own, other, True)
        try:
            win32gui.SetForegroundWindow(parent)
        finally:
            if own != other:
                win32process.AttachThreadInput(own, other, False)
        send_keys("Ctrl+Alt+F9", foreground())
        second = wait_pid(first)
        assert second != first
        assert not psutil.pid_exists(first)
        assert psutil.Process(second).is_running()
    finally:
        terminate(process)
        process.wait(5)
        for pid in pids:
            try:
                owned = psutil.Process(pid)
                for child in owned.children(recursive=True):
                    child.kill()
                owned.kill()
                owned.wait(5)
            except psutil.NoSuchProcess:
                pass
        if parent:
            win32gui.DestroyWindow(parent)
