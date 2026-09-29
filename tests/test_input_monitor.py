import ctypes as C
import time
import win32gui
import win32api
import win32con
from desktop_ai_assistant.input_monitor import InputMonitor
from desktop_ai_assistant.winapi import Input, InputUnion, KeyboardInput, MouseInput, INPUT_MARKER, user32


def test_real_input_ignores_motion_and_own_paste_but_detects_user_actions():
    window = win32gui.CreateWindowEx(0, "STATIC", "Owned input monitor test", win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
                                   50, 50, 300, 180, 0, 0, 0, None)
    monitor = InputMonitor()
    cursor = win32gui.GetCursorPos()

    def send(event):
        assert user32.SendInput(1, C.byref(event), C.sizeof(Input)) == 1
        win32gui.PumpWaitingMessages()

    try:
        baseline = monitor.revision.value
        win32api.SetCursorPos((100, 130))
        time.sleep(0.04)
        assert monitor.revision.value == baseline
        for flags in (0, 2):
            send(Input(1, InputUnion(ki=KeyboardInput(135, 0, flags, 0, INPUT_MARKER))))
        assert monitor.revision.value == baseline
        for flags in (0, 2):
            send(Input(1, InputUnion(ki=KeyboardInput(135, 0, flags, 0, 0))))
        assert monitor.revision.value == baseline + 1
        for flags in (0x0002, 0x0004):
            send(Input(0, InputUnion(mi=MouseInput(0, 0, 0, flags, 0, 0))))
        assert monitor.revision.value == baseline + 2
    finally:
        monitor.close()
        win32api.SetCursorPos(cursor)
        win32gui.DestroyWindow(window)
    assert not monitor.thread.is_alive()
