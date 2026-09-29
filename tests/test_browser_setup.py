import json
from pathlib import Path
from contextlib import nullcontext
import pytest
from desktop_ai_assistant import browser_setup


def test_extension_identity_and_legacy_path():
    assert browser_setup.extension_id(b"test") == "jpignaibiiemhngfjkcpokkamffknabf"
    assert browser_setup.extension_id("/path/to/file.ext".encode("utf-16-le")) == "jjlkojfgbeklddcpckipekckcmgcbfjn"
    assert browser_setup.unpacked_id(r"c:\projects\browser-extension") == browser_setup.unpacked_id(r"C:\projects\browser-extension")
    manifest = Path(__file__).parents[1] / "browser-extension/manifest.json"
    old = "a" * 32
    first = browser_setup.allowed_origins(Path(r"C:\First\browser-extension"), manifest, {"id": old})
    second = browser_setup.allowed_origins(Path(r"D:\Second\browser-extension"), manifest, None)
    assert len(set(first) & set(second)) == 1, "Keyed identity must survive moving the extension"
    assert f"chrome-extension://{old}/" in first
    with pytest.raises(ValueError):
        browser_setup.allowed_origins(Path(r"C:\First"), manifest, {"id": "*"})


def test_automatic_registration_preserves_installed_id_and_rejects_other_origins(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_AI_DATA", str(tmp_path))
    old = "b" * 32
    (tmp_path / "extension.json").write_text(json.dumps({"id": old}))
    folder = tmp_path / "browser-extension"
    folder.mkdir()
    (folder / "manifest.json").write_text("{}")
    (tmp_path / "DesktopAiHost.exe").write_bytes(b"host")
    monkeypatch.setattr(browser_setup, "extension_directory", lambda: folder)
    writes = []
    monkeypatch.setattr(browser_setup.winreg, "CreateKey", lambda root, key: nullcontext(key))
    monkeypatch.setattr(browser_setup.winreg, "SetValueEx", lambda *args: writes.append(args))
    browser_setup.register_browser()
    manifest = json.loads((tmp_path / "native-host.json").read_text())
    assert len(writes) == 2
    assert all(item[-1] == str(tmp_path / "native-host.json") for item in writes)
    assert manifest["path"] == str(tmp_path / "DesktopAiHost.exe")
    assert browser_setup.origin_allowed(f"chrome-extension://{old}/")
    assert browser_setup.origin_allowed(f"chrome-extension://{browser_setup.unpacked_id(folder)}/")
    assert not browser_setup.origin_allowed("chrome-extension://" + "p" * 32 + "/")
    assert not browser_setup.origin_allowed("chrome-extension://*/")
    assert not browser_setup.origin_allowed(f"https://{old}/")
    browser_setup.register_browser()
    assert json.loads((tmp_path / "native-host.json").read_text()) == manifest
