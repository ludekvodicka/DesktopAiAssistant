import pytest

from ..errors import UpdateError, UpdateHttpError
from ..feed import UpdateAsset, UpdateFeedGithub
from ..status import UpdateRelease
from .support import DOWNLOAD, LATEST, OWNER, REPO, FakeTransport, release_json, with_sums

FILES = with_sums({"Demo-App-1.2.0-x64.exe": b"new build"})


def feed(answer: object) -> UpdateFeedGithub:
    return UpdateFeedGithub(OWNER, REPO, FakeTransport({LATEST: answer}, {}))


def test_release_and_assets_are_parsed():
    candidate = feed(release_json("1.2.0", FILES, body="## Fixes\n- **Export** works")).latest()
    assert candidate is not None
    assert candidate.release == UpdateRelease(
        "1.2.0", "Demo 1.2.0", "2026-01-02T03:04:05Z", "Fixes\n- Export works")
    assert candidate.asset("Demo-App-1.2.0-x64.exe") == UpdateAsset(
        "Demo-App-1.2.0-x64.exe", f"{DOWNLOAD}/v1.2.0/Demo-App-1.2.0-x64.exe", 9)
    assert candidate.asset("SHA256SUMS.txt") is not None
    assert candidate.asset("other.bin") is None


def test_missing_optional_fields_become_none():
    candidate = feed({"tag_name": "1.2.0"}).latest()
    assert candidate is not None
    assert candidate.release == UpdateRelease("1.2.0", None, None, None)
    assert candidate.assets == ()


def test_missing_tag_raises():
    with pytest.raises(UpdateError, match="no tag"):
        feed({"name": "Demo"}).latest()


@pytest.mark.parametrize("tag", ["nightly", "v1.2.0-beta", "1.2"])
def test_tag_that_is_not_a_plain_version_is_no_update(tag):
    assert feed({"tag_name": tag}).latest() is None


def test_foreign_and_malformed_assets_are_dropped():
    data = release_json("1.2.0", FILES)
    data["assets"] += [
        {"name": "evil.exe", "size": 3,
         "browser_download_url": "https://example.com/example-owner/demo-app/evil.exe"},
        {"name": "other.exe", "size": 3,
         "browser_download_url": "https://github.com/other-owner/demo-app/releases/download/v1/o"},
        {"name": "nosize.exe", "browser_download_url": f"{DOWNLOAD}/v1.2.0/nosize.exe"},
        {"name": "bool.exe", "size": True, "browser_download_url": f"{DOWNLOAD}/v1.2.0/b.exe"},
        "not an object",
    ]
    candidate = feed(data).latest()
    assert candidate is not None
    assert [asset.name for asset in candidate.assets] == ["Demo-App-1.2.0-x64.exe",
                                                          "SHA256SUMS.txt"]


def test_owner_case_differences_are_accepted():
    data = release_json("1.2.0", FILES)
    for asset in data["assets"]:
        url = asset["browser_download_url"]
        asset["browser_download_url"] = url.replace(OWNER, "Example-Owner")
    candidate = feed(data).latest()
    assert candidate is not None
    assert len(candidate.assets) == 2


def test_no_published_release_is_no_update():
    assert feed(UpdateHttpError(404, LATEST)).latest() is None


def test_rate_limit_raises():
    with pytest.raises(UpdateHttpError) as caught:
        feed(UpdateHttpError(403, LATEST)).latest()
    assert caught.value.status == 403
