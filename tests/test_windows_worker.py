import multiprocessing as mp
import os
from types import SimpleNamespace
import pytest
from desktop_ai_assistant import windows_text


def crash_worker(connection, revision):
    connection.recv()
    os._exit(42)


def reply_worker(connection, revision):
    try:
        while True:
            request = connection.recv()
            if request["op"] == "close":
                return
            connection.send({"ok": True, "value": {"text": "synthetic result"}})
    finally:
        connection.close()


@pytest.mark.parametrize("operation,message", [("capture", "before text could be read"), ("apply", "may already have been inserted")])
def test_worker_crash_is_explained_and_next_action_gets_a_fresh_worker(monkeypatch, operation, message):
    monkeypatch.setattr(windows_text, "InputMonitor", lambda: SimpleNamespace(revision=mp.Value("q", 0), close=lambda: None))
    monkeypatch.setattr(windows_text, "_worker", crash_worker)
    adapter = windows_text.WindowsText()
    try:
        with pytest.raises(RuntimeError, match=message):
            adapter.call({"op": operation})
        assert adapter.process is None
        assert adapter.connection is None
        monkeypatch.setattr(windows_text, "_worker", reply_worker)
        assert adapter.call({"op": "capture"}) == {"text": "synthetic result"}
    finally:
        adapter.close()
