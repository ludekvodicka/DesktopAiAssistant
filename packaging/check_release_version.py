"""Refuse a release whose tag does not match the version in the source.

Run by the release workflow before anything is built. A tag of v0.4.0 must find 0.4.0 in
src/desktop_ai_assistant/__init__.py, otherwise the published files would carry a version
nobody can trace back to a commit. Outside a tag build it only checks that the version is a
valid semantic version, which is what the workflow_dispatch build-only path needs.
"""

import os
import re
import sys
from pathlib import Path


class ReleaseVersion:
    semver = re.compile(r"^\d+\.\d+\.\d+$")

    @staticmethod
    def check(version: str, ref_type: str, ref_name: str) -> str | None:
        """None when the release may go on, otherwise the problem."""
        if not ReleaseVersion.semver.match(version):
            return f"src/desktop_ai_assistant/__init__.py holds {version!r}, which is not MAJOR.MINOR.PATCH."
        if ref_type != "tag":
            print(f"version {version} (no tag to compare against)")
            return None
        if not ref_name.startswith("v"):
            return f"Tag {ref_name!r} does not start with 'v'."
        if ref_name[1:] != version:
            return f"Tag {ref_name} does not match src/desktop_ai_assistant/__init__.py ({version})."
        print(f"version {version} matches tag {ref_name}")
        return None

    @staticmethod
    def main() -> int:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from desktop_ai_assistant import __version__
        problem = ReleaseVersion.check(__version__, os.environ.get("GITHUB_REF_TYPE", ""),
                                       os.environ.get("GITHUB_REF_NAME", ""))
        if problem:
            print(problem, file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(ReleaseVersion.main())
