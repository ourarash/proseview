"""Lexical primitives for proseview.

Pure text crunchers with no knowledge of scenes or config: word and token
regexes, the stopword/filter/sensory/lyrical/hyperbole word lists, MATTR and
MTLD computation, sentence splitting, and ``analyze_style_shape``. Everything
here takes raw strings and returns data.

Example:
    >>> tokens = lexical_tokens("The quick brown fox")
    >>> moving_average_ttr(tokens)
    1.0
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019-][A-Za-z0-9]+)*")
LEXICAL_WORD_RE = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)
QUOTE_RE = re.compile(r'["\u201c](.+?)["\u201d]', re.DOTALL)
ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
FIRST_PERSON_RE = re.compile(r"\b(?:i|me|my|mine|myself)\b", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# Irregular past participles, which do not end in -ed and so have to be listed.
_PARTICIPLES = (
    "born|bought|broken|brought|built|caught|chosen|done|drawn|driven|eaten|"
    "fallen|felt|fought|found|given|gone|grown|heard|held|hidden|hit|hurt|kept|"
    "known|laid|led|left|lost|made|meant|met|paid|put|read|ridden|rung|risen|"
    "said|seen|sold|sent|set|shaken|shot|shut|sung|sunk|spoken|spent|stood|"
    "stolen|struck|swept|swum|taken|taught|thrown|torn|told|thought|"
    "understood|woken|worn|won|written"
)

PASSIVE_VOICE_RE = re.compile(
    r"\b(am|are|is|was|were|be|been|being)\b\s+"
    r"(\w+ed|" + _PARTICIPLES + r")\b"
    r"(?P<agent>\s+by\b)?",
    re.IGNORECASE,
)

# "be + X" where X is nearly always describing a state rather than naming an
# action done to the subject: "she was tired" is not passive voice, but
# "he was surprised by the noise" is. The agent decides it, so these are
# skipped only when no "by" follows.
ADJECTIVAL_PARTICIPLES = {
    "tired", "excited", "scared", "interested", "married", "worried",
    "pleased", "annoyed", "bored", "confused", "frightened", "done",
    "finished", "gone", "closed", "prepared", "determined", "concerned",
    "satisfied", "disappointed", "embarrassed", "exhausted", "involved",
    "known", "used", "supposed", "dressed", "seated", "armed", "surprised",
    "ashamed", "amused", "delighted", "relieved", "alarmed", "puzzled",
}


def passive_spans(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` offsets of likely passive-voice constructions.

    The bare "be + participle" shape over-fires on predicate adjectives --
    "she was tired", "he was excited" -- which are states, not passives. A
    following "by" agent is what separates the two, so a participle on
    :data:`ADJECTIVAL_PARTICIPLES` counts only when one is present.

    The span stops at the participle so the "by" is not highlighted as part of
    the construction.
    """
    spans: list[tuple[int, int]] = []
    for match in PASSIVE_VOICE_RE.finditer(text):
        participle = match.group(2).lower()
        if participle in ADJECTIVAL_PARTICIPLES and not match.group("agent"):
            continue
        spans.append((match.start(), match.end(2)))
    return spans

MATTR_WINDOW = 100
MTLD_THRESHOLD = 0.72
SHORT_PARAGRAPH_WORDS = 40
TOP_REPETITION_TERMS = 6

COMMON_STOPWORDS = {
    "a", "about", "after", "again", "all", "almost", "also", "always", "am",
    "an", "and", "any", "are", "as", "at", "back", "be", "because", "been",
    "before", "being", "but", "by", "can", "could", "did", "do", "does",
    "don't", "down", "even", "every", "for", "from", "get", "go", "good",
    "had", "has", "have", "he", "her", "here", "him", "his", "how", "i",
    "if", "in", "into", "is", "it", "it's", "its", "just", "know", "like",
    "look", "make", "maybe", "me", "more", "most", "my", "need", "no",
    "not", "now", "of", "on", "one", "only", "or", "other", "our", "out",
    "over", "really", "right", "say", "says", "said", "see", "she", "so",
    "some", "still", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "thing", "this", "those", "through", "to",
    "too", "up", "us", "very", "want", "was", "way", "went", "we", "well",
    "were", "what", "when", "which", "who", "will", "with", "would",
    "yeah", "you", "your", "asked", "asks", "tell", "tells", "told",
    "looked", "turn", "turned",
}
FILTER_VERBS = {
    "saw", "heard", "felt", "noticed", "noticing", "smelled", "tasted",
    "thought", "thinking", "knew", "knowing", "wondered", "realized",
    "realizing", "seemed", "seeming", "looked", "looking", "watched",
    "watching",
}
CRUTCH_WORDS = {
    "just", "very", "really", "suddenly", "actually", "basically",
    "essentially", "literally", "slightly", "somewhat", "somehow", "indeed",
    "quite", "rather", "pretty",
}
SENSORY_WORDS = {
    "sight": {"red", "blue", "green", "yellow", "bright", "dark", "neon",
              "glow", "shadow", "shimmer", "pale", "vibrant", "color",
              "light", "silhouette"},
    "sound": {"whisper", "shout", "roar", "hum", "silence", "noise", "echo",
              "rattle", "thump", "rhythm", "melody", "clatter", "splash",
              "bleed"},
    "smell": {"scent", "aroma", "perfume", "smoke", "musk", "stink",
              "fragrance", "breath", "odor", "vanilla", "ash", "chlorine"},
    "touch": {"cold", "warm", "hot", "rough", "soft", "sharp", "smooth",
              "pressure", "heavy", "weight", "texture", "wet", "dry", "skin"},
    "taste": {"bitter", "sweet", "sour", "salt", "tongue", "flavor",
              "metallic", "delicious", "savory", "whiskey", "coffee",
              "saffron"},
}
LYRICAL_MARKERS = {
    "like", "as", "seemed", "became", "seeming", "transformed", "shimmered",
    "bloomed", "dissolved", "echoed",
}
HYPERBOLE_WORDS = {
    "never", "always", "forever", "perfect", "impossible", "utterly",
    "completely", "entirely", "absolute", "totally", "worst", "best",
    "everything", "nothing",
}
COMEDY_BEATS = {"...", "\u2014", "!", "?!"}


@dataclass(frozen=True)
class LexicalStats:
    tokens: int
    types: int
    ttr: float
    mattr: float
    mtld: float


def paragraph_blocks(text: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [b for b in blocks if not b.startswith("#")]


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def lexical_tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in LEXICAL_WORD_RE.finditer(text)]


def type_token_ratio(tokens: list[str]) -> float:
    return len(set(tokens)) / len(tokens) if tokens else 0.0


def moving_average_ttr(tokens: list[str], window: int = MATTR_WINDOW) -> float:
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return type_token_ratio(tokens)
    total = sum(len(set(tokens[s:s + window])) / window for s in range(len(tokens) - window + 1))
    return total / (len(tokens) - window + 1)


def mtld(tokens: list[str], threshold: float = MTLD_THRESHOLD) -> float:
    if not tokens:
        return 0.0

    def count_factors(seq: list[str]) -> float:
        factors, types, start = 0.0, set(), 0
        for idx, tok in enumerate(seq, 1):
            types.add(tok)
            if len(types) / (idx - start) <= threshold:
                factors += 1.0
                types.clear()
                start = idx
        rem = len(seq) - start
        if rem and len(types) / rem != 1.0:
            factors += (1.0 - (len(types) / rem)) / (1.0 - threshold)
        return factors

    f, r = count_factors(tokens), count_factors(list(reversed(tokens)))
    return (len(tokens) / f + len(tokens) / r) / 2.0 if f and r else 0.0


def calculate_lexical_stats(text: str) -> LexicalStats:
    toks = lexical_tokens(text)
    return LexicalStats(len(toks), len(set(toks)), type_token_ratio(toks),
                        moving_average_ttr(toks), mtld(toks))


def split_sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text.strip())
    if not flat:
        return []
    return [p.strip() for p in SENTENCE_SPLIT_RE.split(flat)
            if p.strip() and count_words(p) > 0]


def build_content_stopwords(root: Path, characters_dir: str = "story-bible/characters") -> set[str]:
    sw = set(COMMON_STOPWORDS)
    char_dir = root / characters_dir
    if char_dir.exists():
        for p in char_dir.glob("*.md"):
            for t in lexical_tokens(p.stem.replace("-", " ")):
                sw.add(t)
    return sw


_STEM_SUFFIXES: tuple[str, ...] = (
    "izations", "ization",
    "ations", "ation",
    "ating", "ated", "ates",
    "tions", "tion",
    "nesses", "ness",
    "ments", "ment",
    "izing", "ized", "izes", "ize",
    "ising", "ised", "ises", "ise",
    "ings", "ing",
    "ities", "ity",
    "ally", "edly", "fully", "ably", "ibly",
    "ible", "able",
    "less",
    "ate",
    "ers", "er",
    "ied", "ies",
    "ed", "ly", "al",
    "es", "s",
)
_STEM_MIN_LEN = 3


def _stem(word: str) -> str:
    w = word.lower()
    for suffix in _STEM_SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= _STEM_MIN_LEN:
            stem = w[: -len(suffix)]
            if suffix in ("ied", "ies"):
                stem += "y"
            return stem
    return w


def top_repeated_content_words(text: str, sw: set[str],
                               limit: int = TOP_REPETITION_TERMS) -> tuple[float, tuple[str, ...]]:
    toks = [t for t in lexical_tokens(text) if t not in sw and len(t) >= 3 and "'" not in t]
    if not toks:
        return 0.0, ()

    stem_groups: dict[str, Counter[str]] = defaultdict(Counter)
    for tok in toks:
        stem_groups[_stem(tok)][tok] += 1

    rep = [
        (sum(c.values()), c)
        for c in stem_groups.values()
        if sum(c.values()) >= 3
    ]
    if not rep:
        return 0.0, ()

    rep.sort(key=lambda x: x[0], reverse=True)
    score = rep[0][0] * 1000 / len(toks)

    examples: list[str] = []
    for total, word_counts in rep[:limit]:
        all_forms = [w for w, _ in word_counts.most_common()]
        label = "/".join(all_forms)
        examples.append(f"{label}x{total}")

    return score, tuple(examples)


def analyze_style_shape(text: str, sw: set[str]) -> dict[str, object]:
    words = count_words(text)
    paras = paragraph_blocks(text)
    para_counts = [count_words(b) for b in paras]
    sents = split_sentences(text)
    sent_counts = [count_words(s) for s in sents]
    dlg_matches = list(QUOTE_RE.finditer(text))
    dlg_words = sum(count_words(m.group(1)) for m in dlg_matches)
    score, ex = top_repeated_content_words(text, sw)

    first_person = len(FIRST_PERSON_RE.findall(text))
    italics = len(ITALIC_RE.findall(text))
    questions = text.count("?")
    filter_count = sum(len(re.findall(rf"\b{v}\b", text, re.IGNORECASE)) for v in FILTER_VERBS)
    passive_count = len(passive_spans(text))
    crutch_count = sum(len(re.findall(rf"\b{v}\b", text, re.IGNORECASE)) for v in CRUTCH_WORDS)

    sensory_count = 0
    for cat in SENSORY_WORDS.values():
        sensory_count += sum(len(re.findall(rf"\b{v}\b", text, re.IGNORECASE)) for v in cat)

    avg_sent = sum(sent_counts) / len(sent_counts) if sent_counts else 0.0
    # An empty, whitespace-only, or frontmatter-only scene has no words. Without
    # this guard one blank file takes down the whole dashboard build, not just
    # its own row.
    dialogue_share = (dlg_words / words) if words else 0.0
    energy = 10.0 + (dialogue_share * 5.0) - (avg_sent / 2.0)

    dlg_text = " ".join(m.group(1) for m in dlg_matches)
    dlg_toks = [t for t in lexical_tokens(dlg_text) if t not in sw and len(t) > 3]
    top_dlg = tuple(w for w, _ in Counter(dlg_toks).most_common(5))

    return {
        "avg_sentence_words": avg_sent,
        "sent_len_stdev": statistics.stdev(sent_counts) if len(sent_counts) > 1 else 0.0,
        "dialogue_pct": (dlg_words / words * 100) if words else 0.0,
        "short_paragraph_pct": (sum(1 for c in para_counts if c <= SHORT_PARAGRAPH_WORDS)
                                / len(para_counts) * 100) if para_counts else 0.0,
        "avg_paragraph_words": sum(para_counts) / len(para_counts) if para_counts else 0.0,
        "first_person_per_1k": first_person * 1000 / words if words else 0.0,
        "italics_per_1k": italics * 1000 / words if words else 0.0,
        "questions_per_1k": questions * 1000 / words if words else 0.0,
        "filter_verbs_per_1k": filter_count * 1000 / words if words else 0.0,
        "passive_per_1k": passive_count * 1000 / words if words else 0.0,
        "crutch_per_1k": crutch_count * 1000 / words if words else 0.0,
        "sensory_density": sensory_count * 1000 / words if words else 0.0,
        "energy_score": energy,
        "top_dialogue": top_dlg,
        "repetition_score": score,
        "repetition_examples": ex,
    }
