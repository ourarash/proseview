"""Goals panel computations derived from the history rows.

Three metrics, per the Milestone 2 plan:
    - rolling seven-day velocity (avg net words/day)
    - consecutive writing-day streak (days the manuscript changed, from
      commits, the day log and scene modification dates)
    - per-chapter target vs current (``target_words / chapter_count``)

Everything here is pure: feed it history rows and a ``WorkingCopyDelta``, get
a :class:`Goals` back. That keeps the live banner cheap on a warm cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .config import Config
from .history import HistoryRow, WorkingCopyDelta
from .ledger import Ledger


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
    baseline_date: str = ""
    ledger: Ledger | None = None
    #: ``(date, total, net, since)`` for each day in the last week with a
    #: known total; *net* is measured from *since*, the day before it that has one.
    recent_days: tuple[tuple[str, int, int, str], ...] = ()


def compute_goals(history: list[HistoryRow], cfg: Config,
                  delta: WorkingCopyDelta, *,
                  total_words: int | None = None,
                  chapter_count: int | None = None) -> Goals:
    """Pass *total_words* and *chapter_count* from the files on disk; without
    them the per-chapter figures fall back to the last commit."""
    velocity = rolling_velocity(history, delta)
    streak = writing_day_streak(history, delta)
    latest = history[-1] if history else None
    total = latest.total_words if latest else 0
    chapters = latest.chapter_count if latest and latest.chapter_count > 0 else 0
    if total_words is not None and chapter_count is not None:
        total, chapters = total_words, max(0, chapter_count)
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
        baseline_date=delta.baseline_date,
        ledger=delta.ledger,
        recent_days=recent_days(history, delta),
    )


def recent_days(history: list[HistoryRow], delta: WorkingCopyDelta,
                days: int = 7) -> tuple[tuple[str, int, int, str], ...]:
    """The last week, a row per day with a known end-of-day total."""
    by_day = _last_total_by_day(history)
    by_day.update(delta.day_totals)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    ordered = sorted(by_day.items())
    rows = []
    for i, (day, total) in enumerate(ordered):
        if day < cutoff or i == 0:
            continue
        since, before = ordered[i - 1]
        rows.append((day, total, total - before, since))
    return tuple(reversed(rows))


def rolling_velocity(history: list[HistoryRow], delta: WorkingCopyDelta,
                     days: int = 7) -> float:
    """Average net words-per-day over the last ``days`` calendar days.

    Uses last-commit-of-day totals as day anchors, overlaid by the day log's
    end-of-day totals, which include today's.
    Negative when more was cut than written. Falls back to 0.0 when there is
    no baseline to diff against.
    """
    if not history and delta.words_added_today <= 0:
        return 0.0

    by_day_total = _last_total_by_day(history)
    # The day log saw the files on disk, so it wins over a commit that day.
    by_day_total.update(delta.day_totals)
    today = date.today()
    today_iso = today.isoformat()

    # Without the day log, inject a synthetic "today" anchor from the working
    # tree when relevant.
    if today_iso not in delta.day_totals:
        if history:
            by_day_total[today_iso] = history[-1].total_words + delta.words_added_today
        elif delta.words_added_today > 0:
            by_day_total[today_iso] = delta.words_added_today

    cutoff = (today - timedelta(days=days)).isoformat()
    in_window = sorted((d, t) for d, t in by_day_total.items() if d >= cutoff)
    if len(in_window) < 2:
        return 0.0
    delta_words = in_window[-1][1] - in_window[0][1]
    # Signed: a week of cutting is a negative, and the ledger says where it went.
    return delta_words / days


def writing_day_streak(history: list[HistoryRow],
                       delta: WorkingCopyDelta) -> int:
    """Consecutive calendar days ending today (or yesterday) on which the
    manuscript changed.

    A day counts when (a) a commit that day increased ``total_words`` above
    the previous committed total, (b) the day log or a scene's modification
    date says a scene was saved that day, or (c) today has words or saved
    scenes. Cutting is work too, so a day of revision keeps the streak. The
    walk stops at the first gap.
    """
    positive_days = _positive_delta_days(history) | set(delta.worked_days)
    today = date.today()
    streak = 0
    if (delta.words_added_today > 0 or delta.scenes_touched_today > 0
            or today.isoformat() in delta.worked_days):
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
