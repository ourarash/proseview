"""End-to-end browser tests for Send now across Codex, Claude, and Group."""
from __future__ import annotations

import json
from pathlib import Path
import time

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


def _wait_jsonl_entry(path: Path, predicate, timeout: float = 10.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            entries = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if predicate(entries):
                return entries
        time.sleep(0.02)
    raise AssertionError(f"Expected condition in {path} not met before timeout")


def test_codex_queue_and_send_now_button_steers_active_turn(page, server):
    codex_log = server.home / "fake-codex-received.jsonl"
    codex_log.unlink(missing_ok=True)

    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, "codex")

    send_btn = page.locator("#discussSend")
    now_btn = page.locator("#discussSendNow")
    assert send_btn.inner_text().strip() == "Send"
    assert now_btn.is_hidden()

    page.fill("#discussInput", "HOLD_FOR_STOP First turn")
    page.press("#discussInput", "Enter")

    page.wait_for_function("() => document.querySelector('#discussSend').textContent.trim() === 'Queue'")
    assert now_btn.is_visible()

    _wait_jsonl_entry(codex_log, lambda rows: any("turn/start" == row.get("method", "turn/start") for row in rows))

    # Ordinary Enter queues behind active turn.
    page.fill("#discussInput", "Queued behind message")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelector('#discussInput').value === ''")

    # Clicking Send now steers active turn without interrupting it.
    page.fill("#discussInput", "Urgent steer redirection")
    now_btn.click()

    page.wait_for_function("() => document.querySelector('#discussInput').value === ''")
    page.wait_for_function("() => document.querySelector('#discussSend').textContent.trim() === 'Send'")
    assert now_btn.is_hidden()

    records = _wait_jsonl_entry(codex_log, lambda rows: any(r.get("method") == "turn/steer" for r in rows))
    steers = [r for r in records if r.get("method") == "turn/steer"]
    interrupts = [r for r in records if r.get("method") == "turn/interrupt"]
    assert len(steers) == 1
    assert interrupts == [], f"Unexpected interrupts in {[ {k: r.get(k) for k in ('method', 'turnId')} for r in records ]}"
    assert "Urgent steer redirection" in steers[0]["params"]["input"][0]["text"]

    page.wait_for_function(
        "() => document.body.innerText.includes('Urgent steer redirection')"
        " && document.body.innerText.includes('Queued behind message')"
    )


def test_claude_send_now_interrupts_active_turn_and_runs_ahead_of_queue(page, server):
    claude_log = server.home / "fake-claude-received.jsonl"
    claude_log.unlink(missing_ok=True)

    open_scene(page, server, SCENE_REL)
    _open_discuss_agent(page, "claude")

    send_btn = page.locator("#discussSend")
    now_btn = page.locator("#discussSendNow")
    assert send_btn.inner_text().strip() == "Send"
    assert now_btn.is_hidden()

    page.fill("#discussInput", "HOLD_CLAUDE_ONCE First claude turn")
    page.press("#discussInput", "Enter")

    page.wait_for_function("() => document.querySelector('#discussSend').textContent.trim() === 'Queue'")
    assert now_btn.is_visible()

    _wait_jsonl_entry(claude_log, lambda rows: any(r.get("method") == "query" for r in rows))

    page.fill("#discussInput", "Claude queued second")
    page.press("#discussInput", "Enter")
    page.wait_for_function("() => document.querySelector('#discussInput').value === ''")

    # Ctrl+Enter triggers Send now in individual chat too.
    page.fill("#discussInput", "Claude urgent first")
    page.press("#discussInput", "Control+Enter")

    page.wait_for_function("() => document.querySelector('#discussSend').textContent.trim() === 'Send'")
    assert now_btn.is_hidden()

    records = _wait_jsonl_entry(
        claude_log,
        lambda rows: any(r.get("method") == "query" and "Claude queued second" in r.get("prompt", "") for r in rows),
    )
    interrupts = [r for r in records if r.get("method") == "interrupt"]
    queries = [r["prompt"] for r in records if r.get("method") == "query"]
    assert len(interrupts) == 1
    urgent_idx = next(i for i, q in enumerate(queries) if "Claude urgent first" in q)
    queued_idx = next(i for i, q in enumerate(queries) if "Claude queued second" in q)
    assert urgent_idx < queued_idx


def test_group_send_now_steers_codex_and_keeps_claude_turn_queued(page, server):
    codex_log = server.home / "fake-codex-received.jsonl"
    codex_log.unlink(missing_ok=True)

    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")

    send_btn = page.locator("#groupSendBtn")
    now_btn = page.locator("#groupSendNowBtn")
    assert send_btn.inner_text().strip() == "Send"
    assert now_btn.is_hidden()

    page.fill("#groupInput", "@all HOLD_ONCE_FOR_STEER Initial prompt")
    page.press("#groupInput", "Enter")

    page.wait_for_function("() => document.querySelector('#groupSendBtn').textContent.trim() === 'Queue'")
    assert now_btn.is_visible()

    _wait_jsonl_entry(codex_log, lambda rows: "turnId" in rows[0])

    page.fill("#groupInput", "@all Urgent steer direction")
    now_btn.click()

    _group_idle(page)
    assert send_btn.inner_text().strip() == "Send"
    assert now_btn.is_hidden()

    records = _wait_jsonl_entry(codex_log, lambda rows: any(r.get("method") == "turn/steer" for r in rows))
    assert any(r.get("method") == "turn/steer" and "Urgent steer direction" in r["params"]["input"][0]["text"] for r in records)
    assert not any(r.get("method") == "turn/interrupt" for r in records), f"Unexpected interrupt in {[ {k: r.get(k) for k in ('method', 'turnId')} for r in records ]}"

    labels = page.locator(".group-turn-card:not(.is-user) .chat-message-name").all_inner_texts()
    assert len(labels) == 2
    assert "StoryEditor" in labels[0] or "Codex" in labels[0]
    assert "VoiceEditor" in labels[1] or "Claude" in labels[1]


def test_group_send_now_interrupts_codex_to_follow_mention_order_when_claude_tagged_first(page, server):
    codex_log = server.home / "fake-codex-received.jsonl"
    codex_log.unlink(missing_ok=True)

    open_scene(page, server, SCENE_REL)
    page.evaluate("showScenePanelTab('group')")

    page.fill("#groupInput", "@all HOLD_ONCE_FOR_STEER Start codex")
    page.press("#groupInput", "Enter")

    page.wait_for_function("() => document.querySelector('#groupSendBtn').textContent.trim() === 'Queue'")
    _wait_jsonl_entry(codex_log, lambda rows: "turnId" in rows[0])

    page.fill("#groupInput", "@VoiceEditor @StoryEditor respond in mention order")
    page.locator("#groupSendNowBtn").click()

    _group_idle(page)

    records = _wait_jsonl_entry(codex_log, lambda rows: any(r.get("method") == "turn/interrupt" for r in rows))
    assert not any(r.get("method") == "turn/steer" for r in records)

    labels = page.locator(".group-turn-card:not(.is-user) .chat-message-name").all_inner_texts()
    assert len(labels) == 2
    assert "VoiceEditor" in labels[0] or "Claude" in labels[0]
    assert "StoryEditor" in labels[1] or "Codex" in labels[1]
