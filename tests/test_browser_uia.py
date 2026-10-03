import os
import time
import psutil
import pytest
import win32gui
import win32process
from desktop_ai_assistant import windows_text
from desktop_ai_assistant.text import TextAccessDenied


pytestmark = pytest.mark.skipif(not os.environ.get("DESKTOP_AI_UIA_BROWSER_HWND"), reason="needs the owned browser UIA fixture window")


def fixture_worker(connection, revision):
    import comtypes.client
    from desktop_ai_assistant import clipboard
    state = {}

    class Requests:
        def recv(self):
            request = connection.recv()
            state.update(request)
            return request

        def __getattr__(self, name):
            return getattr(connection, name)

    class Automation:
        automation: object

        def __init__(self, automation):
            self.automation = automation

        def GetFocusedElement(self):
            root = self.automation.ElementFromHandle(state["target"]["hwnd"])
            condition = self.automation.CreatePropertyCondition(30011, state["target"]["fixtureId"])
            deadline = time.monotonic() + 2
            element = root.FindFirst(4, condition)
            while not element and time.monotonic() < deadline:
                time.sleep(0.05)
                element = root.FindFirst(4, condition)
            assert element, "Fixture control not found"
            if state["target"]["fixtureId"] not in ("RootWebArea", "password"):
                module = comtypes.client.GetModule("UIAutomationCore.dll")
                pattern = element.GetCurrentPattern(10014).QueryInterface(module.IUIAutomationTextPattern)
                part = "only" if state["target"]["fixtureId"] == "readonly" else "world"
                pattern.DocumentRange.FindText(part, False, False).Select()
            return element

        def __getattr__(self, name):
            return getattr(self.automation, name)

    factory = comtypes.client.CreateObject
    comtypes.client.CreateObject = lambda *args, **kwargs: Automation(factory(*args, **kwargs))
    windows_text.same_target = lambda target: state.get("op") in ("capture", "read_selection")

    def no_input(*args):
        raise AssertionError("Reading and deferred insertion must not touch the clipboard or keyboard")

    clipboard.Clipboard.replace = no_input
    clipboard.Clipboard.backup = no_input
    windows_text.send_keys = no_input
    windows_text._worker(Requests(), revision)


def test_browser_uia_worker_reads_real_controls_and_defers_plain_insertion(monkeypatch):
    hwnd = int(os.environ["DESKTOP_AI_UIA_BROWSER_HWND"])
    assert win32gui.GetWindowText(hwnd).startswith("Desktop AI UIA fixture")
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process = psutil.Process(pid)
    target = {"hwnd": hwnd, "pid": pid, "started": process.create_time(), "process": process.name(), "title": win32gui.GetWindowText(hwnd)}
    monkeypatch.setattr(windows_text, "_worker", fixture_worker)
    adapter = windows_text.WindowsText()
    try:
        for identifier, expected in (("RootWebArea", "Selected page content"), ("single", "world"), ("multi", "world"), ("rich", "world"), ("readonly", "only")):
            target["fixtureId"] = identifier
            assert adapter.read_selection(target)["text"] == expected
            if identifier in ("single", "multi", "rich"):
                snapshot = adapter.capture(target)
                assert snapshot["text"] == "world" and (snapshot["start"], snapshot["end"]) == (6, 11)
                snapshot["foregroundOnly"] = True
                assert adapter.read_selection({**target, "fixtureId": "readonly"})["text"] == "only"
                assert adapter.apply(snapshot, "Earth", allow_background=True) == {"deferred": True}
            else:
                with pytest.raises(RuntimeError, match="Editability"):
                    adapter.capture(target)
        target["fixtureId"] = "password"
        with pytest.raises(TextAccessDenied, match="Password"):
            adapter.read_selection(target)
        with pytest.raises(TextAccessDenied, match="Password"):
            adapter.capture(target)
    finally:
        adapter.close()


@pytest.mark.skipif(os.environ.get("DESKTOP_AI_LIVE_TESTS") != "1", reason="needs an interactive desktop for the owned fixture paste")
def test_browser_uia_verifies_foreground_paste_into_owned_fields():
    import comtypes.client
    from desktop_ai_assistant.winapi import foreground
    hwnd = int(os.environ["DESKTOP_AI_UIA_BROWSER_HWND"])
    assert win32gui.GetWindowText(hwnd).startswith("Desktop AI UIA fixture")
    module = comtypes.client.GetModule("UIAutomationCore.dll")
    automation = comtypes.client.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
    root = automation.ElementFromHandle(hwnd)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except win32gui.error:
        pytest.skip("Windows refused fixture activation; activate the isolated browser before running the live paste test")
    assert foreground()["hwnd"] == hwnd
    adapter = windows_text.WindowsText()
    try:
        for identifier in ("single", "multi", "rich"):
            element = root.FindFirst(4, automation.CreatePropertyCondition(30011, identifier))
            element.SetFocus()
            pattern = element.GetCurrentPattern(10014).QueryInterface(module.IUIAutomationTextPattern)
            pattern.DocumentRange.FindText("world", False, False).Select()
            target = foreground()
            assert target["hwnd"] == hwnd
            snapshot = adapter.capture(target)
            assert snapshot["text"] == "world"
            snapshot["foregroundOnly"] = True
            after = adapter.apply(snapshot, "Earth", adapter.input_tick(), allow_background=True)
            assert after["full"] == snapshot["full"].replace("world", "Earth")
            assert pattern.DocumentRange.GetText(-1) == after["full"]
    finally:
        adapter.close()
