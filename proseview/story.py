"""Story-layer views: the shape of a book, its threads, and its chronology.

Everything here reads frontmatter the writer already maintains. Nothing is
inferred from prose, and nothing is required: a manuscript with no thread or
day fields still produces the shape view, and the views that need those fields
report themselves unavailable rather than guessing or nagging.

Three layers, each needing more from the writer than the last:

``shape``
    Scenes in reading order with their word counts. Always available.
``threads``
    Scenes grouped into named storylines. Needs the thread field.
``chronology``
    Reading order against story order. Needs the day field on 2+ scenes.

The field *names* are configurable (:class:`proseview.config.StoryConfig`) so a
manuscript that already uses its own convention does not have to be rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .scenes import SceneStats

#: Threads render in the order first met in the manuscript, capped so the
#: lane view stays readable. Beyond this the remainder collapses into "other".
MAX_THREADS = 8


@dataclass(frozen=True)
class StoryScene:
    """One scene, reduced to what the story views need."""

    index: int
    path: str
    title: str
    chapter: str
    words: int
    when: str
    where: str
    thread: str
    day: int | None

    @property
    def has_day(self) -> bool:
        return self.day is not None


@dataclass(frozen=True)
class ChapterBand:
    """A run of consecutive scenes sharing a chapter."""

    chapter: str
    start: int
    scenes: int
    words: int
    day_high: int | None = None
    day_low: int | None = None

    @property
    def day_span(self) -> str:
        if self.day_high is None or self.day_low is None:
            return ""
        if self.day_high == self.day_low:
            return f"day {self.day_high}"
        return f"day {self.day_high} → {self.day_low}"


@dataclass(frozen=True)
class StoryModel:
    """Everything the Timeline tab renders, plus what it may not render."""

    scenes: list[StoryScene] = field(default_factory=list)
    bands: list[ChapterBand] = field(default_factory=list)
    threads: list[str] = field(default_factory=list)
    total_words: int = 0

    @property
    def has_threads(self) -> bool:
        return bool(self.threads)

    @property
    def dated(self) -> list[StoryScene]:
        """Scenes carrying a day, in reading order."""
        return [s for s in self.scenes if s.has_day]

    @property
    def has_chronology(self) -> bool:
        # One dated scene cannot disagree with itself about order.
        return len(self.dated) >= 2

    @property
    def descending_days(self) -> bool:
        """True when the manuscript counts down (day 99 → 86) rather than up.

        A countdown is a real convention, and sorting it ascending would invert
        the story order it encodes.
        """
        days = [s.day for s in self.dated if s.day is not None]
        if len(days) < 2:
            return False
        falls = sum(1 for a, b in zip(days, days[1:]) if b < a)
        return falls > len(days) / 2

    def chronological(self) -> list[StoryScene]:
        """Dated scenes in the order events happen.

        Ties keep reading order, so scenes sharing a day stay as written.
        """
        reverse = self.descending_days
        return sorted(
            self.dated,
            key=lambda s: (-s.day if reverse else s.day, s.index),  # type: ignore[operator]
        )

    def crossings(self) -> list[tuple[StoryScene, int, int]]:
        """``(scene, reading position, story position)`` for dated scenes.

        Positions are ranks within the dated subset, which is what the two rows
        of the chronology view are drawn from.
        """
        reading = {s.index: i for i, s in enumerate(self.dated)}
        story = {s.index: i for i, s in enumerate(self.chronological())}
        return [(s, reading[s.index], story[s.index]) for s in self.dated]

    def thread_of(self, scene: StoryScene) -> str:
        return scene.thread


def _coerce_day(value: Any) -> int | None:
    """Read a day number, tolerating ``day: 93`` and ``day: "Day 93"``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def build_story_model(scenes: list[SceneStats], cfg: Config) -> StoryModel:
    """Assemble the story model from already-parsed scene stats."""
    thread_key = cfg.story.thread_field
    day_key = cfg.story.day_field

    rows: list[StoryScene] = []
    for index, scene in enumerate(scenes):
        fm = scene.frontmatter if isinstance(scene.frontmatter, dict) else {}
        thread = str(fm.get(thread_key, "") or "").strip()
        rows.append(
            StoryScene(
                index=index,
                path=str(scene.path),
                title=scene.title,
                chapter=scene.chapter,
                words=scene.words,
                when=str(fm.get("when", "") or "").strip(),
                where=str(fm.get("where", "") or "").strip() or scene.location,
                thread=thread,
                day=_coerce_day(fm.get(day_key)),
            )
        )

    # Threads in first-met order; anything past the cap folds into "other" so
    # the lane view never grows an unbounded number of rows.
    seen: list[str] = []
    for row in rows:
        if row.thread and row.thread not in seen:
            seen.append(row.thread)
    threads = seen[:MAX_THREADS]
    if len(seen) > MAX_THREADS:
        rows = [
            row if (not row.thread or row.thread in threads)
            else StoryScene(**{**row.__dict__, "thread": "other"})
            for row in rows
        ]
        threads = threads + ["other"]

    bands: list[ChapterBand] = []
    for row in rows:
        if bands and bands[-1].chapter == row.chapter:
            prev = bands[-1]
            days = [d for d in (prev.day_high, prev.day_low, row.day) if d is not None]
            bands[-1] = ChapterBand(
                chapter=prev.chapter,
                start=prev.start,
                scenes=prev.scenes + 1,
                words=prev.words + row.words,
                day_high=max(days) if days else None,
                day_low=min(days) if days else None,
            )
        else:
            bands.append(ChapterBand(
                chapter=row.chapter,
                start=row.index,
                scenes=1,
                words=row.words,
                day_high=row.day,
                day_low=row.day,
            ))

    return StoryModel(
        scenes=rows,
        bands=bands,
        threads=threads,
        total_words=sum(row.words for row in rows),
    )


def story_payload(scenes: list[SceneStats], cfg: Config) -> dict[str, Any]:
    """JSON-safe model for the browser."""
    model = build_story_model(scenes, cfg)
    return {
        "scenes": [
            {
                "index": s.index, "path": s.path, "title": s.title, "chapter": s.chapter,
                "words": s.words, "when": s.when, "where": s.where,
                "thread": s.thread, "day": s.day,
            }
            for s in model.scenes
        ],
        "bands": [
            {
                "chapter": b.chapter, "start": b.start, "scenes": b.scenes,
                "words": b.words, "day_span": b.day_span,
            }
            for b in model.bands
        ],
        "threads": model.threads,
        "total_words": model.total_words,
        "has_threads": model.has_threads,
        "has_chronology": model.has_chronology,
        "chronological": [s.index for s in model.chronological()],
        "thread_field": cfg.story.thread_field,
        "day_field": cfg.story.day_field,
    }


def untagged_summary(model: StoryModel) -> str:
    """One line on how much of the manuscript carries story-layer data."""
    total = len(model.scenes)
    if not total:
        return "No scenes found."
    threaded = sum(1 for s in model.scenes if s.thread)
    dated = len(model.dated)
    return f"{threaded}/{total} scenes have a thread · {dated}/{total} have a day"
