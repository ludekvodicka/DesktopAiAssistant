import hashlib
import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPResponse
from pathlib import Path

from .const import UpdateConst
from .errors import UpdateError, UpdateHttpError, UpdateIntegrityError


class UpdateTransport:
    """HTTPS access through urllib; redirects are followed, every body has a size cap."""

    _user_agent: str
    _context: ssl.SSLContext | None

    def __init__(self, user_agent: str, context: ssl.SSLContext | None = None) -> None:
        self._user_agent = user_agent
        self._context = context

    def get_json(self, url: str) -> dict[str, object]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        with self._open(url, headers) as response:
            body = UpdateTransport._read_capped(response, UpdateConst.json_limit_bytes, url)
        try:
            data = json.loads(body)
        except ValueError as error:
            raise UpdateError(f"The update server sent unreadable data: {error}") from error
        if not isinstance(data, dict):
            raise UpdateError("The update server sent unexpected data.")
        return data

    def get_text(self, url: str, limit: int) -> str:
        with self._open(url, {"Accept": "application/octet-stream"}) as response:
            return UpdateTransport._read_capped(response, limit, url).decode("utf-8", "replace")

    def download(self, url: str, destination: Path, size: int, progress: Callable[[int], None],
                 cancelled: Callable[[], bool]) -> str:
        digest = hashlib.sha256()
        transferred = 0
        try:
            with self._open(url, {"Accept": "application/octet-stream"}) as response, \
                    destination.open("wb") as output:
                announced = response.getheader("Content-Length")
                if announced is not None and announced.isdigit() and int(announced) > size:
                    raise UpdateIntegrityError(f"{destination.name} is larger than announced.")
                while chunk := response.read(UpdateConst.chunk_bytes):
                    if cancelled():
                        raise UpdateError("The download was cancelled.")
                    transferred += len(chunk)
                    if transferred > size:
                        raise UpdateIntegrityError(f"{destination.name} is larger than announced.")
                    digest.update(chunk)
                    output.write(chunk)
                    progress(transferred)
            if transferred != size:
                raise UpdateIntegrityError(f"The download of {destination.name} ended early.")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return digest.hexdigest()

    def _open(self, url: str, headers: dict[str, str]) -> HTTPResponse:
        request = urllib.request.Request(url, headers={**headers, "User-Agent": self._user_agent})
        try:
            return urllib.request.urlopen(
                request, timeout=UpdateConst.request_timeout_seconds, context=self._context)
        except urllib.error.HTTPError as error:
            error.close()
            raise UpdateHttpError(error.code, url) from None

    @staticmethod
    def _read_capped(response: HTTPResponse, limit: int, url: str) -> bytes:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise UpdateIntegrityError(f"The response from {url} is larger than expected.")
        return body
