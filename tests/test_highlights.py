"""Per-pass coverage for the M4 structured highlight spine.

Each pass gets table-driven positives and negatives plus a
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
    compute_scene_highlights,
    ECHO_WINDOW,
    crutch_words_pass,
    dialogue_tags_pass,
    echoes_pass,
    filter_verbs_pass,
    first_person_pass,
    hyperbole_pass,
    lyrical_pass,
    passive_voice_pass,
    repeats_pass,
    sentence_starts_pass,
    sensory_pass,
    split_paragraphs,
    sticky_sentences_pass,
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


def test_passive_voice_pass_skips_predicate_adjectives():
    """"She was tired" is a state, not something done to her.

    The bare "be + participle" shape flagged these, and they are common enough
    in fiction that they dominated the pass -- a writer opening the highlight
    saw mostly false alarms and learned to distrust it.
    """
    paragraphs = [
        "She was tired after the walk.",
        "He was excited about the trip.",
        "They were married for years.",
        "I was scared of the dark.",
        "He was interested in the book.",
    ]
    assert passive_voice_pass(paragraphs) == []


def test_passive_voice_pass_keeps_an_adjectival_participle_with_an_agent():
    """The "by" agent is what separates the two readings."""
    hits = passive_voice_pass(["He was surprised by the noise."])
    assert [h.text.lower() for h in hits] == ["was surprised"]


def test_passive_voice_pass_excludes_the_agent_from_the_span():
    """The highlight covers the construction, not the phrase that follows."""
    hits = passive_voice_pass(["The tree was struck by lightning."])
    assert [h.text for h in hits] == ["was struck"]


def test_passive_voice_pass_catches_irregular_participles():
    """"broken" and "struck" were missing from the participle list, so
    textbook passives went unflagged."""
    paragraphs = [
        "The vase was broken by the cat.",
        "The tree was struck by lightning.",
        "The thief was caught near the gate.",
    ]
    matches = " | ".join(_matched_texts(passive_voice_pass(paragraphs))).lower()
    assert "was broken" in matches
    assert "was struck" in matches
    assert "was caught" in matches


def test_passive_voice_pass_ignores_past_continuous():
    """"was thinking" is tense, not voice."""
    assert passive_voice_pass(["I was thinking about her.", "She was going home."]) == []


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


def test_sentence_starts_pass_marks_a_run_of_three():
    paragraphs = ["She ran. She fell!", "\u201cShe what?\u201d he asked. He left."]
    hits = sentence_starts_pass(paragraphs)
    assert [(h.paragraph_index, h.text, h.note) for h in hits] == [
        (0, "She", "3"), (0, "She", "3"), (1, "She", "3")]


def test_sentence_starts_pass_ignores_a_pair():
    assert sentence_starts_pass(["She ran. She fell. Then the door opened."]) == []


def test_sentence_starts_pass_reads_said_after_speech_as_one_sentence():
    # "she" after a closing quote is not the start of a sentence.
    paragraphs = ['"Wait!" she said. "Stop!" she cried. "Now!" she begged.']
    assert sentence_starts_pass(paragraphs) == []


def test_sentence_starts_pass_does_not_split_after_mr():
    paragraphs = ["Mr. Smith ran. Mr. Jones ran. Mr. Brown ran."]
    hits = sentence_starts_pass(paragraphs)
    assert _matched_texts(hits) == ["Mr", "Mr", "Mr"]


def test_echoes_pass_marks_every_word_of_an_echo_with_its_number():
    paragraphs = ["She walked to the gate and stopped. Then she was walking again. She walks home."]
    hits = echoes_pass(paragraphs)
    assert _matched_texts(hits) == ["walked", "walking", "walks"]
    assert {h.note for h in hits} == {"a \u00b7 walked \u2026 walking \u2026 walks"}


def test_echoes_pass_numbers_separate_echoes_in_order():
    hits = echoes_pass(["The lantern swung. The cart creaked. Someone lit the lantern. The cart stopped."])
    assert [(h.text, h.note.split(" \u00b7 ")[0]) for h in hits] == [
        ("lantern", "a"), ("cart", "b"), ("lantern", "a"), ("cart", "b")]
    from proseview.highlights import echo_count
    assert echo_count(hits) == 2


def test_echoes_pass_runs_across_paragraph_breaks():
    hits = echoes_pass(["The lantern swung.", "Someone lit the lantern."])
    assert [(h.paragraph_index, h.text) for h in hits] == [(0, "lantern"), (1, "lantern")]


def test_echoes_pass_window_is_fifty_words():
    filler = " ".join(["and"] * (ECHO_WINDOW - 1))
    assert _matched_texts(echoes_pass([f"lantern {filler} lantern"])) == ["lantern", "lantern"]
    assert echoes_pass([f"lantern {filler} and lantern"]) == []
    # A third within 50 words of the second joins the same echo.
    hits = echoes_pass([f"lantern {filler} lantern {filler} lantern"])
    assert len(hits) == 3 and len({h.note for h in hits}) == 1


def test_echoes_pass_skips_character_names():
    paragraphs = ["Mira opened the door. Mira closed it."]
    assert _matched_texts(echoes_pass(paragraphs, stopwords={"mira", "the", "it"})) == []
    assert _matched_texts(echoes_pass(paragraphs, stopwords={"the", "it"})) == ["Mira", "Mira"]


def test_echoes_pass_skips_words_capitalised_mid_sentence():
    # "Babak" mid-sentence is a name; "Lanterns" opening a sentence is not.
    paragraphs = ["She called Babak twice, and Babak came. Lanterns hung there. She lit the lanterns."]
    assert _matched_texts(echoes_pass(paragraphs)) == ["Lanterns", "lanterns"]


def test_echoes_pass_skips_stopwords_everyday_words_and_short_words():
    # "the" is a stopword, "enough" an everyday word, "ox" too short.
    hits = echoes_pass(["The ox had enough of the cat. The ox had enough of the cat."])
    assert _matched_texts(hits) == ["cat", "cat"]


def test_sticky_sentences_pass_marks_a_glue_heavy_sentence():
    sentence = "It was one of those things that she had to do in the end."
    hits = sticky_sentences_pass([sentence + " Rain hammered the tin roof."])
    assert _matched_texts(hits) == [sentence]
    assert hits[0].note == "86% glue words"


def test_sticky_sentences_pass_leaves_short_and_content_rich_sentences():
    paragraphs = [
        "It was one of those that she had.",
        "Rain hammered the corrugated roof while frightened chickens scattered across muddy yards.",
    ]
    assert sticky_sentences_pass(paragraphs) == []


def test_sticky_sentences_pass_skips_a_sentence_inside_dialogue():
    speech = "\u201cIt was one of those things that she had to do in the end.\u201d"
    assert sticky_sentences_pass([speech]) == []
    narration = "It was one of those things that she had to do in the end."
    assert sticky_sentences_pass([speech + " " + narration])[0].text == narration


def _tags(paragraphs: list[str]) -> list[tuple[str, str]]:
    return [(h.text, h.note) for h in dialogue_tags_pass(paragraphs)]


def test_dialogue_tags_pass_marks_a_fancy_verb_after_double_quotes():
    assert _tags(["\u201cGo away,\u201d she cried."]) == [
        ("cried", "Other than said or asked: \u201ccried\u201d")]
    assert _tags(['"Go away," she cried.']) == [("cried", "Other than said or asked: \u201ccried\u201d")]


def test_dialogue_tags_pass_leaves_said_and_asked_alone():
    assert _tags(["\u201cGo,\u201d she said.", "\u201cWhere?\u201d he asked."]) == []


def test_dialogue_tags_pass_marks_an_adverb_after_the_verb_and_speaker():
    assert _tags(["\u2018Who are you?\u2019 said the Caterpillar sternly."]) == [
        ("said the Caterpillar sternly", "Adverb on a dialogue tag: \u201csternly\u201d")]


def test_dialogue_tags_pass_reads_a_tag_before_an_opening_single_quote():
    assert _tags(["Alice replied, rather shyly, \u2018I hardly know, sir.\u2019"]) == [
        ("replied, rather shyly",
         "Other than said or asked: \u201creplied\u201d; Adverb on a dialogue tag: \u201cshyly\u201d")]


def test_dialogue_tags_pass_skips_ly_words_that_are_not_adverbs():
    assert _tags(["\u201cCome,\u201d she said only once."]) == []


def test_dialogue_tags_pass_marks_a_non_speech_verb_only_after_a_comma():
    assert _tags(["\u201cFine,\u201d she smiled."]) == [("smiled", "Not a speech verb: \u201csmiled\u201d")]
    assert _tags(["\u201cFine.\u201d She smiled."]) == []


def test_dialogue_tags_pass_is_not_fooled_by_apostrophes():
    # "didn’t" and "’em" are not quotes, so nothing here is dialogue.
    assert _tags(["She didn\u2019t go, and they\u2019d told \u2019em, she cried."]) == []


def test_dialogue_tags_pass_marks_six_untagged_lines_but_not_five():
    lines = [f"\u201cLine {n}.\u201d" for n in range(6)]
    hits = dialogue_tags_pass(lines + ["He left."])
    assert [(h.paragraph_index, h.text, h.note) for h in hits] == [
        (0, "Line", "6 lines in a row with no tag")]
    assert dialogue_tags_pass(lines[:5]) == []


def test_dialogue_tags_pass_an_action_beat_attributes_its_line():
    lines = [f"\u201cLine {n}.\u201d" for n in range(3)]
    assert dialogue_tags_pass(lines + ["She laughed. \u201cMore.\u201d"] + lines) == []
    assert dialogue_tags_pass(lines + ["\u201cMore.\u201d My father\u2019s voice."] + lines) == []


def test_dialogue_tags_pass_skips_an_ly_word_leading_into_a_purpose():
    assert _tags(["\u201cSure,\u201d I said, mostly to test it."]) == []
    assert _tags(["\u201cSure,\u201d I said quietly to her."])[0][0] == "said quietly"


def test_dialogue_tags_pass_a_tag_or_narration_breaks_the_run():
    lines = [f"\u201cLine {n}.\u201d" for n in range(3)]
    assert dialogue_tags_pass(lines + ["\u201cMore,\u201d she said."] + lines) == []
    assert dialogue_tags_pass(lines + ["He left."] + lines) == []


def test_narration_passes_skip_dialogue():
    paragraphs = ["\u201cI just always know,\u201d she said, just as always."]
    assert [h.text for h in crutch_words_pass(paragraphs)] == ["just"]
    assert [h.text for h in hyperbole_pass(paragraphs)] == ["always"]
    assert first_person_pass(paragraphs) == []


def test_first_person_pass_is_off_in_a_first_person_scene():
    assert first_person_pass(["I opened the door."], pov="first person") == []
    narration = ["I went home and I sat down. " * 40]
    assert first_person_pass(narration) == []
    assert [h.text for h in first_person_pass(["She paused. My god, she thought."])] == ["My"]


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


def test_repeats_pass_groups_every_form_of_a_word():
    hits = repeats_pass(["The block fell. Two blocks stood.", "No block."], ("block/blocksx3",))
    assert [(h.text, h.group) for h in hits] == [("block", "block/blocks"), ("blocks", "block/blocks"), ("block", "block/blocks")]
    assert hits[0].to_dict()["group"] == "block/blocks"
    # Passes without groups keep the dict as it was.
    assert "group" not in first_person_pass(["She paused. My god, she thought."])[0].to_dict()


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
            # Repeats also say which word, in all its forms, a mark is.
            extra = {"group"} if name == "repeats" else set()
            assert set(inst) == {"paragraph_index", "char_offsets", "text", "note"} | extra
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
    assert by_pass["sentence_starts"] == []
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


def test_sentence_lengths_skip_headings_and_notes():
    from proseview.highlights import sentence_lengths

    text = '# Title\n\nMr. Smith left. "Wait!" she said.\n\n<!-- a note -->\n\nOne two three four five six.'
    assert sentence_lengths(text) == [3, 3, 6]


def test_sentence_buckets_put_each_length_in_its_band():
    from proseview.highlights import sentence_buckets

    assert sentence_buckets([1, 5, 6, 10, 11, 20, 21, 30, 31, 40, 41, 99]) == [2, 2, 1, 1, 2, 2, 2]
    assert sentence_buckets([]) == [0] * 7



def test_dialogue_pass_marks_what_the_dialogue_share_counts():
    from proseview.highlights import dialogue_pass

    paragraphs = ["\u201cGo,\u201d she said. \u2018Now.\u2019 He didn\u2019t move.", "No speech here."]
    assert [(h.paragraph_index, h.text) for h in dialogue_pass(paragraphs)] == [
        (0, "\u201cGo,\u201d"), (0, "\u2018Now.\u2019")]


def test_dialogue_tags_mark_a_phrase_doing_an_adverbs_job():
    from proseview.highlights import dialogue_tags

    marks, total = dialogue_tags(['"No. I woke up," she said in a sad little voice.'])
    assert total == 1
    assert [(m.text, m.note) for m in marks] == [
        ("said in a sad little voice", "Describes how it was said: “in a sad little voice”")]
    for line, phrase in (('"Go," he said with a sigh.', "with a sigh"),
                         ('"Fine," she said under her breath.', "under her breath"),
                         ('"Stay," said Amir in a low, flat tone.', "in a low, flat tone")):
        assert phrase in dialogue_tags([line])[0][0].note
    # Only these shapes: not any "in a" or "with a".
    for line in ('"Come," she said in a car.', '"Yes," he said with a knife in his hand.', '"Go," she said.'):
        assert dialogue_tags([line])[0] == []


def test_dialogue_tags_count_every_tag_for_the_adverb_share():
    from proseview.highlights import compute_scene_highlights

    payload = compute_scene_highlights('"A," she said.\n\n"B," he said sternly.\n\nShe left.')
    assert payload["stats"]["dialogue_tags"] == 2



def test_a_scene_told_in_first_person_says_so():
    from proseview.highlights import compute_scene_highlights

    told = compute_scene_highlights("I went home. I slept.", pov="first person")
    assert told["stats"]["told_in_first_person"] is True and told["highlights"]["first_person"] == []
    slip = compute_scene_highlights("She went home. I think she slept.", pov="third")
    assert slip["stats"]["told_in_first_person"] is False and slip["highlights"]["first_person"]



def test_echo_labels_run_past_z():
    from proseview.highlights import _echo_label

    assert [_echo_label(n) for n in (1, 2, 26, 27, 28, 52, 53)] == ["a", "b", "z", "aa", "ab", "az", "ba"]


def test_echoes_number_forms_of_a_word_across_paragraphs_in_reading_order():
    paragraphs = [
        "At first we talked some mornings, then almost every morning. Before long, the day felt "
        "wrong if I hadn't heard her voice by noon. We messaged nonstop the rest of the day: "
        "screenshots, jokes, complaints.",
        "Mornings used to belong to my mother.",
    ]
    hits = echoes_pass(paragraphs)
    groups: dict[str, list[tuple[int, int, str]]] = {}
    for h in hits:
        groups.setdefault(h.note.split(" \u00b7 ")[0], []).append((h.paragraph_index, h.char_offsets[0], h.text))
    # Every word sits in one echo, in reading order, so the page numbers them 1..n.
    assert len(hits) == len({(h.paragraph_index, h.char_offsets[0]) for h in hits})
    by_word = {v[0][2].lower(): v for v in groups.values()}
    assert [w for _, _, w in by_word["mornings"]] == ["mornings", "morning", "Mornings"]
    assert [w for _, _, w in by_word["day"]] == ["day", "day"]
    for members in groups.values():
        assert members == sorted(members)
