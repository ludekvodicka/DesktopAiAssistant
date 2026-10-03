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
    assert calls == [{"op": "copy", "target": {"process": "notepad.exe"}, "plain": False}]


def test_paste_refuses_a_terminal_without_starting_the_worker(adapter):
    adapter, calls = adapter
    with pytest.raises(RuntimeError, match="Terminal input"):
        adapter.paste({"process": "pwsh.exe"}, "text", 1)
    assert calls == [] and adapter.process is None


@pytest.mark.skipif(os.environ.get("DESKTOP_AI_LIVE_TESTS") != "1" or not os.path.exists(r"C:\Program Files\Notepad++\notepad++.exe"),
                    reason="needs DESKTOP_AI_LIVE_TESTS=1 and Notepad++")
def test_scintilla_reads_and_replaces_the_selection_in_notepad_plus_plus(tmp_path):
    import ctypes as C
    import subprocess
    import win32gui
    import win32process
    from desktop_ai_assistant.scintilla import Scintilla
    sample = tmp_path / "sample.txt"
    sample.write_bytes("Příliš žluťoučký kůň\r\nhelo world\r\n".encode("utf-8"))
    process = subprocess.Popen([r"C:\Program Files\Notepad++\notepad++.exe", "-multiInst", "-nosession", "-notabbar", str(sample)])

    def message(hwnd, code, wparam=0, lparam=0):
        result = C.c_size_t()
        if not C.windll.user32.SendMessageTimeoutW(hwnd, code, C.c_size_t(wparam), C.c_ssize_t(lparam), 2, 1000, C.byref(result)):
            raise RuntimeError("no response")
        return result.value

    def editors():
        found = []
        def each(hwnd, _):
            if win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid and win32gui.GetClassName(hwnd) == "Notepad++":
                win32gui.EnumChildWindows(hwnd, lambda h, _: found.append(h) if win32gui.GetClassName(h) == "Scintilla" and win32gui.IsWindowVisible(h) else None, None)
            return True
        win32gui.EnumWindows(each, None)
        return found

    try:
        deadline = time.monotonic() + 10
        while not editors() and time.monotonic() < deadline:
            time.sleep(0.2)
        time.sleep(0.5)
        editor = Scintilla(editors()[0], message)
        try:
            full, start, end = editor.read()
            assert full == "Příliš žluťoučký kůň\r\nhelo world\r\n" and start == end
            first = len(full[:22].encode("utf-8"))
            message(editor.hwnd, 2160, first, first + 4)
            full, start, end = editor.read()
            assert (start, end) == (22, 26)
            editor.replace(full, start, end, "hello ✓")
            assert editor.read()[0] == "Příliš žluťoučký kůň\r\nhello ✓ world\r\n"
        finally:
            editor.close()
    finally:
        process.kill()
        process.wait()


def test_copy_selection_refuses_a_terminal_by_window_class(adapter, monkeypatch):
    adapter, calls = adapter
    monkeypatch.setattr(windows_text.win32gui, "GetClassName", lambda hwnd: "mintty")
    with pytest.raises(RuntimeError, match="Terminal text"):
        adapter.copy_selection({"process": "unknown.exe", "hwnd": 5})
    assert calls == []
