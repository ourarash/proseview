"""Properties the hunk picker has to hold, checked over random file pairs.

The old undo searched the live file for text and refused when it could not
place it. This one is arithmetic over two texts we already hold, so the claim
worth testing is that the arithmetic is exact: the extremes round-trip byte for
byte, and every block moves on its own without disturbing its neighbours.
"""

from __future__ import annotations

import random

import pytest

from proseview.hunks import Block, changed_blocks, compose, split_lines


def _random_text(rng: random.Random, *, lines: int, alphabet: str = "abcdefg") -> str:
    out = []
    for _ in range(lines):
        out.append("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 4))) + "\n")
    if out and rng.random() < 0.2:
        out[-1] = out[-1].rstrip("\n")  # A file with no trailing newline.
    return "".join(out)


def _mutate(rng: random.Random, text: str) -> str:
    """An edit of *text* built from the operations an agent actually performs."""
    lines = split_lines(text)
    for _ in range(rng.randint(1, 4)):
        if not lines or rng.random() < 0.25:
            lines.insert(rng.randint(0, len(lines)), "inserted " + str(rng.randint(0, 99)) + "\n")
        elif rng.random() < 0.4:
            del lines[rng.randrange(len(lines))]
        else:
            lines[rng.randrange(len(lines))] = "rewritten " + str(rng.randint(0, 99)) + "\n"
    return "".join(lines)


def _pairs(count: int, *, seed: int = 20260829, lines: int = 12):
    rng = random.Random(seed)
    for _ in range(count):
        before = _random_text(rng, lines=rng.randint(0, lines))
        yield rng, before, _mutate(rng, before)


def test_keeping_everything_reproduces_the_new_file_byte_for_byte():
    for _rng, before, after in _pairs(400):
        ids = [block.index for block in changed_blocks(before, after)]
        assert compose(before, after, ids) == after


def test_keeping_nothing_reproduces_the_old_file_byte_for_byte():
    for _rng, before, after in _pairs(400):
        assert compose(before, after, []) == before


def _spliced(before: str, after: str, keep: set[int]) -> str:
    """The same file, assembled a different way, as an independent check.

    Walks the block offsets and the untouched runs between them, rather than
    the opcode stream ``compose`` follows. Agreement between the two is what
    makes per-block independence a fact about the code and not a sample of it.
    """
    lines = split_lines(before)
    out: list[str] = []
    cursor = 0
    for block in changed_blocks(before, after):
        out.extend(lines[cursor:block.before_start])
        out.extend(block.after if block.index in keep else block.before)
        cursor = block.before_start + len(block.before)
    out.extend(lines[cursor:])
    return "".join(out)


def test_every_selection_is_the_splice_it_claims_to_be():
    """Each block contributes one version of itself and nothing else.

    Stated as agreement with a second assembly rather than by re-diffing the
    result: where a line repeats, a diff can place an insertion anywhere in the
    run, so two correct descriptions of the same file disagree on wording. The
    file is what has to be right.
    """
    for rng, before, after in _pairs(400):
        ids = [block.index for block in changed_blocks(before, after)]
        for _ in range(4):
            chosen = {index for index in ids if rng.random() < 0.5}
            assert compose(before, after, chosen) == _spliced(before, after, chosen)


def test_toggling_one_block_leaves_the_rest_of_the_file_alone():
    """Ticking one edit must not disturb the prose around it.

    Measured as a single contiguous stretch of difference whose two sides are
    the right lengths -- not as an exact quote, for the reason above.
    """
    for rng, before, after in _pairs(400):
        blocks = {block.index: block for block in changed_blocks(before, after)}
        chosen = {index for index in blocks if rng.random() < 0.5}
        rest = sorted(set(blocks) - chosen)
        if not rest:
            continue
        extra = rng.choice(rest)
        without = split_lines(compose(before, after, chosen))
        with_it = split_lines(compose(before, after, chosen | {extra}))

        head = 0
        while head < min(len(without), len(with_it)) and without[head] == with_it[head]:
            head += 1
        tail = 0
        while (tail < min(len(without), len(with_it)) - head
               and without[-1 - tail] == with_it[-1 - tail]):
            tail += 1
        block = blocks[extra]
        assert len(without) - head - tail <= len(block.before)
        assert len(with_it) - head - tail <= len(block.after)
        assert len(with_it) - len(without) == len(block.after) - len(block.before)


def test_selection_order_and_repeats_do_not_matter():
    for rng, before, after in _pairs(200):
        ids = [block.index for block in changed_blocks(before, after)]
        if not ids:
            continue
        chosen = [index for index in ids if rng.random() < 0.5]
        shuffled = chosen * 2
        rng.shuffle(shuffled)
        assert compose(before, after, shuffled) == compose(before, after, chosen)


def test_a_stale_selection_narrows_the_result_instead_of_failing():
    """Ids the pair no longer has are ignored, not raised.

    A selection can outlive the diff it was made against. Dropping the unknown
    ids leaves the writer with less of the change than they ticked, which is
    the safe direction; refusing the write outright is not.
    """
    before, after = "a\nb\n", "a\nB\n"
    assert compose(before, after, [1, 99]) == after
    assert compose(before, after, [99]) == before


@pytest.mark.parametrize("before, after", [
    ("", "new\n"),
    ("gone\n", ""),
    ("no trailing newline", "no trailing newline!"),
    ("keeps\r\nwindows\r\n", "keeps\r\nWINDOWS\r\n"),
    ("a\n\n\n\nb\n", "a\n\n\n\nB\n"),
])
def test_the_shapes_that_broke_the_old_reverter(before: str, after: str):
    ids = [block.index for block in changed_blocks(before, after)]
    assert compose(before, after, ids) == after
    assert compose(before, after, []) == before


def test_blocks_report_what_kind_of_edit_they_are():
    blocks = changed_blocks("keep\nold\ngone\n", "keep\nnew\ngone\nadded\n")
    assert [block.kind for block in blocks] == ["changed", "added"]
