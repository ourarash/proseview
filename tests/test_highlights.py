"""Per-pass coverage for the M4 structured highlight spine.

Each of the nine passes gets table-driven positives and negatives plus a
synthetic-scene snapshot that locks down expected output across the whole
schema. Empty-wordlist / empty-input handling is verified once per pass
shape so the renderer can rely on the schema staying stable.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.highlights import (  # noqa: E402
    PASS_NAMES,
    HighlightInstance,
    comedy_beats_pass,
    compute_scene_highlights,
    crutch_words_pass,
    filter_verbs_pass,
    first_person_pass,
    hyperbole_pass,
    lyrical_pass,
    passive_voice_pass,
    repeats_pass,
    sensory_pass,
    split_paragraphs,
)


def _matched_texts(instances: list[HighlightInstance]) -> list[str]:
    return [h.text for h in instances]


def _at(instances: list[HighlightInstance], text: str) -> HighlightInstance | None:
    for inst in instances:
        if inst.text.lower() == text.lower():
            return inst
    return None


def test_split_paragraphs_drops_blank_blocks():
    text = "First paragraph.\n\n  \n\nSecond paragraph.\n\nThird."
    assert split_paragraphs(text) == [
        "First paragraph.",
        "Second paragraph.",
        "Third.",
    ]


def test_passive_voice_pass_positives_and_negatives():
    paragraphs = [
        "The door was opened slowly by the wind.",
        "She opened the door slowly.",
        "The vase had been broken before they arrived.",
    ]
    hits = passive_voice_pass(paragraphs)
    matches = _matched_texts(hits)
    assert any("was opened" in m.lower() for m in matches)
    assert all("she opened" not in m.lower() for m in matches)


def test_filter_verbs_pass_picks_filter_verbs_only():
    paragraphs = ["She felt the cold floor and noticed the silence."]
    hits = filter_verbs_pass(paragraphs)
    texts = {h.text.lower() for h in hits}
    assert "felt" in texts
    assert "noticed" in texts
    assert "cold" not in texts


def test_filter_verbs_pass_negative_when_no_filter_verbs():
    paragraphs = ["The wind moved the curtain."]
    assert filter_verbs_pass(paragraphs) == []


def test_crutch_words_pass_catches_just_very_really():
    paragraphs = ["He was just very tired and really wanted to leave."]
    hits = crutch_words_pass(paragraphs)
    matches = {h.text.lower() for h in hits}
    assert {"just", "very", "really"} <= matches


def test_crutch_words_pass_negative_on_clean_prose():
    paragraphs = ["He was tired and wanted to leave."]
    assert crutch_words_pass(paragraphs) == []


def test_hyperbole_pass_catches_absolutes():
    paragraphs = ["She was always perfect at everything, never wrong."]
    hits = hyperbole_pass(paragraphs)
    matches = {h.text.lower() for h in hits}
    assert {"always", "perfect", "everything", "never"} <= matches


def test_hyperbole_pass_negative_on_measured_prose():
    paragraphs = ["She was good at most things, occasionally wrong."]
    assert hyperbole_pass(paragraphs) == []


def test_lyrical_pass_catches_lyrical_markers():
    paragraphs = ["The light dissolved into shadow as the room transformed."]
    hits = lyrical_pass(paragraphs)
    matches = {h.text.lower() for h in hits}
    assert {"dissolved", "transformed"} <= matches


def test_lyrical_pass_negative_on_plain_prose():
    paragraphs = ["The room went dark."]
    assert lyrical_pass(paragraphs) == []


def test_sensory_pass_tags_category_in_note():
    paragraphs = ["The bitter coffee, the cold tile, the bright neon."]
    hits = sensory_pass(paragraphs)
    by_text = {h.text.lower(): h for h in hits}
    assert by_text["bitter"].note == "taste"
    assert by_text["coffee"].note == "taste"
    assert by_text["cold"].note == "touch"
    assert by_text["bright"].note == "sight"
    assert by_text["neon"].note == "sight"


def test_sensory_pass_negative_on_abstract_prose():
    paragraphs = ["She considered the proposal carefully."]
    assert sensory_pass(paragraphs) == []


def test_comedy_beats_pass_matches_literal_substrings():
    paragraphs = ["He paused... then shouted! Wait, what?!"]
    matches = {h.text for h in comedy_beats_pass(paragraphs)}
    assert "..." in matches
    assert "?!" in matches
    assert "!" in matches


def test_comedy_beats_pass_negative_on_clean_punctuation():
    paragraphs = ["He paused, then continued."]
    assert comedy_beats_pass(paragraphs) == []


def test_repeats_pass_accepts_bare_words_or_wordxN_terms():
    paragraphs = [
        "Patel raised an eyebrow.",
        "Patel said nothing. Patel waited.",
    ]
    hits = repeats_pass(paragraphs, ("patelx3",))
    assert len(hits) == 3
    assert all(h.text.lower() == "patel" for h in hits)

    hits_bare = repeats_pass(paragraphs, ("patel",))
    assert _matched_texts(hits_bare) == _matched_texts(hits)


def test_repeats_pass_negative_when_no_terms_or_no_hits():
    paragraphs = ["Some scene with no repeated terms."]
    assert repeats_pass(paragraphs, ()) == []
    assert repeats_pass(paragraphs, ("missing",)) == []


def test_first_person_pass_catches_pronouns():
    paragraphs = ["I told myself it was fine. My pulse said otherwise."]
    matches = {h.text.lower() for h in first_person_pass(paragraphs)}
    assert {"i", "myself", "my"} <= matches


def test_first_person_pass_negative_on_third_person():
    paragraphs = ["She told herself it was fine."]
    assert first_person_pass(paragraphs) == []


def test_compute_scene_highlights_payload_locks_full_schema():
    text = (
        "I felt the bitter coffee on my tongue.\n\n"
        "The door was opened by the wind, very slowly...\n\n"
        "She always shimmered, perfect and impossible."
    )
    payload = compute_scene_highlights(text, repeat_terms=("doorx2",))

    assert payload["paragraphs"] == [
        "I felt the bitter coffee on my tongue.",
        "The door was opened by the wind, very slowly...",
        "She always shimmered, perfect and impossible.",
    ]

    highlights = payload["highlights"]
    assert set(highlights) == set(PASS_NAMES)

    # Every pass returned a list (possibly empty), and the lists embed the
    # invariant fields the renderer relies on.
    for name in PASS_NAMES:
        for inst in highlights[name]:
            assert set(inst) == {"paragraph_index", "char_offsets", "text", "note"}
            assert isinstance(inst["paragraph_index"], int)
            assert isinstance(inst["char_offsets"], list) and len(inst["char_offsets"]) == 2
            start, end = inst["char_offsets"]
            assert 0 <= start < end
            paragraph = payload["paragraphs"][inst["paragraph_index"]]
            assert paragraph[start:end] == inst["text"]

    # Pass-by-pass sanity: each of the nine passes finds the things this
    # synthetic scene was crafted to trigger.
    by_pass = {name: _matched_texts(
        [HighlightInstance(h["paragraph_index"], tuple(h["char_offsets"]),
                           h["text"], h["note"]) for h in highlights[name]])
        for name in PASS_NAMES}

    assert "felt" in {t.lower() for t in by_pass["filter_verbs"]}
    assert any("was opened" in t.lower() for t in by_pass["passive_voice"])
    assert "very" in {t.lower() for t in by_pass["crutch_words"]}
    assert {"always", "perfect", "impossible"} <= {t.lower() for t in by_pass["hyperbole"]}
    assert "shimmered" in {t.lower() for t in by_pass["lyrical"]}
    assert {"bitter", "coffee", "tongue"} <= {t.lower() for t in by_pass["sensory"]}
    assert "..." in by_pass["comedy_beats"]
    assert {"door"} == {t.lower() for t in by_pass["repeats"]}
    assert {"i", "my"} <= {t.lower() for t in by_pass["first_person"]}


def test_compute_scene_highlights_handles_empty_repeat_terms():
    """Schema invariant: every pass key is present even when its inputs
    are empty. Lets the renderer skip null checks.
    """
    payload = compute_scene_highlights("Plain prose with nothing notable.")
    for name in PASS_NAMES:
        assert name in payload["highlights"]
        assert isinstance(payload["highlights"][name], list)
    assert payload["highlights"]["repeats"] == []


def test_pass_returns_empty_list_when_wordlist_emptied(monkeypatch):
    """Acceptance: removing all wordlists from one pass leaves the schema
    intact: the pass just returns an empty list. Demonstrated with the
    crutch-words pass, which would otherwise fire on the input.
    """
    from proseview import highlights as hl

    monkeypatch.setattr(hl, "CRUTCH_WORDS", set())
    paragraphs = ["He was just very tired."]
    assert hl.crutch_words_pass(paragraphs) == []

    payload = hl.compute_scene_highlights("He was just very tired.")
    assert payload["highlights"]["crutch_words"] == []
    assert set(payload["highlights"]) == set(hl.PASS_NAMES)
