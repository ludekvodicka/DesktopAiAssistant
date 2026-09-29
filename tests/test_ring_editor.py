import copy
import json
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, QPointF, QMetaObject, Q_ARG, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import desktop_ai_assistant
from desktop_ai_assistant.config import DEFAULT, Config, validate
from desktop_ai_assistant.controller import Controller
from test_settings_layout import named_item


def test_folders_validate_references_cycles_and_migrate_old_appearance():
    value = copy.deepcopy(DEFAULT)
    value.update(version=2, appearance={"english": {"name": "My English"}})
    value.pop("folders")
    value.pop("slotAppearance")
    migrated = validate(value)
    assert migrated["version"] == 4
    assert migrated["appearance"] == value["appearance"]
    assert migrated["slots"] == value["slots"]
    migrated["folders"] = [{"id": "one", "name": "One", "actions": ["folder:two"]}, {"id": "two", "name": "Two", "actions": ["czech"]}]
    migrated["slots"][2] = "folder:one"
    assert validate(migrated)
    migrated["folders"][1]["actions"] = ["folder:one"]
    with pytest.raises(ValueError, match="itself"):
        validate(migrated)
    migrated["folders"][1]["actions"] = ["folder:missing"]
    with pytest.raises(ValueError, match="Unknown submenu"):
        validate(migrated)


def test_click_segment_create_folder_save_and_navigate(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    monkeypatch.setattr(backend, "set_autostart", lambda enabled: None)
    qml = QQmlApplicationEngine()
    warnings = []
    qml.warnings.connect(lambda items: warnings.extend(str(item) for item in items))
    qml.rootContext().setContextProperty("backend", backend)
    qml.load(QUrl.fromLocalFile(str(Path(desktop_ai_assistant.__file__).parent / "qml/Settings.qml")))
    window = qml.rootObjects()[0]

    def click(item, position=None):
        pos = item.mapToScene(position or QPointF(item.width() / 2, item.height() / 2))
        QTest.mouseClick(window, Qt.LeftButton, pos=pos.toPoint())
        QTest.qWait(250)

    def invoke(item, method, *args):
        assert QMetaObject.invokeMethod(item, method, *[Q_ARG("QVariant", value) for value in args])
        QTest.qWait(250)

    try:
        assert backend.menu[4]["id"] == "system"
        assert backend.menu[4]["group"]
        backend.hover(4)
        assert [item["id"] for item in backend.children] == ["settings", "history", "restart"]
        assert backend.children[0]["name"] == "Open config"
        window.setProperty("page", 1)
        window.show()
        QTest.qWait(500)
        editor = named_item(window.contentItem(), "ringEditor")
        ring = named_item(window.contentItem(), "editorRing")
        click(ring, QPointF(412, 300))
        assert editor.property("selectedSlot") == 2
        picker = window.findChild(QObject, "actionPicker")
        assert not picker.property("visible")
        click(named_item(window.contentItem(), "chooseSegmentAction"))
        assert picker.property("visible")
        click(named_item(window.contentItem(), "newFolder"))
        draft = window.property("draft").toVariant()
        folder_id = draft["folders"][0]["id"]
        assert draft["slots"][2] == "folder:" + folder_id
        assert backend.config.value["slots"][2] == "", "Preview must not change live actions"
        click(named_item(window.contentItem(), "addFolderItem"))
        assert picker.property("visible")
        assert editor.property("pickerFolder") == folder_id
        invoke(editor, "assign", "english_formal")
        invoke(editor, "pick", folder_id, -1)
        invoke(editor, "createFolder")
        nested = window.property("draft").toVariant()["folders"][1]["id"]
        invoke(editor, "pick", nested, -1)
        invoke(editor, "assign", "czech")
        draft = window.property("draft").toVariant()
        draft["slotAppearance"][2] = {"name": "Writing"}
        assert backend.saveSettings(json.dumps(draft))
        assert Config().value == backend.config.value
        assert backend.menu[2]["name"] == "Writing"
        backend.hover(2)
        assert [item["id"] for item in backend.children] == ["english_formal", "folder:" + nested]
        backend.enterChild(1)
        assert backend.children[0]["id"] == "czech"
        assert backend.canGoBack
        backend.backFolder()
        assert backend.children[0]["id"] == "english_formal"
        assert not backend.canGoBack
        invoke(editor, "selectSlot", 2)
        invoke(editor, "moveChild", 0, 1)
        assert window.property("draft").toVariant()["folders"][0]["actions"] == ["folder:" + nested, "english_formal"]
        editor.setProperty("folderPath", [folder_id, nested])
        invoke(editor, "deleteFolder")
        assert window.property("draft").toVariant()["folders"][0]["actions"] == ["english_formal"]
        invoke(editor, "pick", folder_id, -1)
        invoke(editor, "assign", "macro:english")
        window.setProperty("macroIndex", 0)
        invoke(window, "removeMacro")
        draft = window.property("draft").toVariant()
        assert draft["folders"][0]["actions"] == ["english_formal"]
        assert backend.saveSettings(json.dumps(draft))
        window.setProperty("page", 6)
        QTest.qWait(100)
        assert named_item(window.contentItem(), "languageSettings").isVisible()
        assert not warnings, warnings
    finally:
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)
        import shiboken6
        shiboken6.delete(qml)
