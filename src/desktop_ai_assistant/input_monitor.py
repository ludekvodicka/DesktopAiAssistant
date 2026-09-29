import ctypes as C
from ctypes import wintypes as W
import multiprocessing as mp
import threading
from .winapi import INPUT_MARKER, user32


class KeyboardEvent(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class InputMonitor:
    revision: object
    thread: threading.Thread
    ready: threading.Event
    thread_id: int
    error: Exception | None

    def __init__(self):
        self.revision = mp.Value(C.c_uint64, 0, lock=False)
        self.ready = threading.Event()
        self.thread_id = 0
        self.error = None
        self.thread = threading.Thread(target=self.run, name="input-monitor", daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            self.close()
            raise RuntimeError("Input monitoring did not start")
        if self.error:
            raise self.error

    def run(self):
        callback_type = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, C.c_size_t, C.c_ssize_t)
        user32.SetWindowsHookExW.argtypes = [C.c_int, callback_type, W.HINSTANCE, W.DWORD]
        user32.SetWindowsHookExW.restype = W.HANDLE
        user32.CallNextHookEx.argtypes = [W.HANDLE, C.c_int, C.c_size_t, C.c_ssize_t]
        user32.CallNextHookEx.restype = C.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [W.HANDLE]
        user32.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
        user32.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
        user32.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, C.c_size_t, C.c_ssize_t]
        kernel32 = C.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = [W.LPCWSTR]
        kernel32.GetModuleHandleW.restype = W.HMODULE
        self.thread_id = kernel32.GetCurrentThreadId()
        hooks = []

        @callback_type
        def keyboard(code, message, data):
            if code >= 0 and message in (0x0100, 0x0104):
                if KeyboardEvent.from_address(data).dwExtraInfo != INPUT_MARKER:
                    self.revision.value += 1
            return user32.CallNextHookEx(None, code, message, data)

        @callback_type
        def mouse(code, message, data):
            # Movement and the release of the activation click do not change an editor.
            if code >= 0 and message in (0x0201, 0x0204, 0x0207, 0x020b, 0x020a, 0x020e):
                self.revision.value += 1
            return user32.CallNextHookEx(None, code, message, data)

        try:
            for kind, callback in ((13, keyboard), (14, mouse)):
                hook = user32.SetWindowsHookExW(kind, callback, kernel32.GetModuleHandleW(None), 0)
                if not hook:
                    raise C.WinError(C.get_last_error())
                hooks.append(hook)
            message = W.MSG()
            user32.PeekMessageW(C.byref(message), None, 0, 0, 0)
            self.ready.set()
            while user32.GetMessageW(C.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(C.byref(message))
                user32.DispatchMessageW(C.byref(message))
        except Exception as error:
            self.error = error
            self.ready.set()
        finally:
            for hook in hooks:
                user32.UnhookWindowsHookEx(hook)

    def close(self):
        if self.thread_id and self.thread.is_alive():
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(2)
