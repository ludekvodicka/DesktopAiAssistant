import ctypes as C
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import psutil
import pytest
import desktop_ai_assistant
from desktop_ai_assistant import input_monitor, windows_text
from desktop_ai_assistant.input_monitor import INPUT_MARKER, InputMonitor, RawInput, count


def report(dw_type):
    raw = RawInput()
    raw.header.dwType = dw_type
    return raw


def keyboard(flags=0, extra=0, message=0x0100):
    raw = report(1)
    raw.data.keyboard.Flags = flags
    raw.data.keyboard.ExtraInformation = extra
    raw.data.keyboard.Message = message
    return raw


def mouse(buttons=0, extra=0):
    raw = report(0)
    raw.data.mouse.ulButtons = buttons
    raw.data.mouse.lLastX = 4
    raw.data.mouse.lLastY = -3
    raw.data.mouse.ulExtraInformation = extra
    return raw


@pytest.mark.parametrize("raw,expected", [
    pytest.param(keyboard(extra=INPUT_MARKER), (0, 0), id="marked-key"),
    pytest.param(keyboard(flags=1, extra=INPUT_MARKER), (0, 0), id="marked-key-up"),
    pytest.param(keyboard(), (1, 0), id="key-down"),
    pytest.param(keyboard(extra=7), (1, 0), id="other-synthetic-key"),
    pytest.param(keyboard(flags=1, message=0x0101), (0, 0), id="key-up"),
    pytest.param(keyboard(message=0x0104), (1, 0), id="system-key-down"),
    pytest.param(keyboard(flags=1, message=0x0105), (0, 0), id="system-key-up"),
    pytest.param(keyboard(flags=2), (1, 0), id="extended-key-down"),
    pytest.param(keyboard(flags=3), (0, 0), id="extended-key-up"),
    pytest.param(keyboard(message=0xFFFF), (1, 0), id="unusual-key-message"),
    pytest.param(mouse(), (0, 0), id="movement"),
    pytest.param(mouse(0x0002), (0, 0), id="left-up"),
    pytest.param(mouse(0x0008 | 0x0020 | 0x0080 | 0x0200), (0, 0), id="other-button-ups"),
    pytest.param(mouse(0x0001), (1, 1), id="left-down"),
    pytest.param(mouse(0x0004), (1, 1), id="right-down"),
    pytest.param(mouse(0x0010), (1, 1), id="middle-down"),
    pytest.param(mouse(0x0040), (1, 1), id="x1-down"),
    pytest.param(mouse(0x0100), (1, 1), id="x2-down"),
    pytest.param(mouse(0x0001 | 0x0004), (2, 2), id="two-buttons"),
    pytest.param(mouse(0x0001 | 0x0004 | 0x0010 | 0x0040 | 0x0100), (5, 5), id="all-buttons"),
    pytest.param(mouse(0x0001, extra=INPUT_MARKER), (1, 1), id="marked-mouse-button"),
    pytest.param(mouse(0x0400), (1, 0), id="vertical-wheel"),
    pytest.param(mouse(0x0800), (1, 0), id="horizontal-wheel"),
    pytest.param(mouse(0x0400 | 0x0800), (2, 0), id="both-wheels"),
    pytest.param(mouse(0x0400 | (120 << 16)), (1, 0), id="positive-wheel-data"),
    pytest.param(mouse(0x0800 | (0xFF88 << 16)), (1, 0), id="negative-wheel-data"),
    pytest.param(mouse(0x0001 | 0x0002 | 0x0400 | 0x0800), (3, 1), id="mixed-transitions"),
])
def test_count_keeps_input_totals(raw, expected):
    assert count(raw) == expected


def test_each_repeated_key_make_counts():
    raw = keyboard()
    assert [count(raw) for _ in range(3)] == [(1, 0), (1, 0), (1, 0)]


def test_unregistered_report_types_are_refused():
    with pytest.raises(ValueError, match="Unregistered raw input type 2"):
        count(report(2))


def test_no_global_hook_in_the_application():
    package = Path(desktop_ai_assistant.__file__).parent
    assert [str(path.relative_to(package)) for path in package.rglob("*.py")
            if "SetWindowsHookEx" in path.read_text("utf-8")] == []
    lock = (Path(__file__).resolve().parents[1] / "requirements.lock.txt").read_text("utf-8")
    assert {line.split("==")[0].lower() for line in lock.splitlines()} & {
        "pynput", "keyboard", "mouse", "pyhook",
    } == set()


def test_monitor_starts_and_closes_idempotently():
    monitor = InputMonitor()
    try:
        assert monitor.process.is_alive()
        assert monitor.process.pid != os.getpid()
        monitor.close()
        assert not monitor.process.is_alive()
        monitor.close()
        assert not monitor.process.is_alive()
    finally:
        monitor.close()


def test_input_tick_reports_monitor_death():
    adapter = windows_text.WindowsText()
    try:
        assert adapter.input_tick() >= 0
        adapter.input_monitor.process.kill()
        adapter.input_monitor.process.join(3)
        assert not adapter.input_monitor.process.is_alive()
        with pytest.raises(RuntimeError) as error:
            adapter.input_tick()
        assert str(error.value) == "Input monitoring stopped. Restart the assistant."
    finally:
        adapter.close()


HELPER = """
import time
from desktop_ai_assistant.input_monitor import InputMonitor

if __name__ == "__main__":
    monitor = InputMonitor()
    print(monitor.process.pid, flush=True)
    time.sleep(60)
"""


def test_monitor_exits_within_three_seconds_of_parent_hard_kill():
    helper = subprocess.Popen([sys.executable, "-c", HELPER], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
    output = []
    reader = threading.Thread(target=lambda: output.append(helper.stdout.readline()), daemon=True)
    child = None
    try:
        reader.start()
        reader.join(15)
        assert not reader.is_alive(), "Monitor parent did not report its child PID within 15 s"
        assert output and output[0].strip().isdigit(), output
        child = psutil.Process(int(output[0]))
        assert child.is_running()
        helper.kill()
        child.wait(3)
        helper.wait(3)
    finally:
        descendants = psutil.Process(helper.pid).children(recursive=True) if helper.poll() is None else []
        if child is not None:
            descendants.append(child)
        if helper.poll() is None:
            helper.kill()
        helper.wait(3)
        for process in descendants:
            try:
                process.kill()
                process.wait(3)
            except psutil.NoSuchProcess:
                pass
        reader.join(3)
        helper.stdout.close()


def registration_failure_worker(connection, revision, clicks):
    def denied(*args):
        C.set_last_error(5)
        return False

    input_monitor.user32.RegisterRawInputDevices = denied
    input_monitor._monitor(connection, revision, clicks)


def eof_worker(connection, revision, clicks):
    connection.close()


def crash_worker(connection, revision, clicks):
    os._exit(42)


def silent_worker(connection, revision, clicks):
    time.sleep(60)


@pytest.fixture
def monitor_resources(monkeypatch):
    processes, connections = [], []
    make_process, make_pipe = input_monitor.mp.Process, input_monitor.mp.Pipe

    def process(*args, **kwargs):
        child = make_process(*args, **kwargs)
        processes.append(child)
        return child

    def pipe(*args, **kwargs):
        endpoints = make_pipe(*args, **kwargs)
        connections.extend(endpoints)
        return endpoints

    monkeypatch.setattr(input_monitor.mp, "Process", process)
    monkeypatch.setattr(input_monitor.mp, "Pipe", pipe)
    try:
        yield processes, connections
    finally:
        for child in processes:
            if child.is_alive():
                child.terminate()
            if child.pid is not None:
                child.join(3)
            child.close()
        for connection in connections:
            connection.close()


@pytest.mark.parametrize("worker,message", [
    pytest.param(registration_failure_worker, r"\[WinError 5\]", id="registration-error"),
    pytest.param(eof_worker, "the monitor process ended", id="child-eof"),
    pytest.param(crash_worker, "the monitor process ended", id="child-crash"),
    pytest.param(silent_worker, "no answer within 10 s", id="child-timeout"),
])
def test_start_failure_is_explained_and_resources_are_closed(monkeypatch, monitor_resources, worker, message):
    monkeypatch.setattr(input_monitor, "_monitor", worker)
    if worker is silent_worker:
        wait = input_monitor.wait
        monkeypatch.setattr(input_monitor, "wait", lambda handles, timeout: wait(handles, 0.1))
    with pytest.raises(RuntimeError, match=f"Input monitoring did not start: {message}"):
        InputMonitor()
    processes, connections = monitor_resources
    assert len(processes) == 1
    assert not processes[0].is_alive()
    assert processes[0].exitcode is not None
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)


def test_launch_failure_closes_both_pipe_endpoints(monkeypatch, monitor_resources):
    def fail_start(self):
        raise OSError("Cannot launch monitor")

    monkeypatch.setattr(input_monitor.mp.process.BaseProcess, "start", fail_start)
    with pytest.raises(RuntimeError, match="Input monitoring did not start: Cannot launch monitor"):
        InputMonitor()
    processes, connections = monitor_resources
    assert len(processes) == 1
    assert processes[0].pid is None
    assert not processes[0].is_alive()
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)
