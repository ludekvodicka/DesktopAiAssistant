import pytest

from ..checksums import UpdateChecksums
from ..errors import UpdateIntegrityError

A = "a" * 64
B = "0123456789abcdef" * 4


def test_text_and_binary_forms():
    text = f"{A}  Demo-App-1.0.0-x64.exe\n{B} *Demo-App-1.0.0.zip\n"
    assert UpdateChecksums.parse(text) == {
        "Demo-App-1.0.0-x64.exe": A,
        "Demo-App-1.0.0.zip": B,
    }


def test_upper_case_hex_is_normalized():
    assert UpdateChecksums.expected(f"{B.upper()}  demo.bin\r\n", "demo.bin") == B


def test_malformed_lines_are_ignored():
    text = "\n".join([
        "# comment",
        f"{A[:-1]}  short.bin",
        f"{A}\tdemo-tab.bin",
        f"{'g' * 64}  not-hex.bin",
        f"{A}  demo.bin",
        "",
    ])
    assert UpdateChecksums.parse(text) == {"demo.bin": A}


def test_missing_name_raises():
    with pytest.raises(UpdateIntegrityError, match="demo.bin"):
        UpdateChecksums.expected(f"{A}  other.bin\n", "demo.bin")
