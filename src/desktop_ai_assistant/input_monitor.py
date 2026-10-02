import ctypes as C
from ctypes import wintypes as W
import multiprocessing as mp
from multiprocessing.connection import wait
from .winapi import INPUT_MARKER


class RawInputDevice(C.Structure):
    _fields_ = [("usUsagePage", W.USHORT), ("usUsage", W.USHORT), ("dwFlags", W.DWORD), ("hwndTarget", W.HWND)]


class RawInputHeader(C.Structure):
    _fields_ = [("dwType", W.DWORD), ("dwSize", W.DWORD), ("hDevice", W.HANDLE), ("wParam", W.WPARAM)]


class RawMouse(C.Structure):
    # ctypes aligns ulButtons at offset 4; its low word holds flags, its high word holds wheel data.
    _fields_ = [("usFlags", W.USHORT), ("ulButtons", W.ULONG), ("ulRawButtons", W.ULONG),
                ("lLastX", W.LONG), ("lLastY", W.LONG), ("ulExtraInformation", W.ULONG)]


class RawKeyboard(C.Structure):
    _fields_ = [("MakeCode", W.USHORT), ("Flags", W.USHORT), ("Reserved", W.USHORT), ("VKey", W.USHORT),
                ("Message", W.UINT), ("ExtraInformation", W.ULONG)]


class RawInputData(C.Union):
    _fields_ = [("mouse", RawMouse), ("keyboard", RawKeyboard)]


class RawInput(C.Structure):
    _fields_ = [("header", RawInputHeader), ("data", RawInputData)]


user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                                   W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
user32.CreateWindowExW.restype = W.HWND
user32.RegisterRawInputDevices.argtypes = [C.POINTER(RawInputDevice), W.UINT, W.UINT]
user32.RegisterRawInputDevices.restype = W.BOOL
user32.GetRegisteredRawInputDevices.argtypes = [C.POINTER(RawInputDevice), C.POINTER(W.UINT), W.UINT]
user32.GetRegisteredRawInputDevices.restype = W.UINT
user32.GetRawInputData.argtypes = [W.HANDLE, W.UINT, C.c_void_p, C.POINTER(W.UINT), W.UINT]
user32.GetRawInputData.restype = W.UINT
user32.MsgWaitForMultipleObjectsEx.argtypes = [W.DWORD, C.POINTER(W.HANDLE), W.DWORD, W.DWORD, W.DWORD]
user32.MsgWaitForMultipleObjectsEx.restype = W.DWORD
user32.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
user32.PeekMessageW.restype = W.BOOL
user32.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
user32.DispatchMessageW.restype = C.c_ssize_t
kernel32.GetCurrentThread.argtypes = []
kernel32.GetCurrentThread.restype = W.HANDLE
kernel32.SetThreadPriority.argtypes = [W.HANDLE, C.c_int]
kernel32.SetThreadPriority.restype = W.BOOL

RIM_TYPEMOUSE, RIM_TYPEKEYBOARD = 0, 1
BUTTON_DOWNS = 0x0001 | 0x0004 | 0x0010 | 0x0040 | 0x0100
WHEELS = 0x0400 | 0x0800
RI_KEY_BREAK = 0x01
HWND_MESSAGE = W.HWND(-3)
RIDEV_INPUTSINK, WM_INPUT, RID_INPUT, PM_REMOVE = 0x0100, 0x00FF, 0x10000003, 0x0001
QS_ALLINPUT, MWMO_INPUTAVAILABLE, INFINITE = 0x04FF, 0x0004, 0xFFFFFFFF
WAIT_OBJECT_0, WAIT_FAILED, UINT_ERROR = 0, 0xFFFFFFFF, 0xFFFFFFFF
THREAD_PRIORITY_ABOVE_NORMAL = 1


def count(raw: RawInput) -> tuple[int, int]:
    if raw.header.dwType == RIM_TYPEMOUSE:
        flags = raw.data.mouse.ulButtons & 0xFFFF
        # One packet can carry several transitions; each changes the same counter as a separate report.
        downs = (flags & BUTTON_DOWNS).bit_count()
        return downs + (flags & WHEELS).bit_count(), downs
    elif raw.header.dwType == RIM_TYPEKEYBOARD:
        key = raw.data.keyboard
        return int(not key.Flags & RI_KEY_BREAK and key.ExtraInformation != INPUT_MARKER), 0
    else:
        raise ValueError(f"Unregistered raw input type {raw.header.dwType}")


def _register(window):
    wanted = (RawInputDevice * 2)(RawInputDevice(1, 6, RIDEV_INPUTSINK, window),
                                  RawInputDevice(1, 2, RIDEV_INPUTSINK, window))
    if not user32.RegisterRawInputDevices(wanted, 2, C.sizeof(RawInputDevice)):
        raise C.WinError(C.get_last_error())
    registered, number = (RawInputDevice * 8)(), W.UINT(8)
    if user32.GetRegisteredRawInputDevices(registered, C.byref(number), C.sizeof(RawInputDevice)) == UINT_ERROR:
        raise C.WinError(C.get_last_error())
    targets = {(x.usUsagePage, x.usUsage): x.hwndTarget for x in registered[:number.value]}
    if targets.get((1, 6)) != window or targets.get((1, 2)) != window:
        raise RuntimeError("Raw input registration does not target the monitor window")


def _monitor(connection, revision, clicks) -> None:
    try:
        try:
            window = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None)
            if not window:
                raise C.WinError(C.get_last_error())
            _register(window)
            if not kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_ABOVE_NORMAL):
                raise C.WinError(C.get_last_error())
        except Exception as error:
            connection.send(str(error) or type(error).__name__)
            return
        connection.send(None)
    finally:
        connection.close()
    parent = W.HANDLE(mp.parent_process().sentinel)
    message, raw, size = W.MSG(), RawInput(), W.UINT()
    while True:
        result = user32.MsgWaitForMultipleObjectsEx(1, C.byref(parent), INFINITE, QS_ALLINPUT, MWMO_INPUTAVAILABLE)
        if result == WAIT_OBJECT_0:
            return
        elif result == WAIT_OBJECT_0 + 1:
            while user32.PeekMessageW(C.byref(message), None, 0, 0, PM_REMOVE):
                if message.message == WM_INPUT:
                    size.value = C.sizeof(raw)
                    if user32.GetRawInputData(message.lParam, RID_INPUT, C.byref(raw), C.byref(size),
                                              C.sizeof(RawInputHeader)) == UINT_ERROR:
                        raise C.WinError(C.get_last_error())
                    keys, presses = count(raw)
                    revision.value += keys
                    clicks.value += presses
                user32.DispatchMessageW(C.byref(message))
        elif result == WAIT_FAILED:
            raise C.WinError(C.get_last_error())
        else:
            raise RuntimeError(f"Unexpected wait result {result}")


class InputMonitor:
    revision: object
    clicks: object
    process: mp.Process

    def __init__(self):
        self.revision = mp.Value(C.c_uint64, 0, lock=False)
        self.clicks = mp.Value(C.c_uint64, 0, lock=False)
        reader, writer = mp.Pipe(duplex=False)
        self.process = mp.Process(target=_monitor, args=(writer, self.revision, self.clicks),
                                  name="input-monitor", daemon=True)
        try:
            try:
                self.process.start()
            finally:
                writer.close()
            # A cold start of the frozen EXE can take several seconds.
            ready = wait([reader, self.process.sentinel], 10)
            if reader in ready:
                error = reader.recv()
            elif self.process.sentinel in ready:
                error = "the monitor process ended"
            else:
                error = "no answer within 10 s"
        except EOFError:
            error = "the monitor process ended"
        except Exception as failure:
            error = str(failure) or type(failure).__name__
        finally:
            reader.close()
        if error is not None:
            self.close()
            raise RuntimeError(f"Input monitoring did not start: {error}")

    def close(self):
        if self.process.is_alive():
            self.process.terminate()
        if self.process.pid is not None:
            self.process.join(2)
