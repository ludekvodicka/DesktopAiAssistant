from dataclasses import dataclass

import pytest

from ..status import (
    UpdateAvailable,
    UpdateChecking,
    UpdateCurrent,
    UpdateDownloading,
    UpdateFailed,
    UpdateIdle,
    UpdateInstalling,
    UpdateOff,
    UpdateReady,
    UpdateRelease,
    UpdateStatus,
)
from ..view import UpdateView, UpdateViewModel

RELEASE = UpdateRelease("1.2.0", "Demo 1.2.0", "2026-01-02T03:04:05Z", "Notes")


def describe(state, release_page: bool) -> UpdateViewModel:
    return UpdateView.describe(UpdateStatus("1.1.0", "automatic", release_page, state))


CASES = [
    (UpdateOff("Development run."),
     UpdateViewModel("Updates off", "Development run.", "muted", (), None),
     ("open_release",)),
    (UpdateIdle(),
     UpdateViewModel("Version 1.1.0", None, "muted", ("check",), None),
     ("check",)),
    (UpdateChecking(),
     UpdateViewModel("Checking for updates", None, "working", (), None),
     ()),
    (UpdateCurrent(10.0),
     UpdateViewModel("Up to date", "Version 1.1.0", "muted", ("check",), None),
     ("check",)),
    (UpdateAvailable(RELEASE),
     UpdateViewModel("Version 1.2.0 available", None, "attention", ("check",), RELEASE),
     ("open_release", "check")),
    (UpdateDownloading(RELEASE, 42.5, 425, 1000, 100.0),
     UpdateViewModel("Downloading 1.2.0 (43%)", None, "working", (), RELEASE),
     ()),
    (UpdateReady(RELEASE),
     UpdateViewModel("Version 1.2.0 ready", "Installs on restart or on the next quit.", "ready",
                     ("install",), RELEASE),
     ("install", "open_release")),
    (UpdateInstalling(RELEASE),
     UpdateViewModel("Restarting to install", None, "working", (), RELEASE),
     ()),
    (UpdateFailed("Network down.", None),
     UpdateViewModel("Update failed", "Network down.", "failed", ("check",), None),
     ("check", "open_release")),
]


@pytest.mark.parametrize(("state", "expected", "linked_actions"), CASES)
def test_without_release_page(state, expected, linked_actions):
    assert describe(state, release_page=False) == expected


@pytest.mark.parametrize(("state", "expected", "linked_actions"), CASES)
def test_with_release_page(state, expected, linked_actions):
    view = describe(state, release_page=True)
    assert (view.text, view.detail, view.tone, view.release) == (
        expected.text, expected.detail, expected.tone, expected.release)
    assert view.actions == linked_actions


def test_percent_rounds_half_up_like_javascript():
    assert describe(UpdateDownloading(RELEASE, 0.5, 5, 1000, 0.0), False).text == (
        "Downloading 1.2.0 (1%)")
    assert describe(UpdateDownloading(RELEASE, 99.4, 994, 1000, 0.0), False).text == (
        "Downloading 1.2.0 (99%)")


def test_unknown_state_raises():
    @dataclass(frozen=True)
    class UpdateStrange:
        pass

    with pytest.raises(ValueError, match="Unknown update state"):
        describe(UpdateStrange(), False)
