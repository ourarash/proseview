"""Write the dashboard as static files: readable anywhere, editable nowhere.

A snapshot is the page the server renders, plus the few reads it makes after
loading, written beside it as files so any static host can serve them -- the
hosted demo is one, a folder handed to a beta reader is another. Nothing that
writes, talks to an agent, or reads history is offered; the page knows it is a
snapshot and says so (``01-static-snapshot.js``).

It also leaves the machine that built it, so the repository's absolute path is
replaced by its folder name everywhere it appears, and the build stops rather
than publish a copy that still names it.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from .config import Config
from .generator import TEMPLATE_DIR, build_analysis_payload, build_dashboard
from .lexical import calculate_lexical_stats
from .scenes import collect_scene_stats, extract_scene_text, split_frontmatter

#: Written into every snapshot, so a rebuild may clear the folder it finds and
#: nothing else ever is.
MARKER = ".proseview-snapshot"


class SnapshotError(RuntimeError):
    pass


def _path_forms(path: str) -> list[str]:
    """Every spelling of *path* the page can carry: raw, in a JSON string, in
    the JS string literal ``_js_json`` wraps JSON in, and HTML-escaped."""
    in_json = json.dumps(path)[1:-1]
    in_js_literal = in_json.replace("\\", "\\\\").replace("'", "\\'")
    return list(dict.fromkeys([in_js_literal, in_json, html.escape(path), path]))


def _scrubbed(text: str, root: Path) -> str:
    stand_in = "/" + root.name
    for spelling in (str(root), root.as_posix()):
        for form in _path_forms(spelling):
            text = text.replace(form, stand_in)
    return text


def _scene_lexical(root: Path, cfg: Config) -> dict[str, dict[str, object]]:
    """What ``/api/scene/lexical`` answers, for every scene, keyed as asked.

    The page names a scene by its path with the manuscript folder stripped
    when it has one, so the keys are spelled the same way.
    """
    prefix = cfg.manuscript_subdir + "/"
    rows: dict[str, dict[str, object]] = {}
    for scene in collect_scene_stats(root, cfg, lexical=False):
        key = scene.path.as_posix()
        key = key[len(prefix):] if key.startswith(prefix) else key
        _, body = split_frontmatter((root / scene.path).read_text(encoding="utf-8"))
        stats = calculate_lexical_stats(extract_scene_text(body))
        rows[key] = {"ok": True, "mattr": stats.mattr, "mtld": stats.mtld}
    return rows


def _prepare_output(root: Path, out: Path) -> None:
    if out == root or root in out.parents:
        raise SnapshotError(
            f"{out} is inside the repository; write the snapshot outside it, "
            "or the next one would include this one"
        )
    if out.exists():
        if not out.is_dir():
            raise SnapshotError(f"{out} exists and is not a folder")
        if any(out.iterdir()) and not (out / MARKER).is_file():
            raise SnapshotError(
                f"{out} is not a Proseview snapshot and is not empty; "
                "choose an empty or new folder"
            )
        shutil.rmtree(out)
    out.mkdir(parents=True)


def write_snapshot(root: Path, out: Path, cfg: Config | None = None, *, demo: bool = False) -> Path:
    """Write a copy of *root*'s dashboard into *out* and return it.

    The copy is read-only. ``demo`` lets a visitor try edit mode as well; what
    they save stays in their tab, since there is nowhere else for it to go.
    """
    root = root.resolve()
    out = out.resolve()
    cfg = cfg or Config.load(root)
    _prepare_output(root, out)

    files = {
        "index.html": build_dashboard(root, cfg, static_snapshot="demo" if demo else "read-only"),
        "analysis.json": json.dumps(build_analysis_payload(root, cfg)),
        "scene-lexical.json": json.dumps(_scene_lexical(root, cfg)),
    }
    for name, text in files.items():
        text = _scrubbed(text, root)
        leaked = next((form for form in _path_forms(str(root)) if form in text), None)
        if leaked:
            raise SnapshotError(f"{name} would publish the repository path {root}")
        (out / name).write_text(text, encoding="utf-8")
    shutil.copytree(TEMPLATE_DIR / "vendor", out / "vendor")
    (out / MARKER).write_text("Written by `proseview snapshot`; safe to replace.\n", encoding="utf-8")
    return out
