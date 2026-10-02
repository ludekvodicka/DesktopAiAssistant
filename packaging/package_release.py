"""Package the folder build as the release zip and the per-user Setup.

    python packaging/package_release.py [--zip-only]

Reads dist/DesktopAiAssistant (built by packaging/build.ps1) and writes into dist/release:
DesktopAiAssistant-X.Y.Z-win-x64.zip, which installed copies download as their update, and
DesktopAiAssistant-Setup-X.Y.Z-x64.exe for first installs. --zip-only skips the Setup on a
machine without Inno Setup.
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


class PackageRelease:
    root = Path(__file__).resolve().parents[1]
    name = "DesktopAiAssistant"

    @staticmethod
    def main(argv: list[str]) -> int:
        parser = argparse.ArgumentParser(description="Package the release zip and Setup.")
        parser.add_argument("--zip-only", action="store_true", help="skip the Inno Setup installer")
        options = parser.parse_args(argv)
        version = PackageRelease.version()
        source = PackageRelease.root / "dist" / PackageRelease.name
        output = PackageRelease.root / "dist" / "release"
        if not (source / f"{PackageRelease.name}.exe").is_file():
            raise SystemExit(f"Build first: {source} has no {PackageRelease.name}.exe")
        iscc = None if options.zip_only else PackageRelease.iscc()
        shutil.rmtree(output, ignore_errors=True)
        output.mkdir(parents=True)
        archive = output / f"{PackageRelease.name}-{version}-win-x64.zip"
        longest = PackageRelease.zip(source, archive)
        print(f"{archive.name}: {archive.stat().st_size} bytes, longest relative path {longest} characters",
              flush=True)
        if iscc is not None:
            PackageRelease.installer(iscc, version)
        return 0

    @staticmethod
    def version() -> str:
        sys.path.insert(0, str(PackageRelease.root / "src"))
        from desktop_ai_assistant import __version__
        return __version__

    @staticmethod
    def zip(source: Path, archive: Path) -> int:
        """One top folder and forward slashes, as the updater's stager requires; returns the
        longest relative path, which the staged copy beside the program folder must keep short."""
        longest = 0
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            for path in sorted(source.rglob("*")):
                relative = path.relative_to(source)
                if ".svn" in relative.parts:
                    raise SystemExit(f"Refusing SVN metadata in the package: {relative}")
                if path.is_symlink():
                    raise SystemExit(f"Refusing a link in the package: {relative}")
                if path.is_file():
                    package.write(path, f"{PackageRelease.name}/{relative.as_posix()}")
                    longest = max(longest, len(str(relative)))
        return longest

    @staticmethod
    def installer(iscc: Path, version: str) -> None:
        script = PackageRelease.root / "packaging" / "installer.iss"
        completed = subprocess.run([str(iscc), "/Q", f"/DAppVersion={version}", str(script)], check=False)
        if completed.returncode != 0:
            raise SystemExit(f"Inno Setup failed with exit code {completed.returncode}")
        setup = PackageRelease.root / "dist" / "release" / f"{PackageRelease.name}-Setup-{version}-x64.exe"
        if not setup.is_file():
            raise SystemExit(f"Inno Setup wrote no {setup.name}")
        print(f"{setup.name}: {setup.stat().st_size} bytes", flush=True)

    @staticmethod
    def iscc() -> Path:
        """The ISCC variable, then PATH (GitHub runner image), then the default install folders."""
        candidates = [os.environ.get("ISCC"), shutil.which("iscc")]
        for variable in ("ProgramFiles(x86)", "ProgramFiles"):
            if folder := os.environ.get(variable):
                candidates.append(str(Path(folder) / "Inno Setup 6" / "ISCC.exe"))
        if folder := os.environ.get("LOCALAPPDATA"):
            candidates.append(str(Path(folder) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        raise SystemExit("Inno Setup 6 (ISCC.exe) was not found. Install it, set ISCC to its path, "
                         "or pass --zip-only.")


if __name__ == "__main__":
    raise SystemExit(PackageRelease.main(sys.argv[1:]))
