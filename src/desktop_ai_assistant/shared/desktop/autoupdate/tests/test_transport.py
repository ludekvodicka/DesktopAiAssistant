import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ..errors import UpdateError, UpdateHttpError, UpdateIntegrityError
from ..transport import UpdateTransport

PAYLOAD = bytes(range(256)) * 1200


class Handler(BaseHTTPRequestHandler):
    seen: list[dict[str, str]] = []

    def do_GET(self) -> None:
        Handler.seen.append(dict(self.headers))
        match self.path:
            case "/json":
                self._send(200, json.dumps({"tag_name": "v1.0.0"}).encode())
            case "/list":
                self._send(200, b"[1, 2]")
            case "/redirect":
                self.send_response(302)
                self.send_header("Location", "/file")
                self.end_headers()
            case "/file":
                self._send(200, PAYLOAD)
            case "/text":
                self._send(200, b"line one\n")
            case "/missing":
                self._send(404, b"{}")
            case "/forbidden":
                self._send(403, b"{}")
            case _:
                self._send(500, b"")

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:
        pass


@pytest.fixture(scope="module")
def loopback():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def server(loopback, monkeypatch):
    # A proxy from the environment or the registry must not intercept the loopback server.
    monkeypatch.setenv("NO_PROXY", "*")
    Handler.seen = []
    return loopback


@pytest.fixture
def transport():
    return UpdateTransport("DemoApp/1.0.0")


def test_get_json_sends_the_github_headers(server, transport):
    assert transport.get_json(f"{server}/json") == {"tag_name": "v1.0.0"}
    headers = {key.lower(): value for key, value in Handler.seen[-1].items()}
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2022-11-28"
    assert headers["user-agent"] == "DemoApp/1.0.0"


def test_get_json_refuses_a_non_object(server, transport):
    with pytest.raises(UpdateError, match="unexpected data"):
        transport.get_json(f"{server}/list")


@pytest.mark.parametrize(("path", "status"), [("/missing", 404), ("/forbidden", 403)])
def test_http_errors_carry_their_status(server, transport, path, status):
    with pytest.raises(UpdateHttpError) as caught:
        transport.get_json(f"{server}{path}")
    assert caught.value.status == status
    assert str(caught.value) == f"The update server answered HTTP {status}."


def test_get_text_and_its_cap(server, transport):
    assert transport.get_text(f"{server}/text", 100) == "line one\n"
    with pytest.raises(UpdateIntegrityError):
        transport.get_text(f"{server}/text", 4)


def test_download_follows_redirects_and_hashes(server, transport, tmp_path):
    destination = tmp_path / "demo.bin.part"
    seen: list[int] = []
    digest = transport.download(f"{server}/redirect", destination, len(PAYLOAD), seen.append,
                                lambda: False)
    assert digest == hashlib.sha256(PAYLOAD).hexdigest()
    assert destination.read_bytes() == PAYLOAD
    assert seen[-1] == len(PAYLOAD)


def test_download_larger_than_announced_raises_and_removes_the_file(server, transport, tmp_path):
    destination = tmp_path / "demo.bin.part"
    with pytest.raises(UpdateIntegrityError, match="larger than announced"):
        transport.download(f"{server}/file", destination, 1000, lambda _n: None, lambda: False)
    assert not destination.exists()


def test_download_shorter_than_announced_raises(server, transport, tmp_path):
    destination = tmp_path / "demo.bin.part"
    with pytest.raises(UpdateIntegrityError, match="ended early"):
        transport.download(f"{server}/file", destination, len(PAYLOAD) + 1, lambda _n: None,
                           lambda: False)
    assert not destination.exists()


def test_cancelled_download_raises_and_removes_the_file(server, transport, tmp_path):
    destination = tmp_path / "demo.bin.part"
    with pytest.raises(UpdateError, match="cancelled"):
        transport.download(f"{server}/file", destination, len(PAYLOAD), lambda _n: None,
                           lambda: True)
    assert not destination.exists()


def test_download_http_error(server, transport, tmp_path):
    with pytest.raises(UpdateHttpError):
        transport.download(f"{server}/missing", tmp_path / "x.part", 10, lambda _n: None,
                           lambda: False)
