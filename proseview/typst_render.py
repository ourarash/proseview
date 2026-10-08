"""Turn scene Markdown into Typst markup, for the PDF renderers.

Scenes are parsed by markdown-it exactly as the EPUB writer parses them (the
same typographer, the same comment stripping, the same image rules), and the
token stream is written out as Typst markup instead of XHTML.

Prose is full of characters that mean something to Typst: ``#`` starts code,
``$`` maths, ``@`` a reference, ``*`` and ``_`` emphasis, ``<label>`` a label,
``//`` a comment, ``=`` at a line start a heading, ``- `` and ``1.`` lists,
and ``https://`` turns into a link. :func:`escape` backslash-escapes every
one of them, so whatever a writer types reaches the page as written and can
never be run as Typst code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .book import SHORT_OPENER, ExportError
from .raw_html import HtmlBreak, HtmlClose, HtmlImage, HtmlOpen, HtmlText, MarkStack, image_only, read_html, straighten_tag_quotes

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: Characters with a meaning somewhere in Typst markup, plus the ones that
#: would continue an embedded expression (``#emph[x].`` or ``#emph[x](``).
_SPECIAL = re.compile(r"""([\\#$@*_`<>\[\]{}()=+\-~'"/.:;])""")


def escape(text: str) -> str:
    """Make *text* literal Typst markup: every special character is escaped.

    Line breaks become spaces; a paragraph break is the renderer's to make.
    """
    return _SPECIAL.sub(r"\\\1", re.sub(r"\s*\n\s*", " ", text))


def string(text: str) -> str:
    """A Typst string literal holding *text*."""
    body = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
    return f'"{body}"'


def _markdown():
    from markdown_it import MarkdownIt

    return MarkdownIt(
        "commonmark", {"html": True, "typographer": True}
    ).enable(["table", "strikethrough", "replacements", "smartquotes"])


@dataclass
class RenderContext:
    """What rendering one scene needs to know about the book around it."""

    root: Path | None
    source: Path | None = None
    owner: str = ""
    scene: str = ""
    #: Added to every heading level inside the scene, below the chapter's.
    shift_headings: int = 2
    #: Images used, as root-relative paths, so the caller can report them.
    images: list[Path] = field(default_factory=list)


class TypstRenderer:
    """Render Markdown to Typst markup. One instance can render many scenes."""

    def __init__(self) -> None:
        self._md = _markdown()

    # -- blocks ---------------------------------------------------------------

    def render(self, text: str, ctx: RenderContext, *, opener: bool = False, noindent: bool = False) -> str:
        """Render *text*.

        With *opener*, the first paragraph gets the style's drop cap; with
        *noindent*, it starts flush left, as a paragraph after a scene break
        or a title does.
        """
        tokens = self._md.parse(straighten_tag_quotes(_COMMENT_RE.sub("", text)))
        out, _ = self._blocks(tokens, 0, ctx, opener=opener, stop=None, noindent=noindent)
        return "\n\n".join(part for part in out if part.strip())

    def _blocks(
        self, tokens: list, i: int, ctx: RenderContext, *, opener: bool, stop: str | None, noindent: bool = False,
    ):
        parts: list[str] = []
        first_paragraph = True
        while i < len(tokens):
            token = tokens[i]
            kind = token.type
            if stop and kind == stop:
                return parts, i + 1
            if kind == "paragraph_open":
                inline = tokens[i + 1]
                if image_only(inline.children or []):
                    # A picture on its own: not the drop-cap paragraph.
                    parts.append(self._inline(inline.children or [], ctx).strip())
                    i += 3
                    continue
                if opener and first_paragraph and token.level == 0:
                    parts.append(self._opener(inline.children or [], ctx))
                elif noindent and first_paragraph and token.level == 0:
                    parts.append("#noindent[" + self._inline(inline.children or [], ctx) + "]")
                else:
                    parts.append(self._inline(inline.children or [], ctx))
                first_paragraph = False
                i += 3
            elif kind == "heading_open":
                level = min(6, int(token.tag[1]) + ctx.shift_headings)
                body = self._inline(tokens[i + 1].children or [], ctx)
                parts.append(f"#heading(level: {level}, outlined: false, bookmarked: false)[{body}]")
                first_paragraph = False
                i += 3
            elif kind == "blockquote_open":
                inner, i = self._blocks(tokens, i + 1, ctx, opener=False, stop="blockquote_close")
                parts.append("#quote(block: true)[" + "\n\n".join(inner) + "]")
            elif kind in {"bullet_list_open", "ordered_list_open"}:
                close = kind.replace("_open", "_close")
                start = token.attrGet("start")
                items, i = self._list_items(tokens, i + 1, ctx, close)
                body = ", ".join(f"[{item}]" for item in items)
                if kind == "bullet_list_open":
                    parts.append(f"#list({body})")
                else:
                    parts.append(f"#enum(start: {int(start or 1)}, {body})")
            elif kind in {"fence", "code_block"}:
                parts.append(f"#raw(block: true, {string(token.content.rstrip(chr(10)))})")
                i += 1
            elif kind == "hr":
                parts.append("#align(center, line(length: 30%, stroke: 0.5pt))")
                i += 1
            elif kind == "table_open":
                table, i = self._table(tokens, i + 1, ctx)
                parts.append(table)
            elif kind == "html_block":
                parts.append(self._html_block(token.content, ctx))
                i += 1
            else:
                i += 1
            first_paragraph = first_paragraph and kind not in {"paragraph_open"}
        return parts, i

    def _list_items(self, tokens: list, i: int, ctx: RenderContext, close: str):
        items: list[str] = []
        while i < len(tokens) and tokens[i].type != close:
            if tokens[i].type == "list_item_open":
                inner, i = self._blocks(tokens, i + 1, ctx, opener=False, stop="list_item_close")
                items.append("\n\n".join(inner))
            else:
                i += 1
        return items, i + 1

    def _table(self, tokens: list, i: int, ctx: RenderContext):
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
                rows[-1].append(self._inline(tokens[i].children or [], ctx))
            i += 1
        columns = max((len(row) for row in rows), default=1)
        cells = []
        for n, row in enumerate(rows):
            row = row + [""] * (columns - len(row))
            cells += [f"[#strong[{cell}]]" if n < header_rows else f"[{cell}]" for cell in row]
        return f"#table(columns: {columns}, inset: 5pt, align: left, {', '.join(cells)})", i + 1

    # -- inline -------------------------------------------------------------------

    def _inline(self, children: list, ctx: RenderContext) -> str:
        out: list[str] = []
        stack: list[str] = []  # what each open mark closes with
        marks = MarkStack()  # marks opened by inline HTML
        for child in children:
            kind = child.type
            if kind == "html_inline":
                if not marks.skipping:
                    out.append(self._html_inline(read_html(child.content), marks, ctx))
                marks.track_skips(child.content)
                continue
            if marks.skipping:
                continue
            if kind == "text":
                out.append(escape(child.content))
            elif kind == "softbreak":
                out.append(" ")
            elif kind == "hardbreak":
                out.append("#linebreak()")
            elif kind == "code_inline":
                out.append(f"#raw({string(child.content)})")
            elif kind in {"em_open", "strong_open", "s_open"}:
                out.append({"em_open": "#emph[", "strong_open": "#strong[", "s_open": "#strike["}[kind])
                stack.append("]")
            elif kind in {"em_close", "strong_close", "s_close"}:
                out.append(stack.pop() if stack else "")
            elif kind == "link_open":
                href = str(child.attrGet("href") or "")
                if urlparse(href).scheme in {"http", "https", "mailto"}:
                    out.append(f"#link({string(href)})[")
                    stack.append("]")
                else:
                    # A link to a repository file has nothing to land on in
                    # the book; its text stays, as in the EPUB.
                    stack.append("")
            elif kind == "link_close":
                out.append(stack.pop() if stack else "")
            elif kind == "image":
                alt = "".join(c.content for c in (child.children or []) if c.type == "text") or child.content
                out.append(self._image(str(child.attrGet("src") or ""), alt, None, ctx))
        out += ["]" for _ in marks.drain()]
        out += reversed(stack)
        return "".join(out)

    def _image(self, src: str, alt: str, width: float | None, ctx: RenderContext) -> str:
        from .epub import resolve_image

        try:
            path = resolve_image(ctx.root, src, ctx.source, ctx.owner)
        except ExportError as exc:
            raise ExportError(str(exc), scene=ctx.scene) from None
        relative = path.relative_to(ctx.root.resolve()).as_posix()
        ctx.images.append(Path(relative))
        size = f", width: {round(width * 100)}%" if width else ""
        return f"#book-image({string('/' + relative)}, alt: {string(alt)}{size})"

    # -- raw HTML -------------------------------------------------------------------

    _MARKS = {"em": "#emph[", "strong": "#strong[", "sup": "#super[", "sub": "#sub["}

    def _html_inline(self, events: list, marks: MarkStack, ctx: RenderContext) -> str:
        out = []
        for event in events:
            if isinstance(event, HtmlText):
                out.append(escape(event.text))
            elif isinstance(event, HtmlBreak):
                out.append("#linebreak()")
            elif isinstance(event, HtmlImage):
                out.append(self._image(event.src, event.alt, event.width, ctx))
            elif isinstance(event, HtmlOpen) and event.mark in self._MARKS:
                marks.push(event.mark)
                out.append(self._MARKS[event.mark])
            elif isinstance(event, HtmlClose) and event.mark in self._MARKS:
                out += ["]" for mark in marks.pop(event.mark) if mark in self._MARKS]
        return "".join(out)

    def _html_block(self, html: str, ctx: RenderContext) -> str:
        """A block of raw HTML as paragraphs and images, centred where it asked to be."""
        blocks: list[str] = []
        current: list = []
        centred = 0

        def place(body: str) -> None:
            blocks.append(f"#align(center)[{body}]" if centred else body)

        def flush() -> None:
            marks = MarkStack()
            body = self._html_inline(current, marks, ctx).strip()
            body += "]" * len([m for m in marks.drain() if m in self._MARKS])
            current.clear()
            if body:
                place(body)

        for event in read_html(html):
            if isinstance(event, HtmlImage):
                flush()
                place(self._image(event.src, event.alt, event.width, ctx))
            elif isinstance(event, (HtmlOpen, HtmlClose)) and event.mark in {"para", "center"}:
                flush()
                if event.mark == "center":
                    centred = max(0, centred + (1 if isinstance(event, HtmlOpen) else -1))
            else:
                current.append(event)
        flush()
        return "\n\n".join(blocks)

    # -- the drop-cap paragraph ---------------------------------------------------

    def _opener(self, children: list, ctx: RenderContext) -> str:
        """A chapter's first paragraph, as words the style can set beside a drop cap.

        The style needs the opening letter on its own and the rest as words it
        can measure line by line, so formatting is applied word by word. A
        paragraph that opens with anything but text (an image, code) is left
        as a plain paragraph.
        """
        if not children or children[0].type not in {"text", "em_open", "strong_open"}:
            return self._inline(children, ctx)
        if any(c.type in {"image", "html_inline"} for c in children):
            # Inline HTML (an image, a mark) is laid out as an ordinary paragraph.
            return self._inline(children, ctx)
        # The initial is the first letter with any opening punctuation before
        # it ("“C"), as CSS's ::first-letter takes it.
        first_text = next((c.content for c in children if c.type == "text" and c.content.strip()), "")
        match = re.match(r"^\s*(\W*\w)", first_text)
        if not match:
            return self._inline(children, ctx)
        initial = match.group(1)

        words: list[str] = []
        current: list[str] = []
        marks: list[str] = []
        pending_initial = [True]
        joined = [True]

        def flush() -> None:
            if current:
                words.append("".join(current))
                current.clear()

        def push_text(text: str) -> None:
            for piece in re.split(r"(\s+)", text):
                if not piece:
                    continue
                if piece.isspace():
                    flush()
                    continue
                if pending_initial[0]:
                    pending_initial[0] = False
                    piece = piece[len(initial):]
                    if not piece:
                        joined[0] = False
                        continue
                wrapped = escape(piece)
                for mark in reversed(marks):
                    wrapped = f"#{mark}[{wrapped}]"
                current.append(wrapped)

        for child in children:
            kind = child.type
            if kind == "text":
                push_text(child.content)
            elif kind in {"softbreak", "hardbreak"}:
                flush()
            elif kind in {"em_open", "strong_open", "s_open"}:
                marks.append({"em_open": "emph", "strong_open": "strong", "s_open": "strike"}[kind])
            elif kind in {"em_close", "strong_close", "s_close"}:
                if marks:
                    marks.pop()
            elif kind == "code_inline":
                current.append(f"#raw({string(child.content)})")
            # A link's words stay, unlinked: a drop-cap opener is no place for one.
        flush()
        body = ", ".join(f"[{word}]" for word in words)
        short = sum(len(c.content) for c in children if c.type == "text") < SHORT_OPENER
        return (
            f"#opener([{escape(initial)}], ({body},), joined: {'true' if joined[0] else 'false'}"
            + (", short: true)" if short else ")")
        )
