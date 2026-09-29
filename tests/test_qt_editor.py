import threading
import time
import win32api
import win32gui
import win32process
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget, QVBoxLayout
from desktop_ai_assistant.windows_text import WindowsText
from desktop_ai_assistant.winapi import foreground


def test_qt_uia_selection_whole_and_mouse_motion():
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setWindowTitle("Owned Qt text adapter test")
    layout = QVBoxLayout(window)
    editor = QTextEdit(window)
    layout.addWidget(editor)
    editor.setPlainText("i thnk ze nevim jak to napsat")
    window.show()
    editor.setFocus()
    app.processEvents()
    own = win32api.GetCurrentThreadId()
    other, _ = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
    if own != other:
        win32process.AttachThreadInput(own, other, True)
    try:
        win32gui.SetForegroundWindow(int(window.winId()))
    finally:
        if own != other:
            win32process.AttachThreadInput(own, other, False)
    app.processEvents()
    cursor = editor.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(6, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)
    target = foreground()
    adapter = WindowsText()
    mime = app.clipboard().mimeData()
    clipboard_before = {name: bytes(mime.data(name)) for name in mime.formats()}
    errors = []
    captured = threading.Event()
    moved = threading.Event()
    mouse = win32gui.GetCursorPos()

    def exercise():
        try:
            tick = adapter.input_tick()
            selected = adapter.capture(target)
            assert selected["text"] == "thnk"
            assert not selected.get("native"), "Exercise UIA paste, not native Edit messages"
            captured.set()
            assert moved.wait(3)
            assert adapter.input_tick() == tick
            after = adapter.apply(selected, "think", tick)
            assert after["full"] == "i think ze nevim jak to napsat"
            whole = adapter.capture(target)
            assert whole["text"] == whole["full"]
            after = adapter.apply(whole, "I think I don't know how to write it.", adapter.input_tick())
            assert after["full"] == "I think I don't know how to write it."
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=exercise)
    worker.start()
    deadline = time.monotonic() + 25
    try:
        while worker.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            if captured.is_set() and not moved.is_set():
                win32api.SetCursorPos((mouse[0] + 8, mouse[1] + 8))
                moved.set()
            time.sleep(0.005)
        assert not worker.is_alive()
        if errors:
            raise errors[0]
        assert editor.toPlainText() == "I think I don't know how to write it."
        editor.undo()
        assert editor.toPlainText() == "i think ze nevim jak to napsat"
        mime = app.clipboard().mimeData()
        for name, data in clipboard_before.items():
            assert bytes(mime.data(name)) == data
    finally:
        adapter.close()
        window.close()
        win32api.SetCursorPos(mouse)
