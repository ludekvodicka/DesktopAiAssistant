import multiprocessing as mp
import threading
import time
import uuid
import ctypes as C
from ctypes import wintypes as W
import pythoncom
import win32gui
from .winapi import same_target, target_exists, send_keys, wait_modifiers
from .input_monitor import InputMonitor


TERMINAL_CLASSES = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "PuTTY", "VirtualConsoleClass")


def terminal(target):
    name = target["process"].lower()
    if any(x in name for x in ("terminal", "powershell", "pwsh", "cmd.exe", "conhost", "wezterm", "putty", "mintty", "bash", "wsl", "alacritty", "conemu", "tabby", "hyper")):
        return True
    # Ctrl+C interrupts a terminal process; the window class also catches terminals with unknown process names.
    try:
        return win32gui.GetClassName(target.get("hwnd", 0)) in TERMINAL_CLASSES
    except win32gui.error:
        return False


def _worker(connection, revision):
    import comtypes
    import comtypes.client
    from .clipboard import Clipboard, copy_mime_data, source_from_mime
    comtypes.CoInitializeEx(2)
    pythoncom.OleInitialize()
    clipboard = Clipboard()
    module = comtypes.client.GetModule("UIAutomationCore.dll")
    automation = comtypes.client.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
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

    def read(target, element=None):
        if element is None and not same_target(target):
            raise RuntimeError("The active window changed")
        if not target_exists(target):
            raise RuntimeError("The original window no longer exists")
        if element is None:
            element = automation.GetFocusedElement()
        if not element or element.CurrentProcessId != target["pid"] or element.CurrentIsPassword or not element.CurrentIsEnabled:
            raise RuntimeError("No supported editable field is focused")
        if element.CurrentControlType not in (50004, 50030):
            raise RuntimeError("Focus a text editor first")
        hwnd = element.CurrentNativeWindowHandle
        classname = element.CurrentClassName.lower()
        if hwnd and (classname == "edit" or "richedit" in classname and target["process"].lower() == "notepad.exe"):
            if win32gui.GetWindowLong(hwnd, -16) & (0x0800 | 0x0020):
                raise RuntimeError("This field is read-only or protected")
            full, start, end = native_read(hwnd)
            whole = start == end
            snapshot = {"kind": "windows", "target": target, "element": list(element.GetRuntimeId()), "native": hwnd,
                        "full": full, "text": full if whole else full[start:end], "start": 0 if whole else start,
                        "end": len(full) if whole else end, "selectionStart": start, "selectionEnd": end}
            return snapshot, None
        try:
            value = element.GetCurrentPattern(10002).QueryInterface(module.IUIAutomationValuePattern)
            if value.CurrentIsReadOnly:
                raise RuntimeError("This field is read-only")
        except (comtypes.COMError, ValueError):
            if "edit" not in element.CurrentClassName.lower():
                raise RuntimeError("Editability cannot be verified for this field")
        pattern = element.GetCurrentPattern(10014).QueryInterface(module.IUIAutomationTextPattern)
        selection = pattern.GetSelection()
        if not selection or selection.Length != 1:
            raise RuntimeError("This editor does not expose a single text selection")
        document = pattern.DocumentRange
        full = document.GetText(-1)
        selected = selection.GetElement(0)
        prefix = document.Clone()
        prefix.MoveEndpointByRange(1, selected, 0)
        start = len(prefix.GetText(-1))
        part = selected.GetText(-1)
        end = start + len(part)
        whole = start == end
        snapshot = {"kind": "windows", "target": target, "element": list(element.GetRuntimeId()),
                    "full": full, "text": full if whole else part, "start": 0 if whole else start,
                    "end": len(full) if whole else end, "selectionStart": start, "selectionEnd": end}
        if len(full) > 200000:
            raise RuntimeError("This field is too large")
        return snapshot, document if whole else selected

    try:
        while True:
            clipboard.app.processEvents()
            if not connection.poll(0.02):
                continue
            request = connection.recv()
            if request["op"] == "close":
                break
            try:
                if request["op"] == "capture":
                    element = automation.GetFocusedElement()
                    if not same_target(request["target"]):
                        raise RuntimeError("The active window changed")
                    result, selected = read(request["target"], element)
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
                    current, selected_range = read(original["target"], element)
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
                    focused = same_target(original["target"]) and automation.CompareElements(element, automation.GetFocusedElement())
                    if relaxed and not focused:
                        value = None
                        try:
                            value = element.GetCurrentPattern(10002).QueryInterface(module.IUIAutomationValuePattern)
                            if value.CurrentIsReadOnly or value.CurrentValue != original["full"]:
                                value = None
                        except (comtypes.COMError, ValueError):
                            pass
                        # Some Qt editors interpret markup in SetValue as HTML.
                        if value is None or "<" in expected:
                            connection.send({"ok": True, "value": {"deferred": True}})
                            continue
                        value.SetValue(expected)
                        result, _ = read(original["target"], element)
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
                        if not automation.CompareElements(element, automation.GetFocusedElement()):
                            raise RuntimeError("The focused editor changed; result kept in History")
                        paste_started = True
                        send_keys("Ctrl+V", original["target"])
                        deadline = time.monotonic() + 1.5
                        while time.monotonic() < deadline:
                            current, _ = read(original["target"], element)
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
                    result = source_from_mime(selection, "selection", target["process"], "The copied content has no text")
                else:
                    raise ValueError("Unknown text operation")
                connection.send({"ok": True, "value": result})
            except Exception as error:
                import traceback
                traceback.print_exc()
                connection.send({"ok": False, "error": str(error) or type(error).__name__})
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
        name = target["process"].lower()
        if name in ("chrome.exe", "msedge.exe", "firefox.exe"):
            raise RuntimeError("Connect the browser extension to preserve formatting")
        if terminal(target):
            raise RuntimeError("Terminal input is not supported")
        return self.call({"op": "capture", "target": target})

    def copy_selection(self, target):
        if terminal(target):
            raise RuntimeError("Terminal text is not supported")
        # A direct shortcut can still be held; waiting inside the worker would hold the call lock.
        wait_modifiers()
        return self.call({"op": "copy", "target": target})

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
