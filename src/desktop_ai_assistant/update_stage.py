import json
import shutil
from pathlib import Path


class UpdateStage:
    """Adjusts a staged update folder before the helper swaps it in for the installed one."""

    # The Inno Setup uninstaller and its file log; the update package does not carry them.
    uninstaller = "unins[0-9][0-9][0-9].*"

    @staticmethod
    def prepare(staged: Path, installed: Path) -> None:
        UpdateStage.keep_extension_identity(staged / "browser-extension/manifest.json",
                                            installed / "browser-extension/manifest.json")
        for file in installed.glob(UpdateStage.uninstaller):
            shutil.copy2(file, staged / file.name)

    @staticmethod
    def keep_extension_identity(staged: Path, installed: Path) -> None:
        # Same rule as browser-extension/deploy.mjs: a loaded unpacked extension keeps its ID.
        if not installed.is_file() or not staged.is_file():
            return
        previous = json.loads(installed.read_text("utf-8"))
        manifest = json.loads(staged.read_text("utf-8"))
        if previous.get("key"):
            manifest["key"] = previous["key"]
        else:
            manifest.pop("key", None)
        staged.write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
