"""Group streaming and connection feedback, using the normal agent transports."""
import json
import pytest

pytest.importorskip("playwright.sync_api")

from .conftest import SCENE_REL
from .test_browser_e2e import _wait_until, open_scene
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def test_group_displays_streamed_markdown_before_the_agent_finishes(page, server):
    with server.hold_codex_request("group-stream") as reached:
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('group')")
        pane = page.locator("#sceneGroupPane")
        pane.locator("#groupInput").fill("@Codex what do you think of this scene?")
        pane.locator("#groupSendBtn").click()
        _wait_until(reached.exists)
        draft = pane.locator(".group-live-draft")
        draft.wait_for(state="visible")
        assert draft.inner_text().strip()
        assert pane.locator(".group-turn-card.is-critic-1").count() == 0
    _group_idle(page)
    assert pane.locator(".group-turn-card.is-critic-1").count() == 1
    assert pane.locator(".group-live-draft").count() == 0


def test_group_warns_about_an_unavailable_provider_before_starting_a_preset(page, server):
    unavailable = True
    def availability(route):
        route.fulfill(json={"ok": True, "agents": [
            {"id": "codex", "label": "Codex", "available": True, "reason": ""},
            {"id": "claude", "label": "Claude", "available": not unavailable, "reason": "Claude CLI is not installed. Install Claude to continue." if unavailable else ""}]})
    page.route("**/api/discuss/agents", availability)
    starts = []
    page.on("request", lambda req: starts.append(req) if req.url.endswith('/api/discuss/group-run') and req.post_data_json.get('action') == 'preset' else None)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane = page.locator("#sceneGroupPane")
    chip = pane.locator('.group-model-control > button[data-warning="true"]')
    chip.wait_for()
    assert "Agent unavailable" in chip.inner_text()
    assert "Install Claude" in chip.get_attribute("title")
    pane.locator('.group-starter-card[data-preset="editorial_critique"]').click()
    pane.locator("#groupStartPresetBtn").click()
    error = pane.locator("#groupPresetPreview [role=alert]")
    error.wait_for()
    assert "Claude CLI is not installed" in error.inner_text()
    assert starts == [] and pane.locator(".group-preset-invitation").count() == 0
    unavailable = False
    pane.locator("#groupStartPresetBtn").click()
    _group_idle(page)
    assert len(starts) == 1
    assert pane.locator('.group-model-control > button[data-warning="true"]').count() == 0


@pytest.mark.allow_http_errors("/api/discuss/models")
def test_group_catalogue_warning_is_visible_and_recovers_when_the_picker_is_reopened(page, server):
    failed = True
    def models(route):
        if failed and route.request.post_data_json.get('agent') == 'codex':
            route.fulfill(status=503, json={"ok": False, "error": "Model catalogue temporarily unavailable"})
        else:
            route.continue_()
    page.route("**/api/discuss/models", models)
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    chip = page.locator('#sceneGroupPane .group-model-control > button').first
    chip.wait_for()
    page.wait_for_function("() => document.querySelector('.group-model-control > button')?.dataset.warning === 'true'")
    assert "Models unavailable" in chip.inner_text()
    assert "temporarily unavailable" in chip.get_attribute("title")
    assert "Agent unavailable" not in chip.inner_text()
    failed = False
    chip.click()
    page.wait_for_function("() => document.querySelector('.group-model-control > button')?.dataset.warning === 'false'")
    assert "Models unavailable" not in chip.inner_text()
    assert page.locator('.group-model-picker:not([hidden]) [role=radio]').count() > 0


def test_group_switching_history_ignores_a_late_poll_response(page, server):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")
    pane = page.locator("#sceneGroupPane")
    pane.locator("#groupInput").fill("@Codex first saved discussion.")
    pane.locator("#groupSendBtn").click()
    _group_idle(page)
    first = page.evaluate("_groupSessionFor(_groupCurrentScenePath()).id")
    pane.locator("#groupResetBtn").click()
    pane.locator("#groupInput").fill("@Codex second saved discussion.")
    pane.locator("#groupSendBtn").click()
    _group_idle(page)
    second = page.evaluate("_groupSessionFor(_groupCurrentScenePath()).id")
    held = []
    def delay_poll(route):
        body = route.request.post_data_json
        if not held and body.get('action') == 'state' and body.get('group_id') == first and 'after_revision' in body:
            # A changed server revision returns a full projection, not just a
            # compact unchanged response. Hold it across a history switch.
            body.pop('after_revision')
            response = route.fetch(post_data=json.dumps(body))
            held.append((route, response.body()))
        else:
            route.continue_()
    page.route("**/api/discuss/group-run", delay_poll)
    page.evaluate("id => openGroupHistorySession(_groupCurrentScenePath(), id)", first)
    def poll_is_held():
        page.evaluate("0")
        return bool(held)
    _wait_until(poll_is_held)
    page.evaluate("id => openGroupHistorySession(_groupCurrentScenePath(), id)", second)
    assert page.evaluate("_groupSessionFor(_groupCurrentScenePath()).id") == second
    held[0][0].fulfill(status=200, body=held[0][1], content_type="application/json")
    page.wait_for_function("id => !_groupRuntimePolls[id]", arg=first)
    assert page.evaluate("_groupSessionFor(_groupCurrentScenePath()).id") == second
    assert "second saved discussion" in pane.locator('.is-user').inner_text()
