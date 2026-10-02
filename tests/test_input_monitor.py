import ctypes as C
import time
import win32gui
import win32api
import win32con
from desktop_ai_assistant.input_monitor import InputMonitor
from desktop_ai_assistant.winapi import Input, InputUnion, KeyboardInput, MouseInput, INPUT_MARKER, user32


def send(*events):
    array = (Input * len(events))(*events)
    assert user32.SendInput(len(array), array, C.sizeof(Input)) == len(array)
    win32gui.PumpWaitingMessages()


def send_key(extra):
    events = [Input(1, InputUnion(ki=KeyboardInput(135, 0, flags, 0, extra))) for flags in (0, 2)]
    try:
        send(*events)
    except Exception:
        user32.SendInput(1, C.byref(events[-1]), C.sizeof(Input))
        raise


def left_click():
    events = [Input(0, InputUnion(mi=MouseInput(0, 0, 0, flags, 0, 0))) for flags in (0x0002, 0x0004)]
    try:
        send(*events)
    except Exception:
        user32.SendInput(1, C.byref(events[-1]), C.sizeof(Input))
        raise


def effect(monitor, action, expected):
    # The following unmarked F24 orders the observation after the action's raw input.
    revision, clicks = monitor.revision.value, monitor.clicks.value
    action()
    send_key(0)
    deadline = time.monotonic() + 1
    while monitor.revision.value - revision < expected + 1 and time.monotonic() < deadline:
        win32gui.PumpWaitingMessages()
        time.sleep(0.005)
    time.sleep(0.05)
    return monitor.revision.value - revision - 1, monitor.clicks.value - clicks


def test_real_input_ignores_motion_and_own_keys_but_detects_user_actions():
    window = win32gui.CreateWindowEx(0, "STATIC", "Owned input monitor test", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                   50, 50, 300, 180, 0, 0, 0, None)
    cursor = win32gui.GetCursorPos()
    monitor = None
    try:
        monitor = InputMonitor()
        assert effect(monitor, lambda: send(Input(0, InputUnion(mi=MouseInput(5, 5, 0, 0x0001, 0, 0)))), 0) == (0, 0)
        assert effect(monitor, lambda: send_key(INPUT_MARKER), 0) == (0, 0)
        assert effect(monitor, lambda: send_key(0), 1) == (1, 0)
        point = win32gui.ClientToScreen(window, (100, 80))
        win32api.SetCursorPos(point)
        assert win32gui.WindowFromPoint(point) == window
        assert effect(monitor, left_click, 1) == (1, 1)
    finally:
        if monitor is not None:
            monitor.close()
        win32api.SetCursorPos(cursor)
        win32gui.DestroyWindow(window)
    assert not monitor.process.is_alive()
