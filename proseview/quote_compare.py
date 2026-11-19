"""Read-only passage comparisons against the current document."""
from __future__ import annotations

import difflib
import re

from markdown_it import MarkdownIt

from .scenes import split_frontmatter


def _blocks(markdown: str, line_offset: int = 0) -> list[dict]:
    _, body = split_frontmatter(markdown)
    frontmatter_lines = markdown[:len(markdown) - len(body)].count("\n")
    rows = []
    for token in MarkdownIt("commonmark", {"html": True}).parse(body):
        if token.type != "inline" or not token.map:
            continue
        text = "".join("\n" if child.type in {"softbreak", "hardbreak"} else child.content
                       if child.type in {"text", "code_inline"} else "" for child in token.children or []).strip()
        if text:
            rows.append({"text": text, "line": token.map[0] + frontmatter_lines + line_offset + 1,
                         "end_line": token.map[1] + frontmatter_lines + line_offset})
    return rows


def _normal(text: str) -> tuple[str, list[int]]:
    chars, offsets = [], []
    for match in re.finditer(r"\s+|\S", text):
        chars.append(" " if match.group().isspace() else match.group())
        offsets.append(match.start())
    return "".join(chars), offsets


def _locate(text: str, needle: str, rows: list[dict], line: int | None) -> tuple[int, int] | None:
    norm, offsets = _normal(text)
    query = _normal(needle.strip())[0]
    if not query:
        return None
    matches = []
    start = norm.find(query)
    while start >= 0:
        end = start + len(query)
        matches.append((offsets[start], offsets[end] if end < len(offsets) else len(text)))
        start = norm.find(query, start + 1)
    if len(matches) == 1:
        return matches[0]
    if line and matches:
        cited = [span for span in matches if any(row["start"] <= span[0] < row["end"]
                   and row["line"] <= line <= row["end_line"] for row in rows)]
        if len(cited) == 1:
            return cited[0]
    if matches:
        raise ValueError("This passage appears more than once. Open its source to choose the intended passage.")
    return None


def _document(markdown: str, line_offset: int = 0) -> tuple[str, list[dict]]:
    rows, parts, pos = _blocks(markdown, line_offset), [], 0
    for row in rows:
        row["start"] = pos
        row["end"] = pos + len(row["text"])
        parts.append(row["text"])
        pos = row["end"] + 2
    return "\n\n".join(parts), rows


def _map_live_span(saved: str, live: str, span: tuple[int, int]) -> tuple[int, int]:
    """Map the saved passage through unsaved edits, retaining surrounding text."""
    old_lines, new_lines = saved.splitlines(keepends=True), live.splitlines(keepends=True)
    old_offsets, new_offsets = [0], [0]
    for text in old_lines:
        old_offsets.append(old_offsets[-1] + len(text))
    for text in new_lines:
        new_offsets.append(new_offsets[-1] + len(text))
    opcodes = []
    for tag, a, b, c, d in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        x, y, u, v = old_offsets[a], old_offsets[b], new_offsets[c], new_offsets[d]
        if tag == "replace":
            opcodes.extend((t, x + i, x + j, u + k, u + l) for t, i, j, k, l in
                           difflib.SequenceMatcher(None, saved[x:y], live[u:v], autojunk=False).get_opcodes())
        else:
            opcodes.append((tag, x, y, u, v))

    def boundary(pos: int, end: bool) -> int:
        for tag, a, b, c, d in opcodes:
            if a <= pos <= b:
                if tag == "equal":
                    return c + pos - a
                if pos == a:
                    return c
                if pos == b:
                    return d
                return d if end else c
        return len(live)
    return boundary(span[0], False), boundary(span[1], True)


def compare_passage(saved: str, quote: str, *, original: str = "", line: int | None = None,
                    end_line: int | None = None, live: str | None = None,
                    live_line_offset: int = 0, kind: str = "replace", prefer_line: bool = False) -> dict:
    """Resolve a quote or its Before passage, never a guessed nearby paragraph."""
    current, rows = _document(live if live is not None else saved, live_line_offset if live is not None else 0)
    span = None if prefer_line else _locate(current, original or quote, rows, line)
    if span is None and original:
        span = _locate(current, quote, rows, line)
    if span is None and live is not None and not prefer_line:
        baseline, saved_rows = _document(saved)
        previous = _locate(baseline, original or quote, saved_rows, line)
        if previous:
            span = _map_live_span(baseline, current, previous)
    if span is None:
        selected = [row for row in rows if line and row["line"] <= (end_line or line) and row["end_line"] >= line]
        if not selected:
            raise ValueError("Could not locate this passage in the current document. Open the source to check its citation.")
        candidate = "\n\n".join(row["text"] for row in selected)
        if original and difflib.SequenceMatcher(None, _normal(original)[0], _normal(candidate)[0], autojunk=False).ratio() < .55:
            raise ValueError("The cited passage has changed and its original text could not be located. Open the source to check it.")
        span = selected[0]["start"], selected[-1]["end"]
    start, end = span
    if kind == "insert-after" and current[end:].startswith("\n\n" + quote.strip()):
        end += 2 + len(quote.strip())
        kind = "replace"
        quote = current[start:end]
    elif kind == "insert-before" and current[:start].endswith(quote.strip() + "\n\n"):
        start -= len(quote.strip()) + 2
        kind = "replace"
        quote = current[start:end]
    source = current[start:end].strip()
    if not source:
        raise ValueError("The original passage is no longer present in the current document.")
    source_rows = [row for row in rows if row["start"] < end and row["end"] > start]
    first, last = source_rows[0]["line"], source_rows[-1]["end_line"]
    replacement = quote.strip()
    if kind == "insert-after":
        replacement = source + "\n\n" + replacement
    elif kind == "insert-before":
        replacement += "\n\n" + source
    patch = "\n".join(difflib.unified_diff(source.splitlines(), replacement.splitlines(),
                                        fromfile="Current scene", tofile="Suggested text", lineterm=""))
    # The modal keeps the source file's line numbers, rather than restarting at 1.
    patch = re.sub(r"^@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@", lambda m:
                   f"@@ -{int(m[1]) + first - 1}{m[2] or ''} +{int(m[3]) + first - 1}{m[4] or ''} @@", patch, flags=re.M)
    return {"before": source, "after": replacement, "line": first, "end_line": last,
            "matches": [_normal(part.strip())[0] for part in re.split(r"\n\s*\n", source)]
                       == [_normal(part.strip())[0] for part in re.split(r"\n\s*\n", replacement)], "patch": patch}
