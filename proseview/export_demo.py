"""Ready-made exports for the hosted demo, which has no server to build them.

``proseview snapshot --demo`` calls :func:`write_demo_exports` to build the
whole demo book once in every style and format, with the preview pages the
Export dialog shows, and to write them beside the page under ``export/``.
The demo page answers the dialog's requests from these files
(``01-static-snapshot.js``): a visitor goes through every step, sees real
previews, and downloads a real EPUB or PDF of the whole book in the style and
format they chose. The dialog says that the demo always shows the whole
book, and that a copy of Proseview on their own computer builds exactly
what they pick.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path

from .book_styles import available_styles, load_style
from .config import Config
from .epub_check import readiness as epub_readiness
from .export import FORMAT_LABELS, export_book, prepare_book
from .export_dashboard import PREVIEW_CHAPTERS, _page_list, _style_order, outline
from .lexical import count_words, prose_only
from .pdf import DEFAULT_TRIM, PdfOptions, render_pages
from .pdf_check import readiness as pdf_readiness

#: Lower than the dashboard's preview resolution: these ship with the demo.
DEMO_PREVIEW_PPI = 72


def _slug(text: str) -> str:
    """``Alice's Adventures`` -> ``alices-adventures``, as export names files."""
    import re

    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’]", "", text.lower())).strip("-") or "book"


def write_demo_exports(root: Path, cfg: Config, out: Path, *, title: str, author: str = "") -> dict:
    """Build the demo's exports into ``out/export`` and return the index written there."""
    target = out / "export"
    files_dir = target / "files"
    previews_dir = target / "previews"
    files_dir.mkdir(parents=True)
    previews_dir.mkdir()
    stem = _slug(title)
    details = {"title": title, "author": author, "isbn": "", "dedication": "", "also_by": ""}

    index: dict[str, dict] = {}
    whole = prepare_book(root, cfg, title=title, author=author)
    totals = {
        "chapters": len(whole.chapters),
        "scenes": len(whole.scenes),
        "words": sum(count_words(prose_only(scene.markdown)) for scene in whole.scenes),
    }
    shortened = replace(whole, chapters=whole.chapters[:PREVIEW_CHAPTERS], appendices=(), back_matter=())

    with tempfile.TemporaryDirectory() as tmp:
        for style_name in sorted(available_styles(), key=_style_order):
            style = load_style(style_name)
            for fmt in style.formats:
                key = f"{style_name}-{fmt}"
                suffix = "epub" if fmt == "epub" else "pdf"
                variant = {"pdf-print": "-print", "pdf-share": ""}.get(fmt, "")
                name = f"{stem}{'-' + style_name if style_name != 'classic' else ''}{variant}.{suffix}"
                result = export_book(
                    root, cfg, Path(tmp) / name, fmt=fmt, style=style_name, title=title, author=author,
                    trim=DEFAULT_TRIM, paper="letter",
                )
                shutil.copyfile(result.path, files_dir / name)
                if fmt == "epub":
                    checks = epub_readiness(result.path, result.book, title_given=True, cover=None)
                    preview_files = {}
                    with zipfile.ZipFile(result.path) as archive:
                        for member in archive.namelist():
                            if member.startswith("OEBPS/"):
                                preview_files[member] = archive.read(member)
                    pages = _page_list(preview_files)
                    preview = {"pages": pages, "kind": result.book.kind, "format": "epub"}
                else:
                    checks = pdf_readiness(
                        result.path, result.book, layout="print" if fmt == "pdf-print" else "share",
                        trim=DEFAULT_TRIM, paper="letter", style=style_name, title_given=True,
                    )
                    images, first = render_pages(shortened, PdfOptions(
                        layout="print" if fmt == "pdf-print" else "share", style=style,
                        trim=DEFAULT_TRIM, paper="letter",
                    ), ppi=DEMO_PREVIEW_PPI)
                    preview_files = {f"page-{n:03d}.png": data for n, data in enumerate(images, start=1)}
                    preview = {
                        "pages": [{"href": n, "label": f"Page {i}"} for i, n in enumerate(preview_files, start=1)],
                        "kind": "book", "format": fmt, "spreads": fmt == "pdf-print",
                        "first_text_page": first,
                        "note": f"The preview shows the first {PREVIEW_CHAPTERS} chapters; the download has them all.",
                    }
                for member, data in preview_files.items():
                    path = previews_dir / key / member
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                (previews_dir / f"{key}.json").write_text(json.dumps({"ok": True, "token": key, **preview}), encoding="utf-8")
                index[key] = {
                    "format": fmt,
                    "label": FORMAT_LABELS[fmt],
                    "path": f"export/files/{name}",
                    "name": name,
                    "size": (files_dir / name).stat().st_size,
                    "pages": result.pages,
                    "checks": checks,
                }

    data = outline(root, cfg)
    data["details"].update(details)
    data["demo"] = True
    data["selections"] = []
    (target / "outline.json").write_text(json.dumps(data), encoding="utf-8")
    (target / "files.json").write_text(json.dumps({"book": totals, "files": index}), encoding="utf-8")
    return index
