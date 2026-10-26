"""Write a :class:`~proseview.book.Book` as a Word document (``.docx``).

Editors and agents work in Word: they read a manuscript there, mark it up
with tracked changes and send it back. This module writes the document
itself, as the EPUB writer writes the EPUB, so nothing needs installing and
the same code runs in the browser.

Two layouts come from the same book:

- ``manuscript`` (the Manuscript style): standard submission format. Times
  New Roman 12 pt, double-spaced, 1 in margins, every paragraph indented
  half an inch, a title page with the author's contact details and the word
  count, each chapter on a new page a third of the way down, a centred
  ``#`` between scenes, and "Surname / TITLE / page" at the top of every
  text page, its page number a real Word field.
- ``book`` (every other style): a reading copy with a title page, the front
  and back matter, chapter openers in the style's manner, scene breaks, and
  page numbers in the footer.

Everything is set with named paragraph styles (Normal, Title, Heading 1,
Scene Break, ...) rather than formatting applied by hand, so an editor can
restyle the whole document from Word's Styles pane, and chapters show in its
navigation pane.

Scenes are parsed by markdown-it exactly as the EPUB and PDF renderers parse
them, and the same token stream is written out as WordprocessingML.
"""

from __future__ import annotations

import datetime as _dt
import posixpath
import re
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

from .book import Book, BookChapter, ExportError, MatterPage, chapter_label, smart_punctuation
from .book_styles import BookStyle
from .callouts import print_fills
from .obsidian import plain_obsidian
from .raw_html import HtmlBreak, HtmlClose, HtmlImage, HtmlOpen, HtmlText, MarkStack, image_only, read_html, straighten_tag_quotes

DOCX_LAYOUTS: tuple[str, ...] = ("manuscript", "book")

#: Page sizes in twentieths of a point (twips), as Word measures them.
PAGE_SIZES: dict[str, tuple[int, int]] = {"letter": (12240, 15840), "a4": (11906, 16838)}

_TWIPS_PER_INCH = 1440
_EMU_PER_INCH = 914400
_MARGIN = _TWIPS_PER_INCH  # 1 in all round, as a manuscript asks

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: Images Word shows everywhere. WebP and SVG open only in recent versions.
WORD_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
#: Characters XML 1.0 does not allow, which a pasted scene can still carry.
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _text(value: str) -> str:
    return _xml_escape(_INVALID_XML.sub("", value), {'"': "&quot;"})


@dataclass(frozen=True)
class DocxOptions:
    layout: str = "book"
    style: BookStyle | None = None
    show_scene_titles: bool = False
    paper: str = "letter"
    cover_image: Path | None = None
    contact: str = ""
    #: Called as ``progress(step, fraction)`` while the document is written.
    progress: Callable[[str, float], None] | None = field(default=None, compare=False)
    #: Fixed creation date, so two exports of the same book are the same file.
    timestamp: _dt.datetime | None = None


# --------------------------------------------------------------------------
# Paragraph styles: written to styles.xml, and to CSS for the preview


@dataclass(frozen=True)
class _Style:
    id: str
    name: str
    kind: str = "paragraph"
    based: str = "Normal"
    next: str = ""
    font: str = ""
    size: float = 0  # points
    bold: bool = False
    italic: bool = False
    caps: bool = False
    letter_spacing: float = 0  # points
    align: str = ""  # left, center, right, both
    first_line: float | None = None  # inches
    left: float = 0
    right: float = 0
    hanging: float = 0
    before: float | None = None  # points
    after: float | None = None
    line: float | None = None  # a multiple of single spacing
    page_break_before: bool = False
    keep_next: bool = False
    outline: int | None = None
    color: str = ""
    underline: bool = False
    small_caps: bool = False
    #: A thin box around the paragraph; Word draws one box round a run of them.
    border: bool = False
    shading: str = ""  # RRGGBB behind the paragraph


def _styles(layout: str, style: BookStyle | None) -> list[_Style]:
    """The document's named styles for *layout*, in the style's manner."""
    settings = dict(style.pdf_settings) if style else {}
    if layout == "manuscript":
        body = "Times New Roman"
        return [
            _Style("Normal", "Normal", based="", font=body, size=12, first_line=0.5, before=0, after=0, line=2.0),
            _Style("FirstParagraph", "First Paragraph", next="Normal"),
            _Style("TitlePageDetails", "Title Page Details", first_line=0, line=1.0),
            _Style("Title", "Title", next="Subtitle", first_line=0, align="center", caps=True, before=216),
            _Style("Subtitle", "Subtitle", next="TitlePageAuthor", first_line=0, align="center"),
            _Style("TitlePageAuthor", "Title Page Author", first_line=0, align="center", before=12),
            _Style("TitlePageNote", "Title Page Note", first_line=0, align="center", italic=True, before=12),
            _Style(
                "Heading1", "heading 1", next="FirstParagraph", first_line=0, align="center",
                before=158, after=24, page_break_before=True, keep_next=True, outline=0,
            ),
            _Style("Heading2", "heading 2", next="Normal", first_line=0, align="center", keep_next=True, outline=1),
            _Style("Heading3", "heading 3", next="Normal", first_line=0, align="center", keep_next=True, outline=2),
            _Style("Heading4", "heading 4", next="Normal", first_line=0, keep_next=True, italic=True, outline=3),
            _Style("SceneBreak", "Scene Break", next="Normal", first_line=0, align="center", keep_next=True),
            _Style("DocumentTitle", "Document Title", next="Normal", first_line=0, bold=True, keep_next=True),
            _Style("BlockText", "Block Text", first_line=0, left=0.5),
            _Style("Callout", "Callout", first_line=0, left=0.15, right=0.15, border=True),
            _Style("CalloutTitle", "Callout Title", based="Callout", next="Callout", keep_next=True),
            _Style("ListItem", "List Item", first_line=0, left=0.5, hanging=0.25),
            _Style("SourceCode", "Source Code", first_line=0, font="Courier New", size=11, line=1.0),
            _Style("Figure", "Figure", first_line=0, align="center", line=1.0, keep_next=True),
            _Style("Hyperlink", "Hyperlink", kind="character", based="", underline=True),
            _Style("Header", "header", first_line=0, align="right", line=1.0),
            _Style("Footer", "footer", first_line=0, align="center", line=1.0),
        ]

    sans = "sans" in str(settings.get("body_font", "")).lower()
    body = "Arial" if sans else "Georgia"
    heading = "Arial" if "sans" in str(settings.get("heading_font", "")).lower() else body
    opener = str(settings.get("opener") or "classic")
    if opener == "modern":
        number = _Style("ChapterNumber", "Chapter Number", kind="character", based="", font=heading, size=40, bold=True)
        title = _Style("ChapterTitle", "Chapter Title", kind="character", based="", font=heading, size=20)
    elif opener == "romance":
        number = _Style("ChapterNumber", "Chapter Number", kind="character", based="", size=13, letter_spacing=1)
        title = _Style("ChapterTitle", "Chapter Title", kind="character", based="", size=26, italic=True)
    else:
        number = _Style(
            "ChapterNumber", "Chapter Number", kind="character", based="", size=10.5, caps=True, letter_spacing=2,
        )
        title = _Style("ChapterTitle", "Chapter Title", kind="character", based="", size=20, italic=True)
    return [
        _Style("Normal", "Normal", based="", font=body, size=12, first_line=0.3, before=0, after=0, line=1.25),
        _Style("FirstParagraph", "First Paragraph", next="Normal", first_line=0),
        _Style("Title", "Title", next="Subtitle", first_line=0, align="center", font=heading, size=28, before=150, line=1.1),
        _Style("Subtitle", "Subtitle", next="TitlePageAuthor", first_line=0, align="center", italic=True, size=15, before=10),
        _Style("TitlePageAuthor", "Title Page Author", first_line=0, align="center", size=14, before=60),
        _Style("TitlePageNote", "Title Page Note", first_line=0, align="center", italic=True, before=24),
        _Style(
            "Heading1", "heading 1", next="FirstParagraph", first_line=0, align="center", font=heading,
            size=20, before=96, after=36, line=1.2, page_break_before=True, keep_next=True, outline=0,
        ),
        _Style(
            "Heading2", "heading 2", next="FirstParagraph", first_line=0, align="center", font=heading,
            size=14, italic=True, before=18, after=12, keep_next=True, outline=1,
        ),
        _Style("Heading3", "heading 3", next="FirstParagraph", first_line=0, font=heading, bold=True,
               before=12, after=6, keep_next=True, outline=2),
        _Style("Heading4", "heading 4", next="FirstParagraph", first_line=0, font=heading, italic=True,
               before=12, after=6, keep_next=True, outline=3),
        _Style("SceneBreak", "Scene Break", next="FirstParagraph", first_line=0, align="center",
               before=12, after=12, keep_next=True),
        _Style("MatterText", "Matter Text", first_line=0, size=10, line=1.15, after=6),
        _Style("Dedication", "Dedication", first_line=0, align="center", italic=True, before=150),
        _Style("DocumentTitle", "Document Title", next="FirstParagraph", first_line=0, font=heading, bold=True,
               before=12, after=6, keep_next=True),
        _Style("BlockText", "Block Text", first_line=0, left=0.4, right=0.4, before=6, after=6),
        _Style("Callout", "Callout", first_line=0, left=0.1, right=0.1, before=4, after=4, border=True),
        _Style("CalloutTitle", "Callout Title", based="Callout", next="Callout", small_caps=True,
               letter_spacing=0.5, color="555555", keep_next=True),
        _Style("ListItem", "List Item", first_line=0, left=0.5, hanging=0.25),
        _Style("SourceCode", "Source Code", first_line=0, font="Courier New", size=10, line=1.0, before=6, after=6),
        _Style("Figure", "Figure", first_line=0, align="center", line=1.0, before=12, after=12, keep_next=True),
        _Style("Hyperlink", "Hyperlink", kind="character", based="", underline=True, color="1F4E79"),
        number,
        title,
        _Style("Header", "header", first_line=0, align="center", line=1.0, size=10),
        _Style("Footer", "footer", first_line=0, align="center", line=1.0, size=10),
    ]


def _callout_styles(layout: str, fills: dict[str, str]) -> list[_Style]:
    """A Callout and a Callout Title style for each type with a print colour, shaded with it."""
    out = []
    for kind, fill in fills.items():
        shading = fill.lstrip("#").upper()
        box = _Style(f"Callout-{kind}", f"Callout {kind}", based="Callout", shading=shading)
        title = _Style(f"CalloutTitle-{kind}", f"Callout Title {kind}", based=box.id, next=box.id, keep_next=True,
                       shading=shading)
        if layout != "manuscript":
            title = replace(title, small_caps=True, letter_spacing=0.5, color="555555")
        out += [box, title]
    return out


def _callout_fills_in(styles: ET.Element) -> dict[str, str]:
    """The shaded callout types in a document's styles.xml, ``{"letter": "#f7f1e6"}``."""
    w = "{" + _NS["w"] + "}"
    fills = {}
    for node in styles.iter(w + "style"):
        style_id = node.get(w + "styleId") or ""
        shading = node.find(f"{w}pPr/{w}shd")
        if style_id.startswith("Callout-") and shading is not None:
            fills[style_id[len("Callout-"):]] = "#" + (shading.get(w + "fill") or "")
    return fills


def _preview_classes(style: str) -> str:
    """A paragraph's classes in the preview: a callout style with the styles it is based on."""
    if not style.startswith(("Callout", "CalloutTitle")):
        return style
    base, _, kind = style.partition("-")
    classes = ["Callout"]
    if kind:
        classes.append(f"Callout-{kind}")
    if base == "CalloutTitle":
        classes.append(style)
    return " ".join(dict.fromkeys(classes))


def _inches(value: float) -> int:
    return round(value * _TWIPS_PER_INCH)


def _run_props_xml(s: _Style) -> str:
    parts = []
    if s.font:
        parts.append(f'<w:rFonts w:ascii="{s.font}" w:hAnsi="{s.font}" w:eastAsia="{s.font}" w:cs="{s.font}"/>')
    if s.bold:
        parts.append("<w:b/><w:bCs/>")
    if s.italic:
        parts.append("<w:i/><w:iCs/>")
    if s.caps:
        parts.append("<w:caps/>")
    if s.small_caps:
        parts.append("<w:smallCaps/>")
    if s.color:
        parts.append(f'<w:color w:val="{s.color}"/>')
    if s.letter_spacing:
        parts.append(f'<w:spacing w:val="{round(s.letter_spacing * 20)}"/>')
    if s.size:
        half = round(s.size * 2)
        parts.append(f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>')
    if s.underline:
        parts.append('<w:u w:val="single"/>')
    return f"<w:rPr>{''.join(parts)}</w:rPr>" if parts else ""


def _para_props_xml(s: _Style) -> str:
    parts = []
    if s.keep_next:
        parts.append("<w:keepNext/>")
    if s.page_break_before:
        parts.append("<w:pageBreakBefore/>")
    if s.border:
        edge = 'w:val="single" w:sz="4" w:space="4" w:color="888888"'
        parts.append(f'<w:pBdr><w:top {edge}/><w:left {edge}/><w:bottom {edge}/><w:right {edge}/></w:pBdr>')
    if s.shading:
        parts.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{s.shading}"/>')
    spacing = []
    if s.before is not None:
        spacing.append(f'w:before="{round(s.before * 20)}"')
    if s.after is not None:
        spacing.append(f'w:after="{round(s.after * 20)}"')
    if s.line is not None:
        spacing.append(f'w:line="{round(s.line * 240)}" w:lineRule="auto"')
    if spacing:
        parts.append(f"<w:spacing {' '.join(spacing)}/>")
    indent = []
    if s.left:
        indent.append(f'w:left="{_inches(s.left)}"')
    if s.right:
        indent.append(f'w:right="{_inches(s.right)}"')
    if s.hanging:
        indent.append(f'w:hanging="{_inches(s.hanging)}"')
    elif s.first_line is not None:
        indent.append(f'w:firstLine="{_inches(s.first_line)}"')
    if indent:
        parts.append(f"<w:ind {' '.join(indent)}/>")
    if s.align:
        parts.append(f'<w:jc w:val="{s.align}"/>')
    if s.outline is not None:
        parts.append(f'<w:outlineLvl w:val="{s.outline}"/>')
    return f"<w:pPr>{''.join(parts)}</w:pPr>" if parts else ""


def styles_xml(styles: list[_Style], language: str) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<w:styles xmlns:w="{_NS["w"]}">',
        "<w:docDefaults><w:rPrDefault><w:rPr>"
        f'<w:lang w:val="{_text(language or "en-US")}"/>'
        "</w:rPr></w:rPrDefault><w:pPrDefault/></w:docDefaults>",
    ]
    for s in styles:
        default = ' w:default="1"' if s.id == "Normal" else ""
        body = [f'<w:name w:val="{s.name}"/>']
        if s.based:
            body.append(f'<w:basedOn w:val="{s.based}"/>')
        if s.next:
            body.append(f'<w:next w:val="{s.next}"/>')
        body.append("<w:qFormat/>")
        if s.kind == "paragraph":
            body.append(_para_props_xml(s))
        body.append(_run_props_xml(s))
        out.append(f'<w:style w:type="{s.kind}"{default} w:styleId="{s.id}">{"".join(body)}</w:style>')
    out.append("</w:styles>")
    return "".join(out)


def styles_css(styles: list[_Style]) -> str:
    """The same styles as CSS, for the Export dialog's preview of the document."""
    rules = []
    for s in styles:
        decl = []
        if s.font:
            decl.append(f"font-family:'{s.font}',serif")
        if s.size:
            decl.append(f"font-size:{s.size:g}pt")
        if s.bold:
            decl.append("font-weight:bold")
        if s.italic:
            decl.append("font-style:italic")
        if s.caps:
            decl.append("text-transform:uppercase")
        if s.small_caps:
            decl.append("font-variant:small-caps")
        if s.border:
            decl.append("border:0.5pt solid #888;padding:3pt 4pt")
        if s.shading:
            decl.append(f"background:#{s.shading}")
        if s.letter_spacing:
            decl.append(f"letter-spacing:{s.letter_spacing:g}pt")
        if s.underline:
            decl.append("text-decoration:underline")
        if s.color:
            decl.append(f"color:#{s.color}")
        if s.kind == "paragraph":
            if s.align:
                decl.append(f"text-align:{'justify' if s.align == 'both' else s.align}")
            if s.hanging:
                decl.append(f"text-indent:-{s.hanging:g}in")
            elif s.first_line is not None:
                decl.append(f"text-indent:{s.first_line:g}in")
            if s.left:
                decl.append(f"margin-left:{s.left:g}in")
            if s.right:
                decl.append(f"margin-right:{s.right:g}in")
            if s.before is not None:
                decl.append(f"margin-top:{s.before:g}pt")
            if s.after is not None:
                decl.append(f"margin-bottom:{s.after:g}pt")
            if s.line is not None:
                decl.append(f"line-height:{s.line * 1.15:.3g}")
        selector = "p, li" if s.id == "Normal" else f".{s.id}"
        if decl:
            rules.append(f"{selector}{{{';'.join(decl)}}}")
    return "\n".join(rules)


# --------------------------------------------------------------------------
# The package around the document


class _Package:
    """Relationships and media for one document."""

    def __init__(self) -> None:
        self.rels: list[tuple[str, str, str, bool]] = []  # id, type, target, external
        self.media: dict[str, bytes] = {}
        self._images: dict[Path, tuple[str, int, int]] = {}
        self._links: dict[str, str] = {}
        self.drawings = 0

    def add(self, kind: str, target: str, *, external: bool = False) -> str:
        rid = f"rId{len(self.rels) + 1}"
        self.rels.append((rid, f"{_REL}/{kind}", target, external))
        return rid

    def link(self, href: str) -> str:
        if href not in self._links:
            self._links[href] = self.add("hyperlink", href, external=True)
        return self._links[href]

    def image(self, path: Path) -> tuple[str, int, int]:
        """The relationship id and pixel size of *path*, added to the package once."""
        from .epub_check import image_size

        if path not in self._images:
            data = path.read_bytes()
            size = image_size(data) or (800, 600)
            name = f"image{len(self.media) + 1}{path.suffix.lower().replace('.jpeg', '.jpg')}"
            self.media[name] = data
            self._images[path] = (self.add("image", f"media/{name}"), *size)
        return self._images[path]


@dataclass
class _Context:
    root: Path | None
    source: Path | None = None
    owner: str = ""
    scene: str = ""
    shift_headings: int = 2


class _Writer:
    """The body of the document, paragraph by paragraph."""

    def __init__(self, book: Book, options: DocxOptions) -> None:
        if options.layout not in DOCX_LAYOUTS:
            raise ExportError(f"Unknown Word layout {options.layout!r}; expected manuscript or book")
        if options.paper not in PAGE_SIZES:
            raise ExportError(f"Unknown paper size {options.paper!r}; expected letter or a4")
        from .typst_render import _markdown

        self.book = book
        self.options = options
        self.manuscript = options.layout == "manuscript"
        self.style = options.style
        self.numbering = self.style.chapter_numbering if self.style else ("numerals" if self.manuscript else "words")
        self.scene_break = self.style.scene_break if self.style else ("#" if self.manuscript else "*   *   *")
        self.root = book.root.resolve() if book.root else None
        self.package = _Package()
        self.paragraphs: list[str] = []
        #: Whether the next paragraph starts a new page.
        self.break_next = False
        self._md = _markdown()
        self.callout_fills = print_fills(self.style.callouts if self.style else (), book.callouts)
        width, _ = PAGE_SIZES[options.paper]
        self.text_width_in = (width - 2 * _MARGIN) / _TWIPS_PER_INCH

    # -- paragraphs and runs ----------------------------------------------------

    def para(self, style: str, runs: str, *, extra: str = "") -> None:
        if self.break_next:
            # A page of its own: the paragraph that opens it starts the page,
            # rather than an empty paragraph holding a page break.
            extra = "<w:pageBreakBefore/>" + extra
            self.break_next = False
        self.paragraphs.append(f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{extra}</w:pPr>{runs}</w:p>')

    @staticmethod
    def run(text: str, props: tuple[str, ...] = (), *, style: str = "") -> str:
        if not text:
            return ""
        rpr = _rpr(props, style)
        pieces = []
        for n, chunk in enumerate(_INVALID_XML.sub("", text).split("\t")):
            if n:
                pieces.append("<w:tab/>")
            if chunk:
                pieces.append(f'<w:t xml:space="preserve">{_text(chunk)}</w:t>')
        return f"<w:r>{rpr}{''.join(pieces)}</w:r>"

    @staticmethod
    def line_break(props: tuple[str, ...] = ()) -> str:
        return f"<w:r>{_rpr(props, '')}<w:br/></w:r>"

    def plain(self, text: str) -> str:
        return self.run(smart_punctuation(text))

    # -- the book ---------------------------------------------------------------

    def write(self) -> tuple[str, bool]:
        """The body XML, and whether it opens with a title section of its own."""
        book = self.book
        front = False
        if book.has_contents:
            self._title_page()
            if not self.manuscript:
                for page in book.front_matter:
                    self._matter(page)
            front = True
        elif not self.manuscript and self.options.cover_image is not None:
            self._cover()
            front = True
        if front:
            # The title pages are a section of their own: no running head,
            # and the story's pages count from 1.
            self.paragraphs.append(f"<w:p><w:pPr>{self._section_xml(body=False)}</w:pPr></w:p>")
        if book.kind == "scene":
            self._single_scene()
        else:
            total = len(book.chapters)
            for index, chapter in enumerate(book.chapters):
                self._progress(f"Writing chapter {chapter.number}", index / max(total, 1))
                self._chapter(chapter)
        if not self.manuscript:
            for page in book.back_matter:
                self._matter(page)
        for section in book.appendices:
            self._appendix(section)
        return "".join(self.paragraphs), front

    def _progress(self, step: str, fraction: float) -> None:
        if self.options.progress is not None:
            self.options.progress(step, fraction)

    def _cover(self) -> None:
        path = self.options.cover_image
        if path is None:
            return
        if path.suffix.lower() not in WORD_IMAGE_TYPES:
            raise ExportError("A Word document's cover must be a JPEG, PNG or GIF. Choose another cover image.")
        self.para("Figure", self._drawing(path, "Cover", 1.0, max_height_in=8.0))

    def _title_page(self) -> None:
        book = self.book
        if self.manuscript:
            from .pdf import approximate_words

            lines = [book.author.strip()] if book.author.strip() else []
            lines += [line.strip() for line in self.options.contact.splitlines() if line.strip()]
            words = approximate_words(book)
            tab = f'<w:tabs><w:tab w:val="right" w:pos="{_inches(self.text_width_in)}"/></w:tabs>'
            first = (lines[0] if lines else "") + "\t" + words
            self.para("TitlePageDetails", self.run(first), extra=tab)
            for line in lines[1:]:
                self.para("TitlePageDetails", self.run(line))
            self.para("Title", self.plain(book.title))
            if book.subtitle:
                self.para("Subtitle", self.plain(book.subtitle))
            if book.author:
                self.para("TitlePageAuthor", self.plain(f"by {book.author}"))
            if book.note:
                self.para("TitlePageNote", self.plain(book.note))
            return
        if self.options.cover_image is not None:
            self._cover()
            self.break_next = True
        self.para("Title", self.plain(book.title))
        if book.subtitle:
            self.para("Subtitle", self.plain(book.subtitle))
        if book.author:
            self.para("TitlePageAuthor", self.plain(book.author))
        if book.note:
            self.para("TitlePageNote", self.plain(book.note))

    def _matter(self, page: MatterPage) -> None:
        ctx = _Context(
            root=self.root, source=Path(page.source) if page.source else None,
            owner=f"The page {page.title!r}" + (f" ({page.source})" if page.source else ""), shift_headings=1,
        )
        if page.shows_title:
            self.para("Heading1", self.plain(page.title))
            self.render(page.markdown, ctx, first="FirstParagraph")
            return
        style = {"copyright": "MatterText", "dedication": "Dedication", "epigraph": "Dedication"}[page.kind]
        # A page that speaks for itself still starts on a page of its own.
        self.break_next = True
        self.render(page.markdown, ctx, first=style, every=style)

    def _chapter_heading(self, number: str, title: str) -> None:
        if self.manuscript:
            runs = self.plain(number) if number else ""
            if number and title:
                runs += self.line_break()
            runs += self.plain(title) if title else ""
        else:
            runs = self.run(smart_punctuation(number), style="ChapterNumber") if number else ""
            if number and title:
                runs += self.line_break()
            runs += self.run(smart_punctuation(title), style="ChapterTitle") if title else ""
        self.para("Heading1", runs)

    def _chapter(self, chapter: BookChapter) -> None:
        number = chapter_label(chapter.number, self.numbering)
        title = chapter.title
        if not number and not title:
            title = f"Chapter {chapter.number}"
        self._chapter_heading(number, title)
        first = "Normal" if self.manuscript else "FirstParagraph"
        for i, scene in enumerate(chapter.scenes):
            if self.options.show_scene_titles:
                self.para("Heading2", self.plain(scene.title))
            elif i:
                self.para("SceneBreak", self.plain(self.scene_break))
            self.render(scene.markdown, self._ctx(scene), first=first)

    def _single_scene(self) -> None:
        chapter = self.book.chapters[0]
        scene = chapter.scenes[0]
        number = chapter_label(chapter.number, self.numbering)
        where = " · ".join(part for part in (number, chapter.title) if part)
        runs = []
        if self.manuscript:
            runs.append(self.run(smart_punctuation(self.book.title).upper()))
        if where:
            runs.append(self.run(smart_punctuation(where), style="" if self.manuscript else "ChapterNumber"))
        runs.append(self.run(smart_punctuation(scene.title), style="" if self.manuscript else "ChapterTitle"))
        self.para("Heading1", self.line_break().join(runs))
        self.render(scene.markdown, self._ctx(scene), first="Normal" if self.manuscript else "FirstParagraph")

    def _appendix(self, section) -> None:
        self.para("Heading1", self.plain("Appendix: " + section.label))
        for doc_title, content in section.documents:
            body = re.sub(r"^# [^\n]*\n*", "", content, count=1).strip()
            self.para("DocumentTitle", self.plain(doc_title))
            ctx = _Context(root=self.root, owner=f"Appendix document {doc_title!r}", shift_headings=2)
            self.render(body, ctx, first="FirstParagraph", every="FirstParagraph")

    def _ctx(self, scene) -> _Context:
        return _Context(
            root=self.root, source=scene.path, owner=f"Scene {scene.title!r} ({scene.path.as_posix()})",
            scene=scene.key, shift_headings=1,
        )

    # -- sections -----------------------------------------------------------------

    def _section_xml(self, *, body: bool, header: str = "", footer: str = "") -> str:
        width, height = PAGE_SIZES[self.options.paper]
        refs = ""
        if header:
            refs += f'<w:headerReference w:type="default" r:id="{header}"/>'
        if footer:
            refs += f'<w:footerReference w:type="default" r:id="{footer}"/>'
        numbering = '<w:pgNumType w:start="1"/>' if body else ""
        return (
            f"<w:sectPr>{refs}<w:pgSz w:w=\"{width}\" w:h=\"{height}\"/>"
            f'<w:pgMar w:top="{_MARGIN}" w:right="{_MARGIN}" w:bottom="{_MARGIN}" w:left="{_MARGIN}" '
            f'w:header="720" w:footer="720" w:gutter="0"/>{numbering}</w:sectPr>'
        )

    # -- Markdown -----------------------------------------------------------------

    def render(self, text: str, ctx: _Context, *, first: str = "Normal", every: str = "Normal") -> None:
        """Write *text* as paragraphs: the first in *first*, the rest in *every*."""
        text = plain_obsidian(text, ctx.root.resolve() if ctx.root else None)
        tokens = self._md.parse(straighten_tag_quotes(_COMMENT_RE.sub("", text)))
        self._blocks(tokens, 0, ctx, stop=None, state={"next": first, "every": every}, level=0, quote="")

    def _take(self, state: dict) -> str:
        style = state["next"]
        state["next"] = state["every"]
        return style

    def _blocks(self, tokens: list, i: int, ctx: _Context, *, stop: str | None, state: dict, level: int, quote: str):
        """Write blocks up to *stop*; inside a quotation or callout, *quote* is its paragraphs' style."""
        while i < len(tokens):
            token = tokens[i]
            kind = token.type
            if stop and kind == stop:
                return i + 1
            if kind == "paragraph_open":
                children = tokens[i + 1].children or []
                if image_only(children):
                    self.para("Figure", self._inline(children, ctx))
                else:
                    style = quote or self._take(state)
                    self.para(style, self._inline(children, ctx))
                i += 3
            elif kind == "heading_open":
                depth = min(4, int(token.tag[1]) + ctx.shift_headings)
                self.para(f"Heading{max(2, depth)}", self._inline(tokens[i + 1].children or [], ctx))
                state["next"] = "Normal" if self.manuscript else "FirstParagraph"
                i += 3
            elif kind == "blockquote_open":
                i = self._blocks(tokens, i + 1, ctx, stop="blockquote_close", state=state, level=level, quote="BlockText")
                state["next"] = state["every"]
            elif kind == "callout_open":
                suffix = "-" + token.meta["type"] if token.meta["type"] in self.callout_fills else ""
                i += 1
                if tokens[i].type == "callout_title_open":
                    self.para("CalloutTitle" + suffix, self._inline(tokens[i + 1].children or [], ctx))
                    i += 3
                i = self._blocks(tokens, i, ctx, stop="callout_close", state=state, level=level, quote="Callout" + suffix)
                state["next"] = state["every"]
            elif kind in {"bullet_list_open", "ordered_list_open"}:
                i = self._list(tokens, i, ctx, level)
                state["next"] = state["every"]
            elif kind in {"fence", "code_block"}:
                lines = token.content.rstrip("\n").split("\n")
                runs = self.line_break(("code",)).join(self.run(line, ("code",)) for line in lines)
                self.para("SourceCode", runs)
                i += 1
            elif kind == "hr":
                self.para("SceneBreak", self.plain(self.scene_break))
                state["next"] = "Normal" if self.manuscript else "FirstParagraph"
                i += 1
            elif kind == "table_open":
                i = self._table(tokens, i + 1, ctx)
            elif kind == "html_block":
                self._html_block(token.content, ctx, state)
                i += 1
            else:
                i += 1
        return i

    def _list(self, tokens: list, i: int, ctx: _Context, level: int) -> int:
        open_token = tokens[i]
        close = open_token.type.replace("_open", "_close")
        ordered = open_token.type == "ordered_list_open"
        number = int(open_token.attrGet("start") or 1)
        indent = f'<w:ind w:left="{_inches(0.5 + 0.35 * level)}" w:hanging="{_inches(0.25)}"/>'
        i += 1
        while i < len(tokens) and tokens[i].type != close:
            if tokens[i].type != "list_item_open":
                i += 1
                continue
            marker = f"{number}." if ordered else "•"
            number += 1
            i += 1
            first_line = True
            while i < len(tokens) and tokens[i].type != "list_item_close":
                kind = tokens[i].type
                if kind == "paragraph_open":
                    runs = self._inline(tokens[i + 1].children or [], ctx)
                    prefix = self.run(marker + "\t") if first_line else self.run("\t")
                    self.para("ListItem", prefix + runs, extra=indent)
                    first_line = False
                    i += 3
                elif kind in {"bullet_list_open", "ordered_list_open"}:
                    i = self._list(tokens, i, ctx, level + 1)
                else:
                    i += 1
            i += 1
        return i + 1

    def _table(self, tokens: list, i: int, ctx: _Context) -> int:
        rows: list[list[str]] = []
        header_rows = 0
        in_head = False
        while i < len(tokens) and tokens[i].type != "table_close":
            kind = tokens[i].type
            if kind == "thead_open":
                in_head = True
            elif kind == "thead_close":
                in_head = False
            elif kind == "tr_open":
                rows.append([])
                header_rows += 1 if in_head else 0
            elif kind == "inline":
                rows[-1].append(self._inline(tokens[i].children or [], ctx, bold=len(rows) <= header_rows))
            i += 1
        columns = max((len(row) for row in rows), default=1)
        width = _inches(self.text_width_in)
        cell_width = width // columns
        border = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        borders = "".join(border.format(side) for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
        grid = f'<w:gridCol w:w="{cell_width}"/>' * columns
        out = [
            f'<w:tbl><w:tblPr><w:tblW w:w="{width}" w:type="dxa"/><w:tblBorders>{borders}</w:tblBorders>'
            '<w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>'
            f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>"
        ]
        for row in rows:
            row = row + [""] * (columns - len(row))
            cells = "".join(
                f'<w:tc><w:tcPr><w:tcW w:w="{cell_width}" w:type="dxa"/></w:tcPr>'
                f'<w:p><w:pPr><w:pStyle w:val="FirstParagraph"/><w:spacing w:line="240" w:lineRule="auto"/></w:pPr>{cell}</w:p></w:tc>'
                for cell in row
            )
            out.append(f"<w:tr>{cells}</w:tr>")
        out.append("</w:tbl>")
        self.paragraphs.append("".join(out))
        # Word needs a paragraph between a table and whatever follows it.
        self.paragraphs.append('<w:p><w:pPr><w:pStyle w:val="FirstParagraph"/></w:pPr></w:p>')
        return i + 1

    # -- inline -------------------------------------------------------------------

    def _inline(self, children: list, ctx: _Context, *, bold: bool = False) -> str:
        groups: list[list[str]] = [[]]  # the innermost is where runs go; a link opens one
        links: list[str | None] = []
        props: list[str] = ["b"] if bold else []
        marks = MarkStack()

        def emit(xml: str) -> None:
            groups[-1].append(xml)

        def current() -> tuple[str, ...]:
            return tuple(props) + tuple(_HTML_MARKS[m] for m in marks.open if m in _HTML_MARKS)

        for child in children:
            kind = child.type
            if kind == "html_inline":
                if not marks.skipping:
                    for event in read_html(child.content):
                        if isinstance(event, HtmlText):
                            emit(self.run(event.text, current()))
                        elif isinstance(event, HtmlBreak):
                            emit(self.line_break(current()))
                        elif isinstance(event, HtmlImage):
                            emit(self._image(event.src, event.alt, event.width, ctx))
                        elif isinstance(event, HtmlOpen) and event.mark in _HTML_MARKS:
                            marks.push(event.mark)
                        elif isinstance(event, HtmlClose) and event.mark in _HTML_MARKS:
                            marks.pop(event.mark)
                marks.track_skips(child.content)
                continue
            if marks.skipping:
                continue
            if kind == "text":
                emit(self.run(child.content, current()))
            elif kind == "softbreak":
                emit(self.run(" ", current()))
            elif kind == "hardbreak":
                emit(self.line_break(current()))
            elif kind == "code_inline":
                emit(self.run(child.content, current() + ("code",)))
            elif kind in _MD_MARKS:
                props.append(_MD_MARKS[kind])
            elif kind in {"em_close", "strong_close", "s_close"}:
                wanted = _MD_MARKS[kind.replace("_close", "_open")]
                if wanted in props:
                    del props[len(props) - 1 - props[::-1].index(wanted)]
            elif kind == "link_open":
                href = str(child.attrGet("href") or "")
                # A link to a repository file has nothing to land on in the
                # document; its text stays, as in the EPUB.
                links.append(self.package.link(href) if urlparse(href).scheme in {"http", "https", "mailto"} else None)
                groups.append([])
            elif kind == "link_close" and links:
                self._close_link(groups, links.pop())
            elif kind == "image":
                alt = "".join(c.content for c in (child.children or []) if c.type == "text") or child.content
                emit(self._image(str(child.attrGet("src") or ""), alt, None, ctx))
        while links:
            self._close_link(groups, links.pop())
        return "".join(groups[0])

    @staticmethod
    def _close_link(groups: list[list[str]], rid: str | None) -> None:
        inner = "".join(groups.pop())
        if rid:
            inner = re.sub(r"<w:r>(<w:rPr>)?", lambda m: '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/>' + ("" if m.group(1) else "</w:rPr>"), inner)
            inner = f'<w:hyperlink r:id="{rid}">{inner}</w:hyperlink>'
        groups[-1].append(inner)

    def _image(self, src: str, alt: str, width: float | None, ctx: _Context) -> str:
        from .epub import resolve_image

        try:
            path = resolve_image(ctx.root, src, ctx.source, ctx.owner)
        except ExportError as exc:
            raise ExportError(str(exc), scene=ctx.scene) from None
        if path.suffix.lower() not in WORD_IMAGE_TYPES:
            raise ExportError(
                f"{ctx.owner} has a {path.suffix.lstrip('.').upper()} image ({src}), which Word cannot show "
                "everywhere. Save a PNG or JPEG copy and link that.", scene=ctx.scene,
            )
        return self._drawing(path, alt, width)

    def _drawing(self, path: Path, alt: str, width: float | None, *, max_height_in: float = 6.0) -> str:
        rid, px_w, px_h = self.package.image(path)
        natural = px_w / 96
        target = self.text_width_in * width if width else min(natural, self.text_width_in)
        scale = min(1.0, max_height_in / (px_h / px_w * target)) if px_w else 1.0
        cx = round(target * scale * _EMU_PER_INCH)
        cy = round(cx * px_h / px_w) if px_w else cx
        self.package.drawings += 1
        n = self.package.drawings
        descr = _text(alt)
        return (
            '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{n}" name="Picture {n}" descr="{descr}"/>'
            f'<a:graphic xmlns:a="{_NS["a"]}"><a:graphicData uri="{_NS["pic"]}">'
            f'<pic:pic xmlns:pic="{_NS["pic"]}"><pic:nvPicPr><pic:cNvPr id="{n}" name="{_text(path.name)}" descr="{descr}"/>'
            '<pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        )

    def _html_block(self, html: str, ctx: _Context, state: dict) -> None:
        """A block of raw HTML as paragraphs and images, centred where it asked to be."""
        current: list = []
        centred = 0

        def place(runs: str, *, figure: bool = False) -> None:
            if figure:
                self.para("Figure", runs)
            else:
                self.para(self._take(state), runs, extra='<w:jc w:val="center"/>' if centred else "")

        def flush() -> None:
            marks = MarkStack()
            runs = []
            for event in current:
                props = tuple(_HTML_MARKS[m] for m in marks.open if m in _HTML_MARKS)
                if isinstance(event, HtmlText):
                    runs.append(self.run(" ".join(event.text.split()) if not event.text.isspace() else " ", props))
                elif isinstance(event, HtmlBreak):
                    runs.append(self.line_break(props))
                elif isinstance(event, HtmlOpen) and event.mark in _HTML_MARKS:
                    marks.push(event.mark)
                elif isinstance(event, HtmlClose) and event.mark in _HTML_MARKS:
                    marks.pop(event.mark)
            has_text = any(isinstance(e, HtmlText) and e.text.strip() for e in current)
            current.clear()
            if has_text:
                place("".join(runs))

        for event in read_html(html):
            if isinstance(event, HtmlImage):
                flush()
                place(self._image(event.src, event.alt, event.width, ctx), figure=True)
            elif isinstance(event, (HtmlOpen, HtmlClose)) and event.mark in {"para", "center"}:
                flush()
                if event.mark == "center":
                    centred = max(0, centred + (1 if isinstance(event, HtmlOpen) else -1))
            else:
                current.append(event)
        flush()


_MD_MARKS = {"em_open": "i", "strong_open": "b", "s_open": "s"}
_HTML_MARKS = {"em": "i", "strong": "b", "sup": "sup", "sub": "sub"}


def _rpr(props: tuple[str, ...], style: str) -> str:
    """Run properties, in the order the schema lists them."""
    if not props and not style:
        return ""
    parts = [f'<w:rStyle w:val="{style}"/>'] if style else []
    if "code" in props:
        parts.append('<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/>')
    if "b" in props:
        parts.append("<w:b/><w:bCs/>")
    if "i" in props:
        parts.append("<w:i/><w:iCs/>")
    if "s" in props:
        parts.append("<w:strike/>")
    if "sup" in props:
        parts.append('<w:vertAlign w:val="superscript"/>')
    elif "sub" in props:
        parts.append('<w:vertAlign w:val="subscript"/>')
    return f"<w:rPr>{''.join(parts)}</w:rPr>" if parts else ""


# --------------------------------------------------------------------------
# Writing the file


def _surname(author: str) -> str:
    parts = author.split()
    return parts[-1] if parts else ""


def _header_xml(text: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{_NS["w"]}" xmlns:r="{_NS["r"]}"><w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr>'
        f"{_Writer.run(text)}" + _page_field() + "</w:p></w:hdr>"
    )


def _footer_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr xmlns:w="{_NS["w"]}" xmlns:r="{_NS["r"]}"><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
        + _page_field() + "</w:p></w:ftr>"
    )


def _page_field() -> str:
    """Word's PAGE field, so the number is the page it sits on."""
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:t>1</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def build_docx(book: Book, options: DocxOptions) -> bytes:
    """The Word document for *book*, as bytes."""
    import io

    writer = _Writer(book, options)
    body, _ = writer.write()
    package = writer.package
    package.add("styles", "styles.xml")
    package.add("settings", "settings.xml")
    if writer.manuscript:
        parts = [_surname(book.author), smart_punctuation(book.title).upper()]
        head = " / ".join(part for part in parts if part) + " / "
        header = package.add("header", "header1.xml")
        section = writer._section_xml(body=True, header=header)
        extra_parts = {"word/header1.xml": _header_xml(head)}
    else:
        footer = package.add("footer", "footer1.xml")
        section = writer._section_xml(body=True, footer=footer)
        extra_parts = {"word/footer1.xml": _footer_xml()}

    namespaces = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in _NS.items() if prefix in {"w", "r", "wp"})
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {namespaces}><w:body>{body}{section}</w:body></w:document>"
    )
    styles = _styles(options.layout, options.style) + _callout_styles(options.layout, writer.callout_fills)
    stamp = (options.timestamp or _dt.datetime.now(_dt.timezone.utc)).replace(microsecond=0)
    iso = stamp.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_text(smart_punctuation(book.title))}</dc:title>"
        + (f"<dc:creator>{_text(book.author)}</dc:creator>" if book.author else "")
        + f"<dc:language>{_text(book.language)}</dc:language>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{iso}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{iso}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>Proseview</Application></Properties>"
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:settings xmlns:w="{_NS["w"]}"><w:defaultTabStop w:val="720"/>'
        '<w:characterSpacingControl w:val="doNotCompress"/>'
        '<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" '
        'w:val="15"/></w:compat></w:settings>'
    )
    media_types = {name.rsplit(".", 1)[1] for name in package.media}
    defaults = "".join(
        f'<Default Extension="{ext}" ContentType="{WORD_IMAGE_TYPES["." + ext]}"/>' for ext in sorted(media_types)
    )
    overrides = [
        ("/word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
        ("/word/styles.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"),
        ("/word/settings.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ("/docProps/app.xml", "application/vnd.openxmlformats-officedocument.extended-properties+xml"),
    ]
    if writer.manuscript:
        overrides.append(("/word/header1.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"))
    else:
        overrides.append(("/word/footer1.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"))
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{defaults}"
        + "".join(f'<Override PartName="{name}" ContentType="{kind}"/>' for name, kind in overrides)
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        f'<Relationship Id="rId3" Type="{_REL}/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="{rid}" Type="{kind}" Target="{_text(target)}"'
            + (' TargetMode="External"' if external else "") + "/>"
            for rid, kind, target, external in package.rels
        )
        + "</Relationships>"
    )

    files: dict[str, bytes] = {
        "[Content_Types].xml": content_types.encode(),
        "_rels/.rels": root_rels.encode(),
        "docProps/core.xml": core.encode(),
        "docProps/app.xml": app.encode(),
        "word/document.xml": document.encode(),
        "word/styles.xml": styles_xml(styles, book.language).encode(),
        "word/settings.xml": settings.encode(),
        "word/_rels/document.xml.rels": document_rels.encode(),
        **{name: text.encode() for name, text in extra_parts.items()},
        **{f"word/media/{name}": data for name, data in package.media.items()},
    }
    buffer = io.BytesIO()
    date = stamp.timetuple()[:6] if stamp.year >= 1980 else (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=date)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def write_docx(book: Book, output: Path, options: DocxOptions) -> Path:
    """Write *book* to *output* as a Word document and return the path."""
    data = build_docx(book, options)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    try:
        partial.write_bytes(data)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


# --------------------------------------------------------------------------
# Reading a document back: the preview, and the check after export


_W = "{" + _NS["w"] + "}"
_R = "{" + _NS["r"] + "}"


def document_paragraphs(data: bytes) -> list[dict]:
    """The document's paragraphs (and tables) as plain records, read back from the file.

    Each record is ``{"style", "runs": [(text, props)], "centred",
    "page_break", "break_before", "section_end", "images"}``; a table is
    ``{"table": [[cell text]]}``.
    """
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    body = document.find(f"{_W}body")
    records: list[dict] = []
    for node in list(body) if body is not None else []:
        if node.tag == f"{_W}tbl":
            rows = [
                ["".join(t.text or "" for t in cell.iter(f"{_W}t")) for cell in row.iter(f"{_W}tc")]
                for row in node.iter(f"{_W}tr")
            ]
            records.append({"table": rows})
        elif node.tag == f"{_W}p":
            records.append(_paragraph_record(node))
    return records


def _paragraph_record(node) -> dict:
    ppr = node.find(f"{_W}pPr")
    style = ""
    centred = False
    if ppr is not None:
        pstyle = ppr.find(f"{_W}pStyle")
        style = pstyle.get(f"{_W}val", "") if pstyle is not None else ""
        jc = ppr.find(f"{_W}jc")
        centred = jc is not None and jc.get(f"{_W}val") == "center"
    runs: list[tuple[str, tuple[str, ...]]] = []
    images: list[tuple[str, str]] = []
    page_break = False

    def walk(parent, link: bool) -> None:
        nonlocal page_break
        for child in parent:
            if child.tag == f"{_W}hyperlink":
                walk(child, True)
            elif child.tag == f"{_W}r":
                rpr = child.find(f"{_W}rPr")
                props: list[str] = ["link"] if link else []
                if rpr is not None:
                    for tag, name in (("i", "i"), ("b", "b"), ("strike", "s"), ("caps", "caps")):
                        if rpr.find(f"{_W}{tag}") is not None:
                            props.append(name)
                    vert = rpr.find(f"{_W}vertAlign")
                    if vert is not None:
                        props.append("sup" if vert.get(f"{_W}val") == "superscript" else "sub")
                    rstyle = rpr.find(f"{_W}rStyle")
                    if rstyle is not None:
                        props.append("style:" + rstyle.get(f"{_W}val", ""))
                    if rpr.find(f"{_W}rFonts") is not None and "Courier" in (rpr.find(f"{_W}rFonts").get(f"{_W}ascii") or ""):
                        props.append("code")
                for item in child:
                    if item.tag == f"{_W}t":
                        runs.append((item.text or "", tuple(props)))
                    elif item.tag == f"{_W}tab":
                        runs.append(("\t", tuple(props)))
                    elif item.tag == f"{_W}br":
                        if item.get(f"{_W}type") == "page":
                            page_break = True
                        else:
                            runs.append(("\n", tuple(props)))
                    elif item.tag == f"{_W}instrText":
                        runs.append(("", ("field",)))
                    elif item.tag == f"{_W}drawing":
                        blip = item.find(".//{" + _NS["a"] + "}blip")
                        doc_pr = item.find(".//{" + _NS["wp"] + "}docPr")
                        if blip is not None:
                            images.append((blip.get(f"{_R}embed", ""), doc_pr.get("descr", "") if doc_pr is not None else ""))

    walk(node, False)
    return {
        "style": style,
        "runs": runs,
        "centred": centred,
        "page_break": page_break,
        "break_before": ppr is not None and ppr.find(f"{_W}pageBreakBefore") is not None,
        "section_end": ppr is not None and ppr.find(f"{_W}sectPr") is not None,
        "images": images,
    }


def _page_label(label: str, content: list[str]) -> str:
    """A page found by a page break is named by its first words."""
    if label != "Page":
        return label
    words = " ".join(re.sub(r"<[^>]+>", " ", "".join(content[:2])).split())
    words = re.sub(r"&#160;|&[a-z]+;", "", words).strip()
    return (words[:40].rstrip() + "…") if len(words) > 40 else (words or label)


def preview_pages(data: bytes, layout: str, style: BookStyle | None) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    """The document as XHTML pages for the Export dialog: a page per chapter.

    Read back from the finished file, so the preview shows what is in it:
    its paragraphs in their named styles, set with the same fonts, sizes and
    spacing as the styles Word will use.
    """
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target") for rel in rels}
        media = {name: archive.read(name) for name in archive.namelist() if name.startswith("word/media/")}
        word_styles = ET.fromstring(archive.read("word/styles.xml"))
    css = styles_css(_styles(layout, style) + _callout_styles(layout, _callout_fills_in(word_styles)))
    page_css = (
        "body{margin:0;padding:24px;background:#fff;color:#111}"
        "p{margin:0}.Heading1{break-before:column}"
        "img{max-width:100%;height:auto}table{border-collapse:collapse;width:100%;margin:6pt 0}"
        "td{border:1px solid #888;padding:2pt 4pt;vertical-align:top;font-size:0.9em}"
        ".running{font-size:9pt;color:#777;text-align:right;margin-bottom:12pt;text-indent:0}"
        # Word draws one box round a run of callout paragraphs.
        ".Callout+.Callout{border-top:none;margin-top:0;padding-top:0}"
        ".Callout:has(+ .Callout){border-bottom:none;margin-bottom:0;padding-bottom:0}"
    )
    pages: list[tuple[str, list[str]]] = [("Title page", [])]
    files: dict[str, bytes] = {}
    for name, blob in media.items():
        files["word/" + name[len("word/"):]] = blob

    for record in document_paragraphs(data):
        if "table" in record:
            rows = "".join(
                "<tr>" + "".join(f"<td>{_text(cell)}</td>" for cell in row) + "</tr>" for row in record["table"]
            )
            pages[-1][1].append(f"<table>{rows}</table>")
            continue
        style = record["style"] or "Normal"
        if record["break_before"] and style != "Heading1" and pages[-1][1]:
            pages.append(("Page", []))
        if style == "Heading1":
            lines = "".join(text for text, props in record["runs"] if "field" not in props).split("\n")
            label = " · ".join(" ".join(line.split()) for line in lines if line.strip())
            if pages[-1][1] or len(pages) > 1:
                pages.append((label or "Chapter", []))
            else:
                pages[-1] = (label or pages[-1][0], pages[-1][1])
        html = []
        for text, props in record["runs"]:
            if "field" in props:
                continue
            piece = "<br/>" if text == "\n" else _text(text).replace("\t", " ")
            for prop in props:
                tag = {"i": "em", "b": "strong", "s": "s", "sup": "sup", "sub": "sub", "code": "code", "link": "u"}.get(prop)
                if tag:
                    piece = f"<{tag}>{piece}</{tag}>"
                elif prop.startswith("style:"):
                    piece = f'<span class="{prop[6:]}">{piece}</span>'
            html.append(piece)
        for rid, alt in record["images"]:
            target = targets.get(rid, "")
            html.append(f'<img src="{_text(posixpath.basename(target))}" alt="{_text(alt)}"/>' if target else "")
        centred = ' style="text-align:center;text-indent:0"' if record["centred"] else ""
        if html or style != "Normal":
            pages[-1][1].append(f'<p class="{_preview_classes(style)}"{centred}>{"".join(html) or "&#160;"}</p>')
        if record["section_end"] or record["page_break"]:
            if pages[-1][1]:
                pages.append(("Page", []))

    pages = [(_page_label(label, content), content) for label, content in pages if content]
    listing: list[dict[str, str]] = []
    for n, (label, content) in enumerate(pages, start=1):
        is_chapter = any('class="Heading1"' in line for line in content[:1])
        href = f"word/chapter-{n:03d}.xhtml" if is_chapter else f"word/page-{n:03d}.xhtml"
        title = _text(label)
        page = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8"/>'
            f"<title>{title}</title><style>{page_css}\n{css}</style></head>"
            f'<body>{"".join(content)}</body></html>'
        )
        # Images are referenced from the page's own folder.
        files[href] = page.replace('src="', 'src="media/').encode("utf-8")
        listing.append({"href": href, "label": label})
    return files, listing
