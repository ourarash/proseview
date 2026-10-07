"""Choose which parts of a change to keep, given both versions of the file.

The dock reviews an agent's work by comparing two texts it actually holds: the
file as it stood before the agent touched it, and the file as it stands now.
Every changed region becomes a block the writer can keep or drop, and the
result is assembled from the two versions directly.

This is deliberately not :mod:`proseview.patches`. Reverting a recorded diff
means searching the current file for text and hoping it appears exactly once;
when the line has moved on there is no answer and the undo has to refuse. Here
nothing is searched for. The blocks partition both files end to end, so any
choice of blocks names exactly one output, and assembling it cannot fail.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Collection, Iterator


def split_lines(text: str) -> list[str]:
    """Split *text* keeping line endings, so joining restores it byte for byte."""
    return text.splitlines(keepends=True)


@dataclass(frozen=True)
class Block:
    """One changed region, as it reads in each version."""

    index: int
    """1-based position among the changed regions of this pair."""
    before: tuple[str, ...]
    after: tuple[str, ...]
    before_start: int
    after_start: int

    @property
    def kind(self) -> str:
        if not self.before:
            return "added"
        if not self.after:
            return "removed"
        return "changed"


def _opcodes(before: str, after: str):
    a, b = split_lines(before), split_lines(after)
    # autojunk discards lines it judges too popular, which on a manuscript full
    # of blank lines silently drops real matches and inflates the diff.
    return a, b, difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def changed_blocks(before: str, after: str) -> list[Block]:
    """Every region where *before* and *after* disagree, in order.

    Equal runs are not blocks: there is nothing to decide about them. Two
    changed regions are always separated by a non-empty equal run, because
    adjacent differences are reported as one opcode.
    """
    a, b, opcodes = _opcodes(before, after)
    blocks: list[Block] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        blocks.append(Block(
            index=len(blocks) + 1,
            before=tuple(a[i1:i2]),
            after=tuple(b[j1:j2]),
            before_start=i1,
            after_start=j1,
        ))
    return blocks


def compose(before: str, after: str, keep: Collection[int]) -> str:
    """Assemble the file that keeps exactly the blocks named in *keep*.

    Unselected regions read as they did in *before*, selected ones as they do
    in *after*, and everything both versions agree on is passed through. Ids
    outside the range are ignored rather than raising: a stale selection should
    narrow the result, never fail the write.
    """
    a, b, opcodes = _opcodes(before, after)
    wanted = {int(value) for value in keep}
    out: list[str] = []
    seen = 0
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            out.extend(a[i1:i2])
            continue
        seen += 1
        out.extend(b[j1:j2] if seen in wanted else a[i1:i2])
    return "".join(out)


def all_block_ids(before: str, after: str) -> list[int]:
    return [block.index for block in changed_blocks(before, after)]
