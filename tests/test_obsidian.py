"""Obsidian's Markdown extensions in an export (:mod:`proseview.obsidian`)."""

from __future__ import annotations

from pathlib import Path

from proseview.obsidian import plain_obsidian


def test_wikilinks_become_the_text_a_reader_sees():
    assert plain_obsidian("Léa met [[ Jack Mercer ]] and [[Jack Mercer|Jack]].") == "Léa met Jack Mercer and Jack."
    assert plain_obsidian("See [[Harbor#The pier]].") == "See Harbor > The pier."


def test_highlights_keep_their_words():
    assert plain_obsidian("It was ==important==, not == spaced ==.") == "It was important, not == spaced ==."


def test_a_callout_is_left_for_the_callout_renderer():
    text = "> [!note] Continuity with [[Jack Mercer]]\n> Jack limps.\n"
    assert plain_obsidian(text) == "> [!note] Continuity with Jack Mercer\n> Jack limps.\n"
    assert plain_obsidian("> [!warning]-\n> Careful.") == "> [!warning]-\n> Careful."


def test_an_embedded_picture_is_found_in_the_vault_and_anything_else_dropped(tmp_path: Path):
    (tmp_path / "Attachments").mkdir()
    (tmp_path / "Attachments" / "harbor map.png").write_bytes(b"png")
    text = "![[harbor map.png]]\n\n![[missing.png]]\n\n![[Other note]]\n"
    assert plain_obsidian(text, tmp_path) == "![](</Attachments/harbor map.png>)\n\n\n\n\n"


def test_code_and_plain_markdown_are_left_alone():
    assert plain_obsidian("Use `[[x]]` here.\n```\n[[y]] ==z==\n```\n") == "Use `[[x]]` here.\n```\n[[y]] ==z==\n```\n"
    assert plain_obsidian("Nothing to see.") == "Nothing to see."
