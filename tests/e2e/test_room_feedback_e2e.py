"""Room streaming and connection feedback, using the normal agent transports."""
import pytest

pytest.importorskip("playwright.sync_api")

from .conftest import SCENE_REL
from .test_browser_e2e import _wait_until, open_scene
from .test_highlight_card_e2e import _room_idle

pytestmark = pytest.mark.e2e_browser


def test_room_displays_streamed_markdown_before_the_agent_finishes(page, server):
    with server.hold_codex_request("room-stream") as reached:
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane = page.locator("#sceneRoomPane")
        pane.locator("#roomInput").fill("@Codex what do you think of this scene?")
        pane.locator("#roomSendBtn").click()
        _wait_until(reached.exists)
        draft = pane.locator(".room-live-draft")
        draft.wait_for(state="visible")
        assert draft.inner_text().strip()
        assert pane.locator(".room-turn-card.is-critic-1").count() == 0
    _room_idle(page)
    assert pane.locator(".room-turn-card.is-critic-1").count() == 1
    assert pane.locator(".room-live-draft").count() == 0


def test_room_warns_about_an_unavailable_provider_before_starting_a_preset(page, server):
    unavailable = True
    def availability(route):
        route.fulfill(json={"ok": True, "agents": [
            {"id": "codex", "label": "Codex", "available": True, "reason": ""},
            {"id": "claude", "label": "Claude", "available": not unavailable, "reason": "Claude CLI is not installed. Install Claude to continue." if unavailable else ""}]})
    page.route("**/api/discuss/agents", availability)
    starts = []
    page.on("request", lambda req: starts.append(req) if req.url.endswith('/api/discuss/room-run') and req.post_data_json.get('action') == 'preset' else None)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    chip = pane.locator('.room-model-control > button[data-warning="true"]')
    chip.wait_for()
    assert "Agent unavailable" in chip.inner_text()
    assert "Install Claude" in chip.get_attribute("title")
    pane.locator('.room-starter-card[data-preset="editorial_critique"]').click()
    pane.locator("#roomStartPresetBtn").click()
    error = pane.locator("#roomPresetPreview [role=alert]")
    error.wait_for()
    assert "Claude CLI is not installed" in error.inner_text()
    assert starts == [] and pane.locator(".room-preset-invitation").count() == 0
    unavailable = False
    pane.locator("#roomStartPresetBtn").click()
    _room_idle(page)
    assert len(starts) == 1
    assert pane.locator('.room-model-control > button[data-warning="true"]').count() == 0


@pytest.mark.allow_http_errors("/api/discuss/models")
def test_room_catalogue_warning_is_visible_and_recovers_when_the_picker_is_reopened(page, server):
    failed = True
    def models(route):
        if failed and route.request.post_data_json.get('agent') == 'codex':
            route.fulfill(status=503, json={"ok": False, "error": "Model catalogue temporarily unavailable"})
        else:
            route.continue_()
    page.route("**/api/discuss/models", models)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    chip = page.locator('#sceneRoomPane .room-model-control > button').first
    chip.wait_for()
    page.wait_for_function("() => document.querySelector('.room-model-control > button')?.dataset.warning === 'true'")
    assert "Models unavailable" in chip.inner_text()
    assert "temporarily unavailable" in chip.get_attribute("title")
    assert "Agent unavailable" not in chip.inner_text()
    failed = False
    chip.click()
    page.wait_for_function("() => document.querySelector('.room-model-control > button')?.dataset.warning === 'false'")
    assert "Models unavailable" not in chip.inner_text()
    assert page.locator('.room-model-picker:not([hidden]) [role=radio]').count() > 0
