"""Tests for :mod:`proseview.goals`.

These are pure-function tests: we build synthetic ``HistoryRow`` lists and
``WorkingCopyDelta`` values, then assert velocity/streak/per-chapter math
matches the M2 specification.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config  # noqa: E402
from proseview.goals import (  # noqa: E402
    compute_goals,
    rolling_velocity,
    writing_day_streak,
)
from proseview.history import HistoryRow, WorkingCopyDelta  # noqa: E402


def _row(days_ago: int, total: int, chapters: int = 5,
         scenes: int = 10, sha: str | None = None) -> HistoryRow:
    d = date.today() - timedelta(days=days_ago)
    return HistoryRow(
        sha=sha or f"sha-{days_ago}",
        committed_at=f"{d.isoformat()}T12:00:00-07:00",
        total_words=total,
        scene_count=scenes,
        chapter_count=chapters,
        mattr=0.75, mtld=110.0,
        characters_active=(),
        tool_version="test",
    )


def test_rolling_velocity_averages_recent_deltas():
    history = [_row(7, 10_000), _row(0, 10_700)]
    # 700 words over a 7-day window == 100 words/day.
    v = rolling_velocity(history, WorkingCopyDelta(0, 0))
    assert v == 100.0


def test_rolling_velocity_includes_working_tree_today():
    history = [_row(7, 10_000)]
    # No commits today, but 350 words dirty in the tree.
    v = rolling_velocity(history, WorkingCopyDelta(350, 1))
    assert v == 50.0


def test_rolling_velocity_empty_history_and_no_delta_is_zero():
    assert rolling_velocity([], WorkingCopyDelta(0, 0)) == 0.0


def test_rolling_velocity_single_anchor_is_zero():
    history = [_row(2, 5_000)]
    # Only one anchor in the window and no working-tree delta => no slope.
    assert rolling_velocity(history, WorkingCopyDelta(0, 0)) == 0.0


def test_writing_day_streak_counts_consecutive_positive_days():
    history = [
        _row(5, 1_000),
        _row(4, 1_200),
        _row(3, 1_400),
        _row(2, 1_600),
        _row(1, 1_800),
    ]
    # No words today; streak ends yesterday.
    assert writing_day_streak(history, WorkingCopyDelta(0, 0)) == 5


def test_writing_day_streak_extends_when_working_tree_has_additions():
    history = [_row(2, 1_000), _row(1, 1_200)]
    assert writing_day_streak(history, WorkingCopyDelta(150, 1)) == 3


def test_writing_day_streak_stops_at_first_gap():
    # Missing yesterday breaks the streak; today's WC delta is the only day.
    history = [_row(3, 1_000), _row(2, 1_200)]
    assert writing_day_streak(history, WorkingCopyDelta(50, 1)) == 1


def test_writing_day_streak_is_zero_when_nothing_written():
    assert writing_day_streak([], WorkingCopyDelta(0, 0)) == 0


def test_compute_goals_populates_per_chapter_average():
    history = [_row(0, 20_000, chapters=4)]
    cfg = Config(target_words=80_000)
    goals = compute_goals(history, cfg, WorkingCopyDelta(0, 0))
    assert goals.per_chapter_target == 80_000 // 4
    assert goals.per_chapter_current == 20_000 // 4
    assert goals.head_total_words == 20_000
    assert goals.head_chapter_count == 4


def test_compute_goals_handles_zero_chapter_count():
    history = [_row(0, 0, chapters=0)]
    cfg = Config()
    goals = compute_goals(history, cfg, WorkingCopyDelta(0, 0))
    assert goals.per_chapter_target == 0
    assert goals.per_chapter_current == 0


def test_compute_goals_echoes_working_copy_delta_fields():
    history = [_row(1, 500)]
    cfg = Config()
    goals = compute_goals(history, cfg, WorkingCopyDelta(120, 2))
    assert goals.words_added_today == 120
    assert goals.scenes_touched_today == 2
