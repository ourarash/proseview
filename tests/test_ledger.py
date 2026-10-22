"""Tests for :mod:`proseview.ledger`: written and cut, scene by scene."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.ledger import (  # noqa: E402
    build_ledger,
    read_day_text,
    record_day_text,
    word_changes,
)


def test_word_changes_split_a_rewrite_into_written_and_cut():
    written, cut = word_changes("She left the room quietly.", "She ran from the burning room.")
    assert (written, cut) == (3, 2)
    # Always adds up to the change in word count.
    assert written - cut == 6 - 5


def test_a_replaced_draft_shows_both_sides():
    """The case that read as a bare -1,079: a long draft out, a shorter one in."""
    old = {"m/ch05/07-first-results.md": "word " * 1776}
    new = {"m/ch05/07-next-best-thing.md": "fresh " * 697}
    ledger = build_ledger(old, new, baseline_date="2026-10-18", baseline_kind="commit")
    assert (ledger.written, ledger.cut) == (697, 1776)
    assert {row.status for row in ledger.rows} == {"new", "removed"}


def test_a_rename_alone_writes_and_cuts_nothing():
    text = "The submission went in at midnight and nobody slept. " * 20
    ledger = build_ledger({"m/08-submission.md": text}, {"m/09-submission.md": text},
                          baseline_date="2026-10-21", baseline_kind="day")
    assert ledger.rows == ()


def test_a_renamed_and_edited_scene_is_one_row():
    old = "The submission went in at midnight and nobody slept. " * 20
    new = old + "Then the reviews came."
    ledger = build_ledger({"m/08.md": old}, {"m/09.md": new},
                          baseline_date="2026-10-21", baseline_kind="day")
    (row,) = ledger.rows
    assert (row.status, row.old_path, row.written, row.cut) == ("renamed", "m/08.md", 4, 0)


def test_day_text_rolls_over_at_a_new_day(tmp_path: Path):
    assert record_day_text(tmp_path, "2026-10-21", {"a.md": "one two"}) is None
    record_day_text(tmp_path, "2026-10-21", {"a.md": "one two three"})
    previous = record_day_text(tmp_path, "2026-10-22", {"a.md": "one"})
    # The end of the 21st is the baseline for the 22nd, on that run and after.
    assert previous == ("2026-10-21", {"a.md": "one two three"})
    assert record_day_text(tmp_path, "2026-10-22", {"a.md": "one four"}) == previous
    assert read_day_text(tmp_path)[0] == "2026-10-22"
