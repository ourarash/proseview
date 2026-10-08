"""Write a :class:`~proseview.book.Book` as a PDF, with Typst.

Two layouts come from the same book:

- ``print``: a paperback interior at a trim size (5.5 × 8.5 in by default),
  with mirrored margins and a gutter sized for the page count, running heads,
  folios, and chapters that can open on a right-hand page. The cover is not
  part of it: KDP and IngramSpark take the cover as a separate file.
- ``share``: a Letter or A4 reading copy with the cover, a clickable table of
  contents, PDF bookmarks, and an optional watermark naming the reader.

The style's ``pdf.typ`` decides how it looks; this module only writes the
book out as calls to the functions it defines (see the comment at the top of
``book_styles/classic/pdf.typ``). Fonts are the ones Typst ships with
(Libertinus Serif and friends, all under the SIL Open Font License), and
system fonts are ignored, so a book lays out the same on every machine and
every font is embedded.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .book import Book, BookChapter, ExportError, chapter_label, smart_punctuation
from .book_styles import STYLES_DIR, BookStyle

#: Fonts bundled with Proseview (see book_styles/fonts/README.md), on top of
#: the ones Typst carries itself.
FONTS_DIR = STYLES_DIR / "fonts"
from .typst_render import RenderContext, TypstRenderer, escape, string

PDF_LAYOUTS: tuple[str, ...] = ("print", "share")

#: Paperback trim sizes, as (width, height) Typst lengths. 5.5 × 8.5 in is the
#: most common size for a novel, and KDP's default.
TRIM_SIZES: dict[str, tuple[str, str]] = {
    "5x8": ("5in", "8in"),
    "5.25x8": ("5.25in", "8in"),
    "5.5x8.5": ("5.5in", "8.5in"),
    "6x9": ("6in", "9in"),
    "a5": ("148mm", "210mm"),
}
TRIM_LABELS: dict[str, str] = {
    "5x8": "5 × 8 in", "5.25x8": "5.25 × 8 in", "5.5x8.5": "5.5 × 8.5 in", "6x9": "6 × 9 in", "a5": "A5",
}
DEFAULT_TRIM = "5.5x8.5"

#: About how many words a printed page holds at each trim size, for the
#: "First 50 pages" pick. (A manuscript page holds about 250.)
WORDS_PER_PAGE: dict[str, int] = {"5x8": 250, "5.25x8": 260, "5.5x8.5": 290, "6x9": 330, "a5": 290}

PAPER_SIZES: dict[str, tuple[str, str]] = {"letter": ("8.5in", "11in"), "a4": ("210mm", "297mm")}
PAPER_LABELS: dict[str, str] = {"letter": "US Letter", "a4": "A4"}

#: Text size per trim: smaller pages get slightly smaller type.
_TRIM_TEXT = {"5x8": "10.5pt", "5.25x8": "10.5pt", "5.5x8.5": "11pt", "6x9": "11.5pt", "a5": "11pt"}

#: KDP's minimum inside margin by page count (no bleed), in inches. The gutter
#: has to grow with the spine, or words disappear into the fold.
_GUTTERS = ((150, 0.375), (300, 0.5), (500, 0.625), (700, 0.75), (828, 0.875))
KDP_MIN_PAGES = 24
KDP_MAX_PAGES = 828


def gutter_for(pages: int) -> float:
    """The inside margin, in inches, for a paperback of *pages* pages."""
    for limit, inches in _GUTTERS:
        if pages <= limit:
            return inches
    return _GUTTERS[-1][1]


def default_paper(language: str) -> str:
    """Letter where Letter is the norm (the US and Canada), A4 elsewhere."""
    region = (language.split("-") + [""])[1].upper()
    return "letter" if region in {"US", "CA", ""} and language.lower().startswith("en") else "a4"


@dataclass(frozen=True)
class PdfOptions:
    layout: str = "print"
    style: BookStyle | None = None
    show_scene_titles: bool = False
    trim: str = DEFAULT_TRIM
    paper: str = ""
    recto_chapters: bool = True
    watermark: str = ""
    cover_image: Path | None = None
    contact: str = ""
    #: Called as ``progress(step, fraction)`` while the book is laid out.
    progress: Callable[[str, float], None] | None = field(default=None, compare=False)
    #: Fixed creation date, so two exports of the same book are the same file.
    timestamp: _dt.datetime | None = None


@dataclass(frozen=True)
class PdfResult:
    path: Path | None
    pages: int
    data: bytes


def approximate_words(book: Book) -> str:
    """The word count as a manuscript's title page gives it: "about 26,000 words"."""
    from .lexical import count_words, prose_only

    words = sum(count_words(prose_only(scene.markdown)) for scene in book.scenes)
    step = 1000 if words >= 10_000 else 100
    rounded = max(step, round(words / step) * step)
    return f"about {rounded:,} words"


def _typst_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return string(str(value))


def _length(inches: float) -> str:
    return f"{inches:g}in"


class _Source:
    """The Typst document for one book."""

    def __init__(self, book: Book, options: PdfOptions) -> None:
        if options.layout not in PDF_LAYOUTS:
            raise ExportError(f"Unknown PDF layout {options.layout!r}; expected print or share")
        if options.style is None or options.style.pdf_template is None:
            name = options.style.name if options.style else "This style"
            raise ExportError(f"{name} has no PDF design yet. Choose another style for a PDF.")
        if options.layout == "print" and options.trim not in TRIM_SIZES:
            raise ExportError(f"Unknown trim size {options.trim!r}; expected one of {', '.join(TRIM_SIZES)}")
        paper = options.paper or default_paper(book.language)
        if options.layout == "share" and paper not in PAPER_SIZES:
            raise ExportError(f"Unknown paper size {paper!r}; expected letter or a4")
        self.book = book
        self.options = options
        self.paper = paper
        self.style = options.style
        self.renderer = TypstRenderer()
        self.root = book.root.resolve() if book.root else None

    # -- configuration -----------------------------------------------------------

    def config(self, gutter: float) -> str:
        book, options = self.book, self.options
        language, _, region = book.language.partition("-")
        if options.layout == "print":
            width, height = TRIM_SIZES[options.trim]
            size = _TRIM_TEXT[options.trim]
            margins = {"inside": _length(gutter + 0.25), "outside": "0.6in", "top": "0.75in", "bottom": "0.8in"}
        else:
            width, height = PAPER_SIZES[self.paper]
            size = "12pt"
            margins = {"inside": "1.1in", "outside": "1.1in", "top": "1in", "bottom": "1in"}
        cover = "none"
        if options.cover_image is not None and options.layout == "share":
            cover = string("/" + self._inside(options.cover_image, "The cover image").as_posix())
        values = {
            "layout": string(options.layout),
            "title": string(smart_punctuation(book.title)),
            "subtitle": string(smart_punctuation(book.subtitle)),
            "author": string(smart_punctuation(book.author)),
            "note": string(smart_punctuation(book.note)),
            "lang": string(language.lower() or "en"),
            "region": string(region.upper()) if re.fullmatch(r"[A-Za-z]{2}", region or "") else "none",
            "page-width": width,
            "page-height": height,
            "size": size,
            "recto": "true" if options.recto_chapters else "false",
            "watermark": string(smart_punctuation(options.watermark.strip())),
            "cover": cover,
            "kind": string(book.kind),
            "scene-break": string(self.style.scene_break),
            "contact": string(options.contact.strip()),
            "word-count": string(approximate_words(book)),
            **margins,
        }
        body = ",\n  ".join(f"{key}: {value}" for key, value in values.items())
        theme = ",\n  ".join(
            f"{key.replace('_', '-')}: {_typst_value(value)}" for key, value in self.style.pdf_settings
        )
        return f"#let config = (\n  {body},\n)\n#let theme = (\n  {theme},\n)\n"

    def _inside(self, path: Path, what: str) -> Path:
        if self.root is None:
            raise ExportError(f"{what} needs the book's folder")
        try:
            return path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise ExportError(f"{what} must be inside the book's folder: {path}") from exc

    # -- the book --------------------------------------------------------------------

    def body(self) -> str:
        book = self.book
        parts = [self.style.pdf_template.rstrip(), "", "#show: book", ""]
        if book.has_contents:
            # In print, a copyright page takes the back of the title page.
            copyright_first = bool(book.front_matter) and book.front_matter[0].kind == "copyright"
            parts.append(f"#title-page(verso: {'false' if copyright_first else 'true'})")
            parts += [self._matter(page) for page in book.front_matter]
            parts += ["#contents()", ""]
        elif self.options.layout == "share" and self.options.cover_image is not None:
            parts += ["#cover-page()", ""]
        if book.kind == "scene":
            parts.append(self._single_scene())
        else:
            total = len(book.chapters)
            for index, chapter in enumerate(book.chapters):
                self._progress(f"Laying out chapter {chapter.number}", index / max(total, 1) * 0.5)
                parts.append(self._chapter(chapter))
        parts += [self._matter(page) for page in book.back_matter]
        for section in book.appendices:
            parts.append(self._appendix(section))
        return "\n\n".join(parts) + "\n"

    def _progress(self, step: str, fraction: float) -> None:
        if self.options.progress is not None:
            self.options.progress(step, fraction)

    def _content(self, text: str) -> str:
        return "[" + escape(smart_punctuation(text)) + "]"

    def _ctx(self, scene) -> RenderContext:
        return RenderContext(
            root=self.root, source=scene.path, owner=f"Scene {scene.title!r} ({scene.path.as_posix()})",
            scene=scene.key, shift_headings=2,
        )

    def _chapter(self, chapter: BookChapter) -> str:
        number = chapter_label(chapter.number, self.style.chapter_numbering)
        title = chapter.title
        joiner = ". " if number.isdigit() else ": "
        outline_label = joiner.join(part for part in (number, title) if part) or f"Chapter {chapter.number}"
        lines = [
            f"#chapter({self._content(number) if number else 'none'}, "
            f"{self._content(title) if title else ('none' if number else self._content(outline_label))}, "
            f"{self._content(outline_label)}, n: {chapter.number})"
        ]
        show_titles = self.options.show_scene_titles
        for i, scene in enumerate(chapter.scenes):
            if show_titles:
                lines.append(f"#scene-title({self._content(scene.title)})")
            elif i:
                lines.append("#scene-break()")
            lines.append(self.renderer.render(
                scene.markdown, self._ctx(scene), opener=i == 0 and not show_titles, noindent=True,
            ))
        lines.append("#chapter-end()")
        return "\n\n".join(lines)

    def _single_scene(self) -> str:
        chapter = self.book.chapters[0]
        scene = chapter.scenes[0]
        number = chapter_label(chapter.number, self.style.chapter_numbering)
        where = " · ".join(part for part in (number, chapter.title) if part)
        return "\n\n".join([
            f"#single-scene({self._content(where) if where else 'none'}, {self._content(scene.title)})",
            self.renderer.render(scene.markdown, self._ctx(scene), noindent=True),
            "#chapter-end()",
        ])

    def _matter(self, page) -> str:
        ctx = RenderContext(
            root=self.root, source=Path(page.source) if page.source else None,
            owner=f"The page {page.title!r}" + (f" ({page.source})" if page.source else ""), shift_headings=1,
        )
        body = self.renderer.render(page.markdown, ctx, noindent=True)
        return (
            f"#matter({string(page.kind)}, {self._content(page.title)}, {'true' if page.shows_title else 'false'})"
            f"[\n{body}\n]\n\n#chapter-end()"
        )

    def _appendix(self, section) -> str:
        lines = [f"#appendix({self._content('Appendix: ' + section.label)})"]
        lines.append("#[\n#set par(justify: false, first-line-indent: 0pt, spacing: 0.9em)\n")
        for doc_title, content in section.documents:
            body = re.sub(r"^# [^\n]*\n*", "", content, count=1).strip()
            lines.append(f"#appendix-document({self._content(doc_title)})")
            ctx = RenderContext(root=self.root, source=None, owner=f"Appendix document {doc_title!r}", shift_headings=2)
            lines.append(self.renderer.render(body, ctx))
        lines.append("]")
        lines.append("#chapter-end()")
        return "\n\n".join(lines)

    # -- compiling ------------------------------------------------------------------

    def compile(self, gutter: float, *, fmt: str = "pdf", ppi: float | None = None, first_page: list | None = None):
        import json
        import tempfile

        import typst

        source = (self.config(gutter) + "\n" + self.body()).encode("utf-8")
        stamp = (self.options.timestamp or _dt.datetime.now(_dt.timezone.utc)).replace(microsecond=0)
        root = str(self.root) if self.root else None
        fonts = [str(FONTS_DIR)]
        try:
            if first_page is None or self.root is None:
                compiler = typst.Compiler(root=root, font_paths=fonts, ignore_system_fonts=True)
                if fmt == "pdf":
                    return compiler.compile(source, format="pdf", timestamp=stamp)
                return compiler.compile(source, format="png", ppi=ppi or 72)
            # Asking where the text starts needs the document as a file inside
            # the book's folder (Typst resolves images against it), so it goes
            # in Proseview's own working folder for the moment it takes.
            work = self.root / ".proseview"
            work.mkdir(exist_ok=True)
            _sweep_previews(work)
            with tempfile.NamedTemporaryFile("wb", prefix="preview-", suffix=".typ", dir=work, delete=False) as handle:
                handle.write(source)
                main = Path(handle.name)
            try:
                compiler = typst.Compiler(str(main), root=root, font_paths=fonts, ignore_system_fonts=True)
                images = compiler.compile(format="png", ppi=ppi or 72)
                found = json.loads(compiler.query("<first-text-page>", field="value") or "[]")
                first_page.append(int(found[0]) if found else 1)
                return images
            finally:
                main.unlink(missing_ok=True)
        except (typst.TypstError, RuntimeError) as exc:  # pragma: no cover -- a style bug, not a writer's
            detail = getattr(exc, "message", "") or str(exc)
            raise ExportError(f"The PDF could not be laid out: {detail}") from exc


def _sweep_previews(work: Path, older_than: float = 600) -> None:
    """Remove preview sources a crashed preview left behind."""
    import time

    for stale in work.glob("preview-*.typ"):
        try:
            if time.time() - stale.stat().st_mtime > older_than:
                stale.unlink()
        except OSError:
            pass


def page_count(data: bytes) -> int:
    """Pages in a PDF Typst wrote (it writes no compressed object streams)."""
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", data))


def write_pdf(book: Book, output: Path | None, options: PdfOptions) -> PdfResult:
    """Lay out *book* and write it to *output* (or only return it, when ``None``).

    A print interior is laid out once to count its pages, then again if the
    gutter that page count needs differs from the first guess.
    """
    source = _Source(book, options)
    guess = gutter_for(max(1, sum(len(s.markdown) for s in book.scenes) // 1800))
    data = source.compile(guess)
    pages = page_count(data)
    if options.layout == "print" and gutter_for(pages) != guess:
        if options.progress:
            options.progress("Widening the inside margin for the page count", 0.75)
        data = source.compile(gutter_for(pages))
        pages = page_count(data)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_name(output.name + ".partial")
        try:
            partial.write_bytes(data)
            partial.replace(output)
        finally:
            partial.unlink(missing_ok=True)
    return PdfResult(output, pages, data)


def render_pages(book: Book, options: PdfOptions, *, ppi: float = 60) -> tuple[list[bytes], int]:
    """PNG images of every page, for the dialog's preview, and where the text starts (from 1)."""
    source = _Source(book, options)
    guess = gutter_for(max(1, sum(len(s.markdown) for s in book.scenes) // 1800))
    first: list[int] = []
    images = source.compile(guess, fmt="png", ppi=ppi, first_page=first)
    return (images if isinstance(images, list) else [images]), (first[0] if first else 1)


def typst_source(book: Book, options: PdfOptions) -> str:
    """The Typst document for *book*, for debugging a style."""
    source = _Source(book, options)
    return source.config(0.5) + "\n" + source.body()
