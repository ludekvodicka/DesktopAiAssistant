import threading
import time
import ctypes
import pythoncom
import win32clipboard
import win32con
import win32gui
import win32api
import win32process
import pytest
from desktop_ai_assistant.clipboard import Clipboard
from desktop_ai_assistant.engine import Engine
from desktop_ai_assistant.windows_text import WindowsText
from desktop_ai_assistant.winapi import foreground


def open_edit(style):
    parent = win32gui.CreateWindowEx(0, "STATIC", "Desktop AI owned integration test", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                   50, 50, 500, 260, 0, 0, 0, None)
    edit = win32gui.CreateWindowEx(0, "EDIT", "Hello world", win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_MULTILINE | style,
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
    return parent


def pump(exercise):
    # The test windows belong to this thread, so it must keep pumping while the worker talks to them.
    results = []
    def run():
        try:
            exercise()
        except BaseException as error:
            results.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 25
    while thread.is_alive() and time.monotonic() < deadline:
        win32gui.PumpWaitingMessages()
        time.sleep(0.005)
    assert not thread.is_alive(), "Editor integration timed out"
    if results:
        raise results[0]


def test_real_windows_edit_selection_whole_and_conflict():
    parent = open_edit(0)
    adapter = WindowsText()
    def exercise():
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
    try:
        pump(exercise)
    finally:
        adapter.close()
        win32gui.DestroyWindow(parent)


def test_read_only_edit_is_read_without_touching_the_clipboard():
    clipboard = Clipboard()
    users, _ = clipboard.backup()
    parent = open_edit(win32con.ES_READONLY)
    adapter = WindowsText()
    engine = Engine(None, None, adapter, None, lambda message: None)
    sources = []
    try:
        clipboard.clipboard.setText("synthetic previous clipboard")
        pythoncom.OleFlushClipboard()
        sequence = win32clipboard.GetClipboardSequenceNumber()
        pump(lambda: sources.append(engine.read_selection(foreground())))
        clipboard.app.processEvents()
        assert sources == [{"kind": "selection", "format": "plain", "text": "world", "image": None, "origin": "python.exe"}]
        assert clipboard.clipboard.text() == "synthetic previous clipboard"
        assert win32clipboard.GetClipboardSequenceNumber() == sequence
    finally:
        adapter.close()
        win32gui.DestroyWindow(parent)
        clipboard.clipboard.setMimeData(users)
        pythoncom.OleFlushClipboard()
