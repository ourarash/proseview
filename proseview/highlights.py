"""Structured highlight passes for scene prose.

The shared spine that the M4 milestone introduces. Each pass takes the
paragraph blocks of a scene (frontmatter already stripped) and returns a
list of :class:`HighlightInstance` records the dashboard renderer can apply
without re-running any regex in the browser.

Nine passes shipped in v1, mirroring the contract in
``visualization/plan/implementation-plan.md``; echoes and sticky_sentences
and dialogue_tags came later:

    passive_voice, filter_verbs, crutch_words, hyperbole,
    lyrical, sensory, sentence_starts, repeats, first_person,
    echoes, sticky_sentences, dialogue_tags, dialogue

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
    COMMON_STOPWORDS,
    CRUTCH_WORDS,
    FILTER_VERBS,
    FIRST_PERSON_RE,
    GLUE_WORDS,
    HYPERBOLE_WORDS,
    KEYWORD_STOPWORDS,
    LEXICAL_WORD_RE,
    LYRICAL_MARKERS,
    NON_SPEECH_TAG_VERBS,
    PLAIN_SPEECH_VERBS,
    SENSORY_WORDS,
    SPEECH_VERBS,
    count_words,
    _stem,
    dialogue_spans,
    passive_spans,
    sentence_spans,
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
    "echoes",
    "sticky_sentences",
    "dialogue_tags",
    "dialogue",
)


@dataclass(frozen=True)
class HighlightInstance:
    """One match produced by a highlight pass.

    ``char_offsets`` are into the corresponding entry of the scene's
    ``paragraphs`` array, never into the full scene text. ``note`` carries
    a sub-category label when a pass cares to distinguish (e.g. the sensory
    pass tags each match with the sensory category). ``group`` ties together
    matches that are one word in different forms (the repeats pass), so the
    page can light them all; it is left out of the dict when unset.
    """

    paragraph_index: int
    char_offsets: tuple[int, int]
    text: str
    note: str | None = None
    group: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "paragraph_index": self.paragraph_index,
            "char_offsets": [self.char_offsets[0], self.char_offsets[1]],
            "text": self.text,
            "note": self.note,
        }
        if self.group is not None:
            out["group"] = self.group
        return out


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
        for pos, end in sentence_spans(para):
            m = _FIRST_WORD_RE.match(para, pos)
            # A one-word cry ("Wow! Wow! Wow!") is not an opening.
            if m and m.start(1) < end and len(para[pos:end].split()) >= SENTENCE_START_MIN_WORDS:
                starts.append((idx, m.start(1), m.end(1), m.group(1)))
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
    in a group are highlighted with the group's total count as the note, and
    the group ("block/blocks") as their ``group``.
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
                out.append(HighlightInstance(idx, (match.start(), match.end()), match.group(0), note, grp.lower()))
    return out


ECHO_WINDOW = 50


def echoes_pass(paragraphs: list[str], stopwords: Iterable[str] = COMMON_STOPWORDS) -> list[HighlightInstance]:
    """Mark the words that come back within :data:`ECHO_WINDOW` words of each other.

    Forms of a word count as the same word (walk, walked, walking), and the
    window runs on across paragraph breaks. Occurrences that follow one
    another within the window form one echo, every one of them marked; echoes
    get an id in the order they start (a, b, … z, aa, ab), and each mark's
    note is "<id> · <the words>" ("a · walked … walking"). The page shows how
    many words the echo has; the id only ties its words together. ``stopwords`` is the
    content stopword set the repeats pass uses, which carries the character
    names; everyday words (:data:`KEYWORD_STOPWORDS`) and words capitalised
    mid-sentence, which are names, are skipped too.
    """
    sw = set(stopwords) | KEYWORD_STOPWORDS
    open_chain: dict[str, list[tuple[int, int, int, int, str]]] = {}
    chains: list[list[tuple[int, int, int, int, str]]] = []
    position = 0
    for idx, para in enumerate(paragraphs):
        # The first word of each sentence, whose capital says nothing.
        starts = set()
        for start, _end in sentence_spans(para):
            first = LEXICAL_WORD_RE.search(para, start)
            if first:
                starts.add(first.start())
        for match in LEXICAL_WORD_RE.finditer(para):
            position += 1
            text = match.group(0)
            word = text.lower()
            if len(word) < 3 or word in sw or "'" in word or "\u2019" in word:
                continue
            if text[0].isupper() and match.start() not in starts:
                continue
            stem = _stem(word)
            entry = (position, idx, match.start(), match.end(), text)
            chain = open_chain.get(stem)
            if chain and position - chain[-1][0] <= ECHO_WINDOW:
                chain.append(entry)
            else:
                chain = [entry]
                open_chain[stem] = chain
                chains.append(chain)
    out: list[HighlightInstance] = []
    number = 0
    for chain in chains:
        if len(chain) < 2:
            continue
        number += 1
        words = " \u2026 ".join(dict.fromkeys(e[4] for e in chain))
        for _pos, idx, start, end, text in chain:
            out.append(HighlightInstance(idx, (start, end), text, f"{_echo_label(number)} \u00b7 {words}"))
    out.sort(key=lambda h: (h.paragraph_index, h.char_offsets[0]))
    return out


def _echo_label(number: int) -> str:
    """1 → a, 26 → z, 27 → aa: the label an echo's words carry."""
    label = ""
    while number:
        number, rest = divmod(number - 1, 26)
        label = chr(ord("a") + rest) + label
    return label


def echo_count(hits: Iterable[object]) -> int:
    """How many echoes a scene has: its groups, not its marks."""
    return len({str(getattr(h, "note", None) or (h.get("note") if isinstance(h, dict) else "")).split(" \u00b7 ")[0]
                for h in hits})


STICKY_MIN_WORDS = 10
STICKY_GLUE_SHARE = 0.60


def sticky_sentences_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    """Mark whole sentences of 10+ words where over 60% are :data:`GLUE_WORDS`.

    A sentence spoken entirely inside quotes is a character's voice and is
    skipped. Each note is the sentence's share of glue words.
    """
    out: list[HighlightInstance] = []
    for idx, para in enumerate(paragraphs):
        speech = dialogue_spans(para)
        for start, end in sentence_spans(para):
            if any(a <= start and end <= b for a, b in speech):
                continue
            words = [w.lower().replace("\u2019", "'") for w in LEXICAL_WORD_RE.findall(para, start, end)]
            if len(words) < STICKY_MIN_WORDS:
                continue
            share = sum(w in GLUE_WORDS for w in words) / len(words)
            if share > STICKY_GLUE_SHARE:
                out.append(HighlightInstance(idx, (start, end), para[start:end],
                                             f"{round(share * 100)}% glue words"))
    return out


def dialogue_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    """Every stretch of speech, quotes included: what the Dialogue % counts.

    The same rule as the measure (:func:`lexical.dialogue_spans`), so the
    tint shows exactly what the percentage is made of.
    """
    return [
        HighlightInstance(idx, (a, b), para[a:b])
        for idx, para in enumerate(paragraphs)
        for a, b in dialogue_spans(para)
        if para[a:b].strip()
    ]


#: The note on each kind of dialogue-tag mark. The scene panel counts the
#: kinds by these labels, so 00-state.js repeats them.
DIALOGUE_TAG_NOTES = {
    "fancy": "Other than said or asked",
    "adverb": "Adverb on a dialogue tag",
    "not_speech": "Not a speech verb",
    "untagged_run": "lines in a row with no tag",
    # Counted with the adverbs: it does the same job as one.
    "manner": "Describes how it was said",
}
DIALOGUE_TAG_WINDOW = 4
UNTAGGED_RUN = 6
# -ly words that are not adverbs of manner.
_NOT_ADVERBS = frozenset({
    "only", "early", "family", "reply", "ugly", "holy", "belly", "rally",
    "ally", "bully", "jolly", "july", "fly", "lily", "emily", "sally",
    "molly", "billy", "kelly", "holly", "polly", "italy", "supply", "apply",
})
# An adverb after the verb, past a named speaker, a comma and a softener:
# "said sternly", "said the Caterpillar sternly", "said, rather shyly".
_ADVERB_AFTER_RE = re.compile(r"(?:\s+(?:the\s+)?[A-Z][A-Za-z]+)?,?\s+"
                              r"(?:(?:rather|very|quite|so|too|almost)\s+)?([A-Za-z]+ly)\b")
_ADVERB_BEFORE_RE = re.compile(r"\b([A-Za-z]+ly)\s+\Z")
# "I said, mostly to test it": after a comma, an -ly word leading into a
# purpose or comparison is about what follows, not about the speaking.
_NOT_MANNER_RE = re.compile(r"\s+(?:to|as\s+if|like)\b")
# A phrase after the verb doing an adverb's job: "said in a sad little voice",
# "with a sigh", "under her breath". Kept to these few shapes so it rarely
# fires on anything else.
_MANNER_RE = re.compile(
    r"(?:\s+(?:the\s+)?[A-Z][A-Za-z]+)?,?\s+("
    r"in an? (?:[a-z]+,? ){0,4}?(?:voice|tone|whisper|murmur|undertone)"
    r"|with an? (?:[a-z]+ ){0,2}?(?:smile|sigh|laugh|grin|shrug)"
    r"|under (?:her|his|their|my|your|its|our) breath"
    r")\b"
)
# Where a tag's words stop: the end of the sentence the tag is in.
_TAG_STOP_RE = re.compile(r"[.!?;:\u2026]")
_QUOTE_MARKS = "\"\u201c\u201d\u2018\u2019"


def _is_adverb(word: str) -> bool:
    return len(word) > 4 and word.lower() not in _NOT_ADVERBS


def _tag_after(para: str, end: int, limit: int) -> re.Match[str] | None:
    """The first tag verb in the few words after a closing quote."""
    stop = _TAG_STOP_RE.search(para, end, limit)
    limit = stop.start() if stop else limit
    for n, m in enumerate(LEXICAL_WORD_RE.finditer(para, end, limit)):
        if n >= DIALOGUE_TAG_WINDOW:
            break
        if m.group(0).lower() in SPEECH_VERBS or m.group(0).lower() in NON_SPEECH_TAG_VERBS:
            return m
    return None


def _tag_before(para: str, start: int, floor: int) -> re.Match[str] | None:
    """The last speech verb in the few words before an opening quote."""
    stop = None
    for stop in _TAG_STOP_RE.finditer(para, floor, start):
        pass
    floor = stop.end() if stop else floor
    words = list(LEXICAL_WORD_RE.finditer(para, floor, start))[-DIALOGUE_TAG_WINDOW:]
    for m in reversed(words):
        if m.group(0).lower() in SPEECH_VERBS:
            return m
    return None


def dialogue_tags_pass(paragraphs: list[str]) -> list[HighlightInstance]:
    """The marks of :func:`dialogue_tags`, without the count of tags."""
    return dialogue_tags(paragraphs)[0]


def dialogue_tags(paragraphs: list[str]) -> tuple[list[HighlightInstance], int]:
    """Mark the tags beside dialogue that a reader notices, and long stretches without one.

    A tag is a speech verb within a few words after a closing quote ("…,” she
    said) or before an opening one (Alice replied, ‘…’). It is marked when its
    verb is not said or asked, when an -ly adverb sits beside the verb, or
    when, right after a quote ending in a comma, the verb is something a face
    does rather than a way of speaking (“Fine,” she smiled). A run of
    :data:`UNTAGGED_RUN` or more dialogue paragraphs with no tag at all is
    marked on the first word of its first quote; a paragraph with narration
    around its speech, an action beat, counts as attributed. Notes start with the labels
    in :data:`DIALOGUE_TAG_NOTES`. A phrase doing an adverb's job ("in a sad little
    voice") is marked like an adverb.

    Also returns how many tags the scene has in all, marked or not, so the
    share of them carrying an adverb can be given.
    """
    out: list[HighlightInstance] = []
    total = 0
    run: list[tuple[int, tuple[int, int]]] = []

    def close_run() -> None:
        if len(run) >= UNTAGGED_RUN:
            idx, (a, b) = run[0]
            first = LEXICAL_WORD_RE.search(paragraphs[idx], a, b)
            if first:
                out.append(HighlightInstance(idx, first.span(), first.group(0),
                                             f"{len(run)} {DIALOGUE_TAG_NOTES['untagged_run']}"))
        run.clear()

    for idx, para in enumerate(paragraphs):
        speech = dialogue_spans(para)
        if not speech:
            close_run()
            continue
        tags: dict[int, tuple[re.Match[str], bool]] = {}
        for k, (a, b) in enumerate(speech):
            prev_end = speech[k - 1][1] if k else 0
            next_start = speech[k + 1][0] if k + 1 < len(speech) else len(para)
            quote = para[a:b]
            closed = len(quote) > 1 and quote[-1] in _QUOTE_MARKS
            inner = quote.rstrip(_QUOTE_MARKS)
            # "Fine." She said nothing. -- a full stop ends the speech, and
            # what follows is a new sentence, not a tag.
            if closed and inner and inner[-1] != ".":
                m = _tag_after(para, b, next_start)
                if m and (m.group(0).lower() in SPEECH_VERBS or inner[-1] == ","):
                    tags.setdefault(m.start(), (m, True))
            m = _tag_before(para, a, prev_end)
            if m:
                tags.setdefault(m.start(), (m, False))
        # An action beat ("She laughed.") says who is talking as well as a tag
        # does, so only a paragraph that is nothing but speech counts as untagged.
        narration = "".join(para[prev:a] for prev, (a, _b) in zip([0] + [b for _a, b in speech], speech))
        narration += para[speech[-1][1]:]
        if not tags and not LEXICAL_WORD_RE.search(narration):
            run.append((idx, speech[0]))
            continue
        close_run()
        total += len(tags)
        for _, (m, _after) in sorted(tags.items()):
            verb = m.group(0)
            start, end = m.span()
            notes = []
            if verb.lower() in NON_SPEECH_TAG_VERBS:
                notes.append(f"{DIALOGUE_TAG_NOTES['not_speech']}: \u201c{verb}\u201d")
            elif verb.lower() not in PLAIN_SPEECH_VERBS:
                notes.append(f"{DIALOGUE_TAG_NOTES['fancy']}: \u201c{verb}\u201d")
            adverb = _ADVERB_AFTER_RE.match(para, end)
            if adverb and "," in adverb.group(0) and _NOT_MANNER_RE.match(para, adverb.end(1)):
                adverb = None
            if adverb and _is_adverb(adverb.group(1)):
                end = adverb.end(1)
                notes.append(f"{DIALOGUE_TAG_NOTES['adverb']}: \u201c{adverb.group(1)}\u201d")
            else:
                adverb = _ADVERB_BEFORE_RE.search(para[:start])
                if adverb and _is_adverb(adverb.group(1)):
                    start = adverb.start(1)
                    notes.append(f"{DIALOGUE_TAG_NOTES['adverb']}: \u201c{adverb.group(1)}\u201d")
                else:
                    manner = _MANNER_RE.match(para, end)
                    if manner:
                        end = manner.end(1)
                        notes.append(f"{DIALOGUE_TAG_NOTES['manner']}: \u201c{manner.group(1)}\u201d")
            if notes:
                out.append(HighlightInstance(idx, (start, end), para[start:end], "; ".join(notes)))
    close_run()
    out.sort(key=lambda h: (h.paragraph_index, h.char_offsets[0]))
    return out, total


# A scene whose narration says "I" this often is told in first person, where
# marking every pronoun says nothing. Long enough not to judge a fragment.
FIRST_PERSON_SCENE_PER_1K = 20.0
FIRST_PERSON_SCENE_MIN_WORDS = 150


def is_first_person_pov(pov: object) -> bool:
    """Whether a scene's ``pov:`` frontmatter names first person ("first", "1st")."""
    return bool(re.search(r"\b(?:first|1st)\b", str(pov or ""), re.IGNORECASE))


def first_person_pass(paragraphs: list[str], *, pov: object = "") -> list[HighlightInstance]:
    """The marks of :func:`first_person`, without whether the scene is told in first person."""
    return first_person(paragraphs, pov=pov)[0]


def first_person(paragraphs: list[str], *, pov: object = "") -> tuple[list[HighlightInstance], bool]:
    """First-person pronouns in the narration of a scene not told in first person.

    "I" in speech is just a character talking. In third-person narration it
    is a slip into the character's voice, which is what this pass is for.
    A scene whose ``pov:`` says first person, or whose narration plainly is,
    gets no marks: there every "I" is meant. The second value says which
    case it was, so the scene panel can say why there are none.
    """
    if is_first_person_pov(pov):
        return [], True
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
        return [], True
    return out, False


#: Upper bounds of the sentence-length buckets the Spread view shows; a last
#: bucket holds everything longer. 68-sentence-rhythm.js repeats them.
SENTENCE_BUCKETS: tuple[int, ...] = (5, 10, 15, 20, 30, 40)


def sentence_lengths(text: str) -> list[int]:
    """Word count of each sentence in *text*, headings and notes left out.

    The same sentences the scene panel's sentence-length strip draws.
    """
    out: list[int] = []
    for para in split_paragraphs(text):
        if para.startswith("#") or para.startswith("<!--"):
            continue
        plain = strip_markdown_for_offsets(para)
        out.extend(n for n in (count_words(plain[a:b]) for a, b in sentence_spans(plain)) if n)
    return out


def sentence_buckets(lengths: Iterable[int]) -> list[int]:
    """How many of *lengths* fall in each of :data:`SENTENCE_BUCKETS`, plus the longer ones."""
    counts = [0] * (len(SENTENCE_BUCKETS) + 1)
    for n in lengths:
        counts[next((i for i, top in enumerate(SENTENCE_BUCKETS) if n <= top), len(SENTENCE_BUCKETS))] += 1
    return counts


def compute_scene_highlights(
    text: str,
    *,
    repeat_terms: Iterable[str] = (),
    pov: object = "",
    stopwords: Iterable[str] = COMMON_STOPWORDS,
) -> dict[str, object]:
    """Return the scene highlight payload embedded in the dashboard JSON.

    ``text`` is the scene body with frontmatter already stripped (matches
    ``SceneStats.text``). ``repeat_terms`` wires the repeats pass to the
    scene's own top-repeated words; pass ``SceneStats.repetition_examples``.
    ``pov`` is the scene's ``pov:`` frontmatter, which turns the first-person
    pass off for a scene told in first person. ``stopwords`` are the content
    stopwords (character names included) the echoes pass skips.
    """
    paragraphs = split_paragraphs(text)
    # A NOTE/TODO comment is a block the editor shows as a note, not prose,
    # so no pass marks it.
    plain_paragraphs = ["" if p.startswith("<!--") else strip_markdown_for_offsets(p)
                        for p in paragraphs]
    
    tag_marks, tag_total = dialogue_tags(plain_paragraphs)
    first_marks, told_in_first = first_person(plain_paragraphs, pov=pov)
    return {
        "paragraphs": paragraphs,
        # Scene numbers a pass's breakdown needs beyond its marks.
        "stats": {"dialogue_tags": tag_total, "told_in_first_person": told_in_first},
        "highlights": {
            "passive_voice": [h.to_dict() for h in passive_voice_pass(plain_paragraphs)],
            "filter_verbs": [h.to_dict() for h in filter_verbs_pass(plain_paragraphs)],
            "crutch_words": [h.to_dict() for h in crutch_words_pass(plain_paragraphs)],
            "hyperbole": [h.to_dict() for h in hyperbole_pass(plain_paragraphs)],
            "lyrical": [h.to_dict() for h in lyrical_pass(plain_paragraphs)],
            "sensory": [h.to_dict() for h in sensory_pass(plain_paragraphs)],
            "sentence_starts": [h.to_dict() for h in sentence_starts_pass(plain_paragraphs)],
            "repeats": [h.to_dict() for h in repeats_pass(plain_paragraphs, repeat_terms)],
            "first_person": [h.to_dict() for h in first_marks],
            "echoes": [h.to_dict() for h in echoes_pass(plain_paragraphs, stopwords)],
            "sticky_sentences": [h.to_dict() for h in sticky_sentences_pass(plain_paragraphs)],
            "dialogue_tags": [h.to_dict() for h in tag_marks],
            "dialogue": [h.to_dict() for h in dialogue_pass(plain_paragraphs)],
        },
    }

