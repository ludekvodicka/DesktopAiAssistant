import hashlib
import io
import itertools
import zipfile
from collections.abc import Callable
from pathlib import Path

from ..errors import UpdateIntegrityError
from ..transport import UpdateTransport

OWNER = "example-owner"
REPO = "demo-app"
LATEST = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
DOWNLOAD = f"https://github.com/{OWNER}/{REPO}/releases/download"
FILE_PATTERN = "Demo-App-{version}-x64.exe"
ZIP_PATTERN = "DemoApp-{version}-win-x64.zip"


class ManualHost:
    """UpdateHost for tests: time advances and background work runs only when the test says so."""

    def __init__(self) -> None:
        self.now = 0.0
        self.timers: list[tuple[float, int, Callable[[], None]]] = []
        self.jobs: list[tuple[Callable[[], object], Callable[[object], None],
                              Callable[[Exception], None]]] = []
        self._sequence = itertools.count()

    def call_later(self, seconds: float, callback: Callable[[], None]) -> Callable[[], None]:
        timer = (self.now + seconds, next(self._sequence), callback)
        self.timers.append(timer)

        def cancel() -> None:
            if timer in self.timers:
                self.timers.remove(timer)

        return cancel

    def run_in_background(self, work, on_done, on_error) -> None:
        self.jobs.append((work, on_done, on_error))

    def post(self, callback: Callable[[], None]) -> None:
        callback()

    def advance(self, seconds: float) -> None:
        end = self.now + seconds
        while due := [timer for timer in self.timers if timer[0] <= end]:
            timer = min(due)
            self.timers.remove(timer)
            self.now = timer[0]
            timer[2]()
        self.now = end

    def run_next(self) -> None:
        work, on_done, on_error = self.jobs.pop(0)
        try:
            result = work()
        except Exception as error:
            on_error(error)
            return
        on_done(result)

    def run_jobs(self) -> None:
        while self.jobs:
            self.run_next()

    def clock(self) -> float:
        return self.now


class FakeTransport(UpdateTransport):
    """The concrete transport without a network: answers come from tables keyed by URL."""

    def __init__(self, responses: dict[str, object], files: dict[str, bytes]) -> None:
        super().__init__("demo-tests/1.0")
        self.responses = responses
        self.files = files
        self.calls: list[str] = []

    def get_json(self, url: str) -> dict[str, object]:
        self.calls.append(url)
        answer = self.responses[url]
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, dict)
        return answer

    def get_text(self, url: str, limit: int) -> str:
        self.calls.append(url)
        data = self.files[url]
        if len(data) > limit:
            raise UpdateIntegrityError("too large")
        return data.decode("utf-8")

    def download(self, url, destination, size, progress, cancelled) -> str:
        self.calls.append(url)
        data = self.files[url]
        if len(data) > size:
            raise UpdateIntegrityError(f"{destination.name} is larger than announced.")
        destination.write_bytes(data)
        for transferred in range(0, len(data), 4):
            progress(min(transferred + 4, len(data)))
        return hashlib.sha256(data).hexdigest()


def with_sums(payloads: dict[str, bytes]) -> dict[str, bytes]:
    lines = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                    for name, data in payloads.items())
    return {**payloads, "SHA256SUMS.txt": lines.encode()}


def release_json(version: str, files: dict[str, bytes], body: str | None = "Fixes.") -> dict:
    return {
        "tag_name": f"v{version}",
        "name": f"Demo {version}",
        "published_at": "2026-01-02T03:04:05Z",
        "body": body,
        "assets": [
            {"name": name, "size": len(data),
             "browser_download_url": f"{DOWNLOAD}/v{version}/{name}"}
            for name, data in files.items()
        ],
    }


def file_urls(version: str, files: dict[str, bytes]) -> dict[str, bytes]:
    return {f"{DOWNLOAD}/v{version}/{name}": data for name, data in files.items()}


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, data in entries.items():
            package.writestr(name, data)
    return buffer.getvalue()


def write_tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root
