"""Write a :class:`~proseview.book.Book` as an EPUB, with no external tools.

An EPUB is a zip of XHTML pages, a stylesheet, and two XML files that list
them (the OPF package) and lay out the contents (the nav page, plus an NCX
for older readers). Writing those directly means export works on a machine
that has only Proseview installed, and every page carries the markup the
book style expects.

Markdown is rendered with markdown-it-py. Raw HTML in a scene is shown as
text rather than passed through, because one unclosed ``<br>`` would make
the page invalid XHTML and some readers refuse the whole book over it.
HTML comments are dropped first, so TODO and NOTE comments never reach a
reader.
"""

from __future__ import annotations

import datetime as _dt
import html
import re
import zipfile
from dataclasses import dataclass, field
from typing import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

from .book import Book, BookChapter, ExportError, SceneDocument, chapter_label, smart_punctuation
from .book_styles import BookStyle
from .raw_html import HtmlBreak, HtmlClose, HtmlImage, HtmlOpen, HtmlText, MarkStack, read_html, repository_src, straighten_tag_quotes, image_only

EPUB_VERSIONS: tuple[str, ...] = ("epub3", "epub2")

IMAGE_TYPES = {
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _txt(text: str) -> str:
    """Escape text a reader sees, with the same curly quotes and dashes as the prose."""
    return _esc(smart_punctuation(str(text)))


def _slug(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "section"


@dataclass(frozen=True)
class EpubOptions:
    version: str = "epub3"
    style: BookStyle | None = None
    show_scene_titles: bool = False
    cover_image: Path | None = None
    css: tuple[Path, ...] = ()
    modified: _dt.datetime | None = None
    #: Called as ``progress(step, fraction)`` while the book is laid out.
    progress: Callable[[str, float], None] | None = field(default=None, compare=False)


@dataclass
class _Item:
    id: str
    href: str
    media_type: str
    data: bytes
    properties: str = ""


@dataclass
class _NavEntry:
    label: str
    href: str
    children: list["_NavEntry"] = field(default_factory=list)


class _Markdown:
    """markdown-it configured for book prose, with image collection."""

    def __init__(self, images: "_Images") -> None:
        from markdown_it import MarkdownIt

        # HTML is parsed so that it can be understood, never passed through:
        # every html token is rewritten from raw_html's events below.
        self._md = MarkdownIt(
            "commonmark", {"html": True, "xhtmlOut": True, "typographer": True}
        ).enable(["table", "strikethrough", "replacements", "smartquotes"])
        self._images = images

    def render(
        self,
        text: str,
        *,
        source: Path | None,
        owner: str,
        shift_headings: int = 0,
        first_class: str = "",
        scene: str = "",
    ) -> str:
        tokens = self._md.parse(straighten_tag_quotes(_COMMENT_RE.sub("", text)))
        first_done = not first_class
        for index, token in enumerate(tokens):
            if shift_headings and token.type in {"heading_open", "heading_close"}:
                level = min(6, int(token.tag[1]) + shift_headings)
                token.tag = f"h{level}"
            if token.type == "paragraph_open" and image_only(tokens[index + 1].children or []):
                # A picture on its own is a figure, not a paragraph to indent.
                token.tag = tokens[index + 2].tag = "div"
                token.attrSet("class", "figure")
                continue
            if not first_done and token.type == "paragraph_open" and token.level == 0:
                token.attrJoin("class", first_class)
                first_done = True
            if token.type == "html_block":
                token.content = self._html_block(token.content, source, owner, scene)
            if token.children:
                token.children = self._inline(token.children, source, owner, scene)
        return self._md.renderer.render(tokens, self._md.options, {})

    # -- raw HTML --------------------------------------------------------------

    _TAGS = {"em": "em", "strong": "strong", "sup": "sup", "sub": "sub"}

    def _html_image(self, event, source, owner, scene) -> str:
        href = self._images.add(event.src, source, owner, scene)
        style = f' style="width: {round(event.width * 100)}%"' if event.width else ""
        return f'<img class="html-image" src="{_esc(href)}" alt="{_esc(event.alt)}"{style} />'

    def _html_inline(self, events, marks: MarkStack, source, owner, scene) -> str:
        out = []
        for event in events:
            if isinstance(event, HtmlText):
                out.append(_esc(event.text))
            elif isinstance(event, HtmlBreak):
                out.append("<br />")
            elif isinstance(event, HtmlImage):
                out.append(self._html_image(event, source, owner, scene))
            elif isinstance(event, HtmlOpen) and event.mark in self._TAGS:
                marks.push(event.mark)
                out.append(f"<{self._TAGS[event.mark]}>")
            elif isinstance(event, HtmlClose) and event.mark in self._TAGS:
                out += [f"</{self._TAGS[mark]}>" for mark in marks.pop(event.mark) if mark in self._TAGS]
        return "".join(out)

    def _html_block(self, html: str, source, owner, scene) -> str:
        """A block of raw HTML as paragraphs and images, centred where it asked to be."""
        blocks: list[str] = []
        current: list = []
        centred = 0

        def flush() -> None:
            marks = MarkStack()
            body = self._html_inline(current, marks, source, owner, scene).strip()
            body += "".join(f"</{self._TAGS[mark]}>" for mark in marks.drain() if mark in self._TAGS)
            current.clear()
            if body:
                blocks.append(f'<p class="html-block{" center" if centred else ""}">{body}</p>')

        for event in read_html(html):
            if isinstance(event, HtmlImage):
                flush()
                blocks.append(
                    f'<div class="figure{" center" if centred else ""}">'
                    f"{self._html_image(event, source, owner, scene)}</div>"
                )
            elif isinstance(event, (HtmlOpen, HtmlClose)) and event.mark in {"para", "center"}:
                flush()
                if event.mark == "center":
                    centred = max(0, centred + (1 if isinstance(event, HtmlOpen) else -1))
            else:
                current.append(event)
        flush()
        return "\n".join(blocks) + "\n"

    def _inline(self, children: list, source: Path | None, owner: str, scene: str = "") -> list:
        """Embed images, and unwrap links that would dangle inside the book.

        A link to another repository file (a character sheet, a plan) or to
        an anchor has nothing to land on in the EPUB, and readers and store
        checks treat a dangling link as an error. Its text stays; only web
        and mail links stay clickable.
        """
        kept = []
        dropping: list[bool] = []
        marks = MarkStack()
        for child in children:
            if child.type == "html_inline":
                raw = child.content
                child.content = "" if marks.skipping else self._html_inline(read_html(raw), marks, source, owner, scene)
                marks.track_skips(raw)
            elif marks.skipping:
                continue
            elif child.type == "image":
                child.attrSet("src", self._images.add(str(child.attrGet("src") or ""), source, owner, scene))
            elif child.type == "link_open":
                href = str(child.attrGet("href") or "")
                dropping.append(urlparse(href).scheme not in {"http", "https", "mailto"})
                if dropping[-1]:
                    continue
            elif child.type == "link_close" and dropping and dropping.pop():
                continue
            kept.append(child)
        if marks.open:
            from markdown_it.token import Token

            closing = Token("html_inline", "", 0)
            closing.content = "".join(f"</{self._TAGS[mark]}>" for mark in marks.drain() if mark in self._TAGS)
            kept.append(closing)
        return kept


def resolve_image(root: Path | None, src: str, source: Path | None, owner: str) -> Path:
    """Find the file a scene's image points at, or explain why it cannot be used.

    *source* is the scene's path below *root*, so a relative ``src`` is read
    from the scene's own folder, and a ``/``-rooted one from the repository.
    Every renderer uses these rules, so an image that works in the EPUB works
    in the PDF too.
    """
    src = repository_src(src)
    parsed = urlparse(src)
    if parsed.scheme in {"http", "https"} or src.startswith("//"):
        raise ExportError(
            f"{owner} uses an image from the web ({src}). A book cannot load "
            "images from the internet; save it into the repository and link that copy."
        )
    if parsed.scheme or not parsed.path:
        raise ExportError(f"{owner} has an image Proseview cannot include: {src!r}")
    if root is None:
        raise ExportError(f"{owner} has an image, but the book has no folder to find it in")
    root = root.resolve()
    relative = Path(unquote(parsed.path))
    base = (root / source).parent if source is not None else root
    candidate = (root / relative.relative_to("/")) if relative.is_absolute() else base / relative
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ExportError(f"{owner} links an image outside the repository: {src}")
    if not resolved.is_file():
        raise ExportError(f"{owner} has an image that can't be found: {src}")
    if resolved.suffix.lower() not in IMAGE_TYPES:
        raise ExportError(
            f"{owner} has an image books cannot show ({resolved.suffix or 'no extension'}): "
            f"{src}. Use PNG, JPEG, GIF, SVG or WebP."
        )
    return resolved


class _Images:
    """Images referenced from scenes, copied into the book once each."""

    def __init__(self, root: Path | None) -> None:
        self.root = root.resolve() if root else None
        self.items: list[_Item] = []
        self._by_path: dict[Path, str] = {}

    def add(self, src: str, source: Path | None, owner: str, scene: str = "") -> str:
        try:
            return self._add(src, source, owner)
        except ExportError as exc:
            raise ExportError(str(exc), scene=scene) from None

    def _add(self, src: str, source: Path | None, owner: str) -> str:
        resolved = resolve_image(self.root, src, source, owner)
        media_type = IMAGE_TYPES[resolved.suffix.lower()]
        if resolved not in self._by_path:
            n = len(self.items) + 1
            href = f"images/image-{n:03d}{resolved.suffix.lower()}"
            self.items.append(_Item(f"image-{n:03d}", href, media_type, resolved.read_bytes()))
            self._by_path[resolved] = href
        return f"../{self._by_path[resolved]}"


class _Writer:
    def __init__(self, book: Book, options: EpubOptions) -> None:
        if options.version not in EPUB_VERSIONS:
            raise ExportError(
                f"Unknown EPUB version {options.version!r}; expected one of {', '.join(EPUB_VERSIONS)}"
            )
        if options.style is None:
            raise ExportError("An EPUB needs a book style")
        if options.style.css is None:
            raise ExportError(f"{options.style.name} has no e-book design. Choose another style for an EPUB.")
        self.book = book
        self.options = options
        self.style = options.style
        self.v3 = options.version == "epub3"
        self.items: list[_Item] = []
        self.spine: list[str] = []
        self.nav: list[_NavEntry] = []
        self.images = _Images(book.root)
        self.markdown = _Markdown(self.images)
        self.stylesheets: list[str] = []
        self.cover_href = ""
        self.first_text_href = ""
        self.toc_href = ""

    # -- markup helpers ---------------------------------------------------

    def _section(self) -> str:
        return "section" if self.v3 else "div"

    def _type(self, value: str) -> str:
        return f' epub:type="{value}"' if self.v3 else ""

    def _role(self, value: str) -> str:
        return f' role="{value}"' if self.v3 else ""

    def _page(self, title: str, body: str, *, body_type: str = "") -> bytes:
        lang = _esc(self.book.language)
        links = "\n".join(
            f'    <link rel="stylesheet" type="text/css" href="../{href}" />' for href in self.stylesheets
        )
        if self.v3:
            head = (
                '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
                f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
                f'xml:lang="{lang}" lang="{lang}">\n<head>\n    <meta charset="utf-8" />\n'
            )
        else:
            head = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">\n'
                f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">\n<head>\n'
                '    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
            )
        body_attr = self._type(body_type) if body_type else ""
        page = (
            f"{head}    <title>{_txt(title)}</title>\n{links}\n</head>\n"
            f"<body{body_attr}>\n{body}\n</body>\n</html>\n"
        )
        return page.encode("utf-8")

    def _add(self, item: _Item, *, in_spine: bool = True) -> None:
        self.items.append(item)
        if in_spine:
            self.spine.append(item.id)

    def _scene_owner(self, scene: SceneDocument) -> str:
        return f"Scene {scene.title!r} ({scene.path.as_posix()})"

    def _render_scene(self, scene: SceneDocument, *, first_class: str, shift: int) -> str:
        return self.markdown.render(
            scene.markdown, source=scene.path, owner=self._scene_owner(scene),
            shift_headings=shift, first_class=first_class, scene=scene.key,
        )

    def _scene_break(self) -> str:
        mark = _esc(self.style.scene_break)
        if self.v3:
            return f'<div class="scene-break" role="separator"><span aria-hidden="true">{mark}</span></div>'
        return f'<p class="scene-break">{mark}</p>'

    def _chapter_heading_parts(self, chapter: BookChapter) -> tuple[str, str]:
        return chapter_label(chapter.number, self.style.chapter_numbering), chapter.title

    def _chapter_nav_label(self, chapter: BookChapter) -> str:
        number, title = self._chapter_heading_parts(chapter)
        if number and title:
            return f"{number}: {title}"
        return title or number or f"Chapter {chapter.number}"

    # -- pages --------------------------------------------------------------

    def add_stylesheets(self) -> None:
        self._add(_Item("style", "styles/book.css", "text/css", self.style.css.encode("utf-8")), in_spine=False)
        self.stylesheets.append("styles/book.css")
        for n, sheet in enumerate(self.options.css, start=1):
            if not sheet.is_file():
                raise ExportError(f"Stylesheet {sheet} does not exist")
            href = f"styles/extra-{n}.css"
            self._add(_Item(f"style-extra-{n}", href, "text/css", sheet.read_bytes()), in_spine=False)
            self.stylesheets.append(href)

    def add_cover(self) -> None:
        cover = self.options.cover_image
        if cover is None:
            return
        if not cover.is_file():
            raise ExportError(f"Cover image {cover} does not exist")
        media_type = IMAGE_TYPES.get(cover.suffix.lower())
        if media_type is None or media_type == "image/svg+xml":
            raise ExportError(f"Cover image {cover.name} must be a JPEG, PNG, GIF or WebP file")
        href = f"images/cover{cover.suffix.lower()}"
        self._add(
            _Item("cover-image", href, media_type, cover.read_bytes(),
                  properties="cover-image" if self.v3 else ""),
            in_spine=False,
        )
        self.cover_href = "text/cover.xhtml"
        body = (
            f'<{self._section()} class="cover"{self._type("cover")}>\n'
            f'  <img src="../{href}" alt="{_txt(self.book.title)}" />\n</{self._section()}>'
        )
        self._add(_Item("cover", self.cover_href, "application/xhtml+xml", self._page("Cover", body)))

    def add_title_page(self) -> None:
        book = self.book
        lines = [f'<{self._section()} class="title-page"{self._type("titlepage")}>',
                 f'  <h1 class="title">{_txt(book.title)}</h1>']
        if book.subtitle:
            lines.append(f'  <p class="subtitle">{_txt(book.subtitle)}</p>')
        if book.author:
            lines.append(f'  <p class="author">{_txt(book.author)}</p>')
        if book.note:
            lines.append(f'  <p class="note">{_txt(book.note)}</p>')
        lines.append(f"</{self._section()}>")
        self._add(_Item("title-page", "text/title.xhtml", "application/xhtml+xml",
                        self._page(book.title, "\n".join(lines), body_type="frontmatter")))

    def add_chapter(self, index: int, chapter: BookChapter) -> None:
        href = f"text/chapter-{index:03d}.xhtml"
        anchor = f"chapter-{chapter.number}"
        number, title = self._chapter_heading_parts(chapter)
        spans = []
        if number:
            spans.append(f'<span class="chapter-number">{_txt(number)}</span>')
        if title or not number:
            spans.append(f'<span class="chapter-title">{_txt(title or f"Chapter {chapter.number}")}</span>')
        parts = [
            f'<{self._section()} class="chapter" id="{anchor}"{self._type("chapter")}>',
            f'  <h1 class="chapter-heading">{" ".join(spans)}</h1>',
        ]
        entry = _NavEntry(self._chapter_nav_label(chapter), href)
        show_titles = self.options.show_scene_titles
        for i, scene in enumerate(chapter.scenes):
            scene_id = f"scene-{scene.chapter_number}-{scene.scene_number}"
            if i and not show_titles:
                # Novels mark a change of scene with the style's break, not a title.
                parts.append(f"  {self._scene_break()}")
            parts.append(f'  <{self._section()} class="scene" id="{scene_id}">')
            if show_titles:
                parts.append(f'    <h2 class="scene-title">{_txt(scene.title)}</h2>')
                entry.children.append(_NavEntry(scene.title, f"{href}#{scene_id}"))
            first = "opener" if i == 0 else "first"
            parts.append(self._render_scene(scene, first_class=first, shift=2))
            parts.append(f"  </{self._section()}>")
        parts.append(f"</{self._section()}>")
        page_title = self._chapter_nav_label(chapter)
        self._add(_Item(f"chapter-{index:03d}", href, "application/xhtml+xml",
                        self._page(page_title, "\n".join(parts), body_type="bodymatter")))
        self.first_text_href = self.first_text_href or href
        self.nav.append(entry)

    def add_single_scene(self, scene: SceneDocument) -> None:
        href = "text/scene.xhtml"
        chapter = self.book.chapters[0]
        number, title = self._chapter_heading_parts(chapter)
        where = " · ".join(part for part in (number, title) if part)
        header = ['<header class="scene-header">', f'  <p class="book-title">{_txt(self.book.title)}</p>']
        if where:
            header.append(f'  <p class="scene-chapter">{_txt(where)}</p>')
        header.append(f'  <h1 class="scene-heading">{_txt(scene.title)}</h1>')
        header.append("</header>")
        if not self.v3:
            header = [line.replace("<header", "<div").replace("</header>", "</div>") for line in header]
        body = "\n".join([
            f'<{self._section()} class="scene single-scene" id="scene-{scene.chapter_number}-{scene.scene_number}">',
            *header,
            self._render_scene(scene, first_class="first", shift=1),
            f"</{self._section()}>",
        ])
        self._add(_Item("scene", href, "application/xhtml+xml",
                        self._page(scene.title, body, body_type="bodymatter")))
        self.first_text_href = href
        self.nav.append(_NavEntry(scene.title, href))

    def add_appendix(self, index: int, section) -> None:
        href = f"text/appendix-{index:02d}.xhtml"
        heading = f"Appendix: {section.label}"
        parts = [f'<{self._section()} class="appendix" id="appendix-{index}"{self._type("appendix")}>',
                 f"  <h1>{_txt(heading)}</h1>"]
        entry = _NavEntry(heading, href)
        ids: set[str] = set()
        anchors: list[tuple[str, str]] = []
        for doc_title, _ in section.documents:
            anchor = base = f"appendix-{index}-{_slug(doc_title)}"
            n = 2
            while anchor in ids:
                anchor, n = f"{base}-{n}", n + 1
            ids.add(anchor)
            anchors.append((doc_title, anchor))
        if len(section.documents) > 1:
            parts.append('  <ul class="appendix-contents">')
            parts += [f'    <li><a href="#{a}">{_txt(t)}</a></li>' for t, a in anchors]
            parts.append("  </ul>")
        for (doc_title, content), (_, anchor) in zip(section.documents, anchors):
            # The document's own H1 gives way to the folder-derived title, and
            # its remaining headings sit two levels down, as with pandoc.
            body = re.sub(r"^# [^\n]*\n*", "", content, count=1).strip()
            parts.append(f'  <h2 id="{anchor}">{_txt(doc_title)}</h2>')
            parts.append(self.markdown.render(
                body, source=None, owner=f"Appendix document {doc_title!r}", shift_headings=2,
            ))
            entry.children.append(_NavEntry(doc_title, f"{href}#{anchor}"))
        parts.append(f"</{self._section()}>")
        self._add(_Item(f"appendix-{index:02d}", href, "application/xhtml+xml",
                        self._page(heading, "\n".join(parts), body_type="backmatter")))
        self.nav.append(entry)

    # -- navigation -----------------------------------------------------------

    def _nav_list(self, entries: list[_NavEntry], indent: str, *, relative: bool) -> list[str]:
        lines = [f"{indent}<ol>"]
        for entry in entries:
            href = entry.href.removeprefix("text/") if relative else entry.href
            line = f'{indent}  <li><a href="{_esc(href)}">{_txt(entry.label)}</a>'
            if entry.children:
                lines.append(line)
                lines += self._nav_list(entry.children, indent + "    ", relative=relative)
                lines.append(f"{indent}  </li>")
            else:
                lines.append(line + "</li>")
        lines.append(f"{indent}</ol>")
        return lines

    def nav_page(self, *, in_spine: bool) -> bytes:
        """The contents page: the EPUB 3 nav document, or a plain page for EPUB 2.

        A landmark may only point at a page in the reading order, so the
        contents landmark is left out when the page is kept out of the spine.
        """
        if self.v3:
            body = ['<nav epub:type="toc" id="toc" role="doc-toc">', "  <h1>Contents</h1>"]
            body += self._nav_list(self.nav, "  ", relative=True)
            body.append("</nav>")
            landmarks = [('toc', 'nav.xhtml#toc', 'Contents')] if in_spine else []
            if self.first_text_href:
                landmarks.append(("bodymatter", self.first_text_href.removeprefix("text/"), "Start of book"))
            if self.cover_href:
                landmarks.insert(0, ("cover", self.cover_href.removeprefix("text/"), "Cover"))
            body.append('<nav epub:type="landmarks" id="landmarks" hidden="hidden">')
            body.append("  <h1>Landmarks</h1>\n  <ol>")
            body += [f'    <li><a epub:type="{t}" href="{h}">{_txt(label)}</a></li>' for t, h, label in landmarks]
            body.append("  </ol>\n</nav>")
        else:
            body = ['<div class="contents">', "  <h1>Contents</h1>"]
            body += self._nav_list(self.nav, "  ", relative=True)
            body.append("</div>")
        return self._page("Contents", "\n".join(body))

    def ncx(self) -> bytes:
        counter = 0

        def points(entries: list[_NavEntry], indent: str) -> list[str]:
            nonlocal counter
            out = []
            for entry in entries:
                counter += 1
                out.append(f'{indent}<navPoint id="nav-{counter}" playOrder="{counter}">')
                out.append(f"{indent}  <navLabel><text>{_txt(entry.label)}</text></navLabel>")
                out.append(f'{indent}  <content src="{_esc(entry.href)}" />')
                out += points(entry.children, indent + "  ")
                out.append(f"{indent}</navPoint>")
            return out

        depth = 2 if any(entry.children for entry in self.nav) else 1
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="{_esc(self.book.language)}">',
            "  <head>",
            f'    <meta name="dtb:uid" content="{_esc(self.book.identifier)}" />',
            f'    <meta name="dtb:depth" content="{depth}" />',
            '    <meta name="dtb:totalPageCount" content="0" />',
            '    <meta name="dtb:maxPageNumber" content="0" />',
            "  </head>",
            f"  <docTitle><text>{_txt(self.book.title)}</text></docTitle>",
        ]
        if self.book.author:
            lines.append(f"  <docAuthor><text>{_txt(self.book.author)}</text></docAuthor>")
        lines.append("  <navMap>")
        lines += points(self.nav, "    ")
        lines += ["  </navMap>", "</ncx>", ""]
        return "\n".join(lines).encode("utf-8")

    def opf(self) -> bytes:
        book = self.book
        modified = (self.options.modified or _dt.datetime.now(_dt.timezone.utc)).astimezone(_dt.timezone.utc)
        has_images = any(item.media_type.startswith("image/") and item.id != "cover-image" for item in self.items)
        meta: list[str] = []
        if self.v3:
            meta += [
                f'    <dc:identifier id="book-id">{_esc(book.identifier)}</dc:identifier>',
                f"    <dc:title>{_txt(book.title)}</dc:title>",
            ]
            if book.subtitle:
                meta += [
                    f'    <dc:title id="subtitle">{_txt(book.subtitle)}</dc:title>',
                    '    <meta refines="#subtitle" property="title-type">subtitle</meta>',
                ]
            meta.append(f"    <dc:language>{_esc(book.language)}</dc:language>")
            if book.author:
                meta.append(f'    <dc:creator id="creator">{_txt(book.author)}</dc:creator>')
            meta.append(f'    <meta property="dcterms:modified">{modified.strftime("%Y-%m-%dT%H:%M:%SZ")}</meta>')
            access_modes = ["textual"] + (["visual"] if has_images else [])
            meta += [f'    <meta property="schema:accessMode">{m}</meta>' for m in access_modes]
            meta.append('    <meta property="schema:accessModeSufficient">textual</meta>')
            features = ["structuralNavigation", "readingOrder"]
            if book.has_contents:
                features.append("tableOfContents")
            if has_images:
                features.append("alternativeText")
            meta += [f'    <meta property="schema:accessibilityFeature">{f}</meta>' for f in features]
            meta.append('    <meta property="schema:accessibilityHazard">none</meta>')
            meta.append(
                '    <meta property="schema:accessibilitySummary">Reflowable text with '
                "headings for each chapter, in reading order.</meta>"
            )
        else:
            meta += [
                f'    <dc:identifier id="book-id" opf:scheme="UUID">{_esc(book.identifier)}</dc:identifier>',
                f"    <dc:title>{_txt(book.title)}</dc:title>",
                f"    <dc:language>{_esc(book.language)}</dc:language>",
                f'    <dc:date opf:event="modification">{modified.strftime("%Y-%m-%d")}</dc:date>',
            ]
            if book.author:
                meta.append(f'    <dc:creator opf:role="aut">{_txt(book.author)}</dc:creator>')
        if self.options.cover_image:
            meta.append('    <meta name="cover" content="cover-image" />')

        manifest = []
        for item in self.items:
            props = f' properties="{item.properties}"' if item.properties else ""
            manifest.append(f'    <item id="{item.id}" href="{_esc(item.href)}" media-type="{item.media_type}"{props} />')
        spine = [f'    <itemref idref="{idref}" />' for idref in self.spine]
        package_open = (
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" '
            f'xml:lang="{_esc(book.language)}">'
            if self.v3 else
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="book-id">'
        )
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            package_open,
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"'
            + ("" if self.v3 else ' xmlns:opf="http://www.idpf.org/2007/opf"') + ">",
            *meta,
            "  </metadata>",
            "  <manifest>",
            *manifest,
            "  </manifest>",
            '  <spine toc="ncx">',
            *spine,
            "  </spine>",
        ]
        if not self.v3:
            guide = []
            if self.cover_href:
                guide.append(f'    <reference type="cover" title="Cover" href="{self.cover_href}" />')
            if self.toc_href:
                guide.append(f'    <reference type="toc" title="Contents" href="{self.toc_href}" />')
            if self.first_text_href:
                guide.append(f'    <reference type="text" title="Start" href="{self.first_text_href}" />')
            if guide:
                lines += ["  <guide>", *guide, "  </guide>"]
        lines += ["</package>", ""]
        return "\n".join(lines).encode("utf-8")

    # -- assembly -------------------------------------------------------------

    def _progress(self, step: str, fraction: float) -> None:
        if self.options.progress is not None:
            self.options.progress(step, fraction)

    def build(self) -> list[_Item]:
        book = self.book
        self.add_stylesheets()
        self.add_cover()
        toc_position = None
        if book.has_contents:
            self.add_title_page()
            toc_position = len(self.spine)
        if book.kind == "scene":
            self._progress("Laying out the scene", 0.5)
            self.add_single_scene(book.chapters[0].scenes[0])
        else:
            total = len(book.chapters)
            for index, chapter in enumerate(book.chapters, start=1):
                self._progress(f"Laying out chapter {chapter.number}", (index - 1) / max(total, 1))
                self.add_chapter(index, chapter)
        if book.appendices:
            self._progress("Adding the appendices", 0.95)
        for index, section in enumerate(book.appendices, start=1):
            self.add_appendix(index, section)

        nav_href = "text/nav.xhtml"
        nav_item = _Item("nav", nav_href, "application/xhtml+xml", self.nav_page(in_spine=toc_position is not None),
                         properties="nav" if self.v3 else "")
        self.items.append(nav_item)
        if toc_position is not None:
            # The contents page follows the title page in reading order; a
            # single chapter or scene keeps it out of the way.
            self.spine.insert(toc_position, "nav")
            self.toc_href = nav_href
        elif not self.v3:
            # EPUB 2 has no nav document, so an unlisted page would only be
            # an orphan in the manifest.
            self.items.remove(nav_item)
        self.items.append(_Item("ncx", "toc.ncx", "application/x-dtbncx+xml", self.ncx()))
        self.items.extend(self.images.items)
        return self.items


_CONTAINER = b"""<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""


def write_epub(book: Book, output: Path, options: EpubOptions) -> Path:
    """Write *book* to *output* and return the path."""
    writer = _Writer(book, options)
    items = writer.build()
    opf = writer.opf()

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    try:
        with zipfile.ZipFile(partial, "w") as archive:
            # The mimetype entry must come first and be stored uncompressed,
            # so a reader can identify the file from its opening bytes.
            mimetype = zipfile.ZipInfo("mimetype")
            mimetype.compress_type = zipfile.ZIP_STORED
            archive.writestr(mimetype, b"application/epub+zip")
            archive.writestr("META-INF/container.xml", _CONTAINER, zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
            for item in items:
                archive.writestr(f"OEBPS/{item.href}", item.data, zipfile.ZIP_DEFLATED)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output
