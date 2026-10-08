"""TODOs and notes are comments in the manuscript, not prose.

A writer annotates a scene to remember what to change. Counting those comments
as words made annotating look like writing, and skewed every measure of the
prose -- word totals, reading time, vocabulary, sentence rhythm, goals.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from proseview.config import Config
from proseview.history import iter_manuscript_commits, stats_for_commit
from proseview.lexical import prose_only
from proseview.scenes import collect_scene_stats
from proseview.snapshot import write_snapshot

PROSE = (
    "Mira found the letter under the door at dawn. It was cold and smelled of rain.\n\n"
    "\"Who brought this?\" she asked the empty hall. Nobody answered, and the clock kept "
    "its slow count.\n\n"
    "She read it twice, then once more, very slowly. The handwriting was her mother's, "
    "and her mother had been gone for nine years.\n"
)
ANNOTATED = (
    "Mira found the letter under the door at dawn. It was cold and smelled of rain.\n\n"
    "<!-- TODO: Open on the sound of the letter instead; the dawn image is soft -->\n\n"
    "\"Who brought this?\" she asked the empty hall. Nobody answered, and the clock kept "
    "its slow count. <!-- NOTE[continuity]: The clock stopped in chapter two -->\n\n"
    "She read it twice, then once more, very slowly. The handwriting was her mother's, "
    "and her mother had been gone for nine years.\n"
)

MEASURES = (
    "words", "paragraphs", "headings", "characters", "reading_minutes",
    "lexical_tokens", "lexical_types", "ttr", "mattr", "mtld",
    "avg_sentence_words", "sent_len_stdev", "dialogue_pct", "avg_paragraph_words",
    "short_paragraph_pct", "questions_per_1k", "italics_per_1k", "first_person_per_1k",
    "passive_per_1k", "crutch_per_1k", "sensory_density", "energy_score",
    "repetition_score", "repetition_examples", "top_dialogue_words", "flavor_words",
)


import pytest


@pytest.mark.parametrize(("written", "prose"), [
    ("a\n\n<!-- c -->\n\nb\n", "a\n\nb\n"),
    ("<!-- c -->\n\na\n", "a\n"),
    ("a\n\n<!-- c -->\n", "a\n"),
    ("a <!-- c --> b\n", "a b\n"),
    ("a\n\n<!-- x -->\n\n<!-- y -->\n\nb", "a\n\nb"),
    ("a\n\n<!-- one\n\nspanning two paragraphs -->\n\nb", "a\n\nb"),
    # Two comments never swallow the prose between them.
    ("<!--a--> keep this <!--b-->\n", " keep this\n"),
    ("no comments here\n", "no comments here\n"),
])
def test_prose_is_what_it_would_be_had_the_comment_never_been_written(written: str, prose: str):
    assert prose_only(written) == prose


def _book(root: Path, prose: str) -> Path:
    scene = root / "manuscript" / "ch01" / "01-letter.md"
    scene.parent.mkdir(parents=True)
    scene.write_text("---\ntitle: The Letter\n---\n\n# The Letter\n\n" + prose, encoding="utf-8")
    return root


def test_annotations_change_no_measure_of_the_prose(tmp_path: Path):
    plain = collect_scene_stats(_book(tmp_path / "plain", PROSE), Config())[0]
    annotated = collect_scene_stats(_book(tmp_path / "annotated", ANNOTATED), Config())[0]

    for measure in MEASURES:
        assert getattr(annotated, measure) == getattr(plain, measure), f"{measure} counts the annotations"


def test_the_annotations_themselves_are_still_found_where_they_are(tmp_path: Path):
    root = _book(tmp_path / "annotated", ANNOTATED)
    scene = collect_scene_stats(root, Config())[0]
    lines = (root / "manuscript" / "ch01" / "01-letter.md").read_text(encoding="utf-8").splitlines()

    assert [todo["text"] for todo in scene.todos] == [
        "Open on the sound of the letter instead; the dawn image is soft"
    ]
    assert "TODO: Open on the sound" in lines[scene.todos[0]["line"] - 1]
    assert [note["tag"] for note in scene.notes] == ["continuity"]
    assert "NOTE[continuity]" in lines[scene.notes[0]["line"] - 1]
    # The page shows the scene as written, annotations included.
    assert "<!-- TODO:" in scene.text


def test_goal_history_counts_prose_only(tmp_path: Path):
    """Word counts over the git history feed the goals panel and its streak."""
    root = _book(tmp_path / "book", ANNOTATED)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
    }
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "."], ["git", "commit", "-q", "-m", "seed"]):
        subprocess.run(cmd, cwd=root, check=True, env=env, capture_output=True)

    commit = list(iter_manuscript_commits(root, Config()))[-1]
    plain = collect_scene_stats(_book(tmp_path / "plain", PROSE), Config())[0]
    assert stats_for_commit(root, commit.sha, Config()).total_words == plain.words


def test_a_snapshot_measures_the_same_prose(tmp_path: Path):
    def lexical(prose: str, name: str) -> dict:
        out = tmp_path / f"site-{name}"
        write_snapshot(_book(tmp_path / name, prose), out)
        return json.loads((out / "scene-lexical.json").read_text(encoding="utf-8"))

    assert lexical(ANNOTATED, "annotated") == lexical(PROSE, "plain")
