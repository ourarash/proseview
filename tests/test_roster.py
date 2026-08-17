"""Candidate character-roster extraction.

Character Presence and Co-Occurrence read a roster -- ``characters:`` in config
or the files under ``story-bible/characters/`` -- not per-scene frontmatter. A
writer pointing Proseview at an existing manuscript has neither, so both charts
came back empty with nothing to act on.

``proseview roster`` proposes candidates from capitalisation alone. It is a
suggestion a human prunes once, never a detection the tool acts on: the tests
below pin the shape of the suggestion and, most importantly, that nothing is
written to the manuscript.

The prose in these fixtures deliberately reads like prose. An earlier round
used three-word sentences where the name always came first, which hid a real
bug: a protagonist who habitually starts sentences was dropped entirely.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.cli import main  # noqa: E402
from proseview.roster import extract_roster  # noqa: E402


def names(texts, top_n=30):
    return [name for name, _ in extract_roster(texts, top_n=top_n)]


def test_repeated_name_ranks_first():
    text = (
        "The garden belonged to Alice. She followed Alice through the hedge, "
        "and Alice never looked back. Everyone watched Alice go."
    )
    assert extract_roster([text])[0][0] == "Alice"


def test_multi_word_names_stay_together():
    text = "The White Rabbit checked his watch. The White Rabbit hurried on."
    assert "White Rabbit" in names([text])


def test_particle_names_stay_together():
    text = "She bowed to the Queen of Hearts. The Queen of Hearts scowled."
    assert "Queen of Hearts" in names([text])


def test_sentence_initial_word_is_not_a_name():
    # "Suddenly" and "Then" are capitalised only by position, and never appear
    # capitalised mid-sentence, so neither is ever confirmed.
    text = "Suddenly the door opened. Then the room fell quiet. Then it passed."
    assert "Suddenly" not in names([text])
    assert "Then" not in names([text])


def test_a_name_that_always_opens_a_sentence_still_counts_once_confirmed():
    """Sentence-initial mentions are counted for names seen mid-sentence too.

    A protagonist habitually starts sentences. Discarding every
    sentence-initial mention lost them entirely; one mid-sentence appearance
    is enough to confirm the capitalisation means something, after which the
    rest of the mentions count.
    """
    text = (
        "Alice waited. Alice left. Alice returned. "
        "The others had not seen Alice go."
    )
    found = dict(extract_roster([text]))
    assert found.get("Alice") == 4


def test_an_unconfirmed_sentence_initial_word_stays_out():
    """The same rule in reverse: never seen mid-sentence, never counted."""
    text = "Meanwhile the fire died. Meanwhile the wind rose."
    assert "Meanwhile" not in names([text])


def test_contractions_are_not_names():
    text = "He said it plainly. I'm certain of it. I'm going. That's enough."
    found = names([text])
    assert not [n for n in found if n.startswith(("I'", "I’", "That"))]


def test_possessive_folds_into_the_base_name():
    text = (
        "The house belonged to Alice. She fed Alice's cat, and Alice's cat "
        "purred at Alice until the light went."
    )
    found = dict(extract_roster([text]))
    assert "Alice" in found
    assert "Alice's" not in found and "Alice’s" not in found


def test_possessive_strip_does_not_eat_a_trailing_s():
    # A bare rstrip turns "Thoris" into "Thori" and "Mars" into "Mar".
    text = (
        "He bowed to Dejah Thoris, princess of Mars. The court of Mars knew "
        "Dejah Thoris well, and Dejah Thoris knew Mars better."
    )
    found = names([text])
    assert "Dejah Thoris" in found
    assert "Dejah Thori" not in found
    assert "Mar" not in found


def test_pure_title_alone_is_not_a_candidate():
    text = (
        "She greeted Mr. Collins warmly. The room turned to Mr. Collins, and "
        "Mr. Collins bowed to Mr. Collins in the glass."
    )
    found = names([text])
    assert "Mr" not in found
    assert any("Collins" in n for n in found)


def test_role_title_alone_survives_because_fiction_uses_it_as_a_name():
    # "the Queen" is the character in Alice; dropping it as an honorific lost her.
    text = "The Queen shouted. The Queen turned away. She saw the Queen was furious."
    assert "Queen" in names([text])


def test_shorter_name_folds_into_the_dominant_longer_one():
    text = " ".join(["The others let Van Helsing speak."] * 5) + " We saw Van there."
    found = dict(extract_roster([text]))
    assert found.get("Van Helsing", 0) >= 5
    assert "Van" not in found


def test_frontmatter_is_ignored():
    text = (
        "---\ntitle: Reginald Opens\nstatus: drafted\n---\n\n"
        "The door opened for Alice. She let Alice pass, and Alice went in."
    )
    found = names([text])
    assert "Reginald" not in found
    assert "Alice" in found


def test_markdown_emphasis_does_not_split_a_name():
    text = "The *White Rabbit* ran off. The White Rabbit vanished."
    assert "White Rabbit" in names([text])


def test_top_n_is_respected():
    text = " ".join(f"They met Person{i} and Person{i} spoke." for i in range(40))
    assert len(extract_roster([text], top_n=5)) <= 5


def test_empty_input_returns_nothing():
    assert extract_roster([]) == []
    assert extract_roster(["", "   \n\n"]) == []


def test_extraction_recovers_the_demo_book_cast():
    """The five story-bible characters should surface from the prose alone."""
    manuscript = REPO_ROOT / "fixtures" / "demo-book" / "manuscript"
    texts = [p.read_text(encoding="utf-8-sig") for p in sorted(manuscript.rglob("*.md"))]
    found = " | ".join(names(texts)).lower()
    for expected in ("alice", "white rabbit", "hatter", "queen"):
        assert expected in found, f"{expected!r} missing from candidates"


# --- the CLI wrapper -------------------------------------------------------

def test_roster_command_prints_candidates(capsys):
    rc = main(["roster", "--root", str(REPO_ROOT / "fixtures" / "demo-book"), "--top", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Alice" in out
    assert "mentions" in out


def test_roster_command_yaml_mode_is_pasteable(capsys):
    rc = main([
        "roster", "--root", str(REPO_ROOT / "fixtures" / "demo-book"),
        "--top", "3", "--yaml",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("characters:\n")
    assert "  - Alice\n" in out


def test_roster_command_writes_nothing(tmp_path):
    """The whole design rests on this: propose, never write."""
    scene_dir = tmp_path / "manuscript" / "ch01"
    scene_dir.mkdir(parents=True)
    scene = scene_dir / "01.md"
    scene.write_text(
        "The room was cold for Alice. She watched Alice cross it, and Alice "
        "did not look back.\n",
        encoding="utf-8",
    )

    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main(["roster", "--root", str(tmp_path)]) == 0
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    assert before == after


def test_roster_command_reports_an_empty_manuscript(tmp_path, capsys):
    (tmp_path / "manuscript").mkdir()
    rc = main(["roster", "--root", str(tmp_path)])
    assert rc == 1
    assert "no scenes found" in capsys.readouterr().err
