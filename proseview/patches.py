"""Read a unified diff into hunks, for showing one.

Prosview renders diffs it did not produce -- an agent's reported file change,
a save conflict -- and needs a tolerant reading of the shapes those arrive in.
That is all this does now.

Undoing an agent's work does not go through here. Reversing a recorded patch
means searching the live file for text and hoping it appears exactly once,
which has no answer when the line has moved on. :mod:`proseview.hunks` keeps
the file as it stood before the turn instead and assembles the writer's choice
from the two versions, which cannot fail to place anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Hunk:
    """One ``@@`` section of a unified diff."""

    index: int
    header: str
    old_start: int
    new_start: int
    lines: tuple[tuple[str, str], ...]
    """``(op, text)`` pairs, where ``op`` is one of ``' '``, ``'-'``, ``'+'``."""

    @property
    def old_lines(self) -> list[str]:
        """The lines this hunk replaced, as they were before the change."""
        return [text for op, text in self.lines if op in " -"]

    @property
    def new_lines(self) -> list[str]:
        """The lines this hunk produced, as they should read after the change."""
        return [text for op, text in self.lines if op in " +"]


@dataclass(frozen=True)
class FilePatch:
    """The hunks of a unified diff that belong to a single file."""

    old_path: str
    new_path: str
    hunks: tuple[Hunk, ...]


def parse_unified_diff(text: str) -> list[FilePatch]:
    """Read *text* as a unified diff.

    Tolerates the shapes agents actually send: with or without ``---``/``+++``
    headers, with or without ``@@`` line counts, and with ``\\ No newline at end
    of file`` markers. Hunks are numbered across the whole patch so a hunk keeps
    its identity no matter which file section it came from.
    """
    files: list[FilePatch] = []
    old_path = ""
    new_path = ""
    hunks: list[Hunk] = []
    current: dict | None = None
    counter = 0
    saw_header = False

    def close_hunk() -> None:
        nonlocal current
        if current is not None:
            hunks.append(Hunk(
                index=current["index"],
                header=current["header"],
                old_start=current["old_start"],
                new_start=current["new_start"],
                lines=tuple(current["lines"]),
            ))
            current = None

    def close_file() -> None:
        nonlocal hunks, old_path, new_path, saw_header
        close_hunk()
        if hunks:
            files.append(FilePatch(old_path=old_path, new_path=new_path, hunks=tuple(hunks)))
        hunks = []
        old_path = ""
        new_path = ""
        saw_header = False

    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        # The patch's own trailing newline, not an empty context line.
        raw_lines.pop()
    for line in raw_lines:
        if line.startswith("--- "):
            # A second file section starts here; bank the one before it.
            if saw_header or hunks:
                close_file()
            old_path = _strip_path_prefix(line[4:])
            saw_header = True
            continue
        if line.startswith("+++ "):
            new_path = _strip_path_prefix(line[4:])
            saw_header = True
            continue
        match = _HUNK_HEADER.match(line)
        if match:
            close_hunk()
            counter += 1
            current = {
                "index": counter,
                "header": line.strip(),
                "old_start": int(match.group(1)),
                "new_start": int(match.group(3)),
                "lines": [],
            }
            continue
        if current is None:
            continue
        if line.startswith("\\"):
            # "\ No newline at end of file" annotates the line above it. Text is
            # rejoined with "\n" on the way out, so there is nothing to record.
            continue
        if line[:1] in ("-", "+", " "):
            current["lines"].append((line[0], line[1:]))
        elif line == "":
            # Some producers emit a bare empty line for an empty context line.
            current["lines"].append((" ", ""))
        else:
            # Anything else ends the hunk: "diff --git", an index line, trailer.
            close_hunk()

    close_file()
    return files


def _strip_path_prefix(value: str) -> str:
    """Turn a ``---``/``+++`` operand into a plain path."""
    path = value.strip().split("\t", 1)[0].strip()
    if path in ("/dev/null", ""):
        return ""
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


def parse_hunks(text: str) -> list[Hunk]:
    """Every hunk in *text*, flattened across file sections."""
    return [hunk for file_patch in parse_unified_diff(text) for hunk in file_patch.hunks]
