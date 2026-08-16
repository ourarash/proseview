"""Manuscripts as they actually arrive, not as the fixture imagines them.

Every bug this session was the same shape: correct against our tidy fixture,
wrong against real data. These pin the shapes a stranger's manuscript will have
-- Windows line endings, a byte-order mark, apostrophes and accents in names,
one character's name inside another's, scenes with no frontmatter at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.generator import build_dashboard  # noqa: E402
from proseview.scenes import collect_scene_stats, split_frontmatter  # noqa: E402


def scene(root: Path, name: str, text: str, *, bom: bool = False, crlf: bool = False) -> Path:
    path = root / "manuscript" / "ch01" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if crlf:
        text = text.replace("\n", "\r\n")
    payload = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + payload)
    return path


def test_a_byte_order_mark_does_not_swallow_the_frontmatter(tmp_path: Path):
    """The bug this file was written for.

    A BOM sits before the ``---`` that opens frontmatter, so the block never
    matches: the title silently falls back to the filename and every metadata
    line is counted as prose, inflating word counts and polluting search.
    Word and several Windows editors add one without saying so.
    """
    scene(tmp_path, "01.md",
          "---\ntitle: Byte Order Mark\ncharacters:\n  - Anna\n---\n\n# Byte Order Mark\n\n"
          "The tide went out.\n", bom=True)

    stats = collect_scene_stats(tmp_path, "manuscript")[0]

    assert stats.title == "Byte Order Mark", "frontmatter was lost to the BOM"
    assert stats.frontmatter.get("characters") == ["Anna"]
    assert stats.words == 4, f"metadata leaked into the prose ({stats.words} words)"
    assert "title:" not in stats.text


def test_windows_line_endings_parse(tmp_path: Path):
    scene(tmp_path, "01.md",
          "---\ntitle: Windows Endings\n---\n\n# Windows Endings\n\nAnna counted the boats.\n",
          crlf=True)

    stats = collect_scene_stats(tmp_path, "manuscript")[0]

    assert stats.title == "Windows Endings"
    assert stats.words == 4


def test_apostrophes_and_accents_survive_in_names_and_titles(tmp_path: Path):
    scene(tmp_path, "01.md",
          "---\ntitle: O'Brien and Zoë\ncharacters:\n  - O'Brien\n  - Zoë\n---\n\n"
          "# O'Brien and Zoë\n\nO'Brien watched Zoë cross the quay.\n")

    stats = collect_scene_stats(tmp_path, "manuscript")[0]

    assert stats.title == "O'Brien and Zoë"
    assert stats.frontmatter.get("characters") == ["O'Brien", "Zoë"]


def test_a_name_inside_another_name_is_not_double_counted(tmp_path: Path):
    """"Ann" must not match inside "Anna", or presence counts every mention twice."""
    import re

    scene(tmp_path, "01.md",
          "---\ntitle: Ann and Anna\n---\n\n# Ann and Anna\n\nAnna spoke. Anna spoke again.\n")
    text = collect_scene_stats(tmp_path, "manuscript")[0].text

    assert not re.search(r"\bAnn\b", text), "'Ann' should not match inside 'Anna'"
    assert len(re.findall(r"\bAnna\b", text)) == 2


def test_a_colon_in_a_frontmatter_value_is_kept(tmp_path: Path):
    fm, _ = split_frontmatter(
        "---\ntitle: Chapter 3: The Reckoning\nwhere: The pier, 4:15pm\n---\n\nProse.\n"
    )
    assert fm["title"] == "Chapter 3: The Reckoning"
    assert fm["where"] == "The pier, 4:15pm"


def test_scenes_with_and_without_frontmatter_coexist(tmp_path: Path):
    scene(tmp_path, "01.md", "---\ntitle: Has Metadata\n---\n\n# Has Metadata\n\nProse.\n")
    scene(tmp_path, "02.md", "Just prose, nothing else.\n")

    stats = sorted(collect_scene_stats(tmp_path, "manuscript"), key=lambda s: s.path.name)

    assert stats[0].title == "Has Metadata"
    assert stats[1].title == "02", "a bare file falls back to its filename"


def test_the_dashboard_builds_over_all_of_these_at_once(tmp_path: Path):
    """None of these shapes may raise, whatever else they do."""
    scene(tmp_path, "01.md", "---\ntitle: BOM\n---\n\n# BOM\n\nProse.\n", bom=True)
    scene(tmp_path, "02.md", "---\ntitle: CRLF\n---\n\n# CRLF\n\nProse.\n", crlf=True)
    scene(tmp_path, "03.md", "---\ntitle: Zoë O'Brien\n---\n\n# Zoë O'Brien\n\nProse.\n")
    scene(tmp_path, "04.md", "No frontmatter here.\n")
    scene(tmp_path, "05.md", "---\ntitle: Empty\n---\n")
    scene(tmp_path, "06.md",
          "---\ntitle: " + "A Chapter Title Long Enough To Collide With Its Neighbours" + "\n---\n\nProse.\n")

    html = build_dashboard(tmp_path, Config.load(tmp_path))

    assert html
    assert len(collect_scene_stats(tmp_path, "manuscript")) == 6
