import copy
from types import SimpleNamespace
import pytest
from desktop_ai_assistant.engine import Engine
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.history import History
from desktop_ai_assistant import engine as engine_module


class TextField:
    snapshot: dict
    writes: list
    copies: list

    clipboard: str
    pastes: list

    def __init__(self):
        self.snapshot = {"kind": "windows", "target": {"process": "test.exe"}, "text": "helo", "full": "helo", "start": 0, "end": 4}
        self.writes = []
        self.copies = []
        self.clipboard = "helo clip"
        self.pastes = []

    def read_clipboard(self):
        return self.clipboard

    def write_clipboard(self, text):
        self.clipboard = text

    def paste(self, target, text, tick):
        self.pastes.append((target["process"], text, tick))

    def input_tick(self):
        return 123

    def capture(self, target):
        return copy.deepcopy(self.snapshot)

    def read_selection(self, target):
        snapshot = self.capture(target)
        return {"kind": "selection", "format": "plain", "text": snapshot["text"], "image": None, "origin": target["process"]}

    def copy_selection(self, target, plain=False):
        self.copies.append(target)
        if plain:
            return {"kind": "selection", "format": "plain", "text": "helo app", "image": None, "origin": target["process"]}
        return {"kind": "selection", "format": "markdown", "text": "# copied", "image": None, "origin": target["process"]}

    def apply(self, snapshot, text, tick=None, allow_background=False):
        if self.snapshot["full"] != snapshot["full"]:
            raise RuntimeError("The original field changed")
        self.writes.append(text)
        return {**snapshot, "full": text}


@pytest.fixture
def runner(tmp_path, monkeypatch):
    class Settings:
        value = copy.deepcopy(DEFAULT)
    field = TextField()
    history = History(tmp_path / "history.db")
    runner = Engine(Settings(), history, field, None, lambda message: None)
    monkeypatch.setattr(engine_module, "same_target", lambda target: True)
    monkeypatch.setattr(engine_module, "target_exists", lambda target: True)
    monkeypatch.setattr(field, "input_tick", lambda: 123)
    return runner, field, history


def test_original_is_durable_before_provider_and_result_before_write(runner, monkeypatch):
    engine, field, history = runner
    def provider(*args):
        assert history.entries()[0]["original"] == "helo"
        return "hello"
    monkeypatch.setattr(engine_module.providers, "transform", provider)
    assert engine.edit("english_formal", {"process": "test.exe"})
    assert field.writes == ["hello"]
    assert history.entries()[0]["status"] == "applied"


def test_input_elsewhere_does_not_block_unchanged_original_field(runner, monkeypatch):
    engine, field, history = runner
    def provider(*args):
        monkeypatch.setattr(field, "input_tick", lambda: 124)
        return "hello"
    monkeypatch.setattr(engine_module.providers, "transform", provider)
    assert engine.edit("english_formal", {"process": "test.exe"})
    assert field.writes == ["hello"]
    assert history.entries()[0]["result"] == "hello"
    assert history.entries()[0]["status"] == "applied"


def test_foreground_change_allows_addressed_write_to_original_field(runner, monkeypatch):
    engine, field, history = runner
    def provider(*args):
        engine.invalidated.set()
        monkeypatch.setattr(engine_module, "same_target", lambda target: False)
        return "hello"
    monkeypatch.setattr(engine_module.providers, "transform", provider)
    assert engine.edit("english_formal", {"process": "test.exe"})
    assert field.writes == ["hello"]


def test_changed_original_retains_result_without_overwriting(runner, monkeypatch):
    engine, field, history = runner
    def provider(*args):
        field.snapshot["full"] = "new draft"
        return "hello"
    monkeypatch.setattr(engine_module.providers, "transform", provider)
    with pytest.raises(RuntimeError, match="original field changed"):
        engine.edit("english_formal", {"process": "test.exe"})
    assert not field.writes
    assert history.entries()[0]["result"] == "hello"


def test_clipboard_only_editor_waits_for_return_without_repeating_provider(runner, monkeypatch):
    engine, field, history = runner
    calls = []
    apply = field.apply
    def deferred_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {"deferred": True}
        return apply(*args, **kwargs)
    provider_calls = []
    def provider(*args):
        provider_calls.append(1)
        return "hello"
    monkeypatch.setattr(field, "apply", deferred_once)
    monkeypatch.setattr(engine_module.providers, "transform", provider)
    assert engine.edit("english_formal", {"process": "test.exe"})
    assert field.writes == ["hello"]
    assert len(provider_calls) == 1
    assert history.entries()[0]["status"] == "applied"


def test_pending_insertion_can_be_cancelled_with_result_retained(runner, monkeypatch):
    engine, field, history = runner
    def defer(*args, **kwargs):
        engine.cancel.set()
        return {"deferred": True}
    monkeypatch.setattr(field, "apply", defer)
    monkeypatch.setattr(engine_module.providers, "transform", lambda *args: "hello")
    with pytest.raises(engine_module.providers.Cancelled):
        engine.edit("english_formal", {"process": "test.exe"})
    assert not field.writes
    assert history.entries()[0]["status"] == "cancelled"
    assert history.entries()[0]["result"] == "hello"
    assert not engine.waiting_for_editor


def test_pending_insertion_stops_when_original_window_closes(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(field, "apply", lambda *args, **kwargs: {"deferred": True})
    monkeypatch.setattr(engine_module.providers, "transform", lambda *args: "hello")
    monkeypatch.setattr(engine_module, "target_exists", lambda target: False)
    with pytest.raises(RuntimeError, match="original window closed"):
        engine.edit("english_formal", {"process": "test.exe"})
    assert not field.writes
    assert not engine.waiting_for_editor
    assert history.entries()[0]["result"] == "hello"


def test_unchanged_text_is_reported_without_pasting(runner, monkeypatch):
    engine, field, history = runner
    messages = []
    engine.progress = messages.append
    monkeypatch.setattr(engine_module.providers, "transform", lambda *args: "helo")
    assert engine.edit("english_formal", {"process": "test.exe"})
    assert not field.writes
    assert history.entries()[0]["status"] == "unchanged"
    assert "No changes needed" in messages[-1]


def test_macro_stops_on_first_error_and_records_completed_steps(runner, monkeypatch):
    engine, field, history = runner
    engine.config.value["macros"] = [{"id": "test", "name": "Test", "steps": [{"type": "delay", "value": 0}, {"type": "keys", "value": "Ctrl+A"}, {"type": "text", "value": "must not run"}]}]
    def fail(*args):
        raise RuntimeError("Test refusal")
    monkeypatch.setattr(engine_module, "send_keys", fail)
    with pytest.raises(RuntimeError, match="Test refusal"):
        engine.macro("test", {"process": "test.exe"})
    assert not field.writes
    assert history.entries()[0]["steps"] == [{"index": 1, "type": "delay"}]


def test_capture_failure_clears_edit_target(runner, monkeypatch):
    engine, field, history = runner
    def fail(target):
        raise RuntimeError("The editor helper stopped")
    monkeypatch.setattr(field, "capture", fail)
    with pytest.raises(RuntimeError, match="helper stopped"):
        engine.edit("english_formal", {"process": "test.exe"})
    assert engine.edit_target is None
    assert not field.writes


def test_failed_write_keeps_result_and_nonempty_error_without_retry(runner, monkeypatch):
    engine, field, history = runner
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        raise EOFError()
    monkeypatch.setattr(field, "apply", fail)
    monkeypatch.setattr(engine_module.providers, "transform", lambda *args: "hello")
    with pytest.raises(EOFError):
        engine.edit("english_formal", {"process": "test.exe"})
    entry = history.entries()[0]
    assert entry["status"] == "failed"
    assert entry["result"] == "hello"
    assert entry["original"] == "helo"
    assert entry["error"] == "EOFError"
    assert len(calls) == 1
    assert engine.edit_target is None


def no_apply(*args, **kwargs):
    pytest.fail("read_selection must never apply")


def test_read_selection_uses_the_adapter_without_copy(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(engine, "apply", no_apply)
    assert engine.read_selection({"process": "test.exe"}) == {"kind": "selection", "format": "plain", "text": "helo", "image": None, "origin": "test.exe"}
    assert field.copies == [] and field.writes == []
    assert engine.edit_target is None
    assert history.entries() == []


def test_read_selection_copies_when_the_adapter_refuses(runner, monkeypatch):
    engine, field, history = runner
    def refuse(target):
        raise RuntimeError("This field is read-only or protected")
    monkeypatch.setattr(field, "capture", refuse)
    monkeypatch.setattr(engine, "apply", no_apply)
    assert engine.read_selection({"process": "test.exe"})["text"] == "# copied"
    assert field.copies == [{"process": "test.exe"}]
    assert field.writes == [] and engine.edit_target is None


def test_read_selection_does_not_copy_after_the_target_changed(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(engine_module, "same_target", lambda target: False)
    with pytest.raises(RuntimeError, match="no longer active"):
        engine.read_selection({"process": "test.exe"})
    assert field.copies == [] and engine.edit_target is None


def test_read_selection_refuses_a_terminal_before_capture(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(field, "capture", lambda target: pytest.fail("capture must not run"))
    with pytest.raises(RuntimeError, match="Terminal text"):
        engine.read_selection({"process": "powershell.exe"})
    assert field.copies == []


def test_read_selection_strips_gmail_markers(runner, monkeypatch):
    engine, field, history = runner
    engine.browser = SimpleNamespace(supports=lambda target: True, capture=lambda target: {"kind": "browser", "rich": True, "text": "<t0>Fish &amp; chips</t0><o1/> &lt;3"},
                                     apply=no_apply)
    monkeypatch.setattr(engine, "apply", no_apply)
    def unavailable(target):
        raise RuntimeError("TextPattern unavailable")
    monkeypatch.setattr(field, "read_selection", unavailable)
    source = engine.read_selection({"process": "chrome.exe"})
    assert source == {"kind": "selection", "format": "plain", "text": "Fish & chips <3", "image": None, "origin": "chrome.exe"}
    assert engine.edit_target is None


def test_read_selection_uses_uia_in_browser_without_extension_or_clipboard(runner):
    engine, field, history = runner
    engine.browser = SimpleNamespace(supports=lambda target: True, capture=lambda target: pytest.fail("Extension must not be used"))
    assert engine.read_selection({"process": "chrome.exe"})["text"] == "helo"
    assert not field.copies and not field.writes and history.entries() == []


def test_protected_uia_read_cannot_fall_back_to_extension_or_clipboard(runner, monkeypatch):
    engine, field, history = runner
    def protected(target):
        raise engine_module.TextAccessDenied("Password fields cannot be read")
    monkeypatch.setattr(field, "read_selection", protected)
    with pytest.raises(engine_module.TextAccessDenied, match="Password"):
        engine.read_selection({"process": "chrome.exe"})
    assert not field.copies and history.entries() == []


def test_explicit_uia_edit_uses_verified_write_and_preserves_history(runner, monkeypatch):
    engine, field, history = runner
    engine.browser = SimpleNamespace(supports=lambda target: True, capture=lambda target: pytest.fail("Extension must not be used"))
    monkeypatch.setattr(engine_module.providers, "transform", lambda *args: "hello")
    assert engine.edit_via("english_formal", {"process": "chrome.exe"}, "uia")
    assert field.writes == ["hello"] and not field.copies and not field.pastes
    entry = history.entries()[0]
    assert entry["via"] == "uia" and entry["status"] == "applied"
    assert entry["snapshot"]["foregroundOnly"]


def test_default_browser_edit_still_requires_formatted_adapter(runner, monkeypatch):
    engine, field, history = runner
    def disconnected(target):
        raise RuntimeError("Choose UIA plain text")
    engine.browser = SimpleNamespace(supports=lambda target: True, capture=disconnected)
    with pytest.raises(RuntimeError, match="Choose UIA"):
        engine.edit("native", {"process": "chrome.exe"})
    assert not field.writes and not field.copies and history.entries() == []


def test_edit_via_clipboard_writes_the_result_to_the_clipboard(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(engine_module.providers, "transform", lambda config, action, text, cancel: text.replace("helo", "hello"))
    monkeypatch.setattr(engine, "apply", no_apply)
    assert engine.edit_via("english_formal", {}, "clipboard")
    assert field.clipboard == "hello clip" and field.pastes == [] and field.copies == []
    entry = history.entries()[0]
    assert (entry["status"], entry["via"], entry["source"], entry["original"], entry["result"]) == ("copied", "clipboard", "Clipboard", "helo clip", "hello clip")


def test_edit_via_app_copies_and_pastes_with_the_input_tick(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(engine_module.providers, "transform", lambda config, action, text, cancel: text.replace("helo", "hello"))
    assert engine.edit_via("native", {"process": "notepad++.exe"}, "app")
    assert field.copies == [{"process": "notepad++.exe"}]
    assert field.pastes == [("notepad++.exe", "hello app", 123)]
    assert field.clipboard == "helo clip"
    assert history.entries()[0]["status"] == "pasted"


def test_edit_via_app_leaves_the_result_in_the_clipboard_when_paste_is_refused(runner, monkeypatch):
    engine, field, history = runner
    messages = []
    engine.progress = messages.append
    monkeypatch.setattr(engine_module.providers, "transform", lambda config, action, text, cancel: "hello app")
    def refuse(target, text, tick):
        raise RuntimeError("You used the keyboard or mouse in the meantime")
    monkeypatch.setattr(field, "paste", refuse)
    assert engine.edit_via("english_social", {"process": "chrome.exe"}, "app")
    assert field.clipboard == "hello app"
    entry = history.entries()[0]
    assert entry["status"] == "copied" and "keyboard or mouse" in entry["error"]
    assert messages[-1] == "You used the keyboard or mouse in the meantime, so the text was not pasted. The result is in the clipboard; paste it with Ctrl+V."


def test_edit_via_unchanged_text_writes_nothing(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(engine_module.providers, "transform", lambda config, action, text, cancel: text)
    assert engine.edit_via("english_formal", {"process": "notepad.exe"}, "app")
    assert field.pastes == [] and field.clipboard == "helo clip"
    assert history.entries()[0]["status"] == "unchanged"


def test_edit_via_app_refuses_a_changed_window_before_copy(runner, monkeypatch):
    engine, field, history = runner
    monkeypatch.setattr(engine_module, "same_target", lambda target: False)
    with pytest.raises(RuntimeError, match="no longer active"):
        engine.edit_via("english_formal", {"process": "notepad.exe"}, "app")
    assert field.copies == [] and history.entries() == []
