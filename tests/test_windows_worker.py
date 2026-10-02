import multiprocessing as mp
import os
import time
from types import SimpleNamespace
import pytest
from desktop_ai_assistant import windows_text, winapi


def crash_worker(connection, revision):
    connection.recv()
    os._exit(42)


def reply_worker(connection, revision):
    try:
        while True:
            request = connection.recv()
            if request["op"] == "close":
                return
            connection.send({"ok": True, "value": {"text": "synthetic result"}})
    finally:
        connection.close()


@pytest.mark.parametrize("operation,message", [("capture", "before text could be read"), ("apply", "may already have been inserted")])
def test_worker_crash_is_explained_and_next_action_gets_a_fresh_worker(monkeypatch, operation, message):
    monkeypatch.setattr(windows_text, "InputMonitor", lambda: SimpleNamespace(revision=mp.Value("q", 0), close=lambda: None))
    monkeypatch.setattr(windows_text, "_worker", crash_worker)
    adapter = windows_text.WindowsText()
    try:
        with pytest.raises(RuntimeError, match=message):
            adapter.call({"op": operation})
        assert adapter.process is None
        assert adapter.connection is None
        monkeypatch.setattr(windows_text, "_worker", reply_worker)
        assert adapter.call({"op": "capture"}) == {"text": "synthetic result"}
    finally:
        adapter.close()


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(windows_text, "InputMonitor", lambda: SimpleNamespace(revision=mp.Value("q", 0), close=lambda: None))
    adapter = windows_text.WindowsText()
    calls = []
    monkeypatch.setattr(adapter, "call", lambda request: calls.append(request) or {"text": "copied"})
    yield adapter, calls
    adapter.close()


def test_copy_selection_refuses_a_terminal_without_starting_the_worker(adapter):
    adapter, calls = adapter
    with pytest.raises(RuntimeError, match="Terminal text"):
        adapter.copy_selection({"process": "WindowsTerminal.exe"})
    assert calls == []
    assert adapter.process is None


def test_copy_selection_waits_for_modifiers_outside_the_worker(adapter, monkeypatch):
    adapter, calls = adapter
    monkeypatch.setattr(winapi.user32, "GetAsyncKeyState", lambda vk: -32768)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="Release modifier keys"):
        adapter.copy_selection({"process": "notepad.exe"})
    assert 1.4 < time.monotonic() - started < 2
    assert calls == []
    released = time.monotonic() + 0.2
    monkeypatch.setattr(winapi.user32, "GetAsyncKeyState", lambda vk: -32768 if time.monotonic() < released else 0)
    assert adapter.copy_selection({"process": "notepad.exe"}) == {"text": "copied"}
    assert calls == [{"op": "copy", "target": {"process": "notepad.exe"}}]


def test_copy_selection_refuses_a_terminal_by_window_class(adapter, monkeypatch):
    adapter, calls = adapter
    monkeypatch.setattr(windows_text.win32gui, "GetClassName", lambda hwnd: "mintty")
    with pytest.raises(RuntimeError, match="Terminal text"):
        adapter.copy_selection({"process": "unknown.exe", "hwnd": 5})
    assert calls == []
