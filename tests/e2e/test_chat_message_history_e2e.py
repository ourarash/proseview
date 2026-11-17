"""End-to-end tests for per-group chat message history with Up/Down arrow cycling."""
import pytest

pytest.importorskip("playwright.sync_api")

from .conftest import SCENE_REL
from .test_browser_e2e import open_scene
from .test_highlight_card_e2e import _group_idle

pytestmark = pytest.mark.e2e_browser


def _open_discuss_agent(page, agent: str) -> None:
    page.evaluate("agent => showDiscussAgentTab(agent)", agent)
    page.wait_for_function(
        "agent => window._discussAgent === agent"
        " && !!window._discussConversationId"
        " && !document.querySelector('#discussSend').disabled",
        arg=agent,
    )


def _send_discuss(page, text: str) -> None:
    box = page.locator("#discussInput")
    box.fill(text)
    box.press("Enter")
    page.wait_for_function("() => document.querySelector('#discussInput').value === ''")


def _send_group(page, text: str) -> None:
    box = page.locator("#groupInput")
    box.fill(text)
    box.press("Enter")
    page.wait_for_function("() => document.querySelector('#groupInput').value === ''")


def test_chat_message_history_is_isolated_per_group_and_survives_reload(page, server):
    open_scene(page, server, SCENE_REL)

    # 1. Send two messages in Codex.
    _open_discuss_agent(page, "codex")
    _send_discuss(page, "Codex first message")
    _send_discuss(page, "Codex second message")

    # 2. Send two messages in Claude.
    _open_discuss_agent(page, "claude")
    _send_discuss(page, "Claude first message")
    _send_discuss(page, "Claude second message")

    # 3. Send two messages in the Group.
    page.evaluate("showScenePanelTab('group')")
    _send_group(page, "@StoryEditor Group first message")
    _send_group(page, "@VoiceEditor Group second message")
    _group_idle(page)

    # 4. Verify Group ArrowUp/ArrowDown cycles only Group messages and preserves draft.
    group_input = page.locator("#groupInput")
    group_input.fill("Group unsent draft")
    group_input.press("ArrowUp")
    assert group_input.input_value() == "@VoiceEditor Group second message"
    assert page.locator("#groupMentionMenu").is_hidden()
    assert page.locator("#groupTargetSelect").input_value() == "critic2"

    group_input.press("ArrowUp")
    assert group_input.input_value() == "@StoryEditor Group first message"
    assert page.locator("#groupTargetSelect").input_value() == "critic1"

    # Pressing ArrowUp past the oldest message stays at the oldest message.
    group_input.press("ArrowUp")
    assert group_input.input_value() == "@StoryEditor Group first message"

    group_input.press("ArrowDown")
    assert group_input.input_value() == "@VoiceEditor Group second message"
    group_input.press("ArrowDown")
    assert group_input.input_value() == "Group unsent draft"
    assert not page.locator("#groupTargetSelect").is_disabled()

    # 5. Verify Claude ArrowUp/ArrowDown cycles only Claude messages.
    _open_discuss_agent(page, "claude")
    discuss_input = page.locator("#discussInput")
    discuss_input.fill("Claude draft")
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Claude second message"
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Claude first message"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "Claude second message"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "Claude draft"

    # 6. Verify Codex ArrowUp/ArrowDown cycles only Codex messages.
    _open_discuss_agent(page, "codex")
    discuss_input.fill("")
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Codex second message"
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Codex first message"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "Codex second message"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == ""

    # 7. Persistence across page reload and new conversation / group reset.
    page.reload()
    open_scene(page, server, SCENE_REL)

    _open_discuss_agent(page, "codex")
    page.locator("#discussNewConversation").click()
    page.locator("#discussNewConversationConfirm").click()
    page.wait_for_function("() => document.querySelector('#discussNewConversationDialog').open === false")
    discuss_input = page.locator("#discussInput")
    discuss_input.focus()
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Codex second message"

    _open_discuss_agent(page, "claude")
    discuss_input.focus()
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Claude second message"

    page.evaluate("showScenePanelTab('group')")
    _group_idle(page)
    page.locator("#groupResetBtn").click()
    group_input = page.locator("#groupInput")
    group_input.focus()
    group_input.press("ArrowUp")
    assert group_input.input_value() == "@VoiceEditor Group second message"


def test_chat_history_handles_multiline_wrapped_drafts_edits_and_pickers(page, server):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, "codex")
    discuss_input = page.locator("#discussInput")

    # Send a multiline message and a newer single-line message.
    _send_discuss(page, "Older one")
    _send_discuss(page, "Multi line 1\nMulti line 2")
    _send_discuss(page, "Newest single")

    # Rapid ArrowUp cycling skips smoothly past multiline messages.
    discuss_input.focus()
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Newest single"
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Multi line 1\nMulti line 2"
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Older one"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "Multi line 1\nMulti line 2"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "Newest single"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == ""

    # Editing a recalled message exits history browsing so ArrowDown does not discard edits.
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Newest single"
    discuss_input.press_sequentially(" edited")
    assert discuss_input.input_value() == "Newest single edited"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "Newest single edited"

    # Explicit multiline draft: ArrowUp on line 2 moves to line 1 first, then cycles history on line 1.
    discuss_input.fill("Draft line 1\nDraft line 2")
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Draft line 1\nDraft line 2"
    caret_pos = page.evaluate("() => document.getElementById('discussInput').selectionStart")
    assert caret_pos <= len("Draft line 1")
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "Newest single"
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "Draft line 1\nDraft line 2"

    # Visually wrapped single-paragraph draft: ArrowUp from visual line 2 moves up instead of hijacking.
    wrapped = " ".join(["word"] * 45)
    discuss_input.fill(wrapped)
    end_pos = len(wrapped)
    assert page.evaluate("() => document.getElementById('discussInput').selectionStart") == end_pos
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == wrapped
    assert page.evaluate("() => document.getElementById('discussInput').selectionStart") < end_pos

    # When @ context picker is open, ArrowUp/ArrowDown navigate picker options instead of history.
    discuss_input.fill("@")
    picker = page.locator("#discussContextPicker")
    picker.wait_for(state="visible")
    discuss_input.press("ArrowDown")
    assert discuss_input.input_value() == "@"
    assert picker.is_visible()
