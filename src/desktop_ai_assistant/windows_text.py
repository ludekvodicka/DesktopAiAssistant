import multiprocessing as mp
import threading
import time
import uuid
import ctypes as C
from ctypes import wintypes as W
import pythoncom
import win32gui
from .winapi import same_target, target_exists, send_keys, wait_modifiers, terminal
from .input_monitor import InputMonitor
from .scintilla import Scintilla
from .uia_text import UiaText
from .text import TextAccessDenied


def _worker(connection, revision):
    import comtypes
    import comtypes.client
    from .clipboard import Clipboard, copy_mime_data, source_from_mime
    comtypes.CoInitializeEx(2)
    pythoncom.OleInitialize()
    clipboard = Clipboard()
    module = comtypes.client.GetModule("UIAutomationCore.dll")
    automation = comtypes.client.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
    uia = UiaText(automation, module)
    records = {}
    send = C.WinDLL("user32", use_last_error=True).SendMessageTimeoutW
    send.argtypes = [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t, W.UINT, W.UINT, C.POINTER(C.c_size_t)]
    send.restype = C.c_ssize_t

    def message(hwnd, code, wparam=0, lparam=0):
        result = C.c_size_t()
        if not send(hwnd, code, wparam, lparam, 2, 1000, C.byref(result)):
            raise RuntimeError("The native editor did not respond")
        return result.value

    def native_read(hwnd):
        length = message(hwnd, 0x000e)
        if length > 200000:
            raise RuntimeError("This field is too large")
        buffer = C.create_unicode_buffer(length + 1)
        message(hwnd, 0x000d, length + 1, C.addressof(buffer))
        start, end = W.DWORD(), W.DWORD()
        message(hwnd, 0x00b0, C.addressof(start), C.addressof(end))
        encoded = buffer.value.encode("utf-16-le")
        return buffer.value, len(encoded[:start.value * 2].decode("utf-16-le")), len(encoded[:end.value * 2].decode("utf-16-le"))

    def read(target, element=None, read_only=False, verify_only=False):
        if element is None and not same_target(target):
            raise RuntimeError("The active window changed")
        if not target_exists(target):
            raise RuntimeError("The original window no longer exists")
        if element is None:
            element = automation.GetFocusedElement()
        uia.ancestors(element, target)
        hwnd = element.CurrentNativeWindowHandle
        if hwnd and win32gui.GetClassName(hwnd) == "Scintilla":
            editor = Scintilla(hwnd, message)
            try:
                if not read_only and editor.readonly():
                    raise RuntimeError("This field is read-only")
                full, start, end = editor.read()
            finally:
                editor.close()
            whole = start == end
            snapshot = {"kind": "windows", "target": target, "element": list(element.GetRuntimeId()), "scintilla": hwnd,
                        "full": full, "text": full if whole else full[start:end], "start": 0 if whole else start,
                        "end": len(full) if whole else end, "selectionStart": start, "selectionEnd": end}
            if len(full) > 200000:
                raise RuntimeError("This field is too large")
            return snapshot, None
        classname = element.CurrentClassName.lower()
        if hwnd and (classname == "edit" or "richedit" in classname and target["process"].lower() == "notepad.exe"):
            style = win32gui.GetWindowLong(hwnd, -16)
            if style & 0x0020:
                raise TextAccessDenied("Password fields cannot be read")
            if not read_only and style & 0x0800:
                raise RuntimeError("This field is read-only")
            full, start, end = native_read(hwnd)
            whole = start == end
            snapshot = {"kind": "windows", "target": target, "element": list(element.GetRuntimeId()), "native": hwnd,
                        "full": full, "text": full if whole else full[start:end], "start": 0 if whole else start,
                        "end": len(full) if whole else end, "selectionStart": start, "selectionEnd": end}
            return snapshot, None
        return uia.read(element, target, read_only, verify_only)

    try:
        while True:
            clipboard.app.processEvents()
            if not connection.poll(0.02):
                continue
            request = connection.recv()
            if request["op"] == "close":
                break
            try:
                if request["op"] in ("capture", "read_selection"):
                    element = automation.GetFocusedElement()
                    if not same_target(request["target"]):
                        raise RuntimeError("The active window changed")
                    hwnd = element.CurrentNativeWindowHandle if element else 0
                    if not hwnd or win32gui.GetClassName(hwnd) != "Scintilla":
                        element = uia.resolve(element, request["target"])
                    reading = request["op"] == "read_selection"
                    result, selected = read(request["target"], element, read_only=reading)
                    if not same_target(request["target"]):
                        raise TextAccessDenied("The active window changed while reading text")
                    if reading:
                        result = {"kind": "selection", "format": "plain", "text": result["text"], "image": None, "origin": request["target"]["process"]}
                    else:
                        token = uuid.uuid4().hex
                        records[token] = (element, selected)
                        if len(records) > 100:
                            del records[next(iter(records))]
                        result["token"] = token
                elif request["op"] == "apply":
                    original = request["snapshot"]
                    relaxed = request.get("allowBackground", False)
                    retained = records.get(original.get("token"))
                    if relaxed and retained is None:
                        raise RuntimeError("The original editor reference expired. Result kept in History.")
                    element = retained[0] if retained else automation.GetFocusedElement()
                    current, selected_range = read(original["target"], element, verify_only=relaxed)
                    if relaxed and win32gui.GetWindowText(original["target"]["hwnd"]) != original["target"].get("title", ""):
                        raise RuntimeError("The original document or conversation changed. Result kept in History.")
                    keys = ("element", "full") if relaxed else ("element", "full", "selectionStart", "selectionEnd")
                    for key in keys:
                        if current[key] != original[key]:
                            raise RuntimeError("The field or selection changed; result kept in history")
                    if not relaxed and request.get("tick") is not None and revision.value != request["tick"]:
                        raise RuntimeError("User input occurred; result kept in history")
                    replacement = request["text"]
                    expected = original["full"][:original["start"]] + replacement + original["full"][original["end"]:]
                    if original.get("native"):
                        if native_read(original["native"])[0] != original["full"]:
                            raise RuntimeError("The original text changed; result kept in History")
                        start = len(original["full"][:original["start"]].encode("utf-16-le")) // 2
                        end = len(original["full"][:original["end"]].encode("utf-16-le")) // 2
                        message(original["native"], 0x00b1, start, end)
                        buffer = C.create_unicode_buffer(replacement)
                        message(original["native"], 0x00c2, 1, C.addressof(buffer))
                        result, _ = read(original["target"], element)
                        if result["full"] != expected:
                            raise RuntimeError("Write was not verified; do not repeat automatically")
                        result.update(token=original.get("token"), background=not same_target(original["target"]))
                        connection.send({"ok": True, "value": result})
                        continue
                    if original.get("scintilla"):
                        editor = Scintilla(original["scintilla"], message)
                        try:
                            if editor.read()[0] != original["full"]:
                                raise RuntimeError("The original text changed; result kept in History")
                            editor.replace(original["full"], original["start"], original["end"], replacement)
                        finally:
                            editor.close()
                        result, _ = read(original["target"], element)
                        if result["full"] != expected:
                            raise RuntimeError("Write was not verified; do not repeat automatically")
                        result.update(token=original.get("token"), background=not same_target(original["target"]))
                        connection.send({"ok": True, "value": result})
                        continue
                    focused = same_target(original["target"]) and uia.focused(element, original["target"])
                    if relaxed and not focused:
                        value = None
                        try:
                            value = element.GetCurrentPattern(10002).QueryInterface(module.IUIAutomationValuePattern)
                            if value.CurrentIsReadOnly or value.CurrentValue != original["full"]:
                                value = None
                        except (comtypes.COMError, ValueError):
                            pass
                        # Some Qt editors interpret markup in SetValue as HTML.
                        if value is None or "<" in expected or original.get("foregroundOnly"):
                            connection.send({"ok": True, "value": {"deferred": True}})
                            continue
                        value.SetValue(expected)
                        result, _ = read(original["target"], element, verify_only=True)
                        if result["full"] != expected:
                            raise RuntimeError("Write was not verified; do not repeat automatically")
                        result.update(token=original.get("token"), background=True)
                        connection.send({"ok": True, "value": result})
                        continue
                    if not focused:
                        raise RuntimeError("Focus the original editor before inserting text")
                    paste_tick = revision.value if relaxed else request.get("tick")
                    if relaxed:
                        selected_range = retained[1]
                        if not original.get("insert") and not original.get("restoreWhole"):
                            pattern = element.GetCurrentPattern(10014).QueryInterface(module.IUIAutomationTextPattern)
                            prefix = pattern.DocumentRange.Clone()
                            prefix.MoveEndpointByRange(1, selected_range, 0)
                            if selected_range.GetText(-1) != original["text"] or len(prefix.GetText(-1)) != original["start"]:
                                raise RuntimeError("The original text range changed; result kept in History")
                    if original.get("insert"):
                        pattern = element.GetCurrentPattern(10014).QueryInterface(module.IUIAutomationTextPattern)
                        selected_range = pattern.GetSelection().GetElement(0)
                    if original.get("restoreWhole"):
                        pattern = element.GetCurrentPattern(10014).QueryInterface(module.IUIAutomationTextPattern)
                        selected_range = pattern.DocumentRange
                    selected_range.Select()
                    previous, sequence = clipboard.replace(replacement)
                    verified = False
                    paste_started = False
                    try:
                        if paste_tick is not None and revision.value != paste_tick:
                            raise RuntimeError("User input occurred; result kept in history")
                        if not uia.focused(element, original["target"]):
                            raise RuntimeError("The focused editor changed; result kept in History")
                        paste_started = True
                        send_keys("Ctrl+V", original["target"])
                        deadline = time.monotonic() + 1.5
                        while time.monotonic() < deadline:
                            current, _ = read(original["target"], element, verify_only=True)
                            if current["full"] == expected:
                                verified = True
                                break
                            time.sleep(0.04)
                        else:
                            raise RuntimeError("Write was not verified; do not repeat automatically")
                        result = current
                        result["token"] = original.get("token")
                    finally:
                        if verified or not paste_started:
                            try:
                                clipboard.restore(previous, sequence)
                            except Exception:
                                if verified:
                                    result["clipboardWarning"] = "Text updated, but the previous clipboard could not be restored."
                elif request["op"] == "copy":
                    target = request["target"]
                    if not same_target(target):
                        raise RuntimeError("The active window changed")
                    saved, sequence = clipboard.backup()
                    send_keys("Ctrl+C", target)
                    copied = clipboard.wait_change(sequence, 2.5)
                    if copied == sequence:
                        raise RuntimeError("Nothing was copied. Select text first.")
                    try:
                        selection = copy_mime_data(clipboard.clipboard.mimeData())
                    finally:
                        clipboard.restore(saved, copied)
                    # Converted after the restore, so a slow conversion of a large page cannot cost the user's clipboard.
                    if request.get("plain"):
                        if not selection.hasFormat("text/plain") or not selection.text().strip():
                            raise RuntimeError("The copied content has no text")
                        result = {"kind": "selection", "format": "plain", "text": selection.text(), "image": None, "origin": target["process"]}
                    else:
                        result = source_from_mime(selection, "selection", target["process"], "The copied content has no text")
                elif request["op"] == "paste":
                    target = request["target"]
                    if not same_target(target):
                        raise RuntimeError("The window changed")
                    previous, sequence = clipboard.replace(request["text"])
                    try:
                        if revision.value != request["tick"]:
                            raise RuntimeError("You used the keyboard or mouse in the meantime")
                        send_keys("Ctrl+V", target)
                        # Windows reports no moment when the editor has read the clipboard.
                        deadline = time.monotonic() + 0.8
                        while time.monotonic() < deadline:
                            clipboard.app.processEvents()
                            time.sleep(0.02)
                    finally:
                        clipboard.restore(previous, sequence)
                    result = True
                elif request["op"] == "read_clipboard":
                    mime = clipboard.clipboard.mimeData()
                    # Qt 6 hasText() is also true for file URLs alone.
                    if mime is None or not mime.hasFormat("text/plain") or not mime.text().strip():
                        raise RuntimeError("The clipboard has no text")
                    result = mime.text()
                elif request["op"] == "write_clipboard":
                    clipboard.clipboard.setText(request["text"])
                    if not clipboard.clipboard.ownsClipboard():
                        raise RuntimeError("Could not write the clipboard")
                    # The text stays available after the worker stops.
                    pythoncom.OleFlushClipboard()
                    result = True
                else:
                    raise ValueError("Unknown text operation")
                connection.send({"ok": True, "value": result})
            except Exception as error:
                import traceback
                traceback.print_exc()
                connection.send({"ok": False, "error": str(error) or type(error).__name__, "denied": isinstance(error, TextAccessDenied)})
    except (EOFError, BrokenPipeError):
        pass
    finally:
        ole32 = C.WinDLL("ole32")
        ole32.OleUninitialize.restype = None
        ole32.OleUninitialize()
        comtypes.CoUninitialize()
        connection.close()


class WindowsText:
    process: object
    connection: object
    lock: threading.Lock
    input_monitor: InputMonitor

    def __init__(self):
        self.process = None
        self.connection = None
        self.lock = threading.Lock()
        self.input_monitor = InputMonitor()

    def input_tick(self):
        if not self.input_monitor.process.is_alive():
            raise RuntimeError("Input monitoring stopped. Restart the assistant.")
        return self.input_monitor.revision.value

    def call(self, request):
        with self.lock:
            if not self.process or not self.process.is_alive():
                self._discard_worker()
                self.connection, child = mp.Pipe()
                self.process = mp.Process(target=_worker, args=(child, self.input_monitor.revision), daemon=True)
                self.process.start()
                child.close()
            try:
                self.connection.send(request)
                if not self.connection.poll(6):
                    raise TimeoutError("The editor did not respond. No automatic retry. Check the editor before trying again.")
                result = self.connection.recv()
            except TimeoutError:
                self._discard_worker()
                raise
            except (EOFError, OSError) as error:
                self._discard_worker()
                if request["op"] == "apply":
                    message = "The editor helper stopped. Text may already have been inserted. Check the editor before trying again; the result is kept in History."
                else:
                    message = "The editor helper stopped before text could be read. Try the action again."
                raise RuntimeError(message) from error
            if not result["ok"]:
                if result.get("denied"):
                    raise TextAccessDenied(result["error"])
                raise RuntimeError(result["error"])
            return result["value"]

    def _discard_worker(self):
        if self.process:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(2)
            self.process.close()
            self.process = None
        if self.connection:
            self.connection.close()
            self.connection = None

    def capture(self, target):
        if terminal(target):
            raise RuntimeError("Terminal input is not supported")
        return self.call({"op": "capture", "target": target})

    def read_selection(self, target):
        if terminal(target):
            raise TextAccessDenied("Terminal text is not supported")
        return self.call({"op": "read_selection", "target": target})

    def copy_selection(self, target, plain=False):
        if terminal(target):
            raise RuntimeError("Terminal text is not supported")
        # A direct shortcut can still be held; waiting inside the worker would hold the call lock.
        wait_modifiers()
        return self.call({"op": "copy", "target": target, "plain": plain})

    def paste(self, target, text, tick):
        if terminal(target):
            raise RuntimeError("Terminal input is not supported")
        return self.call({"op": "paste", "target": target, "text": text, "tick": tick})

    def read_clipboard(self):
        return self.call({"op": "read_clipboard"})

    def write_clipboard(self, text):
        return self.call({"op": "write_clipboard", "text": text})

    def apply(self, snapshot, text, tick=None, allow_background=False):
        return self.call({"op": "apply", "snapshot": snapshot, "text": text, "tick": tick, "allowBackground": allow_background})

    def close(self):
        with self.lock:
            if self.process and self.process.is_alive():
                try:
                    self.connection.send({"op": "close"})
                except (EOFError, OSError):
                    pass
                self.process.join(1)
            self._discard_worker()
            self.input_monitor.close()
