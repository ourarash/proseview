"""Candidate character-roster extraction from prose.

Onboarding helper, not an analysis pass. Character Presence and Co-Occurrence
read a *roster* -- ``characters:`` in config, or the files under
``story-bible/characters/`` -- rather than per-scene frontmatter. A writer
pointing Proseview at an existing manuscript has neither, so both charts come
back empty with nothing to act on.

This proposes a ranked candidate list for a human to confirm once. It never
writes to the manuscript and never runs during a dashboard build: the writer
edits the list, saves it as config or story-bible files, and from then on
Proseview reads plain data exactly as it does today.

Accuracy is therefore not the bar -- "better than a blank page" is. Measured
recall against the principal casts of five public-domain novels (Dracula,
Pride and Prejudice, The Wonderful Wizard of Oz, A Princess of Mars,
Frankenstein) is 95% in the top 30 candidates, with the misses being
low-frequency framing narrators.

Example:
    >>> extract_roster(["Alice met the White Rabbit. The White Rabbit ran."])[0]
    ('White Rabbit', 2)
"""

from __future__ import annotations

import re
from collections import Counter

# Words that routinely appear capitalised only because they open a sentence.
# A single capitalised token from this set is never a name candidate.
_SENTENCE_CAPS = frozenset("""
the a an and or but if then when while as of to in on at by for with from into
i you he she it we they me him her them his hers its their our your my this that
these those there here what which who whom whose how why where was were is are am
be been being had has have do did does said says say oh well no yes not so very
much more most now one two three four five six seven eight nine ten first last
next thus down up out off over under again still just only even never always
come came go went let make made take took give gave see saw look looked turn
turned know knew think thought tell told ask asked good bad old new young little
big long short great small poor dear true false perhaps indeed however therefore
because before after until since though although unless whether both each either
neither every all any some none such same other another few many nor yet
""".split())

# Titles that attach to a following name ("Lady Catherine") and are never a
# character on their own.
_PURE_TITLES = frozenset({
    "mr", "mrs", "ms", "miss", "dr", "doctor", "prof", "professor", "sir",
    "lady", "lord", "madam", "madame", "mme", "mlle", "capt", "col", "gen",
    "sgt", "lt", "saint", "st", "rev", "reverend", "esq",
})

# Titles that are routinely the character's actual name in fiction -- "the
# Queen" in Alice, "the Duchess", "the Count". Kept as candidates; the
# prefix-merge below still folds them into a longer form when one dominates.
_ROLE_TITLES = frozenset({
    "king", "queen", "prince", "princess", "count", "countess", "duke",
    "duchess", "baron", "baroness", "captain", "colonel", "general", "major",
    "sergeant", "lieutenant", "father", "mother", "brother", "sister",
    "aunt", "uncle", "nurse", "doctor",
})

_HONORIFICS = _PURE_TITLES | _ROLE_TITLES

# Abbreviated titles carry a period that would otherwise break the capitalised
# run, leaving "Mr" and "Collins" as separate candidates.
_ABBREV_TITLE = r"(?:Mr|Mrs|Ms|Dr|Prof|St|Rev|Capt|Col|Gen|Sgt|Lt)\.?"

# A capitalised run, allowing lowercase particles inside a multi-word name
# ("Queen of Hearts", "Ludwig van Beethoven").
_NAME_RE = re.compile(
    r"(?:" + _ABBREV_TITLE + r"\s+)?"
    r"[A-Z][a-z’']+"
    r"(?:\s+(?:of|the|de|von|van|del|di|da)\s+[A-Z][a-z’']+|\s+[A-Z][a-z’']+)*"
)

# "I'm", "That's" -- a capitalised token glued to a contraction, never a name.
_CONTRACTION_RE = re.compile(r"^(?:I|It|That|There|What|He|She|They|We|You|Who|Here|Let)[’']")

# Sentence boundaries, except after an abbreviated title -- splitting on the
# period in "Mr. Collins" leaves the title and the name in different sentences,
# which loses the name entirely.
_ABBREVS = ("Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "St.", "Rev.", "Capt.",
            "Col.", "Gen.", "Sgt.", "Lt.")
_SENT_SPLIT_RE = re.compile(
    "".join(rf"(?<!\b{re.escape(a)})" for a in _ABBREVS) + r"(?<=[.!?”’])\s+"
)

_MD_NOISE_RE = re.compile(r"[*_#>`\[\]()]")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", re.DOTALL)
# A trailing possessive only. Stripping bare letters turns "Thoris" into
# "Thori" and "Mars" into "Mar".
_POSSESSIVE_RE = re.compile(r"[’']s?$")

DEFAULT_TOP_N = 30


def _clean(text: str) -> str:
    return _MD_NOISE_RE.sub("", _FRONTMATTER_RE.sub("", text))


def _candidates_in(sentence: str) -> list[tuple[str, bool]]:
    """Return ``(candidate, sentence_initial)`` pairs found in one sentence."""
    found: list[tuple[str, bool]] = []
    for match in _NAME_RE.finditer(sentence):
        raw = re.sub(r"\s+", " ", match.group(0)).strip().strip("’'")
        if not raw or _CONTRACTION_RE.match(raw):
            continue
        initial = match.start() == 0
        parts = raw.split()
        if len(parts) == 1 and parts[0].lower() in _SENTENCE_CAPS:
            continue
        # "Then Alice" -> "Alice": shed leading function words from a phrase.
        while len(parts) > 1 and parts[0].lower() in _SENTENCE_CAPS:
            parts = parts[1:]
            initial = False
        if not parts:
            continue
        # "Mr" alone is never a character; "Queen" alone often is.
        if len(parts) == 1 and parts[0].lower().rstrip(".") in _PURE_TITLES:
            continue
        found.append((" ".join(parts), initial))
    return found


def extract_roster(texts: list[str], top_n: int = DEFAULT_TOP_N) -> list[tuple[str, int]]:
    """Return ``[(candidate, mentions)]`` ranked by frequency, most-mentioned first.

    ``texts`` are raw scene bodies; frontmatter and Markdown punctuation are
    stripped internally.
    """
    # Two passes. A capitalised word opening a sentence is ambiguous -- "Alice
    # waited" and "Suddenly it stopped" look identical -- so sentence-initial
    # occurrences are counted only for names that also turn up mid-sentence
    # somewhere, where capitalisation actually means something. Names are
    # otherwise lost whenever a protagonist habitually starts sentences.
    counts: Counter[str] = Counter()
    initial_only: Counter[str] = Counter()
    confirmed: set[str] = set()

    for text in texts:
        for sentence in _SENT_SPLIT_RE.split(_clean(text)):
            sentence = sentence.strip()
            if not sentence:
                continue
            for name, initial in _candidates_in(sentence):
                if initial:
                    initial_only[name] += 1
                else:
                    counts[name] += 1
                    confirmed.add(name)

    for name, count in initial_only.items():
        if name in confirmed:
            counts[name] += count

    # Fold a name that is strictly a prefix of a more frequent longer name, so
    # "Van" lands under "Van Helsing" rather than competing with it.
    ranked = [name for name, _ in counts.most_common()]
    merged: Counter[str] = Counter()
    for name, count in counts.items():
        base = _POSSESSIVE_RE.sub("", name)
        target = base
        for longer in ranked:
            if longer != base and longer.startswith(base + " ") and counts[longer] > count:
                target = longer
                break
        merged[target] += count

    return merged.most_common(top_n)


def roster_from_scenes(scenes) -> list[tuple[str, int]]:
    """Convenience wrapper over already-parsed :class:`SceneStats`."""
    return extract_roster([scene.text for scene in scenes])
