import logging
from pathlib import Path
import winreg

log = logging.getLogger(__name__)


class InstallRegistration:
    """The Apps & Features entry that Setup writes; a self-update keeps its version current."""

    # AppId in packaging/installer.iss; a test compares the two. It never changes.
    app_id = "{9EA4AB2D-541B-497C-A34F-10C2FBE9D378}"
    uninstall_key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{app_id}_is1"

    @staticmethod
    def sync(app_dir: Path, version: str, key: str = uninstall_key) -> bool:
        """Writes DisplayVersion when the entry belongs to this program folder."""
        try:
            handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                                    winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE)
        except FileNotFoundError:
            return False
        with handle:
            try:
                location, _ = winreg.QueryValueEx(handle, "InstallLocation")
            except FileNotFoundError:
                return False
            # A portable copy elsewhere must not rewrite the installed copy's entry.
            if Path(location).resolve() != app_dir.resolve():
                return False
            winreg.SetValueEx(handle, "DisplayVersion", 0, winreg.REG_SZ, version)
        return True

    @staticmethod
    def sync_quietly(app_dir: Path, version: str) -> None:
        try:
            InstallRegistration.sync(app_dir, version)
        except OSError as error:
            log.warning("Could not update the uninstall entry: %s", error)
