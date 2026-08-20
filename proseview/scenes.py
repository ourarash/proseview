"""Scene walking, dataclasses, filtering, sorting, and baseline resolution.

Operates one level up from :mod:`proseview.lexical`: takes a repo root,
discovers scenes under ``manuscript/``, and returns typed records
(:class:`SceneStats`, :class:`ChapterSummary`, :class:`BaselineStats`) that the
generator and later milestones consume.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TODO_RE = re.compile(r'<!--\s*TODO\s*:(.*?)-->', re.DOTALL | re.IGNORECASE)
NOTE_RE = re.compile(r'<!--\s*NOTE(?:\[(\w+)\])?\s*:(.*?)-->', re.DOTALL | re.IGNORECASE)

from .config import Config
from .repo import CONTEXT_SKIP_DIRS, read_repo_text
from .lexical import (
    FRONTMATTER_RE,
    analyze_style_shape,
    build_content_stopwords,
    calculate_lexical_stats,
    count_words,
    lexical_tokens,
    paragraph_blocks,
    LexicalStats,
)


@dataclass
class SceneStats:
    path: Path
    chapter: str
    title: str
    status: str
    text: str
    words: int
    paragraphs: int
    headings: int
    characters: int
    reading_minutes: int
    lexical_tokens: int
    lexical_types: int
    ttr: float
    mattr: float
    mtld: float
    avg_sentence_words: float
    sent_len_stdev: float
    dialogue_pct: float
    avg_paragraph_words: float
    short_paragraph_pct: float
    questions_per_1k: float
    italics_per_1k: float
    first_person_per_1k: float
    passive_per_1k: float
    crutch_per_1k: float
    sensory_density: float
    energy_score: float
    repetition_score: float
    repetition_examples: tuple[str, ...]
    top_dialogue_words: tuple[str, ...]
    flavor_words: tuple[str, ...]
    location: str
    frontmatter: dict[str, object]
    todos: list
    notes: list
    txt_line_offset: int


@dataclass(frozen=True)
class BaselineStats:
    label: str
    scene_count: int
    words: int
    lexical: LexicalStats
    scene_mattr_median: float
    scene_mtld_median: float


@dataclass(frozen=True)
class ChapterSummary:
    chapter: str
    scene_count: int
    words: int
    lexical: LexicalStats
    scene_mattr_median: float
    scene_mtld_median: float
    dialogue_pct: float
    avg_sentence_words: float
    short_paragraph_pct: float


def scan_todos(fm: dict, txt: str, txt_line_offset: int = 0) -> list:
    """Return TODO items from frontmatter todos: list and inline <!-- TODO: --> comments.

    Each item: {text, line, paragraph_index, source}.

    ``line`` is 1-based and **file-relative** when ``txt_line_offset`` is
    supplied (the count of source-file lines stripped before ``txt``:
    frontmatter, leading H1, blanks). It is ``None`` for frontmatter
    todos, which have no line anchor. ``paragraph_index`` matches the
    ``paragraph_blocks(txt)`` index. Frontmatter todos use -1.
    """
    todos: list = []

    fm_todos = fm.get('todos', [])
    if isinstance(fm_todos, str):
        fm_todos = [fm_todos] if fm_todos.strip() else []
    elif not isinstance(fm_todos, list):
        fm_todos = []
    for item in fm_todos:
        text = str(item).strip()
        if text:
            todos.append({'text': text, 'line': None, 'paragraph_index': -1, 'source': 'frontmatter'})

    paras = paragraph_blocks(txt)
    para_offsets: list[int] = []
    pos = 0
    for para in paras:
        idx = txt.find(para, pos)
        if idx < 0:
            idx = pos
        para_offsets.append(idx)
        pos = idx + len(para)

    for match in TODO_RE.finditer(txt):
        todo_text = ' '.join(match.group(1).split())
        if not todo_text:
            continue
        line = txt[:match.start()].count('\n') + 1 + txt_line_offset
        para_idx = max(0, len(paras) - 1) if paras else 0
        for i, offset in enumerate(para_offsets):
            para_end = offset + len(paras[i])
            if offset <= match.start() < para_end:
                para_idx = i
                break
            if offset > match.end():
                if not paras[i].strip().startswith('<!--'):
                    para_idx = i
                    break
        todos.append({'text': todo_text, 'line': line, 'paragraph_index': para_idx, 'source': 'inline'})

    return todos


def scan_notes(fm: dict, txt: str, txt_line_offset: int = 0) -> list:
    """Return NOTE items from inline <!-- NOTE[tag]: --> comments.

    Each item: {text, tag, line, paragraph_index, source}. ``line`` is
    file-relative when ``txt_line_offset`` is supplied; see
    :func:`scan_todos` for details. ``paragraph_index`` matches the
    ``paragraph_blocks(txt)`` index used by the highlights renderer.
    """
    notes: list = []

    paras = paragraph_blocks(txt)
    para_offsets: list[int] = []
    pos = 0
    for para in paras:
        idx = txt.find(para, pos)
        if idx < 0:
            idx = pos
        para_offsets.append(idx)
        pos = idx + len(para)

    for match in NOTE_RE.finditer(txt):
        tag = (match.group(1) or 'note').strip().lower()
        note_text = ' '.join(match.group(2).split())
        if not note_text:
            continue
        line = txt[:match.start()].count('\n') + 1 + txt_line_offset
        para_idx = max(0, len(paras) - 1) if paras else 0
        for i, offset in enumerate(para_offsets):
            para_end = offset + len(paras[i])
            if offset <= match.start() < para_end:
                para_idx = i
                break
            if offset > match.end():
                if not paras[i].strip().startswith('<!--'):
                    para_idx = i
                    break
        notes.append({'text': note_text, 'tag': tag, 'line': line, 'paragraph_index': para_idx, 'source': 'inline'})

    return notes


def parse_simple_yaml(text: str) -> dict[str, object]:
    data: dict[str, object] = {}
    current_key = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and current_key:
            val = line.lstrip()[2:].strip()
            if current_key not in data:
                data[current_key] = [val]
            elif isinstance(data[current_key], list):
                data[current_key].append(val)
            else:
                data[current_key] = [data[current_key], val]
            continue
        if raw_line[:1].isspace() and current_key:
            current = data.get(current_key)
            if isinstance(current, str):
                piece = line.strip()
                if piece:
                    data[current_key] = f"{current} {piece}"
                continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        current_key = key
        data[key] = value if value else []
    return data


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    return parse_simple_yaml(match.group(1)), text[match.end():]


def extract_scene_text(text: str) -> str:
    lines = text.splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start < len(lines) and lines[start].lstrip().startswith("# "):
        start += 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start:])


def _is_scene(fm: dict[str, object]) -> bool:
    """False when frontmatter opts the file out with ``scene: false``."""
    raw = fm.get("scene")
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"false", "no", "off", "0"}


def resolve_manuscript_dir(root: Path, manuscript_subdir: str) -> Path:
    """Return the directory scenes are read from.

    Normally ``root/manuscript``. When that does not exist the whole repo is
    treated as the manuscript, which is what makes Proseview usable against an
    Obsidian vault or any other flat folder of Markdown: point it at the folder
    and the scenes are simply the ``.md`` files in it.
    """
    subdir = manuscript_subdir.strip("/")
    if not subdir or subdir == ".":
        return root
    candidate = root / subdir
    return candidate if candidate.is_dir() else root


def iter_scene_paths(manuscript_dir: Path) -> list[Path]:
    """Every Markdown file under *manuscript_dir*, at any depth.

    The old rule was exactly two levels -- ``manuscript/<chapter>/<scene>.md``
    -- which meant a flat folder or a nested one indexed as nothing at all, and
    the dashboard came up empty with no explanation. Any depth is accepted now,
    including files sitting directly in the manuscript root.

    Hidden directories and tool directories are skipped, so pointing at a repo
    root or an Obsidian vault does not sweep in ``.git`` or ``.obsidian``.
    """
    if not manuscript_dir.is_dir():
        return []

    paths: list[Path] = []
    for path in sorted(manuscript_dir.rglob("*.md")):
        relative = path.relative_to(manuscript_dir)
        if any(part.startswith(".") or part in CONTEXT_SKIP_DIRS for part in relative.parts[:-1]):
            continue
        if path.name.startswith(".") or path.name.lower() == "readme.md":
            continue
        paths.append(path)
    return paths


def scene_chapter(path: Path, manuscript_dir: Path) -> str:
    """Default chapter label for a scene, when frontmatter does not name one.

    The first directory below the manuscript root, so the conventional
    ``manuscript/ch01/01-opening.md`` still groups under ``ch01`` and a deeper
    ``manuscript/ch01/drafts/01.md`` groups with it rather than splitting off.
    Files directly in the root fall back to the root's own name.
    """
    relative = path.relative_to(manuscript_dir)
    return relative.parts[0] if len(relative.parts) > 1 else manuscript_dir.name


#: Placeholder used when ``collect_scene_stats(lexical=False)`` skips the
#: MATTR/MTLD pass. Same shape as the real result, zeroed, so ``SceneStats``
#: keeps one field layout regardless of how it was built.
_EMPTY_LEXICAL = LexicalStats(tokens=0, types=0, ttr=0.0, mattr=0.0, mtld=0.0)


def collect_scene_stats(
    root: Path,
    manuscript_subdir: str | Config = "manuscript",
    *,
    characters_dir: str = "story-bible/characters",
    lexical: bool = True,
) -> list[SceneStats]:
    """Index the manuscript, optionally skipping the MATTR/MTLD pass.

    With ``lexical=False`` the type-token measures come back zeroed. Only the
    Analysis tab reads them -- the scatter chart and the table's Variety column
    -- so a dashboard build skips them.

    The style pass always runs: the reading view's stat grid and the ``repeats``
    highlight pass are built from it, and both are wanted on every scene the
    reader opens.
    """
    if isinstance(manuscript_subdir, Config):
        cfg = manuscript_subdir
        manuscript_subdir = cfg.manuscript_subdir
        characters_dir = cfg.characters_dir
    man_dir = resolve_manuscript_dir(root, manuscript_subdir)
    sw = build_content_stopwords(root, characters_dir)
    scenes: list[SceneStats] = []
    global_counts: Counter[str] = Counter()
    temp_scenes = []
    for p in iter_scene_paths(man_dir):
        raw = read_repo_text(p)
        fm, body = split_frontmatter(raw)
        txt = extract_scene_text(body)
        toks = [t for t in lexical_tokens(txt) if t not in sw and len(t) > 3]
        global_counts.update(toks)
        # Lines in the original file before the extracted prose starts
        prefix = txt.lstrip("\n")[:60]
        raw_idx = raw.find(prefix) if prefix else -1
        txt_line_offset = raw[:raw_idx].count("\n") if raw_idx >= 0 else 0
        # `scene: false` opts a file out of the index. Accepting any Markdown
        # at any depth means review notes and per-chapter outlines living inside
        # the manuscript now count toward scene and word totals; this is how a
        # writer says "that one is not prose".
        if not _is_scene(fm):
            continue
        temp_scenes.append((p, fm, txt, toks, txt_line_offset))

    for p, fm, txt, toks, txt_line_offset in temp_scenes:
        words = count_words(txt)
        lex = calculate_lexical_stats(txt) if lexical else _EMPTY_LEXICAL
        st = analyze_style_shape(txt, sw)
        scene_counts = Counter(toks)
        distinctive = []
        for word, count in scene_counts.most_common(20):
            score = count / (global_counts[word] + 1)
            distinctive.append((word, score))
        flavor = tuple(w for w, _ in sorted(distinctive, key=lambda x: x[1], reverse=True)[:3])

        loc = str(fm.get("where", fm.get("location", p.parent.name))).strip()
        if not loc:
            loc = p.parent.name

        scenes.append(SceneStats(
            p.relative_to(root), str(fm.get("chapter", scene_chapter(p, man_dir))).strip(),
            str(fm.get("title", p.stem.replace("-", " ").title())).strip(),
            str(fm.get("status", "unknown")).strip() or "unknown",
            txt, words, len(paragraph_blocks(txt)),
            sum(1 for l in txt.splitlines() if l.lstrip().startswith("#")),
            len(txt), max(1, math.ceil(words / 250)),
            lex.tokens, lex.types, lex.ttr, lex.mattr, lex.mtld,
            float(st["avg_sentence_words"]), float(st["sent_len_stdev"]), float(st["dialogue_pct"]),
            float(st["avg_paragraph_words"]), float(st["short_paragraph_pct"]),
            float(st["questions_per_1k"]), float(st["italics_per_1k"]),
            float(st["first_person_per_1k"]), float(st["passive_per_1k"]),
            float(st["crutch_per_1k"]), float(st["sensory_density"]),
            float(st["energy_score"]), float(st["repetition_score"]),
            st["repetition_examples"], st["top_dialogue"], flavor,
            loc, fm, scan_todos(fm, txt, txt_line_offset), scan_notes(fm, txt, txt_line_offset), txt_line_offset,
        ))
    return scenes


def scene_mtld_median(scenes: list[SceneStats]) -> float:
    """The manuscript's own MTLD median.

    Computed per chapter and per baseline for a long time, and read by nothing:
    ``build_dashboard`` opened with ``del baseline``. It is the reference that
    needs no corpus, and the one that answers the question a writer revising
    actually has -- which scene is unlike the rest of my book.
    """
    vals = [s.mtld for s in scenes if s.mtld]
    return statistics.median(vals) if vals else 0.0


def scene_mattr_median(scenes: list[SceneStats]) -> float:
    vals = [s.mattr for s in scenes if s.mattr]
    return statistics.median(vals) if vals else 0.0


def goal_position(v: float, g: tuple[float, float]) -> str:
    if v < g[0]:
        return "below"
    return "above" if v > g[1] else "inside"


def scene_is_outlier(s: SceneStats, cfg: Config) -> bool:
    return (goal_position(s.mattr, cfg.mattr_band) != "inside"
            or goal_position(s.mtld, cfg.mtld_band) != "inside")


def scene_severity(s: SceneStats, cfg: Config) -> float:
    sev = 0.0
    if s.mattr < cfg.mattr_band[0]:
        sev += cfg.mattr_band[0] - s.mattr
    elif s.mattr > cfg.mattr_band[1]:
        sev += s.mattr - cfg.mattr_band[1]
    if s.mtld < cfg.mtld_band[0]:
        sev += (cfg.mtld_band[0] - s.mtld) / 100
    elif s.mtld > cfg.mtld_band[1]:
        sev += (s.mtld - cfg.mtld_band[1]) / 100
    return sev


def revision_signal(s: SceneStats, cfg: Config) -> str:
    m_p, l_p = goal_position(s.mattr, cfg.mattr_band), goal_position(s.mtld, cfg.mtld_band)
    p = []
    if m_p == "below":
        p.append("Local variety (MATTR) is below target")
    elif m_p == "above":
        p.append("Local variety (MATTR) is above target")

    if l_p == "below":
        p.append("Whole-scene variety (MTLD) is below target")
    elif l_p == "above":
        p.append("Whole-scene variety (MTLD) is above target")

    if s.dialogue_pct > 45:
        p.append(f"High dialogue ({int(s.dialogue_pct)}%)")
    if s.avg_sentence_words < 8:
        p.append(f"Short sentences (Avg {s.avg_sentence_words} words)")
    if s.short_paragraph_pct > 65:
        p.append(f"Many short paragraphs ({int(s.short_paragraph_pct)}%)")
    if s.repetition_examples:
        p.append(f"Top repeated words: {', '.join(s.repetition_examples)}")
    return " • ".join(p)


def chapter_summaries(scenes: list[SceneStats]) -> list[ChapterSummary]:
    grouped: dict[str, list[SceneStats]] = defaultdict(list)
    for s in scenes:
        grouped[s.chapter].append(s)
    summaries = []
    for ch in sorted(grouped):
        ch_scenes = grouped[ch]
        txt = "\n".join(s.text for s in ch_scenes)
        lex = calculate_lexical_stats(txt)
        m_vals = [s.mattr for s in ch_scenes]
        l_vals = [s.mtld for s in ch_scenes]
        summaries.append(ChapterSummary(
            ch, len(ch_scenes), sum(s.words for s in ch_scenes), lex,
            statistics.median(m_vals), statistics.median(l_vals),
            sum(s.dialogue_pct for s in ch_scenes) / len(ch_scenes),
            sum(s.avg_sentence_words for s in ch_scenes) / len(ch_scenes),
            sum(s.short_paragraph_pct for s in ch_scenes) / len(ch_scenes),
        ))
    return summaries


def resolve_baseline(baseline: str, scenes: list[SceneStats], root: Path) -> BaselineStats | None:
    val = baseline.strip().lower()
    if not val or val == "none":
        return None
    sel: list[SceneStats] = []
    label = baseline
    if val in {"auto", "ch01"}:
        sel = [s for s in scenes if s.chapter == "Chapter 1"]
        label = "Chapter 1"
    elif val.startswith("chapter:"):
        raw = baseline.split(":", 1)[1].strip()
        sel = [s for s in scenes if raw.lower() in s.chapter.lower()]
        label = raw
    else:
        cand = (root / baseline).resolve() if not Path(baseline).is_absolute() else Path(baseline)
        sel = [s for s in scenes if (root / s.path).resolve() == cand or s.path.as_posix() == baseline]
        label = str(baseline)
    if not sel:
        return None
    txt = "\n".join(s.text for s in sel)
    return BaselineStats(
        label, len(sel), sum(s.words for s in sel),
        calculate_lexical_stats(txt),
        statistics.median([s.mattr for s in sel]),
        statistics.median([s.mtld for s in sel]),
    )


def filter_scenes(scenes: list[SceneStats], focus: str, cfg: Config) -> list[SceneStats]:
    if not focus or focus.lower() == "all":
        return scenes
    terms = [t.strip().lower() for t in focus.split(",")]
    filtered: list[SceneStats] = []
    for s in scenes:
        for t in terms:
            if t == "outliers" and scene_is_outlier(s, cfg):
                filtered.append(s)
                break
            if t == "low" and (goal_position(s.mattr, cfg.mattr_band) == "below"
                               or goal_position(s.mtld, cfg.mtld_band) == "below"):
                filtered.append(s)
                break
            if t == "high" and (goal_position(s.mattr, cfg.mattr_band) == "above"
                                or goal_position(s.mtld, cfg.mtld_band) == "above"):
                filtered.append(s)
                break
            if t.startswith("chapter:") and t.split(":", 1)[1].strip() in s.chapter.lower():
                filtered.append(s)
                break
            if t.startswith("path:") and t.split(":", 1)[1].strip() in s.path.as_posix().lower():
                filtered.append(s)
                break
    return filtered


def sort_scenes(scenes: list[SceneStats], key: str, rev: bool,
                cfg: Config | None = None) -> list[SceneStats]:
    funcs: dict[str, Any] = {
        # Posix so ordering and search behave the same on every platform.
        "path": lambda s: s.path.as_posix(),
        "chapter": lambda s: (s.chapter, s.path.as_posix()),
        "words": lambda s: s.words,
        "mattr": lambda s: s.mattr,
        "mtld": lambda s: s.mtld,
        "dialogue": lambda s: s.dialogue_pct,
    }
    if key == "severity":
        if cfg is None:
            raise ValueError("sort_scenes(key='severity') requires cfg")
        return sorted(scenes, key=lambda s: scene_severity(s, cfg), reverse=rev)
    return sorted(scenes, key=funcs.get(key, funcs["path"]), reverse=rev)
