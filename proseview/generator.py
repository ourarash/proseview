"""HTML dashboard generator.

Public entry: :func:`build_dashboard`. Takes a repo root and a
:class:`~proseview.config.Config`, returns the single-file HTML string that
``.proseview/stats.html`` is written from.

The dashboard is emitted as one self-contained HTML file, but the source is
split into a Jinja template plus inlined CSS and JavaScript assets under
``proseview/templates/``.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .editor import build_url as _editor_url, label as _editor_label
from .goals import Goals, compute_goals
from .highlights import PASS_NAMES, compute_scene_highlights
from .history import HistoryRow, load_history, working_copy_delta
from .lexical import FILTER_VERBS, calculate_lexical_stats
from .related import find_related
from .repo import build_sidebar_tree, build_tree, recent_changes
from .scenes import (
    BaselineStats,
    SceneStats,
    collect_scene_stats,
    filter_scenes,
    goal_position,
    revision_signal,
    scene_is_outlier,
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


def _render_template(name: str, **context: object) -> str:
    return _template_env().get_template(name).render(**context)


def _render_goals_sections(goals: Goals | None, cfg: Config) -> tuple[str, str]:
    """Return (banner_fragment, card_fragment). Both are empty strings when
    ``goals`` is ``None`` (non-git repo or no history), which hides the Goals
    panel entirely while keeping the surrounding layout intact.
    """
    if goals is None:
        return "", ""

    banner = (
        '<div class="banner-stat" style="margin-left:30px;">'
        '<span class="label">Added Today</span>'
        f'<span class="value">+{goals.words_added_today:,}</span>'
        "</div>"
    )

    chapter_target = goals.per_chapter_target or 1
    chapter_pct = min(100, goals.per_chapter_current / chapter_target * 100) if chapter_target else 0
    card = f"""<div class="card">
        <div class="card-header"><span class="card-title">Goals</span></div>
        <div class="goals-grid">
            <div class="goal-metric">
                <span class="goal-value">{goals.rolling_velocity:.0f}</span>
                <span class="goal-label">Rolling 7-day velocity</span>
                <span class="goal-sub">target: {cfg.daily_target:,} words/day</span>
            </div>
            <div class="goal-metric">
                <span class="goal-value">{goals.streak_days}</span>
                <span class="goal-label">Writing streak</span>
                <span class="goal-sub">consecutive days</span>
            </div>
            <div class="goal-metric">
                <span class="goal-value">{goals.scenes_touched_today}</span>
                <span class="goal-label">Scenes touched today</span>
                <span class="goal-sub">uncommitted + today's commits</span>
            </div>
            <div class="goal-metric">
                <span class="goal-value">{goals.per_chapter_current:,}</span>
                <span class="goal-label">Per-chapter average</span>
                <span class="goal-sub">target: {goals.per_chapter_target:,}</span>
                <div class="range-bar" style="margin-top:6px;">
                    <div class="target-zone" style="width:{chapter_pct:.1f}%;"></div>
                </div>
            </div>
        </div>
    </div>"""
    return banner, card


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


def _js_attr(s: str) -> str:
    """Escape ``s`` for use inside a single-quoted JS string in an HTML attribute."""
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def _render_recent_changes_card(
    entries: list[dict[str, object]],
    git_available: bool,
    cfg: Config,
) -> str:
    """Return the Recently Modified card wrapped in a full-width grid row."""
    editor_label = _editor_label(cfg)

    if not git_available:
        inner = "<p>Git is not available; recent changes cannot be determined.</p>"
    elif not entries:
        inner = "<p>No files changed in the last 7 days.</p>"
    else:
        rows: list[str] = []
        for entry in entries[:20]:
            path = str(entry["path"])
            abs_path = str(entry["abs_path"])
            editor_url = _editor_url(cfg, abs_path)
            open_btn = (
                f'<a class="editor-btn" href="{_html_esc(editor_url)}" target="_blank">'
                f"&#x2197; {_html_esc(editor_label)}</a>"
            )
            if entry.get("is_scene") and entry.get("scene_path"):
                sp = _js_attr(str(entry["scene_path"]))
                onclick = f"openSceneModal('{sp}')"
            else:
                pp = _js_attr(path)
                onclick = f"previewRepoFile('{pp}')"
            path_link = (
                f'<button type="button" class="recent-file-link" '
                f'onclick="{onclick}" title="Open {_html_esc(path)}">'
                f"{_html_esc(path)}</button>"
            )
            rows.append(
                f'<div style="display:flex; align-items:center; justify-content:space-between;'
                f' padding:10px 0; border-bottom:1px solid var(--border);">'
                f"{path_link}"
                f'<span style="flex-shrink:0; margin-left:12px;">{open_btn}</span>'
                f"</div>"
            )
        inner = "".join(rows)

    card = (
        '<div class="card">'
        '<div class="card-header">'
        '<span class="card-title">Recently Modified</span>'
        '<span style="font-size:11px; color:var(--text-muted); margin-left:8px;">last 7 days</span>'
        "</div>"
        f"{inner}"
        "</div>"
    )
    return f'<div class="dashboard-grid" style="grid-template-columns: 1fr;">{card}</div>'


def build_dashboard(
    root: Path,
    cfg: Config | None = None,
    *,
    history_rows: list[HistoryRow] | None = None,
) -> str:
    """Produce the full HTML dashboard for the repo at ``root``."""
    cfg = cfg or Config.load(root)
    scenes = collect_scene_stats(root, cfg.manuscript_subdir)
    display_scenes = sort_scenes(filter_scenes(scenes, "all", cfg), "path", False)
    history = load_history(root, cfg) if history_rows is None else history_rows
    delta = working_copy_delta(root, cfg, history)
    goals = compute_goals(history, cfg, delta) if history or delta.words_added_today else None
    tree_nodes = build_tree(root, cfg)
    sidebar_nodes = build_sidebar_tree(root, cfg)
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
        recent_entries=recent_entries,
        recent_git=recent_git,
    )


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
    recent_entries: list[dict[str, object]] | None = None,
    recent_git: bool | None = None,
) -> str:
    del baseline

    cfg = cfg or Config.load(root)
    if tree_nodes is None:
        tree_nodes = build_tree(root, cfg)
    if sidebar_nodes is None:
        sidebar_nodes = build_sidebar_tree(root, cfg)
    if recent_entries is None:
        recent_entries, recent_git = recent_changes(root, cfg)
    elif recent_git is None:
        recent_git = True
    recent_card = _render_recent_changes_card(recent_entries, bool(recent_git), cfg)

    target_words = cfg.target_words
    daily_target = cfg.daily_target
    total_words = sum(s.words for s in scenes)
    all_text = "\n".join(s.text for s in scenes)
    lexical = calculate_lexical_stats(all_text)
    percent_target = (total_words / target_words * 100) if target_words else 0.0
    days_to_finish = math.ceil(max(0, target_words - total_words) / daily_target) if daily_target else 0

    manuscript_prefix = cfg.manuscript_subdir + "/"

    def clean_path(path: Path) -> str:
        text = str(path)
        return text[len(manuscript_prefix):] if text.startswith(manuscript_prefix) else text

    ordered_paths = [clean_path(s.path) for s in display_scenes]
    scene_content_map = {clean_path(s.path): s.text for s in scenes}
    highlights_map = {
        clean_path(s.path): compute_scene_highlights(
            s.text,
            repeat_terms=s.repetition_examples,
        )
        for s in scenes
    }

    char_dir = root / cfg.characters_dir
    char_bio_map: dict[str, str] = {}
    if char_dir.exists():
        for path in char_dir.glob("*.md"):
            char_bio_map[path.stem.lower()] = path.read_text(encoding="utf-8")

    chapters = sorted({s.chapter for s in scenes})
    if cfg.characters:
        char_names = [c.strip() for c in cfg.characters if c.strip()]
    elif char_dir.exists():
        char_names = [path.stem.capitalize() for path in sorted(char_dir.glob("*.md"))]
    else:
        char_names = []

    presence_data: list[dict[str, object]] = []
    for name in char_names:
        chapter_mentions = [
            len(
                re.findall(
                    rf"\b{re.escape(name)}\b",
                    "\n".join(s.text for s in scenes if s.chapter == chapter),
                    re.IGNORECASE,
                )
            )
            for chapter in chapters
        ]
        if sum(chapter_mentions) > 0:
            presence_data.append({"label": name, "data": chapter_mentions, "fill": False, "tension": 0.3})
    presence_data = sorted(presence_data, key=lambda row: sum(row["data"]), reverse=True)[:12]

    rhythm_vals = [
        sum(s.sent_len_stdev for s in scenes if s.chapter == chapter)
        / max(1, len([s for s in scenes if s.chapter == chapter]))
        for chapter in chapters
    ]
    location_counts: Counter[str] = Counter()
    for scene in scenes:
        location_counts[scene.location] += scene.words
    top_locs = location_counts.most_common(8)

    co_occur: dict[tuple[str, str], int] = defaultdict(int)
    for scene in scenes:
        present = [
            name
            for name in char_names
            if re.search(rf"\b{re.escape(name)}\b", scene.text, re.IGNORECASE)
        ]
        for i, first in enumerate(present):
            for second in present[i + 1:]:
                co_occur[tuple(sorted((first, second)))] += 1
    top_pairs = sorted(co_occur.items(), key=lambda item: item[1], reverse=True)[:15]

    scene_meta_map = {
        clean_path(scene.path): {
            "repeats": scene.repetition_examples,
            "avg_sent": scene.avg_sentence_words,
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
                * 1000
                / scene.words
                if scene.words
                else 0
            ),
            "related_docs": find_related(scene, cfg, tree_nodes),
            "todos": scene.todos,
            "notes": scene.notes,
            "txt_line_offset": scene.txt_line_offset,
            "mtime": (root / scene.path).stat().st_mtime,
        }
        for scene in scenes
    }

    flagged = sort_scenes(
        [scene for scene in scenes if scene_is_outlier(scene, cfg)],
        "severity",
        True,
        cfg,
    )
    scatter_data = [{"x": scene.mattr, "y": scene.mtld, "label": clean_path(scene.path)} for scene in scenes]

    def get_pct(value: float, minimum: float, maximum: float) -> float:
        return max(0, min(100, (value - minimum) / (maximum - minimum) * 100))

    m_start = get_pct(cfg.mattr_band[0], 0.65, 0.85)
    m_width = get_pct(cfg.mattr_band[1], 0.65, 0.85) - m_start
    l_start = get_pct(cfg.mtld_band[0], 50, 180)
    l_width = get_pct(cfg.mtld_band[1], 50, 180) - l_start

    editor_label = _editor_label(cfg)
    goals_banner_html, goals_card_html = _render_goals_sections(goals, cfg)
    goals_card_wrapper = (
        f'<div class="dashboard-grid" style="grid-template-columns: 1fr;">{goals_card_html}</div>'
        if goals_card_html
        else ""
    )

    alerts_html = (
        "".join(
            [
                f'<div class="alert-item" onclick="openSceneModal(\'{clean_path(scene.path)}\')">'
                f'<div class="alert-path">{clean_path(scene.path)}</div>'
                f'<div class="alert-msg">{revision_signal(scene, cfg)}</div></div>'
                for scene in flagged[:8]
            ]
        )
        if flagged
        else "<p>No urgent issues detected.</p>"
    )

    table_body = ""
    last_chapter = None
    for scene in display_scenes:
        if scene.chapter != last_chapter:
            chapter_total = sum(current.words for current in display_scenes if current.chapter == scene.chapter)
            table_body += (
                f'<tr class="ch-row chapter-row">'
                f'<td colspan="2">{scene.chapter}</td><td>{chapter_total:,}</td><td colspan="5"></td></tr>'
            )
            last_chapter = scene.chapter
        m_pos = goal_position(scene.mattr, cfg.mattr_band)
        l_pos = goal_position(scene.mtld, cfg.mtld_band)
        display_path = clean_path(scene.path)
        editor_url = _editor_url(cfg, str((root / scene.path).resolve()))
        variety = (
            f'<span class="badge badge-{m_pos}">{scene.mattr:.3f}</span> '
            f'<span class="badge badge-{l_pos}">{scene.mtld:.1f}</span>'
        )
        todo_count = len(scene.todos)
        note_count = len(scene.notes)
        status_slug = re.sub(r'[^a-z0-9]+', '-', scene.status.lower()) if scene.status else 'unknown'
        status_badge = f'<span class="badge status-badge status-{status_slug}">{scene.status}</span> '
        todo_badge = (
            f'<span class="badge todo-badge" title="{todo_count} TODO(s)">{todo_count} todo</span> '
            if todo_count else ''
        )
        note_badge = (
            f'<span class="badge note-badge" title="{note_count} note(s)">{note_count} note</span> '
            if note_count else ''
        )
        table_body += (
            f'<tr class="scene-row" data-dlg="{scene.dialogue_pct}" '
            f'data-sent="{scene.avg_sentence_words}" data-rep="{scene.repetition_score}" '
            f'data-todos="{todo_count}" data-notes="{note_count}" data-status="{status_slug}">'
            f'<td><span style="color:var(--primary); font-weight:600; cursor:pointer;" '
            f'onclick="openSceneModal(\'{display_path}\')">{display_path}</span>'
            f'{status_badge}{todo_badge}{note_badge}'
            f'<a class="editor-btn" href="{editor_url}" title="Open in {editor_label}" '
            f'onclick="event.stopPropagation()">\u2197 {editor_label}</a></td>'
            f'<td><span style="font-size:11px; opacity:0.7;">{scene.chapter}</span></td>'
            f'<td style="font-weight:600;">{scene.words:,}</td>'
            f"<td>{variety}</td>"
            f'<td><span style="font-size:10px; color:var(--text-muted); font-style:italic;">'
            f'{", ".join(scene.flavor_words)}</span></td>'
            f'<td><span class="badge {"badge-danger" if scene.repetition_score > 25 else ""}">'
            f'{scene.repetition_examples[0] if scene.repetition_examples else ""}</span></td>'
            f'<td><span class="badge {"badge-danger" if scene.dialogue_pct > 45 else ("badge-low" if scene.dialogue_pct < 8 else "")}">'
            f"{scene.dialogue_pct:.1f}%</span></td>"
            f'<td><span class="badge {"badge-high" if scene.avg_sentence_words > 19 else ("badge-low" if scene.avg_sentence_words < 8 else "")}">'
            f"{scene.avg_sentence_words:.1f}</span></td></tr>"
        )

    context = {
        "app_css": _load_asset("assets/app.css"),
        "app_js": _load_asset("assets/app.js"),
        "total_words_text": f"{total_words:,}",
        "target_words_text": f"{target_words:,}",
        "percent_target_text": f"{percent_target:.1f}",
        "percent_target_width": f"{min(100, percent_target):.1f}",
        "scene_count": len(scenes),
        "days_to_finish": days_to_finish,
        "goals_banner_html": goals_banner_html,
        "goals_card_wrapper": goals_card_wrapper,
        "recent_changes_card": recent_card,
        "alerts_html": alerts_html,
        "lexical_mattr_text": f"{lexical.mattr:.3f}",
        "lexical_mattr_zone_left": f"{m_start:.1f}",
        "lexical_mattr_zone_width": f"{m_width:.1f}",
        "lexical_mattr_marker_left": f"{get_pct(lexical.mattr, 0.65, 0.85):.1f}",
        "lexical_mtld_text": f"{lexical.mtld:.1f}",
        "lexical_mtld_zone_left": f"{l_start:.1f}",
        "lexical_mtld_zone_width": f"{l_width:.1f}",
        "lexical_mtld_marker_left": f"{get_pct(lexical.mtld, 50, 180):.1f}",
        "table_body": table_body,
        "editor_label": editor_label,
        "contents_json": _js_json(scene_content_map),
        "bios_json": _js_json(char_bio_map),
        "meta_json": _js_json(scene_meta_map),
        "paths_json": _js_json(ordered_paths),
        "highlights_json": _js_json(highlights_map),
        "editor_scheme_json": json.dumps(cfg.editor.scheme),
        "editor_url_template_json": json.dumps(cfg.editor.url_template),
        "editor_label_json": json.dumps(editor_label),
        "repo_tree_json": _js_json(tree_nodes),
        "sidebar_tree_json": _js_json(sidebar_nodes),
        "repo_preview_max": cfg.repo_tab.preview_max_bytes,
        "pass_order_json": _js_json(list(PASS_NAMES)),
        "presence_chart_json": _js_json({"labels": chapters, "datasets": presence_data}),
        "rhythm_chart_json": _js_json(
            {
                "labels": chapters,
                "datasets": [{"label": "Sentence Var (Stdev)", "data": rhythm_vals, "fill": False, "tension": 0.4}],
            }
        ),
        "location_chart_json": _js_json(
            {"labels": [name for name, _ in top_locs], "datasets": [{"data": [words for _, words in top_locs]}]}
        ),
        "cooccur_chart_json": _js_json(
            {
                "labels": [f"{pair[0]}+{pair[1]}" for pair, _ in top_pairs],
                "datasets": [{"label": "Shared Scenes", "data": [count for _, count in top_pairs]}],
            }
        ),
        "scatter_chart_json": _js_json(
            {
                "datasets": [{"data": scatter_data}],
                "bands": {"mattr": list(cfg.mattr_band), "mtld": list(cfg.mtld_band)},
            }
        ),
        "skills_json": _js_json(_load_skills(root, cfg.skills_dir)),
    }
    return _render_template("index.html.j2", **context)


def _load_skills(root: Path, skills_subdir: str = "skills") -> list[dict]:
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
        raw = skill_md.read_text(encoding="utf-8")
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
            oy = _parse_yaml_block(openai_yaml.read_text(encoding="utf-8"))
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
