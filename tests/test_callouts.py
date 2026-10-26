"""Callouts (:mod:`proseview.callouts`): parsing, colours, and what they print as."""

from __future__ import annotations

import pytest
from markdown_it import MarkdownIt

from proseview.callouts import (
    callout_plugin,
    merge_colours,
    parse_colours,
    parse_marker,
    print_fills,
    screen_css,
    strip_markers,
)


def html(text: str) -> str:
    md = MarkdownIt("commonmark", {"typographer": True}).enable(["smartquotes"])
    callout_plugin(md)
    return md.render(text)


# -- the marker ------------------------------------------------------------------


@pytest.mark.parametrize(("line", "expected"), [
    ("[!NOTE]", ("note", "", "")),
    ("[!letter] A letter, undated", ("letter", "", "A letter, undated")),
    ("[!sms]- Jonah, 11:42 pm", ("sms", "-", "Jonah, 11:42 pm")),
    ("[!Warning]+", ("warning", "+", "")),
    ("[!my-type]   Spaced  ", ("my-type", "", "Spaced")),
])
def test_a_marker_gives_its_type_fold_and_title(line, expected):
    assert parse_marker(line) == expected


@pytest.mark.parametrize("line", [
    "[!] empty", "[!1st] digit first", "[note] no bang", " [!note] indented", "[!note]title glued",
    "text [!note]", "[!no te]",
])
def test_anything_else_is_not_a_marker(line):
    assert parse_marker(line) is None


# -- markdown-it ---------------------------------------------------------------


def test_a_callout_is_a_div_with_its_type_and_title():
    out = html("> [!letter] A *letter*, undated\n> Mara, if you are reading this.\n>\n> — T.\n")
    assert out == (
        '<div class="callout callout-letter" data-callout="letter">\n'
        '<p class="callout-title">A <em>letter</em>, undated</p>\n'
        "<p>Mara, if you are reading this.</p>\n"
        "<p>— T.</p>\n"
        "</div>\n"
    )


def test_an_untitled_callout_shows_no_word_for_its_type():
    out = html("> [!NOTE]\n> Untitled box.\n")
    assert "callout-title" not in out
    assert "NOTE" not in out and "Note" not in out.replace('callout-note', '').replace('"note"', "")
    assert "<p>Untitled box.</p>" in out


def test_a_marker_alone_in_its_paragraph_leaves_no_empty_paragraph():
    out = html("> [!sms]- Jonah\n>\n> are you up\n")
    assert "<p></p>" not in out
    assert out.count("<p>") == 1


def test_a_plain_quotation_stays_a_quotation():
    assert html("> Every harbour keeps one ghost.\n") == "<blockquote>\n<p>Every harbour keeps one ghost.</p>\n</blockquote>\n"
    assert "blockquote" in html("> Not [!note] at the start.\n")
    assert "blockquote" in html("> - [!note] in a list\n")


def test_callouts_nest_and_a_quotation_inside_one_stays_a_quotation():
    out = html("> [!sidebar] Outer\n> Text.\n>\n> > [!quote]\n> > Inner.\n>\n> > Plain.\n")
    assert out.count('class="callout ') == 2
    assert "<blockquote>\n<p>Plain.</p>\n</blockquote>" in out
    assert out.rstrip().endswith("</div>")


def test_a_marker_in_code_is_left_as_code():
    assert "callout" not in html("```\n> [!note] Title\n```\n")


def test_strip_markers_keeps_the_title_and_the_quote_prefix():
    text = "> [!letter] A letter\n> Body.\n\n> > [!NOTE]-\n> > Inner\n\nPlain [!note] text.\n"
    assert strip_markers(text) == "> A letter\n> Body.\n\n> > \n> > Inner\n\nPlain [!note] text.\n"


# -- colours -----------------------------------------------------------------------


def test_one_colour_is_every_theme_and_print():
    colours = parse_colours({"Letter": {"background": "#F7F1E6"}}, "x")
    assert colours == (("letter", (("default", "#f7f1e6"), ("print", "#f7f1e6"))),)


def test_a_mapping_sets_each_theme_and_print_only_when_asked():
    colours = parse_colours({"sms": {"background": {"dark": "#16233a", "default": "#abc"}}}, "x")
    assert colours == (("sms", (("default", "#aabbcc"), ("dark", "#16233a"))),)
    assert print_fills(colours) == {}


@pytest.mark.parametrize(("raw", "message"), [
    ([], "must map"),
    ({"1x": {"background": "#fff"}}, "callout type"),
    ({"note": {"colour": "#fff"}}, "only setting"),
    ({"note": {"background": {"sepia": "#fff"}}}, "unknown key 'sepia'"),
    ({"note": {"background": "red"}}, "not a hex colour"),
    ({"note": {"background": "#fff; }"}}, "not a hex colour"),
    ({"note": {"background": {"print": "#ffffff80"}}}, "must be opaque"),
    ({"note": {"background": 3}}, "hex colour or a mapping"),
])
def test_bad_colour_settings_are_errors_that_say_what_to_write(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_colours(raw, ".proseview.yaml")


def test_the_project_wins_over_the_style_key_by_key():
    style = parse_colours({"note": {"background": {"light": "#111111", "print": "#222222"}}}, "s")
    project = parse_colours({"note": {"background": {"print": "#333333"}}, "sms": {"background": "#444444"}}, "p")
    merged = merge_colours(style, project)
    assert dict(merged)["note"] == (("light", "#111111"), ("print", "#333333"))
    assert print_fills(merged) == {"note": "#333333", "sms": "#444444"}


def test_screen_css_sets_a_variable_per_theme_and_leaves_print_out():
    css = screen_css(parse_colours({"sms": {"background": {"default": "#eef3fb", "graphite-dark": "#232c33",
                                                            "print": "#ffffff"}}}, "x"))
    assert css == (
        '.pv-callout[data-callout="sms"] { --callout-bg: #eef3fb; }\n'
        ':root[data-theme="graphite-dark"] .pv-callout[data-callout="sms"] { --callout-bg: #232c33; }'
    )
