import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import winreg
from .config import data_dir


def extension_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "browser-extension"
    return Path(__file__).absolute().parents[2] / "dist/DesktopAiAssistant/browser-extension"


def extension_id(data):
    return hashlib.sha256(data).hexdigest()[:32].translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def unpacked_id(path):
    # Chromium hashes the Windows path as UTF-16, normalizing only the drive letter.
    normalized = os.path.abspath(path)
    if len(normalized) >= 2 and normalized[1] == ":":
        normalized = normalized[0].upper() + normalized[1:]
    return extension_id(normalized.encode("utf-16-le"))


def allowed_origins(folder, identity_manifest, previous):
    manifest = json.loads(identity_manifest.read_text("utf-8"))
    identifiers = {unpacked_id(folder)}
    if manifest.get("key"):
        identifiers.add(extension_id(base64.b64decode(manifest["key"], validate=True)))
    if previous:
        identifier = previous.get("id")
        if not isinstance(identifier, str) or not re.fullmatch("[a-p]{32}", identifier):
            raise ValueError("Invalid saved browser registration")
        identifiers.add(identifier)
    return [f"chrome-extension://{identifier}/" for identifier in sorted(identifiers)]


def register_browser():
    folder = extension_directory()
    host = folder.parent / "DesktopAiHost.exe"
    if not (folder / "manifest.json").is_file() or not host.is_file():
        raise RuntimeError("Browser integration files are missing. Run packaging/build.ps1.")
    identity_manifest = folder / "manifest.json" if getattr(sys, "frozen", False) else Path(__file__).absolute().parents[2] / "browser-extension/manifest.json"
    legacy = data_dir() / "extension.json"
    previous = json.loads(legacy.read_text("utf-8")) if legacy.exists() else None
    manifest = data_dir() / "native-host.json"
    origins = set(allowed_origins(folder, identity_manifest, previous))
    origins.update(allowed_origins(folder, folder / "manifest.json", None))
    value = {"name": "com.desktopai.assistant", "description": "Desktop AI Assistant", "path": str(host), "type": "stdio",
             "allowed_origins": sorted(origins)}
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), "utf-8")
    temporary.replace(manifest)
    for browser in (r"Google\Chrome", r"Microsoft\Edge"):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\" + browser + r"\NativeMessagingHosts\com.desktopai.assistant") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))


def origin_allowed(origin):
    if not re.fullmatch(r"chrome-extension://[a-p]{32}/", origin):
        return False
    manifest = data_dir() / "native-host.json"
    if manifest.exists():
        return origin in json.loads(manifest.read_text("utf-8")).get("allowed_origins", [])
    legacy = data_dir() / "extension.json"
    if legacy.exists():
        return origin == f"chrome-extension://{json.loads(legacy.read_text('utf-8')).get('id')}/"
    return False
