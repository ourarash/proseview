"""The sentence-length strip in a scene's Analysis tab.

One bar per sentence, read from the scene as the editor holds it. The browser
splits sentences itself, so these tests hold it to the same rules as
``lexical.sentence_spans``, which every other sentence measure uses.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page  # noqa: E402

from proseview.highlights import sentence_buckets, sentence_lengths  # noqa: E402
from proseview.scenes import extract_scene_text, split_frontmatter  # noqa: E402

from .conftest import ProseviewServer  # noqa: E402
from .test_browser_e2e import SCENE_REL, _wait_until, open_scene, open_scene_analysis  # noqa: E402

pytestmark = pytest.mark.e2e_browser


def _python_sentence_words(server: ProseviewServer, rel: str) -> list[int]:
    _fm, body = split_frontmatter((server.root / "manuscript" / rel).read_text(encoding="utf-8"))
    return sentence_lengths(extract_scene_text(body))


def _in_order(page: Page) -> None:
    page.evaluate("() => { try { localStorage.removeItem('proseview-rhythm-view'); } catch (e) {} }")


def test_the_strip_has_a_bar_per_sentence_split_as_python_splits_them(page: Page, server: ProseviewServer):
    open_scene(page, server)
    _in_order(page)
    open_scene_analysis(page)
    bars = page.locator("#sceneRhythm .rhythm-bar")
    bars.first.wait_for()
    browser_words = page.evaluate("() => sceneSentences(_pmView).map(s => s.words)")
    assert browser_words == _python_sentence_words(server, SCENE_REL)
    assert bars.count() == len(browser_words)

    # The numbers sit behind an i on the heading row, not under the graph.
    info = page.locator("#sceneRhythm .rhythm-info")
    pop = page.locator("#sceneRhythm .rhythm-info-pop")
    assert pop.is_hidden()
    info.hover()
    pop.wait_for()
    text = pop.locator(".rhythm-note").inner_text()
    assert re.match(r"Average \d+ words; most sentences \d+\u2013\d+ words\. Your typical scene: \d+, mostly \d+\u2013\d+\. "
                    r"Darker bars are over 40 words\.$", text), text
    assert "Range is average \u00b1 one standard deviation." in pop.inner_text()
    page.mouse.move(5, 5)
    info.focus()
    page.keyboard.press("Enter")
    assert info.get_attribute("aria-expanded") == "true" and pop.is_visible()
    page.keyboard.press("Escape")
    assert info.get_attribute("aria-expanded") == "false"
    title = bars.first.get_attribute("title") or ""
    assert title.endswith(" words") or title.endswith(" word")


def test_clicking_a_bar_brings_its_sentence_to_the_middle(page: Page, server: ProseviewServer):
    page.set_viewport_size({"width": 1400, "height": 700})
    open_scene(page, server)
    open_scene_analysis(page)
    bars = page.locator("#sceneRhythm .rhythm-bar")
    bars.first.wait_for()
    scroller = "document.querySelector('#sceneModal .modal-content')"
    before = page.evaluate(f"() => {scroller}.scrollTop")
    bars.last.hover()
    page.wait_for_timeout(300)
    assert page.evaluate(f"() => {scroller}.scrollTop") == before, "hovering never scrolls"
    # ...but lights its sentence for as long as the pointer stays.
    lit = page.evaluate("""() => {
        const h = CSS.highlights.get('proseview-rhythm-hover');
        return h ? [...h][0].toString() : null;
    }""")
    assert lit and lit.strip() == page.evaluate("() => sceneSentences(_pmView).at(-1).text").strip()
    page.mouse.move(5, 5)
    assert not page.evaluate("() => CSS.highlights.has('proseview-rhythm-hover')")

    bars.last.click()
    _wait_until(lambda: page.evaluate(
        """() => {
            const s = sceneSentences(_pmView).at(-1);
            const box = document.querySelector('#sceneModal .modal-content').getBoundingClientRect();
            const top = _pmView.coordsAtPos(s.from).top;
            return top > box.top && top < box.bottom;
        }"""), message="the last sentence was not brought into view")
    assert page.evaluate("() => CSS.highlights.has('proseview-rhythm-flash')")


def test_a_long_scene_never_scrolls_sideways(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-bar").first.wait_for()
    # Four hundred sentences of every length, drawn into the same pane.
    page.evaluate("""() => {
        const real = sceneSentences;
        window.sceneSentences = () => Array.from({length: 400}, (_, i) => ({from: 1, to: 2, words: 1 + (i * 7) % 60, text: 'x'}));
        refreshSceneRhythm();
        window.sceneSentences = real;
    }""")
    bars = page.locator("#sceneRhythm .rhythm-bars")
    assert page.locator("#sceneRhythm .rhythm-bar").count() == 400
    assert bars.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    assert page.locator("#sceneRhythm .rhythm-bar.is-long").count() > 0


def test_the_summary_line_compares_words_with_the_book(page: Page, server: ProseviewServer):
    """Words name the book's typical scene on hover, and an unusual count is marked."""
    open_scene(page, server)
    open_scene_analysis(page)
    words = page.locator("#sceneSummary .scene-summary-part").first
    words.wait_for()
    assert "Your typical scene:" in (words.get_attribute("title") or "")
    marked = page.evaluate("""() => {
        const m = meta[paths[curIdx]], md = medians;
        const out = (v, med) => !!(v && med) && (v > med * 1.5 || v < med * 0.5);
        return out(m.words, md.words) === document.querySelector('#sceneSummary .scene-summary-part')
            .classList.contains('is-warn');
    }""")
    assert marked


def test_spread_shows_the_scenes_mix_against_the_books(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-bar").first.wait_for()
    height = page.locator("#sceneRhythm").bounding_box()["height"]
    page.locator('#sceneRhythm .rhythm-switch-btn[data-view="spread"]').click()
    buckets = page.locator("#sceneRhythm .rhythm-bucket")
    buckets.first.wait_for()
    assert buckets.count() == 7
    assert abs(page.locator("#sceneRhythm").bounding_box()["height"] - height) < 2, "switching moves nothing"

    expected = sentence_buckets(_python_sentence_words(server, SCENE_REL))
    shown = [int((b.get_attribute("title") or "0").split(" ")[0]) for b in buckets.all()]
    assert shown == expected
    assert "sentences, 1\u20135 words" in (buckets.first.get_attribute("title") or "") \
        or "sentence, 1\u20135 words" in (buckets.first.get_attribute("title") or "")
    assert page.locator("#sceneRhythm .rhythm-bucket-typical").count() == 7, "the book's mix is drawn"

    # Each band's count sits on its bar; an empty band shows none.
    numbers = page.locator("#sceneRhythm .rhythm-bucket-count").all_inner_texts()
    assert numbers == [str(n) if n else "" for n in expected]
    assert page.locator('#sceneRhythm .rhythm-switch-btn[data-view="spread"]').inner_text() == "By length"

    # Remembered.
    page.reload(wait_until="load")
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-bucket").first.wait_for()


def test_clicking_a_band_tints_its_sentences_and_again_clears(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-bar, #sceneRhythm .rhythm-bucket").first.wait_for()
    page.evaluate("() => { localStorage.setItem('proseview-rhythm-view', 'spread'); refreshSceneRhythm(); }")
    scroller = "document.querySelector('#sceneModal .modal-content')"
    top = page.evaluate(f"() => {scroller}.scrollTop")
    expected = sentence_buckets(_python_sentence_words(server, SCENE_REL))
    band = max(range(7), key=lambda i: expected[i])
    col = page.locator(f'#sceneRhythm .rhythm-bucket[data-bucket="{band}"]')
    col.click()
    assert col.get_attribute("aria-pressed") == "true"
    assert page.evaluate("() => CSS.highlights.get('proseview-rhythm-bucket').size") == expected[band]
    assert page.evaluate(f"() => {scroller}.scrollTop") == top, "tinting never scrolls"
    page.locator(f'#sceneRhythm .rhythm-bucket[data-bucket="{band}"]').click()
    assert not page.evaluate("() => CSS.highlights.has('proseview-rhythm-bucket')")


def test_in_order_marks_the_average_paragraphs_and_dialogue(page: Page, server: ProseviewServer):
    open_scene(page, server)
    _in_order(page)
    open_scene_analysis(page)
    page.evaluate("() => refreshSceneRhythm()")
    page.locator("#sceneRhythm .rhythm-bar").first.wait_for()
    assert page.locator("#sceneRhythm .rhythm-avg").count() == 1
    sentences = page.evaluate("() => sceneSentences(_pmView).map(s => [s.paragraphStart, s.dialogue, s.text])")
    paragraphs = sum(1 for start, _d, _t in sentences if start) - 1
    assert page.locator("#sceneRhythm .rhythm-bar.is-paragraph").count() == paragraphs
    # A paragraph mark is a small tick under the baseline, clear of the bars.
    tick = page.evaluate("""() => {
        const s = getComputedStyle(document.querySelector('#sceneRhythm .rhythm-bar.is-paragraph'), '::before');
        return [s.bottom, s.height];
    }""")
    assert tick == ["-5px", "4px"]
    dialogue = [t for _s, d, t in sentences if d]
    narration = [t for _s, d, t in sentences if not d]
    # Speech that runs on past its opening quote still counts as speech.
    assert "I do not need it open today.\"" in dialogue
    assert dialogue and narration and not any(t.count('"') == 0 and "\u201c" not in t for t in dialogue)
    assert page.locator("#sceneRhythm .rhythm-bar.is-dialogue").count() == len(dialogue)


def test_the_graph_can_be_enlarged_and_points_back_at_the_text(page: Page, server: ProseviewServer):
    page.set_viewport_size({"width": 1400, "height": 900})
    open_scene(page, server)
    _in_order(page)
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-bar").first.wait_for()
    small = page.locator("#sceneRhythm .rhythm-bar").count()
    scroller = "document.querySelector('#sceneModal .modal-content')"
    top = page.evaluate(f"() => {scroller}.scrollTop")

    page.locator("#sceneRhythm .rhythm-enlarge").click()
    dialog = page.locator("#rhythmDialog")
    dialog.wait_for()
    assert page.locator("#sceneRhythmLarge .rhythm-bar").count() == small
    assert page.locator("#sceneRhythmLarge .rhythm-bars").bounding_box()["height"] >= 170
    assert dialog.bounding_box()["width"] > 900
    assert page.locator("#sceneRhythmLarge .rhythm-avg").count() == 1
    page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    assert page.evaluate(f"() => {scroller}.scrollTop") == top, "opening and closing it moves nothing"

    # A bar in the large window does what one in the panel does: the window
    # stays open beside the text, and the sentence is brought into view and lit.
    page.locator("#sceneRhythm .rhythm-enlarge").click()
    page.locator("#sceneRhythmLarge .rhythm-bar").last.click()
    assert dialog.is_visible()
    assert "Show in text" not in page.locator("#rhythmDetail").inner_text()
    _wait_until(lambda: page.evaluate(
        """() => {
            const s = sceneSentences(_pmView).at(-1);
            const box = document.querySelector('#sceneModal .modal-content').getBoundingClientRect();
            const win = document.getElementById('rhythmDialog').getBoundingClientRect();
            const top = _pmView.coordsAtPos(s.from).top;
            return top > box.top && top < Math.min(box.bottom, win.top);
        }"""), message="the bar's sentence was not brought into view above the window")
    assert page.evaluate("() => CSS.highlights.has('proseview-rhythm-flash')")
    assert "is-picked" in (page.locator("#sceneRhythmLarge .rhythm-bar").last.get_attribute("class") or "")

    # The window can be moved by its title bar.
    head = page.locator("#rhythmDialog .rhythm-dialog-head").bounding_box()
    before = dialog.bounding_box()
    page.mouse.move(head["x"] + 60, head["y"] + 10)
    page.mouse.down()
    page.mouse.move(head["x"] + 20, head["y"] - 140, steps=5)
    page.mouse.up()
    after = dialog.bounding_box()
    assert after["y"] < before["y"] - 100 and after["x"] < before["x"] - 20

    # A band lists its sentences there and tints them in the text behind;
    # a listed sentence is brought into view, still with the window open.
    page.locator('#sceneRhythmLarge .rhythm-switch-btn[data-view="spread"]').click()
    expected = sentence_buckets(_python_sentence_words(server, SCENE_REL))
    band = max(range(7), key=lambda i: expected[i])
    page.locator(f'#sceneRhythmLarge .rhythm-bucket[data-bucket="{band}"]').click()
    assert dialog.is_visible()
    assert page.locator("#rhythmDetail .rhythm-detail-item").count() == expected[band]
    assert page.evaluate("() => CSS.highlights.get('proseview-rhythm-bucket').size") == expected[band]
    page.locator("#rhythmDetail .rhythm-detail-item").first.click()
    assert dialog.is_visible()
    page.locator("#rhythmDialog .ledger-close").click()
    dialog.wait_for(state="hidden")
    assert page.locator("#sceneRhythm .rhythm-bucket").count() == 7, "the panel follows the switch"
    page.evaluate("() => { tintRhythmBucket(null); localStorage.removeItem('proseview-rhythm-view'); }")


def test_a_legend_says_what_the_marks_mean_and_keeps_its_place(page: Page, server: ProseviewServer):
    open_scene(page, server)
    _in_order(page)
    open_scene_analysis(page)
    page.evaluate("() => refreshSceneRhythm()")
    legend = page.locator("#sceneRhythm .rhythm-legend")
    legend.wait_for()
    assert " ".join(legend.inner_text().split()) == "narration \u00b7 dialogue \u00b7 average \u00b7 new paragraph"
    height = page.locator("#sceneRhythm").bounding_box()["height"]
    page.locator('#sceneRhythm .rhythm-switch-btn[data-view="spread"]').click()
    assert " ".join(page.locator("#sceneRhythm .rhythm-legend").inner_text().split()) == "this scene \u00b7 your typical scene"
    assert abs(page.locator("#sceneRhythm").bounding_box()["height"] - height) < 1, "switching moves nothing"
    page.evaluate("() => localStorage.removeItem('proseview-rhythm-view')")


def test_dialogue_wrapped_over_lines_in_the_file_is_tinted_whole(page: Page, server: ProseviewServer):
    """A paragraph wrapped in the file is one line in the editor; its tint must still find it."""
    from tests.test_sentences_and_dialogue import WRAPPED_SPEECH

    scene = server.root / "manuscript" / SCENE_REL
    scene.write_text(scene.read_text(encoding="utf-8").rstrip() + "\n\n" + "\n\n".join(WRAPPED_SPEECH) + "\n",
                     encoding="utf-8")
    # The server notices a changed file on its next look; wait until the page has it.
    import urllib.request
    _wait_until(lambda: "in case you forgot" in urllib.request.urlopen(server.base_url + "/").read().decode("utf-8"),
                message="the server never picked up the edited scene")
    open_scene(page, server)
    open_scene_analysis(page)
    page.click("#pass-row-dialogue")
    _wait_until(lambda: page.locator("#sceneProseHost .hl-dialogue").count() > 0)
    tinted = " ".join(page.locator("#sceneProseHost .hl-dialogue").all_inner_texts())
    for para in WRAPPED_SPEECH:
        assert " ".join(para.split()) in " ".join(tinted.split()), para[:40]
    page.click("#pass-row-dialogue")


def test_the_large_window_resizes_and_remembers_its_size(page: Page, server: ProseviewServer):
    page.set_viewport_size({"width": 1400, "height": 900})
    open_scene(page, server)
    page.evaluate("() => { localStorage.removeItem('proseview-rhythm-window'); localStorage.removeItem('proseview-rhythm-view'); }")
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-enlarge").click()
    dialog = page.locator("#rhythmDialog")
    dialog.wait_for()
    first = dialog.bounding_box()
    bars_before = page.locator("#sceneRhythmLarge .rhythm-bars").bounding_box()["height"]

    # Drag it up a little, then pull its corner out.
    head = page.locator("#rhythmDialog .rhythm-dialog-head").bounding_box()
    page.mouse.move(head["x"] + 80, head["y"] + 10)
    page.mouse.down()
    page.mouse.move(head["x"] + 80, head["y"] - 200, steps=5)
    page.mouse.up()
    box = dialog.bounding_box()
    page.mouse.move(box["x"] + box["width"] - 3, box["y"] + box["height"] - 3)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 103, box["y"] + box["height"] + 117, steps=6)
    page.mouse.up()
    _wait_until(lambda: page.locator("#sceneRhythmLarge .rhythm-bars").bounding_box()["height"] > bars_before + 60,
                message="the bars did not take the new height")
    resized = dialog.bounding_box()
    assert resized["height"] > box["height"] + 60 and resized["width"] < box["width"] - 60

    # Kept across a reload.
    page.reload(wait_until="load")
    page.wait_for_selector("#sceneProseHost .ProseMirror")
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-enlarge").click()
    dialog.wait_for()
    again = dialog.bounding_box()
    for key in ("x", "y", "width", "height"):
        assert abs(again[key] - resized[key]) < 3, key

    # A double-click on the title bar puts it back.
    page.locator("#rhythmDialog .rhythm-dialog-title").dblclick()
    back = dialog.bounding_box()
    assert abs(back["height"] - first["height"]) < 3 and abs(back["y"] - first["y"]) < 3
    page.keyboard.press("Escape")



def test_the_large_window_has_the_numbers_behind_its_i_too(page: Page, server: ProseviewServer):
    open_scene(page, server)
    open_scene_analysis(page)
    page.locator("#sceneRhythm .rhythm-enlarge").click()
    info = page.locator("#sceneRhythmLarge .rhythm-info")
    info.wait_for()
    info.hover()
    assert "Average " in page.locator("#sceneRhythmLarge .rhythm-info-pop").inner_text()
    page.keyboard.press("Escape")
