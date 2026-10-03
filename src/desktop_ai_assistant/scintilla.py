import contextlib
import ctypes as C
from ctypes import wintypes as W
import win32process

kernel32 = C.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
kernel32.VirtualAllocEx.restype = C.c_void_p
kernel32.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
kernel32.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
kernel32.CloseHandle.argtypes = [W.HANDLE]

GETLENGTH, GETTEXT, GETCODEPAGE, GETREADONLY = 2006, 2182, 2137, 2140
GETSELECTIONSTART, GETSELECTIONEND, GETSELECTIONS, SELECTIONISRECTANGLE = 2143, 2145, 2570, 2372
SETTARGETSTART, SETTARGETEND, REPLACETARGET = 2190, 2192, 2194


class Scintilla:
    """Scintilla exposes no UI Automation text, and its messages take pointers into the editor process."""
    hwnd: int
    message: object
    process: int

    def __init__(self, hwnd, message):
        self.hwnd = hwnd
        self.message = message
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        # PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
        self.process = kernel32.OpenProcess(0x38, False, pid)
        if not self.process:
            raise RuntimeError("The editor runs with higher rights than the assistant")

    def close(self):
        kernel32.CloseHandle(self.process)

    @contextlib.contextmanager
    def remote(self, size):
        address = kernel32.VirtualAllocEx(self.process, None, size, 0x3000, 0x04)
        if not address:
            raise RuntimeError("Could not reach the editor memory")
        try:
            yield address
        finally:
            kernel32.VirtualFreeEx(self.process, address, 0, 0x8000)

    def send(self, code, wparam=0, lparam=0):
        return self.message(self.hwnd, code, wparam, lparam)

    def encoding(self):
        return "utf-8" if self.send(GETCODEPAGE) == 65001 else "mbcs"

    def read(self):
        if self.send(GETSELECTIONS) > 1 or self.send(SELECTIONISRECTANGLE):
            raise RuntimeError("Use a single text selection")
        length = self.send(GETLENGTH)
        if length > 800000:
            raise RuntimeError("This field is too large")
        data = C.create_string_buffer(length + 2)
        # Scintilla 5 writes length bytes plus a terminator, older versions length - 1 plus a terminator.
        with self.remote(length + 2) as address:
            self.send(GETTEXT, length + 1, address)
            if not kernel32.ReadProcessMemory(self.process, address, data, length, None):
                raise RuntimeError("Could not read the editor text")
        raw = data.raw[:length]
        start, end = self.send(GETSELECTIONSTART), self.send(GETSELECTIONEND)
        encoding = self.encoding()
        full = raw.decode(encoding)
        return full, len(raw[:start].decode(encoding)), len(raw[:end].decode(encoding))

    def readonly(self):
        return bool(self.send(GETREADONLY))

    def replace(self, full, start, end, text):
        encoding = self.encoding()
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError:
            raise RuntimeError("The document encoding cannot store the result; result kept in History") from None
        # The target range replaces text without moving the user's selection, so a background write is safe.
        with self.remote(len(data) + 1) as address:
            if not kernel32.WriteProcessMemory(self.process, address, data, len(data), None):
                raise RuntimeError("Could not write into the editor")
            self.send(SETTARGETSTART, len(full[:start].encode(encoding)))
            self.send(SETTARGETEND, len(full[:end].encode(encoding)))
            self.send(REPLACETARGET, len(data), address)
