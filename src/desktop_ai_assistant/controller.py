import copy
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import winreg
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QDesktopServices
from PySide6.QtWidgets import QFileDialog
from .config import Config, DEFAULT, EDITS, GROUPS, TRANSLATIONS, validate, data_dir
from .history import History
from .windows_text import WindowsText
from .bridge import BrowserBridge
from .engine import Engine
from .geometry import ring_geometry, sector, point
from .winapi import Hotkeys, foreground, same_target, parse_key, user32, window_at_cursor
from .providers import clean_jobs, command, provider_env, run_process
from .translation import Translator
from .text import LANGUAGES, SOURCES

LABELS = {"english": "Fix EN", "english_formal": "Formal", "english_social": "Social",
          "translate_selection": "Selection", "translate_region": "Region", "translate_clipboard": "Clipboard",
          "macros": "Macros", "application": "Application", "system": "System", "history": "History", "settings": "Open config", "restart": "Restart app", "jamat_new": "New session", "jamat_remarkable": "Read reMarkable"}
TITLES = {"english_formal": "Fix EN · Formal", "english_social": "Fix EN · Social"}
ICONS = {"english": "Aa", "english_formal": "Aa", "english_social": "hi", "translate": "⇄", "translate_selection": "¶", "translate_region": "⬚", "translate_clipboard": "⎘",
         "macros": "⌘", "application": "▦", "system": "⚙", "history": "↶", "settings": "⚙", "restart": "↻", "jamat_new": "+", "jamat_remarkable": "▤"}
CATALOG = ["english", "english_formal", "english_social", "native", "translate", *TRANSLATIONS, "macros",
           "application", "system", "history", "settings", "restart", "jamat_new", "jamat_remarkable"]


def names(action, value):
    short, _, icon = LANGUAGES[value["nativeLanguage"]]
    if action == "native":
        return "Fix " + short, "Fix " + short, icon
    if action == "translate":
        return "Translate to " + short, "Translate to " + short, ICONS[action]
    if action in TRANSLATIONS:
        return LABELS[action], f"Translate to {short} · {SOURCES[action.removeprefix('translate_')]}", ICONS[action]
    return LABELS.get(action, action), TITLES.get(action, LABELS.get(action, action)), ICONS.get(action, "›")


class Controller(QObject):
    changed = Signal()
    notification = Signal(str)
    finished = Signal(str)
    requestMenu = Signal()
    requestSettings = Signal(str)
    requestRestart = Signal()
    hideMenu = Signal()
    config: Config
    history: History
    windows: WindowsText
    browser: BrowserBridge
    engine: Engine
    translator: Translator
    hotkeys: Hotkeys
    _status: str
    _browser_status: str
    _busy: bool
    _target: dict
    _limit: str
    _profile: dict | None
    _menu: list
    _children: list
    _folder_path: list
    _history: list
    _parent: int
    _armed: str
    _pending_restore: str
    _paused: bool
    _ring_visible: bool
    _ring_clicks: int
    ring_window: int
    thread: threading.Thread | None
    monitor: QTimer

    def __init__(self, app):
        super().__init__()
        self.config = Config()
        clean_jobs()
        self.history = History()
        self.history.prune(self.config.value["historyDays"])
        self.windows = WindowsText()
        self.browser = BrowserBridge()
        self.engine = Engine(self.config, self.history, self.windows, self.browser, self.notification.emit)
        self.translator = Translator(self.config, self.history, self.engine.read_selection)
        self.translator.ended.connect(self.refresh)
        self.hotkeys = Hotkeys(self.hotkey)
        app.installNativeEventFilter(self.hotkeys)
        self._status, self._busy, self._target, self._limit, self._profile = "Ready", False, {}, "", None
        self._menu, self._children, self._history = [], [], []
        self._folder_path = []
        self._parent, self._armed, self._pending_restore, self._paused = -1, "", "", False
        self._ring_visible, self._ring_clicks, self.ring_window = False, 0, 0
        self.thread = None
        self._browser_status = "Browser integration has not been prepared yet."
        self.notification.connect(self.set_status)
        self.finished.connect(self.job_finished)
        self.configure_hotkeys(self.config.value)
        self.refresh()
        self.monitor = QTimer(self)
        self.monitor.setInterval(100)
        self.monitor.timeout.connect(self.watch)
        self.monitor.start()

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(bool, notify=changed)
    def waitingForEditor(self):
        return self.engine.waiting_for_editor

    @Property('QVariantMap', notify=changed)
    def settings(self):
        return self.config.value

    @Property('QVariantList', notify=changed)
    def menu(self):
        return self._menu

    @Property('QVariantList', notify=changed)
    def children(self):
        return self._children

    @Property(bool, notify=changed)
    def canGoBack(self):
        return bool(self._folder_path)

    @Property('QVariantList', notify=changed)
    def historyEntries(self):
        return self._history

    @Property(str, notify=changed)
    def context(self):
        return self._profile["name"] if self._profile else self._target.get("process", "Desktop")

    @Property('QVariantList', constant=True)
    def languages(self):
        return [{"code": code, "name": f"{name} ({short})"} for code, (short, name, _) in LANGUAGES.items()]

    @Property(str, constant=True)
    def dataPath(self):
        return str(data_dir())

    @Property(str, constant=True)
    def version(self):
        from . import __version__
        return __version__

    def refresh(self):
        self._history = [{k: v for k, v in x.items() if k not in ("snapshot", "after")} for x in self.history.entries()]
        import html
        for entry in self._history:
            entry["displayOriginal"] = html.unescape(re.sub(r"</?t\d+>|<o\d+/>", "", entry.get("original", "")))
            entry["displayResult"] = html.unescape(re.sub(r"</?t\d+>|<o\d+/>", "", entry.get("result", ""))) + "".join(
                f"\n\nQ: {x['question']}\nA: {x['answer']}" for x in entry.get("conversation", []))
            entry["displayAction"] = names(entry["action"], self.config.value)[1] if entry["action"] in CATALOG else entry["action"]
        self._menu = []
        for index, action in enumerate(self.config.value["slots"]):
            item = self.action_item(action)
            item.update({key: value for key, value in self.config.value["slotAppearance"][index].items() if value})
            item.update(ring_geometry()[index])
            self._menu.append(item)
        self.changed.emit()

    def action_item(self, action, value=None):
        live = value is None
        value = self.config.value if live else value
        name, title, icon = names(action, value)
        if action.startswith("macro:"):
            name = title = next((x["name"] for x in value["macros"] if "macro:" + x["id"] == action), "Macro")
            icon = "⌘"
        if action.startswith("folder:"):
            folder = next((x for x in value["folders"] if "folder:" + x["id"] == action), {})
            name, icon = folder.get("name", "Submenu"), folder.get("icon") or "▦"
            title = name
        if action == "application" and self._profile:
            name = title = self._profile["name"]
        appearance = value["appearance"].get(action, {})
        name = appearance.get("name") or name
        icon = appearance.get("icon") or icon
        group = action in GROUPS or action.startswith("folder:")
        enabled = bool(action) and action != "jamat_remarkable" and (action != "application" or self._profile is not None) \
            and (group or not live or self.available(action))
        return {"id": action, "name": name, "title": title, "icon": icon, "enabled": enabled, "group": group}

    def available(self, action):
        if self._limit == "":
            return True
        elif self._limit == "own":
            return action in ("translate_region", "translate_clipboard", "settings", "history", "restart")
        elif self._limit == "busy":
            return action in TRANSLATIONS + ("settings", "history")
        else:
            raise ValueError("Unknown ring limit")

    def group_actions(self, action, value=None):
        value = self.config.value if value is None else value
        if action == "english":
            return ["english_formal", "english_social"]
        elif action == "translate":
            return list(TRANSLATIONS)
        elif action == "macros":
            return ["macro:" + x["id"] for x in value["macros"]][:6]
        elif action == "application":
            return self._profile["actions"] if self._profile else []
        elif action == "system":
            return ["settings", "history", "restart"]
        elif action.startswith("folder:"):
            return next((x["actions"] for x in value["folders"] if "folder:" + x["id"] == action), [])
        else:
            return []

    def configure_hotkeys(self, value):
        keys = [value["hotkey"], value["stopHotkey"]] + [x["key"] for x in value["bindings"]]
        seen = set()
        for binding in value["bindings"]:
            identity = (binding.get("profile", ""), parse_key(binding["key"]))
            if identity in seen:
                raise ValueError("Duplicate action shortcut in the same profile")
            seen.add(identity)
        processes = [x["process"].lower() for x in value["profiles"]]
        if len(processes) != len(set(processes)):
            raise ValueError("Use one profile per process filename")
        if parse_key(value["hotkey"]) == parse_key(value["stopHotkey"]):
            raise ValueError("Menu and stop shortcuts must differ")
        reserved = {parse_key(value["hotkey"]), parse_key(value["stopHotkey"])}
        if any(parse_key(x["key"]) in reserved for x in value["bindings"]):
            raise ValueError("An action shortcut conflicts with menu or stop")
        for macro in value["macros"]:
            for step in macro["steps"]:
                if step["type"] == "keys" and parse_key(step["value"]) in {parse_key(x) for x in keys}:
                    raise ValueError("A macro cannot send an assistant activation shortcut")
        self.hotkeys.configure(keys)

    @Slot(str)
    def set_status(self, value):
        self._status = value
        self.changed.emit()

    @Slot(str)
    def job_finished(self, error):
        self._busy = False
        self._limit = "" if self._limit == "busy" else self._limit
        self.engine.edit_target = None
        if error:
            self._status = error
        self.refresh()

    def work(self, function):
        if self._busy:
            self.set_status("An action is already running. Stop it first.")
            return
        self._busy = True
        self.engine.cancel.clear()
        self.changed.emit()
        def run():
            error = ""
            try:
                function()
            except Exception as caught:
                error = str(caught) or type(caught).__name__
            self.finished.emit(error)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def hotkey(self, key):
        if parse_key(key) == parse_key(self.config.value["stopHotkey"]):
            self.cancel()
            return
        if self._ring_visible and parse_key(key) == parse_key(self.config.value["hotkey"]):
            self.hideMenu.emit()
            return
        if self._paused:
            return
        try:
            self._target = foreground()
            own = self._target["pid"] == os.getpid()
            self._limit = "own" if own else "busy" if self._busy else ""
            self._profile = None if own else next((x for x in self.config.value["profiles"] if x["process"].lower() == self._target["process"].lower()), None)
            if self._pending_restore and not own:
                job = self._pending_restore
                self._pending_restore = ""
                self.work(lambda: self.engine.restore(job))
                return
            if self._armed and not own:
                action = self._armed
                self._armed = ""
                QTimer.singleShot(180, lambda: self.execute(action))
                return
            self._children, self._parent, self._folder_path = [], -1, []
            self.refresh()
            if parse_key(key) == parse_key(self.config.value["hotkey"]):
                self.requestMenu.emit()
            else:
                candidates = [x for x in self.config.value["bindings"] if parse_key(x["key"]) == parse_key(key)]
                selected = next((x for x in candidates if self._profile and x.get("profile") == self._profile["id"]), None)
                selected = selected or next((x for x in candidates if not x.get("profile")), None)
                if selected and self.available(selected["action"]):
                    QTimer.singleShot(180, lambda: self.execute(selected["action"]))
                elif selected:
                    self.set_status("This shortcut is not available while " + ("an assistant window is active" if own else "another action runs"))
        except Exception as error:
            self.set_status(str(error))

    @Slot(int)
    def hover(self, index):
        if index == self._parent:
            return
        self._parent = index
        self._folder_path = []
        self.render_children(self._menu[index]["id"] if index >= 0 else "")

    def render_children(self, action):
        self._children = []
        actions = self.group_actions(action)
        if actions and self._parent >= 0:
            angle = -90 + self._parent * 45
            cx, cy = 300, 300
            width = min(108, max(64, len(actions) * 28))
            inner, outer, label_radius = 158, 230, 194
            label_width = min(52, 2 * label_radius * math.sin(math.radians(width / len(actions) / 2)) - 16)
            for i, child in enumerate(actions):
                start, end = angle - width / 2 + width * i / len(actions), angle - width / 2 + width * (i + 1) / len(actions)
                x, y = point(cx, cy, label_radius, (start + end) / 2)
                self._children.append({**self.action_item(child), "path": sector(cx, cy, inner, outer, start, end), "x": x, "y": y,
                                       "cx": cx, "cy": cy, "start": start, "end": end, "inner": inner, "outer": outer, "labelWidth": label_width})
        self.changed.emit()

    @Slot(int)
    def enterChild(self, index):
        if 0 <= index < len(self._children) and self._children[index]["group"]:
            action = self._children[index]["id"]
            self._folder_path.append(action)
            self.render_children(action)

    @Slot()
    def backFolder(self):
        if self._folder_path:
            self._folder_path.pop()
            self.render_children(self._folder_path[-1] if self._folder_path else self._menu[self._parent]["id"])

    @Slot(bool)
    def ringVisible(self, visible):
        self._ring_visible = visible
        self._ring_clicks = self.windows.input_monitor.clicks.value

    @Slot(str)
    def execute(self, action):
        self.hideMenu.emit()
        if action in ("settings", "history"):
            self.requestSettings.emit(action)
        elif action == "restart":
            self.restartApp()
        elif action in EDITS:
            self.work(lambda: self.engine.edit(action, self._target))
        elif action in TRANSLATIONS:
            self.translator.start(action.removeprefix("translate_"), self._target)
        elif action.startswith("macro:"):
            self.work(lambda: self.engine.macro(action[6:], self._target))
        elif action in ("jamat_new", "jamat_remarkable"):
            self.work(lambda: self.engine.app_command(action))
        elif action == "":
            return
        else:
            self.set_status("Select a submenu action")

    @Slot()
    def restartApp(self):
        if self._busy:
            self.notification.emit("Stop the running action before restarting the app.")
            return
        self.requestRestart.emit()

    @Slot()
    def cancel(self):
        self.engine.cancel.set()
        self.translator.stop()
        self.hideMenu.emit()
        self._armed, self._pending_restore = "", ""
        self.set_status("Stopping…" if self._busy else "Ready")

    @Slot(str)
    def armMacro(self, identifier):
        self._armed = "macro:" + identifier
        self.set_status("Macro armed. Focus its target, then press " + self.config.value["hotkey"])

    @Slot(str)
    def restore(self, job):
        self._pending_restore = job
        self.set_status("Restore armed. Focus the original field, then press " + self.config.value["hotkey"])

    @Slot(str, bool)
    def copyHistory(self, job, original):
        entry = self.history.get(job)
        text = entry.get("original" if original else "result", "")
        if entry.get("snapshot", {}).get("rich"):
            text = re.sub(r"</?t\d+>|<o\d+/>", "", text)
            import html
            text = html.unescape(text)
        QGuiApplication.clipboard().setText(text)
        self.set_status("Copied as plain text")

    @Slot()
    def clearHistory(self):
        if self._busy or self.translator.active:
            self.set_status("Wait for running actions before clearing History")
            return
        self.history.clear()
        self.refresh()

    @Slot(str, result=bool)
    def saveSettings(self, text):
        if self._busy:
            self.set_status("Wait for the running action before changing settings")
            return False
        previous = copy.deepcopy(self.config.value)
        try:
            value = validate(json.loads(text))
            self.configure_hotkeys(value)
            self.config.save(value)
            self.set_autostart(value["autostart"])
            self.refresh()
            self.set_status("Settings saved")
            return True
        except Exception as error:
            self.configure_hotkeys(previous)
            if self.config.value != previous:
                self.config.save(previous)
            self.set_status(str(error))
            return False

    def set_autostart(self, enabled):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if enabled:
                args = [sys.executable] if getattr(sys, "frozen", False) else [str(Path(sys.executable).with_name("pythonw.exe")), "-m", "desktop_ai_assistant"]
                winreg.SetValueEx(key, "DesktopAiAssistant", 0, winreg.REG_SZ, subprocess.list2cmdline(args))
            else:
                try:
                    winreg.DeleteValue(key, "DesktopAiAssistant")
                except FileNotFoundError:
                    pass

    @Slot()
    def exportSettings(self):
        path, _ = QFileDialog.getSaveFileName(None, "Export settings (includes macro snippets)", "desktop-ai-settings.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.config.value, ensure_ascii=False, indent=2), "utf-8")

    @Slot(result=str)
    def importSettings(self):
        path, _ = QFileDialog.getOpenFileName(None, "Preview imported settings", "", "JSON (*.json)")
        if path:
            try:
                value = validate(json.loads(Path(path).read_text("utf-8")))
                self.set_status("Import preview loaded. Check paths and macros, then Save to replace settings.")
                return json.dumps(value, ensure_ascii=False)
            except Exception as error:
                self.set_status(str(error))
        return ""

    @Slot(result=str)
    def defaults(self):
        return json.dumps(DEFAULT)

    @Slot(str, result='QVariantList')
    def previewMenu(self, text):
        value = json.loads(text)
        result = []
        for index, action in enumerate(value["slots"]):
            item = {**self.action_item(action, value), **ring_geometry()[index]}
            for key, entry in value.get("appearance", {}).get(action, {}).items():
                if entry:
                    item[key] = entry
            item.update({key: entry for key, entry in value["slotAppearance"][index].items() if entry})
            result.append(item)
        return result

    @Slot(str, str, result='QVariantMap')
    def previewAction(self, action, text):
        return self.action_item(action, json.loads(text))

    @Slot(str, str, result='QVariantList')
    def previewChildren(self, action, text):
        value = json.loads(text)
        return [self.action_item(child, value) for child in self.group_actions(action, value)]

    @Slot(str, result='QVariantList')
    def previewCatalog(self, text):
        value = json.loads(text)
        return [{"id": "", "name": "Empty", "group": False, "edit": False}] + [
            {"id": a, "name": names(a, value)[1], "group": a in GROUPS, "edit": a in EDITS} for a in CATALOG]

    @Slot(bool)
    def captureShortcut(self, active):
        if active:
            self.hotkeys.close()
        else:
            try:
                self.configure_hotkeys(self.config.value)
            except Exception as error:
                self.set_status(str(error))

    @Slot(str)
    def login(self, provider):
        def sign_in():
            args = command(provider)
            if provider == "codex":
                args += ["login", "--device-auth"]
            elif provider == "claude":
                args += ["auth", "login"]
            else:
                raise ValueError("Unknown provider")
            process = subprocess.Popen(args, cwd=data_dir(), env=provider_env(provider), creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.notification.emit("Complete sign-in in the authentication window")
            while process.poll() is None:
                if self.engine.cancel.wait(0.2):
                    from .providers import terminate
                    terminate(process)
                    return
            if process.returncode:
                raise RuntimeError("Sign-in did not complete")
            self.notification.emit("Sign-in completed")
        self.work(sign_in)

    @Slot()
    def diagnostics(self):
        def inspect():
            facts = [f"Browser connections: {len(self.browser.clients)}"]
            for provider in ("claude", "codex"):
                try:
                    args = command(provider)
                    version = run_process(args + ["--version"], self.engine.cancel, timeout=10).strip()
                    auth_args = ["auth", "status"] if provider == "claude" else ["login", "status"]
                    try:
                        run_process(args + auth_args, self.engine.cancel, env=provider_env(provider), timeout=10)
                        auth = "signed in"
                    except RuntimeError:
                        auth = "sign-in required"
                    facts.append(f"{version}: {auth}")
                except Exception as error:
                    facts.append(f"{provider}: {error}")
            self.notification.emit("\n".join(facts))
        self.work(inspect)

    @Property(str, constant=True)
    def extensionPath(self):
        from .browser_setup import extension_directory
        return str(extension_directory())

    @Property(str, notify=changed)
    def browserSetupStatus(self):
        return self._browser_status

    @Slot()
    def setupBrowser(self):
        from .browser_setup import register_browser
        try:
            register_browser()
            self._browser_status = "Desktop connection prepared automatically. Enable your site in the extension."
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            self._browser_status = str(error)
        self.changed.emit()

    @Slot()
    def openExtensionFolder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.extensionPath))

    @Slot()
    def copyExtensionPath(self):
        QGuiApplication.clipboard().setText(self.extensionPath)
        self.set_status("Extension folder copied")

    @Slot()
    def togglePause(self):
        self._paused = not self._paused
        self.set_status("Hotkeys paused" if self._paused else "Ready")

    def watch(self):
        if self.engine.edit_target and not same_target(self.engine.edit_target):
            self.engine.invalidated.set()
        if self._target and not same_target(self._target):
            self.hideMenu.emit()
        if user32.GetAsyncKeyState(27) & 0x8000:
            self.hideMenu.emit()
        clicks = self.windows.input_monitor.clicks.value
        # A click outside the ring shapes never reaches the ring window, so the passive mouse hook reports it.
        if self._ring_visible and clicks != self._ring_clicks:
            self._ring_clicks = clicks
            if window_at_cursor() != self.ring_window:
                self.hideMenu.emit()

    def close(self):
        self.engine.cancel.set()
        self.translator.stop()
        self.monitor.stop()
        self.hotkeys.close()
        if self.thread and self.thread.is_alive():
            self.thread.join(8)
        self.translator.close()
        self.windows.close()
        self.browser.close()
