import importlib.util
from pathlib import Path
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package_release = load("package_release")
check_release_version = load("check_release_version")


def tree(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


class TestZip:
    def test_one_top_folder_and_forward_slashes(self, tmp_path):
        source = tree(tmp_path / "dist", {
            "DesktopAiAssistant.exe": b"app", "DesktopAiHost.exe": b"host",
            "_internal/desktop_ai_assistant/qml/Settings.qml": b"qml",
        })
        archive = tmp_path / "out.zip"
        longest = package_release.PackageRelease.zip(source, archive)
        with zipfile.ZipFile(archive) as package:
            names = sorted(package.namelist())
        assert names == [
            "DesktopAiAssistant/DesktopAiAssistant.exe", "DesktopAiAssistant/DesktopAiHost.exe",
            "DesktopAiAssistant/_internal/desktop_ai_assistant/qml/Settings.qml",
        ]
        assert longest == len("_internal/desktop_ai_assistant/qml/Settings.qml")

    def test_svn_metadata_is_refused(self, tmp_path):
        source = tree(tmp_path / "dist", {"DesktopAiAssistant.exe": b"app", "_internal/pkg/.svn/wc.db": b"db"})
        with pytest.raises(SystemExit, match="SVN metadata"):
            package_release.PackageRelease.zip(source, tmp_path / "out.zip")

    def test_a_missing_compiler_names_the_ways_out(self, monkeypatch, tmp_path):
        for variable in ("ISCC", "ProgramFiles(x86)", "ProgramFiles"):
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setattr(package_release.shutil, "which", lambda name: None)
        with pytest.raises(SystemExit, match="--zip-only"):
            package_release.PackageRelease.iscc()

    def test_the_compiler_variable_wins(self, monkeypatch, tmp_path):
        compiler = tree(tmp_path, {"ISCC.exe": b""}) / "ISCC.exe"
        monkeypatch.setenv("ISCC", str(compiler))
        assert package_release.PackageRelease.iscc() == compiler


class TestReleaseVersion:
    check = staticmethod(check_release_version.ReleaseVersion.check)

    def test_a_matching_tag_passes(self):
        assert self.check("0.4.0", "tag", "v0.4.0") is None

    def test_a_different_tag_fails(self):
        assert "does not match" in self.check("0.4.0", "tag", "v0.4.1")

    def test_a_tag_without_v_fails(self):
        assert "does not start with 'v'" in self.check("0.4.0", "tag", "0.4.0")

    def test_without_a_tag_only_the_form_is_checked(self):
        assert self.check("0.4.0", "branch", "main") is None
        assert "not MAJOR.MINOR.PATCH" in self.check("0.4", "branch", "main")
