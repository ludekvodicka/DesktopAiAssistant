import copy
import json
from pathlib import Path
import time
from PySide6.QtCore import QObject, QPointF, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication
import desktop_ai_assistant
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.controller import Controller


def named_item(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        result = named_item(child, name)
        if result:
            return result
    return None


def test_macro_frames_and_busy_footer_contain_their_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    qml = QQmlApplicationEngine()
    qml.rootContext().setContextProperty("backend", backend)
    qml.load(QUrl.fromLocalFile(str(Path(desktop_ai_assistant.__file__).parent / "qml/Settings.qml")))
    window = qml.rootObjects()[0]
    try:
        window.setProperty("page", 2)
        window.setProperty("macroIndex", 1)
        backend._busy = True
        backend.set_status("Editing with claude…")
        window.show()
        for width, height in ((1100, 780), (940, 660)):
            window.setWidth(width)
            window.setHeight(height)
            for _ in range(12):
                app.processEvents()
                time.sleep(0.01)
            step = named_item(window.contentItem(), "macroStep0")
            actions = named_item(window.contentItem(), "macroActions")
            assert step.height() >= 150
            assert step.mapToScene(QPointF(0, step.height())).y() <= actions.mapToScene(QPointF()).y()
            panel = named_item(window.contentItem(), "statusPanel")
            stop = named_item(window.contentItem(), "statusStop")
            assert stop.mapToItem(panel, QPointF()).y() >= 0
            assert stop.mapToItem(panel, QPointF(0, stop.height())).y() <= panel.height()
    finally:
        backend._busy = False
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)
        import shiboken6
        shiboken6.delete(qml)
