import sys
from pathlib import Path

import pytest

from ..helper import UpdateHelper
from ..verify import UpdateVerify

pytestmark = pytest.mark.skipif(sys.platform == "darwin", reason="no self-install on macOS")


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    monkeypatch.setattr(UpdateVerify, "holder_seconds", 0.5)
    monkeypatch.setattr(UpdateVerify, "blocked_swap_seconds", 0.6)


def built_helper(folder: Path, name: str, works: bool = True) -> Path:
    """A stand-in for a frozen build: a script that runs the helper from this source tree."""
    module = UpdateHelper.__module__
    top = Path(sys.modules[module].__file__ or "").resolve().parents[module.count(".")]
    folder.mkdir(parents=True, exist_ok=True)
    runner = folder / "runner.py"
    body = (f"sys.exit(importlib.import_module({module!r}).UpdateHelper.main(sys.argv[1:]))"
            if works else "sys.exit(0)")
    runner.write_text(f"import importlib, sys\nsys.path.insert(0, {str(top)!r})\n{body}\n")
    match sys.platform:
        case "win32":
            program = folder / f"{name}.cmd"
            program.write_text(f'@"{sys.executable}" "{runner}" %*\r\n')
        case "linux":
            program = folder / f"{name}.sh"
            program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{runner}" "$@"\n')
            program.chmod(0o755)
        case _:
            raise ValueError(f"Unsupported platform: {sys.platform}")
    return program


def test_file_build_is_verified(tmp_path, capsys):
    built = built_helper(tmp_path / "release", "Demo-App")
    assert UpdateVerify.main(["file", str(built), "--scratch", str(tmp_path / "scratch")]) == 0
    assert "UPDATE HELPER VERIFIED" in capsys.readouterr().out
    assert list((tmp_path / "scratch").iterdir()) == []


def test_folder_build_is_verified(tmp_path, capsys):
    build = tmp_path / "dist" / "DemoApp"
    build.mkdir(parents=True)
    (build / "DemoApp.exe").write_bytes(b"app")
    helper = built_helper(build, "DemoHelper")
    assert UpdateVerify.main(["folder", str(build), "--executable", "DemoApp.exe", "--helper",
                              helper.name, "--scratch", str(tmp_path / "scratch")]) == 0
    assert "UPDATE HELPER VERIFIED" in capsys.readouterr().out


def test_a_build_without_the_helper_fails(tmp_path, capsys):
    built = built_helper(tmp_path / "release", "Demo-App", works=False)
    assert UpdateVerify.main(["file", str(built), "--scratch", str(tmp_path / "scratch")]) == 1
    assert "wrote no result" in capsys.readouterr().err


def test_folder_without_its_programs_fails(tmp_path, capsys):
    build = tmp_path / "dist" / "DemoApp"
    build.mkdir(parents=True)
    assert UpdateVerify.main(["folder", str(build), "--executable", "DemoApp.exe", "--helper",
                              "DemoHelper.exe"]) == 1
    assert "has no DemoApp.exe" in capsys.readouterr().err
