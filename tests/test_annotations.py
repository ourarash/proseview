"""Tests for the inline TODO / NOTE writers in :mod:`proseview.server`.

These six functions are the only code paths besides the scene editor that write
into a manuscript file, so the contract they have to hold is narrow but strict:

    - an annotation lands above the paragraph the selection came from
    - a selection that no longer matches raises instead of guessing a location
    - every write is atomic, so a failure mid-write cannot truncate the prose
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.server import (  # noqa: E402
    _atomic_write_text,
    add_note,
    delete_note,
    delete_todo,
    edit_note,
    edit_todo,
    insert_todo,
)

SCENE = """\
---
title: Opening
---

# Opening

The harbour was empty when she arrived.

She counted the boats twice, and then a third time.

The tide went out without her.
"""

#: Lines of frontmatter + heading before the prose begins.
OFFSET = 5


@pytest.fixture()
def scene(tmp_path: Path) -> Path:
    path = tmp_path / "01-opening.md"
    path.write_text(SCENE, encoding="utf-8")
    return path


# ── Anchoring ────────────────────────────────────────────────────────────────

def test_todo_lands_above_the_paragraph_the_selection_came_from(scene: Path):
    insert_todo(str(scene), "counted the boats", OFFSET, "check the count")
    lines = scene.read_text(encoding="utf-8").splitlines()

    comment_idx = lines.index("<!-- TODO: check the count -->")
    paragraph_idx = next(i for i, ln in enumerate(lines) if "counted the boats" in ln)
    assert comment_idx < paragraph_idx
    # Nothing above the anchor paragraph moved.
    assert "The harbour was empty when she arrived." in lines[:comment_idx]


def test_note_lands_above_its_paragraph_and_carries_its_tag(scene: Path):
    add_note(str(scene), "The tide went out", OFFSET, "does this contradict ch03?", "continuity")
    lines = scene.read_text(encoding="utf-8").splitlines()

    comment_idx = lines.index("<!-- NOTE[continuity]: does this contradict ch03? -->")
    assert comment_idx < next(i for i, ln in enumerate(lines) if "The tide went out" in ln)


def test_untagged_note_omits_the_bracket(scene: Path):
    add_note(str(scene), "The tide went out", OFFSET, "reads well", "note")
    assert "<!-- NOTE: reads well -->" in scene.read_text(encoding="utf-8")


# ── Failing loudly rather than guessing ──────────────────────────────────────

def test_stale_selection_raises_instead_of_annotating_the_first_paragraph(scene: Path):
    """The regression this suite exists for.

    A selection that no longer appears in the file used to fall through to
    ``para_idx = 0``, silently planting the comment at the top of the scene.
    """
    before = scene.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="Could not find the selected passage"):
        insert_todo(str(scene), "a sentence that was edited away", OFFSET, "orphaned")

    assert scene.read_text(encoding="utf-8") == before


def test_stale_selection_raises_for_notes_too(scene: Path):
    before = scene.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="Could not find the selected passage"):
        add_note(str(scene), "not in this scene at all", OFFSET, "orphaned", "question")

    assert scene.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("selection", ["", "   "])
def test_empty_selection_raises_rather_than_defaulting_to_the_top(scene: Path, selection: str):
    before = scene.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="No selected text to anchor to"):
        insert_todo(str(scene), selection, OFFSET, "no anchor")

    assert scene.read_text(encoding="utf-8") == before


def test_missing_file_raises_before_any_write(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        insert_todo(str(tmp_path / "nope.md"), "anything", 0, "x")


# ── Edit and delete ──────────────────────────────────────────────────────────

def test_edit_and_delete_round_trip_a_todo(scene: Path):
    insert_todo(str(scene), "counted the boats", OFFSET, "check the count")
    edit_todo(str(scene), "check the count", "verify the count")
    assert "<!-- TODO: verify the count -->" in scene.read_text(encoding="utf-8")

    delete_todo(str(scene), "verify the count")
    text = scene.read_text(encoding="utf-8")
    assert "TODO" not in text
    assert "\n\n\n" not in text, "deleting should collapse the blank line it leaves"


def test_edit_and_delete_round_trip_a_tagged_note(scene: Path):
    add_note(str(scene), "The tide went out", OFFSET, "check ch03", "continuity")
    edit_note(str(scene), "check ch03", "continuity", "checked, fine", "theme")
    assert "<!-- NOTE[theme]: checked, fine -->" in scene.read_text(encoding="utf-8")

    delete_note(str(scene), "checked, fine", "theme")
    assert "NOTE" not in scene.read_text(encoding="utf-8")


def test_editing_an_absent_annotation_raises(scene: Path):
    with pytest.raises(ValueError, match="TODO not found"):
        edit_todo(str(scene), "never written", "replacement")
    with pytest.raises(ValueError, match="Note not found"):
        delete_note(str(scene), "never written", "note")


# ── Atomicity ────────────────────────────────────────────────────────────────

def test_a_failed_write_leaves_the_original_file_intact(scene: Path, monkeypatch):
    """A write that dies partway must not truncate the prose.

    ``_atomic_write_text`` stages into a sibling temp file, so an exception
    raised before ``os.replace`` leaves the target byte-for-byte unchanged.
    """
    before = scene.read_text(encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("proseview.server.os.replace", boom)

    with pytest.raises(OSError, match="disk full"):
        insert_todo(str(scene), "counted the boats", OFFSET, "check the count")

    assert scene.read_text(encoding="utf-8") == before


def test_a_failed_write_leaves_no_temp_files_behind(scene: Path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("proseview.server.os.replace", boom)
    with pytest.raises(OSError):
        insert_todo(str(scene), "counted the boats", OFFSET, "check the count")

    assert list(scene.parent.glob("*.tmp")) == []


def test_atomic_write_replaces_contents_in_place(tmp_path: Path):
    target = tmp_path / "scene.md"
    target.write_text("old\n", encoding="utf-8")

    _atomic_write_text(target, "new\n")

    assert target.read_text(encoding="utf-8") == "new\n"
    assert list(tmp_path.glob("*.tmp")) == []


# ── Concurrent-edit guard ────────────────────────────────────────────────────

def test_a_scene_edited_since_the_page_loaded_refuses_the_annotation(scene: Path):
    """The other half of the atomic-write work.

    Annotations anchor to a paragraph the reader could see. If the scene changed
    in another editor since the page rendered it, that anchor may no longer mean
    what they selected, so the write is refused rather than guessed at.
    """
    from proseview.server import _FileConflictError

    stale = scene.stat().st_mtime - 5
    before = scene.read_text(encoding="utf-8")

    with pytest.raises(_FileConflictError, match="changed on disk"):
        insert_todo(str(scene), "counted the boats", OFFSET, "late", stale)

    assert scene.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("call", [
    lambda p, mt: insert_todo(str(p), "counted the boats", OFFSET, "x", mt),
    lambda p, mt: edit_todo(str(p), "a", "b", mt),
    lambda p, mt: delete_todo(str(p), "a", mt),
    lambda p, mt: add_note(str(p), "counted the boats", OFFSET, "x", "note", mt),
    lambda p, mt: edit_note(str(p), "a", "note", "b", "note", mt),
    lambda p, mt: delete_note(str(p), "a", "note", mt),
])
def test_every_mutator_honours_the_guard(scene: Path, call):
    from proseview.server import _FileConflictError

    with pytest.raises(_FileConflictError):
        call(scene, scene.stat().st_mtime - 5)


def test_a_matching_mtime_lets_the_write_through(scene: Path):
    insert_todo(str(scene), "counted the boats", OFFSET, "fine", scene.stat().st_mtime)
    assert "<!-- TODO: fine -->" in scene.read_text(encoding="utf-8")


def test_omitting_the_mtime_keeps_the_old_unguarded_behaviour(scene: Path):
    """The CLI does not track page state, so the guard stays opt-in."""
    insert_todo(str(scene), "counted the boats", OFFSET, "cli")
    assert "<!-- TODO: cli -->" in scene.read_text(encoding="utf-8")
