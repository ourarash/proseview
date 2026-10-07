"""Tests for reading a unified diff into hunks.

Prosview renders diffs it did not write -- an agent's reported change, a save
conflict -- so the parser has to tolerate the shapes those arrive in. Undoing
an agent's work is not done from a patch; see ``test_hunks``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.patches import (  # noqa: E402
    parse_hunks,
    parse_unified_diff,
)

BEFORE = "alpha\nShe had used the same four digits since spring.\nomega\n"
AFTER = "alpha\nShe had changed the four digits at the start of spring.\nomega\n"

ONE_HUNK = (
    "@@ -2,1 +2,1 @@\n"
    "-She had used the same four digits since spring.\n"
    "+She had changed the four digits at the start of spring.\n"
)

TWO_HUNKS = (
    "--- a/manuscript/ch01/01-opening.md\n"
    "+++ b/manuscript/ch01/01-opening.md\n"
    "@@ -1,3 +1,3 @@\n"
    " alpha\n"
    "-old first\n"
    "+new first\n"
    " bridge\n"
    "@@ -10,3 +10,3 @@\n"
    " gamma\n"
    "-old second\n"
    "+new second\n"
    " delta\n"
)


def test_parses_headers_hunks_and_line_operations() -> None:
    files = parse_unified_diff(TWO_HUNKS)
    assert len(files) == 1
    assert files[0].old_path == "manuscript/ch01/01-opening.md"
    assert files[0].new_path == "manuscript/ch01/01-opening.md"
    first, second = files[0].hunks
    assert (first.index, second.index) == (1, 2)
    assert first.old_start == 1 and second.new_start == 10
    assert first.old_lines == ["alpha", "old first", "bridge"]
    assert first.new_lines == ["alpha", "new first", "bridge"]


def test_parses_a_bare_hunk_without_file_headers() -> None:
    hunks = parse_hunks(ONE_HUNK)
    assert len(hunks) == 1
    assert hunks[0].new_lines == ["She had changed the four digits at the start of spring."]


def test_trailing_newline_is_not_read_as_a_context_line() -> None:
    assert parse_hunks("@@ -1,1 +1,1 @@\n-a\n+b\n")[0].new_lines == ["b"]


def test_drops_no_newline_markers_and_ignores_trailing_junk() -> None:
    hunks = parse_hunks("@@ -1,1 +1,1 @@\n-a\n+b\n\\ No newline at end of file\ndiff --git c d\n")
    assert len(hunks) == 1
    assert hunks[0].old_lines == ["a"] and hunks[0].new_lines == ["b"]


def test_text_without_any_hunk_header_yields_nothing() -> None:
    assert parse_hunks("Once upon a time\nthe end\n") == []


def test_separates_two_file_sections() -> None:
    files = parse_unified_diff(
        "--- a/one.md\n+++ b/one.md\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        "--- a/two.md\n+++ b/two.md\n@@ -1,1 +1,1 @@\n-c\n+d\n"
    )
    assert [f.new_path for f in files] == ["one.md", "two.md"]
    # Hunk numbering runs across the whole patch so an id stays unique.
    assert [hunk.index for f in files for hunk in f.hunks] == [1, 2]


def test_the_scene_diff_keeps_prose_copyable() -> None:
    """A diff a writer can copy out of.

    difflib.HtmlDiff renders every space as &nbsp;, so lifting a passage out of
    the review modal produced U+00A0 between every word -- which then travelled
    back into the manuscript on paste.
    """
    from proseview.server import render_scene_diff_html

    old = "alpha\nShe counted the boats twice.\nomega\n"
    new = "alpha\nShe counted the boats three times.\nomega\n"
    for mode in ("inline", "side-by-side"):
        html = render_scene_diff_html(old, new, mode=mode)
        assert "&nbsp;" not in html, f"{mode} diff is not copyable"
        assert "counted the boats" in html, f"{mode} diff lost the prose"
