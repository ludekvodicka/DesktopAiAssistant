from ..release_notes import UpdateReleaseNotes


def test_none_and_empty_body():
    assert UpdateReleaseNotes.to_text(None) is None
    assert UpdateReleaseNotes.to_text("") is None
    assert UpdateReleaseNotes.to_text("<!-- update-notes-end -->\n### Verify") is None


def test_headings_lose_their_marks():
    assert UpdateReleaseNotes.to_text("## What changed\n\n### Fixes") == "What changed\n\nFixes"


def test_hash_without_space_is_text():
    assert UpdateReleaseNotes.to_text("#42 is fixed") == "#42 is fixed"


def test_nested_lists_keep_their_indent():
    body = "* first\n  + nested\n    - deeper\n1. numbered"
    assert UpdateReleaseNotes.to_text(body) == "- first\n  - nested\n    - deeper\n1. numbered"


def test_links_and_images():
    body = "See [the guide](https://example.com/guide) ![shot](https://example.com/a.png) now"
    assert UpdateReleaseNotes.to_text(body) == "See the guide  now"


def test_fences_keep_their_content():
    body = "Run:\n```bash\ndemo --help\n```\nDone"
    assert UpdateReleaseNotes.to_text(body) == "Run:\ndemo --help\nDone"


def test_inline_emphasis_and_code():
    body = "- **Bold** and *soft* and __strong__ and `code` and _quiet_"
    assert UpdateReleaseNotes.to_text(body) == "- Bold and soft and strong and code and quiet"


def test_snake_case_words_are_untouched():
    assert UpdateReleaseNotes.to_text("Set max_chunk_size and a_b_c") == (
        "Set max_chunk_size and a_b_c")


def test_inline_html_and_entities():
    body = "<p>Fast &amp; safe<br>next line</p> <b>&lt;done&gt;</b>"
    assert UpdateReleaseNotes.to_text(body) == "Fast & safe\nnext line <done>"


def test_end_marker_cuts_the_body():
    body = "Fixes the export.\n\n<!-- update-notes-end -->\n\n### Verify your download\n" + "a" * 64
    assert UpdateReleaseNotes.to_text(body) == "Fixes the export."


def test_blank_runs_collapse_and_crlf_is_normalized():
    assert UpdateReleaseNotes.to_text("one  \r\n\r\n\r\n\r\ntwo\r\n") == "one\n\ntwo"
