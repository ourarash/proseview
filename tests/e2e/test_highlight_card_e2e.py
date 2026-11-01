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


