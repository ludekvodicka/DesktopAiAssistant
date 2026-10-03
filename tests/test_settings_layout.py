import copy
import json
from pathlib import Path
import time
from PySide6.QtCore import QObject, QMetaObject, QPointF, Q_ARG, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import desktop_ai_assistant
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.controller import Controller
from desktop_ai_assistant.updates import Updates


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
    qml.rootContext().setContextProperty("updates", Updates.create(app, busy=lambda: False))
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


def texts(item):
    value = item.property("text")
    return ([value] if isinstance(value, str) else []) + [x for child in item.childItems() for x in texts(child)]


def test_language_settings_pickers_and_history_follow_the_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12", bindings=[{"key": "Ctrl+Alt+F10", "action": "translate_selection", "profile": ""}])
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    backend.history.create({"action": "translate_region", "source": "test.exe", "original": "", "result": ""})
    backend.refresh()
    qml = QQmlApplicationEngine()
    warnings = []
    qml.warnings.connect(lambda items: warnings.extend(str(item) for item in items))
    qml.rootContext().setContextProperty("backend", backend)
    qml.rootContext().setContextProperty("updates", Updates.create(app, busy=lambda: False))
    qml.load(QUrl.fromLocalFile(str(Path(desktop_ai_assistant.__file__).parent / "qml/Settings.qml")))
    window = qml.rootObjects()[0]

    def settle():
        for _ in range(12):
            app.processEvents()
            time.sleep(0.01)

    def choices(name):
        return [x["name"] for x in named_item(window.contentItem(), name).property("model")]

    try:
        window.show()
        window.setProperty("page", 6)
        settle()
        boxes = [named_item(window.contentItem(), "ruleBox_" + x).property("title") for x in ("english_formal", "english_social", "native", "translate", "explain")]
        assert boxes == ["Fix EN · Formal", "Fix EN · Social", "Fix CZ", "Translate to CZ", "Explain in CZ"]
        language = named_item(window.contentItem(), "nativeLanguage")
        assert language.property("currentText") == "Czech (CZ)"
        language.setProperty("currentIndex", [x["code"] for x in backend.languages].index("de"))
        assert QMetaObject.invokeMethod(language, "activated", Q_ARG(int, language.property("currentIndex")))
        settle()
        assert window.property("draft").toVariant()["nativeLanguage"] == "de"
        assert named_item(window.contentItem(), "ruleBox_native").property("title") == "Fix DE"
        assert named_item(window.contentItem(), "ruleBox_translate").property("title") == "Translate to DE"
        assert named_item(window.contentItem(), "ruleBox_explain").property("title") == "Explain in DE"
        for key in ("native", "translate", "explain"):
            area = named_item(window.contentItem(), "rules_" + key)
            assert QMetaObject.invokeMethod(area, "forceActiveFocus")
            settle()
            for key_code in (Qt.Key_D, Qt.Key_U):
                QTest.keyClick(window, key_code)
            settle()
            assert window.property("draft").toVariant()["rules"][key] == "du"
        assert backend.config.value["nativeLanguage"] == "cs"
        window.setProperty("page", 3)
        settle()
        assert choices("shortcutAction0")[:4] == ["Fix EN · Formal", "Fix EN · Social", "Fix DE", "Translate to DE · from selection"]
        shortcut = choices("shortcutAction0")
        assert {"Translate to DE · from screen region", "Translate to DE · from clipboard"} <= set(shortcut)
        assert not {"Translate to DE", "Fix EN", "System"} & set(shortcut)
        window.setProperty("page", 2)
        window.setProperty("macroIndex", 0)
        settle()
        assert choices("macroStepAction0") == ["Fix EN · Formal", "Fix EN · Social", "Fix DE"]
        window.setProperty("page", 4)
        settle()
        assert window.property("historyRows").toVariant()[0]["displayAction"] == "Translate to CZ · from screen region"
        assert "Translate to CZ · from screen region" in texts(window.contentItem())
        assert not warnings, warnings
    finally:
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)
        import shiboken6
        shiboken6.delete(qml)
