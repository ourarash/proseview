"""Structured highlight passes for scene prose.

The shared spine that the M4 milestone introduces. Each pass takes the
paragraph blocks of a scene (frontmatter already stripped) and returns a
list of :class:`HighlightInstance` records the dashboard renderer can apply
without re-running any regex in the browser.

Nine passes ship in v1, mirroring the contract in
``visualization/plan/implementation-plan.md``:

    passive_voice, filter_verbs, crutch_words, hyperbole,
    lyrical, sensory, comedy_beats, repeats, first_person

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
    COMEDY_BEATS,
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
    "comedy_beats",
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
    
    # Inline formatting
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    return text


def _word_list_pass(
    paragraphs: list[str],
    words: Iterable[str],
    *,
    note: str | None = None,
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
        for match in pattern.finditer(para):
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


def crutch_words_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    return _word_list_pass(paragraphs, CRUTCH_WORDS)


def hyperbole_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    return _word_list_pass(paragraphs, HYPERBOLE_WORDS)


def lyrical_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    return _word_list_pass(paragraphs, LYRICAL_MARKERS)


def sensory_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    out: list[HighlightInstance] = []
    for category, words in SENSORY_WORDS.items():
        out.extend(_word_list_pass(paragraphs, words, note=category))
    out.sort(key=lambda h: (h.paragraph_index, h.char_offsets[0], h.char_offsets[1]))
    return out


def comedy_beats_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    out: list[HighlightInstance] = []
    beats = [b for b in COMEDY_BEATS if b]
    if not beats:
        return out
    pattern = re.compile("|".join(re.escape(b) for b in sorted(beats, key=len, reverse=True)))
    for idx, para in enumerate(paragraphs):
        for match in pattern.finditer(para):
            out.append(HighlightInstance(idx, (match.start(), match.end()),
                                         match.group(0)))
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


def first_person_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    out: list[HighlightInstance] = []
    for idx, para in enumerate(paragraphs):
        for match in FIRST_PERSON_RE.finditer(para):
            out.append(HighlightInstance(idx, (match.start(), match.end()),
                                         match.group(0)))
    return out


def compute_scene_highlights(
    text: str,
    *,
    repeat_terms: Iterable[str] = (),
) -> dict[str, object]:
    """Return the scene highlight payload embedded in the dashboard JSON.

    ``text`` is the scene body with frontmatter already stripped (matches
    ``SceneStats.text``). ``repeat_terms`` wires the repeats pass to the
    scene's own top-repeated words; pass ``SceneStats.repetition_examples``.
    """
    paragraphs = split_paragraphs(text)
    plain_paragraphs = [strip_markdown_for_offsets(p) for p in paragraphs]
    
    return {
        "paragraphs": paragraphs,
        "highlights": {
            "passive_voice": [h.to_dict() for h in passive_voice_pass(plain_paragraphs)],
            "filter_verbs": [h.to_dict() for h in filter_verbs_pass(plain_paragraphs)],
            "crutch_words": [h.to_dict() for h in crutch_words_pass(plain_paragraphs)],
            "hyperbole": [h.to_dict() for h in hyperbole_pass(plain_paragraphs)],
            "lyrical": [h.to_dict() for h in lyrical_pass(plain_paragraphs)],
            "sensory": [h.to_dict() for h in sensory_pass(plain_paragraphs)],
            "comedy_beats": [h.to_dict() for h in comedy_beats_pass(plain_paragraphs)],
            "repeats": [h.to_dict() for h in repeats_pass(plain_paragraphs, repeat_terms)],
            "first_person": [h.to_dict() for h in first_person_pass(plain_paragraphs)],
        },
    }

