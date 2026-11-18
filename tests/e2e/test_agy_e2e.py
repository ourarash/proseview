"""End-to-end Playwright browser tests for the Agy backend across Discuss, /btw, Highlight Suggestions, and Beat Map."""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from .conftest import SCENE_REL, ProseviewServer  # noqa: E402
from .test_browser_e2e import _wait_until, open_scene, wait_for_discuss_idle  # noqa: E402
from .test_btw_e2e import _open_discuss_agent  # noqa: E402
from .test_highlight_card_e2e import _open_card  # noqa: E402

pytestmark = pytest.mark.e2e_browser


def test_agy_dock_chat_streams_filters_thoughts_and_runs_seeded_btw(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, "agy")

    # Model picker populates from the ACP session/new catalog.
    expect(page.locator("#discussModelChip")).to_contain_text("Gemini 4 Argon")
    page.fill("#discussInput", "Check opening pacing.")
    page.click("#discussSend")

    page.wait_for_function("() => document.querySelector('#discussPanel').innerText.includes('Fake Agy reply:')")
    wait_for_discuss_idle(page)
    expect(page.locator("#discussPanel")).to_contain_text("Fake Agy reply:")
    panel_text = page.locator("#discussPanel").inner_text()
    assert "Fake Agy reply:" in panel_text
    assert "PRIVATE AGY THOUGHT" not in panel_text

    # /btw runs in seeded mode without failing on missing native fork.
    page.fill("#discussInput", "/btw Check consistency in ch01.")
    assert page.locator("#discussSend").inner_text().strip() == "Ask /btw"
    page.click("#discussSend")
    page.wait_for_function("() => !document.querySelector('#btwSplitPane').hidden")
    page.wait_for_function("() => document.querySelector('.btw-tab')?.dataset.status === 'completed'")
    btw_text = page.locator("#btwTabPanel").inner_text()
    assert "Check consistency in ch01." in btw_text
    assert "Fake Agy reply:" in btw_text


def test_agy_highlight_suggestion_card_extracts_fenced_json_and_applies(page: Page, server: ProseviewServer):
    _scene, _word = _open_card(page, server)
    card = page.locator("#hlSuggestCard")
    agy_btn = card.get_by_role("button", name="Suggest with Agy")
    assert agy_btn.is_visible()

    agy_btn.click()
    agy_group = card.locator('.hl-card-group[data-agent="agy"]')
    agy_group.locator(".hl-card-option").first.wait_for(timeout=15000)
    assert agy_group.locator(".hl-card-option").count() == 3
    assert "Suggested by Agy in" in agy_group.locator(".hl-card-by").inner_text()

    choice = agy_group.locator(".hl-card-option-text").first.inner_text()
    assert choice == "Agy tightened rewrite one."
    agy_group.locator(".hl-card-use").first.click()
    _wait_until(
        lambda: "Applied ·" in card.locator(".hl-card-applied").inner_text(),
        message="the card did not report the Agy rewrite as applied",
    )
    assert choice in page.locator("#sceneProseHost").inner_text()


def test_agy_beatmap_generation_and_settings_roundtrip(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.click("#sceneModal .discuss-open-btn")
    page.click("#utilityTabBeats")
    page.wait_for_selector("#paneAgentSelect")
    assert page.locator("#paneAgentSelect option[value='agy']").count() == 1

    page.select_option("#paneAgentSelect", "agy")
    page.click(".beatmap-generate-btn")
    page.wait_for_selector(".sidebar-beat-group", timeout=15000)
    assert "Agy Opening Beat" in page.locator("#sceneBeatMapPane").inner_text()

    # Settings -> Beat Map persists Agy selection.
    page.evaluate("openBeatMapSettings()")
    page.wait_for_selector("#settingsPanelBeatmap:not([hidden])")
    agent_select = page.locator("#beatmapSettingsBody select").first
    agent_select.wait_for()
    assert agent_select.locator("option[value='agy']").count() == 1
    agent_select.select_option("agy")
    save_btn = page.locator("#settingsSaveBtn")
    assert save_btn.is_enabled()
    save_btn.click()
    page.wait_for_selector("#settingsSaveBtn:has-text('Saved')", timeout=5000)
    assert server.get_json("/api/discuss/beatmap-settings")["settings"]["book"]["agent"] == "agy"


import copy


def test_agy_group_critic_seat_replies_in_group_panel(page: Page, server: ProseviewServer):
    original = server.post_json("/api/discuss/group-settings", {}).json()["settings"]
    library = copy.deepcopy(original["library"])
    library["profiles"][0]["agent"] = "agy"
    library["profiles"][0]["model"] = ""
    library["profiles"][0]["effort"] = ""
    try:
        server.post_json("/api/discuss/group-settings", {
            "save": True,
            "library": library,
            "app": {**original["app"], "library": library, "critic1": {"agent": "agy"}, "moderator": {"agent": "agy"}},
        })
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('group')")
        pane = page.locator("#sceneGroupPane")
        pane.locator("#groupInput").fill("@StoryEditor How is the tension here?")
        pane.locator("#groupSendBtn").click()
        card = pane.locator(".group-turn-card.is-critic-1").first
        card.wait_for(timeout=15000)
        card_text = card.inner_text()
        assert "Fake Agy reply:" in card_text
        assert "Story Editor · Agy" in card_text
        assert "Agy default" in card_text
    finally:
        server.post_json("/api/discuss/group-settings", {
            "save": True,
            "library": original["library"],
            "app": {**original["app"], "library": original["library"]},
        })


def test_three_agent_group_room_toggle_and_send_to_group_with_efforts(page: Page, server: ProseviewServer):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane = page.locator("#sceneGroupPane")

    # Default Group room has 3 active participants.
    assert pane.get_by_role("button", name="3 agents", exact=True).get_attribute("aria-pressed") == "true"
    assert "Continuity Editor · Agy" in pane.locator("#groupHeaderSummary").inner_text()
    assert pane.locator("#groupTargetSelect option").count() == 4  # All 3, Seat 1, Seat 2, Seat 3

    # Toggle down to 2 agents and back up to 3 before turn 1.
    pane.get_by_role("button", name="2 agents", exact=True).click()
    assert pane.locator("#groupTargetSelect option").count() == 3
    pane.get_by_role("button", name="3 agents", exact=True).click()
    assert pane.locator("#groupTargetSelect option").count() == 4

    # Untapped message routes through all 3 seats sequentially.
    pane.locator("#groupInput").fill("Quick feedback from all three editors.")
    pane.locator("#groupSendBtn").click()
    pane.locator(".group-turn-card.is-critic-3").first.wait_for(timeout=20000)
    assert pane.locator(".group-turn-card.is-critic-1").count() == 1
    assert pane.locator(".group-turn-card.is-critic-2").count() == 1
    assert "Fake Agy reply:" in pane.locator(".group-turn-card.is-critic-3").first.inner_text()

    # Send to Group defaults to 3 participants, allows 2 vs 3 toggle, and exposes Provider + Model + Effort per seat.
    _open_discuss_agent(page, "codex")
    page.fill("#discussInput", "Should Perkins confess on line 17?")
    page.click("#discussSend")
    page.wait_for_selector("#discussGroupFork:not([disabled])", timeout=15000)
    page.locator("#discussGroupFork").click()

    fork_dialog = page.locator("#discussGroupForkDialog")
    fork_dialog.wait_for(state="visible")
    fork_dialog.locator(".group-fork-model").first.wait_for(timeout=15000)
    assert fork_dialog.locator(".group-fork-model").count() == 3
    assert fork_dialog.get_by_role("combobox", name="Third perspective provider").input_value() == "agy"
    model_select = fork_dialog.get_by_role("combobox", name="Third perspective model")
    model_select.locator("option[value='gemini-4-argon']").wait_for(state="attached", timeout=10000)
    model_select.select_option("gemini-4-argon")
    fork_dialog.get_by_role("combobox", name="Third perspective reasoning effort").select_option("high")

    # Toggling 2 -> 3 works without losing selections.
    fork_dialog.get_by_role("button", name="2 agents", exact=True).click()
    assert fork_dialog.locator(".group-fork-model").count() == 2
    fork_dialog.get_by_role("button", name="3 agents", exact=True).click()
    assert fork_dialog.locator(".group-fork-model").count() == 3
    assert fork_dialog.get_by_role("combobox", name="Third perspective reasoning effort").input_value() == "high"

    fork_dialog.locator("#groupForkConfirm").click()
    page.wait_for_function("() => _groupActiveSession?.participants?.length === 3 && _groupActiveSession.participants[2].effort === 'high'")
