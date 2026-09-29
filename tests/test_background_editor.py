import threading
import time
import psutil
import pytest
import win32con
import win32gui
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget, QVBoxLayout
from desktop_ai_assistant.windows_text import WindowsText
from desktop_ai_assistant.windows_text import _worker as real_worker
from desktop_ai_assistant import windows_text


def background_worker(connection, revision):
    import comtypes.client
    from desktop_ai_assistant import clipboard
    state = {}
    class Requests:
        def recv(self):
            request = connection.recv()
            state.update(capture=request["op"] == "capture", target=request.get("target"))
            return request

        def __getattr__(self, key):
            return getattr(connection, key)
    class Automation:
        def __init__(self, automation):
            self.automation = automation

        def GetFocusedElement(self):
            # Supply capture discovery without activating a window. All text
            # reads, identity checks and writes use the real UIA provider.
            root = self.automation.ElementFromHandle(state["target"]["hwnd"])
            return root.FindFirst(4, self.automation.CreatePropertyCondition(30003, 50004))

        def __getattr__(self, key):
            return getattr(self.automation, key)
    factory = comtypes.client.CreateObject
    comtypes.client.CreateObject = lambda *args, **kwargs: Automation(factory(*args, **kwargs))
    windows_text.same_target = lambda target: state["capture"]
    def no_clipboard(*args):
        raise AssertionError("Background insertion must not use the clipboard")
    clipboard.Clipboard.replace = no_clipboard
    windows_text.send_keys = no_clipboard
    real_worker(Requests(), revision)


@pytest.mark.parametrize("kind", ["native", "qt"])
@pytest.mark.parametrize("change", ["unchanged", "edited", "closed", "context"])
def test_background_write_retains_identity_content_focus_and_clipboard(kind, change, monkeypatch):
    monkeypatch.setattr(windows_text, "_worker", background_worker)
    app = QApplication.instance() or QApplication([])
    text = "Hello world 🙂"
    source = None
    source_window = None
    if kind == "native":
        hwnd = win32gui.CreateWindowEx(0x08000000, "STATIC", "Owned source", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE, -30000, -30000, 500, 260, 0, 0, 0, None)
        control = win32gui.CreateWindowEx(0, "EDIT", text, win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_MULTILINE, 10, 10, 450, 180, hwnd, 1, 0, None)
        win32gui.SendMessage(control, win32con.EM_SETSEL, 6, 11)
    elif kind == "qt":
        source_window = QWidget()
        source_window.setWindowTitle("Owned source")
        source_window.setAttribute(Qt.WA_ShowWithoutActivating)
        source_window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        source_window.move(-30000, -30000)
        layout = QVBoxLayout(source_window)
        source = QTextEdit(source_window)
        layout.addWidget(source)
        source.setPlainText(text)
        source_window.show()
        cursor = source.textCursor()
        cursor.setPosition(6)
        cursor.setPosition(11, QTextCursor.KeepAnchor)
        source.setTextCursor(cursor)
        hwnd = control = int(source_window.winId())
    else:
        raise ValueError("Unknown test editor")
    destination = QTextEdit()
    destination.setWindowTitle("Owned other work")
    destination.setAttribute(Qt.WA_ShowWithoutActivating)
    destination.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    destination.move(-30000, -30000)
    destination.setPlainText("Work elsewhere")
    destination.show()
    app.processEvents()
    process = psutil.Process()
    target = {"hwnd": hwnd, "pid": process.pid, "started": process.create_time(), "process": process.name(), "title": "Owned source"}
    adapter = WindowsText()
    captured, switched = threading.Event(), threading.Event()
    errors, results = [], []

    def exercise():
        try:
            snapshot = adapter.capture(target)
            assert snapshot["text"] == "world"
            captured.set()
            assert switched.wait(5)
            if change == "unchanged":
                after = adapter.apply(snapshot, "Earth", -1, allow_background=True)
                assert after["full"] == "Hello Earth 🙂"
                with pytest.raises(RuntimeError):
                    adapter.apply(snapshot, "WRONG", allow_background=True)
                results.append(after)
            else:
                with pytest.raises(RuntimeError):
                    adapter.apply(snapshot, "WRONG", allow_background=True)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=exercise)
    worker.start()
    deadline = time.monotonic() + 25
    try:
        while worker.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            win32gui.PumpWaitingMessages()
            if captured.is_set() and not switched.is_set():
                if change == "edited":
                    if source is None:
                        win32gui.SetWindowText(control, "Newer draft")
                    else:
                        source.setPlainText("Newer draft")
                elif change == "closed":
                    if source is None:
                        win32gui.DestroyWindow(hwnd)
                    else:
                        import shiboken6
                        shiboken6.delete(source_window)
                elif change == "context":
                    win32gui.SetWindowText(hwnd, "Different document")
                elif change != "unchanged":
                    raise ValueError("Unknown editor change")
                app.processEvents()
                destination.setPlainText("Other work continues")
                adapter.input_monitor.revision.value += 1
                switched.set()
            time.sleep(0.005)
        assert not worker.is_alive(), "Background edit timed out"
        if errors:
            raise errors[0]
        assert win32gui.GetForegroundWindow() not in (hwnd, int(destination.winId()))
        assert destination.toPlainText() == "Other work continues"
        if change == "unchanged":
            assert len(results) == 1
        elif change == "edited":
            actual = win32gui.GetWindowText(control) if source is None else source.toPlainText()
            assert actual == "Newer draft"
    finally:
        switched.set()
        adapter.close()
        if source is None:
            if win32gui.IsWindow(hwnd):
                win32gui.DestroyWindow(hwnd)
        elif change != "closed":
            source_window.close()
        destination.close()
