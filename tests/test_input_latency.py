import ctypes as C
from ctypes import wintypes as W
import multiprocessing as mp
import os
import queue
import sys
import threading
import time
import winreg
import psutil
import pytest
import win32api
import win32gui
from desktop_ai_assistant.input_monitor import InputMonitor
from desktop_ai_assistant.winapi import Input, InputUnion, KeyboardInput, MouseInput, INPUT_MARKER, user32

pytestmark = pytest.mark.skipif(
    os.environ.get("DESKTOP_AI_LATENCY_TESTS") != "1",
    reason="The legacy run delays real mouse input for about 2 s; set DESKTOP_AI_LATENCY_TESTS=1 to opt in",
)

MOVES, SPACING, MOVE_MARKER = 10, 0.3, 0x4C415400
HOOK_CALLBACK = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, C.c_size_t, C.c_ssize_t)
hook_user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
hook_user32.SetWindowsHookExW.argtypes = [C.c_int, HOOK_CALLBACK, W.HINSTANCE, W.DWORD]
hook_user32.SetWindowsHookExW.restype = W.HANDLE
hook_user32.CallNextHookEx.argtypes = [W.HANDLE, C.c_int, C.c_size_t, C.c_ssize_t]
hook_user32.CallNextHookEx.restype = C.c_ssize_t
hook_user32.UnhookWindowsHookEx.argtypes = [W.HANDLE]
hook_user32.UnhookWindowsHookEx.restype = W.BOOL
hook_user32.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
hook_user32.GetMessageW.restype = C.c_int
hook_user32.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
hook_user32.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]
hook_user32.PostThreadMessageW.restype = W.BOOL
hook_user32.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
hook_user32.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
hook_user32.DispatchMessageW.restype = C.c_ssize_t
kernel32.GetModuleHandleW.argtypes = [W.LPCWSTR]
kernel32.GetModuleHandleW.restype = W.HMODULE
kernel32.GetCurrentThreadId.restype = W.DWORD
kernel32.GetTickCount.restype = W.DWORD


class KeyboardEvent(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class MouseEvent(C.Structure):
    _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


def _receive(connection, expected, timeout=20):
    if not connection.poll(timeout):
        raise TimeoutError(f"No {expected!r} response within {timeout} s")
    tag, value = connection.recv()
    if tag == "error":
        raise RuntimeError(value)
    elif tag == expected:
        return value
    else:
        raise ValueError(f"Expected {expected!r}, received {tag!r}")


def _hook_loop(callbacks, ready):
    hooks = []
    try:
        for kind, callback in callbacks:
            hook = hook_user32.SetWindowsHookExW(kind, callback, kernel32.GetModuleHandleW(None), 0)
            if not hook:
                raise C.WinError(C.get_last_error())
            hooks.append(hook)
        message = W.MSG()
        hook_user32.PeekMessageW(C.byref(message), None, 0, 0, 0)
        ready.put((kernel32.GetCurrentThreadId(), None))
        while True:
            result = hook_user32.GetMessageW(C.byref(message), None, 0, 0)
            if result == -1:
                raise C.WinError(C.get_last_error())
            if result == 0:
                return
            hook_user32.TranslateMessage(C.byref(message))
            hook_user32.DispatchMessageW(C.byref(message))
    except Exception as error:
        ready.put((0, error))
    finally:
        for hook in hooks:
            hook_user32.UnhookWindowsHookEx(hook)


def _start_hooks(callbacks):
    ready = queue.Queue()
    thread = threading.Thread(target=_hook_loop, args=(callbacks, ready), daemon=True)
    thread.start()
    identifier, error = ready.get(timeout=5)
    if error is not None:
        raise error
    return thread, identifier


def _stop_hooks(hooks):
    thread, identifier = hooks
    if thread.is_alive():
        if not hook_user32.PostThreadMessageW(identifier, 0x0012, 0, 0):
            raise C.WinError(C.get_last_error())
        thread.join(3)
        if thread.is_alive():
            raise TimeoutError("Hook thread did not stop")


def _legacy_hooks():
    # The 0.4.6 callbacks must acquire the victim's GIL even for an ignored mouse move.
    revision, clicks = 0, 0

    @HOOK_CALLBACK
    def keyboard(code, message, data):
        nonlocal revision
        if code >= 0 and message in (0x0100, 0x0104):
            if KeyboardEvent.from_address(data).dwExtraInfo != INPUT_MARKER:
                revision += 1
        return hook_user32.CallNextHookEx(None, code, message, data)

    @HOOK_CALLBACK
    def mouse(code, message, data):
        nonlocal revision, clicks
        if code >= 0 and message in (0x0201, 0x0204, 0x0207, 0x020b, 0x020a, 0x020e):
            revision += 1
        if code >= 0 and message in (0x0201, 0x0204, 0x0207, 0x020b):
            clicks += 1
        return hook_user32.CallNextHookEx(None, code, message, data)

    return _start_hooks(((13, keyboard), (14, mouse)))


def _probe(connection):
    lags, hooks = {}, None

    @HOOK_CALLBACK
    def mouse(code, message, data):
        if code >= 0 and message == 0x0200:
            event = MouseEvent.from_address(data)
            index = event.dwExtraInfo - MOVE_MARKER
            if 0 <= index < MOVES:
                lags[index] = (kernel32.GetTickCount() - event.time) & 0xFFFFFFFF
        return hook_user32.CallNextHookEx(None, code, message, data)

    try:
        # The newer victim hook runs first; these timestamps include its delay.
        hooks = _start_hooks(((14, mouse),))
        connection.send(("ready", None))
        _receive(connection, "stop", 60)
        _stop_hooks(hooks)
        hooks = None
        connection.send(("lags", sorted(lags.items())))
    except Exception as error:
        connection.send(("error", str(error) or type(error).__name__))
    finally:
        try:
            if hooks is not None:
                _stop_hooks(hooks)
        finally:
            connection.close()


def _send_key():
    events = (Input * 2)(*[Input(1, InputUnion(ki=KeyboardInput(135, 0, flags, 0, 0))) for flags in (0, 2)])
    if user32.SendInput(2, events, C.sizeof(Input)) != 2:
        user32.SendInput(1, C.byref(events[1]), C.sizeof(Input))
        raise RuntimeError("Windows refused the F24 sentinel")


def _reader(revision, connection):
    try:
        connection.send(("ready", None))
        _receive(connection, "go", 30)
        baseline, started = revision.value, time.perf_counter()
        _send_key()
        while revision.value == baseline and time.perf_counter() - started < 1:
            time.sleep(0.001)
        elapsed = time.perf_counter() - started
        if revision.value == baseline:
            raise TimeoutError("The F24 sentinel was not counted within 1 s")
        connection.send(("counted", elapsed))
    except Exception as error:
        connection.send(("error", str(error) or type(error).__name__))
    finally:
        connection.close()


def _spin(started, stop):
    started.set()
    while not stop.is_set():
        pass


def _victim(connection, kind, reader_end, interval):
    monitor, reader, hooks, load = None, None, None, None
    stop, started = threading.Event(), threading.Event()
    previous_interval = sys.getswitchinterval()
    try:
        if kind == "legacy":
            hooks = _legacy_hooks()
        elif kind == "raw":
            monitor = InputMonitor()
            reader = mp.get_context("spawn").Process(target=_reader, args=(monitor.revision, reader_end), daemon=True)
            reader.start()
        else:
            raise ValueError(kind)
        reader_end.close()
        sys.setswitchinterval(interval)
        load = threading.Thread(target=_spin, args=(started, stop), daemon=True)
        load.start()
        if not started.wait(3):
            raise TimeoutError("GIL load did not start")
        connection.send(("loaded", None))
        _receive(connection, "stop", 60)
    except Exception as error:
        connection.send(("error", str(error) or type(error).__name__))
    finally:
        stop.set()
        sys.setswitchinterval(previous_interval)
        if load is not None:
            load.join(3)
        try:
            if hooks is not None:
                _stop_hooks(hooks)
        finally:
            if reader is not None:
                _finish_process(reader)
            if monitor is not None:
                monitor.close()
            reader_end.close()
            connection.close()


def _finish_process(process, connection=None):
    if process.pid is None:
        return
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    if connection is not None and process.is_alive():
        try:
            connection.send(("stop", None))
        except (BrokenPipeError, EOFError, OSError):
            pass
    process.join(5 if connection is not None else 0)
    if process.is_alive():
        process.terminate()
        process.join(3)
    if process.is_alive():
        process.kill()
        process.join(3)
    for child in descendants:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(descendants, timeout=3)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=3)
    assert not process.is_alive() and not alive, "Latency test processes did not stop"


def _hooks_timeout():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            value, _ = winreg.QueryValueEx(key, "LowLevelHooksTimeout")
            return int(value)
    except FileNotFoundError:
        return None


@pytest.mark.parametrize("kind", ["legacy", "raw"])
def test_system_input_delay(kind):
    timeout = _hooks_timeout()
    interval = 0.2 if timeout is None or timeout >= 250 else timeout * 0.0008
    assert interval > 0, "LowLevelHooksTimeout must allow a positive GIL hold"
    legacy_bound = interval * 0.75
    print(f"{kind}: LowLevelHooksTimeout {timeout if timeout is not None else 'default'}, "
          f"GIL interval {interval * 1000:.1f} ms, legacy bound {legacy_bound * 1000:.1f} ms", flush=True)
    context = mp.get_context("spawn")
    probe_end, probe_child = context.Pipe()
    victim_end, victim_child = context.Pipe()
    reader_end, reader_child = context.Pipe()
    probe = context.Process(target=_probe, args=(probe_child,), name="latency-probe", daemon=True)
    victim = context.Process(target=_victim, args=(victim_child, kind, reader_child, interval),
                             name="latency-victim", daemon=False)
    cursor = win32gui.GetCursorPos()
    try:
        probe.start()
        probe_child.close()
        _receive(probe_end, "ready")
        victim.start()
        victim_child.close()
        reader_child.close()
        _receive(victim_end, "loaded")
        if kind == "raw":
            _receive(reader_end, "ready")
        elif kind == "legacy":
            pass
        else:
            raise ValueError(kind)
        calls = []
        for index in range(MOVES):
            event = Input(0, InputUnion(mi=MouseInput(1 if index % 2 else -1, 0, 0, 0x0001, 0, MOVE_MARKER + index)))
            start = time.perf_counter()
            sent = user32.SendInput(1, C.byref(event), C.sizeof(Input))
            calls.append(time.perf_counter() - start)
            assert sent == 1, "Windows refused the relative mouse move"
            time.sleep(max(0, SPACING - calls[-1]))
        probe_end.send(("stop", None))
        indexed_lags = _receive(probe_end, "lags")
        lags = [lag for _, lag in indexed_lags]
        worst = max(max(lags, default=0) / 1000, max(calls))
        print(f"{kind}: probe lags by move {indexed_lags} ms; "
              f"SendInput calls {[round(value * 1000, 3) for value in calls]} ms; "
              f"SendInput max {max(calls) * 1000:.3f} ms; worst {worst * 1000:.3f} ms", flush=True)
        assert len(lags) >= MOVES - 1, f"Probe saw only {len(lags)} of {MOVES} marked moves"
        if kind == "legacy":
            assert worst >= legacy_bound, "The legacy positive control did not reproduce GIL input delay"
        elif kind == "raw":
            reader_end.send(("go", None))
            counted = _receive(reader_end, "counted")
            print(f"raw: sentinel counted after {counted * 1000:.3f} ms with the victim's GIL busy", flush=True)
            assert worst < 0.050, f"Raw Input system delay was {worst * 1000:.3f} ms"
            assert counted < 0.050, f"Raw Input sentinel delay was {counted * 1000:.3f} ms"
        else:
            raise ValueError(kind)
    finally:
        try:
            _finish_process(victim, victim_end)
        finally:
            try:
                _finish_process(probe, probe_end)
            finally:
                for connection in (probe_end, probe_child, victim_end, victim_child, reader_end, reader_child):
                    connection.close()
                win32api.SetCursorPos(cursor)
