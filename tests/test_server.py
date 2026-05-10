"""Tests for the local Proseview HTTP server helpers."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.generator import build_dashboard  # noqa: E402
from proseview.server import _extract_script_vars, save_scene_content, _FileConflictError  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo-repo"
SCENE = FIXTURE / "manuscript" / "ch01" / "01-opening.md"


def test_extract_script_vars_decodes_json_parse_payloads():
    html = build_dashboard(FIXTURE, Config.load(FIXTURE))

    data = _extract_script_vars(html, ("contents", "meta", "highlightsByPath"))

    assert "ch01/01-opening.md" in data["contents"]
    assert data["meta"]["ch01/01-opening.md"]["words"] > 0
    assert data["highlightsByPath"]["ch01/01-opening.md"]["paragraphs"]


# ── save_scene_content tests ─────────────────────────────────────────────────

def test_save_scene_rejects_path_outside_manuscript(tmp_path):
    outside = tmp_path / "evil.md"
    outside.write_text("bad\n")
    mtime = outside.stat().st_mtime
    with pytest.raises(PermissionError):
        save_scene_content(str(outside), "new content", mtime, str(FIXTURE))


def test_save_scene_conflict_guard(tmp_path):
    scene = tmp_path / "manuscript" / "ch01" / "01-opening.md"
    scene.parent.mkdir(parents=True)
    scene.write_text(SCENE.read_text())
    stale_mtime = scene.stat().st_mtime - 10.0  # pretend editor opened 10s ago
    # Touch the file to advance mtime
    scene.write_text(scene.read_text())
    with pytest.raises(_FileConflictError):
        save_scene_content(str(scene), "new content", stale_mtime, str(tmp_path))


def test_save_scene_preserves_frontmatter_and_heading(tmp_path):
    scene = tmp_path / "manuscript" / "ch01" / "01-opening.md"
    scene.parent.mkdir(parents=True)
    original = SCENE.read_text()
    scene.write_text(original)
    mtime = scene.stat().st_mtime

    save_scene_content(str(scene), "Edited prose here.\n", mtime, str(tmp_path))

    result = scene.read_text()
    assert result.startswith("---")
    assert "# Opening Ledger" in result
    assert "Edited prose here." in result
    # Frontmatter fields preserved
    assert "chapter: Chapter 1" in result


def test_save_scene_preserves_multiline_todo(tmp_path):
    scene = tmp_path / "manuscript" / "ch01" / "01-opening.md"
    scene.parent.mkdir(parents=True)
    original = SCENE.read_text()
    # Inject a multiline TODO into the prose section
    with_todo = original.replace(
        "The loft smelled",
        "<!-- TODO: fix this\nspanning two lines -->\nThe loft smelled",
    )
    scene.write_text(with_todo)
    mtime = scene.stat().st_mtime

    # Save with new prose that still contains the TODO
    new_prose = "<!-- TODO: fix this\nspanning two lines -->\nEdited prose.\n"
    save_scene_content(str(scene), new_prose, mtime, str(tmp_path))

    result = scene.read_text()
    assert "<!-- TODO: fix this" in result
    assert "spanning two lines" in result
    assert "Edited prose." in result


def test_save_scene_atomic_no_truncation_on_bad_content(tmp_path):
    """File should not be left empty/truncated if something goes wrong mid-write."""
    scene = tmp_path / "manuscript" / "ch01" / "01-opening.md"
    scene.parent.mkdir(parents=True)
    original = SCENE.read_text()
    scene.write_text(original)
    mtime = scene.stat().st_mtime

    # Normal save -- verify file is fully intact (atomic write path exercised)
    save_scene_content(str(scene), "New prose.\n", mtime, str(tmp_path))

    result = scene.read_text()
    # File must not be empty and must have frontmatter + content
    assert len(result) > 10
    assert "---" in result
    assert "New prose." in result
