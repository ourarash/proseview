"""Generate a full-length manuscript for the scaling tier.

``fixtures/demo-repo`` is four scenes. That is the right size for asserting on
exact content, and the wrong size for finding the bugs that only appear at book
length: chart rendering with hundreds of points, search ranking across a real
corpus, scene-table sorting, Timeline lanes, and the O(n^2) analytics that look
free at four scenes.

Nothing here is committed as text. The book is synthesised into a temp
directory, deterministically seeded so a failure reproduces exactly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

#: Shape of the generated book. Roughly a 90k-word literary novel.
CHAPTERS = 30
SCENES_PER_CHAPTER = 10
WORDS_PER_SCENE = 300

CHARACTERS = [
    "Rena", "Lowe", "Patel", "Ade", "Marisol", "Okonkwo",
    "Bex", "Halloran", "Yusuf", "Ines",
]
SETTINGS = [
    "the harbour office", "the back room", "the pier", "the night market",
    "the customs shed", "the ferry deck", "the accountant's flat", "the long quay",
]
THREADS = ["ledger", "harbour", "family", "inquest"]

_SUBJECTS = CHARACTERS + [
    "the ledger", "the pier boy", "the harbour master", "the dockhand",
    "the auditor", "the clerk", "the tide", "the river", "the inspector",
]
_VERBS = [
    "counted", "questioned", "abandoned", "recovered", "measured", "doubted",
    "annotated", "misplaced", "reconciled", "defended", "postponed", "revisited",
    "forgave", "catalogued", "mistrusted", "rehearsed", "unpicked", "conceded",
]
_OBJECTS = [
    "the weekly total", "a column of figures", "the safe's dial", "a torn receipt",
    "the morning delivery", "an unsigned invoice", "the shop's account",
    "a promise from spring", "the last honest number", "a stack of manifests",
    "the inspector's question", "a debt nobody claimed",
]
_CODAS = [
    "and said nothing afterward", "before the kettle boiled", "against her better sense",
    "while the market woke", "with the patience of a creditor", "twice, then once more",
    "as though it were arithmetic", "under a grey and unhelpful sky",
    "long after the office emptied", "without looking up",
]


@dataclass(frozen=True)
class BookStats:
    """What was written, so tests can assert against real numbers."""

    scenes: int
    words: int
    chapters: int
    root: Path


def _scene_body(rng: random.Random, target_words: int) -> str:
    paragraphs: list[str] = []
    words = 0
    while words < target_words:
        sentences = [
            f"{rng.choice(_SUBJECTS)} {rng.choice(_VERBS)} {rng.choice(_OBJECTS)} "
            f"{rng.choice(_CODAS)}."
            for _ in range(rng.randint(3, 6))
        ]
        para = " ".join(sentences)
        paragraphs.append(para)
        words += len(para.split())
    return "\n\n".join(paragraphs)


def build_book(
    root: Path,
    chapters: int = CHAPTERS,
    scenes_per_chapter: int = SCENES_PER_CHAPTER,
    words_per_scene: int = WORDS_PER_SCENE,
    seed: int = 20260815,
) -> BookStats:
    """Write a full manuscript under ``root/manuscript`` and report its shape."""
    rng = random.Random(seed)
    manuscript = root / "manuscript"
    manuscript.mkdir(parents=True, exist_ok=True)

    total_words = 0
    total_scenes = 0
    day = 1

    for chapter in range(1, chapters + 1):
        chapter_dir = manuscript / f"ch{chapter:02d}"
        chapter_dir.mkdir(exist_ok=True)

        for scene_no in range(1, scenes_per_chapter + 1):
            cast = rng.sample(CHARACTERS, rng.randint(1, 3))
            body = _scene_body(rng, words_per_scene)
            # Every fourth scene carries an annotation, so TODO/NOTE scanning has
            # a realistic amount of work rather than none.
            if scene_no % 4 == 0:
                body += f"\n\n<!-- NOTE[continuity]: check ch{chapter:02d} against the ledger -->"
            if scene_no % 7 == 0:
                body += f"\n\n<!-- TODO: tighten the close of scene {scene_no} -->"

            front = [
                "---",
                f"title: Scene {scene_no}",
                f"chapter: Chapter {chapter}",
                f"status: {rng.choice(['draft', 'revised', 'final'])}",
                f"setting: {rng.choice(SETTINGS)}",
                f"thread: {rng.choice(THREADS)}",
                f"day: {day}",
                "characters:",
                *[f"  - {name}" for name in cast],
                "---",
            ]
            text = "\n".join(front) + f"\n\n# Scene {scene_no}\n\n{body}\n"
            (chapter_dir / f"{scene_no:02d}-scene.md").write_text(text, encoding="utf-8")

            total_words += len(body.split())
            total_scenes += 1
            # Chronology drifts forward, occasionally out of reading order so the
            # Timeline has something real to show.
            day += rng.choice([0, 1, 1, 2, -1])

    return BookStats(scenes=total_scenes, words=total_words, chapters=chapters, root=root)
