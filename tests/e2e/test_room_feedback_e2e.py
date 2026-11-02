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
