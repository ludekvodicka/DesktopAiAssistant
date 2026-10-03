import html
import os
from pathlib import Path
import threading
from urllib.parse import urlparse
import win32gui
from . import providers
from .text import TAGS
from .winapi import same_target, target_exists, send_keys, activate
from .windows_text import terminal


class Engine:
    config: object
    history: object
    windows: object
    browser: object
    cancel: threading.Event
    progress: object
    edit_target: dict | None
    invalidated: threading.Event
    waiting_for_editor: bool

    def __init__(self, config, history, windows, browser, progress):
        self.config = config
        self.history = history
        self.windows = windows
        self.browser = browser
        self.cancel = threading.Event()
        self.progress = progress
        self.edit_target = None
        self.invalidated = threading.Event()
        self.waiting_for_editor = False

    def capture(self, target):
        if not same_target(target):
            raise RuntimeError("The original window is no longer active")
        if target["process"].lower() in ("chrome.exe", "msedge.exe"):
            return self.browser.capture(target)
        return self.windows.capture(target)

    def read_selection(self, target):
        if terminal(target):
            raise RuntimeError("Terminal text is not supported")
        try:
            snapshot = self.capture(target)
        except RuntimeError:
            if not same_target(target):
                raise
            return self.windows.copy_selection(target)
        text = html.unescape(TAGS.sub("", snapshot["text"])) if snapshot.get("rich") else snapshot["text"]
        return {"kind": "selection", "format": "plain", "text": text, "image": None, "origin": target["process"]}

    def apply(self, snapshot, text, tick):
        if self.cancel.is_set():
            raise providers.Cancelled("Cancelled")
        if snapshot["kind"] == "windows":
            return self.windows.apply(snapshot, text, tick, allow_background=True)
        elif snapshot["kind"] == "browser":
            return self.browser.apply(snapshot, text)
        else:
            raise ValueError("Unknown text adapter")

    def edit(self, action, target, literal=None):
        self.progress("Reading the focused editor…")
        self.invalidated.clear()
        self.edit_target = target
        initial_tick = self.windows.input_tick()
        try:
            snapshot = self.capture(target)
        except Exception:
            self.edit_target = None
            raise
        if self.windows.input_tick() != initial_tick or self.invalidated.is_set():
            self.edit_target = None
            raise RuntimeError("Input changed while capturing the editor. Try again.")
        tick = self.windows.input_tick()
        if literal is not None:
            snapshot["start"] = snapshot.get("selectionStart", snapshot.get("start", 0))
            snapshot["end"] = snapshot.get("selectionEnd", snapshot.get("end", 0))
            snapshot["insert"] = True
        job = self.history.create({"action": action, "source": target["process"], "original": snapshot["text"], "snapshot": snapshot,
                                   "provider": self.config.value["provider"], "rulesVersion": 1, "language": self.config.value["nativeLanguage"],
                                   "rules": self.config.value["rules"].get(action, ""), "model": self.config.value["models"][self.config.value["provider"]]})
        try:
            if literal is None:
                self.progress("Editing with " + self.config.value["provider"] + "…")
                result = providers.transform(self.config.value, action, snapshot["text"], self.cancel)
            else:
                if snapshot.get("rich"):
                    raise RuntimeError("Snippet insertion into rich text is not enabled. Use a plain text field.")
                result = literal
            self.history.update(job, "ready", result=result)
            if self.cancel.is_set():
                raise providers.Cancelled("Cancelled")
            if literal is None and result == snapshot["text"]:
                self.history.update(job, "unchanged")
                self.progress("No changes needed. The text is already correct.")
                return True
            self.history.update(job, "writing")
            after = self.apply(snapshot, result, tick)
            if after.get("deferred"):
                self.waiting_for_editor = True
                reason = "Result ready. Return to the original unchanged field for insertion, or stop the action."
                self.history.update(job, "ready", error=reason)
                self.progress(reason)
                while after.get("deferred"):
                    if self.cancel.wait(0.3):
                        raise providers.Cancelled("Cancelled; result kept in History")
                    if not target_exists(target):
                        raise RuntimeError("The original window closed. Result kept in History.")
                    if not same_target(target):
                        continue
                    tick = self.windows.input_tick()
                    if self.cancel.wait(0.3):
                        raise providers.Cancelled("Cancelled; result kept in History")
                    if self.windows.input_tick() != tick:
                        continue
                    after = self.apply(snapshot, result, tick)
            self.waiting_for_editor = False
            warning = after.get("clipboardWarning", "")
            self.history.update(job, "applied", after=after, error=warning)
            self.progress(warning or ("Text updated in the original editor. Original saved in History." if after.get("background") else "Text updated. Original saved in History."))
            return True
        except providers.Cancelled:
            self.history.update(job, "cancelled")
            raise
        except Exception as error:
            self.history.update(job, "failed", error=str(error) or type(error).__name__)
            raise
        finally:
            self.waiting_for_editor = False
            self.edit_target = None

    def edit_via(self, action, target, via):
        if via == "clipboard":
            self.progress("Reading the clipboard…")
            text, source, tick = self.windows.read_clipboard(), "Clipboard", None
        elif via == "app":
            if not same_target(target):
                raise RuntimeError("The original window is no longer active")
            self.progress("Copying the selection…")
            text, source = self.windows.copy_selection(target, plain=True)["text"], target["process"]
            # The monitor can still be counting the copy shortcut.
            tick = self.windows.input_tick()
            for _ in range(6):
                if self.cancel.wait(0.15) or self.windows.input_tick() == tick:
                    break
                tick = self.windows.input_tick()
        else:
            raise ValueError("Unknown text source")
        job = self.history.create({"action": action, "via": via, "source": source, "original": text,
                                   "provider": self.config.value["provider"], "rulesVersion": 1, "language": self.config.value["nativeLanguage"],
                                   "rules": self.config.value["rules"].get(action, ""), "model": self.config.value["models"][self.config.value["provider"]]})
        try:
            self.progress("Editing with " + self.config.value["provider"] + "…")
            result = providers.transform(self.config.value, action, text, self.cancel)
            self.history.update(job, "ready", result=result)
            if self.cancel.is_set():
                raise providers.Cancelled("Cancelled")
            if result == text:
                self.history.update(job, "unchanged")
                self.progress("No changes needed. The text is already correct.")
            elif via == "clipboard":
                self.windows.write_clipboard(result)
                self.history.update(job, "copied")
                self.progress("Result copied to the clipboard. Original saved in History.")
            else:
                try:
                    self.windows.paste(target, result, tick)
                except RuntimeError as error:
                    # The selection cannot be verified without an adapter, so the user pastes it.
                    self.windows.write_clipboard(result)
                    self.history.update(job, "copied", error=str(error))
                    self.progress(f"{str(error).rstrip('.')}, so the text was not pasted. The result is in the clipboard; paste it with Ctrl+V.")
                    return True
                self.history.update(job, "pasted")
                self.progress("Text pasted. Original saved in History.")
            return True
        except providers.Cancelled:
            self.history.update(job, "cancelled")
            raise
        except Exception as error:
            self.history.update(job, "failed", error=str(error) or type(error).__name__)
            raise

    def app_command(self, action):
        if action == "jamat_remarkable":
            raise RuntimeError("Jamat does not expose a verified reMarkable import command yet.")
        elif action == "jamat_new":
            settings = self.config.value["jamat"]
            cli = Path(settings["cli"])
            directory = Path(settings["directory"])
            if not cli.is_file() or not directory.is_dir():
                raise RuntimeError("Choose the Jamat CLI and project directory in Settings first")
            import shutil
            node = shutil.which("node.exe")
            if not node:
                raise RuntimeError("Node.js is required for the Jamat CLI")
            args = [node, str(cli)]
            if settings["controller"]:
                args += ["--config-identity", settings["controller"], "--channel", settings["channel"]]
            args += ["sessions", "create", "--directory", str(directory), "--title", "New session", "--open-tab"]
            import json
            reply = json.loads(providers.run_process(args, self.cancel, timeout=20))
            if not reply.get("ok"):
                raise RuntimeError("Jamat: " + str(reply.get("error", reply)))
        else:
            raise ValueError("Unknown application command")

    def macro(self, macro_id, target):
        macro = next(x for x in self.config.value["macros"] if x["id"] == macro_id)
        job = self.history.create({"action": macro["name"], "source": target["process"], "original": "", "steps": []})
        completed = []
        try:
            for index, step in enumerate(macro["steps"]):
                if self.cancel.is_set():
                    raise providers.Cancelled("Cancelled")
                self.progress(f"{macro['name']} · {index + 1}/{len(macro['steps'])} · {step['type']}")
                kind, value = step["type"], step["value"]
                if kind == "activate":
                    target = activate(value, self.cancel)
                elif kind == "delay":
                    if self.cancel.wait(value):
                        raise providers.Cancelled("Cancelled")
                elif kind == "open":
                    url = urlparse(value)
                    if url.scheme in ("https", "http") or Path(value).exists():
                        os.startfile(value)
                    else:
                        raise ValueError("Choose an existing file/application or HTTP(S) URL")
                elif kind == "app":
                    self.app_command(value)
                elif kind in ("keys", "text", "ai"):
                    if not same_target(target):
                        raise RuntimeError("The macro target changed. Use an explicit Activate step.")
                    if kind == "keys":
                        send_keys(value, target)
                    elif kind == "text":
                        if not self.edit("snippet", target, value):
                            raise RuntimeError("Snippet could not be applied")
                    elif kind == "ai":
                        if not self.edit(value, target):
                            raise RuntimeError("AI result requires manual recovery from History")
                    else:
                        raise ValueError("Unknown input step")
                else:
                    raise ValueError("Unknown macro step")
                completed.append({"index": index + 1, "type": kind})
                self.history.update(job, "running", steps=completed)
            self.history.update(job, "completed")
            self.progress("Macro completed")
        except Exception as error:
            self.history.update(job, "cancelled" if self.cancel.is_set() else "failed", steps=completed, error=str(error))
            raise

    def restore(self, job):
        entry = self.history.get(job)
        if entry["status"] != "applied" or "after" not in entry:
            raise RuntimeError("Only a verified applied edit can be restored")
        after = entry["after"]
        win32gui.SetForegroundWindow(after["target"]["hwnd"])
        if not same_target(after["target"]):
            raise RuntimeError("Activate the original window first")
        if after["kind"] == "browser":
            self.browser.restore(after)
        elif after["kind"] == "windows":
            current = self.windows.capture(after["target"])
            if current["element"] != after["element"] or current["full"] != after["full"]:
                raise RuntimeError("The editor changed since this result. Original is available for copying.")
            current.update(start=0, end=len(current["full"]), restoreWhole=True)
            self.windows.apply(current, entry["snapshot"]["full"])
        else:
            raise ValueError("Unknown text adapter")
        self.history.update(job, "restored")
        self.progress("Original text restored")
