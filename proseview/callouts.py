"""Callouts: ``> [!type] Title`` boxes, GitHub's and Obsidian's syntax.

A callout is a quotation whose first line is exactly ``[!type]``, optionally
followed by ``-`` or ``+`` (Obsidian's folding, kept in the file but never
acted on: a book cannot fold) and a title. Nothing is guessed from content.
It is book text, so it prints, unlike the TODOs and notes kept in comments.

``callout_plugin`` turns such a quotation into ``callout_open`` /
``callout_title_*`` / ``callout_close`` tokens for every markdown-it based
renderer; the scene editor has the same rule in JavaScript
(``templates/assets/js/14-callouts.js``), tested against the same cases.

Each type may have a background, set under ``callouts:`` in
``.proseview.yaml`` or a book style's ``style.yaml``: one hex colour for
everywhere, or one per screen theme with ``default`` and ``print`` keys.
"""

from __future__ import annotations

import re
from typing import Any

#: ``[!type]``, its fold sign and its title, at the start of a quotation.
MARKER_RE = re.compile(r"^\[!([A-Za-z][A-Za-z0-9-]*)\]([+-]?)(?:[ \t]+(.*?))?[ \t]*$")
#: The same marker at the start of a Markdown line, after its ``>`` prefixes.
LINE_MARKER_RE = re.compile(r"^((?:[ \t]{0,3}>[ \t]?)+)\[![A-Za-z][A-Za-z0-9-]*\][+-]?[ \t]*", re.MULTILINE)
TYPE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_OPAQUE_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: The types GitHub draws; a book's own (letter, sms) are just as welcome.
GITHUB_TYPES: tuple[str, ...] = ("note", "tip", "important", "warning", "caution")

#: The screen themes a colour can be set for (``data-theme`` in the dashboard).
THEMES: tuple[str, ...] = ("light", "dark", "docsify", "hopscotch", "graphite-light", "graphite-dark")
COLOUR_KEYS: tuple[str, ...] = ("default", *THEMES, "print")

#: ``((type, ((key, "#hex"), ...)), ...)``: frozen, so configs stay hashable.
CalloutColours = tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


def parse_marker(line: str) -> tuple[str, str, str] | None:
    """``(type, fold, title)`` for a callout's first line, else None. The type is lower-cased."""
    match = MARKER_RE.match(line)
    if not match:
        return None
    kind, fold, title = match.groups()
    return kind.lower(), fold, (title or "").strip()


def strip_markers(text: str) -> str:
    """*text* with each ``[!type]`` marker gone and its title kept: the words a reader reads."""
    if "[!" not in text:
        return text
    return LINE_MARKER_RE.sub(r"\1", text)


# --------------------------------------------------------------------------
# markdown-it


def callout_plugin(md) -> None:
    """Turn each quotation that opens with ``[!type]`` into callout tokens.

    Runs after block parsing and before inline parsing, so the title is an
    ordinary inline token and gets emphasis, links and smart quotes. The tokens
    carry ``div`` / ``p`` tags, classes and ``data-callout``, so markdown-it's
    own HTML renderer writes them with no rules of its own.
    """
    md.core.ruler.after("block", "callouts", _callout_rule)


def _callout_rule(state) -> None:
    from markdown_it.token import Token

    tokens = state.tokens
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type != "blockquote_open" or i + 2 >= len(tokens):
            i += 1
            continue
        para, inline = tokens[i + 1], tokens[i + 2]
        if para.type != "paragraph_open" or inline.type != "inline":
            i += 1
            continue
        first, _, rest = inline.content.partition("\n")
        marker = parse_marker(first)
        if marker is None:
            i += 1
            continue
        kind, fold, title = marker
        close = _matching_close(tokens, i)
        token.type, token.tag = "callout_open", "div"
        token.attrs = {"class": f"callout callout-{kind}", "data-callout": kind}
        token.meta = {"type": kind, "fold": fold, "title": title}
        tokens[close].type, tokens[close].tag = "callout_close", "div"
        title_tokens: list = []
        if title:
            opener = Token("callout_title_open", "p", 1, attrs={"class": "callout-title"}, map=inline.map,
                           level=token.level + 1, block=True)
            text = Token("inline", "", 0, content=title, map=inline.map, level=token.level + 2, children=[])
            closer = Token("callout_title_close", "p", -1, level=token.level + 1, block=True)
            title_tokens = [opener, text, closer]
        if rest.strip():
            inline.content = rest
            tokens[i + 1:i + 1] = title_tokens
        else:
            # The marker was the whole paragraph: drop it.
            tokens[i + 1:i + 4] = title_tokens
        i += 1


def _matching_close(tokens: list, start: int) -> int:
    depth = 0
    for j in range(start, len(tokens)):
        if tokens[j].type == "blockquote_open":
            depth += 1
        elif tokens[j].type == "blockquote_close":
            depth -= 1
            if depth == 0:
                return j
    raise ValueError("unbalanced blockquote tokens")


# --------------------------------------------------------------------------
# Colours


def parse_colours(raw: Any, where: str) -> CalloutColours:
    """The ``callouts:`` mapping from YAML, checked. Raises ValueError naming *where*."""
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: 'callouts' must map callout types to settings")
    out: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for name, settings in raw.items():
        kind = str(name).strip().lower()
        label = f"{where}: callouts.{name}"
        if not TYPE_RE.match(kind):
            raise ValueError(f"{label}: a callout type is letters, digits and '-', starting with a letter")
        if not isinstance(settings, dict) or set(settings) - {"background"}:
            raise ValueError(f"{label}: the only setting is 'background'")
        background = settings.get("background")
        if isinstance(background, str):
            colours = {"default": background, "print": background}
        elif isinstance(background, dict):
            unknown = [str(k) for k in background if str(k) not in COLOUR_KEYS]
            if unknown:
                raise ValueError(f"{label}.background: unknown key {unknown[0]!r}; use {', '.join(COLOUR_KEYS)}")
            colours = {str(k): v for k, v in background.items()}
        else:
            raise ValueError(f"{label}.background must be a hex colour or a mapping of themes to hex colours")
        for key, value in colours.items():
            at = f"{label}.background" + ("" if isinstance(background, str) else f".{key}")
            if not isinstance(value, str) or not _HEX_RE.match(value.strip()):
                raise ValueError(f"{at}: {value!r} is not a hex colour like \"#f7f1e6\"")
            if key == "print" and not _OPAQUE_HEX_RE.match(value.strip()):
                raise ValueError(f"{at}: {value!r} must be opaque (#rgb or #rrggbb) to print; Word has no see-through shading")
        out.append((kind, tuple((key, _long_hex(colours[key])) for key in COLOUR_KEYS if key in colours)))
    return tuple(out)


def _long_hex(value: str) -> str:
    value = value.strip().lower()
    if len(value) == 4:
        value = "#" + "".join(c * 2 for c in value[1:])
    return value


def merge_colours(base: CalloutColours, override: CalloutColours) -> CalloutColours:
    """*base* (a book style's) with *override* (the project's) on top, key by key."""
    merged: dict[str, dict[str, str]] = {kind: dict(keys) for kind, keys in base}
    for kind, keys in override:
        merged.setdefault(kind, {}).update(dict(keys))
    return tuple((kind, tuple((k, keys[k]) for k in COLOUR_KEYS if k in keys)) for kind, keys in merged.items())


def print_fills(*layers: CalloutColours) -> dict[str, str]:
    """Each type's print background, ``{"letter": "#f7f1e6"}``, later layers winning."""
    fills: dict[str, str] = {}
    for layer in layers:
        for kind, keys in layer:
            value = dict(keys).get("print")
            if value:
                fills[kind] = value
    return fills


def screen_css(colours: CalloutColours) -> str:
    """The rules that give each callout type its background on screen, per theme."""
    rules = []
    for kind, keys in colours:
        target = f'.pv-callout[data-callout="{kind}"]'
        for key, value in keys:
            if key == "print":
                continue
            selector = target if key == "default" else f':root[data-theme="{key}"] {target}'
            rules.append(f"{selector} {{ --callout-bg: {value}; }}")
    return "\n".join(rules)
