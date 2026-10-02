from dataclasses import dataclass

from .const import UpdateConst
from .errors import UpdateError, UpdateHttpError
from .release_notes import UpdateReleaseNotes
from .status import UpdateRelease
from .transport import UpdateTransport
from .version import UpdateVersion


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class UpdateCandidate:
    release: UpdateRelease
    # Only assets served from the repository's own release download path.
    assets: tuple[UpdateAsset, ...]

    def asset(self, name: str) -> UpdateAsset | None:
        return next((asset for asset in self.assets if asset.name == name), None)


class UpdateFeedGithub:
    _latest_url: str
    _download_prefix: str
    _transport: UpdateTransport

    def __init__(self, owner: str, repo: str, transport: UpdateTransport) -> None:
        self._latest_url = f"{UpdateConst.api_root}/repos/{owner}/{repo}/releases/latest"
        self._download_prefix = f"https://github.com/{owner}/{repo}/releases/download/".lower()
        self._transport = transport

    def latest(self) -> UpdateCandidate | None:
        """None when the repository has no published release or its tag is not X.Y.Z."""
        try:
            data = self._transport.get_json(self._latest_url)
        except UpdateHttpError as error:
            if error.status == 404:
                return None
            raise
        tag = data.get("tag_name")
        if not isinstance(tag, str):
            raise UpdateError("The latest release has no tag.")
        if UpdateVersion.parse(tag) is None:
            return None
        release = UpdateRelease(
            version=tag.strip().removeprefix("v"),
            name=UpdateFeedGithub._text(data.get("name")),
            date=UpdateFeedGithub._text(data.get("published_at")),
            notes=UpdateReleaseNotes.to_text(UpdateFeedGithub._text(data.get("body"))),
        )
        raw_assets = data.get("assets")
        entries = raw_assets if isinstance(raw_assets, list) else []
        assets = tuple(asset for asset in map(self._asset, entries) if asset is not None)
        return UpdateCandidate(release, assets)

    def _asset(self, entry: object) -> UpdateAsset | None:
        if not isinstance(entry, dict):
            return None
        name, url, size = entry.get("name"), entry.get("browser_download_url"), entry.get("size")
        if not isinstance(name, str) or not isinstance(url, str):
            return None
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return None
        if not url.lower().startswith(self._download_prefix):
            return None
        return UpdateAsset(name, url, size)

    @staticmethod
    def _text(value: object) -> str | None:
        return value if isinstance(value, str) and value else None
