from pathlib import Path
import copy
import json
import time
import win32api
import win32gui
import win32process
import win32con
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication
from desktop_ai_assistant.controller import Controller
from desktop_ai_assistant.config import DEFAULT
import desktop_ai_assistant


def test_real_overlay_does_not_take_foreground(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    view = QQuickView()
    parent = win32gui.CreateWindowEx(0, "STATIC", "Owned overlay focus test", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                   100, 100, 400, 200, 0, 0, 0, None)
    thread, _ = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
    own = win32api.GetCurrentThreadId()
    if thread != own:
        win32process.AttachThreadInput(own, thread, True)
    try:
        win32gui.SetForegroundWindow(parent)
    finally:
        if thread != own:
            win32process.AttachThreadInput(own, thread, False)
    try:
        view.setFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        view.setColor(QColor("transparent"))
        view.rootContext().setContextProperty("backend", backend)
        view.setSource(QUrl.fromLocalFile(str(Path(desktop_ai_assistant.__file__).parent / "qml/Overlay.qml")))
        assert view.status() == QQuickView.Ready
        view.show()
        for _ in range(12):
            app.processEvents()
            time.sleep(0.01)
        assert win32gui.GetForegroundWindow() == parent
        assert not view.grabWindow().isNull()
        backend.monitor.stop()
        view.visibleChanged.connect(backend.ringVisible)
        backend.hideMenu.connect(view.hide)
        backend.requestMenu.connect(view.show)
        backend.ringVisible(True)
        backend.hotkey(config["hotkey"])
        assert not view.isVisible()
        assert not backend._ring_visible
        import desktop_ai_assistant.controller as controller_module
        monkeypatch.setattr(controller_module, "foreground", lambda: {"pid": -1, "process": "test.exe"})
        backend.hotkey(config["hotkey"])
        assert view.isVisible()
        assert backend._ring_visible
    finally:
        view.close()
        import shiboken6
        shiboken6.delete(view)
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)
        win32gui.DestroyWindow(parent)
