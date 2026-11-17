"""End-to-end browser tests for /btw side questions (Codex & Claude right split + tabs)."""
from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

pytest.importorskip("playwright.sync_api")

from .conftest import SCENE_REL
from .test_browser_e2e import open_scene, wait_for_settled_answers

pytestmark = pytest.mark.e2e_browser


def _open_discuss_agent(page, agent: str) -> None:
    page.evaluate("agent => showDiscussAgentTab(agent)", agent)
    page.wait_for_function(
        "agent => window._discussAgent === agent"
        " && !!window._discussConversationId"
        " && window._discussSnapshot?.agent === agent"
        " && window._discussSnapshot?.conversation_id === window._discussConversationId"
        " && document.querySelector('#discussConnection').innerText.startsWith('Live')"
        " && !document.querySelector('#discussSend').disabled",
        arg=agent,
    )


def _wait_jsonl(path: Path, predicate, timeout: float = 10.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if predicate(rows):
                return rows
        time.sleep(0.02)
    raise AssertionError(f"Expected condition in {path} not met before timeout")


def test_btw_typing_indicator_parallel_tabs_resize_history_exclusion_and_esc_in_codex(page, server):
    codex_log = server.home / "fake-codex-received.jsonl"
    codex_log.unlink(missing_ok=True)

    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, "codex")

    # 1. Run one completed turn so the parent Codex thread is persisted.
    page.fill("#discussInput", "Warmup main question")
    page.press("#discussInput", "Enter")
    page.wait_for_function(
        "() => document.querySelector('#discussLog').querySelectorAll('.chat-message-card:not(.user)').length >= 1"
        " && document.querySelector('#discussStop').hidden"
        " && document.querySelector('#discussSend').textContent.trim() === 'Send'"
        " && !document.querySelector('#discussSend').disabled"
    )

    # 2. Start a held main turn so Codex is actively busy.
    page.fill("#discussInput", "HOLD_FOR_STOP Long running main turn")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelector('#discussSend').textContent.trim() === 'Queue'")
    assert page.locator("#discussSendNow").is_visible()

    # 3. Typing "/btw ..." shows subtle indicator without opening split yet.
    page.fill("#discussInput", "/btw Check character age in ch01")
    assert page.locator("#discussBtwHint").is_visible()
    assert page.locator("#discussSend").inner_text().strip() == "Ask /btw"
    assert page.locator("#discussSendNow").is_hidden()
    assert page.locator("#btwSplitPane").is_hidden()

    # 4. Pressing Enter opens right-hand split pane immediately even while main is busy.
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => !document.querySelector('#btwSplitPane').hidden")
    page.wait_for_function("() => document.querySelector('#discussInput').value === ''")

    # Composer returns to Queue / Send now right away for the busy main chat.
    assert page.locator("#discussBtwHint").is_hidden()
    assert page.locator("#discussSend").inner_text().strip() == "Queue"
    assert page.locator("#discussSendNow").is_visible()

    # Verify side pane is positioned to the RIGHT of the main .discuss-shell.
    geometry = page.evaluate("""() => {
        const shell = document.querySelector('#discussPanel .discuss-shell').getBoundingClientRect();
        const split = document.querySelector('#btwSplitPane').getBoundingClientRect();
        return {shellRight: shell.right, splitLeft: split.left, splitWidth: split.width};
    }""")
    assert geometry["splitLeft"] >= geometry["shellRight"] - 1

    # Wait for first side tab to complete while main turn stays active.
    page.wait_for_function("() => document.querySelector('.btw-tab')?.dataset.status === 'completed'")
    assert "Forked side branch" in page.locator("#btwTabPanel").inner_text()
    assert page.locator("#discussStop").is_visible()

    # 5. Ask a second /btw -> opens as a separate second tab in the right split.
    page.fill("#discussInput", "/btw Second side check")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelectorAll('.btw-tab').length === 2")
    page.wait_for_function(
        "() => document.querySelectorAll('.btw-tab')[1].dataset.status === 'completed'"
    )

    # Switch back to tab 1 and verify its distinct question stays intact.
    page.locator(".btw-tab-select").nth(0).click()
    assert "Check character age in ch01" in page.locator(".btw-question-text").first.inner_text()

    # Ask a follow-up directly using the separate #btwInput chat box inside the /btw pane.
    page.fill("#btwInput", "Follow-up from side box")
    page.press("#btwInput", "Enter")
    page.wait_for_function("() => document.querySelectorAll('#btwTabPanel .btw-exchange').length === 2")
    page.wait_for_function("() => document.querySelectorAll('.btw-tab')[0].dataset.status === 'completed'")

    # 6. Verify /btw prompts stayed OUT of Up/Down cursor history.
    discuss_input = page.locator("#discussInput")
    discuss_input.fill("")
    discuss_input.press("ArrowUp")
    assert discuss_input.input_value() == "HOLD_FOR_STOP Long running main turn"
    discuss_input.fill("")

    # 7. Drag #discussResizeHandle right to make the main chat window narrower,
    #    and drag #btwResizeHandle left to widen the /btw pane.
    main_before = page.locator("#discussPanel .discuss-shell").bounding_box()["width"]
    outer_box = page.locator("#discussResizeHandle").bounding_box()
    ocx = outer_box["x"] + outer_box["width"] / 2
    ocy = outer_box["y"] + outer_box["height"] / 2
    page.mouse.move(ocx, ocy)
    page.mouse.down()
    page.mouse.move(ocx + 70, ocy, steps=5)
    page.mouse.up()
    main_after = page.locator("#discussPanel .discuss-shell").bounding_box()["width"]
    assert main_after < main_before - 35

    before_width = page.locator("#btwSplitPane").bounding_box()["width"]
    handle_box = page.locator("#btwResizeHandle").bounding_box()
    cx = handle_box["x"] + handle_box["width"] / 2
    cy = handle_box["y"] + handle_box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx - 60, cy, steps=5)
    page.mouse.up()
    after_width = page.locator("#btwSplitPane").bounding_box()["width"]
    assert after_width > before_width + 20

    # Open a blank tab with "+ New" and submit from #btwInput.
    page.locator("#btwNewTabBtn").click()
    page.wait_for_function("() => document.querySelectorAll('.btw-tab').length === 3")
    page.fill("#btwInput", "Third tab from side composer")
    page.press("#btwInput", "Enter")
    page.wait_for_function("() => document.querySelectorAll('.btw-tab')[2].dataset.status === 'completed'")

    # 8. Verify thread/fork logged on Codex without interrupting the main turn.
    records = _wait_jsonl(codex_log, lambda rows: any(r.get("method") == "thread/fork" for r in rows))
    forks = [r for r in records if r.get("method") == "thread/fork"]
    assert len(forks) >= 1
    assert forks[0]["params"]["ephemeral"] is True
    assert forks[0]["params"]["sandbox"] == "workspace-write"
    assert not any(r.get("method") == "turn/interrupt" for r in records)

    # 9. Dismiss tab 3 with Esc, then close remaining tabs.
    page.locator("#btwInput").focus()
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.querySelectorAll('.btw-tab').length === 2")
    assert page.locator("#btwSplitPane").is_visible()

    page.locator(".btw-tab-close").first.click()
    page.locator(".btw-tab-close").first.click()
    page.wait_for_function("() => document.querySelector('#btwSplitPane').hidden")
    assert page.locator("#discussLog").inner_text().find("Check character age") == -1


def test_btw_fallback_when_no_parent_thread_and_claude_fork_plus_group_exclusion(page, server):
    claude_log = server.home / "fake-claude-received.jsonl"
    claude_log.unlink(missing_ok=True)

    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, "codex")

    # No prior Codex turn yet -> falls back seamlessly to seeded ephemeral thread/start.
    page.fill("#discussInput", "/btw Quick check without prior thread")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelector('.btw-tab')?.dataset.status === 'completed'")
    assert "Seeded side session" in page.locator("#btwTabPanel").inner_text()
    page.locator("#btwCloseAll").click()
    page.wait_for_function("() => document.querySelector('#btwSplitPane').hidden")

    # Switch to Claude, run one main turn so parent thread is persisted, then run /btw.
    _open_discuss_agent(page, "claude")
    page.fill("#discussInput", "Claude warmup turn")
    page.press("#discussInput", "Enter")
    wait_for_settled_answers(page, 1)

    page.fill("#discussInput", "/btw Check Claude side answer")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelector('.btw-tab')?.dataset.status === 'completed'")
    assert "Forked side branch" in page.locator("#btwTabPanel").inner_text()

    claude_rows = _wait_jsonl(claude_log, lambda rows: any(r.get("fork_session") for r in rows))
    forked_query = next(r for r in claude_rows if r.get("fork_session"))
    assert forked_query["ephemeral"] is True
    assert {"Read", "Grep", "Glob", "Edit", "Write"}.issubset(set(forked_query["tools"]))

    # Switching to Group hides /btw split, and /btw is excluded from Group.
    page.evaluate("showScenePanelTab('group')")
    assert page.locator("#btwSplitPane").is_hidden()
    page.fill("#groupInput", "/btw Should not open side split")
    assert page.locator("#discussBtwHint").is_hidden()

    # Returning to Codex and pressing Enter on bare "/btw " opens a blank tab
    # in #btwSplitPane and moves focus into #btwInput.
    _open_discuss_agent(page, "codex")
    page.fill("#discussInput", "/btw Question before reload")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelectorAll('.btw-tab').length === 1 && document.querySelector('.btw-tab')?.dataset.status === 'completed'")
    for idx in range(5):
        page.fill("#btwInput", f"Long follow-up {idx} " + ("detail " * 25))
        page.press("#btwInput", "Enter")
        expected = idx + 2
        page.wait_for_function(
            f"() => document.querySelectorAll('#btwTabPanel .btw-exchange').length === {expected} && document.querySelector('.btw-tab')?.dataset.status === 'completed'"
        )

    page.fill("#discussInput", "/btw ")
    assert page.locator("#discussSend").inner_text().strip() == "Open /btw"
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => !document.querySelector('#btwSplitPane').hidden && document.querySelectorAll('.btw-tab').length === 2")
    assert page.locator("#discussInput").input_value() == ""
    assert page.evaluate("() => document.activeElement?.id") == "btwInput"
    assert page.locator("#btwTabPanel .btw-empty-hint").is_visible()
    page.fill("#btwInput", "unsent draft across refresh")

    # Scroll tab 1 to a specific non-zero offset and make it active before reloading.
    page.locator(".btw-tab-select").first.click()
    saved_scroll = page.evaluate("""() => {
        const panel = document.querySelector('#btwTabPanel');
        const target = Math.max(80, Math.floor((panel.scrollHeight - panel.clientHeight) * 0.45));
        panel.scrollTop = target;
        panel.dispatchEvent(new Event('scroll'));
        return panel.scrollTop;
    }""")
    assert saved_scroll >= 80
    page.wait_for_timeout(250)

    # Reloading the page preserves all open /btw tabs, scroll position, exchanges, and draft.
    page.reload()
    page.wait_for_function(
        "() => !document.querySelector('#btwSplitPane')?.hidden && document.querySelectorAll('.btw-tab').length === 2"
    )
    page.wait_for_function(
        f"() => Math.abs(document.querySelector('#btwTabPanel').scrollTop - {saved_scroll}) <= 4"
    )
    assert "Question before reload" in page.locator("#btwTabPanel").inner_text()
    assert "Fake answer for turn-" in page.locator("#btwTabPanel").inner_text()
    page.locator(".btw-tab-select").nth(1).click()
    assert page.locator("#btwInput").input_value() == "unsent draft across refresh"


def test_closing_a_running_btw_tab_cancels_its_backend_turn(page, server):
    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, "codex")
    page.fill("#discussInput", "/btw HOLD_FOR_STOP Wait for cancellation")
    page.press("#discussInput", "Enter")
    page.wait_for_function(
        "() => _btwState(_discussConversationId)?.tabs[0]?.exchanges[0]?.sideQuestionId"
        " && document.querySelector('.btw-tab')?.dataset.status === 'running'"
    )
    with page.expect_response(
        lambda response: "/side-questions/" in response.url and response.url.endswith("/stop")
    ) as cancelled:
        page.locator(".btw-tab-close").click()
    assert cancelled.value.status == 200
    assert cancelled.value.json()["stopped"] is True
    assert page.locator("#btwSplitPane").is_hidden()
