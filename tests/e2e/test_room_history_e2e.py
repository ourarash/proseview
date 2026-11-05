"""Room threads belong to the book; scene navigation changes message context."""
import pytest

pytest.importorskip("playwright.sync_api")

from .conftest import SCENE_REL
from .test_browser_e2e import _wait_until, open_scene
from .test_highlight_card_e2e import _room_idle

pytestmark = pytest.mark.e2e_browser
SECOND = "ch01/02-walk.md"


def test_room_follows_scene_navigation_and_all_book_history_is_available(page, server):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator("#roomInput").fill("@Codex help with the opening.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    first_id = page.evaluate("_roomActiveSession.id")
    pane.locator("#roomInput").fill("Keep this draft while I look at another scene.")
    open_scene(page, server, SECOND)
    page.evaluate("showScenePanelTab('room')")
    assert page.evaluate("_roomActiveSession.id") == first_id
    assert pane.locator("#roomInput").input_value() == "Keep this draft while I look at another scene."
    assert pane.locator(".discuss-sees").inner_text() == SECOND
    assert pane.locator(".is-user").count() == 1
    pane.locator("#roomInput").fill("@Codex what about this next scene?")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    assert page.evaluate("_roomActiveSession.id") == first_id
    assert page.evaluate("_roomActiveSession.runtime.steps.map(s=>s.scene)") == [SCENE_REL, SECOND]
    page.reload()
    open_scene(page, server, SECOND)
    page.evaluate("showScenePanelTab('room')")
    _room_idle(page)
    assert page.evaluate("_roomActiveSession.id") == first_id
    assert pane.locator(".is-user").count() == 2
    assert "help with the opening" in pane.locator(".room-topic-title").inner_text()
    pane.locator("#roomResetBtn").click()
    pane.locator("#roomInput").fill("@Codex start a different discussion.")
    pane.locator("#roomSendBtn").click()
    _room_idle(page)
    second_id = page.evaluate("_roomActiveSession.id")
    assert first_id != second_id
    pane.locator("#roomHistoryBtn").click()
    entries = pane.locator(".room-history-item")
    _wait_until(lambda: entries.count() == 2)
    assert SCENE_REL in entries.nth(1).inner_text()
    assert SECOND in entries.nth(0).inner_text()
    entries.nth(1).locator(".room-history-open").click()
    page.wait_for_function("id => _roomActiveSession.id === id && _roomActiveSession.turns.length === 4", arg=first_id)
    assert pane.locator(".is-user").count() == 2
    assert pane.locator(".discuss-sees").inner_text() == SECOND


def test_queued_scene_context_survives_navigation_and_reload(page, server):
    with server.hold_codex_request("turn/start") as reached:
        open_scene(page, server, SCENE_REL)
        page.evaluate("showScenePanelTab('room')")
        pane = page.locator("#sceneRoomPane")
        pane.locator("#roomInput").fill("@Codex consider this first scene.")
        pane.locator("#roomSendBtn").click()
        _wait_until(reached.exists)
        first_id = page.evaluate("_roomActiveSession.id")
        open_scene(page, server, SECOND)
        page.evaluate("showScenePanelTab('room')")
        pane.locator("#roomInput").fill("@Codex consider this second scene next.")
        pane.locator("#roomSendBtn").click()
        pane.locator(".room-message-queue").wait_for()
        page.reload()
        open_scene(page, server, SECOND)
        page.evaluate("showScenePanelTab('room')")
        pane.locator(".is-user").first.wait_for()
    _room_idle(page)
    assert page.evaluate("_roomActiveSession.id") == first_id
    assert pane.locator(".is-user").count() == 2
    assert page.evaluate("_roomActiveSession.runtime.steps.map(s=>s.scene)") == [SCENE_REL, SECOND]


@pytest.mark.allow_http_errors("/api/discuss/models")
def test_legacy_room_citations_keep_their_original_scene_when_opened_elsewhere(page, server):
    server.post_json("/api/discuss/room-history", {"action": "save", "session": {
        "id": "older-opening-discussion", "scene": SCENE_REL, "title": "Conversation", "turns": [
            {"role": "user", "text": "Check the old opening."},
            {"role": "critic", "seat": 1, "agent": "codex", "text": "Review line 18."}]}})
    open_scene(page, server, SECOND)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    pane.locator(".is-critic-1").wait_for()
    assert "Check the old opening" in pane.locator(".room-topic-title").inner_text()
    link = pane.locator(".is-critic-1 a").get_attribute("href")
    assert "01-opening.md" in link and "02-walk.md" not in link
    assert pane.locator(".discuss-sees").inner_text() == SECOND


def test_room_auto_targeting_and_at_all_mention(page, server):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    target = pane.locator("#roomTargetSelect")

    # 1. Fresh room: initially target is 'both'
    assert target.input_value() == "both"
    assert not target.is_disabled()

    # 2. Typing @all sets target to 'both' and disables target with hint
    input_box = pane.locator("#roomInput")
    input_box.fill("@all hello editors")
    assert target.input_value() == "both"
    assert target.is_disabled()
    assert "Replies:" in pane.locator("#roomMentionHint").inner_text()

    # 3. Clearing input restores enabled state and 'both'
    input_box.fill("Initial message to both")
    assert not target.is_disabled()
    assert target.input_value() == "both"

    # Send message to both
    pane.locator("#roomSendBtn").click()
    _room_idle(page)

    # 4. Critics have replied. Last critic was seat 2 (Claude)
    # Target now defaults to last replying critic (critic2)
    last_seat = page.evaluate("() => _roomLastCriticSeat(_roomActiveSession)")
    assert last_seat in (1, 2)
    assert target.input_value() == f"critic{last_seat}"
    assert not target.is_disabled()

    # 5. Follow-up message without @all routes to last critic
    input_box.fill("Follow-up question")
    assert page.evaluate("() => roomRequestedSeats(document.getElementById('roomInput').value)") == [last_seat]

    # 6. Typing @all routes to [1, 2]
    input_box.fill("@all what do you both think?")
    assert target.input_value() == "both"
    assert target.is_disabled()
    assert page.evaluate("() => roomRequestedSeats(document.getElementById('roomInput').value)") == [1, 2]


def test_room_target_menu_and_mentions_show_agent_names(page, server):
    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('room')")
    pane = page.locator("#sceneRoomPane")
    target = pane.locator("#roomTargetSelect")
    page.wait_for_selector("#roomTargetSelect option", state="attached")

    # 1. Menu options show agent names (Claude / Codex)
    options = target.locator("option").all_text_contents()
    assert options == [
        "Room (Both: Codex, Claude)",
        "Story Editor (Codex) only",
        "Voice Editor (Claude) only",
    ]

    # 2. Mentioning @all shows both agents in hint
    input_box = pane.locator("#roomInput")
    input_box.fill("@all please check this")
    assert pane.locator("#roomMentionHint").inner_text() == "Replies: Story Editor (Codex), Voice Editor (Claude)"

    # 3. Mentioning a specific editor shows their agent in hint
    input_box.fill("@VoiceEditor check voice")
    assert pane.locator("#roomMentionHint").inner_text() == "Replies: Voice Editor (Claude)"

    input_box.fill("@StoryEditor check story")
    assert pane.locator("#roomMentionHint").inner_text() == "Replies: Story Editor (Codex)"

    input_box.fill("@claude check voice")
    assert pane.locator("#roomMentionHint").inner_text() == "Replies: Voice Editor (Claude)"

    input_box.fill("@codex check story")
    assert pane.locator("#roomMentionHint").inner_text() == "Replies: Story Editor (Codex)"

    # 4. Mention autocomplete menu offers agent handles and shows agent names
    input_box.fill("")
    input_box.focus()
    input_box.press_sequentially("@")
    menu = pane.locator("#roomMentionMenu")
    menu.wait_for()
    option_texts = menu.locator(".room-mention-option").all_text_contents()
    # Check that option names and handles reflect the agent
    assert any("All editors" in t and "Codex" in t and "Claude" in t and "@all" in t for t in option_texts)
    assert any("Story Editor" in t and "Codex" in t and "@StoryEditor" in t for t in option_texts)
    assert any("Voice Editor" in t and "Claude" in t and "@VoiceEditor" in t for t in option_texts)

    # 5. Selecting Voice Editor mention inserts @VoiceEditor and sets target
    voice_btn = menu.locator(".room-mention-option").filter(has_text="Voice Editor").first
    voice_btn.click()
    assert input_box.input_value().strip() == "@VoiceEditor"
    assert target.input_value() == "critic2"
    assert pane.locator("#roomMentionHint").inner_text() == "Replies: Voice Editor (Claude)"

