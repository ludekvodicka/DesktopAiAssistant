import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import win32api
import win32con
import win32gui
import win32process
import pytest
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.history import decrypt
from desktop_ai_assistant.providers import terminate
from desktop_ai_assistant.winapi import foreground, send_keys


@pytest.mark.parametrize("packaged", [False, True])
def test_app_hotkey_uia_cli_and_history(tmp_path, packaged):
    flag = "DESKTOP_AI_FROZEN_TESTS" if packaged else "DESKTOP_AI_SOURCE_TESTS"
    if os.environ.get(flag) != "1":
        pytest.skip("Explicit application and live provider check")
    executable = Path(__file__).resolve().parents[1] / "dist/DesktopAiAssistant/DesktopAiAssistant.exe"
    settings = copy.deepcopy(DEFAULT)
    settings.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    settings["bindings"] = [{"key": "Ctrl+Alt+F9", "action": "english_formal", "profile": ""}]
    (tmp_path / "settings.json").write_text(json.dumps(settings), "utf-8")
    env = dict(os.environ, DESKTOP_AI_DATA=str(tmp_path))
    command = [str(executable)] if packaged else [sys.executable, "-m", "desktop_ai_assistant"]
    process = subprocess.Popen(command, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    parent = 0
    mouse = win32gui.GetCursorPos()
    moved = False
    try:
        time.sleep(2)
        assert process.poll() is None, "Packaged application exited at startup"
        parent = win32gui.CreateWindowEx(0, "STATIC", "Owned packaged AI integration", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                       100, 100, 540, 230, 0, 0, 0, None)
        edit = win32gui.CreateWindowEx(0, "EDIT", "Hello, I has a meeting tomorrow.", win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_MULTILINE,
                                     10, 10, 500, 140, parent, 1, 0, None)
        thread, _ = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
        own = win32api.GetCurrentThreadId()
        if thread != own:
            win32process.AttachThreadInput(own, thread, True)
        try:
            win32gui.SetForegroundWindow(parent)
            win32gui.SetFocus(edit)
        finally:
            if thread != own:
                win32process.AttachThreadInput(own, thread, False)
        target = foreground()
        send_keys("Ctrl+Alt+F9", target)
        deadline = time.monotonic() + 100
        row = None
        while time.monotonic() < deadline:
            win32gui.PumpWaitingMessages()
            if (tmp_path / "history.sqlite3").exists():
                with sqlite3.connect(tmp_path / "history.sqlite3") as db:
                    row = db.execute("SELECT status,payload FROM jobs ORDER BY created DESC LIMIT 1").fetchone()
                if row and row[0] not in ("running", "writing"):
                    break
                if row and row[0] == "running" and not packaged and not moved:
                    win32api.SetCursorPos((mouse[0] + 8, mouse[1] + 8))
                    moved = True
            time.sleep(0.01)
        assert row, "The global shortcut did not create a text job"
        payload = decrypt(row[1])
        assert row[0] == "applied", payload.get("error", row[0])
        assert payload["original"] == "Hello, I has a meeting tomorrow."
        assert "I have a meeting tomorrow" in payload["result"]
        assert win32gui.GetWindowText(edit) == payload["result"]
        if not packaged:
            assert moved
    finally:
        terminate(process)
        process.wait(5)
        if parent:
            win32gui.DestroyWindow(parent)
        win32api.SetCursorPos(mouse)
