import hashlib
import socket
import ssl
from types import SimpleNamespace
import urllib.error

import certifi
import pytest

from desktop_ai_assistant.update_transport import create_update_transport
from desktop_ai_assistant.update_tls_check import INCIDENT_HOSTS, check


# The advisory's roots.json includes both TLS roots, the code-signing root and AAA.
INCIDENT_ROOTS = {
    "7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d",
    "f2edaaff3d9b701fb4d14c9f285f8c0bad90fc3bcc1fa07d47f4718edaba34a5",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
}


def test_updater_uses_only_the_patched_bundle(monkeypatch, tmp_path):
    def no_default_roots(*args, **kwargs):
        raise AssertionError("OS roots must not be added to the updater")

    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", no_default_roots)
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "missing"))
    context = create_update_transport()._context
    expected = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    expected.load_verify_locations(cafile=certifi.where())
    assert set(context.get_ca_certs(binary_form=True)) == set(expected.get_ca_certs(binary_form=True))
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert len(context.get_ca_certs()) > 100
    roots = {hashlib.sha256(der).hexdigest() for der in context.get_ca_certs(binary_form=True)}
    assert roots.isdisjoint(INCIDENT_ROOTS)


@pytest.mark.parametrize("content", [None, "invalid CA data"])
def test_missing_or_broken_bundle_fails_closed(monkeypatch, tmp_path, content):
    path = tmp_path / "cacert.pem"
    if content is not None:
        path.write_text(content, "utf-8")
    monkeypatch.setattr(certifi, "where", lambda: str(path))
    with pytest.raises((OSError, ssl.SSLError)):
        create_update_transport()


@pytest.mark.parametrize("cause", [TimeoutError("timeout"), socket.gaierror("DNS failure"),
                                   ConnectionRefusedError("connection refused")])
def test_network_errors_do_not_count_as_distrust(cause):
    def fail(*args):
        raise urllib.error.URLError(cause)

    result = check(SimpleNamespace(get_text=fail), "get_text", "https://example.test/", True)
    assert result["passed"] is False
    assert result["outcome"] == "error"


def test_only_certificate_errors_prove_distrust():
    cause = ssl.SSLCertVerificationError(1, "unable to get local issuer certificate")
    cause.verify_code = 20
    cause.verify_message = "unable to get local issuer certificate"

    def fail(*args):
        raise urllib.error.URLError(cause)

    transport = SimpleNamespace(get_text=fail)
    assert check(transport, "get_text", "https://example.test/", True)["passed"] is True
    assert check(transport, "get_text", "https://example.test/", False)["passed"] is False
    assert len(INCIDENT_HOSTS) == len(set(INCIDENT_HOSTS)) == 12


def test_tls_check_dispatch_precedes_normal_startup(monkeypatch, tmp_path):
    import sys
    from desktop_ai_assistant import app, update_tls_check

    calls = []
    monkeypatch.setattr(sys, "argv", ["app", "--verify-update-tls", str(tmp_path / "report.json")])
    monkeypatch.setattr(update_tls_check, "main", lambda args: calls.append(args) or 17)
    assert app.main() == 17
    assert calls == [[str(tmp_path / "report.json")]]
