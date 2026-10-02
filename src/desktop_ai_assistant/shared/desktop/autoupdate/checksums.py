import re

from .errors import UpdateIntegrityError


class UpdateChecksums:
    # sha256sum output: "<hex>  <name>" in text mode, "<hex> *<name>" in binary mode.
    line = re.compile(r"([0-9a-fA-F]{64}) [ *](.+)")

    @staticmethod
    def parse(text: str) -> dict[str, str]:
        sums: dict[str, str] = {}
        for raw in text.splitlines():
            match = UpdateChecksums.line.fullmatch(raw.strip())
            if match is not None:
                sums[match.group(2)] = match.group(1).lower()
        return sums

    @staticmethod
    def expected(text: str, name: str) -> str:
        digest = UpdateChecksums.parse(text).get(name)
        if digest is None:
            raise UpdateIntegrityError(f"SHA256SUMS.txt has no entry for {name}.")
        return digest
