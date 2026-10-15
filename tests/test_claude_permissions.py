"""Claude asks where the Claude Code extension would, and edits go to the review.

Claude in Prosview loads the writer's settings (user, project, local) and
decides permissions the way the extension does; where it would ask, the
question reaches the writer through ``can_use_tool``. Prosview keeps two rules
of its own at the ``PreToolUse`` hook, which runs before those permissions:

* on a writing turn, every edit goes through Prosview, which keeps the text so
  the writer can review and undo it after the turn;
* on a reading pass, no edit happens at all.

These tests assert those rules, and that nothing else is layered on top.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

import proseview.claude_agent_client as module
from proseview.claude_agent_client import WRITE_TOOLS, ClaudeAgentClient


class _FakeSDKClient:
    def __init__(self, options: Any) -> None:
        self.options = options

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def query(self, prompt: str) -> None:
        return None

    async def interrupt(self) -> None:
        return None

    async def receive_response(self):
        return
        yield  # pragma: no cover - never reached


def _client() -> tuple[ClaudeAgentClient, list[dict]]:
    seen: list[dict] = []
    client = ClaudeAgentClient(
        cwd=".",
        on_message=seen.append,
        options_factory=lambda **opts: opts,
        client_factory=_FakeSDKClient,
    )
    client.start()
    return client, seen


def _run(client: ClaudeAgentClient, coro):
    return asyncio.run_coroutine_threadsafe(coro, client._loop)


def _gate(client: ClaudeAgentClient, thread_id: str, tool: str, tool_input: dict | None = None):
    session = client._sessions[thread_id]
    return _run(client, client._gate_tool(session, {"tool_name": tool, "tool_input": tool_input or {}}))


def _ask(client: ClaudeAgentClient, thread_id: str, tool: str, tool_input: dict | None = None):
    session = client._sessions[thread_id]
    return _run(client, client._permission_prompt(session, tool, tool_input or {}))


def _approvals(seen: list[dict]) -> list[dict]:
    return [m for m in seen if "requestApproval" in m.get("method", "")]


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_a_reading_pass_refuses_every_edit_outright(tool):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client._sessions[thread_id].may_write = False
        decision = _gate(client, thread_id, tool, {"file_path": "manuscript/one.md"}).result(timeout=5)
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert not _approvals(seen)
    finally:
        client.close()


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_a_writing_turn_sends_every_edit_through_prosview(tool):
    """Prosview keeps the text before the edit runs, so the review can undo it."""
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client._sessions[thread_id].may_write = True
        pending = _gate(client, thread_id, tool, {"file_path": "manuscript/one.md"})
        assert _wait_for(lambda: bool(_approvals(seen)))
        request = _approvals(seen)[0]
        assert request["method"] == "item/fileChange/requestApproval"
        client.respond(request["id"], {"decision": "accept"})
        assert pending.result(timeout=5)["hookSpecificOutput"]["permissionDecision"] == "allow"
    finally:
        client.close()


@pytest.mark.parametrize("tool", ["Read", "Grep", "Bash", "WebFetch", "Agent", "mcp__github__create_issue"])
def test_anything_but_an_edit_is_left_to_claudes_own_permissions(tool):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client._sessions[thread_id].may_write = True
        assert _gate(client, thread_id, tool, {"command": "rm -rf manuscript"}).result(timeout=5) == {}
        assert not _approvals(seen)
    finally:
        client.close()


@pytest.mark.parametrize("tool", ["Bash", "WebFetch", "Agent", "mcp__github__create_issue"])
def test_where_claude_would_ask_the_writer_answers(tool):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        pending = _ask(client, thread_id, tool, {"command": "rm -rf manuscript"})
        assert _wait_for(lambda: bool(_approvals(seen))), f"{tool} was not put to the writer"
        request = _approvals(seen)[0]
        assert request["method"] == "item/commandExecution/requestApproval"
        client.respond(request["id"], {"decision": "decline"})
        assert pending.result(timeout=5)["behavior"] == "deny"
    finally:
        client.close()


def test_an_unanswered_question_denies_rather_than_hanging(monkeypatch):
    monkeypatch.setattr(module, "APPROVAL_TIMEOUT", 0.2)
    client, _ = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        assert _ask(client, thread_id, "Bash", {"command": "touch x"}).result(timeout=5)["behavior"] == "deny"
    finally:
        client.close()


def test_no_mode_switches_permission_checks_off():
    client, _ = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        options = client._build_options({}, client._sessions[thread_id])
        assert options.get("permission_mode") not in {"bypassPermissions", "acceptEdits", "dontAsk"}
        assert options["setting_sources"] == ["user", "project", "local"]
        assert callable(options["can_use_tool"])
    finally:
        client.close()


def test_the_real_sdk_receives_its_own_permission_results():
    """The callback answers in the SDK's types, not Prosview's dicts."""
    sdk = pytest.importorskip("claude_agent_sdk")
    client = ClaudeAgentClient(cwd=".", on_message=lambda message: None, client_factory=_FakeSDKClient)
    client.start()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        options = client._build_options({}, client._sessions[thread_id])
        assert isinstance(options, sdk.ClaudeAgentOptions)
        assert options.setting_sources == ["user", "project", "local"]
        verdict = _run(client, options.can_use_tool("StructuredOutput", {}, None)).result(timeout=5)
        assert isinstance(verdict, sdk.PermissionResultAllow)
    finally:
        client.close()
