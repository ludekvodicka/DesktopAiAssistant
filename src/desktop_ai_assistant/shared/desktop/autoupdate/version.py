import re


class UpdateVersion:
    pattern = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

    @staticmethod
    def parse(text: str) -> tuple[int, int, int] | None:
        match = UpdateVersion.pattern.fullmatch(text.strip())
        if match is None:
            return None
        major, minor, patch = (int(part) for part in match.groups())
        return major, minor, patch

    @staticmethod
    def is_newer(candidate: str, running: str) -> bool:
        left, right = UpdateVersion.parse(candidate), UpdateVersion.parse(running)
        if left is None or right is None:
            return False
        return left > right
