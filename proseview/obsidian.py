"""Obsidian's Markdown extensions, rewritten as plain Markdown for a book.

A vault's scenes carry ``[[wikilinks]]``, ``![[embeds]]``, ``> [!note]``
callouts and ``==highlights==``. None of them is CommonMark, so an export
printed them as typed. A book shows what a reader of the vault sees instead:
a link's text, the embedded picture, the callout as a quotation with its
title, the highlighted words.
"""

from __future__ import annotations

import re
from pathlib import Path

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"})

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_EMBED_RE = re.compile(r"!\[\[([^\[\]\n]+?)\]\]")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
_HIGHLIGHT_RE = re.compile(r"(?<!=)==(?=\S)(.+?)(?<=\S)==(?!=)")
_CALLOUT_RE = re.compile(r"^(\s*>\s*)\[!([A-Za-z][\w-]*)\][+-]?[ \t]*(.*)$")
_CODE_SPAN_RE = re.compile(r"(`+)(.+?)\1")


def _link_text(inner: str) -> str:
    """``target#heading|alias`` -> what Obsidian displays."""
    target, _, alias = inner.partition("|")
    if alias.strip():
        return alias.strip()
    page, _, heading = target.partition("#")
    page = page.strip()
    heading = heading.strip().lstrip("^")
    return f"{page} > {heading}" if page and heading else (page or heading)


def _find_file(root: Path | None, name: str) -> Path | None:
    """The file *name* names, as Obsidian resolves it: by path, else anywhere."""
    if root is None:
        return None
    direct = root / name
    if direct.is_file():
        return direct
    base = Path(name).name
    for path in sorted(root.rglob(base)):
        relative = path.relative_to(root)
        if path.is_file() and not any(part.startswith(".") for part in relative.parts):
            return path
    return None


def _embed(inner: str, root: Path | None) -> str:
    name = inner.partition("|")[0].partition("#")[0].strip()
    if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
        return ""  # an embedded note or PDF has no place in a printed book
    found = _find_file(root, name)
    if found is None:
        return ""
    return f"![](</{found.relative_to(root).as_posix()}>)"


def _inline(line: str, root: Path | None) -> str:
    # Leave code spans as written.
    pieces: list[str] = []
    last = 0
    for match in _CODE_SPAN_RE.finditer(line):
        pieces.append(_rewrite(line[last:match.start()], root))
        pieces.append(match.group(0))
        last = match.end()
    pieces.append(_rewrite(line[last:], root))
    return "".join(pieces)


def _rewrite(text: str, root: Path | None) -> str:
    text = _EMBED_RE.sub(lambda m: _embed(m.group(1), root), text)
    text = _WIKILINK_RE.sub(lambda m: _link_text(m.group(1)), text)
    return _HIGHLIGHT_RE.sub(r"\1", text)


def plain_obsidian(text: str, root: Path | None = None) -> str:
    """*text* with Obsidian's extensions rewritten as plain Markdown.

    *root* is the vault, where ``![[picture.png]]`` is looked for. Fenced code
    is left alone; text without any of the syntax comes back unchanged.
    """
    if "[[" not in text and "==" not in text and "[!" not in text:
        return text
    out: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        callout = _CALLOUT_RE.match(line)
        if callout:
            prefix, kind, title = callout.groups()
            title = title.strip() or kind.capitalize()
            # The title is a paragraph of its own inside the quotation.
            out.append(f"{prefix}**{_inline(title, root)}**")
            out.append(prefix.rstrip())
            continue
        out.append(_inline(line, root))
    return "\n".join(out)
