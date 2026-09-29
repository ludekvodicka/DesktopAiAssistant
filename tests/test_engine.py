import copy
import pytest
from desktop_ai_assistant.engine import Engine
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.history import History
from desktop_ai_assistant import engine as engine_module


class TextField:
    snapshot: dict
    writes: list

    def __init__(self):
        self.snapshot = {"kind": "windows", "target": {"process": "test.exe"}, "text": "helo", "full": "helo", "start": 0, "end": 4}
        self.writes = []

    def input_tick(self):
        return 123

    def capture(self, target):
        return copy.deepcopy(self.snapshot)

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
