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
from desktop_ai_assistant import controller
from desktop_ai_assistant.controller import Controller
from desktop_ai_assistant.updates import Updates
from test_settings_layout import named_item


def test_folders_validate_references_cycles_and_migrate_old_appearance():
    value = copy.deepcopy(DEFAULT)
    value.update(version=2, appearance={"english": {"name": "My English"}})
    value.pop("folders")
    value.pop("slotAppearance")
    migrated = validate(value)
    assert migrated["version"] == 6
    assert migrated["appearance"] == value["appearance"]
    assert migrated["slots"] == value["slots"]
    migrated["folders"] = [{"id": "one", "name": "One", "actions": ["folder:two"]}, {"id": "two", "name": "Two", "actions": ["native"]}]
    migrated["slots"][2] = "folder:one"
    assert validate(migrated)
    migrated["folders"][1]["actions"] = ["folder:one"]
    with pytest.raises(ValueError, match="itself"):
        validate(migrated)
    migrated["folders"][1]["actions"] = ["folder:missing"]
    with pytest.raises(ValueError, match="Unknown submenu"):
        validate(migrated)



def test_labels_follow_native_language_without_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    monkeypatch.setattr(backend, "set_autostart", lambda enabled: None)
    try:
        assert [x["name"] for x in backend.menu[1:4]] == ["Fix EN", "Explain", "Fix CZ"]
        assert backend.menu[2]["group"] and not backend.menu[3]["group"]
        backend.hover(1)
        assert [(x["name"], x["title"]) for x in backend.children] == [("Formal", "Fix EN · Formal"), ("Social", "Fix EN · Social")]
        backend.hover(2)
        assert [x["name"] for x in backend.children] == ["Translate to CZ", "Explain in CZ"]
        backend.enterChild(0)
        assert [x["name"] for x in backend.children] == ["Selection", "Region", "Clipboard"]
        assert backend.children[0]["title"] == "Translate to CZ · from selection"
        draft = copy.deepcopy(backend.config.value)
        draft["nativeLanguage"] = "de"
        assert [x["name"] for x in backend.previewMenu(json.dumps(draft))[1:4]] == ["Fix EN", "Explain", "Fix DE"]
        assert backend.menu[3]["name"] == "Fix CZ"
        draft["nativeLanguage"] = "sk"
        assert backend.saveSettings(json.dumps(draft))
        assert [x["name"] for x in backend.menu[2:4]] == ["Explain", "Fix SK"]
        draft["appearance"] = {"native": {"name": "Opravit"}}
        assert backend.previewMenu(json.dumps(draft))[3]["name"] == "Opravit"
        assert backend.saveSettings(json.dumps(draft))
        assert backend.menu[3]["name"] == "Opravit"
    finally:
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)

def test_ring_limits_while_own_window_is_in_front_or_an_action_runs(tmp_path, monkeypatch):
    import os
    from desktop_ai_assistant import controller as controller_module
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12", bindings=[{"key": "Ctrl+Alt+Shift+F9", "action": "translate_selection", "profile": ""}])
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    front = {"hwnd": 1, "pid": os.getpid(), "started": 0, "process": "python.exe", "title": ""}
    monkeypatch.setattr(controller_module, "foreground", lambda: dict(front))
    started, menus = [], []
    monkeypatch.setattr(backend.translator, "start", lambda kind, target, operation: started.append((kind, target["process"])))
    backend.requestMenu.connect(lambda: menus.append(True))

    def enabled(slot):
        backend.hover(slot)
        if slot == 2:
            backend.hoverChild(0)
            return [x["enabled"] for x in backend.variants]
        return [x["enabled"] for x in backend.children]

    try:
        backend.hotkey("Ctrl+Alt+F11")
        assert len(menus) == 1
        assert {x["id"]: x["enabled"] for x in backend.menu} == {"macros": True, "english": True, "reader": True, "native": False,
                                                                 "system": True, "": False, "application": False}
        assert enabled(2) == [False, True, True]
        assert enabled(4) == [True, True, True]
        assert enabled(1) == [False, False]
        assert enabled(0) == [False, False]
        draft = json.dumps(backend.config.value)
        assert all(x["enabled"] for x in backend.previewChildren("translate", draft) + backend.previewChildren("english", draft))
        assert backend.previewMenu(draft)[3]["enabled"]
        backend.hotkey("Ctrl+Alt+Shift+F9")
        QTest.qWait(300)
        assert backend.status == "This shortcut is not available while an assistant window is active"
        assert started == []
        front.update(pid=1, process="notepad.exe")
        backend._busy = True
        backend.hotkey("Ctrl+Alt+F11")
        assert len(menus) == 2
        assert {x["id"]: x["enabled"] for x in backend.menu}["native"] is False
        assert enabled(2) == [True, True, True]
        assert enabled(4) == [True, True, False]
        assert enabled(1) == [False, False]
        assert enabled(0) == [False, False]
        assert not backend.action_item("jamat_new")["enabled"]
        backend.hotkey("Ctrl+Alt+Shift+F9")
        QTest.qWait(300)
        assert started == [("selection", "notepad.exe")]
        backend._busy = False
        backend.hotkey("Ctrl+Alt+F11")
        assert enabled(1) == [True, True] and backend.action_item("jamat_new")["enabled"]
    finally:
        backend._busy = False
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)


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
    qml.rootContext().setContextProperty("updates", Updates.create(app, busy=lambda: False))
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
        choices = editor.property("choices").toVariant()
        assert {"id": "translate", "name": "Translate to CZ (submenu)"} in choices
        assert {"id": "english_formal", "name": "Fix EN · Formal"} in choices
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
        assert backend.config.value["slots"][2] == "reader", "Preview must not change live actions"
        click(named_item(window.contentItem(), "addFolderItem"))
        assert picker.property("visible")
        assert editor.property("pickerFolder") == folder_id
        invoke(editor, "assign", "english_formal")
        invoke(editor, "pick", folder_id, -1)
        invoke(editor, "createFolder")
        nested = window.property("draft").toVariant()["folders"][1]["id"]
        invoke(editor, "pick", nested, -1)
        invoke(editor, "assign", "native")
        draft = window.property("draft").toVariant()
        draft["slotAppearance"][2] = {"name": "Writing"}
        assert backend.saveSettings(json.dumps(draft))
        assert Config().value == backend.config.value
        assert backend.menu[2]["name"] == "Writing"
        backend.hover(2)
        assert [item["id"] for item in backend.children] == ["english_formal", "folder:" + nested]
        backend.enterChild(1)
        assert backend.children[0]["id"] == "native"
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


def test_open_ring_takes_no_navigation_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    try:
        registered, executed = [], []
        monkeypatch.setattr(backend.hotkeys, "configure", registered.append)
        monkeypatch.setattr(backend, "execute", executed.append)
        backend.ringVisible(True)
        backend.hotkey("Enter")
        backend.hotkey("1")
        backend.ringVisible(False)
        assert registered == [] and executed == []
    finally:
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)


def test_click_outside_the_ring_closes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    try:
        hidden, under = [], [7]
        backend.hideMenu.connect(lambda: hidden.append(True))
        monkeypatch.setattr(controller, "window_at_cursor", lambda: under[0])
        backend.ring_window, backend._target = 7, {}
        backend.ringVisible(True)
        backend.watch()
        backend.windows.input_monitor.clicks.value += 1
        backend.watch()
        assert hidden == []
        under[0] = 9
        backend.windows.input_monitor.clicks.value += 1
        backend.watch()
        assert hidden == [True]
    finally:
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)


def test_language_edits_offer_clipboard_and_current_app_as_the_next_ring(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    front = {"hwnd": 1, "pid": 1, "started": 0, "process": "notepad++.exe", "title": ""}
    monkeypatch.setattr(controller, "foreground", lambda: dict(front))
    edits = []
    monkeypatch.setattr(backend.engine, "edit_via", lambda action, target, via: edits.append((action, target["process"], via)))
    try:
        backend.hotkey("Ctrl+Alt+F11")
        backend.hover(1)
        assert [x["id"] for x in backend.children] == ["english_formal", "english_social"]
        assert backend.variants == []
        backend.hoverChild(0)
        assert [(x["id"], x["name"], x["title"], x["enabled"]) for x in backend.variants] == [
            ("english_formal@app", "Current app", "Fix EN · Formal · Current app", True),
            ("english_formal@uia", "UIA plain text", "Fix EN · Formal · UIA plain text", True),
            ("english_formal@clipboard", "Clipboard", "Fix EN · Formal · Clipboard", True)]
        assert all(x["inner"] == backend.children[0]["outer"] < x["outer"] <= 298 for x in backend.variants)
        backend.hoverChild(1)
        assert backend.variants[1]["id"] == "english_social@uia"
        backend.hover(3)
        assert [x["id"] for x in backend.children] == ["native@app", "native@uia", "native@clipboard"] and backend.variants == []
        assert backend.children[0]["title"] == "Fix CZ · Current app"
        backend.hover(2)
        backend.hoverChild(0)
        assert [x["id"] for x in backend.variants] == ["translate_selection", "translate_region", "translate_clipboard"]
        backend.hoverChild(1)
        assert [x["id"] for x in backend.variants] == ["explain_selection", "explain_region", "explain_clipboard"]
        backend._limit = "own"
        assert [backend.action_item(x)["enabled"] for x in ("explain_selection", "explain_region", "explain_clipboard")] == [False, True, True]
        backend._limit = "busy"
        assert all(backend.action_item(x)["enabled"] for x in ("explain_selection", "explain_region", "explain_clipboard"))
        backend._limit = ""
        backend.execute("english_social@app")
        backend.thread.join(2)
        assert edits == [("english_social", "notepad++.exe", "app")]
        front.update(pid=os.getpid(), process="python.exe")
        backend.hotkey("Ctrl+Alt+F11")
        backend.hover(1)
        backend.hoverChild(0)
        assert [x["enabled"] for x in backend.variants] == [False, False, True]
    finally:
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)


@pytest.mark.parametrize("slot,branch,children,variants", [
    (1, 0, ["english_formal", "english_social"], ["english_formal@app", "english_formal@uia", "english_formal@clipboard"]),
    (2, 0, ["translate", "explain"], ["translate_selection", "translate_region", "translate_clipboard"]),
    (2, 1, ["translate", "explain"], ["explain_selection", "explain_region", "explain_clipboard"]),
])
def test_pointer_reaches_the_third_ring_and_clicks_a_variant(tmp_path, monkeypatch, slot, branch, children, variants):
    from PySide6.QtQuick import QQuickView
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    config = copy.deepcopy(DEFAULT)
    config.update(hotkey="Ctrl+Alt+F11", stopHotkey="Ctrl+Alt+F12")
    (tmp_path / "settings.json").write_text(json.dumps(config), "utf-8")
    app = QApplication.instance() or QApplication([])
    backend = Controller(app)
    backend.monitor.stop()
    monkeypatch.setattr(controller, "foreground", lambda: {"hwnd": 1, "pid": 1, "started": 0, "process": "notepad++.exe", "title": ""})
    executed = []
    view = QQuickView()
    view.rootContext().setContextProperty("backend", backend)
    view.setSource(QUrl.fromLocalFile(str(Path(desktop_ai_assistant.__file__).parent / "qml/Overlay.qml")))
    view.resize(720, 720)
    view.show()
    try:
        backend.hotkey("Ctrl+Alt+F11")
        monkeypatch.setattr(backend, "execute", executed.append)
        def at(radius, angle):
            from desktop_ai_assistant.geometry import point
            x, y = point(360, 360, radius, angle)
            return QPointF(x, y).toPoint()
        QTest.mouseMove(view, at(113, -90 + slot * 45))
        QTest.qWait(300)
        assert [x["id"] for x in backend.children] == children
        formal = backend.children[branch]
        QTest.mouseMove(view, at(194, (formal["start"] + formal["end"]) / 2))
        QTest.qWait(300)
        assert [x["id"] for x in backend.variants] == variants
        clipboard = backend.variants[-1]
        QTest.mouseMove(view, at(266, (clipboard["start"] + clipboard["end"]) / 2))
        QTest.mouseClick(view, Qt.LeftButton, pos=at(266, (clipboard["start"] + clipboard["end"]) / 2))
        assert executed == [variants[-1]]
    finally:
        view.close()
        backend.close()
        app.removeNativeEventFilter(backend.hotkeys)
