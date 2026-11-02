"""Browser tests for a highlight's suggestion card.

A click on a mark while reading opens a card under its line. Suggest asks the
agent once, outside the chat, and shows the rewrites in the card; Use puts
one in the scene and saves it, with an Undo; Discuss in chat hands the
passage over with an unsent starter. None of it moves the page.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page  # noqa: E402

from .conftest import ANNOTATED_SCENE_REL, SCENE_REL, ProseviewServer  # noqa: E402
from .test_browser_e2e import _scene_with_hits, _wait_until, open_scene, open_scene_analysis  # noqa: E402

pytestmark = pytest.mark.e2e_browser

PASS = "filter_verbs"


def _scroll_top(page: Page) -> float:
    return page.evaluate("() => document.querySelector('#sceneModal .modal-content').scrollTop")


def _open_card(page: Page, server: ProseviewServer) -> tuple[str, str]:
    scene = _scene_with_hits(server, PASS)
    open_scene(page, server, scene)
    open_scene_analysis(page)
    page.click(f"#pass-row-{PASS}")
    mark = page.locator("#sceneProseHost .hl-filter").first
    mark.wait_for(state="visible")
    # Bring a mark well into view before measuring, so nothing the card does
    # has a reason to scroll.
    mark.evaluate("el => el.scrollIntoView({block: 'center'})")
    word = mark.inner_text()
    mark.click()
    page.wait_for_selector("#hlSuggestCard:not([hidden])")
    return scene, word


def test_clicking_a_mark_opens_its_card_and_esc_closes_it(page: Page, server: ProseviewServer):
    _scene, _word = _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    assert card.locator(".hl-card-title strong").inner_text() == "Filter Verbs"
    assert "perceiving and thinking" in card.locator(".hl-card-why").inner_text()
    assert card.get_by_role("button", name="Suggest with Codex").is_visible()
    assert card.get_by_role("button", name="Discuss in chat").is_visible()

    # Under the mark's line, not over it.
    mark_box = page.locator("#sceneProseHost .hl-filter").first.bounding_box()
    assert card.bounding_box()["y"] >= mark_box["y"] + mark_box["height"] - 1

    page.keyboard.press("Escape")
    card.wait_for(state="hidden")


def test_suggest_use_and_undo_without_moving_the_page(page: Page, server: ProseviewServer):
    scene, word = _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    top = _scroll_top(page)

    card.get_by_role("button", name="Suggest with Codex").click()
    card.locator(".hl-card-option").first.wait_for()
    assert card.locator(".hl-card-option").count() == 3
    assert card.locator(".hl-card-option-why").first.inner_text().strip()
    # A rewrite asked for here is not a chat message.
    assert page.locator("#discussSelectionChip").is_hidden()
    assert _scroll_top(page) == top

    # A one-word mark is rewritten with its sentence, not on its own.
    received = (server.home / "fake-codex-received.jsonl").read_text(encoding="utf-8").splitlines()
    prompt = json.loads(received[-1])["params"]["input"][0]["text"]
    passage = prompt.split("MARKED PASSAGE\n<<<\n", 1)[1].split("\n>>>", 1)[0]
    assert word in passage and len(passage.split()) > 3 and passage.rstrip().endswith((".", "!", "?", "\u201d", '"'))
    assert f"The words the mark is on: \u201c{word}\u201d" in prompt

    choice = card.locator(".hl-card-option-text").first.inner_text()
    card.locator(".hl-card-use").first.click()
    _wait_until(lambda: "Applied ·" in card.locator(".hl-card-applied").inner_text(),
                message="the card did not say the rewrite was applied and saved")
    assert choice in page.locator("#sceneProseHost").inner_text()
    on_disk = (server.root / "manuscript" / scene).read_text(encoding="utf-8")
    assert choice in on_disk, "Use saves the scene"
    assert _scroll_top(page) == top

    card.get_by_role("button", name="Undo").click()
    _wait_until(lambda: choice not in (server.root / "manuscript" / scene).read_text(encoding="utf-8"),
                message="Undo did not restore and save the original")
    assert choice not in page.locator("#sceneProseHost").inner_text()
    assert card.locator(".hl-card-use").count() == 3, "after Undo the options can be used again"
    assert _scroll_top(page) == top


def test_the_card_shows_the_agent_working_until_the_options_arrive(page: Page, server: ProseviewServer):
    _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    top = _scroll_top(page)
    with server.hold_codex_request("turn/start") as reached:
        card.get_by_role("button", name="Suggest with Codex").click()
        _wait_until(reached.exists, message="the suggestion never reached the agent")
        card.locator(".hl-card-spinner").wait_for()
        assert "Asking Codex" in card.locator(".hl-card-wait").inner_text()
        assert card.get_by_role("button", name="Cancel").is_visible()
        _wait_until(lambda: card.locator(".hl-card-elapsed").inner_text() == "0:01",
                    message="the elapsed time did not count up")
    card.locator(".hl-card-option").first.wait_for()
    assert card.locator(".hl-card-spinner").count() == 0
    assert _scroll_top(page) == top


def test_discuss_in_chat_hands_over_the_passage_unsent(page: Page, server: ProseviewServer):
    _scene, word = _open_card(page, server)
    page.locator("#hlSuggestCard").get_by_role("button", name="Discuss in chat").click()
    page.wait_for_selector("#discussPanel:not([hidden])")
    _wait_until(lambda: "Filter Verbs" in page.locator("#discussInput").input_value(),
                message="the starter was not put in the box")
    assert page.locator("#discussInput").input_value().startswith("Proseview marked this with Filter Verbs")
    assert "Is it worth changing" in page.locator("#discussInput").input_value()
    assert page.locator("#hlSuggestCard").is_hidden()
    chip = page.locator("#discussSelectionChip")
    chip.wait_for(state="visible")
    assert word.lower() in chip.inner_text().lower()


def _received_turns(server: ProseviewServer) -> int:
    record = server.home / "fake-codex-received.jsonl"
    return len(record.read_text(encoding="utf-8").splitlines()) if record.exists() else 0


def _reopen(page: Page) -> None:
    page.keyboard.press("Escape")
    page.locator("#hlSuggestCard").wait_for(state="hidden")
    page.locator("#sceneProseHost .hl-filter").first.click()
    page.wait_for_selector("#hlSuggestCard:not([hidden])")


def test_suggestions_are_still_there_when_the_mark_is_clicked_again(page: Page, server: ProseviewServer):
    _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    top = _scroll_top(page)
    card.get_by_role("button", name="Suggest with Codex").click()
    card.locator(".hl-card-option").first.wait_for()
    assert _scroll_top(page) == top
    options = card.locator(".hl-card-option-text").all_inner_texts()
    asked = _received_turns(server)

    _reopen(page)
    assert card.locator(".hl-card-option-text").all_inner_texts() == options
    assert re.fullmatch(r"Suggested by Codex in 0:\d\d \u00b7 just now", card.locator(".hl-card-by").inner_text())
    assert "Now:" not in card.inner_text()
    assert _received_turns(server) == asked, "reopening shows what was asked, it does not ask again"

    # And after a reload in the same tab.
    page.reload(wait_until="load")
    page.wait_for_selector("#sceneProseHost .hl-filter")
    page.locator("#sceneProseHost .hl-filter").first.evaluate("el => el.scrollIntoView({block: 'center'})")
    page.locator("#sceneProseHost .hl-filter").first.click()
    card.locator(".hl-card-option").first.wait_for()
    assert card.locator(".hl-card-option-text").all_inner_texts() == options
    assert _received_turns(server) == asked


def test_try_again_asks_afresh(page: Page, server: ProseviewServer):
    _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    top = _scroll_top(page)
    card.get_by_role("button", name="Suggest with Codex").click()
    card.locator(".hl-card-option").first.wait_for()
    asked = _received_turns(server)

    with server.hold_codex_request("turn/start") as reached:
        card.get_by_role("button", name="Try again").click()
        _wait_until(reached.exists, message="Try again never reached the agent")
        card.locator(".hl-card-spinner").wait_for()
        assert card.locator(".hl-card-option").count() == 0
    card.locator(".hl-card-option").first.wait_for()
    assert _received_turns(server) == asked + 1
    assert card.locator(".hl-card-spinner").count() == 0
    assert _scroll_top(page) == top


def test_closing_the_card_mid_request_does_not_cancel_it(page: Page, server: ProseviewServer):
    _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    top = _scroll_top(page)
    with server.hold_codex_request("turn/start") as reached:
        card.get_by_role("button", name="Suggest with Codex").click()
        _wait_until(reached.exists, message="the suggestion never reached the agent")
        _reopen(page)
        card.locator(".hl-card-spinner").wait_for()
        _wait_until(lambda: card.locator(".hl-card-elapsed").inner_text() in {"0:01", "0:02", "0:03"},
                    message="the clock did not keep counting from the first ask")
        page.keyboard.press("Escape")
        card.wait_for(state="hidden")
    # The answer lands while the card is closed, and is there on the next click.
    page.wait_for_timeout(500)
    page.locator("#sceneProseHost .hl-filter").first.click()
    card.locator(".hl-card-option").first.wait_for()
    assert card.locator(".hl-card-option").count() == 3
    assert _scroll_top(page) == top


def test_the_gear_opens_suggestion_settings_which_save_and_can_be_tried(page: Page, server: ProseviewServer):
    _open_card(page, server)
    page.locator("#hlSuggestCard .hl-card-gear").click()
    page.wait_for_selector("#settingsDialog[open]")
    page.wait_for_selector("#settingsPanelSuggestions:not([hidden]) .suggestion-grid")
    assert page.locator("#settingsTabSuggestions").get_attribute("aria-selected") == "true"
    assert page.locator("#settingsPanelGeneral").is_hidden(), "the everyday settings are on their own tab"
    assert page.locator("#hlSuggestCard").is_hidden()
    assert page.locator("#settingsDialog").is_visible()

    claude_tools = page.locator('.suggestion-cell[data-agent="claude"] select[aria-label="claude tools"]')
    claude_tools.select_option("none")
    page.locator('#settingsPanelSuggestions select[aria-label="Context"]').select_option("scene")
    page.locator("#settingsPanelSuggestions .suggestion-prompts summary").click()
    echoes = page.locator('#settingsPanelSuggestions textarea[aria-label="Echoes prompt"]')
    echoes.fill("Keep the earlier word; change this one.")
    page.click("#settingsSaveBtn")
    _wait_until(lambda: "context: scene" in (server.root / ".proseview.yaml").read_text(encoding="utf-8")
                if (server.root / ".proseview.yaml").exists() else False,
                message="the book's suggestion settings were not saved")
    yaml_text = (server.root / ".proseview.yaml").read_text(encoding="utf-8")
    assert "echoes: Keep the earlier word; change this one." in yaml_text
    assert "tools" not in yaml_text, "tools belong to this computer, not the book"

    # Try it shows how a sample suggestion went.
    page.locator('.suggestion-cell[data-agent="codex"] button', has_text="Try it").click()
    result = page.locator('.suggestion-try-out[data-agent="codex"] dl')
    result.wait_for(timeout=20000)
    text = result.inner_text()
    for label in ("Model", "Instructions", "Tools", "MCP servers", "Time", "First option"):
        assert label in text

    # Still there after a reload.
    page.reload(wait_until="load")
    page.evaluate("openSuggestionSettings()")
    page.wait_for_selector("#settingsPanelSuggestions:not([hidden]) .suggestion-grid")
    assert page.locator('.suggestion-cell[data-agent="claude"] select[aria-label="claude tools"]').input_value() == "none"
    assert page.locator('#settingsPanelSuggestions select[aria-label="Context"]').input_value() == "scene"


def test_hovering_suggested_by_names_the_model(page: Page, server: ProseviewServer):
    _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    card.get_by_role("button", name="Suggest with Codex").click()
    card.locator(".hl-card-option").first.wait_for()
    title = card.locator(".hl-card-by").get_attribute("title") or ""
    assert title.strip(), "the model is named on hover"



def test_settings_can_be_made_wider_and_keep_that_width(page: Page, server: ProseviewServer):
    page.set_viewport_size({"width": 1400, "height": 900})
    open_scene(page, server)
    page.evaluate("openSuggestionSettings()")
    dialog = page.locator("#settingsDialog")
    before = dialog.bounding_box()["width"]
    assert before >= 900, "Settings opens wider than it used to"

    handle = page.locator("#settingsDialog .settings-resize").bounding_box()
    x, y = handle["x"] + handle["width"] / 2, handle["y"] + 40
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y, steps=4)
    page.mouse.up()
    after = dialog.bounding_box()["width"]
    assert after > before + 100

    page.reload(wait_until="load")
    page.evaluate("openSuggestionSettings()")
    assert abs(page.locator("#settingsDialog").bounding_box()["width"] - after) < 2, "the width is remembered"

    page.locator("#settingsDialog .settings-resize").dblclick()
    assert abs(page.locator("#settingsDialog").bounding_box()["width"] - before) < 2, "double-click restores it"


def test_settings_never_outgrow_a_narrow_window(page: Page, server: ProseviewServer):
    page.set_viewport_size({"width": 700, "height": 900})
    open_scene(page, server)
    page.evaluate("setSettingsWidth(1600, true); openSuggestionSettings()")
    for tab in ("#settingsTabSuggestions", "#settingsTabGeneral"):
        page.click(tab)
        box = page.locator("#settingsDialog").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 700, tab


def test_both_agents_can_be_asked_and_keep_their_own_answers(page: Page, server: ProseviewServer):
    _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    top = _scroll_top(page)
    assert card.get_by_role("button", name="Suggest with Codex").is_visible()
    assert card.get_by_role("button", name="Suggest with Claude").is_visible()

    with server.hold_codex_request("turn/start") as reached:
        card.get_by_role("button", name="Suggest with Codex").click()
        _wait_until(reached.exists, message="Codex was never asked")
        # Claude can be asked while Codex is still working.
        card.get_by_role("button", name="Suggest with Claude").click()
        card.locator('.hl-card-group[data-agent="codex"] .hl-card-spinner').wait_for()
        card.locator('.hl-card-group[data-agent="claude"] .hl-card-by').wait_for(timeout=20000)
        assert "Suggested by Claude in" in card.locator('.hl-card-group[data-agent="claude"] .hl-card-by').inner_text()
    card.locator('.hl-card-group[data-agent="codex"] .hl-card-by').wait_for()
    assert card.locator(".hl-card-group").count() == 2
    assert card.locator(".hl-card-again").count() == 2, "each answer has its own Try again"
    assert card.get_by_role("button", name="Suggest with Codex").count() == 0
    assert _scroll_top(page) == top

    # Both are still there when the mark is clicked again.
    _reopen(page)
    assert card.locator(".hl-card-group").count() == 2


def _apply_first_option(page: Page, server: ProseviewServer) -> tuple[str, str, str]:
    scene, _word = _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    original = page.evaluate("_hlCard.text")
    card.get_by_role("button", name="Suggest with Codex").click()
    card.locator(".hl-card-option").first.wait_for()
    choice = card.locator(".hl-card-option-text").first.inner_text()
    card.locator(".hl-card-use").first.click()
    _wait_until(lambda: "Applied ·" in card.locator(".hl-card-applied").inner_text(),
                message="the rewrite was not applied and saved")
    page.keyboard.press("Escape")
    card.wait_for(state="hidden")
    return scene, original, choice


def _scene_text(server: ProseviewServer, scene: str) -> str:
    return (server.root / "manuscript" / scene).read_text(encoding="utf-8")


def test_applied_text_stays_clickable_and_can_be_restored(page: Page, server: ProseviewServer):
    scene, original, choice = _apply_first_option(page, server)
    top = _scroll_top(page)
    applied = page.locator("#sceneProseHost .hl-applied")
    applied.first.wait_for()
    assert choice.lower() in applied.first.inner_text().lower()

    applied.first.click()
    card = page.locator("#hlSuggestCard")
    card.wait_for()
    assert "Suggestion applied" in card.inner_text()
    assert original in card.locator(".hl-card-was").inner_text()
    assert card.get_by_role("button", name="Use instead").count() == 2, "the other options are offered"

    card.get_by_role("button", name="Restore original").click()
    _wait_until(lambda: choice not in _scene_text(server, scene), message="Restore did not save the original")
    assert page.locator("#sceneProseHost .hl-applied").count() == 0
    assert _scroll_top(page) == top


def test_use_instead_swaps_to_another_option(page: Page, server: ProseviewServer):
    scene, _original, choice = _apply_first_option(page, server)
    page.locator("#sceneProseHost .hl-applied").first.click()
    card = page.locator("#hlSuggestCard")
    other = card.locator(".hl-card-options .hl-card-option-text").first.inner_text()
    card.get_by_role("button", name="Use instead").first.click()
    _wait_until(lambda: other in _scene_text(server, scene) and choice not in _scene_text(server, scene),
                message="the other option was not put in and saved")
    assert other.lower() in page.locator("#sceneProseHost .hl-applied").first.inner_text().lower()


def test_cmd_z_while_reading_undoes_the_last_suggestion(page: Page, server: ProseviewServer):
    scene, original, choice = _apply_first_option(page, server)
    page.locator("#sceneProseHost .hl-applied").first.wait_for()
    top = _scroll_top(page)
    page.keyboard.press("ControlOrMeta+z")
    _wait_until(lambda: choice not in _scene_text(server, scene), message="Cmd+Z did not undo the suggestion")
    _wait_until(lambda: "Undone" in page.locator("#sidebarFileToast").inner_text(),
                message="no Undone note")
    assert page.locator("#sceneProseHost .hl-applied").count() == 0
    assert _scroll_top(page) == top


def test_done_stops_marking_the_suggestion(page: Page, server: ProseviewServer):
    scene, _original, choice = _apply_first_option(page, server)
    page.locator("#sceneProseHost .hl-applied").first.click()
    page.locator("#hlSuggestCard").get_by_role("button", name="Done").click()
    _wait_until(lambda: page.locator("#sceneProseHost .hl-applied").count() == 0)
    assert choice in _scene_text(server, scene), "Done keeps the text"


def test_history_names_the_suggestion(page: Page, server: ProseviewServer):
    scene, _original, _choice = _apply_first_option(page, server)
    history = server.get_json(f"/api/scene/history?path=manuscript/{scene}")
    sources = [row["source"] for row in history.get("history") or history.get("backups") or []]
    assert "Suggestion: Filter Verbs (Codex)" in sources



def test_no_keep_as_is_and_marks_have_no_hover_card(page: Page, server: ProseviewServer):
    """The click card is a mark's only card; nothing appears on hover."""
    _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    assert card.get_by_role("button", name="Keep as is").count() == 0, "x closes the card"
    card.get_by_role("button", name="Close").click()
    mark = page.locator("#sceneProseHost .hl-filter").first
    mark.hover()
    page.wait_for_timeout(300)
    assert page.locator(".hl-custom-tooltip").count() == 0
    assert page.locator("#sceneProseHost [data-hl-title], #sceneProseHost [data-hl-desc]").count() == 0


def test_echoes_are_numbered_and_light_their_partners(page: Page, server: ProseviewServer):
    from .test_browser_e2e import _scene_with_hits, open_scene_analysis as analysis

    scene = _scene_with_hits(server, "echoes")
    open_scene(page, server, scene)
    analysis(page)
    page.click("#pass-row-echoes")
    marks = page.locator("#sceneProseHost .hl-echo")
    marks.first.wait_for()
    groups = page.evaluate("""() => {
        const out = {};
        document.querySelectorAll('#sceneProseHost .hl-echo[data-hl-group]').forEach(el => {
            (out[el.dataset.hlGroup] = out[el.dataset.hlGroup] || []).push(el.classList.contains('is-first'));
        });
        return out;
    }""")
    assert groups and all(len(v) >= 2 and v[0] and not any(v[1:]) for v in groups.values()), groups
    shown = int(page.locator("#pass-row-echoes .scene-pass-count").inner_text())
    assert shown == len(groups), "the row counts echoes, not words"
    assert page.locator("#sceneProseHost .hl-echo-count").count() == marks.count()
    # Each word says which word of its echo it is and how many it has: 1/3, 2/3, 3/3.
    places = page.evaluate("""() => {
        const badges = [...document.querySelectorAll('#sceneProseHost .hl-echo-count')];
        const out = {};
        document.querySelectorAll('#sceneProseHost .hl-echo[data-hl-group]').forEach(el => {
            const badge = badges.find(b => el.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
            (out[el.dataset.hlGroup] = out[el.dataset.hlGroup] || []).push(badge.textContent);
        });
        return out;
    }""")
    for group_id, texts in places.items():
        n = len(texts)
        assert texts == [f"{k}/{n}" for k in range(1, n + 1)], (group_id, texts)
    # The number never wraps away from its word.
    assert page.locator("#sceneProseHost .hl-echo-count").first.evaluate("b => getComputedStyle(b).whiteSpace") == "nowrap"
    group = next(iter(groups))
    first = page.locator(f'#sceneProseHost [data-hl-group="{group}"]').first
    first.evaluate("el => el.scrollIntoView({block: 'center'})")
    tint = first.evaluate("el => getComputedStyle(el).backgroundColor")
    first.hover()
    assert page.locator(f'#sceneProseHost [data-hl-group="{group}"].is-partner').count() == len(groups[group])
    # Partners take their own colour, not the echo tint.
    lit = first.evaluate("el => getComputedStyle(el).backgroundColor")
    assert lit != tint
    assert lit == page.evaluate("""() => { const p = document.createElement('span');
        p.style.background = 'var(--hl-echo-partner-bg)'; document.body.appendChild(p);
        const c = getComputedStyle(p).backgroundColor; p.remove(); return c; }""")
    first.click()
    page.wait_for_selector("#hlSuggestCard:not([hidden])")
    echo_note = page.locator("#hlSuggestCard .hl-card-note").inner_text()
    assert f"1 of {len(groups[group])} \u00b7 " in echo_note, echo_note


def test_a_repeated_word_lights_its_other_uses(page: Page, server: ProseviewServer):
    from .test_browser_e2e import _scene_with_hits, open_scene_analysis as analysis

    scene = _scene_with_hits(server, "repeats")
    open_scene(page, server, scene)
    analysis(page)
    page.click("#pass-row-repeats")
    marks = page.locator("#sceneProseHost [data-hl-repeat]")
    marks.first.wait_for()
    group = marks.first.get_attribute("data-hl-repeat")
    same = page.locator(f'#sceneProseHost [data-hl-repeat="{group}"]')
    assert same.count() >= 2
    tint = marks.first.evaluate("el => getComputedStyle(el).backgroundColor")
    marks.first.evaluate("el => el.scrollIntoView({block: 'center'})")
    marks.first.hover()
    assert page.locator(f'#sceneProseHost [data-hl-repeat="{group}"].is-partner').count() == same.count()
    assert page.locator("#sceneProseHost .is-partner").count() == same.count(), "other words stay as they were"
    assert marks.first.evaluate("el => getComputedStyle(el).backgroundColor") != tint
    page.mouse.move(5, 5)
    assert page.locator("#sceneProseHost .is-partner").count() == 0
    # Numbered as an echo's words are: its place among the word's uses, in reading order.
    places = page.evaluate("""() => {
        const badges = [...document.querySelectorAll('#sceneProseHost .hl-repeat-count')];
        const out = {};
        document.querySelectorAll('#sceneProseHost [data-hl-repeat]').forEach(el => {
            const badge = badges.find(b => el.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
            (out[el.dataset.hlRepeat] = out[el.dataset.hlRepeat] || []).push(badge.textContent);
        });
        return out;
    }""")
    for word, texts in places.items():
        n = len(texts)
        assert texts == [f"{k}/{n}" for k in range(1, n + 1)], (word, texts)
    # The card says it in words, with the paragraph's count.
    marks.first.click()
    page.wait_for_selector("#hlSuggestCard:not([hidden])")
    note = page.locator("#hlSuggestCard .hl-card-note").inner_text()
    assert re.search(rf"1 of {same.count()} in this scene \u00b7 \d+ in this paragraph", note), note


def test_todo_unstick_card_suggests_and_replaces_todo_with_prose(page: Page, server: ProseviewServer):
    open_scene(page, server, ANNOTATED_SCENE_REL)
    todo = page.locator("#sceneProseHost .pm-annotation-todo").first
    todo.wait_for()
    assert todo.locator(".pm-annotation-unstick").count() == 0
    todo.click()
    unstick_btn = page.locator("#sceneProseHost .pm-annotation-editing .pm-annotation-unstick").first
    unstick_btn.wait_for(state="visible")
    assert unstick_btn.inner_text() == "Suggest"
    assert "3 ways to write or bridge this TODO beat" in (unstick_btn.get_attribute("data-tip") or "")
    assert unstick_btn.inner_text() == "Suggest"
    assert "3 ways to write or bridge this TODO beat" in (unstick_btn.get_attribute("data-tip") or "")

    requests = []
    bridge_prose = "Elena caught the brass key before it rolled under the threshold and tried the lock."

    def handle(route):
        requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "ok": True,
                "agent": "codex",
                "original": requests[-1].get("text", ""),
                "original_glue_pct": 0.0,
                "alternatives": [
                    {"text": bridge_prose, "rationale": "Bridges the beat with concrete action.", "glue_pct": 25.0},
                    {"text": "She knelt beside the doorway, measuring the lock against her thumb.", "rationale": "Slower sensory beat.", "glue_pct": 22.0},
                    {"text": '"Wait," she whispered, though the corridor was empty.', "rationale": "Opens with voice.", "glue_pct": 20.0},
                ],
            }),
        )

    page.route("**/api/discuss/highlight-suggest", handle)
    unstick_btn.click()
    card = page.locator("#hlSuggestCard")
    card.wait_for(state="visible")
    assert "Suggest for TODO" in card.locator(".hl-card-title").inner_text()

    card.get_by_role("button", name="Suggest with Codex").click()
    page.wait_for_selector("#hlSuggestCard .hl-card-option")
    assert len(requests) == 1
    assert requests[0]["pass"] == "todo_unstick"
    assert "[TODO:" in requests[0]["paragraph"]

    card.locator(".hl-card-use").first.click()
    _wait_until(lambda: bridge_prose in page.locator("#sceneProseHost").inner_text())
    _wait_until(lambda: page.locator("#hlSuggestCard .hl-card-applied").inner_text().startswith("Applied ·"))

    # Undo restores the original <!-- TODO: ... --> block.
    card.get_by_role("button", name="Undo").click()
    _wait_until(lambda: bridge_prose not in page.locator("#sceneProseHost").inner_text())
    assert page.locator("#sceneProseHost .pm-annotation-todo").count() >= 1


def test_drafting_momentum_todo_insertion_word_delta_and_sprint_timer(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.click("#sceneEditBtn")
    page.wait_for_function("window._pmEditMode === true")

    delta = page.locator("#sceneEditWordDelta")
    assert delta.inner_text() == "+0w"

    # Start and stop the 15-minute sprint timer.
    sprint = page.locator("#sceneSprintBtn")
    assert "15m" in sprint.inner_text()
    sprint.click()
    assert "is-running" in (sprint.get_attribute("class") or "")
    sprint.click()
    assert "15m" in sprint.inner_text()

    # Insert an inline TODO from the edit bar button and save it to return to prose.
    page.click("#sceneEditTodoBtn")
    inp = page.locator("#sceneProseHost .pm-annotation-editing .pm-annotation-edit-text")
    inp.wait_for(state="visible")
    inp.fill("Bridge the hallway transition here")
    inp.press("Enter")
    _wait_until(lambda: "Bridge the hallway transition here" in page.locator("#sceneProseHost").inner_text())

    # Typing prose updates the live session word delta.
    page.locator("#sceneProseHost .ProseMirror p").first.click()
    page.keyboard.type(" Extra drafting words here ")
    _wait_until(lambda: delta.inner_text() not in ("+0w", ""))
    assert delta.inner_text().startswith("+")
    page.click("#sceneEditBar .scene-edit-cancel")
    page.wait_for_function("window._pmEditMode === false")


def test_where_you_left_off_preview_and_overview_scene_cards_and_filters(page: Page, server: ProseviewServer):
    # Scene after the first shows "Where you left off" from the previous scene.
    open_scene(page, server, ANNOTATED_SCENE_REL)
    tail = page.locator("#scenePrevTail")
    tail.wait_for(state="visible")
    assert "Where you left off" in tail.locator(".scene-prev-tail-summary").inner_text()
    tail.locator(".scene-prev-tail-summary").click()
    assert len(tail.locator(".scene-prev-tail-para").all_inner_texts()) >= 1

    # Return to dashboard and switch the Overview scene list to Cards view + filters.
    page.evaluate("closeSceneModal()")
    page.wait_for_selector("#sceneViewCardsBtn", state="visible")
    page.click("#sceneViewCardsBtn")
    grid = page.locator("#sceneCardsGrid")
    grid.wait_for(state="visible")
    assert grid.locator(".scene-overview-card").count() >= 2
    assert "Goal" in grid.inner_text()
    assert "Conflict" in grid.inner_text()

    page.select_option("#issueFilter", "stubs")
    visible_cards = page.evaluate(
        "() => [...document.querySelectorAll('#sceneCardsGrid .scene-overview-card')].filter(c => c.style.display !== 'none').length"
    )
    assert visible_cards >= 1
    page.select_option("#issueFilter", "all")
    page.click("#sceneViewTableBtn")
    assert page.locator("#sceneTable").is_visible()


@pytest.fixture(autouse=True)
def restore_room_library(request, server):
    if not (request.node.name.startswith("test_room_") or request.node.name.startswith("test_writers_room_")):
        yield
        return
    original = server.post_json("/api/discuss/room-settings", {}).json()["settings"]["library"]
    yield
    server.post_json("/api/discuss/room-settings", {"save": True, "library": original})


class _RoomCalls:
    """Observed server invitations, independent of the browser's polling cadence."""
    def __init__(self, page):
        self.page, self.rows = page, {}

    def snapshot(self):
        data = self.page.evaluate("""() => {
            const session = _roomSessionsByScene[_roomCurrentScenePath()];
            return session && session.runtime ? session.runtime : null;
        }""")
        if data:
            for step in data["steps"]:
                if step["state"] in ("queued", "cancelled"):
                    continue
                turns = data["turns"]
                end = next((i for i, turn in enumerate(turns) if turn.get("step_id") == step["id"] and turn["role"] == "critic"), len(turns))
                history = turns[:end]
                attachments = []
                for turn in history:
                    for item in turn.get("attachments", []):
                        if item not in attachments:
                            attachments.append(item)
                self.rows[step["id"]] = {"seat": step["seat"], "participants": data["participants"], "history": history, "attachments": attachments}
        return list(self.rows.values())

    def __iter__(self): return iter(self.snapshot())
    def __getitem__(self, index): return self.snapshot()[index]
    def __len__(self): return len(self.snapshot())
    def __eq__(self, other): return self.snapshot() == other


def _room_idle(page):
    page.wait_for_function("() => { const s = _roomSessionsByScene[_roomCurrentScenePath()]; return s && s.turns.length && !s.busy && !s.queue.length && !(s.outbox || []).length && !s.sendingOutbox && (!s.runtime || ['idle', 'review'].includes(s.runtime.status)); }")


def test_writers_room_previews_explicit_invitations_and_optional_recap(page: Page, server: ProseviewServer):
    requests, moderators = _RoomCalls(page), []
    page.on("request", lambda req: moderators.append(req.url) if req.url.endswith('/api/discuss/room-moderator') else None)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    _wait_until(lambda: pane.locator(".room-starter-card").count() == 3)
    assert "Story Editor · Codex" in pane.locator("#roomHeaderSummary").inner_text()
    pane.locator('.room-starter-card[data-preset="editorial_critique"]').click()
    preview = pane.locator("#roomPresetPreview")
    preview.wait_for()
    assert requests == []
    pane.get_by_role("combobox", name="Preset invitations", exact=True).select_option("3")
    pane.get_by_role("combobox", name="Preset recap", exact=True).select_option("2")
    assert preview.locator("li").count() == 3
    pane.locator("#roomStartPresetBtn").click()
    _room_idle(page)
    assert [r["seat"] for r in requests] == [1, 2, 1, 2]
    assert pane.locator(".room-preset-invitation").count() == 4
    assert pane.locator(".room-turn-card.is-critic-1").count() == 2
    assert pane.locator(".room-turn-card.is-critic-2").count() == 2
    assert pane.locator(".room-turn-tag").last.inner_text() == "Recap"
    pane.locator("#roomInput").fill("What about the ending?")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [r["seat"] for r in requests] == [1, 2, 1, 2, 1, 2]
    assert pane.locator(".room-preset-invitation").count() == 4
    assert pane.locator("#roomPlanCard").count() == 0 and moderators == []
    pane.locator("#roomInput").fill("@Claude summarize the action items we all agreed on.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [r["seat"] for r in requests][-1:] == [2]
    assert len(requests[-1]["history"]) == 12, "the complete shared thread reaches the ordinary agent"


def test_room_profiles_presets_and_snapshot_names_survive_reload(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    page.click("#roomSettingsBtn")
    page.wait_for_selector("#settingsPanelRoom:not([hidden]) .room-library-card")
    cards = page.locator("#roomSettingsBody .room-library-card")
    cards.nth(0).locator("summary").click()
    page.get_by_role("textbox", name="Profile 1 name", exact=True).fill("Plot & Stakes <b>")
    page.get_by_role("textbox", name="Profile 1 style", exact=True).fill("Curious and direct")
    cards.nth(2).locator("summary").click()
    page.get_by_role("combobox", name="Preset 1 invitations", exact=True).select_option("2")
    page.get_by_role("combobox", name="Preset 1 recap", exact=True).select_option("0")
    page.get_by_role("textbox", name="Preset 1 invitation 1", exact=True).fill("Look at the opening with fresh eyes.")
    assert "Moderator" not in page.locator("#settingsPanelRoom").inner_text()
    page.click("#settingsSaveBtn")
    _wait_until(lambda: page.locator("#settingsSaveBtn").inner_text() == "Saved")
    page.click("#settingsDialog .ledger-close")
    pane.locator("#roomInput").fill("continue")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    user = pane.locator(".room-turn-card.is-user")
    assert user.locator(".chat-message-name").inner_text() == "Me"
    box = user.bounding_box()
    assert box["width"] < 200 and box["height"] < 90
    assert pane.locator(".is-critic-1 .chat-message-name").inner_text() == "Plot & Stakes <b> · Codex"
    assert pane.locator(".is-critic-1 .chat-message-name b").count() == 0
    # Settings edits do not rename an ongoing or saved conversation.
    page.click("#roomSettingsBtn")
    profile = page.locator("#roomSettingsBody .room-library-card").first
    if profile.get_attribute("open") is None:
        profile.locator("summary").click()
    page.get_by_role("textbox", name="Profile 1 name", exact=True).fill("Renamed Editor")
    page.click("#settingsSaveBtn")
    _wait_until(lambda: page.locator("#settingsSaveBtn").inner_text() == "Saved")
    page.click("#settingsDialog .ledger-close")
    assert "Plot & Stakes <b> · Codex" in pane.inner_text()
    page.wait_for_function("() => !_roomSessionFor(_roomCurrentScenePath())._saving")
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane.locator(".is-critic-2 .chat-message-name").wait_for(timeout=20000)
    assert "Plot & Stakes <b> · Codex" in pane.inner_text()
    pane.locator("#roomResetBtn").click()
    pane.locator('.room-starter-card[data-preset="editorial_critique"]').click()
    assert pane.locator("#roomPresetPreview li").count() == 2
    assert "Look at the opening with fresh eyes." in pane.locator("#roomPresetPreview").inner_text()
    assert pane.get_by_role("combobox", name="Preset recap", exact=True).input_value() == "0"
    assert "Renamed Editor" in pane.locator("#roomHeaderSummary").inner_text()


@pytest.mark.parametrize("both_pass", [False, True])
def test_room_pass_is_quiet_and_does_not_cancel_the_next_invitation(page: Page, server: ProseviewServer, both_pass):
    requests = _RoomCalls(page)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("Anything to add? ROOM_PASS_CODEX" + (" ROOM_PASS_CLAUDE" if both_pass else ""))
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [r["seat"] for r in requests] == [1, 2]
    assert requests[1]["history"][-1]["passed"] is True
    assert pane.locator(".is-critic-1").count() == 0
    assert pane.locator(".is-critic-2").count() == (0 if both_pass else 1)
    assert "[ROOM_PASS]" not in pane.inner_text()
    page.wait_for_function("() => !_roomSessionFor(_roomCurrentScenePath())._saving")
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane.locator(".is-user").wait_for(timeout=20000)
    assert pane.locator(".is-critic-1").count() == 0


def test_room_settings_can_create_profiles_and_presets_and_preview_a_different_pair(page: Page, server: ProseviewServer, tmp_path):
    requests = _RoomCalls(page)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    page.click("#roomSettingsBtn")
    page.wait_for_selector("#settingsPanelRoom:not([hidden]) .room-library-card")
    page.get_by_role("button", name="+ Add profile", exact=True).click()
    page.get_by_role("textbox", name="Profile 3 name", exact=True).fill("First Reader")
    page.get_by_role("textbox", name="Profile 3 specialty", exact=True).fill("Reader expectations and unanswered questions")
    page.get_by_role("combobox", name="Profile 3 provider", exact=True).select_option("claude")
    profile_id = page.evaluate("_rm.library.profiles[2].id")
    page.get_by_role("button", name="+ Add preset", exact=True).click()
    page.get_by_role("textbox", name="Preset 4 name", exact=True).fill("Fresh reader discussion")
    page.get_by_role("combobox", name="Preset 4 participant 1", exact=True).select_option(profile_id)
    page.get_by_role("combobox", name="Preset 4 participant 2", exact=True).select_option("story-editor")
    page.get_by_role("combobox", name="Preset 4 invitations", exact=True).select_option("2")
    page.get_by_role("textbox", name="Preset 4 invitation 1", exact=True).fill("What questions would a new reader ask?")
    page.locator("#settingsDialog").screenshot(path=str(tmp_path / "room-settings.png"))
    page.click("#settingsSaveBtn")
    _wait_until(lambda: page.locator("#settingsSaveBtn").inner_text() == "Saved")
    page.click("#settingsDialog .ledger-close")
    pane.get_by_role("button", name="Fresh reader discussion 2 invitations", exact=False).click()
    assert pane.get_by_role("combobox", name="Room participant 1", exact=True).input_value() == profile_id
    assert pane.get_by_role("combobox", name="Room participant 2", exact=True).input_value() == "story-editor"
    assert "@FirstReader, What questions would a new reader ask?" in pane.locator("#roomPresetPreview").inner_text()
    pane.screenshot(path=str(tmp_path / "room-preview.png"))
    assert requests == []
    pane.locator("#roomStartPresetBtn").click()
    _room_idle(page)
    assert [r["participants"][r["seat"] - 1]["agent"] for r in requests] == ["claude", "codex"]
    assert pane.locator(".is-critic-1 .chat-message-name").inner_text() == "First Reader · Claude"
    assert pane.locator(".is-critic-2 .chat-message-name").inner_text() == "Story Editor · Codex"
    pane.screenshot(path=str(tmp_path / "room-conversation.png"))


def test_room_legacy_plan_can_still_be_reopened_added_to_todo_and_applied(page: Page, server: ProseviewServer):
    response = server.post_json("/api/discuss/room-history", {"action": "save", "session": {
        "id": "legacy-plan", "scene": SCENE_REL, "title": "Earlier discussion", "turns": [{"role": "user", "text": "Review this scene."}],
        "plans": [{"after_turn": 1, "agent": "claude", "items": [
            {"title": "Cut the opening weather line", "line": "17", "original": "The weather was grey.", "replacement": "She had used the same four digits since spring.", "detail": "Open on the safe.", "proposed_by": "Critic 1", "accepted": True},
            {"title": "Keep the dialogue subtext clipped", "detail": "Let the pause carry the tension.", "proposed_by": "Critic 2", "accepted": False}],
            "open": [{"issue": "When to reveal the safe code", "critic1": "Here", "critic2": "Later"}]}]}})
    assert response.json()["ok"]
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    plan = page.locator("#roomPlanCard")
    plan.wait_for(timeout=20000)
    assert plan.locator(".room-plan-item").count() == 2
    assert plan.locator('[data-consensus="agreed"] .room-plan-check').is_checked()
    assert not plan.locator('[data-consensus="suggested"] .room-plan-check').is_checked()
    plan.locator(".room-todo-btn").first.click()
    _wait_until(lambda: "<!-- TODO: Cut the opening weather line" in (server.root / "manuscript" / SCENE_REL).read_text())
    page.locator("#roomApplyBtn").click()
    _wait_until(lambda: page.locator("#utilityTabClaude").get_attribute("aria-selected") == "true")
    _wait_until(lambda: "Writers’ Room revision plan" in page.locator("#discussLog").inner_text())


def test_room_mentions_pick_and_route_only_the_addressed_editors(page: Page, server: ProseviewServer):
    requests = _RoomCalls(page)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@VoiceEditr")
    pane.locator("#roomInput").press("ArrowLeft")
    pane.locator("#roomInput").press_sequentially("o")
    pane.locator("#roomInput").press("Tab")
    assert pane.locator("#roomInput").input_value() == "@VoiceEditor ", "completing a tag mid-word must replace its remaining suffix"
    pane.locator("#roomInput").fill("@")
    picker = pane.get_by_role("listbox", name="Mention an editor or project file")
    picker.wait_for(state="visible")
    assert "Story Editor" in picker.inner_text() and "Codex" in picker.inner_text()
    assert "Voice Editor" in picker.inner_text() and "Claude" in picker.inner_text()
    pane.locator("#roomInput").press("ArrowDown")
    pane.locator("#roomInput").press("Enter")
    assert pane.locator("#roomInput").input_value() == "@VoiceEditor "
    assert pane.locator(".room-turn-card").count() == 0, "selecting a tag must not send"
    assert pane.locator("#roomTargetSelect").input_value() == "critic2"
    assert not pane.locator("#roomTargetSelect").is_enabled()
    pane.locator("#roomInput").press_sequentially("What do you think about the voice?")
    pane.locator("#roomInput").press("Enter")
    _room_idle(page)
    assert [req['seat'] for req in requests] == [2]
    assert pane.locator(".room-turn-card.is-critic-1").count() == 0
    assert "@VoiceEditor" in pane.locator(".room-turn-card.is-user").inner_text()

    # Unique provider aliases work without opening the picker.
    pane.locator("#roomInput").fill("@Codex give me another take.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [req['seat'] for req in requests] == [2, 1]

    # Mention order is speaking order, independent of the normal To selector.
    pane.locator("#roomInput").fill("@VoiceEditor and @StoryEditor: discuss this together.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [req['seat'] for req in requests] == [2, 1, 2, 1]
    pane.locator("#roomInput").fill("Email me at someone@claude.example; this is not a mention.")
    assert pane.locator("#roomTargetSelect").is_enabled()
    assert pane.locator("#roomTargetSelect").input_value() == "both"
    pane.locator("#roomInput").fill("@")
    pane.locator("#roomInput").press("Escape")
    assert picker.is_hidden()
    assert pane.locator("#roomInput").input_value() == "@"
    page.click("#roomSettingsBtn")
    page.wait_for_selector("#settingsPanelRoom:not([hidden]) .room-library-card")
    page.locator("#roomSettingsBody .room-library-card").nth(0).locator("summary").click()
    page.locator("#roomSettingsBody .room-library-card").nth(1).locator("summary").click()
    page.get_by_role("textbox", name="Profile 1 name", exact=True).fill("Editor")
    page.get_by_role("textbox", name="Profile 2 name", exact=True).fill("Editor")
    page.get_by_role("combobox", name="Profile 2 provider", exact=True).select_option("codex")
    page.click("#settingsSaveBtn")
    _wait_until(lambda: page.locator("#settingsSaveBtn").inner_text() == "Saved")
    page.click("#settingsDialog .ledger-close")
    assert "Story Editor · Codex" in pane.inner_text(), "current participants are frozen"
    pane.locator("#roomResetBtn").click()
    pane.locator("#roomInput").fill("@Codex")
    assert picker.get_by_role("option").filter(has_text="Editor · Codex").count() == 2
    assert pane.locator("#roomTargetSelect").is_enabled(), "an ambiguous provider alias must not silently choose a seat"
    picker.get_by_role("option").filter(has_text="@Editor2").click()
    assert pane.locator("#roomInput").input_value() == "@Editor2 "
    pane.locator("#roomInput").press_sequentially("Please give me your view.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [req['seat'] for req in requests] == [2, 1, 2, 1, 2]


def test_room_file_mentions_supply_reference_text_without_changing_editor_routing(page: Page, server: ProseviewServer):
    requests = _RoomCalls(page)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@Codex Compare this with @02-walk")
    picker = pane.get_by_role("listbox", name="Mention an editor or project file")
    picker.wait_for(state="visible")
    assert "manuscript/ch01/02-walk.md" in picker.inner_text()
    pane.locator("#roomInput").press("Enter")
    assert pane.locator("#roomInput").input_value() == "@Codex Compare this with @manuscript/ch01/02-walk.md "
    assert pane.locator("#roomTargetSelect").input_value() == "critic1"
    pane.locator("#roomInput").press("Enter")
    _room_idle(page)
    assert [req["seat"] for req in requests] == [1]
    assert requests[0]["attachments"] == [{"kind": "file", "path": "manuscript/ch01/02-walk.md"}]
    records = [json.loads(line) for line in (server.home / "fake-codex-received.jsonl").read_text().splitlines()]
    assert any("Mentioned: manuscript/ch01/02-walk.md" in record["params"]["input"][0]["text"] for record in records)
    collision = page.evaluate('''() => {
        const original = _discussContextCandidateCache;
        _discussContextCandidateCache = discussContextCandidates().concat([{kind:'file',path:'StoryEditor.md',name:'StoryEditor.md'}]);
        try { return _roomMentionRecipients('@StoryEditor.md'); }
        finally { _discussContextCandidateCache = original; }
    }''')
    assert collision == [], "a filename that begins with an editor handle must not address that editor"
    # File-only messages retain the ordinary To setting and shared context.
    pane.locator("#roomInput").fill("Compare again with @manuscript/ch01/02-walk.md")
    assert pane.locator("#roomTargetSelect").is_enabled()
    assert pane.locator("#roomTargetSelect").input_value() == "both"
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [req["seat"] for req in requests] == [1, 1, 2]
    page.evaluate("attachSelectionToRoom('Quoted @scripts/check_continuity.py', null)")
    pane.locator("#roomInput").fill("Keep discussing the scene.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert requests[-1]["attachments"] == [{"kind": "file", "path": "manuscript/ch01/02-walk.md"}], "quoted selections must not add file reads"


@pytest.mark.parametrize("decision", ["Accept once", "Decline"])
def test_room_tools_show_approvals_in_the_room_and_leave_single_chat_separate(page: Page, server: ProseviewServer, decision):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@Codex REQUEST_APPROVAL inspect the project for this question.")
    pane.locator("#roomSendBtn").click()
    approvals = pane.locator("#roomLiveApprovals")
    approvals.get_by_role("heading", name="Approval required").wait_for(timeout=20000)
    assert "printf approved" in approvals.inner_text()
    assert page.locator("#utilityTabRoom").get_attribute("aria-selected") == "true"
    approvals.get_by_role("button", name=decision, exact=True).click()
    _room_idle(page)
    assert pane.locator(".room-turn-card.is-critic-1").count() == 1
    assert pane.locator(".room-turn-card.is-critic-2").count() == 0
    assert ("Approval resolved: accept" if decision == "Accept once" else "Approval resolved: decline") in pane.inner_text()
    page.click("#utilityTabCodex")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    assert "REQUEST_APPROVAL inspect" not in page.locator("#discussLog").inner_text()


def test_room_can_stop_while_a_tool_is_waiting_for_approval(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@Codex REQUEST_APPROVAL inspect this scene.")
    pane.locator("#roomSendBtn").click()
    pane.locator("#roomLiveApprovals").get_by_role("heading", name="Approval required").wait_for(timeout=20000)
    pane.get_by_role("button", name="Stop", exact=True).click()
    _wait_until(lambda: pane.locator("#roomLiveApprovals").count() == 0)
    assert pane.locator("#roomSendBtn").is_visible()
    assert pane.locator(".room-turn-card.is-critic-1").count() == 0


def test_room_file_edits_can_be_undone_before_the_discussion_continues(page: Page, server: ProseviewServer):
    original = (server.root / "manuscript" / SCENE_REL).read_text()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@Codex SELECT_FILE_CHANGE make this edit.")
    pane.locator("#roomSendBtn").click()
    review = pane.locator(".room-tool-review")
    review.get_by_role("button", name="Expand view", exact=True).wait_for(timeout=20000)
    _room_idle(page)
    assert pane.locator("#roomSendBtn").inner_text() == "Send"
    assert pane.get_by_role("button", name="Continue discussion").count() == 0
    assert (server.root / "manuscript" / SCENE_REL).read_text() != original
    review.get_by_role("button", name="Expand view", exact=True).click()
    page.locator("#discussDiffModalContent .discuss-review-table").first.wait_for()
    page.get_by_role("button", name="Close diff viewer", exact=True).click()
    review.get_by_role("button", name="Undo all", exact=True).click()
    _wait_until(lambda: (server.root / "manuscript" / SCENE_REL).read_text() == original)
    _wait_until(lambda: review.count() == 0)
    _room_idle(page)


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_shared_chat_cards_keep_short_messages_compact(page: Page, server: ProseviewServer, agent):
    open_scene(page, server, SCENE_REL)
    page.evaluate("agent => showDiscussAgentTab(agent)", agent)
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    page.locator("#discussInput").fill("continue")
    page.locator("#discussSend").click()
    _wait_until(lambda: page.locator("#discussLog > .discuss-message.assistant:not(.discuss-stream-draft)").count() > 0, timeout=20)
    user = page.locator("#discussLog > .chat-message-card.user").last
    reply = page.locator("#discussLog > .chat-message-card.assistant:not(.discuss-stream-draft)").last
    assert user.locator(".chat-message-name").inner_text() == "Me"
    assert reply.locator(".chat-message-name").inner_text() == agent.title()
    assert reply.get_by_role("button", name="Copy message", exact=True).count() == 1
    box = user.bounding_box()
    assert box["width"] < 200 and box["height"] < 90


def test_room_mentions_remain_highlighted_unbroken_and_edit_as_one_item(page: Page, server: ProseviewServer, tmp_path):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    text = "@StoryEditor compare this with @manuscript/ch01/02-walk.md please."
    input = pane.locator("#roomInput")
    input.fill(text)
    assert pane.locator(".room-input-mirror .discuss-mention").all_text_contents() == ["@StoryEditor", "@manuscript/ch01/02-walk.md"]
    # Both typed and picked mentions delete as a whole item.
    input.evaluate("el => el.setSelectionRange(13, 13)")
    input.press("Backspace")
    assert input.input_value() == "compare this with @manuscript/ch01/02-walk.md please."
    input.fill(text)
    end = text.index(" please.")
    input.evaluate("(el, end) => el.setSelectionRange(end, end)", end)
    input.press("Backspace")
    assert input.input_value() == "@StoryEditor compare this with  please."
    # Replacing part of a mention replaces the complete token.
    input.fill(text)
    input.evaluate("el => el.setSelectionRange(2, 4)")
    input.press_sequentially("Hello")
    assert input.input_value().startswith("Hello compare this")
    input.fill(text)
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    user = pane.locator(".is-user")
    chips = user.locator(".chat-mention")
    assert chips.all_text_contents() == ["@StoryEditor", "@manuscript/ch01/02-walk.md"]
    assert chips.evaluate_all("els => els.every(el => getComputedStyle(el).whiteSpace === 'nowrap' && getComputedStyle(el).userSelect === 'all')")
    assert chips.nth(1).get_attribute("title") == "manuscript/ch01/02-walk.md"
    pane.screenshot(path=str(tmp_path / "room-mention-chips.png"))
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    user.get_by_role("button", name="Copy message", exact=True).click()
    assert page.evaluate("navigator.clipboard.readText()") == text
    page.wait_for_function("() => !_roomSessionFor(_roomCurrentScenePath())._saving")
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane.locator(".is-user .chat-mention").first.wait_for(timeout=20000)
    assert pane.locator(".is-user .chat-mention").all_text_contents() == ["@StoryEditor", "@manuscript/ch01/02-walk.md"]


def test_single_chat_file_mentions_keep_their_highlight_after_sending(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showDiscussAgentTab('codex')")
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")
    text = "Compare with @manuscript/ch01/02-walk.md please."
    page.locator("#discussInput").fill(text)
    page.locator("#discussSend").click()
    user = page.locator("#discussLog > .chat-message-card.user").last
    user.locator(".chat-mention").wait_for()
    assert user.locator(".chat-mention").inner_text() == "@manuscript/ch01/02-walk.md"


@pytest.mark.parametrize("finish", ["Send follow-up", "Undo 1 change"])
def test_room_uses_the_large_chat_review_and_applies_its_per_change_choices(page: Page, server: ProseviewServer, tmp_path, finish):
    from .test_browser_e2e import OPENED_SECOND, CHANGED_SECOND, CHANGED_SENTENCE
    scene = server.root / "manuscript" / SCENE_REL
    open_scene(page, server, SCENE_REL)
    original_chat = page.evaluate("_discussConversationId")
    original_keep = page.evaluate("JSON.stringify(_discussReviewKeep)")
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("SELECT_FILE_CHANGE make these edits, then discuss them together.")
    pane.locator("#roomSendBtn").click()
    review = pane.locator(".room-tool-review")
    expand = review.get_by_role("button", name="Expand view", exact=True)
    expand.wait_for(timeout=20000)
    _room_idle(page)
    assert pane.locator(".is-critic-2").count() == 1, "the next agent responds without a review gate"
    assert pane.locator("#roomSendBtn").inner_text() == "Send"
    assert review.locator(".discuss-review-block").count() == 0, "the card stays compact"
    expand.click()
    modal = page.locator("#discussDiffModalOverlay")
    modal.wait_for(state="visible")
    page.locator("#discussDiffModalContent table.diff-side-by-side").first.wait_for()
    assert modal.locator(".diff-modal").bounding_box()["width"] > pane.bounding_box()["width"]
    assert modal.locator(".diff-modal").evaluate("el => getComputedStyle(el).resize") == "both"
    assert page.locator("#discussDiffModalTitle").inner_text() == "manuscript/" + SCENE_REL
    room_id = page.evaluate("_roomSessionFor(_roomCurrentScenePath()).turns.find(t => t.review_pending).tool_conversation_id")
    assert page.evaluate("_currentDiscussReviewContext.conversationId") == room_id
    assert page.evaluate("_discussConversationId") == original_chat
    choices = page.locator("#discussDiffModalContent .discuss-review-choice input")
    assert choices.count() == 2
    choices.nth(1).uncheck()
    page.locator("#discussDiffToggleInline").click()
    page.locator("#discussDiffModalContent table.diff-inline").first.wait_for()
    assert not choices.nth(1).is_checked()
    page.locator("#discussDiffFontSize").fill("30")
    assert page.locator("#discussDiffModalContent table.diff").first.evaluate("el => getComputedStyle(el).fontSize") == "30px"
    modal.screenshot(path=str(tmp_path / "room-expanded-review.png"))
    page.get_by_role("button", name="Close diff viewer", exact=True).click()
    assert "Undoing 1 of 2" in review.inner_text()
    assert page.evaluate("JSON.stringify(_discussReviewKeep)") == original_keep
    # The same mode and choices return when expanding the Room card again.
    review.get_by_role("button", name="Expand view", exact=True).click()
    page.locator("#discussDiffModalContent table.diff-inline").first.wait_for()
    assert not choices.nth(1).is_checked()
    page.get_by_role("button", name="Close diff viewer", exact=True).click()
    if finish == "Send follow-up":
        pane.locator("#roomInput").fill("@VoiceEditor how does it read with the kept change?")
        pane.locator("#roomSendBtn").click()
    else:
        review.get_by_role("button", name=finish, exact=True).click()
    _wait_until(lambda: review.count() == 0)
    _room_idle(page)
    assert pane.locator(".is-critic-2").count() == (2 if finish == "Send follow-up" else 1)
    text = scene.read_text()
    assert CHANGED_SENTENCE in text and OPENED_SECOND in text and CHANGED_SECOND not in text
    assert pane.locator(".room-tool-review").count() == 0


def test_room_looks_good_settles_the_review_before_continuing(page: Page, server: ProseviewServer):
    from .test_browser_e2e import CHANGED_SECOND, CHANGED_SENTENCE
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@Codex SELECT_FILE_CHANGE make these edits.")
    pane.locator("#roomSendBtn").click()
    review = pane.locator(".room-tool-review")
    review.get_by_role("button", name="Looks good", exact=True).wait_for(timeout=20000)
    review.get_by_role("button", name="Looks good", exact=True).click()
    _wait_until(lambda: review.count() == 0)
    _room_idle(page)
    pane.locator("#roomInput").fill("Ready for a follow-up")
    assert pane.locator("#roomSendBtn").is_enabled()
    assert pane.locator("#roomSendBtn").inner_text() == "Send"
    text = (server.root / "manuscript" / SCENE_REL).read_text()
    assert CHANGED_SENTENCE in text and CHANGED_SECOND in text


def test_room_composer_has_context_skills_models_quick_send_and_saved_drafts(page: Page, server: ProseviewServer, tmp_path):
    open_scene(page, server, SCENE_REL)
    page.evaluate("localStorage.setItem('proseview-codex-favorite-instructions', JSON.stringify(['Continue', 'Polish this']))")
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.get_by_role("button", name="Add people, files and folders", exact=True).click()
    picker = pane.get_by_role("listbox", name="Mention an editor or project file")
    picker.wait_for(state="visible")
    assert "Story Editor" in picker.inner_text() and "manuscript/ch01/02-walk.md" in picker.inner_text()
    input = pane.locator("#roomInput")
    input.press("Escape")
    input.fill("")
    page.evaluate("mentionInDiscuss('manuscript/ch01/02-walk.md')")
    assert input.input_value() == "@manuscript/ch01/02-walk.md "
    assert pane.is_visible()
    input.fill("")
    pane.get_by_role("combobox", name="Room message recipient", exact=True).select_option("critic2")
    page.evaluate("attachSelectionToRoom('The passage selected for this question.', null)")
    input.fill("Keep this unsent draft.")
    input.evaluate("el => { el.style.height = '140px'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    assert input.evaluate("el => getComputedStyle(el).resize") == "vertical"
    assert pane.locator(".discuss-sees").inner_text() == SCENE_REL
    assert pane.locator("#roomQuickSend").is_visible()
    assert pane.locator("#roomQuickSend button.discuss-preset-inline:enabled").count() == 0
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    input.wait_for()
    assert input.input_value() == "Keep this unsent draft."
    assert input.evaluate("el => el.style.height") == "140px"
    assert pane.locator("#roomTargetSelect").input_value() == "critic2"
    assert "The passage selected" in pane.locator("#roomSelectionChip").inner_text()
    pane.screenshot(path=str(tmp_path / "room-full-composer.png"))
    input.fill("")
    assert pane.locator("#roomQuickSend button.discuss-preset-inline:enabled").count() > 0
    pane.locator("#roomQuickSend button.discuss-preset-inline").first.click()
    _room_idle(page)
    assert pane.locator(".is-user").count() == 1
    assert pane.locator(".is-critic-2").count() == 1
    assert pane.locator("#roomSelectionChip").is_visible(), "selection stays attached for follow-up questions"


def test_room_composer_models_apply_to_this_room_without_changing_profiles_or_single_chat(page: Page, server: ProseviewServer):
    requests = _RoomCalls(page)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    chip = pane.get_by_role("button", name=re.compile("^Model for Story Editor:"))
    chip.click()
    picker = pane.get_by_role("dialog", name="Choose model for Story Editor", exact=True)
    picker.get_by_role("radio", name=re.compile("GPT-5.6-Luna")).click()
    picker.get_by_role("button", name="high", exact=True).click()
    assert picker.get_by_role("button", name="max", exact=True).is_disabled()
    picker.get_by_role("button", name="Close model picker", exact=True).click()
    assert "GPT-5.6-Luna" in chip.inner_text() and "high" in chip.inner_text()
    assert page.evaluate("_roomSettings.library.profiles[0].model") == ""
    assert page.evaluate("(((_discussSnapshot || {}).model || {}).model) || ''") == ""
    pane.locator("#roomInput").fill("@StoryEditor use the selected model.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert requests[0]["participants"][0]["model"] == "gpt-5.6-luna"
    assert requests[0]["participants"][0]["effort"] == "high"
    assert pane.locator(".is-critic-1 .room-turn-model").inner_text() == "gpt-5.6-luna"
    page.wait_for_function("() => !_roomSessionFor(_roomCurrentScenePath())._saving")
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane.locator(".is-critic-1").wait_for()
    assert "GPT-5.6-Luna" in chip.inner_text()


def test_room_composer_skill_picker_sends_the_native_skill_to_the_selected_agent(page: Page, server: ProseviewServer):
    requests = _RoomCalls(page)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("$")
    picker = pane.get_by_role("listbox", name="Mention an editor or project file")
    choice = picker.get_by_role("option").filter(has_text="$tighten-prose")
    choice.wait_for()
    choice.click()
    input = pane.locator("#roomInput")
    assert input.input_value() == "@StoryEditor $tighten-prose "
    assert pane.locator(".room-input-mirror .discuss-mention").all_text_contents() == ["@StoryEditor", "$tighten-prose"]
    input.press_sequentially("Keep the scene's voice.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert [req["seat"] for req in requests] == [1]
    assert "$tighten-prose" in requests[0]["history"][-1]["text"]
    records = [json.loads(line) for line in (server.home / "fake-codex-received.jsonl").read_text().splitlines()]
    assert any(any(item.get("type") == "skill" and item.get("name") == "tighten-prose" for item in row.get("params", {}).get("input", [])) for row in records)


def test_room_composer_queues_messages_while_agents_reply_and_can_remove_them(page: Page, server: ProseviewServer):
    requests = _RoomCalls(page)
    with server.hold_codex_request("turn/start") as reached:
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane = page.locator("#sceneRoomPane")
        pane.locator("#roomInput").fill("@StoryEditor answer this first.")
        pane.locator("#roomSendBtn").click()
        _wait_until(reached.exists)
        pane.locator("#roomInput").fill("@VoiceEditor answer this next.")
        assert pane.locator("#roomSendBtn").inner_text() == "Queue"
        pane.locator("#roomSendBtn").click()
        pane.locator("#roomInput").fill("@StoryEditor remove this queued question.")
        pane.locator("#roomSendBtn").click()
        pane.get_by_role("button", name="Remove queued message 2", exact=True).click()
        _wait_until(lambda: pane.locator(".room-message-queue .discuss-queue-item").count() == 1)
    _room_idle(page)
    assert [req["seat"] for req in requests] == [1, 2]
    assert pane.locator(".is-user").count() == 2
    assert "answer this next" in pane.locator(".is-user").last.inner_text()
    assert pane.locator(".room-message-queue").count() == 0


def test_room_discussion_and_queued_messages_survive_reload_without_resending(page: Page, server: ProseviewServer):
    requests = _RoomCalls(page)
    with server.hold_codex_request("turn/start") as reached:
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane = page.locator("#sceneRoomPane")
        pane.locator("#roomInput").fill("@StoryEditor first question.")
        pane.locator("#roomSendBtn").click()
        _wait_until(reached.exists)
        pane.locator("#roomInput").fill("@VoiceEditor keep this queued message.")
        pane.locator("#roomSendBtn").click()
        pane.get_by_role("button", name="Remove queued message 1", exact=True).wait_for()
        page.reload()
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane.locator(".is-user").wait_for()
        assert "keep this queued message" in pane.locator(".room-message-queue").inner_text()
    _room_idle(page)
    assert [req["seat"] for req in requests] == [1, 2]
    assert pane.locator(".is-user").count() == 2
    assert pane.locator(".is-critic-1").count() == pane.locator(".is-critic-2").count() == 1


def test_diff_viewer_can_expand_a_patch_before_any_review_is_opened(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.evaluate("openDiscussDiffModal('--- a/scene.md\\n+++ b/scene.md\\n@@ -1 +1 @@\\n-Old sentence.\\n+New sentence.\\n')")
    page.locator("#discussDiffModalContent table.diff-side-by-side").wait_for()
    assert page.locator("#discussDiffModalTitle").inner_text() == "Review Changes"
    page.get_by_role("button", name="Close diff viewer", exact=True).click()
    assert page.locator("#discussDiffModalOverlay").is_hidden()


def test_room_preset_runs_remaining_invitations_after_reload(page: Page, server: ProseviewServer):
    with server.hold_codex_request("turn/start") as reached:
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane = page.locator("#sceneRoomPane")
        pane.locator('.room-starter-card[data-preset="editorial_critique"]').click()
        pane.get_by_role("combobox", name="Preset invitations", exact=True).select_option("3")
        pane.get_by_role("combobox", name="Preset recap", exact=True).select_option("2")
        pane.locator("#roomStartPresetBtn").click()
        _wait_until(reached.exists)
        page.reload()
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane.locator(".room-preset-invitation").first.wait_for()
    _room_idle(page)
    state = page.evaluate("_roomSessionFor(_roomCurrentScenePath()).runtime")
    assert [step["seat"] for step in state["steps"]] == [1, 2, 1, 2]
    assert all(step["state"] == "completed" for step in state["steps"])
    assert pane.locator(".room-preset-invitation").count() == 4
    assert pane.locator(".room-turn-tag").last.inner_text() == "Recap"


def test_room_review_and_queued_invitation_survive_server_restart(page: Page, server: ProseviewServer):
    scene = server.root / "manuscript" / SCENE_REL
    original = scene.read_text()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("SELECT_FILE_CHANGE make these edits, then discuss them together.")
    pane.locator("#roomSendBtn").click()
    review = pane.locator(".room-tool-review")
    review.get_by_role("button", name="Expand view", exact=True).wait_for(timeout=20000)
    _room_idle(page)
    room_id = page.evaluate("_roomSessionFor(_roomCurrentScenePath()).id")
    review.get_by_role("button", name="Expand view", exact=True).click()
    page.locator("#discussDiffModalContent .discuss-review-choice input").nth(1).uncheck()
    page.get_by_role("button", name="Close diff viewer", exact=True).click()
    pane.locator("#roomInput").fill("Unsent draft preserved through restart")
    server.restart()
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    review.get_by_role("button", name="Expand view", exact=True).wait_for(timeout=20000)
    assert page.evaluate("_roomSessionFor(_roomCurrentScenePath()).id") == room_id
    assert pane.locator("#roomInput").input_value() == "Unsent draft preserved through restart"
    assert pane.locator(".is-critic-2").count() == 1
    review.get_by_role("button", name="Expand view", exact=True).click()
    page.locator("#discussDiffModalContent .discuss-review-table").first.wait_for()
    assert page.locator("#discussDiffModalContent .discuss-review-choice input").count() == 2
    assert not page.locator("#discussDiffModalContent .discuss-review-choice input").nth(1).is_checked()
    page.get_by_role("button", name="Close diff viewer", exact=True).click()
    review.get_by_role("button", name="Undo all", exact=True).click()
    _wait_until(lambda: scene.read_text() == original)
    _wait_until(lambda: review.count() == 0)
    _room_idle(page)
    assert pane.locator(".is-critic-1").count() == pane.locator(".is-critic-2").count() == 1


def test_room_restart_during_a_reply_requires_an_explicit_retry_or_skip(page: Page, server: ProseviewServer):
    with server.hold_codex_request("turn/start") as reached:
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane = page.locator("#sceneRoomPane")
        pane.locator("#roomInput").fill("@StoryEditor answer this question.")
        pane.locator("#roomSendBtn").click()
        _wait_until(reached.exists)
        server.restart()
        page.reload()
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane.get_by_role("button", name="Skip interrupted invitation", exact=True).wait_for(timeout=20000)
        assert pane.get_by_role("button", name="Retry interrupted invitation", exact=True).is_enabled()
        assert pane.locator(".is-critic-1").count() == 0
        pane.get_by_role("button", name="Skip interrupted invitation", exact=True).click()
    _room_idle(page)
    assert pane.locator(".is-user").count() == 1
    assert pane.locator(".is-critic-1").count() == 0
    assert page.evaluate("_roomSessionFor(_roomCurrentScenePath()).runtime.steps[0].state") == "cancelled"


def test_room_reload_retries_an_unconfirmed_send_without_duplicate_messages(page: Page, server: ProseviewServer):
    accepted = []
    def lose_ack(route):
        body = route.request.post_data_json
        if body.get("action") == "submit" and not accepted:
            response = route.fetch()
            assert response.ok
            accepted.append(body)
            route.abort()
        else:
            route.continue_()
    page.route("**/api/discuss/room-run", lose_ack)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@StoryEditor deliver this once.")
    pane.locator("#roomSendBtn").click()
    page.wait_for_function("() => { const s = _roomSessionFor(_roomCurrentScenePath()); return s.sendError || s.runtime; }")
    assert accepted
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    _room_idle(page)
    assert pane.locator(".is-user").count() == pane.locator(".is-critic-1").count() == 1
    state = page.evaluate("_roomSessionFor(_roomCurrentScenePath()).runtime")
    assert len(state["steps"]) == 1 and accepted[0]["request_id"] in state["acknowledged_requests"]


def test_room_recovers_an_unsent_outbox_before_opening_an_older_room(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@StoryEditor an older discussion.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    pane.locator("#roomResetBtn").click()
    def offline_submit(route):
        if route.request.post_data_json.get("action") == "submit":
            route.abort()
        else:
            route.continue_()
    page.route("**/api/discuss/room-run", offline_submit)
    pane.locator("#roomInput").fill("@VoiceEditor recover this new discussion.")
    pane.locator("#roomSendBtn").click()
    page.wait_for_function("() => !!_roomSessionFor(_roomCurrentScenePath()).sendError")
    new_id = page.evaluate("_roomSessionFor(_roomCurrentScenePath()).id")
    page.unroute("**/api/discuss/room-run", offline_submit)
    page.reload()
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    _room_idle(page)
    assert page.evaluate("_roomSessionFor(_roomCurrentScenePath()).id") == new_id
    assert pane.locator(".is-user").count() == pane.locator(".is-critic-2").count() == 1
    assert "recover this new discussion" in pane.locator(".is-user").inner_text()
    assert pane.locator(".is-critic-1").count() == 0
