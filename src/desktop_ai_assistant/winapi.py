import ctypes as C
from ctypes import wintypes as W
import os
import time
import psutil
import win32gui
import win32process
from PySide6.QtCore import QAbstractNativeEventFilter

user32 = C.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = W.HWND
user32.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
user32.UnregisterHotKey.argtypes = [W.HWND, C.c_int]
user32.GetAsyncKeyState.argtypes = [C.c_int]
user32.GetAsyncKeyState.restype = C.c_short
user32.WindowFromPoint.argtypes = [W.POINT]
user32.WindowFromPoint.restype = W.HWND
user32.GetAncestor.argtypes = [W.HWND, W.UINT]
user32.GetAncestor.restype = W.HWND
INPUT_MARKER = 0x44414941

MODS = {"alt": 1, "ctrl": 2, "shift": 4, "win": 8}
KEYS = {"space": 32, "escape": 27, "enter": 13, "tab": 9, "backspace": 8, "delete": 46,
        "home": 36, "end": 35, "left": 37, "up": 38, "right": 39, "down": 40,
        **{f"f{i}": 111 + i for i in range(1, 25)}}


def parse_key(text):
    parts = text.lower().split("+")
    if not parts or any(x not in MODS for x in parts[:-1]) or len(set(parts)) != len(parts):
        raise ValueError("Use a shortcut such as Ctrl+Alt+Space")
    key = KEYS.get(parts[-1], ord(parts[-1].upper()) if len(parts[-1]) == 1 and parts[-1].isalnum() else 0)
    if not key:
        raise ValueError("Unsupported key")
    return sum(MODS[x] for x in parts[:-1]), key


def foreground():
    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        raise RuntimeError("No active window")
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process = psutil.Process(pid)
    return {"hwnd": hwnd, "pid": pid, "started": process.create_time(), "process": process.name(), "title": win32gui.GetWindowText(hwnd)}


def window_at_cursor():
    point = W.POINT()
    user32.GetCursorPos(C.byref(point))
    # Fully transparent pixels of a layered window pass the hit test to the window below.
    return int(user32.GetAncestor(user32.WindowFromPoint(point), 2) or 0)


def same_target(target):
    try:
        current = foreground()
        return all(current[x] == target[x] for x in ("hwnd", "pid", "started"))
    except (OSError, RuntimeError, psutil.Error):
        return False


def target_exists(target):
    try:
        if not win32gui.IsWindow(target["hwnd"]):
            return False
        _, pid = win32process.GetWindowThreadProcessId(target["hwnd"])
        return pid == target["pid"] and psutil.Process(pid).create_time() == target["started"]
    except (OSError, RuntimeError, psutil.Error):
        return False


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


class KeyboardInput(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class MouseInput(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class InputUnion(C.Union):
    _fields_ = [("ki", KeyboardInput), ("mi", MouseInput)]


class Input(C.Structure):
    _fields_ = [("type", W.DWORD), ("data", InputUnion)]


user32.SendInput.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
user32.SendInput.restype = W.UINT


def held_modifiers():
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (16, 17, 18, 91, 92))


def wait_modifiers(timeout=1.5):
    deadline = time.monotonic() + timeout
    while held_modifiers():
        if time.monotonic() >= deadline:
            raise RuntimeError("Release modifier keys before running the action")
        time.sleep(0.02)


def send_keys(text, target):
    if not same_target(target):
        raise RuntimeError("The active window changed")
    mods, key = parse_key(text)
    modifier_keys = [vk for flag, vk in ((1, 18), (2, 17), (4, 16), (8, 91)) if mods & flag]
    if held_modifiers():
        raise RuntimeError("Release modifier keys before running the action")
    keys = modifier_keys + [key]
    events = [Input(1, InputUnion(ki=KeyboardInput(vk, 0, 0, 0, INPUT_MARKER))) for vk in keys]
    events += [Input(1, InputUnion(ki=KeyboardInput(vk, 0, 2, 0, INPUT_MARKER))) for vk in reversed(keys)]
    array = (Input * len(events))(*events)
    if user32.SendInput(len(array), array, C.sizeof(Input)) != len(array):
        ups = (Input * len(keys))(*[Input(1, InputUnion(ki=KeyboardInput(vk, 0, 2, 0, INPUT_MARKER))) for vk in reversed(keys)])
        user32.SendInput(len(ups), ups, C.sizeof(Input))
        raise RuntimeError("Windows refused keyboard input")


class Hotkeys(QAbstractNativeEventFilter):
    bindings: dict
    callback: object
    suspended: bool

    def __init__(self, callback):
        super().__init__()
        self.bindings = {}
        self.callback = callback
        self.suspended = False

    def configure(self, keys):
        wanted = {parse_key(x): x for x in keys}
        additions = {}
        try:
            for combination, name in wanted.items():
                if combination in self.bindings:
                    continue
                identifier = next(x for x in range(100, 2000) if x not in [v[0] for v in self.bindings.values()] + [v[0] for v in additions.values()])
                if not user32.RegisterHotKey(None, identifier, combination[0] | 0x4000, combination[1]):
                    raise ValueError(f"Shortcut already in use: {name}")
                additions[combination] = (identifier, name)
        except Exception:
            for identifier, _ in additions.values():
                user32.UnregisterHotKey(None, identifier)
            raise
        for combination, (identifier, _) in self.bindings.items():
            if combination not in wanted:
                user32.UnregisterHotKey(None, identifier)
        self.bindings = {k: (v[0], wanted[k]) for k, v in (self.bindings | additions).items() if k in wanted}

    def nativeEventFilter(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == 0x0312:
            if not self.suspended:
                for identifier, name in self.bindings.values():
                    if msg.wParam == identifier:
                        self.callback(name)
            return True, 0
        return False, 0

    def close(self):
        for identifier, _ in self.bindings.values():
            user32.UnregisterHotKey(None, identifier)
        self.bindings.clear()


def activate(process_name, cancel, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancel.is_set():
            raise RuntimeError("Cancelled")
        matches = []
        def visit(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if psutil.Process(pid).name().lower() == process_name.lower():
                        matches.append(hwnd)
                except psutil.Error:
                    pass
        win32gui.EnumWindows(visit, None)
        if len(matches) > 1:
            raise RuntimeError("Several matching windows exist. Activate the intended window first.")
        if matches:
            win32gui.ShowWindow(matches[0], 9)
            win32gui.SetForegroundWindow(matches[0])
            result = foreground()
            if result["hwnd"] == matches[0]:
                return result
        cancel.wait(0.1)
    raise TimeoutError("The requested application window did not become active")
