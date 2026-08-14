"""Tests for :mod:`proseview.story`.

Covers:
- the shape layer works with no story fields at all
- threads and days are read through the configured field names
- a counting-down manuscript is not sorted backwards
- reading order and story order diverge only where the writer moved a scene
- every layer reports itself unavailable instead of guessing
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config, StoryConfig  # noqa: E402
from proseview.scenes import collect_scene_stats  # noqa: E402
from proseview.story import (  # noqa: E402
    MAX_THREADS,
    build_story_model,
    story_payload,
    untagged_summary,
)


def _write(root: Path, chapter: str, name: str, *, fm: str = "", body: str = "Words here.") -> None:
    d = root / "manuscript" / chapter
    d.mkdir(parents=True, exist_ok=True)
    front = f"---\n{fm}---\n\n" if fm else ""
    (d / name).write_text(f"{front}{body}\n", encoding="utf-8")


def _model(root: Path, cfg: Config | None = None):
    cfg = cfg or Config()
    return build_story_model(collect_scene_stats(root, cfg), cfg)


def test_shape_works_with_no_story_fields(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", body="One two three four five.")
    _write(tmp_path, "ch01", "02-b.md", body="Six seven.")
    _write(tmp_path, "ch02", "01-c.md", body="Eight nine ten.")

    model = _model(tmp_path)

    assert [s.words for s in model.scenes] == [5, 2, 3]
    assert model.total_words == 10
    assert [(b.chapter, b.scenes) for b in model.bands] == [("ch01", 2), ("ch02", 1)]
    # The layers that need writer input stay off rather than guessing.
    assert model.has_threads is False
    assert model.has_chronology is False
    assert model.chronological() == []


def test_threads_and_days_are_read_through_configured_field_names(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm="timeline: current\ncountdown: 99\n")
    _write(tmp_path, "ch01", "02-b.md", fm="timeline: past\ncountdown: 98\n")

    default = _model(tmp_path)
    assert default.has_threads is False, "default names must not pick up a foreign convention"

    cfg = replace(Config(), story=StoryConfig(thread_field="timeline", day_field="countdown"))
    mapped = _model(tmp_path, cfg)
    assert mapped.threads == ["current", "past"]
    assert [s.day for s in mapped.scenes] == [99, 98]


def test_day_tolerates_prose_and_rejects_nonsense(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm='day: "Day 93"\n')
    _write(tmp_path, "ch01", "02-b.md", fm="day: 7\n")
    _write(tmp_path, "ch01", "03-c.md", fm="day: someday\n")
    _write(tmp_path, "ch01", "04-d.md", fm="day: true\n")

    days = [s.day for s in _model(tmp_path).scenes]

    assert days == [93, 7, None, None]


def test_a_counting_down_manuscript_is_not_sorted_backwards(tmp_path: Path):
    for i, day in enumerate([99, 98, 97, 96], start=1):
        _write(tmp_path, "ch01", f"0{i}-s.md", fm=f"day: {day}\n")

    model = _model(tmp_path)

    assert model.descending_days is True
    # Story order equals reading order: a countdown told in order.
    assert [s.day for s in model.chronological()] == [99, 98, 97, 96]
    assert [reading - story for _, reading, story in model.crossings()] == [0, 0, 0, 0]


def test_ascending_days_sort_forwards(tmp_path: Path):
    for i, day in enumerate([1, 2, 3], start=1):
        _write(tmp_path, "ch01", f"0{i}-s.md", fm=f"day: {day}\n")

    model = _model(tmp_path)

    assert model.descending_days is False
    assert [s.day for s in model.chronological()] == [1, 2, 3]


def test_a_scene_read_out_of_order_shows_as_a_crossing(tmp_path: Path):
    # Told 1, 3, 2 — the middle event is revealed last.
    for i, day in enumerate([1, 3, 2], start=1):
        _write(tmp_path, "ch01", f"0{i}-s.md", fm=f"day: {day}\n")

    model = _model(tmp_path)
    moved = {s.day: (reading, story) for s, reading, story in model.crossings()}

    assert moved[1] == (0, 0)
    assert moved[3] == (1, 2), "day 3 is read second but happens last"
    assert moved[2] == (2, 1), "day 2 is read last but happens second"


def test_scenes_sharing_a_day_keep_reading_order(tmp_path: Path):
    for i in range(1, 4):
        _write(tmp_path, "ch01", f"0{i}-s.md", fm="day: 93\n")

    model = _model(tmp_path)

    assert [s.index for s in model.chronological()] == [0, 1, 2]


def test_one_dated_scene_is_not_a_chronology(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm="day: 4\n")
    _write(tmp_path, "ch01", "02-b.md")

    assert _model(tmp_path).has_chronology is False


def test_threads_past_the_cap_fold_into_other(tmp_path: Path):
    for i in range(MAX_THREADS + 3):
        _write(tmp_path, "ch01", f"{i:02d}-s.md", fm=f"thread: t{i}\n")

    model = _model(tmp_path)

    assert len(model.threads) == MAX_THREADS + 1
    assert model.threads[-1] == "other"
    assert sum(1 for s in model.scenes if s.thread == "other") == 3


def test_chapter_bands_carry_their_day_span(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm="day: 99\n")
    _write(tmp_path, "ch01", "02-b.md", fm="day: 94\n")
    _write(tmp_path, "ch02", "01-c.md")

    bands = _model(tmp_path).bands

    assert bands[0].day_span == "day 99 → 94"
    assert bands[1].day_span == "", "a chapter with no days claims no span"


def test_payload_is_json_safe_and_reports_what_is_missing(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm="thread: present\nday: 2\nwhen: Tuesday\nwhere: The pier\n")
    _write(tmp_path, "ch01", "02-b.md")

    import json

    cfg = Config()
    payload = story_payload(collect_scene_stats(tmp_path, cfg), cfg)
    json.dumps(payload)

    assert payload["threads"] == ["present"]
    assert payload["has_chronology"] is False
    assert payload["scenes"][0]["when"] == "Tuesday"
    assert payload["scenes"][0]["where"] == "The pier"
    assert payload["scenes"][1]["thread"] == ""
    assert payload["thread_field"] == "thread" and payload["day_field"] == "day"


def test_hover_blurb_prefers_summary_then_falls_back_to_the_arc(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm=(
        "summary: Rena counts the till and finds it short.\n"
        "goal: Balance the books\nconflict: The safe is stuck\noutcome: She gives up\n"))
    _write(tmp_path, "ch01", "02-b.md", fm=(
        "goal: Balance the books\nconflict: The safe is stuck\noutcome: She gives up\n"))
    _write(tmp_path, "ch01", "03-c.md")

    scenes = _model(tmp_path).scenes

    assert scenes[0].blurb == "Rena counts the till and finds it short."
    # No summary: the arc fields carry the hover instead, which is what most
    # manuscripts actually fill in.
    assert scenes[1].blurb == "Balance the books · The safe is stuck · She gives up"
    assert scenes[2].blurb == ""


def test_payload_carries_the_blurb(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm="summary: A short scene.\n")

    cfg = Config()
    payload = story_payload(collect_scene_stats(tmp_path, cfg), cfg)

    assert payload["scenes"][0]["blurb"] == "A short scene."
    assert payload["scenes"][0]["summary"] == "A short scene."


def test_untagged_summary_counts_both_fields(tmp_path: Path):
    _write(tmp_path, "ch01", "01-a.md", fm="thread: present\nday: 1\n")
    _write(tmp_path, "ch01", "02-b.md", fm="thread: past\n")
    _write(tmp_path, "ch01", "03-c.md")

    assert untagged_summary(_model(tmp_path)) == "2/3 scenes have a thread · 1/3 have a day"


def test_empty_manuscript_does_not_crash(tmp_path: Path):
    (tmp_path / "manuscript").mkdir()

    model = _model(tmp_path)

    assert model.scenes == [] and model.bands == []
    assert untagged_summary(model) == "No scenes found."
