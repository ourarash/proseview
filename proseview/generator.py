"""HTML dashboard generator.

Public entry: :func:`build_dashboard`. Takes a repo root and a
:class:`~proseview.config.Config`, returns the single-file HTML string that
``.proseview/stats.html`` is written from.

The dashboard is emitted as one self-contained HTML file, but the source is
split into a Jinja template plus inlined CSS and JavaScript assets under
``proseview/templates/``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import html
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .callouts import GITHUB_TYPES, screen_colours, screen_css
from .config import GENRE_LABELS, Config
from .editor import build_url as _editor_url, label as _editor_label
from .goals import Goals, compute_goals
from .highlights import PASS_NAMES, compute_scene_highlights
from .history import HistoryRow, load_history, working_copy_delta
from .lexical import FILTER_VERBS, calculate_lexical_stats, text_dialogue_spans
from .related import find_related
from .repo import (
    build_repository_tree, build_sidebar_tree, build_tree, lists_whole_folder, read_repo_text, recent_changes,
)
from .story import story_payload
from .scenes import (
    BaselineStats,
    SceneStats,
    collect_scene_stats,
    filter_scenes,
    goal_position,
    revision_signal,
    scene_is_outlier,
    scene_mattr_median,
    scene_mtld_median,
    manuscript_missing,
    sort_scenes,
)

TEMPLATE_DIR = Path(__file__).with_name("templates")


@lru_cache(maxsize=1)
def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(enabled_extensions=("html", "xml", "j2")),
        keep_trailing_newline=True,
    )


@lru_cache(maxsize=None)
def _load_asset(relative_path: str) -> str:
    return (TEMPLATE_DIR / relative_path).read_text(encoding="utf-8")


def _load_app_css() -> str:
    """Concatenate ``assets/app.css`` with every theme in ``assets/themes``.

    Themes live in their own files so one can be added or edited without
    touching the main stylesheet — the same reason the front-end JS is split.
    Order is app.css first, then themes lexically, so a theme's ``[data-theme]``
    block always wins over the defaults it overrides.
    """
    parts = [_load_asset("assets/app.css")]
    themes_dir = TEMPLATE_DIR / "assets" / "themes"
    if themes_dir.is_dir():
        for path in sorted(themes_dir.glob("*.css")):
            parts.append(_load_asset(f"assets/themes/{path.name}"))
    return "\n".join(parts)


def _load_app_js() -> str:
    """Concatenate ``templates/assets/js/*.js`` in lexical order.

    The front-end is split into topical files for readability but emitted
    as one ``<script>`` block so the runtime is identical to the legacy
    single-file form (no module boundaries, all top-level functions
    hoisted into the same scope). Each file is fetched via ``_load_asset``
    so ``_load_asset.cache_clear()`` invalidates them all at once.
    """
    js_dir = TEMPLATE_DIR / "assets" / "js"
    if not js_dir.is_dir():
        return _load_asset("assets/app.js")
    rel_paths = sorted(p.relative_to(TEMPLATE_DIR).as_posix() for p in js_dir.glob("*.js"))
    return "\n".join(_load_asset(rel) for rel in rel_paths)


def _render_template(name: str, **context: object) -> str:
    return _template_env().get_template(name).render(**context)


def info_tip(text: str) -> str:
    """A small "i" that shows *text* on hover or keyboard focus.

    For what a number measures: one quiet mark beside the label instead of a
    paragraph under it.
    """
    escaped = html.escape(text, quote=True)
    return f'<span class="info-tip" tabindex="0" role="img" aria-label="{escaped}" data-tip="{escaped}">i</span>'


def _signed(n: int) -> str:
    """``+250``, ``\u22121,118`` or ``0``."""
    if n == 0:
        return "0"
    return f"{n:+,}".replace("-", "\u2212")


def _short_date(iso: str) -> str:
    try:
        moment = date.fromisoformat(iso)
    except ValueError:
        return iso
    return moment.strftime("%b ") + str(moment.day)


def _stat(label: str, tip: str, value: str, sub: str = "") -> str:
    sub_html = f'<span class="progress-stat-sub">{sub}</span>' if sub else ""
    return (
        '<div class="progress-stat">'
        f'<span class="progress-stat-label">{html.escape(label)}{info_tip(tip)}</span>'
        f'<span class="progress-stat-value">{value}</span>{sub_html}'
        "</div>"
    )


def _render_progress_card(
    goals: Goals | None,
    cfg: Config,
    *,
    total_words: int,
    scene_count: int,
) -> str:
    """The Overview's one summary: words against the goal, then today, pace
    and finish in a single row. Every figure carries an "i" saying what it
    measures. Without git history the row keeps only what needs none.
    """
    target = cfg.target_words
    daily = cfg.daily_target
    percent = (total_words / target * 100) if target else 0.0
    words_left = max(0, target - total_words)
    minutes = math.ceil(total_words / 250)
    reading = f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"
    total_tip = (
        "Words of prose in your scenes. Frontmatter, headings and TODO or NOTE comments "
        "don't count."
    )

    stats: list[str] = []
    today_label = "Today"
    opener = "record"
    if goals is not None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        kind = goals.ledger.baseline_kind if goals.ledger is not None else "commit"
        since = _short_date(goals.baseline_date) if goals.baseline_date else ""
        # Say what the number is measured against: Proseview's own record of
        # yesterday, an older day it saw, or (before it has a record) a commit.
        if kind == "commit" and since:
            today_label = f"Since {since} (last commit)"
            opener = "git"
            today_tip = (
                f"Net words since your last commit, on {since}: written minus cut. Proseview "
                "has no copy of your book from before today yet; from tomorrow this counts today alone."
            )
        elif goals.baseline_date and goals.baseline_date < yesterday:
            today_label = f"Since {since}"
            today_tip = (
                f"Net words since {since}, the last day Proseview saw your book: written minus cut. "
                "It wasn't running in between, so those days are counted together."
            )
        else:
            today_tip = "Net words today: written minus cut, against Proseview's copy from the end of yesterday."
        today_value = _signed(goals.words_added_today)
        today_tip += " Click the number to see what was written and cut, scene by scene."
        today_value = (
            f'<button type="button" class="banner-ledger-btn" onclick="openLedger(\'{opener}\')" '
            f'title="What was written and cut">{today_value}</button>'
        )
        stats.append(_stat(today_label, today_tip, today_value))
        stats.append(_stat(
            "Words a day",
            "Words added per day over the last 7 days, net of cuts, so a week of revision "
            "reads negative. \u201cWhat changed\u201d shows what was written and cut.",
            _signed(round(goals.rolling_velocity)),
            f"last 7 days &middot; goal {daily:,}",
        ))
        stats.append(_stat(
            "Writing streak",
            "Days in a row, up to today or yesterday, on which a scene was saved or committed.",
            f"{goals.streak_days} {'day' if goals.streak_days == 1 else 'days'}",
        ))
        stats.append(_stat(
            "Scenes changed today",
            "Scenes whose file was saved today, plus scenes in today's commits.",
            f"{goals.scenes_touched_today}",
        ))
        stats.append(_stat(
            "Words per chapter",
            f"Your words divided by your {goals.head_chapter_count} chapters. The goal spreads "
            f"the book goal of {target:,} evenly over them.",
            f"{goals.per_chapter_current:,}",
            f"goal {goals.per_chapter_target:,}",
        ))
    if words_left == 0 and target:
        stats.append(_stat("Book goal", f"The manuscript has reached your goal of {target:,} words.", "Reached"))
    elif daily:
        days = math.ceil(words_left / daily)
        stats.append(_stat(
            "To finish",
            f"{words_left:,} words to go, at your daily goal of {daily:,} words. "
            "This is a plan, not a forecast. Change the goals in Settings.",
            f"{days:,} {'day' if days == 1 else 'days'}",
            f"at {daily:,} a day",
        ))

    ledger_btn = (
        f'<button type="button" class="ledger-open-btn" onclick="openLedger(\'{opener}\')" '
        'title="Words written and cut, scene by scene">What changed</button>'
        if goals is not None else ""
    )
    return f"""<section class="card progress-card" aria-labelledby="progressTitle">
        <div class="progress-head">
            <h2 id="progressTitle" class="card-title">Progress</h2>{ledger_btn}
        </div>
        <p class="progress-words"><span class="progress-big">{total_words:,}</span>
            <span class="progress-of">of <button type="button" class="goal-link" onclick="showTab('settings')" title="Change the goal in Settings">{target:,}</button> words{info_tip(total_tip)}</span></p>
        <div class="progress-bar" role="progressbar" aria-label="Book goal" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{min(100, round(percent))}"><span style="width:{min(100, percent):.1f}%"></span></div>
        <p class="progress-caption">{percent:.0f}% of your goal &middot; {scene_count:,} {'scene' if scene_count == 1 else 'scenes'} &middot; about {reading} to read</p>
        {'<div class="progress-stats">' + "".join(stats) + "</div>" if stats else ""}
    </section>"""


def character_name_from_file(path: Path) -> str:
    """The character's name, preferring what the file declares.

    A character file usually carries ``name: White Rabbit`` in frontmatter.
    Deriving the name from the filename instead gave ``White-rabbit``, which
    matches nothing in the prose -- so multi-word characters were silently
    absent from presence and co-occurrence, and the charts came back empty
    without saying why.
    """
    try:
        head = read_repo_text(path)[:400]
    except OSError:
        head = ""
    match = re.search(r"^name:\s*(.+?)\s*$", head, re.M)
    if match:
        declared = match.group(1).strip().strip("\"'")
        if declared:
            return declared
    return path.stem.replace("-", " ").replace("_", " ").title()


def scene_cast(scene: SceneStats, names: list[str]) -> set[str]:
    """Which of *names* are in *scene*.

    A scene's ``characters:`` list says who is in it; without one, a name in
    the prose stands in. ``pov:`` always counts. Counting mentions instead hid
    the narrator of a first-person book, whose name the prose hardly says.
    """
    fm = scene.frontmatter if isinstance(scene.frontmatter, dict) else {}

    def listed(key: str) -> str:
        value = fm.get(key)
        if isinstance(value, (list, tuple)):
            return "\n".join(str(item) for item in value if item is not None)
        return "" if value is None else str(value)

    characters = listed("characters")
    haystack = (characters if characters.strip() else scene.text) + "\n" + listed("pov")
    return {
        name for name in names
        if re.search(rf"\b{re.escape(name)}\b", haystack, re.IGNORECASE)
    }


def _js_json(data: object) -> str:
    """Return a JS expression ``JSON.parse('...')`` that evaluates to *data*.

    Embedding large data as JS object literals causes V8's recursive-descent
    parser to exhaust the JS call stack (RangeError). JSON.parse() is
    implemented in C++ and uses no JS stack depth, so this is the safe way to
    inline large JSON payloads in a <script> tag.

    Escaping applied to the inner string literal:
      1. ``</`` → ``<\\/`` so the HTML parser never sees ``</script>``
      2. ``\\`` → ``\\\\`` so the JS string parser doesn't consume the
         backslashes that JSON.parse needs
      3. ``'`` → ``\\'`` so the single-quoted JS string stays well-formed
    """
    s = json.dumps(data, ensure_ascii=True)
    s = s.replace("</", "<\\/")
    s = s.replace("\\", "\\\\")
    s = s.replace("'", "\\'")
    return f"JSON.parse('{s}')"


def _html_esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _recent_when(iso: str) -> str:
    """``today 18:07``, ``yesterday 09:12`` or ``Oct 3`` for a modification time."""
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    days = (datetime.now(moment.tzinfo).date() - moment.date()).days
    if days == 0:
        return "today " + moment.strftime("%H:%M")
    if days == 1:
        return "yesterday " + moment.strftime("%H:%M")
    return moment.strftime("%b ") + str(moment.day)


def _render_recent_changes_card(
    entries: list[dict[str, object]],
    git_available: bool,
    cfg: Config,
    titles: dict[str, str] | None = None,
) -> str:
    """"Pick up where you left off": the last few scenes, by title, and every
    recently changed file folded away under them."""
    del git_available
    titles = titles or {}
    if not entries:
        return ""

    def when_html(entry: dict[str, object]) -> str:
        when = _recent_when(str(entry.get("modified_at") or ""))
        tag = (
            '<span class="recent-uncommitted" title="Changed since your last commit">not committed</span>'
            if entry.get("uncommitted") else ""
        )
        return f'<span class="recent-meta">{tag}<span class="recent-when">{_html_esc(when)}</span></span>'

    scene_rows: list[str] = []
    for entry in entries:
        scene_path = str(entry.get("scene_path") or "")
        if not (entry.get("is_scene") and scene_path):
            continue
        title = titles.get(scene_path) or Path(scene_path).stem
        folder = Path(scene_path).parent.name
        number = re.fullmatch(r"(?:ch(?:apter)?[-_ ]?)?0*(\d+)", folder, re.IGNORECASE)
        chapter = f"Chapter {number.group(1)}" if number else folder
        scene_rows.append(
            '<li class="recent-row">'
            f'<button type="button" class="recent-scene-link" data-scene-path="{_html_esc(scene_path)}" '
            f'onclick="openSceneModal(this.dataset.scenePath)" title="{_html_esc(scene_path)}">'
            f'{_html_esc(title)}</button>'
            f'<span class="recent-chapter">{_html_esc(chapter)}</span>{when_html(entry)}</li>'
        )
        if len(scene_rows) == 5:
            break

    file_rows: list[str] = []
    for entry in entries[:20]:
        path = str(entry["path"])
        if entry.get("is_scene") and entry.get("scene_path"):
            data_attr = f'data-scene-path="{_html_esc(str(entry["scene_path"]))}"'
            onclick = "openSceneModal(this.dataset.scenePath)"
        else:
            data_attr = f'data-repo-path="{_html_esc(path)}"'
            onclick = "previewRepoFile(this.dataset.repoPath)"
        file_rows.append(
            '<li class="recent-row">'
            f'<button type="button" class="recent-file-link" {data_attr} onclick="{onclick}" '
            f'title="Open {_html_esc(path)}">{_html_esc(path)}</button>{when_html(entry)}</li>'
        )

    scenes_html = (
        f'<ul class="recent-list">{"".join(scene_rows)}</ul>' if scene_rows
        else '<p class="section-note">No scene has changed this week.</p>'
    )
    return (
        '<section class="card recent-card" aria-labelledby="recentTitle">'
        '<div class="card-header"><h2 id="recentTitle" class="card-title">Pick up where you left off</h2></div>'
        f"{scenes_html}"
        '<details class="recent-all"><summary>Every file changed in the last 7 days '
        f'({len(file_rows)})</summary><ul class="recent-list">{"".join(file_rows)}</ul></details>'
        "</section>"
    )


def build_dashboard(
    root: Path,
    cfg: Config | None = None,
    *,
    history_rows: list[HistoryRow] | None = None,
    session_token: str = "",
    static_snapshot: str = "",
    snapshot_meta: dict[str, str] | None = None,
) -> str:
    """Produce the full HTML dashboard for the repo at ``root``.

    ``static_snapshot`` renders the page :mod:`proseview.snapshot` publishes,
    with no server behind it: ``"read-only"``, or ``"demo"``, which also lets
    a visitor try editing with saves that stay in their tab. ``snapshot_meta``
    carries the title, description, address and preview image a snapshot
    gives link previews.
    """
    cfg = cfg or Config.load(root)
    # MATTR/MTLD are read only by the Analysis tab, which fetches them on
    # demand, so a dashboard rebuild no longer pays for that pass.
    scenes = collect_scene_stats(root, cfg.manuscript_subdir, lexical=False)
    display_scenes = sort_scenes(filter_scenes(scenes, "all", cfg), "path", False)
    history = load_history(root, cfg) if history_rows is None else history_rows
    delta = working_copy_delta(root, cfg, history, scenes)
    goals = (
        compute_goals(
            history, cfg, delta,
            total_words=sum(s.words for s in scenes),
            chapter_count=len({s.chapter for s in scenes}),
        )
        if history or delta.words_added_today else None
    )
    tree_nodes = build_tree(root, cfg)
    sidebar_nodes = build_sidebar_tree(root, cfg)
    repository_nodes = build_repository_tree(root, cfg)
    recent_entries, recent_git = recent_changes(root, cfg)
    return render_html_report(
        scenes,
        display_scenes,
        root,
        None,
        cfg,
        goals=goals,
        tree_nodes=tree_nodes,
        sidebar_nodes=sidebar_nodes,
        repository_nodes=repository_nodes,
        recent_entries=recent_entries,
        recent_git=recent_git,
        session_token=session_token,
        static_snapshot=static_snapshot,
        snapshot_meta=snapshot_meta,
    )


def build_scene_data(
    scenes: list[SceneStats],
    root: Path,
    cfg: Config,
    tree_nodes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build the JSON payload consumed by ``/data.json`` and embedded in the
    initial HTML.

    Returns a dict with three keys:

    - ``contents``: ``{display_path: prose_text}`` for the embedded ProseMirror
      editor and the highlight overlays.
    - ``meta``: ``{display_path: scene_meta_dict}`` for the scene header,
      stats grid, todos, notes, and related docs.
    - ``highlightsByPath``: ``{display_path: {paragraphs, highlights}}`` for
      the nine highlight passes.

    The data shape is identical to what the template embeds for first paint,
    so a client can hot-refresh the open scene by fetching ``/data.json``
    without a full page reload.
    """
    if tree_nodes is None:
        tree_nodes = build_tree(root, cfg)

    manuscript_prefix = cfg.manuscript_subdir + "/"

    def clean_path(path: Path) -> str:
        # as_posix, not str: these become keys in the embedded JSON and the
        # fragments of every scene URL. On Windows str() yields backslashes,
        # so the browser looks up "ch01/one.md" against "ch01\\one.md" and
        # finds nothing.
        text = path.as_posix()
        return text[len(manuscript_prefix):] if text.startswith(manuscript_prefix) else text

    def _compute_char_mentions(scene: SceneStats) -> dict[str, dict[str, int]]:
        chars = scene.frontmatter.get("characters") if isinstance(scene.frontmatter, dict) else None
        if not chars:
            return {}
        if not isinstance(chars, (list, tuple)):
            chars = [chars]

        # Speech as every other measure reads it: curly single quotes included.
        dlg_spans = text_dialogue_spans(scene.text)
        mentions: dict[str, dict[str, int]] = {}

        for c in chars:
            if not isinstance(c, str) or not c.strip():
                continue
            c_name = c.strip()
            c_pattern = re.compile(rf"\b{re.escape(c_name)}\b", re.IGNORECASE)
            
            dlg_count = 0
            prose_count = 0
            
            for m in c_pattern.finditer(scene.text):
                start = m.start()
                is_dlg = any(ds <= start < de for ds, de in dlg_spans)
                if is_dlg:
                    dlg_count += 1
                else:
                    prose_count += 1
            
            mentions[c_name] = {"dialogue": dlg_count, "prose": prose_count}
            
        return mentions

    contents = {clean_path(s.path): s.text for s in scenes}
    highlights = {
        clean_path(s.path): compute_scene_highlights(s.text, repeat_terms=s.repetition_examples,
                                                  pov=s.frontmatter.get("pov", ""))
        for s in scenes
    }
    meta = {
        clean_path(scene.path): {
            "title": scene.title,
            "chapter": scene.chapter,
            "repeats": scene.repetition_examples,
            "avg_sent": scene.avg_sentence_words,
            "sent_stdev": scene.sent_len_stdev,
            "dlg_pct": scene.dialogue_pct,
            "first_person": scene.first_person_per_1k,
            "italics": scene.italics_per_1k,
            "questions": scene.questions_per_1k,
            "para_words": scene.avg_paragraph_words,
            "signals": revision_signal(scene, cfg).split(". "),
            "read_min": scene.reading_minutes,
            "words": scene.words,
            "passive": scene.passive_per_1k,
            "crutch": scene.crutch_per_1k,
            "sensory": scene.sensory_density,
            "energy": scene.energy_score,
            "top_dlg": scene.top_dialogue_words,
            "abs_path": str((root / scene.path).resolve()),
            "fm": scene.frontmatter,
            "filters": (
                sum(len(re.findall(rf"\b{verb}\b", scene.text, re.IGNORECASE)) for verb in FILTER_VERBS)
                * 1000 / scene.words
                if scene.words else 0
            ),
            "char_mentions": _compute_char_mentions(scene),
            "related_docs": find_related(scene, cfg, tree_nodes),
            "mattr": scene.mattr,
            "mtld": scene.mtld,
            "todos": scene.todos,
            "notes": scene.notes,
            "txt_line_offset": scene.txt_line_offset,
            "frontmatter_text": scene.frontmatter_text,
            "mtime": (root / scene.path).stat().st_mtime,
            # A stable token for the exact Markdown source that produced the
            # browser's ProseMirror document. Selection offsets belong to that
            # rendered document, not to a server-side Markdown approximation.
            "revision": hashlib.sha256(scene.text.encode("utf-8")).hexdigest(),
        }
        for scene in scenes
    }
    medians = {
        "words": statistics.median([s.words for s in scenes]) if scenes else 0,
        "avg_sent": statistics.median([s.avg_sentence_words for s in scenes]) if scenes else 0.0,
        "sent_stdev": statistics.median([s.sent_len_stdev for s in scenes]) if scenes else 0.0,
        "dlg_pct": statistics.median([s.dialogue_pct for s in scenes]) if scenes else 0.0,
        "sensory": statistics.median([s.sensory_density for s in scenes]) if scenes else 0.0,
        "first_person": statistics.median([s.first_person_per_1k for s in scenes]) if scenes else 0.0,
        "passive": statistics.median([s.passive_per_1k for s in scenes]) if scenes else 0.0,
        "crutch": statistics.median([s.crutch_per_1k for s in scenes]) if scenes else 0.0,
    }

    return {"contents": contents, "meta": meta, "highlightsByPath": highlights, "medians": medians}

def _scene_table_body(
    display_scenes: list[SceneStats],
    root: Path,
    cfg: Config,
    editor_label: str,
    *,
    analysis: bool,
) -> str:
    """Render the scene table rows.

    The Overview's form (``analysis=False``) is a title and a word count, so
    it can be built from a scan that never ran the lexical passes. The
    Analysis tab asks for the full form, with word variety, keywords, the most
    repeated word, dialogue and sentence length.
    """
    manuscript_prefix = cfg.manuscript_subdir + "/"

    def clean_path(path: Path) -> str:
        # as_posix, not str: these become keys in the embedded JSON and the
        # fragments of every scene URL. On Windows str() yields backslashes,
        # so the browser looks up "ch01/one.md" against "ch01\\one.md" and
        # finds nothing.
        text = path.as_posix()
        return text[len(manuscript_prefix):] if text.startswith(manuscript_prefix) else text

    span = 7 if analysis else 2
    body = ""
    last_chapter = None
    # The Overview also shows how far into the book each row ends: the words
    # of every scene up to and including it, in book order.
    running = 0
    for scene in display_scenes:
        if scene.chapter != last_chapter:
            chapter_total = sum(
                current.words for current in display_scenes if current.chapter == scene.chapter
            )
            chapter_label = f"Chapter {scene.chapter}" if scene.chapter.isdigit() else scene.chapter
            body += (
                f'<tr class="ch-row chapter-row">'
                f'<td>{html.escape(chapter_label)}</td><td class="num-col">{chapter_total:,}</td>'
                + (f'<td colspan="{span - 2}"></td>' if span > 2 else "")
                + ("" if analysis else f'<td class="num-col running-col">{running + chapter_total:,}</td>')
                + "</tr>"
            )
            last_chapter = scene.chapter

        display_path = clean_path(scene.path)
        display_path_attr = html.escape(display_path, quote=True)
        todo_count = len(scene.todos)
        note_count = len(scene.notes)
        status_slug = re.sub(r'[^a-z0-9]+', '-', scene.status.lower()) if scene.status else 'unknown'
        # Almost every scene is a draft; a tag on each row said nothing. Only
        # a status that differs from it is worth a tag.
        status_badge = (
            f'<span class="badge status-badge status-{status_slug}">{html.escape(scene.status)}</span> '
            if status_slug not in ("draft", "drafted", "unknown") else ""
        )
        todo_badge = (
            f'<span class="badge todo-badge" title="{todo_count} TODO(s)">{todo_count} todo</span> '
            if todo_count else ''
        )
        note_badge = (
            f'<span class="badge note-badge" title="{note_count} note(s)">{note_count} note</span> '
            if note_count else ''
        )

        outlier = analysis and scene_is_outlier(scene, cfg)
        alert_badge = ""
        if outlier:
            msg = html.escape(revision_signal(scene, cfg), quote=True)
            alert_badge = f'<span class="badge badge-review" title="{msg}" style="cursor:help;">Repeats words</span> '

        style_attrs = (
            f'data-dlg="{scene.dialogue_pct}" data-sent="{scene.avg_sentence_words}" '
            f'data-rep="{scene.repetition_score}" data-review="{1 if outlier else 0}" '
            f'data-words="{scene.words}" '
            if analysis else ""
        )
        body += (
            f'<tr class="scene-row" {style_attrs}'
            f'data-todos="{todo_count}" data-notes="{note_count}" data-status="{status_slug}">'
            f'<td><button type="button" class="scene-table-link" data-scene-path="{display_path_attr}" '
            f'title="{display_path_attr}" '
            f'onclick="openSceneModal(this.dataset.scenePath)">{html.escape(scene.title or display_path)}</button>'
            f'<span class="scene-row-tags">{alert_badge}{status_badge}{todo_badge}{note_badge}</span></td>'
            f'<td class="num-col">{scene.words:,}</td>'
        )
        if not analysis:
            running += scene.words
            body += f'<td class="num-col running-col">{running:,}</td></tr>'
            continue
        # An empty scene has nothing to measure: a dash, not a row of zeros
        # that reads like the worst prose in the book.
        if scene.words <= 0:
            dash = '<td class="num-col"><span class="muted-dash">—</span></td>'
            body += dash + "<td></td><td></td>" + dash + dash + "</tr>"
            continue
        m_pos = goal_position(scene.mattr, cfg.mattr_band)
        l_pos = goal_position(scene.mtld, cfg.mtld_band)
        body += (
            f'<td class="num-col"><span class="badge badge-{m_pos}">{scene.mattr:.3f}</span> '
            f'<span class="badge badge-{l_pos}">{scene.mtld:.0f}</span></td>'
            f'<td class="keywords-col">{html.escape(", ".join(scene.flavor_words))}</td>'
            f'<td><span class="badge {"badge-low" if scene.repetition_score > 25 else ""}">'
            f'{html.escape(scene.repetition_examples[0] if scene.repetition_examples else "")}</span></td>'
            f'<td class="num-col"><span class="badge {"badge-low" if scene.dialogue_pct > 45 else ""}">'
            f"{scene.dialogue_pct:.0f}%</span></td>"
            f'<td class="num-col"><span class="badge {"badge-low" if scene.avg_sentence_words < 8 or scene.avg_sentence_words > 19 else ""}">'
            f"{scene.avg_sentence_words:.1f}</span></td>"
            "</tr>"
        )
    return body


def _analysis_findings(scenes: list[SceneStats], cfg: Config, clean_path) -> list[dict[str, object]]:
    """What the Analysis tab says first, in plain sentences.

    Each finding names its scenes and, where the table can show them, the
    filter that does. Nothing here is a verdict: dialogue-heavy or clipped
    scenes may be exactly what the book wants, so the wording only says what
    the numbers are.
    """
    def plural(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}"

    def names(group: list[SceneStats]) -> list[dict[str, str]]:
        return [{"title": s.title, "path": clean_path(s.path)} for s in group[:6]]

    measured = [s for s in scenes if s.words > 0]
    findings: list[dict[str, object]] = []
    shared: dict[str, list[str]] = {}
    for s in scenes:
        if s.chapter_shared:
            folder = s.path.parent.name
            if folder not in shared.setdefault(s.chapter_shared, []):
                shared[s.chapter_shared].append(folder)
    for name, folders in shared.items():
        count = "Two" if len(folders) == 2 else str(len(folders))
        listed = ", ".join(folders[:-1]) + " and " + folders[-1]
        findings.append({
            "text": f"{count} folders, {listed}, {'both' if len(folders) == 2 else 'all'} say chapter {name}.",
            "tip": "Each folder is shown as its own chapter. Give one of them its own chapter: number "
                   "in its scenes' frontmatter if they are different chapters.",
            "filter": "",
            "scenes": [],
        })
    repeating = [s for s in measured if scene_is_outlier(s, cfg)]
    findings.append({
        "text": (
            f"{plural(len(repeating), 'scene repeats', 'scenes repeat')} words more than is usual for your genre."
            if repeating else "No scene repeats words more than is usual for your genre."
        ),
        "tip": "Measured by word variety. Hover a scene's \u201cRepeats words\u201d tag to see which words.",
        "filter": "review" if repeating else "",
        "scenes": names(repeating),
    })
    talky = [s for s in measured if s.dialogue_pct > 45]
    if talky:
        findings.append({
            "text": f"{plural(len(talky), 'scene is', 'scenes are')} mostly dialogue (over 45% in quotes).",
            "tip": "Not a problem in itself; worth a look if you meant these scenes to slow down.",
            "filter": "talky",
            "scenes": names(talky),
        })
    clipped = [s for s in measured if s.avg_sentence_words < 8]
    if clipped:
        findings.append({
            "text": f"{plural(len(clipped), 'scene has', 'scenes have')} very short sentences (under 8 words on average).",
            "tip": "Short sentences speed a scene up; a run of them can read as clipped.",
            "filter": "clipped",
            "scenes": names(clipped),
        })
    empty = [s for s in scenes if s.words <= 0]
    if empty:
        findings.append({
            "text": f"{plural(len(empty), 'scene has', 'scenes have')} no prose yet.",
            "tip": "TODO and NOTE comments don't count as prose.",
            "filter": "",
            "scenes": names(empty),
        })
    return findings


def build_analysis_payload(root: Path, cfg: Config | None = None) -> dict[str, object]:
    """Everything the Analysis tab needs, computed on demand.

    This is the expensive half of the old dashboard: the lexical and style
    passes over every scene, which cost roughly 60% of a full build. Nothing on
    the Overview tab reads any of it, so it is no longer paid on every rebuild.
    """
    cfg = cfg or Config.load(root)
    scenes = collect_scene_stats(root, cfg.manuscript_subdir, lexical=True)
    display_scenes = sort_scenes(filter_scenes(scenes, "all", cfg), "path", False)

    manuscript_prefix = cfg.manuscript_subdir + "/"

    def clean_path(path: Path) -> str:
        # as_posix, not str: these become keys in the embedded JSON and the
        # fragments of every scene URL. On Windows str() yields backslashes,
        # so the browser looks up "ch01/one.md" against "ch01\\one.md" and
        # finds nothing.
        text = path.as_posix()
        return text[len(manuscript_prefix):] if text.startswith(manuscript_prefix) else text

    chapters = sorted({scene.chapter for scene in scenes})



    lexical = calculate_lexical_stats("\n\n".join(scene.text for scene in scenes))

    def get_pct(value: float, minimum: float, maximum: float) -> float:
        return max(0, min(100, (value - minimum) / (maximum - minimum) * 100))

    m_start = get_pct(cfg.mattr_band[0], 0.65, 0.85)
    l_start = get_pct(cfg.mtld_band[0], 50, 180)

    return {
        "findings": _analysis_findings(scenes, cfg, clean_path),
        "tableBody": _scene_table_body(
            display_scenes, root, cfg, _editor_label(cfg), analysis=True
        ),
        # Same shapes the template used to inject, so the existing Chart.js
        # setup in 70-dashboard.js builds them without changes.
        "scatterChart": {
            "datasets": [
                {
                    "data": [
                        {"x": scene.mattr, "y": scene.mtld, "label": clean_path(scene.path)}
                        for scene in scenes
                        if scene.words > 0
                    ]
                }
            ],
            "bands": {"mattr": list(cfg.mattr_band), "mtld": list(cfg.mtld_band)},
        },
        "lexical": {
            "mattrText": f"{lexical.mattr * 100:.1f}%",
            "mattrZoneLeft": f"{m_start:.1f}",
            # The bands are floors: everything from the low end up is healthy.
            "mattrZoneWidth": f"{100 - m_start:.1f}",
            "mattrMarkerLeft": f"{get_pct(lexical.mattr, 0.65, 0.85):.1f}",
            "mtldText": f"{int(lexical.mtld)} words",
            "mtldZoneLeft": f"{l_start:.1f}",
            "mtldZoneWidth": f"{100 - l_start:.1f}",
            "mtldMarkerLeft": f"{get_pct(lexical.mtld, 50, 180):.1f}",
            # The manuscript's own median, which the code has always computed
            # and always discarded. It is the more useful of the two references
            # for revision: it says which scenes are unusual *for this book*,
            # which is a question the genre band cannot answer.
            "mtldMedian": scene_mtld_median(scenes),
            "mattrMedian": scene_mattr_median(scenes),
            "mtldMedianText": f"{int(scene_mtld_median(scenes))} words",
            "mattrMedianText": f"{scene_mattr_median(scenes) * 100:.1f}%",
            "mtldBand": [cfg.mtld_band[0], cfg.mtld_band[1]],
            "genreLabel": GENRE_LABELS.get(cfg.genre, cfg.genre),
        },
    }


def render_html_report(
    scenes: list[SceneStats],
    display_scenes: list[SceneStats],
    root: Path,
    baseline: BaselineStats | None,
    cfg: Config | None = None,
    *,
    goals: Goals | None = None,
    tree_nodes: list[dict[str, object]] | None = None,
    sidebar_nodes: list[dict[str, object]] | None = None,
    repository_nodes: list[dict[str, object]] | None = None,
    recent_entries: list[dict[str, object]] | None = None,
    recent_git: bool | None = None,
    session_token: str = "",
    static_snapshot: str = "",
    snapshot_meta: dict[str, str] | None = None,
) -> str:
    del baseline

    cfg = cfg or Config.load(root)
    if tree_nodes is None:
        tree_nodes = build_tree(root, cfg)
    if sidebar_nodes is None:
        sidebar_nodes = build_sidebar_tree(root, cfg)
    if repository_nodes is None:
        repository_nodes = build_repository_tree(root, cfg)
    if recent_entries is None:
        recent_entries, recent_git = recent_changes(root, cfg)
    elif recent_git is None:
        recent_git = True
    manuscript_prefix = cfg.manuscript_subdir + "/"
    scene_titles = {
        (s.path.as_posix()[len(manuscript_prefix):] if s.path.as_posix().startswith(manuscript_prefix)
         else s.path.as_posix()): s.title
        for s in scenes
    }
    recent_card = _render_recent_changes_card(recent_entries, bool(recent_git), cfg, scene_titles)
    if static_snapshot:
        # What the author touched this week, and what they have not
        # committed, is not something a reader of a published copy acts on.
        recent_card = ""

    total_words = sum(s.words for s in scenes)

    def clean_path(path: Path) -> str:
        # as_posix, not str: these become keys in the embedded JSON and the
        # fragments of every scene URL. On Windows str() yields backslashes,
        # so the browser looks up "ch01/one.md" against "ch01\\one.md" and
        # finds nothing.
        text = path.as_posix()
        return text[len(manuscript_prefix):] if text.startswith(manuscript_prefix) else text

    scene_data = build_scene_data(scenes, root, cfg, tree_nodes)
    scene_content_map = scene_data["contents"]
    highlights_map = scene_data["highlightsByPath"]
    scene_meta_map = scene_data["meta"]
    medians_map = scene_data["medians"]
    ordered_paths = [clean_path(s.path) for s in display_scenes]

    char_dir = root / cfg.characters_dir
    char_bio_map: dict[str, str] = {}
    if char_dir.exists():
        for path in char_dir.glob("*.md"):
            char_bio_map[path.stem.lower()] = read_repo_text(path)

    # Reading order, not alphabetical: chapter names such as "IX. ..." sort
    # before "V. ..." as text, which put the presence chart out of order.
    chapters = list(dict.fromkeys(s.chapter for s in display_scenes))
    if cfg.characters:
        char_names = [c.strip() for c in cfg.characters if c.strip()]
    elif char_dir.exists():
        char_names = [character_name_from_file(p) for p in sorted(char_dir.glob("*.md"))]
    else:
        char_names = []

    casts = {id(scene): scene_cast(scene, char_names) for scene in scenes}
    presence_data: list[dict[str, object]] = []
    for name in char_names:
        chapter_scenes = [
            sum(1 for s in scenes if s.chapter == chapter and name in casts[id(s)])
            for chapter in chapters
        ]
        if sum(chapter_scenes) > 0:
            presence_data.append({"label": name, "data": chapter_scenes, "fill": False, "tension": 0})
    presence_data = sorted(presence_data, key=lambda row: sum(row["data"]), reverse=True)[:12]

    location_counts: Counter[str] = Counter()
    for scene in scenes:
        location_counts[scene.location] += scene.words
    top_locs = location_counts.most_common(8)

    co_occur: dict[tuple[str, str], int] = defaultdict(int)
    for scene in scenes:
        present = [name for name in char_names if name in casts[id(scene)]]
        for i, first in enumerate(present):
            for second in present[i + 1:]:
                co_occur[tuple(sorted((first, second)))] += 1
    top_pairs = sorted(co_occur.items(), key=lambda item: item[1], reverse=True)[:15]

    editor_label = _editor_label(cfg)
    if static_snapshot and goals is not None:
        # Which scenes the author cut today is not for a published copy.
        goals = dataclasses.replace(goals, ledger=None)
    progress_card = _render_progress_card(goals, cfg, total_words=total_words, scene_count=len(scenes))

    table_body = _scene_table_body(display_scenes, root, cfg, editor_label, analysis=False)

    context = {
        "app_css": _load_app_css(),
        "app_js": _load_app_js(),
        "scene_count": len(scenes),
        "progress_card": progress_card,
        "recent_changes_card": recent_card,
        "table_body": table_body,
        "editor_label": editor_label,
        "contents_json": _js_json(scene_content_map),
        "bios_json": _js_json(char_bio_map),
        "meta_json": _js_json(scene_meta_map),
        "medians_json": _js_json(medians_map),
        "paths_json": _js_json(ordered_paths),
        "highlights_json": _js_json(highlights_map),
        "editor_scheme_json": _js_json(cfg.editor.scheme),
        "editor_url_template_json": _js_json(cfg.editor.url_template),
        "editor_label_json": _js_json(editor_label),
        # Names "Reveal in Finder" for the computer the server runs on.
        "host_platform_json": _js_json(sys.platform),
        "repo_tree_json": _js_json(tree_nodes),
        "sidebar_tree_json": _js_json(sidebar_nodes),
        # No manuscript/ folder: the whole folder is the manuscript, so new
        # files can go at its top level.
        "sidebar_whole_folder_json": _js_json(lists_whole_folder(root, cfg)),
        # No manuscript folder: the folder opens as plain Markdown, and the
        # book features wait for the writer to say where the book is.
        "manuscript_missing": manuscript_missing(root, cfg.manuscript_subdir),
        "manuscript_path_text": cfg.manuscript_subdir,
        "repository_tree_json": _js_json(repository_nodes),
        "repo_preview_max": cfg.repo_tab.preview_max_bytes,
        "images_config_json": _js_json(
            {"mode": cfg.images.mode, "remoteInAgentOutput": cfg.images.remote_in_agent_output}
        ),
        "discuss_presets_json": _js_json(list(cfg.discuss.selection_presets)),
        # Which agent tab the dock opens on. Both tabs always exist; live
        # availability is fetched from /api/discuss/agents once the page runs.
        "discuss_default_agent_json": _js_json(cfg.discuss.agent),
        "lexical_bands_json": _js_json({"mattr": list(cfg.mattr_band), "mtld": list(cfg.mtld_band)}),
        "pass_order_json": _js_json(list(PASS_NAMES)),
        "presence_chart_json": _js_json({
            # The axis already says Chapter.
            "labels": [c.removeprefix("Chapter ") for c in chapters], "datasets": presence_data,
        }),
        "location_chart_json": _js_json(
            {"labels": [name for name, _ in top_locs], "datasets": [{"data": [words for _, words in top_locs]}]}
        ),
        "cooccur_chart_json": _js_json(
            {
                "labels": [f"{pair[0]}+{pair[1]}" for pair, _ in top_pairs],
                "datasets": [{"label": "Shared Scenes", "data": [count for _, count in top_pairs]}],
            }
        ),
        "skills_json": _js_json(_load_skills(root, cfg.skills_dir)),
        "story_json": _js_json(story_payload(scenes, cfg)),
        "session_token_json": json.dumps(session_token),
        "static_snapshot": static_snapshot,
        "snapshot_meta": snapshot_meta,
        "config_json": _js_json(dataclasses.asdict(cfg)),
        # Each callout type's background per theme, and the types the
        # editor offers: GitHub's and the ones the config colours.
        "callout_css": screen_css(screen_colours(cfg.callouts)),
        "callout_types": list(dict.fromkeys([*GITHUB_TYPES, *(kind for kind, _ in cfg.callouts)])),
        "cfg": cfg,
        "config_exists": (root / ".proseview.yaml").exists(),
        "repo_root_json": _js_json(str(root.resolve())),
        "yaml_editor_url": _editor_url(cfg, str((root / ".proseview.yaml").resolve())),
    }
    return _render_template("index.html.j2", **context)


def _load_skills(root: Path, skills_subdir: str = ".proseview/skills") -> list[dict]:
    skills_dir = root / skills_subdir
    if not skills_dir.exists():
        return []

    def _parse_yaml_block(text: str) -> dict:
        """Parse a simple nested YAML block (one level of indentation only)."""
        result: dict = {}
        section: str | None = None
        for line in text.splitlines():
            top = re.match(r'^(\w[\w-]*):\s*$', line)
            if top:
                section = top.group(1)
                result[section] = {}
                continue
            nested = re.match(r'^  (\w[\w_-]*):\s*"?(.*?)"?\s*$', line)
            if nested and section and isinstance(result.get(section), dict):
                result[section][nested.group(1)] = nested.group(2)
                continue
            flat = re.match(r'^(\w[\w-]*):\s*(.+)$', line)
            if flat:
                result[flat.group(1)] = flat.group(2).strip().strip('"')
        return result

    skills = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        raw = read_repo_text(skill_md)
        fm_match = re.match(r'^---\n(.*?)\n---', raw, re.DOTALL)
        name = skill_dir.name
        if fm_match:
            fm = _parse_yaml_block(fm_match.group(1))
            name = fm.get("name", name)

        display_name = name
        short_description = ""
        default_prompt = ""
        openai_yaml = skill_dir / "agents" / "openai.yaml"
        if openai_yaml.exists():
            oy = _parse_yaml_block(read_repo_text(openai_yaml))
            iface = oy.get("interface", {})
            if isinstance(iface, dict):
                display_name = iface.get("display_name", display_name)
                short_description = iface.get("short_description", short_description)
                default_prompt = iface.get("default_prompt", default_prompt)

        skills.append({
            "name": name,
            "display_name": display_name,
            "short_description": short_description,
            "default_prompt": default_prompt,
            "type": "snippet" if name.startswith("snippet-") else "scene",
        })
    return skills
