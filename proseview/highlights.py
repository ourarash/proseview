"""Structured highlight passes for scene prose.

The shared spine that the M4 milestone introduces. Each pass takes the
paragraph blocks of a scene (frontmatter already stripped) and returns a
list of :class:`HighlightInstance` records the dashboard renderer can apply
without re-running any regex in the browser.

Nine passes ship in v1, mirroring the contract in
``visualization/plan/implementation-plan.md``:

    passive_voice, filter_verbs, crutch_words, hyperbole,
    lyrical, sensory, sentence_starts, repeats, first_person

A pass may legitimately return an empty list (e.g. ``crutch_words`` on a
scene with no crutch hits, or any pass whose wordlist has been emptied).
The schema stays stable so the renderer never needs to special-case
absence.

Example:
    >>> compute_scene_highlights("She felt the cold wind. I knew it.")
    {'paragraphs': ['She felt the cold wind. I knew it.'], 'highlights': {...}}
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .lexical import (
    CRUTCH_WORDS,
    FILTER_VERBS,
    FIRST_PERSON_RE,
    HYPERBOLE_WORDS,
    LYRICAL_MARKERS,
    SENSORY_WORDS,
    passive_spans,
)

PASS_NAMES: tuple[str, ...] = (
    "passive_voice",
    "filter_verbs",
    "crutch_words",
    "hyperbole",
    "lyrical",
    "sensory",
    "sentence_starts",
    "repeats",
    "first_person",
)


@dataclass(frozen=True)
class HighlightInstance:
    """One match produced by a highlight pass.

    ``char_offsets`` are into the corresponding entry of the scene's
    ``paragraphs`` array, never into the full scene text. ``note`` carries
    a sub-category label when a pass cares to distinguish (e.g. the sensory
    pass tags each match with the sensory category).
    """

    paragraph_index: int
    char_offsets: tuple[int, int]
    text: str
    note: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "paragraph_index": self.paragraph_index,
            "char_offsets": [self.char_offsets[0], self.char_offsets[1]],
            "text": self.text,
            "note": self.note,
        }


_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_REPEAT_TERM_RE = re.compile(r"^(.+)x\d+$")


def split_paragraphs(text: str) -> list[str]:
    """Split scene text into the paragraph blocks the renderer iterates.

    Mirrors the simple blank-line split used throughout proseview. Headings
    and list items keep their leading markers; the renderer handles them
    through ``marked.parse`` block-level rendering.
    """
    return [block.strip() for block in _PARAGRAPH_SPLIT_RE.split(text) if block.strip()]


def strip_markdown_for_offsets(text: str) -> str:
    """Remove markdown syntax to match ProseMirror's plain text content."""
    # Block markers
    text = re.sub(r'^#{1,6}\s+', '', text)
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-*+]\s+', '', text)
    text = re.sub(r'^\d+\.\s+', '', text)
    
    # Inline formatting. An image shows no text, so its alt text is not prose.
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '￼', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    return text


# Opening and closing marks of speech. A curly single quote opens only after a
# space or a dash, and closes only before a non-letter, so "don’t" stays prose.
_DIALOGUE_RE = re.compile(
    r'"[^"]*(?:"|$)|\u201c[^\u201d]*(?:\u201d|$)'
    r"|(?:(?<=^)|(?<=[\s\u2014(]))\u2018.*?(?:\u2019(?![A-Za-z])|$)",
    re.DOTALL,
)


def dialogue_spans(paragraph: str) -> list[tuple[int, int]]:
    """Character spans of ``paragraph`` that are speech, quotes included.

    Speech running on into the next paragraph has no closing mark, as is the
    convention, so an unclosed quote runs to the end of its paragraph.
    """
    return [m.span() for m in _DIALOGUE_RE.finditer(paragraph)]


def _in_spans(start: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= start < b for a, b in spans)


def _word_list_pass(
    paragraphs: list[str],
    words: Iterable[str],
    *,
    note: str | None = None,
    narration_only: bool = False,
) -> list[HighlightInstance]:
    out: list[HighlightInstance] = []
    word_list = [w for w in words if w]
    if not word_list:
        return out
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(w) for w in word_list) + r")\b",
        re.IGNORECASE,
    )
    for idx, para in enumerate(paragraphs):
        speech = dialogue_spans(para) if narration_only else []
        for match in pattern.finditer(para):
            if speech and _in_spans(match.start(), speech):
                continue
            out.append(HighlightInstance(idx, (match.start(), match.end()),
                                         match.group(0), note))
    return out


def passive_voice_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    out: list[HighlightInstance] = []
    for idx, para in enumerate(paragraphs):
        for start, end in passive_spans(para):
            out.append(HighlightInstance(idx, (start, end), para[start:end]))
    return out


def filter_verbs_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    return _word_list_pass(paragraphs, FILTER_VERBS)


# Crutch words, absolutes and "I" are how people talk, so in dialogue they are
# the character's voice, not the writer's habit. These passes read narration.
def crutch_words_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    return _word_list_pass(paragraphs, CRUTCH_WORDS, narration_only=True)


def hyperbole_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    return _word_list_pass(paragraphs, HYPERBOLE_WORDS, narration_only=True)


def lyrical_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    return _word_list_pass(paragraphs, LYRICAL_MARKERS)


def sensory_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    out: list[HighlightInstance] = []
    for category, words in SENSORY_WORDS.items():
        out.extend(_word_list_pass(paragraphs, words, note=category))
    out.sort(key=lambda h: (h.paragraph_index, h.char_offsets[0], h.char_offsets[1]))
    return out


# A sentence ends at . ! ? or an ellipsis, with any closing quote or bracket.
_SENTENCE_END_RE = re.compile(r"[.!?\u2026]+[\"'\u201d\u2019)\]]*\s+")
# A sentence's first word, past any opening quote, bracket or dash.
_FIRST_WORD_RE = re.compile(r"[\s\"'\u201c\u2018(\[\u2014*_-]*([A-Za-z]+(?:['\u2019][A-Za-z]+)?)")
SENTENCE_START_RUN = 3
SENTENCE_START_MIN_WORDS = 2


def sentence_starts_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    """Mark runs of three or more sentences in a row that open on the same word.

    "She… She… She…" is a pattern a reader hears long before they could name
    it. A run carries on across a paragraph break, since the ear does too.
    Each marked word's note is the run's length.
    """
    starts: list[tuple[int, int, int, str]] = []
    for idx, para in enumerate(paragraphs):
        pos = 0
        for end in [m.end() for m in _SENTENCE_END_RE.finditer(para)] + [len(para)]:
            m = _FIRST_WORD_RE.match(para, pos)
            # A one-word cry ("Wow! wow! wow!") is not an opening.
            if m and m.start(1) < end and len(para[pos:end].split()) >= SENTENCE_START_MIN_WORDS:
                starts.append((idx, m.start(1), m.end(1), m.group(1)))
            pos = end
    out: list[HighlightInstance] = []
    i = 0
    while i < len(starts):
        j = i
        while j + 1 < len(starts) and starts[j + 1][3].lower() == starts[i][3].lower():
            j += 1
        run = j - i + 1
        if run >= SENTENCE_START_RUN:
            for idx, start, end, word in starts[i:j + 1]:
                out.append(HighlightInstance(idx, (start, end), word, str(run)))
        i = j + 1
    return out


def repeats_pass(paragraphs: list[str], repeat_terms: Iterable[str]) -> list[HighlightInstance]:
    """Highlight occurrences of the scene's most-repeated content words.

    ``repeat_terms`` accepts bare words (``"patel"``), the ``"word"+"x"+count``
    shape, or slash-joined variant groups (``"deactivate/deactivationx7"``) that
    the stemming-aware ``top_repeated_content_words`` produces. All surface forms
    in a group are highlighted with the group's total count as the note.
    """
    word_to_group: dict[str, str] = {}
    group_scene_count: dict[str, str] = {}
    
    for term in repeat_terms:
        if not term:
            continue
        m = _REPEAT_TERM_RE.match(term)
        raw = m.group(1) if m else term
        count_m = re.search(r"x(\d+)$", term)
        note = count_m.group(1) if count_m else ""
        group_scene_count[raw] = note
        for w in raw.split("/"):
            word_to_group[w.lower()] = raw

    if not word_to_group:
        return []

    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(w) for w in word_to_group) + r")\b",
        re.IGNORECASE,
    )
    out: list[HighlightInstance] = []
    for idx, para in enumerate(paragraphs):
        matches = list(pattern.finditer(para))
        
        group_para_count = {}
        for match in matches:
            w_lower = match.group(0).lower()
            grp = word_to_group.get(w_lower)
            if grp:
                group_para_count[grp] = group_para_count.get(grp, 0) + 1
                
        for match in matches:
            w_lower = match.group(0).lower()
            grp = word_to_group.get(w_lower)
            if grp:
                p_c = group_para_count[grp]
                s_c = group_scene_count.get(grp, "")
                note = f"{p_c}/{s_c}" if s_c else str(p_c)
                out.append(HighlightInstance(idx, (match.start(), match.end()), match.group(0), note))
    return out


# A scene whose narration says "I" this often is told in first person, where
# marking every pronoun says nothing. Long enough not to judge a fragment.
FIRST_PERSON_SCENE_PER_1K = 20.0
FIRST_PERSON_SCENE_MIN_WORDS = 150


def is_first_person_pov(pov: object) -> bool:
    """Whether a scene's ``pov:`` frontmatter names first person ("first", "1st")."""
    return bool(re.search(r"\b(?:first|1st)\b", str(pov or ""), re.IGNORECASE))


def first_person_pass(paragraphs: list[str], *, pov: object = "") -> list[HighlightInstance]:
    """First-person pronouns in the narration of a scene not told in first person.

    "I" in speech is just a character talking. In third-person narration it
    is a slip into the character's voice, which is what this pass is for.
    A scene whose ``pov:`` says first person, or whose narration plainly is,
    gets no marks: there every "I" is meant.
    """
    if is_first_person_pov(pov):
        return []
    out: list[HighlightInstance] = []
    narration_words = 0
    for idx, para in enumerate(paragraphs):
        speech = dialogue_spans(para)
        narration = "".join(ch for k, ch in enumerate(para) if not _in_spans(k, speech)) if speech else para
        narration_words += len(narration.split())
        for match in FIRST_PERSON_RE.finditer(para):
            if speech and _in_spans(match.start(), speech):
                continue
            out.append(HighlightInstance(idx, (match.start(), match.end()),
                                         match.group(0)))
    if (narration_words >= FIRST_PERSON_SCENE_MIN_WORDS
            and len(out) * 1000 / narration_words >= FIRST_PERSON_SCENE_PER_1K):
        return []
    return out


def compute_scene_highlights(
    text: str,
    *,
    repeat_terms: Iterable[str] = (),
    pov: object = "",
) -> dict[str, object]:
    """Return the scene highlight payload embedded in the dashboard JSON.

    ``text`` is the scene body with frontmatter already stripped (matches
    ``SceneStats.text``). ``repeat_terms`` wires the repeats pass to the
    scene's own top-repeated words; pass ``SceneStats.repetition_examples``.
    ``pov`` is the scene's ``pov:`` frontmatter, which turns the first-person
    pass off for a scene told in first person.
    """
    paragraphs = split_paragraphs(text)
    # A NOTE/TODO comment is a block the editor shows as a note, not prose,
    # so no pass marks it.
    plain_paragraphs = ["" if p.startswith("<!--") else strip_markdown_for_offsets(p)
                        for p in paragraphs]
    
    return {
        "paragraphs": paragraphs,
        "highlights": {
            "passive_voice": [h.to_dict() for h in passive_voice_pass(plain_paragraphs)],
            "filter_verbs": [h.to_dict() for h in filter_verbs_pass(plain_paragraphs)],
            "crutch_words": [h.to_dict() for h in crutch_words_pass(plain_paragraphs)],
            "hyperbole": [h.to_dict() for h in hyperbole_pass(plain_paragraphs)],
            "lyrical": [h.to_dict() for h in lyrical_pass(plain_paragraphs)],
            "sensory": [h.to_dict() for h in sensory_pass(plain_paragraphs)],
            "sentence_starts": [h.to_dict() for h in sentence_starts_pass(plain_paragraphs)],
            "repeats": [h.to_dict() for h in repeats_pass(plain_paragraphs, repeat_terms)],
            "first_person": [h.to_dict() for h in first_person_pass(plain_paragraphs, pov=pov)],
        },
    }

