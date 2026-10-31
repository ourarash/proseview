"""Where a sentence ends and what counts as speech.

Average sentence length, dialogue share and the highlight passes all read
these, so a sentence split after "Mr." or speech missed in single quotes
skews every one of them.
"""

from __future__ import annotations

from proseview.lexical import (
    COMMON_STOPWORDS,
    analyze_style_shape,
    dialogue_spans,
    text_dialogue_spans,
    split_sentences,
)


def test_split_sentences_keeps_abbreviations_and_initials_inside_the_sentence():
    text = "Mr. Smith met Dr. Jones on St. Mark's Road. J. R. Tolkien wrote it, e.g. the map, etc. Then they left."
    assert split_sentences(text) == [
        "Mr. Smith met Dr. Jones on St. Mark's Road.",
        "J. R. Tolkien wrote it, e.g. the map, etc. Then they left.",
    ]


def test_split_sentences_still_splits_after_i():
    assert split_sentences("So did I. Then we went home.") == ["So did I.", "Then we went home."]


def test_split_sentences_keeps_a_speech_tag_with_its_speech():
    text = '"Wait!" she said. ‘Stop!’ he cried. “Why?” Nobody answered.'
    assert split_sentences(text) == [
        '"Wait!" she said.',
        "‘Stop!’ he cried.",
        "“Why?”",
        "Nobody answered.",
    ]


def test_split_sentences_continues_past_an_ellipsis_before_a_lowercase_word():
    assert split_sentences("He paused... and then left. She stayed… Nobody spoke.") == [
        "He paused... and then left.",
        "She stayed…",
        "Nobody spoke.",
    ]


def test_dialogue_spans_reads_single_curly_quotes():
    para = "‘I don’t know,’ said Alice, ‘and I don’t care.’"
    assert [para[a:b] for a, b in dialogue_spans(para)] == [
        "‘I don’t know,’",
        "‘and I don’t care.’",
    ]


def test_dialogue_spans_ignores_apostrophes():
    for para in ("She didn’t go.", "Give ’em hell, she thought.",
                 "Leave ‘em be, she thought.", "The dogs’ bowls were empty."):
        assert dialogue_spans(para) == [], para


def test_dialogue_share_counts_single_quoted_speech():
    single = "‘Come here now,’ said Alice. She waited by the door."
    double = "“Come here now,” said Alice. She waited by the door."
    assert analyze_style_shape(single, COMMON_STOPWORDS)["dialogue_pct"] == 30.0
    assert analyze_style_shape(double, COMMON_STOPWORDS)["dialogue_pct"] == 30.0


def test_dialogue_share_is_zero_with_apostrophes_only():
    text = "She didn’t go. They’d left ’em the keys."
    assert analyze_style_shape(text, COMMON_STOPWORDS)["dialogue_pct"] == 0.0


def test_average_sentence_length_is_not_cut_short_by_mr():
    shape = analyze_style_shape("Mr. Smith left early. Mrs. Smith stayed late.", COMMON_STOPWORDS)
    assert shape["avg_sentence_words"] == 4.0


def test_text_dialogue_spans_reads_each_paragraph_on_its_own():
    text = "\u201cStill talking,\n\nShe waited. \u2018Go,\u2019 he said."
    spans = [text[a:b] for a, b in text_dialogue_spans(text)]
    # The open quote runs to its paragraph's end, not into the next one.
    assert spans == ["\u201cStill talking,", "\u2018Go,\u2019"]


# Ari's paragraphs, wrapped over several lines as they are in the book.
WRAPPED_SPEECH = [
    '"Not really, because, in case you forgot, I\'m an art\n'
    'student. I usually work in our studio, but sometimes,\n'
    'when we have reading assignments, I come here."',
    '"My point is, the library has a soul. Think how many\n'
    'students have studied here since the university was\n'
    'founded. How many of them are old now. How\n'
    'many are dead. You should pick a corner here and\n'
    'make it yours. I have my own desk at the studio. It\'s\n'
    'the one by the sink, with the bad light. Nobody\n'
    'wants it. That\'s why it\'s usually free."',
]


def test_wrapped_speech_with_apostrophes_is_all_speech():
    from proseview.highlights import dialogue_pass

    for para in WRAPPED_SPEECH:
        assert [para[a:b] for a, b in dialogue_spans(para)] == [para]
    assert [h.text for h in dialogue_pass(WRAPPED_SPEECH)] == WRAPPED_SPEECH
    text = "\n\n".join(WRAPPED_SPEECH + ["My hand was on her feet under the hoodie."])
    shape = analyze_style_shape(text, COMMON_STOPWORDS)
    assert shape["dialogue_pct"] > 90
