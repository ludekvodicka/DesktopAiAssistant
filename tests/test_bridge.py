import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import pytest
from desktop_ai_assistant.bridge import BrowserBridge, BrowserRequestError


@pytest.mark.parametrize("registration", ["legacy", "automatic"])
def test_native_host_pipe_roundtrip(tmp_path, monkeypatch, registration):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    extension = "a" * 32
    if registration == "legacy":
        (tmp_path / "extension.json").write_text(json.dumps({"id": extension}), "utf-8")
    elif registration == "automatic":
        (tmp_path / "native-host.json").write_text(json.dumps({"allowed_origins": [f"chrome-extension://{extension}/"]}), "utf-8")
    else:
        raise ValueError(registration)
    bridge = BrowserBridge()
    args = [os.environ["DESKTOP_AI_HOST_EXE"]] if os.environ.get("DESKTOP_AI_HOST_EXE") else [sys.executable, "-m", "desktop_ai_assistant", "--native-host"]
    host = subprocess.Popen(args + [f"chrome-extension://{extension}/"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    errors = []
    def respond():
        try:
            size = struct.unpack("<I", host.stdout.read(4))[0]
            request = json.loads(host.stdout.read(size))
            assert request["op"] == "hello"
            assert request["version"]
            size = struct.unpack("<I", host.stdout.read(4))[0]
            request = json.loads(host.stdout.read(size))
            assert request["op"] == "capture"
            payload = json.dumps({"id": request["id"], "ok": True, "value": {"text": "synthetic"}}).encode()
            host.stdin.write(struct.pack("<I", len(payload)) + payload)
            host.stdin.flush()
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=respond, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not bridge.clients and time.monotonic() < deadline:
            time.sleep(0.02)
        assert bridge.clients, "Native host did not connect"
        result = bridge.request(next(iter(bridge.clients)), "capture")
        assert result == {"text": "synthetic"}
        assert not errors
    finally:
        host.stdin.close()
        try:
            host.wait(3)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait()
        bridge.close()


def test_capture_reports_disconnection_and_preserves_editor_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    bridge = BrowserBridge()
    try:
        with pytest.raises(RuntimeError, match="extension is disconnected"):
            bridge.capture({})
        bridge.clients = {"inactive": None, "active": None}
        def request(client, operation):
            if client == "inactive":
                raise BrowserRequestError("Other window is inactive", "browser_not_focused")
            raise BrowserRequestError("Focus the Gmail subject or message body", "editor_error")
        monkeypatch.setattr(bridge, "request", request)
        with pytest.raises(RuntimeError, match="Gmail subject or message body"):
            bridge.capture({})
    finally:
        bridge.clients.clear()
        bridge.close()
