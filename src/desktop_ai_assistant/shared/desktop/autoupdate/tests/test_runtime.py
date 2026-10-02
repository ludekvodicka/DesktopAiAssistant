from pathlib import Path

import pytest

from ..runtime import (
    UpdateResolution,
    UpdateRuntime,
    UpdateRuntimeFacts,
    UpdateTargetFile,
    UpdateTargetFolder,
)

FILE = UpdateTargetFile(Path("/opt/demo/Demo-App.bin"), "Demo-App-{version}.bin",
                        onefile_parent=False)
FOLDER = UpdateTargetFolder(Path("/opt/demo/DemoApp"), "DemoApp-{version}.zip", "DemoApp",
                            "DemoApp.exe", "DemoHelper.exe")


def writable(_folder: Path) -> bool:
    return True


def read_only(_folder: Path) -> bool:
    return False


def resolve(frozen, platform, target, probe=writable) -> UpdateResolution:
    return UpdateRuntime.resolve(UpdateRuntimeFacts(frozen, platform, target), probe)


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin", "freebsd"])
def test_source_run_is_off_everywhere(platform):
    resolution = resolve(False, platform, FILE)
    assert resolution == UpdateResolution(
        "off", "Development run: install a packaged release to get updates.")


def test_macos_without_target_notifies():
    assert resolve(True, "darwin", None) == UpdateResolution(
        "notify", "Unsigned macOS build: download new versions from the release page.")


def test_linux_without_target_notifies():
    assert resolve(True, "linux", None) == UpdateResolution(
        "notify", "Unpacked Linux build: download new versions from the release page.")


def test_windows_without_target_notifies():
    assert resolve(True, "win32", None) == UpdateResolution(
        "notify", "This build does not update itself: download new versions from the release page.")


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("target", [FILE, FOLDER])
def test_read_only_program_folder_notifies(platform, target):
    assert resolve(True, platform, target, read_only) == UpdateResolution(
        "notify",
        "The program folder is not writable: download new versions from the release page.")


@pytest.mark.parametrize("target", [FILE, FOLDER])
def test_windows_with_target_is_automatic(target):
    assert resolve(True, "win32", target) == UpdateResolution(
        "automatic", "Packaged Windows build.")


def test_linux_with_target_is_automatic():
    assert resolve(True, "linux", FILE) == UpdateResolution("automatic", "Packaged Linux build.")


def test_writability_is_probed_in_the_swap_folder():
    probed: list[Path] = []
    resolve(True, "win32", FOLDER, lambda folder: probed.append(folder) or True)
    assert probed == [Path("/opt/demo")]


def test_macos_target_raises():
    with pytest.raises(ValueError, match="macOS"):
        resolve(True, "darwin", FILE)


def test_unknown_platform_raises():
    with pytest.raises(ValueError, match="Unsupported update platform: freebsd"):
        resolve(True, "freebsd", None)


def test_writable_probe_on_a_real_folder(tmp_path):
    assert UpdateRuntime.writable(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_writable_probe_on_a_missing_folder(tmp_path):
    assert not UpdateRuntime.writable(tmp_path / "missing")


def test_staged_folder_sits_beside_the_program_folder():
    assert UpdateRuntime.staged_folder(FOLDER) == Path("/opt/demo/DemoApp.staged")
