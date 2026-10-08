"""The dashboard's side of export: what the Export dialog asks the server.

The dialog never names chapters the way the command line does. It shows a
checklist built from :func:`outline`, sends back what is ticked, and the
server turns that into the same :class:`~proseview.book.Selection` the CLI
builds, so a book exported from either place is the same book.

Everything here runs inside the local server process. It reads the novel,
writes only under the novel's folder (``exports/``, the cover, and the
``export:`` block of ``.proseview.yaml``), and keeps finished previews and
jobs in memory.
"""

from __future__ import annotations

import re
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .book import BOOK_KINDS, ExportError, SceneDocument, Selection, chapter_label, chapter_title
from .book_styles import DEFAULT_STYLE, StyleError, available_styles, load_style
from .config import EXPORT_EPUB_VERSIONS, Config, ConfigError
from .epub import IMAGE_TYPES
from .epub_check import readiness
from .export import (
    BOOK_DETAIL_KEYS,
    EXPORT_FORMATS,
    EXPORTS_DIR,
    FORMAT_LABELS,
    prepare_book,
    collect_scene_documents,
    default_title,
    ensure_gitignored,
    export_book,
    new_book_identifier,
    save_book_details,
    save_book_identifier,
    save_selection,
    saved_cover_path,
)
from .lexical import count_words, prose_only
from .pdf import DEFAULT_TRIM, PAPER_LABELS, PAPER_SIZES, TRIM_LABELS, TRIM_SIZES, default_paper
from .repo import resolve_visible_repository_path

#: Cover formats a store accepts (no SVG), by extension.
COVER_TYPES = {ext: kind for ext, kind in IMAGE_TYPES.items() if kind != "image/svg+xml"}
#: Big enough for a print-resolution cover, small enough for one JSON body.
MAX_COVER_BYTES = 20 * 1024 * 1024

_STYLE_BLURBS = {
    "classic": "Serif text, “Chapter One” openers with a drop cap, and a centred * * * between scenes.",
    "manuscript": "Standard submission format: 12 pt, double-spaced, “Surname / TITLE / page”.",
}

_FORMAT_BLURBS = {
    "epub": "For Apple Books, Kobo, Kindle and every e-reader.",
    "pdf-print": "A paperback interior to upload to KDP or IngramSpark.",
    "pdf-share": "A PDF to send to a reader, an agent or an editor.",
    "all": "The e-book and both PDFs in one go.",
}

#: The version of what the Export dialog asks of the server (see outline()).
EXPORT_API = 3

#: Chapters a PDF preview lays out. The whole book is laid out on export;
#: the preview only needs enough pages to judge the look.
PREVIEW_CHAPTERS = 3
PREVIEW_PPI = 110


def _words(scene: SceneDocument) -> int:
    """Words as the dashboard counts them, without TODO and NOTE comments."""
    return count_words(prose_only(scene.markdown))


def scene_path(scene: SceneDocument) -> str:
    """The scene's route in the dashboard (``ch01/01-opening.md``)."""
    return scene.key + ".md"


# --------------------------------------------------------------------------
# What the dialog shows


def outline(root: Path, cfg: Config) -> dict[str, Any]:
    """Everything the Export dialog needs to draw itself.

    Chapters carry their scenes in book order with word counts, saved
    selections are resolved to the scene keys they pick today (a saved
    selection that no longer matches is listed with the reason), and
    ``details`` are the book details remembered from the last export.
    """
    documents = collect_scene_documents(root, cfg)
    chapters: list[dict[str, Any]] = []
    for doc in documents:
        if not chapters or chapters[-1]["number"] != doc.chapter_number:
            chapters.append({
                "number": doc.chapter_number,
                "label": chapter_label(doc.chapter_number, "words") or f"Chapter {doc.chapter_number}",
                "title": chapter_title(doc),
                "folder": doc.folder,
                "words": 0,
                "scenes": [],
            })
        words = _words(doc)
        chapters[-1]["words"] += words
        chapters[-1]["scenes"].append({
            "key": doc.key,
            "title": doc.title,
            "number": doc.scene_number,
            "words": words,
            "path": doc.path.as_posix(),
            "scene_path": scene_path(doc),
        })

    from .book import resolve_selection

    selections = []
    for saved in cfg.export.selections:
        entry: dict[str, Any] = {"name": saved.name, "order": saved.order}
        try:
            picked = resolve_selection(documents, saved)
            entry["scenes"] = [doc.key for doc in picked]
            entry["items"] = _items_for(saved, documents)
        except ExportError as exc:
            entry["error"] = str(exc)
        selections.append(entry)

    saved = cfg.export
    cover = saved.cover_image
    cover_ok = bool(cover)
    if cover:
        try:
            cover_ok = saved_cover_path(root, cover).is_file()
        except ExportError:
            cover_ok = False
    return {
        "ok": True,
        # Raised whenever the dialog starts needing something new from the
        # server, so a page newer than a long-running server can say so.
        "api": EXPORT_API,
        "book": {
            "default_title": default_title(root),
            "words": sum(chapter["words"] for chapter in chapters),
            "scenes": len(documents),
        },
        "chapters": chapters,
        "selections": selections,
        "styles": [_style_entry(name) for name in available_styles()],
        "formats": [
            {"name": name, "label": FORMAT_LABELS.get(name, "All formats"), "blurb": _FORMAT_BLURBS[name]}
            for name in (*EXPORT_FORMATS, "all")
        ],
        "trims": [{"name": name, "label": label} for name, label in TRIM_LABELS.items()],
        "papers": [{"name": name, "label": label} for name, label in PAPER_LABELS.items()],
        "details": {
            "title": saved.title,
            "subtitle": saved.subtitle,
            "author": saved.author,
            "language": saved.language or "en-US",
            "epub_version": saved.epub_version or "epub3",
            "style": saved.style or DEFAULT_STYLE,
            "scene_titles": bool(saved.scene_titles) if saved.scene_titles is not None else False,
            "cover_image": cover if cover_ok else "",
            "format": saved.format or "epub",
            "trim": saved.trim if saved.trim in TRIM_SIZES else DEFAULT_TRIM,
            "paper": saved.paper if saved.paper in PAPER_SIZES else default_paper(saved.language or "en-US"),
            "recto_chapters": saved.recto_chapters if saved.recto_chapters is not None else True,
            "contact": saved.contact,
            "watermark": "",
        },
    }


def _style_entry(name: str) -> dict[str, Any]:
    style = load_style(name)
    return {
        "name": name,
        "label": style.name,
        "blurb": _STYLE_BLURBS.get(name, style.description),
        "formats": list(style.formats),
    }


def _items_for(selection: Selection, documents: list[SceneDocument]) -> list[dict[str, str]]:
    """A custom-order selection as dialog items: whole chapters and single scenes."""
    from .book import _chapters, _match_chapters, _match_scene

    chapters = _chapters(documents)
    items: list[dict[str, str]] = []
    for kind, token in selection.picks:
        if kind == "scene":
            items.append({"kind": "scene", "id": _match_scene(token, documents).key})
        else:
            items += [{"kind": "chapter", "id": str(n)} for n in _match_chapters(token, chapters)]
    return items


# --------------------------------------------------------------------------
# What the dialog sends back


def selection_from_request(body: dict[str, Any], documents: list[SceneDocument]) -> Selection | None:
    """Turn the dialog's ticks into a selection; ``None`` means the whole book.

    The body holds ``order`` (``book`` or ``custom``) and ``items``: each
    ``{"kind": "chapter", "id": "<number>"}`` or ``{"kind": "scene", "id":
    "<key>"}``. Every scene ticked in book order is the whole book, with its
    title page and contents, exactly as if nothing had been narrowed.
    """
    raw = body.get("selection")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ExportError("The selection must be an object")
    order = str(raw.get("order") or "book")
    if order not in {"book", "custom"}:
        raise ExportError(f"Unknown order {order!r}")
    items = raw.get("items")
    if not isinstance(items, list):
        raise ExportError("The selection must list its chapters and scenes")
    known_chapters = {str(doc.chapter_number) for doc in documents}
    known_scenes = {doc.key for doc in documents}
    picks: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ExportError("Each selected item must be an object")
        kind, ident = str(item.get("kind") or ""), str(item.get("id") or "")
        if kind == "chapter" and ident in known_chapters:
            picks.append(("chapter", ident))
        elif kind == "scene" and ident in known_scenes:
            picks.append(("scene", ident))
        else:
            raise ExportError(
                "Something you picked is no longer in the book. Close Export and open it again to refresh the list."
            )
    if not picks:
        raise ExportError("Tick at least one chapter or scene to export.")
    selection = Selection(name=str(raw.get("name") or ""), picks=tuple(picks), order=order)
    if order == "book":
        from .book import resolve_selection

        if len(resolve_selection(documents, selection)) == len(documents):
            return None
    return selection


@dataclass(frozen=True)
class ExportRequest:
    """Book details from the dialog, checked."""

    title: str = ""
    subtitle: str = ""
    author: str = ""
    language: str = "en-US"
    epub_version: str = "epub3"
    style: str = DEFAULT_STYLE
    scene_titles: bool = False
    cover_image: str = ""
    format: str = "epub"
    trim: str = DEFAULT_TRIM
    paper: str = "letter"
    recto_chapters: bool = True
    contact: str = ""
    #: Names one reader, so it is never remembered for the next export.
    watermark: str = ""

    def details(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in BOOK_DETAIL_KEYS}

    @property
    def formats(self) -> tuple[str, ...]:
        return EXPORT_FORMATS if self.format == "all" else (self.format,)


def request_details(body: dict[str, Any]) -> ExportRequest:
    raw = body.get("details") or {}
    if not isinstance(raw, dict):
        raise ExportError("Book details must be an object")

    def text(key: str, limit: int = 300) -> str:
        value = raw.get(key, "")
        if not isinstance(value, str):
            raise ExportError(f"{key} must be text")
        value = " ".join(value.split())
        if len(value) > limit:
            raise ExportError(f"The {key.replace('_', ' ')} is too long")
        return value

    epub_version = text("epub_version") or "epub3"
    if epub_version not in EXPORT_EPUB_VERSIONS:
        raise ExportError(f"Unknown EPUB version {epub_version!r}")
    style = text("style") or DEFAULT_STYLE
    if style not in available_styles():
        raise ExportError(f"Unknown book style {style!r}")
    language = text("language", 35) or "en-US"
    if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*", language):
        raise ExportError(f"{language!r} is not a language code like en-US")
    scene_titles = raw.get("scene_titles", False)
    if not isinstance(scene_titles, bool):
        raise ExportError("scene_titles must be true or false")
    fmt = text("format") or "epub"
    if fmt not in (*EXPORT_FORMATS, "all"):
        raise ExportError(f"Unknown format {fmt!r}")
    trim = text("trim") or DEFAULT_TRIM
    if trim not in TRIM_SIZES:
        raise ExportError(f"Unknown trim size {trim!r}")
    paper = text("paper") or default_paper(language)
    if paper not in PAPER_SIZES:
        raise ExportError(f"Unknown paper size {paper!r}")
    recto = raw.get("recto_chapters", True)
    if not isinstance(recto, bool):
        raise ExportError("recto_chapters must be true or false")
    contact = raw.get("contact", "")
    if not isinstance(contact, str) or len(contact) > 600:
        raise ExportError("The contact details must be text, at most a few lines")
    contact = "\n".join(" ".join(line.split()) for line in contact.splitlines() if line.strip())
    wanted = load_style(style)
    for each in (EXPORT_FORMATS if fmt == "all" else (fmt,)):
        if each not in wanted.formats:
            raise ExportError(
                f"The {wanted.name} style does not make {FORMAT_LABELS[each]}. Choose another style or format."
            )
    return ExportRequest(
        title=text("title"),
        subtitle=text("subtitle"),
        author=text("author"),
        language=language,
        epub_version=epub_version,
        style=style,
        scene_titles=scene_titles,
        cover_image=text("cover_image", 1024),
        format=fmt,
        trim=trim,
        paper=paper,
        recto_chapters=recto,
        contact=contact,
        watermark=text("watermark", 120),
    )


def _cover(root: Path, details: ExportRequest) -> Path | None:
    if not details.cover_image:
        return None
    path = saved_cover_path(root, details.cover_image)
    if not path.is_file():
        raise ExportError("The cover image has gone missing. Choose it again.")
    return path


# --------------------------------------------------------------------------
# Cover upload


def save_cover(root: Path, filename: str, data: bytes) -> str:
    """Save an uploaded cover inside the novel and return its relative path.

    The cover belongs with the book, so it lives in the novel's folder as
    ``cover.<ext>`` (where a writer would look for it, and where git keeps
    it) rather than in ``exports/``. A different file already using that
    name is never overwritten: the upload takes ``cover-2.<ext>`` instead.
    """
    from .epub_check import image_size

    suffix = Path(filename or "").suffix.lower()
    if suffix not in COVER_TYPES:
        raise ExportError("A cover must be a JPEG, PNG, GIF or WebP image.")
    if not data:
        raise ExportError("That image file is empty.")
    if len(data) > MAX_COVER_BYTES:
        raise ExportError("That image is over 20 MB. Save a smaller copy and try again.")
    if image_size(data) is None:
        raise ExportError("That file does not look like an image Proseview can read.")
    root = root.resolve()
    n = 1
    while True:
        name = f"cover{suffix}" if n == 1 else f"cover-{n}{suffix}"
        target = root / name
        if not target.exists() or (target.is_file() and target.read_bytes() == data):
            break
        n += 1
    if target.is_symlink():
        raise ExportError("The cover file is a link; remove it and try again.")
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(data)
    partial.replace(target)
    return name


# --------------------------------------------------------------------------
# Preview


@dataclass
class Preview:
    """A built EPUB held in memory so its pages can be shown in a frame."""

    token: str
    files: dict[str, bytes]
    pages: list[dict[str, str]]
    created: float = field(default_factory=time.monotonic)


class PreviewCache:
    """The last few previews, by token. Old ones are dropped."""

    def __init__(self, keep: int = 4) -> None:
        self._keep = keep
        self._items: dict[str, Preview] = {}
        self._lock = threading.Lock()

    def add(self, preview: Preview) -> None:
        with self._lock:
            self._items[preview.token] = preview
            while len(self._items) > self._keep:
                self._items.pop(next(iter(self._items)))

    def file(self, token: str, name: str) -> bytes | None:
        with self._lock:
            preview = self._items.get(token)
        return preview.files.get(name) if preview else None


def _page_list(files: dict[str, bytes]) -> list[dict[str, str]]:
    """Spine pages in reading order, each with a label for the page picker."""
    opf_name = "OEBPS/content.opf"
    opf = ET.fromstring(files[opf_name])
    ns = "{http://www.idpf.org/2007/opf}"
    manifest = {item.get("id"): item.get("href") for item in opf.iter(f"{ns}item")}
    pages = []
    for ref in opf.iter(f"{ns}itemref"):
        href = "OEBPS/" + manifest[ref.get("idref")]
        title = ""
        try:
            tree = ET.fromstring(files[href])
            node = tree.find(".//{http://www.w3.org/1999/xhtml}title")
            title = (node.text or "").strip() if node is not None else ""
        except (KeyError, ET.ParseError):
            pass
        pages.append({"href": href, "label": title or Path(href).stem.replace("-", " ").title()})
    return pages


def build_preview(root: Path, cfg: Config, body: dict[str, Any], cache: PreviewCache) -> dict[str, Any]:
    """Build the book as Export would and list its pages.

    An EPUB preview is the book itself, its XHTML pages shown in a frame. A
    PDF preview is the first chapters laid out exactly as the PDF will be and
    drawn as page images. With every format chosen, ``preview`` in the body
    says which one to show.
    """
    documents = collect_scene_documents(root, cfg)
    selection = selection_from_request(body, documents)
    details = request_details(body)
    cfg = _dialog_config(cfg)
    fmt = str(body.get("preview") or details.formats[0])
    if fmt not in details.formats:
        fmt = details.formats[0]
    if fmt == "epub":
        with tempfile.TemporaryDirectory() as tmp:
            result = export_book(
                root, cfg, Path(tmp) / "preview.epub", selection=selection, **_book_options(root, cfg, details),
            )
            with zipfile.ZipFile(result.path) as archive:
                files = {name: archive.read(name) for name in archive.namelist()}
        token = uuid.uuid4().hex
        preview = Preview(token=token, files=files, pages=_page_list(files))
        cache.add(preview)
        return {"ok": True, "token": token, "pages": preview.pages, "kind": result.book.kind, "format": "epub"}

    from dataclasses import replace

    from .book_styles import load_style as _load
    from .pdf import PdfOptions, render_pages

    options = _book_options(root, cfg, details)
    book = prepare_book(
        root, cfg, selection, title=options["title"], subtitle=options["subtitle"],
        author=options["author"], language=options["language"],
    )
    shortened = len(book.chapters) > PREVIEW_CHAPTERS and book.kind != "scene"
    if shortened:
        book = replace(book, chapters=book.chapters[:PREVIEW_CHAPTERS], appendices=())
    images, first_text_page = render_pages(book, PdfOptions(
        layout="print" if fmt == "pdf-print" else "share",
        style=_load(details.style),
        show_scene_titles=details.scene_titles,
        trim=details.trim,
        paper=details.paper,
        recto_chapters=details.recto_chapters,
        watermark=details.watermark,
        cover_image=options["cover_image"],
        contact=details.contact,
    ), ppi=PREVIEW_PPI)
    files = {f"page-{n:03d}.png": data for n, data in enumerate(images, start=1)}
    token = uuid.uuid4().hex
    pages = [{"href": name, "label": f"Page {n}"} for n, name in enumerate(files, start=1)]
    cache.add(Preview(token=token, files=files, pages=pages))
    return {
        "ok": True, "token": token, "pages": pages, "kind": book.kind, "format": fmt,
        "spreads": fmt == "pdf-print",
        "first_text_page": first_text_page,
        "note": f"The preview shows the first {PREVIEW_CHAPTERS} chapters; the export has them all." if shortened else "",
    }


def _dialog_config(cfg: Config) -> Config:
    """*cfg* without the remembered book details.

    The dialog sends every detail itself, starting from the remembered ones,
    so a field the writer cleared must stay clear rather than fall back to
    what was saved last time.
    """
    from dataclasses import replace

    blank = {key: (None if key in {"scene_titles", "recto_chapters"} else "") for key in BOOK_DETAIL_KEYS}
    return replace(cfg, export=replace(cfg.export, **blank))


def _book_options(root: Path, cfg: Config, details: ExportRequest) -> dict[str, Any]:
    return {
        "title": details.title or default_title(root),
        "subtitle": details.subtitle,
        "author": details.author,
        "language": details.language,
        "identifier": cfg.export.identifier or "",
        "epub_version": details.epub_version,
        "style": details.style,
        "scene_titles": details.scene_titles,
        "cover_image": _cover(root, details),
        "trim": details.trim,
        "paper": details.paper,
        "recto_chapters": details.recto_chapters,
        "watermark": details.watermark,
        "contact": details.contact,
    }


# --------------------------------------------------------------------------
# Export jobs


@dataclass
class ExportJob:
    id: str
    state: str = "running"
    step: str = "Starting"
    fraction: float = 0.0
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ok": True, "id": self.id, "state": self.state, "step": self.step,
            "fraction": round(self.fraction, 3),
        }
        if self.result is not None:
            data["result"] = self.result
        if self.error is not None:
            data["error"] = self.error
        return data


class ExportJobs:
    """Exports running in the background, one at a time per server.

    Two exports at once would race on ``.proseview.yaml`` and on the dated
    file name, and a writer never needs two, so a second start waits for the
    first. Finished jobs are kept briefly so the page can read the outcome.
    """

    def __init__(self, on_written=None) -> None:
        self._jobs: dict[str, ExportJob] = {}
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._on_written = on_written

    def get(self, job_id: str) -> ExportJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, root: Path, body: dict[str, Any]) -> ExportJob:
        # Validate in the request, so a bad selection answers 400 at once
        # instead of starting a job that fails a moment later.
        cfg = Config.load(root)
        documents = collect_scene_documents(root, cfg)
        selection = selection_from_request(body, documents)
        details = request_details(body)
        save_as = str(body.get("save_selection") or "").strip()
        if save_as and selection is None:
            raise ExportError("The whole book is always one click away; tick part of it to save a selection.")
        job = ExportJob(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > 20:
                self._jobs.pop(next(iter(self._jobs)))
        thread = threading.Thread(
            target=self._run, args=(job, root, selection, details, save_as), daemon=True,
            name=f"proseview-export-{job.id[:8]}",
        )
        thread.start()
        return job

    def _progress(self, job: ExportJob, step: str, fraction: float) -> None:
        job.step, job.fraction = step, max(job.fraction, min(fraction, 1.0))

    def _run(self, job: ExportJob, root: Path, selection, details: ExportRequest, save_as: str) -> None:
        with self._run_lock:
            try:
                job.result = self._export(job, root, selection, details, save_as)
                job.step, job.fraction, job.state = "Done", 1.0, "done"
            except ExportError as exc:
                job.error = _error_payload(root, exc)
                job.state = "failed"
            except (ConfigError, StyleError) as exc:
                job.error = {"message": str(exc)}
                job.state = "failed"
            except BaseException as exc:  # noqa: BLE001 -- even a crash inside Typst must reach the page
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                job.error = {"message": f"The export stopped unexpectedly: {exc or exc.__class__.__name__}. "
                             "Please try again; if it happens twice, report it with this message."}
                job.state = "failed"

    def _export(self, job: ExportJob, root: Path, selection, details: ExportRequest, save_as: str) -> dict:
        cfg = Config.load(root)
        if save_as:
            # Named, the file is named after it too: my-novel-beta-readers-….epub
            selection = Selection(name=save_as, picks=selection.picks, order=selection.order)
        identifier = cfg.export.identifier or new_book_identifier()
        options = _book_options(root, cfg, details)
        options["identifier"] = identifier
        formats = details.formats
        cfg = _dialog_config(cfg)
        files = []
        book = None
        for n, fmt in enumerate(formats):
            share = (n / len(formats), (n + 1) / len(formats))
            label = FORMAT_LABELS[fmt]

            def report(step: str, fraction: float, share=share, label=label) -> None:
                prefix = f"{label}: " if len(formats) > 1 else ""
                self._progress(job, prefix + step, (share[0] + (share[1] - share[0]) * fraction) * 0.92)

            result = export_book(root, cfg, None, selection=selection, fmt=fmt, progress=report, **options)
            book = result.book
            self._progress(job, "Checking the book", (share[1]) * 0.92)
            files.append(self._file_entry(root, result, details, options))
        # Only a successful export is remembered, so a failed first try
        # leaves the config as it was.
        if not cfg.export.identifier:
            save_book_identifier(root, identifier)
        if save_as:
            save_selection(root, Config.load(root), selection)
        save_book_details(root, Config.load(root), details.details())
        ensure_gitignored(root)
        if self._on_written:
            self._on_written()
        scenes = book.scenes
        return {
            "files": files,
            "kind": book.kind,
            "chapters": len(book.chapters),
            "scenes": len(scenes),
            "words": sum(_words(scene) for scene in scenes),
            "saved_selection": save_as,
        }

    @staticmethod
    def _file_entry(root: Path, result, details: ExportRequest, options: dict) -> dict:
        cover = options["cover_image"]
        if result.format == "epub":
            checks = readiness(
                result.path, result.book, title_given=bool(details.title),
                cover=cover.read_bytes() if cover else None,
            )
        else:
            from .pdf_check import readiness as pdf_readiness

            checks = pdf_readiness(
                result.path, result.book,
                layout="print" if result.format == "pdf-print" else "share",
                trim=details.trim, paper=details.paper, style=details.style,
                title_given=bool(details.title), contact=details.contact,
            )
        return {
            "format": result.format,
            "label": FORMAT_LABELS[result.format],
            "path": result.path.relative_to(root.resolve()).as_posix(),
            "name": result.path.name,
            "size": result.path.stat().st_size,
            "pages": result.pages,
            "checks": checks,
        }


def _error_payload(root: Path, exc: ExportError) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": str(exc)}
    if exc.scene:
        payload["scene"] = exc.scene
        payload["scene_path"] = exc.scene + ".md"
    return payload


# --------------------------------------------------------------------------
# Finished files


def exported_file(root: Path, relative: str) -> Path:
    """Resolve a finished export for download, refusing anything else.

    Only ``.epub`` and ``.pdf`` files directly inside ``exports/`` qualify, so
    this route cannot be used to read the rest of the novel or the machine.
    """
    try:
        path = resolve_visible_repository_path(root, relative)
    except ValueError as exc:
        raise ExportError(str(exc)) from exc
    exports = (root.resolve() / EXPORTS_DIR).resolve()
    if path.parent != exports or path.suffix.lower() not in {".epub", ".pdf"} or not path.is_file():
        raise ExportError("No such exported book")
    return path


def open_in_system(path: Path, *, reveal: bool = False) -> None:
    """Open *path* in its usual app, or show it in Finder / Explorer / the file manager.

    Only ever called with a path :func:`exported_file` returned, and with a
    fixed argument list, so nothing from the page reaches a shell.
    """
    import os
    import subprocess
    import sys

    if sys.platform == "darwin":
        command = ["open", "-R", str(path)] if reveal else ["open", str(path)]
    elif sys.platform.startswith("win"):
        if not reveal:
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
            return
        command = ["explorer", f"/select,{path}"]
    else:
        command = ["xdg-open", str(path.parent if reveal else path)]
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    except OSError as exc:
        raise ExportError(
            "This computer has no app set up to open that. Use Download instead."
            if not reveal else "Could not open the folder. The book is in the exports folder of your novel."
        ) from exc


__all__ = [
    "BOOK_KINDS", "ExportJobs", "open_in_system", "PreviewCache", "build_preview", "exported_file",
    "outline", "request_details", "save_cover", "selection_from_request",
]
