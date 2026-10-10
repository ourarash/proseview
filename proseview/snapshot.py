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
from .lexical import calculate_lexical_stats, prose_only
from .repo import read_repo_text
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


def _scene_lexical(root: Path, cfg: Config, scenes: list) -> dict[str, dict[str, object]]:
    """What ``/api/scene/lexical`` answers, for every scene, keyed as asked.

    The page names a scene by its path with the manuscript folder stripped
    when it has one, so the keys are spelled the same way.
    """
    prefix = cfg.manuscript_subdir + "/"
    rows: dict[str, dict[str, object]] = {}
    for scene in scenes:
        key = scene.path.as_posix()
        key = key[len(prefix):] if key.startswith(prefix) else key
        _, body = split_frontmatter(read_repo_text(root / scene.path))
        stats = calculate_lexical_stats(prose_only(extract_scene_text(body)))
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


def write_snapshot(
    root: Path,
    out: Path,
    cfg: Config | None = None,
    *,
    demo: bool = False,
    title: str = "",
    description: str = "",
    site_url: str = "",
    preview_image: Path | None = None,
    book_title: str = "",
    book_author: str = "",
) -> Path:
    """Write a copy of *root*'s dashboard into *out* and return it.

    The copy is read-only. ``demo`` lets a visitor try edit mode as well; what
    they save stays in their tab, since there is nowhere else for it to go.

    The rest describes the copy to link previews. ``site_url`` is where it
    will be served from; a ``preview_image`` needs it, because a preview
    image is only fetched from a full address.
    """
    root = root.resolve()
    out = out.resolve()
    cfg = cfg or Config.load(root)
    if preview_image is not None:
        if not site_url:
            raise SnapshotError("a preview image needs the site URL the snapshot will be served from")
        if not preview_image.is_file():
            raise SnapshotError(f"{preview_image} is not a file")
    _prepare_output(root, out)

    scenes = collect_scene_stats(root, cfg, lexical=False)
    words = sum(scene.words for scene in scenes)
    meta = {
        "title": title or f"{root.name} · Proseview",
        "description": description or (
            f"{title or root.name}: {len(scenes)} scenes, {words:,} words. "
            "Made with Proseview, a local dashboard for Markdown novels."
        ),
        "url": "",
        "image": "",
    }
    if site_url:
        meta["url"] = site_url.rstrip("/") + "/"
    if preview_image is not None:
        image_name = "preview" + preview_image.suffix.lower()
        shutil.copyfile(preview_image, out / image_name)
        meta["image"] = meta["url"] + image_name

    files = {
        "index.html": build_dashboard(
            root, cfg, static_snapshot="demo" if demo else "read-only", snapshot_meta=meta
        ),
        "analysis.json": json.dumps(build_analysis_payload(root, cfg)),
        "scene-lexical.json": json.dumps(_scene_lexical(root, cfg, scenes)),
    }
    for name, text in files.items():
        text = _scrubbed(text, root)
        leaked = next((form for form in _path_forms(str(root)) if form in text), None)
        if leaked:
            raise SnapshotError(f"{name} would publish the repository path {root}")
        (out / name).write_text(text, encoding="utf-8")
    shutil.copytree(TEMPLATE_DIR / "vendor", out / "vendor")
    if demo:
        # The demo has no server to build books, so the Export dialog serves
        # ready-made ones of the whole book (see export_demo.py).
        from .book import ExportError
        from .export_demo import write_demo_exports

        try:
            write_demo_exports(
                root, cfg, out,
                title=book_title or (title.split(" · ")[0] if title else "") or root.name.replace("-", " ").title(),
                author=book_author,
            )
        except ExportError as exc:
            # A book that cannot be exported (a missing image, say) still
            # makes a demo; its Export dialog says why there is nothing in it.
            shutil.rmtree(out / "export", ignore_errors=True)
            (out / "export").mkdir()
            message = f"This demo has no books to download: {exc}"
            (out / "export" / "outline.json").write_text(json.dumps({"ok": False, "error": message}), encoding="utf-8")
            (out / "export" / "files.json").write_text(json.dumps({"book": {}, "files": {}}), encoding="utf-8")
        for name in ("export/outline.json", "export/files.json"):
            text = (out / name).read_text(encoding="utf-8")
            if any(form in text for form in _path_forms(str(root))):
                raise SnapshotError(f"{name} would publish the repository path {root}")
    (out / MARKER).write_text("Written by `proseview snapshot`; safe to replace.\n", encoding="utf-8")
    return out
