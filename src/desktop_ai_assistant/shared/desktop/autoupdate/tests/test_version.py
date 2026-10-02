import pytest

from ..version import UpdateVersion


def test_prefixed_candidate_is_newer():
    assert UpdateVersion.is_newer("v0.3.1", "0.3.0")


def test_equal_version_is_not_newer():
    assert not UpdateVersion.is_newer("0.3.0", "v0.3.0")


def test_older_version_is_not_newer():
    assert not UpdateVersion.is_newer("0.2.9", "0.3.0")


def test_numeric_parts_compare_as_numbers():
    assert UpdateVersion.is_newer("0.10.0", "0.9.9")


@pytest.mark.parametrize("candidate", ["0.3.1-beta", "latest", "", "1.2", "v", "0.3.1.4"])
def test_unparsable_candidate_is_no_update(candidate):
    assert UpdateVersion.parse(candidate) is None
    assert not UpdateVersion.is_newer(candidate, "0.3.0")


def test_unparsable_running_version_is_no_update():
    assert not UpdateVersion.is_newer("9.9.9", "dev")


def test_parse_strips_whitespace_and_prefix():
    assert UpdateVersion.parse(" v1.2.3\n") == (1, 2, 3)
