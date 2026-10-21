"""Opt-in TLS acceptance check, also runnable inside the released GUI executable."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import urllib.error

import certifi

from . import __version__


INCIDENT_HOSTS = tuple(
    f"{kind}-{series}{cross}-emudhra.we-have-a-problem.com"
    for kind in ("dv", "ov", "ev")
    for series in ("g3b", "g3c")
    for cross in ("", "-aaa")
)
API = "https://api.github.com/repos/ludekvodicka/DesktopAiAssistant/releases/latest"
CHECKSUMS = "https://github.com/ludekvodicka/DesktopAiAssistant/releases/latest/download/SHA256SUMS.txt"


def check(transport, method: str, url: str, reject: bool) -> dict:
    result = {"method": method, "url": url, "expected": "certificate-error" if reject else "accepted"}
    try:
        if method == "get_text":
            body = transport.get_text(url, 1_048_576)
            if not body:
                raise ValueError("Empty control response")
        elif method == "get_json":
            body = transport.get_json(url)
            if not body:
                raise ValueError("Empty control response")
        elif method == "download":
            expected = None if reject else transport.get_text(url, 1_048_576).encode("utf-8")
            with tempfile.TemporaryDirectory(prefix="update-tls-") as folder:
                destination = Path(folder) / "response"
                digest = transport.download(url, destination,
                                            1_048_576 if expected is None else len(expected),
                                            lambda _: None, lambda: False)
                if expected is not None and (
                        destination.read_bytes() != expected or
                        digest != hashlib.sha256(expected).hexdigest()):
                    raise ValueError("Downloaded control differs from its text response")
        else:
            raise ValueError(f"Unknown transport method: {method}")
        result.update(outcome="accepted", passed=not reject)
    except Exception as error:
        cause = error.reason if isinstance(error, urllib.error.URLError) else error
        certificate_error = isinstance(cause, ssl.SSLCertVerificationError)
        result.update(outcome="certificate-error" if certificate_error else "error",
                      passed=reject and certificate_error,
                      error_type=type(cause).__name__, error=str(cause))
        if certificate_error:
            result.update(verify_code=cause.verify_code, verify_message=cause.verify_message)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    options = parser.parse_args(argv)
    report = {"version": __version__, "at": datetime.now(timezone.utc).isoformat(),
              "executable": sys.executable, "frozen": bool(getattr(sys, "frozen", False)),
              "python": sys.version, "openssl": ssl.OPENSSL_VERSION,
              "certifi": certifi.__version__, "results": [], "passed": False}
    try:
        from PySide6.QtCore import QCoreApplication
        from .updates import Updates

        app = QCoreApplication.instance() or QCoreApplication([])
        previous_data = os.environ.get("DESKTOP_AI_DATA")
        with tempfile.TemporaryDirectory(prefix="update-tls-data-") as folder:
            os.environ["DESKTOP_AI_DATA"] = folder
            try:
                updates = Updates.create(app, busy=lambda: False)
            finally:
                if previous_data is None:
                    os.environ.pop("DESKTOP_AI_DATA")
                else:
                    os.environ["DESKTOP_AI_DATA"] = previous_data
        transport = updates._manager._feed._transport
        if updates._manager._stager._transport is not transport:
            raise ValueError("Metadata and downloads use different transports")
        report["composition"] = "Updates.create: shared feed and stager transport"
        bundle = Path(certifi.where())
        report.update(ca_file=str(bundle), ca_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                      verify_mode=transport._context.verify_mode,
                      check_hostname=transport._context.check_hostname)
        cases = [(method, f"https://{host}/", True) for host in INCIDENT_HOSTS
                 for method in ("get_text", "get_json", "download")]
        cases += [("get_text", "https://example.com/", False), ("get_json", API, False),
                  ("get_text", CHECKSUMS, False), ("download", CHECKSUMS, False)]
        with ThreadPoolExecutor(max_workers=4) as workers:
            report["results"] = list(workers.map(lambda case: check(transport, *case), cases))
        report["passed"] = all(result["passed"] for result in report["results"])
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    options.report.write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
