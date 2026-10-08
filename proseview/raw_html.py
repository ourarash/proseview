"""Make sense of raw HTML in a scene, for the book renderers.

Writers put a little HTML in Markdown, mostly ``<img>`` tags with a width
the dashboard's preview honours. A book should show the picture, not the
tag, so the renderers ask this module what a fragment of HTML amounts to,
as a stream of events:

- ``<img>`` is an :class:`HtmlImage`, its ``src`` read the way the dashboard
  reads it (a ``/repo-asset/...`` address is the file at that path in the
  book) and its ``width`` kept as a share of the page
- ``<br>`` is a line break
- ``<em>``/``<i>``, ``<strong>``/``<b>``, ``<sup>``, ``<sub>`` and ``<center>``
  (or ``align="center"`` / ``text-align: center``) open and close those marks
- ``<p>`` and ``<div>`` are paragraphs
- every other tag is left out and its text kept, so ``<span>word</span>``
  reads "word"; ``<script>``, ``<style>``, ``<iframe>`` and the like are left
  out with their contents

Nothing a fragment holds is ever passed through as markup, so one stray or
unclosed tag cannot make an EPUB page invalid or reach Typst as code: the
renderers write each event themselves, and close whatever was left open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote

#: The dashboard serves repository images under this address, so a scene
#: written in the dashboard may point at it.
REPO_ASSET_PREFIX = "/repo-asset/"

#: Left out together with everything inside them.
_SKIP_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "title", "head", "noscript", "svg"}
#: Tags that mean something a book can show, by the mark they open.
MARKS = {"em": "em", "i": "em", "cite": "em", "strong": "strong", "b": "strong", "sup": "sup", "sub": "sub"}
_BLOCKS = {"p", "div", "figure", "figcaption", "blockquote", "section"}

#: The content width a scene's ``width="600"`` is measured against: the
#: dashboard's reading column, so a 600 px picture fills the page and a
#: 300 px one half of it.
REFERENCE_WIDTH = 600

# Curly quotes around attribute values (a word processor's doing) read as
# straight ones, or `alt=“A dark room”` would break at every space.
_TAG_RE = re.compile(r"<[^<>]*>", re.DOTALL)
_CURLY = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'"})


@dataclass(frozen=True)
class HtmlImage:
    src: str
    alt: str = ""
    #: Share of the page width, 0 < width <= 1, or None to use the style's.
    width: float | None = None


@dataclass(frozen=True)
class HtmlText:
    text: str


@dataclass(frozen=True)
class HtmlBreak:
    pass


@dataclass(frozen=True)
class HtmlOpen:
    """A mark opens: ``em``, ``strong``, ``sup``, ``sub``, ``center`` or ``para``."""

    mark: str


@dataclass(frozen=True)
class HtmlClose:
    mark: str


HtmlEvent = HtmlImage | HtmlText | HtmlBreak | HtmlOpen | HtmlClose


def repository_src(src: str) -> str:
    """``/repo-asset/manuscript/x.png`` -> ``/manuscript/x.png`` (a path from the book's folder)."""
    src = src.strip()
    if src.startswith(REPO_ASSET_PREFIX):
        return "/" + unquote(src[len(REPO_ASSET_PREFIX):].split("?", 1)[0].split("#", 1)[0])
    return src


def _width(value: str | None) -> float | None:
    """``600`` / ``600px`` against the reference width, ``50%`` as given."""
    if not value:
        return None
    match = re.fullmatch(r"\s*([\d.]+)\s*(px|%)?\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    share = number / 100 if match.group(2) == "%" else number / REFERENCE_WIDTH
    return max(0.05, min(1.0, share)) if share > 0 else None


def _centred(attrs: dict) -> bool:
    style = str(attrs.get("style") or "").replace(" ", "").lower()
    return str(attrs.get("align") or "").lower() == "center" or "text-align:center" in style


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[HtmlEvent] = []
        self._skipping = 0
        #: For each open block tag, the marks it opened, to close at its end.
        self._block_marks: list[tuple[str, list[str]]] = []

    def handle_starttag(self, tag, attrs):
        self._start(tag, dict(attrs), closed=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, dict(attrs), closed=True)

    def _start(self, tag: str, attrs: dict, *, closed: bool) -> None:
        if tag in _SKIP_CONTENT:
            if not closed:
                self._skipping += 1
            return
        if self._skipping:
            return
        if tag == "img":
            src = str(attrs.get("src") or "").strip()
            if src:
                style_width = re.search(r"width\s*:\s*([\d.]+\s*(?:px|%)?)", str(attrs.get("style") or ""))
                width = _width(attrs.get("width") or (style_width.group(1) if style_width else None))
                self.events.append(HtmlImage(repository_src(src), str(attrs.get("alt") or "").strip(), width))
        elif tag == "br":
            self.events.append(HtmlBreak())
        elif tag in MARKS and not closed:
            self.events.append(HtmlOpen(MARKS[tag]))
        elif tag == "center" and not closed:
            self.events.append(HtmlOpen("center"))
        elif tag in _BLOCKS and not closed:
            opened = ["para"] + (["center"] if _centred(attrs) else [])
            self.events += [HtmlOpen(mark) for mark in opened]
            self._block_marks.append((tag, opened))

    def handle_endtag(self, tag):
        if tag in _SKIP_CONTENT:
            self._skipping = max(0, self._skipping - 1)
            return
        if self._skipping:
            return
        if tag in MARKS:
            self.events.append(HtmlClose(MARKS[tag]))
        elif tag == "center":
            self.events.append(HtmlClose("center"))
        elif tag in _BLOCKS:
            for index in range(len(self._block_marks) - 1, -1, -1):
                if self._block_marks[index][0] == tag:
                    _, opened = self._block_marks.pop(index)
                    self.events += [HtmlClose(mark) for mark in reversed(opened)]
                    break

    def handle_data(self, data):
        if self._skipping or not data:
            return
        if self.events and isinstance(self.events[-1], HtmlText):
            self.events[-1] = HtmlText(self.events[-1].text + data)
        else:
            self.events.append(HtmlText(data))


_TAG_LIKE_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^<>]*>", re.DOTALL)


def straighten_tag_quotes(text: str) -> str:
    """Straight quotes inside anything shaped like a tag, before Markdown sees it.

    ``alt=“A dark room”`` (a word processor's curly quotes) is not valid
    HTML, so a Markdown parser would leave the whole tag as text. Prose never
    puts quotes inside ``<…>``, so straightening them there is safe.
    """
    return _TAG_LIKE_RE.sub(lambda m: m.group(0).translate(_CURLY), text)


def image_only(children: list) -> bool:
    """Whether a paragraph's inline tokens are a single image and nothing else.

    A tag written over several lines is not an HTML block to Markdown, so a
    picture on a paragraph of its own arrives as inline HTML; it is still a
    figure, and never a chapter's drop-cap opener.
    """
    images = 0
    for child in children:
        if child.type in {"softbreak", "hardbreak"} or (child.type == "text" and not child.content.strip()):
            continue
        if child.type == "image":
            images += 1
        elif child.type == "html_inline":
            events = read_html(child.content)
            if any(not isinstance(e, HtmlImage) for e in events if not (isinstance(e, HtmlText) and not e.text.strip())):
                return False
            images += sum(isinstance(e, HtmlImage) for e in events)
        else:
            return False
    return images == 1


def read_html(fragment: str) -> list[HtmlEvent]:
    """What *fragment* shows a reader, as events in reading order."""
    reader = _Reader()
    reader.feed(_TAG_RE.sub(lambda m: m.group(0).translate(_CURLY), fragment))
    reader.close()
    return reader.events


class MarkStack:
    """Opened marks across a paragraph's inline HTML, so all of them close.

    Inline HTML arrives one tag at a time (``<b>``, then text, then
    ``</b>``), possibly unbalanced. A renderer opens and closes marks through
    this, ignores a close with nothing to close, and closes what is still
    open at the end of the paragraph.
    """

    def __init__(self) -> None:
        self.open: list[str] = []
        #: How deep inside ``<script>``-like elements the paragraph is, across
        #: tokens, so their text is left out with them.
        self.skipping = 0

    def track_skips(self, fragment: str) -> None:
        for closing, tag in re.findall(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)", fragment):
            if tag.lower() in _SKIP_CONTENT:
                self.skipping = max(0, self.skipping + (-1 if closing else 1))

    def push(self, mark: str) -> bool:
        self.open.append(mark)
        return True

    def pop(self, mark: str) -> list[str]:
        """The marks to close (innermost first) to close *mark*, or none if it is not open."""
        if mark not in self.open:
            return []
        index = len(self.open) - 1 - self.open[::-1].index(mark)
        closing = self.open[index:][::-1]
        del self.open[index:]
        return closing

    def drain(self) -> list[str]:
        closing = self.open[::-1]
        self.open.clear()
        return closing
