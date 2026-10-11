"""The Claude session must stay read-only unless the writer says otherwise.

Codex guarantees this with one protocol field —
``sandboxPolicy: {readOnly, networkAccess: false}``. Claude has no equivalent
single switch, so the same property is *composed* from an explicit tool
allowlist, a refusal to load ambient configuration, and a ``PreToolUse`` gate.
Composed properties rot silently: a new built-in tool, a changed default, or a
stray settings source can widen the sandbox without any code here changing.

These tests exist to make that rot loud. They assert the property itself — no
tool that can modify anything runs without the writer being asked — rather than
the current spelling of the options dict.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

import proseview.claude_agent_client as module
from proseview.claude_agent_client import READ_ONLY_TOOLS, ClaudeAgentClient

# Tools that can change something, reach the network, or run arbitrary code.
# "Someday__NewTool" stands in for a tool that does not exist yet: the gate must
# treat anything it does not recognise as needing permission.
MUTATING_TOOLS = [
    "Bash",
    "Write",
    "Edit",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
    "Task",
    "mcp__github__create_issue",
    "Someday__NewTool",
]


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


def _gate(client: ClaudeAgentClient, thread_id: str, tool: str, tool_input: dict | None = None):
    session = client._sessions[thread_id]
    return asyncio.run_coroutine_threadsafe(
        client._gate_tool(session, {"tool_name": tool, "tool_input": tool_input or {"command": "x"}}),
        client._loop,
    )


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize("tool", MUTATING_TOOLS)
def test_no_mutating_tool_runs_without_asking_the_writer(tool):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        # On a turn that may write, an edit still stops at the writer.
        client._sessions[thread_id].may_write = True
        pending = _gate(client, thread_id, tool)
        assert _wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen)), (
            f"{tool} ran without reaching the approval gate"
        )
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        client.respond(request["id"], {"decision": "decline"})
        decision = pending.result(timeout=5)
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    finally:
        client.close()


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
def test_a_reading_turn_refuses_every_editing_tool_outright(tool):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client._sessions[thread_id].may_write = False
        decision = _gate(client, thread_id, tool).result(timeout=5)
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert not [m for m in seen if "requestApproval" in m.get("method", "")]
    finally:
        client.close()


@pytest.mark.parametrize("tool", READ_ONLY_TOOLS)
def test_read_only_tools_run_without_interrupting_the_writer(tool):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        decision = _gate(client, thread_id, tool).result(timeout=5)
        assert decision["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert not [m for m in seen if "requestApproval" in m.get("method", "")]
    finally:
        client.close()


def test_read_only_allowlist_contains_nothing_that_can_write():
    """A regression alarm for the allowlist itself."""
    forbidden = {"Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"}
    assert not forbidden.intersection(READ_ONLY_TOOLS)


def test_an_unanswered_request_denies_rather_than_hanging(monkeypatch):
    monkeypatch.setattr(module, "APPROVAL_TIMEOUT", 0.2)
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        pending = _gate(client, thread_id, "Bash")
        decision = pending.result(timeout=5)
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    finally:
        client.close()


def test_session_options_cannot_inherit_ambient_permission_rules():
    client, _ = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        options = client._build_options({}, client._sessions[thread_id])
        # Ambient config is what would let a writer's settings file grant a tool
        # behind Prosview's back, so it must stay switched off.
        assert options["setting_sources"] is None
        assert options["strict_mcp_config"] is True
        assert options["mcp_servers"] == {}
        # These modes bypass permission checks entirely.
        assert options["permission_mode"] not in {"bypassPermissions", "acceptEdits", "dontAsk"}
        # Reading tools, the editing ones every turn gates for itself, a
        # shell whose every non-reading command asks, and the web and helper
        # agents, which always ask.
        assert set(options["tools"]) == set(READ_ONLY_TOOLS) | {
            "Write", "Edit", "NotebookEdit", "Bash", "WebSearch", "WebFetch", "Task",
        }
    finally:
        client.close()


def test_every_allowed_tool_is_explicit():
    """An empty or absent allowlist would mean "all tools", not "no tools"."""
    client, _ = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        options = client._build_options({}, client._sessions[thread_id])
        assert isinstance(options["tools"], list)
        assert options["tools"], "an empty tools list would not restrict anything"
    finally:
        client.close()


@pytest.mark.parametrize("command", [
    "git log --oneline -- manuscript/ch01/01-opening.md",
    "git show HEAD~3:manuscript/ch01/01-opening.md",
    "git log -p manuscript | head -200",
    "rg -n 'tea party' manuscript && wc -w manuscript/ch01/*.md",
    "git -C . log --follow --oneline -- manuscript/ch01/01-opening.md",
])
def test_a_reading_command_runs_without_asking(command):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        decision = _gate(client, thread_id, "Bash", {"command": command}).result(timeout=5)
        assert decision["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert not [m for m in seen if "requestApproval" in m.get("method", "")]
    finally:
        client.close()


@pytest.mark.parametrize("command", [
    "rm -rf manuscript",
    "git commit -am x",
    "git checkout -- manuscript",
    "git log > history.txt",
    "cat a.md; rm b.md",
    "find . -name '*.md' -delete",
    "echo $(rm x)",
    "git diff --output=x",
    "sed -i s/a/b/ f.md",
    "X=1 cat a.md",
    "python3 -c 'print(1)'",
    "git -C / log",
])
def test_any_other_command_still_asks(command):
    client, seen = _client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        pending = _gate(client, thread_id, "Bash", {"command": command})
        assert _wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen)), command
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        client.respond(request["id"], {"decision": "decline"})
        assert pending.result(timeout=5)["hookSpecificOutput"]["permissionDecision"] == "deny"
    finally:
        client.close()
