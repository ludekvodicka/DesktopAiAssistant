import threading
import time
import ctypes
import win32con
import win32gui
import win32api
import win32process
import pytest
from desktop_ai_assistant.windows_text import WindowsText
from desktop_ai_assistant.winapi import foreground


def test_real_windows_edit_selection_whole_and_conflict():
    parent = win32gui.CreateWindowEx(0, "STATIC", "Desktop AI owned integration test", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                   50, 50, 500, 260, 0, 0, 0, None)
    edit = win32gui.CreateWindowEx(0, "EDIT", "Hello world", win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_MULTILINE,
                                 10, 10, 450, 180, parent, 1, 0, None)
    foreground_thread, _ = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
    own_thread = win32api.GetCurrentThreadId()
    if own_thread != foreground_thread:
        win32process.AttachThreadInput(own_thread, foreground_thread, True)
    try:
        win32gui.SetForegroundWindow(parent)
        win32gui.SetFocus(edit)
    finally:
        if own_thread != foreground_thread:
            win32process.AttachThreadInput(own_thread, foreground_thread, False)
    win32gui.SendMessage(edit, win32con.EM_SETSEL, 6, 11)
    adapter = WindowsText()
    results = []
    def exercise():
        try:
            target = foreground()
            snapshot = adapter.capture(target)
            assert snapshot["text"] == "world"
            with pytest.raises(RuntimeError, match="User input"):
                adapter.apply(snapshot, "WRONG", -1)
            after = adapter.apply(snapshot, "Earth")
            assert after["full"] == "Hello Earth"
            with pytest.raises(RuntimeError):
                adapter.apply(snapshot, "WRONG")
            whole = adapter.capture(target)
            assert whole["text"] == "Hello Earth"
            after = adapter.apply(whole, "Hello\r\nEarth")
            assert after["full"] == "Hello\r\nEarth"
        except BaseException as error:
            results.append(error)
    thread = threading.Thread(target=exercise)
    thread.start()
    deadline = time.monotonic() + 25
    try:
        while thread.is_alive() and time.monotonic() < deadline:
            win32gui.PumpWaitingMessages()
            time.sleep(0.005)
        assert not thread.is_alive(), "Editor integration timed out"
        if results:
            raise results[0]
    finally:
        adapter.close()
        win32gui.DestroyWindow(parent)
