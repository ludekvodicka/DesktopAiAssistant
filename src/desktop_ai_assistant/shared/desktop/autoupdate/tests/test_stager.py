import hashlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from ..errors import UpdateIntegrityError
from ..feed import UpdateCandidate, UpdateFeedGithub
from ..runtime import UpdateTargetFile, UpdateTargetFolder
from ..stager import UpdateStager
from .support import (
    FILE_PATTERN,
    LATEST,
    OWNER,
    REPO,
    ZIP_PATTERN,
    FakeTransport,
    file_urls,
    release_json,
    with_sums,
    zip_bytes,
)

VERSION = "1.2.0"
FILE_NAME = FILE_PATTERN.format(version=VERSION)
ZIP_NAME = ZIP_PATTERN.format(version=VERSION)
GOOD_TREE = {
    "DemoApp/DemoApp.exe": b"app",
    "DemoApp/DemoHelper.exe": b"helper",
    "DemoApp/lib/data.bin": b"data",
}


def published(files: dict[str, bytes], sums: dict[str, bytes] | None = None):
    files_with_sums = with_sums(files) if sums is None else {**files, **sums}
    transport = FakeTransport({LATEST: release_json(VERSION, files_with_sums)},
                              file_urls(VERSION, files_with_sums))
    candidate = UpdateFeedGithub(OWNER, REPO, transport).latest()
    assert isinstance(candidate, UpdateCandidate)
    return transport, candidate


def file_target(tmp_path: Path) -> UpdateTargetFile:
    program = tmp_path / "app" / "Demo-App.exe"
    program.parent.mkdir()
    program.write_bytes(b"old build")
    return UpdateTargetFile(program, FILE_PATTERN, onefile_parent=True)


def folder_target(tmp_path: Path) -> UpdateTargetFolder:
    program = tmp_path / "Programs" / "DemoApp"
    program.mkdir(parents=True)
    (program / "DemoApp.exe").write_bytes(b"old app")
    return UpdateTargetFolder(program, ZIP_PATTERN, "DemoApp", "DemoApp.exe", "DemoHelper.exe")


def stage(stager, candidate, name, target):
    asset = candidate.asset(name)
    assert asset is not None
    return stager.stage(candidate, asset, target, lambda _n: None, lambda: False)


def test_file_match_renames_the_part(tmp_path):
    transport, candidate = published({FILE_NAME: b"new build"})
    root = tmp_path / "updates"
    staged = stage(UpdateStager(transport, root), candidate, FILE_NAME, file_target(tmp_path))
    assert staged.version == VERSION
    assert staged.source == root / VERSION / FILE_NAME
    assert staged.source.read_bytes() == b"new build"
    assert not (root / VERSION / (FILE_NAME + ".part")).exists()


def test_file_mismatch_removes_the_part_and_raises(tmp_path):
    bad_sum = f"{hashlib.sha256(b'other').hexdigest()}  {FILE_NAME}\n".encode()
    transport, candidate = published({FILE_NAME: b"new build"}, {"SHA256SUMS.txt": bad_sum})
    root = tmp_path / "updates"
    with pytest.raises(UpdateIntegrityError, match="does not match SHA256SUMS.txt"):
        stage(UpdateStager(transport, root), candidate, FILE_NAME, file_target(tmp_path))
    assert list((root / VERSION).iterdir()) == []


def test_name_missing_from_the_sums_raises(tmp_path):
    other = f"{hashlib.sha256(b'x').hexdigest()}  other.exe\n".encode()
    transport, candidate = published({FILE_NAME: b"new build"}, {"SHA256SUMS.txt": other})
    with pytest.raises(UpdateIntegrityError, match="no entry"):
        stage(UpdateStager(transport, tmp_path / "u"), candidate, FILE_NAME, file_target(tmp_path))


def test_file_oversize_raises(tmp_path):
    transport, candidate = published({FILE_NAME: b"new build"})
    transport.files[candidate.asset(FILE_NAME).url] = b"new build plus more"
    with pytest.raises(UpdateIntegrityError, match="larger than announced"):
        stage(UpdateStager(transport, tmp_path / "u"), candidate, FILE_NAME, file_target(tmp_path))


def test_verified_copy_is_reused_without_download(tmp_path):
    transport, candidate = published({FILE_NAME: b"new build"})
    root = tmp_path / "updates"
    stager = UpdateStager(transport, root)
    target = file_target(tmp_path)
    stage(stager, candidate, FILE_NAME, target)
    asset_url = candidate.asset(FILE_NAME).url
    transport.calls.clear()
    staged = stage(stager, candidate, FILE_NAME, target)
    assert staged.source.read_bytes() == b"new build"
    assert asset_url not in transport.calls


def test_other_staged_versions_are_pruned(tmp_path):
    transport, candidate = published({FILE_NAME: b"new build"})
    root = tmp_path / "updates"
    (root / "1.1.0").mkdir(parents=True)
    (root / "helper").mkdir()
    stage(UpdateStager(transport, root), candidate, FILE_NAME, file_target(tmp_path))
    assert sorted(entry.name for entry in root.iterdir()) == [VERSION, "helper"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_staged_file_is_executable_on_posix(tmp_path):
    transport, candidate = published({FILE_NAME: b"new build"})
    staged = stage(UpdateStager(transport, tmp_path / "u"), candidate, FILE_NAME,
                   file_target(tmp_path))
    assert stat.S_IMODE(staged.source.stat().st_mode) == 0o755


def test_valid_zip_is_staged_beside_the_program_folder(tmp_path):
    transport, candidate = published({ZIP_NAME: zip_bytes(GOOD_TREE)})
    root = tmp_path / "updates"
    target = folder_target(tmp_path)
    calls: list[tuple[Path, Path, bool]] = []
    staged_path = tmp_path / "Programs" / "DemoApp.staged"

    def prepare(staged: Path, installed: Path) -> None:
        calls.append((staged, installed, staged_path.exists()))
        (staged / "prepared.txt").write_text("yes")

    staged = stage(UpdateStager(transport, root, prepare), candidate, ZIP_NAME, target)
    assert staged.source == staged_path
    assert (staged_path / "DemoApp.exe").read_bytes() == b"app"
    assert (staged_path / "lib" / "data.bin").read_bytes() == b"data"
    assert (staged_path / "prepared.txt").read_text() == "yes"
    assert calls == [(tmp_path / "Programs" / "DemoApp.staged.part", target.path, False)]
    marker = json.loads((root / "staged.json").read_text("utf-8"))
    assert marker["version"] == VERSION
    assert not (root / VERSION / ZIP_NAME).exists()
    assert (target.path / "DemoApp.exe").read_bytes() == b"old app"


def test_marker_reuse_skips_the_download(tmp_path):
    transport, candidate = published({ZIP_NAME: zip_bytes(GOOD_TREE)})
    root = tmp_path / "updates"
    target = folder_target(tmp_path)
    stager = UpdateStager(transport, root)
    stage(stager, candidate, ZIP_NAME, target)
    transport.calls.clear()
    staged = stage(stager, candidate, ZIP_NAME, target)
    assert staged.source == tmp_path / "Programs" / "DemoApp.staged"
    assert candidate.asset(ZIP_NAME).url not in transport.calls


def backslash_zip() -> bytes:
    # zipfile turns backslashes into slashes when it writes on Windows, so they are patched in.
    data = zip_bytes({**GOOD_TREE, "DemoApp|..|escape.txt": b"x"})
    return data.replace(b"DemoApp|..|escape.txt", b"DemoApp\\..\\escape.txt")


def symlink_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("DemoApp/DemoApp.exe", b"app")
        package.writestr("DemoApp/DemoHelper.exe", b"helper")
        link = zipfile.ZipInfo("DemoApp/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        package.writestr(link, "/etc/passwd")
    return buffer.getvalue()


@pytest.mark.parametrize(("archive", "message"), [
    (zip_bytes({**GOOD_TREE, "DemoApp/../escape.txt": b"x"}), "Unexpected path"),
    (backslash_zip(), "Unexpected path"),
    (zip_bytes({**GOOD_TREE, "DemoApp/C:/x.txt": b"x"}), "Unexpected path"),
    (zip_bytes({**GOOD_TREE, "DemoApp//escape.txt": b"x"}), "Unexpected path"),
    (zip_bytes({**GOOD_TREE, "Second/readme.txt": b"x"}), "Unexpected path"),
    (symlink_zip(), "Links are not allowed"),
    (zip_bytes({"DemoApp/DemoHelper.exe": b"helper"}), "no DemoApp.exe"),
    (zip_bytes({"DemoApp/DemoApp.exe": b"app"}), "no DemoHelper.exe"),
])
def test_bad_packages_raise_and_leave_nothing_staged(tmp_path, archive, message):
    transport, candidate = published({ZIP_NAME: archive})
    root = tmp_path / "updates"
    calls: list[Path] = []
    with pytest.raises(UpdateIntegrityError, match=message):
        stage(UpdateStager(transport, root, lambda staged, _installed: calls.append(staged)),
              candidate, ZIP_NAME, folder_target(tmp_path))
    assert calls == []
    assert sorted(path.name for path in (tmp_path / "Programs").iterdir()) == ["DemoApp"]
    assert not (tmp_path / "escape.txt").exists()
    assert not (root / "staged.json").exists()
