"""Goals panel computations derived from the history rows.

Three metrics, per the Milestone 2 plan:
    - rolling seven-day velocity (avg words/day)
    - consecutive writing-day streak (counting today if the working tree has
      added words since the last commit)
    - per-chapter target vs current (``target_words / chapter_count``)

Everything here is pure: feed it history rows and a ``WorkingCopyDelta``, get
a :class:`Goals` back. That keeps the live banner cheap on a warm cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .config import Config
from .history import HistoryRow, WorkingCopyDelta


@dataclass(frozen=True)
class Goals:
    rolling_velocity: float
    streak_days: int
    per_chapter_target: int
    per_chapter_current: int
    words_added_today: int
    scenes_touched_today: int
    head_total_words: int
    head_chapter_count: int


def compute_goals(history: list[HistoryRow], cfg: Config,
                  delta: WorkingCopyDelta) -> Goals:
    velocity = rolling_velocity(history, delta)
    streak = writing_day_streak(history, delta)
    latest = history[-1] if history else None
    total = latest.total_words if latest else 0
    chapters = latest.chapter_count if latest and latest.chapter_count > 0 else 0
    if chapters > 0:
        per_chapter_target = cfg.target_words // chapters
        per_chapter_current = total // chapters
    else:
        per_chapter_target = 0
        per_chapter_current = 0
    return Goals(
        rolling_velocity=velocity,
        streak_days=streak,
        per_chapter_target=per_chapter_target,
        per_chapter_current=per_chapter_current,
        words_added_today=delta.words_added_today,
        scenes_touched_today=delta.scenes_touched_today,
        head_total_words=total,
        head_chapter_count=chapters,
    )


def rolling_velocity(history: list[HistoryRow], delta: WorkingCopyDelta,
                     days: int = 7) -> float:
    """Average words-per-day over the last ``days`` calendar days.

    Uses last-commit-of-day totals as day anchors, plus the working tree as
    today's anchor when the writer has added words since the last commit.
    Falls back to 0.0 when there is no baseline to diff against.
    """
    if not history and delta.words_added_today <= 0:
        return 0.0

    by_day_total = _last_total_by_day(history)
    today = date.today()
    today_iso = today.isoformat()

    # Inject a synthetic "today" anchor from the working tree when relevant.
    today_total = by_day_total.get(today_iso)
    if history:
        last_known_total = history[-1].total_words + delta.words_added_today
        by_day_total[today_iso] = last_known_total
    elif delta.words_added_today > 0:
        by_day_total[today_iso] = delta.words_added_today

    cutoff = (today - timedelta(days=days)).isoformat()
    in_window = sorted((d, t) for d, t in by_day_total.items() if d >= cutoff)
    if len(in_window) < 2:
        return 0.0
    delta_words = in_window[-1][1] - in_window[0][1]
    return max(0.0, delta_words / days)


def writing_day_streak(history: list[HistoryRow],
                       delta: WorkingCopyDelta) -> int:
    """Consecutive calendar days ending today (or yesterday) with positive
    word deltas.

    A day counts when either (a) a commit that day increased ``total_words``
    above the previous committed total, or (b) the working tree itself has
    added words today. The walk stops at the first gap.
    """
    positive_days = _positive_delta_days(history)
    today = date.today()
    streak = 0
    if delta.words_added_today > 0:
        streak += 1
    # Walk back from yesterday. Today in committed history is rare (most
    # writers aren't committing mid-session), so yesterday is the right
    # starting point regardless of whether the working tree has adds.
    check = today - timedelta(days=1)
    while check.isoformat() in positive_days:
        streak += 1
        check -= timedelta(days=1)
    return streak


def _last_total_by_day(history: list[HistoryRow]) -> dict[str, int]:
    by_day: dict[str, int] = {}
    for row in sorted(history, key=lambda r: r.committed_at):
        by_day[row.committed_at[:10]] = row.total_words
    return by_day


def _positive_delta_days(history: list[HistoryRow]) -> set[str]:
    sorted_hist = sorted(history, key=lambda r: r.committed_at)
    positive: set[str] = set()
    prev_total = 0
    # Last-of-day totals drive the signal, matching the velocity anchor choice.
    last_of_day: dict[str, int] = {}
    for row in sorted_hist:
        last_of_day[row.committed_at[:10]] = row.total_words
    for d in sorted(last_of_day):
        if last_of_day[d] > prev_total:
            positive.add(d)
        prev_total = last_of_day[d]
    return positive
