from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from proseview.claude_agent_client import (
    APPROVAL_DECISIONS,
    ClaudeAgentClient,
    LOGIN_COMMAND,
    LOGIN_EXPIRED,
    ClaudeRequestError,
    ClaudeUnavailableError,
    claude_logged_in,
    open_login_terminal,
    sanitize_claude_message,
)


# --- fakes standing in for the SDK -----------------------------------------
#
# These deliberately carry the SDK's own class names. The transport identifies
# messages by ``type(message).__name__`` so it never has to import the SDK, so
# a fake named anything else is silently ignored and its test passes vacuously.
# Do not rename them to Fake*.

@dataclass
class TextBlock:
    text: str


@dataclass
class ThinkingBlock:
    thinking: str = "internal reasoning"


@dataclass
class ToolUseBlock:
    name: str
    input: dict
    id: str = "tool-1"


@dataclass
class AssistantMessage:
    content: list
    session_id: str = "sess-1"
    uuid: str = "msg-1"
    error: str | None = None


@dataclass
class ResultMessage:
    subtype: str = "success"
    terminal_reason: str | None = None
    is_error: bool = False
    errors: list = field(default_factory=list)
    session_id: str = "sess-1"
    result: str = ""
    api_error_status: int | None = None


class FakeSDKClient:
    """Minimal ClaudeSDKClient: replays a scripted message stream per turn."""

    def __init__(self, options: Any) -> None:
        self.options = options
        self.connected = False
        self.queries: list[str] = []
        self.interrupted = 0
        self.script: list[Any] = [ResultMessage()]
        self.models: list[str | None] = []
        self.hold = None

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def query(self, prompt: str) -> None:
        self.queries.append(prompt)

    async def interrupt(self) -> None:
        self.interrupted += 1

    async def set_model(self, model: str | None = None) -> None:
        self.models.append(model)

    async def receive_response(self):
        for message in self.script:
            if self.hold is not None:
                await self.hold.wait()
            yield message


def make_client(script: list | None = None, **kwargs: Any) -> tuple[ClaudeAgentClient, list, list]:
    """Build a client wired to fakes, collecting notifications it emits.

    ``script`` is applied at construction: the drain starts as soon as a turn
    does, so setting it afterwards races the turn it is meant to describe.

    A ``session_reader`` is always supplied, defaulting to an empty store. The
    SDK is an optional dependency, so a test that falls through to the real one
    passes wherever it happens to be installed and fails in CI, where it is not.
    """
    kwargs.setdefault("session_reader", lambda session_id, cwd: [])
    seen: list[dict] = []
    made: list[FakeSDKClient] = []

    def client_factory(options: Any) -> FakeSDKClient:
        fake = FakeSDKClient(options)
        if script is not None:
            fake.script = list(script)
        made.append(fake)
        return fake

    client = ClaudeAgentClient(
        cwd=".",
        on_message=seen.append,
        options_factory=lambda **opts: opts,
        client_factory=client_factory,
        **kwargs,
    )
    client.capabilities = {"approval_decisions": {}}
    client.start()
    return client, seen, made


@pytest.fixture(autouse=True)
def isolated_claude_settings(tmp_path, monkeypatch):
    """Keep the developer's own Claude settings out of these assertions.

    The transport reads the model and effort keys from the writer's settings
    file, so a machine that has configured Opus would otherwise see different
    options than a machine that has not.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- translator -------------------------------------------------------------

def test_translator_drops_raw_thinking():
    assert sanitize_claude_message({"method": "assistant/thinkingDelta", "params": {}}) == []


def test_translator_emits_prosview_vocabulary():
    events = sanitize_claude_message({
        "method": "assistant/message",
        "params": {"threadId": "t1", "turnId": "u1", "text": "hello"},
    })
    assert events == [{
        "type": "response.completed",
        "thread_id": "t1",
        "turn_id": "u1",
        "item_id": None,
        "phase": "final_answer",
        "text": "hello",
    }]


def test_translator_maps_bash_to_command_activity():
    events = sanitize_claude_message({
        "method": "tool/started",
        "params": {"threadId": "t1", "turnId": "u1", "tool": "Bash", "command": "ls", "itemId": "i1"},
    })
    assert events[0]["type"] == "activity.updated"
    assert events[0]["activity"]["kind"] == "commandExecution"
    assert events[0]["activity"]["command"] == "ls"


def test_translator_maps_write_to_file_change():
    events = sanitize_claude_message({
        "method": "tool/started",
        "params": {"tool": "Write", "changes": [{"path": "a.md", "kind": "modify"}]},
    })
    assert events[0]["activity"]["kind"] == "fileChange"
    assert events[0]["activity"]["changes"] == [{"path": "a.md", "kind": "modify"}]


def test_a_read_or_search_keeps_what_it_looked_at():
    """Claude's Read and Grep name a file and a pattern; the step shows them."""
    read = sanitize_claude_message({
        "method": "tool/started",
        "params": {"tool": "Read", "itemId": "r1", "path": "manuscript/ch01/01.md"},
    })[0]["activity"]
    grep = sanitize_claude_message({
        "method": "tool/started",
        "params": {"tool": "Grep", "itemId": "g1", "pattern": "Hatter", "path": "manuscript"},
    })[0]["activity"]
    assert (read["tool"], read["path"]) == ("Read", "manuscript/ch01/01.md")
    assert (grep["tool"], grep["pattern"], grep["path"]) == ("Grep", "Hatter", "manuscript")


def test_a_completion_does_not_relabel_the_tool_it_finished():
    """A completion knows the outcome, not the tool.

    Deriving a kind from the empty name it carries turned a finished command
    into a dynamic tool call and threw the command away with it.
    """
    events = sanitize_claude_message({
        "method": "tool/completed",
        "params": {"threadId": "t1", "turnId": "u1", "itemId": "i1", "tool": "", "status": "completed"},
    })
    activity = events[0]["activity"]
    assert activity["status"] == "completed"
    assert "kind" not in activity
    assert "command" not in activity


def test_thinking_reports_life_without_reporting_the_thought():
    """Claude was mute from Send to answer: thinking is dropped and nothing
    replaced it. A fixed heartbeat says work is happening and nothing else."""
    client, seen, _made = make_client(script=[
        AssistantMessage(content=[ThinkingBlock("the butler did it")]),
        AssistantMessage(content=[TextBlock("an answer")]),
        ResultMessage(),
    ])
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "who?"}]})
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        progress = [m for m in seen if m["method"] == "assistant/progress"]
        assert [m["params"]["text"] for m in progress] == ["Thinking\n"]
        assert "butler" not in json.dumps(seen)
    finally:
        client.close()


def test_translator_ignores_unknown_methods():
    assert sanitize_claude_message({"method": "something/else", "params": {}}) == []


# --- session pool -----------------------------------------------------------

def test_thread_start_creates_distinct_sessions():
    client, _, _ = make_client()
    try:
        first = client.request("thread/start", {})["thread"]["id"]
        second = client.request("thread/start", {})["thread"]["id"]
        assert first != second
        assert len(client._sessions) == 2
    finally:
        client.close()


def test_pool_evicts_least_recently_used_idle_session():
    client, _, _ = make_client()
    try:
        client.max_sessions = 2
        ids = [client.request("thread/start", {})["thread"]["id"] for _ in range(4)]
        assert len(client._sessions) <= 2
        # The survivors are the most recent ones.
        assert ids[-1] in client._sessions
    finally:
        client.close()


def test_turn_start_on_unknown_thread_reports_not_found():
    client, _, _ = make_client()
    try:
        with pytest.raises(ClaudeRequestError) as excinfo:
            client.request("turn/start", {"threadId": "missing", "input": [{"type": "text", "text": "hi"}]})
        assert excinfo.value.code == -32004
    finally:
        client.close()


def test_unknown_method_is_method_not_found():
    client, _, _ = make_client()
    try:
        with pytest.raises(ClaudeRequestError) as excinfo:
            client.request("thread/fork", {})
        assert excinfo.value.code == -32601
    finally:
        client.close()


# --- turn execution ---------------------------------------------------------

def test_turn_streams_message_and_completes():
    client, seen, made = make_client(script=[
        AssistantMessage(content=[TextBlock("an answer")]),
        ResultMessage(),
    ])
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        result = client.request(
            "turn/start",
            {"threadId": thread_id, "input": [{"type": "text", "text": "question"}]},
        )
        turn_id = result["turn"]["id"]
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        methods = [m["method"] for m in seen]
        assert "turn/started" in methods
        assert made[0].queries == ["question"]
        answers = [m["params"]["text"] for m in seen if m["method"] == "assistant/message"]
        assert answers == ["an answer"]
        completed = next(m for m in seen if m["method"] == "turn/completed")
        assert completed["params"]["turnId"] == turn_id
        assert completed["params"]["status"] == "completed"
    finally:
        client.close()


def test_empty_turn_input_is_rejected():
    client, _, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        with pytest.raises(ClaudeRequestError):
            client.request("turn/start", {"threadId": thread_id, "input": []})
    finally:
        client.close()


@pytest.mark.parametrize(
    "message,expected_status",
    [
        (ResultMessage(), "completed"),
        (ResultMessage(subtype="error_during_execution", terminal_reason="aborted_streaming"), "interrupted"),
        (ResultMessage(subtype="error_during_execution", is_error=True, errors=["boom"]), "failed"),
    ],
)
def test_turn_outcome_classification(message, expected_status):
    """An interrupted turn must not be reported as a failure.

    The SDK terminates an interrupted turn with error_during_execution, so
    reading only the subtype would surface every writer Stop as an error.
    """
    status, _ = ClaudeAgentClient._turn_outcome(message)
    assert status == expected_status


OUT_OF_CREDITS = (
    "You're out of usage credits. Switch to another model, or manage usage credits at "
    "https://claude.ai/settings/usage?from=cc_cli_limit_message, to continue."
)


@pytest.mark.parametrize(
    "message,reason",
    [
        # Exactly what Claude Code sent for an exhausted plan: an error whose
        # subtype says "success", the reason in ``result``, and no ``errors``.
        (ResultMessage(subtype="success", is_error=True, terminal_reason="api_error",
                       result=OUT_OF_CREDITS, api_error_status=429), OUT_OF_CREDITS),
        (ResultMessage(subtype="error_during_execution", is_error=True, errors=["boom", "bang"]), "boom; bang"),
        (ResultMessage(subtype="error_max_turns", is_error=True), "error_max_turns"),
        (ResultMessage(subtype="success", is_error=True, api_error_status=503),
         "Claude's service answered with an error (HTTP 503)."),
        (ResultMessage(subtype="success", is_error=True), "Claude stopped with an error and gave no reason."),
    ],
)
def test_a_failed_turn_says_why_it_failed(message, reason):
    """The reason under "Claude could not finish" once read "success".

    The dock showed the subtype whenever ``errors`` was empty, and for an
    exhausted plan the subtype is "success". The writer needs the reason.
    """
    status, detail = ClaudeAgentClient._turn_outcome(message)
    assert status == "failed"
    assert detail == reason


EXPIRED_LOGIN = "Failed to authenticate: OAuth session expired and could not be refreshed"


@pytest.mark.parametrize("error", ["authentication_failed", "unknown"])
def test_an_expired_login_says_how_to_log_in_again(error):
    """Claude Code's own wording for an expired login read like a Proseview fault.

    The raw text arrives as an assistant message, so it also landed in the
    conversation as though Claude had answered with it.
    """
    client, seen, made = make_client([
        AssistantMessage([TextBlock(EXPIRED_LOGIN)], error=error),
        ResultMessage(is_error=True, result=EXPIRED_LOGIN),
    ])
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        assert not [m for m in seen if m["method"] == "assistant/message"]
        completed = next(m for m in seen if m["method"] == "turn/completed")
        assert completed["params"]["status"] == "failed"
        assert completed["params"]["error"] == LOGIN_EXPIRED
        errors = [m["params"] for m in seen if m["method"] == "error"]
        assert [(e["message"], e["command"]) for e in errors] == [(LOGIN_EXPIRED, LOGIN_COMMAND)]
        event = sanitize_claude_message({"method": "error", "params": errors[0]})[0]
        assert event["command"] == LOGIN_COMMAND
        # The CLI that failed is let go, so the next turn reads the new login.
        assert not made[0].connected
    finally:
        client.close()


def test_logging_in_opens_terminal_with_the_login_running(monkeypatch):
    import subprocess
    import sys

    launched = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", lambda command, **_: launched.append(command))
    open_login_terminal()
    assert launched[0][:2] == ["osascript", "-e"]
    assert f'do script "{LOGIN_COMMAND}"' in launched[0][2]


@pytest.mark.parametrize("stdout,expected", [
    ('{"loggedIn": true, "authMethod": "claude.ai"}', True),
    ('{"loggedIn": false, "authMethod": "none"}', False),
    ("not json", False),
])
def test_the_login_is_read_from_claude_auth_status(monkeypatch, stdout, expected):
    import subprocess

    calls = []

    def run(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert claude_logged_in() is expected
    assert calls == [["claude", "auth", "status", "--json"]]


def test_logging_in_elsewhere_says_what_to_run(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ClaudeUnavailableError, match=LOGIN_COMMAND):
        open_login_terminal()


def test_an_answer_that_mentions_authentication_is_still_an_answer():
    client, seen, _ = make_client([
        AssistantMessage([TextBlock("The guard failed to authenticate the courier.")]),
        ResultMessage(),
    ])
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        answers = [m["params"]["text"] for m in seen if m["method"] == "assistant/message"]
        assert answers == ["The guard failed to authenticate the courier."]
        assert not [m for m in seen if m["method"] == "error"]
    finally:
        client.close()


def test_interrupt_forwards_to_the_session():
    client, _, made = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: bool(made))
        client.request("turn/interrupt", {"threadId": thread_id, "turnId": "any"})
        assert wait_for(lambda: made[0].interrupted == 1)
    finally:
        client.close()


# --- structured output ------------------------------------------------------

@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str = "{}"
    is_error: bool = False


@dataclass
class UserMessage:
    content: list
    session_id: str = "sess-1"


def test_structured_turn_reports_the_json_not_the_prose():
    """With a schema in play the JSON is the answer, not the model's commentary.

    Found live: the CLI delivers structured output through a StructuredOutput
    tool call while the assistant text carries prose. Publishing the prose as
    the final answer fails the manager's validator on every selection action.
    """
    client, seen, made = make_client(script=[
        AssistantMessage(content=[TextBlock("here are two options")]),
        ResultMessage(result='{"kind": "alternatives"}'),
    ])
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": "hi"}],
            "outputSchema": {"type": "object"},
        })
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        finals = [m for m in seen if m["method"] == "assistant/message"]
        assert [m["params"]["text"] for m in finals] == ['{"kind": "alternatives"}']
    finally:
        client.close()


def test_structured_output_prefers_the_structured_field():
    message = ResultMessage(result="ignored")
    message.structured_output = {"kind": "critique"}
    assert ClaudeAgentClient._structured_payload(message) == '{"kind": "critique"}'


def test_internal_tool_never_becomes_an_activity_card():
    """StructuredOutput is plumbing; showing it as activity confuses the writer."""
    client, seen, made = make_client(script=[
        AssistantMessage(content=[ToolUseBlock("StructuredOutput", {}, id="t-9")]),
        UserMessage(content=[ToolResultBlock(tool_use_id="t-9")]),
        ResultMessage(result="{}"),
    ])
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": "hi"}],
            "outputSchema": {"type": "object"},
        })
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        assert not [m for m in seen if m["method"] in {"tool/started", "tool/completed"}]
    finally:
        client.close()


def test_internal_tool_is_never_asked_about():
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        assert _gate(client, thread_id, "StructuredOutput", {}).result(timeout=5) == {}
        assert _ask(client, thread_id, "StructuredOutput", {}).result(timeout=5) == {"behavior": "allow"}
        assert not [m for m in seen if "requestApproval" in m.get("method", "")]
    finally:
        client.close()


# --- approvals --------------------------------------------------------------

def _gate(client: ClaudeAgentClient, thread_id: str, tool: str, tool_input: dict | None = None):
    """Invoke the PreToolUse gate the way the SDK would, from the loop thread."""
    session = client._sessions[thread_id]
    return asyncio.run_coroutine_threadsafe(
        client._gate_tool(session, {"tool_name": tool, "tool_input": tool_input or {}}),
        client._loop,
    )


def _ask(client: ClaudeAgentClient, thread_id: str, tool: str, tool_input: dict | None = None):
    """Invoke the can_use_tool callback, as the SDK does where Claude would ask."""
    session = client._sessions[thread_id]
    return asyncio.run_coroutine_threadsafe(
        client._permission_prompt(session, tool, tool_input or {}),
        client._loop,
    )


@pytest.mark.parametrize("tool", ["Read", "Bash", "WebSearch", "Agent", "mcp__github__create_issue"])
def test_the_gate_leaves_everything_but_edits_to_claudes_own_permissions(tool):
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client._sessions[thread_id].may_write = True
        assert _gate(client, thread_id, tool, {"command": "rm -rf /"}).result(timeout=5) == {}
        assert not [m for m in seen if m.get("method", "").endswith("requestApproval")]
    finally:
        client.close()


def test_bash_asks_the_writer_and_honours_accept():
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        pending = _ask(client, thread_id, "Bash", {"command": "rm -rf /"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        assert request["method"] == "item/commandExecution/requestApproval"
        assert request["params"]["command"] == "rm -rf /"
        assert request["params"]["availableDecisions"] == APPROVAL_DECISIONS
        client.respond(request["id"], {"decision": "accept"})
        assert pending.result(timeout=5)["behavior"] == "allow"
    finally:
        client.close()


def test_decline_denies_the_tool():
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        pending = _ask(client, thread_id, "Bash", {"command": "touch notes.txt"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        client.respond(request["id"], {"decision": "decline"})
        assert pending.result(timeout=5)["behavior"] == "deny"
    finally:
        client.close()


def test_accept_for_session_is_not_asked_again():
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        pending = _ask(client, thread_id, "Bash", {"command": "touch notes.txt"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        client.respond(request["id"], {"decision": "acceptForSession"})
        assert pending.result(timeout=5)["behavior"] == "allow"

        seen.clear()
        again = _ask(client, thread_id, "Bash", {"command": "touch notes.txt"}).result(timeout=5)
        assert again["behavior"] == "allow"
        assert not [m for m in seen if "requestApproval" in m.get("method", "")]
    finally:
        client.close()


def test_session_grant_does_not_leak_across_threads():
    client, seen, _ = make_client()
    try:
        first = client.request("thread/start", {})["thread"]["id"]
        second = client.request("thread/start", {})["thread"]["id"]
        pending = _ask(client, first, "Bash", {"command": "touch notes.txt"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        client.respond(request["id"], {"decision": "acceptForSession"})
        pending.result(timeout=5)

        seen.clear()
        _ask(client, second, "Bash", {"command": "touch notes.txt"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
    finally:
        client.close()


def test_write_tool_is_reported_as_a_file_change_approval():
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client._sessions[thread_id].may_write = True
        _gate(client, thread_id, "Write", {"file_path": "manuscript/one.md"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        assert request["method"] == "item/fileChange/requestApproval"
        assert request["params"]["changes"] == [{"path": "manuscript/one.md", "kind": "modify"}]
    finally:
        client.close()


def test_a_reading_turn_refuses_edits_and_a_later_turn_may_make_them():
    """The tool list is fixed when the session connects; the turn decides.

    A session whose first turn was a critique used to keep the critique's
    read-only tools, so every later "please change it" came back refused.
    """
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        session = client._sessions[thread_id]
        session.may_write = False
        refused = _gate(client, thread_id, "Edit", {"file_path": "manuscript/one.md"}).result(timeout=5)
        assert "reading pass" in json.dumps(refused)
        assert not any("requestApproval" in m.get("method", "") for m in seen)

        session.may_write = True
        _gate(client, thread_id, "Edit", {"file_path": "manuscript/one.md"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
    finally:
        client.close()


def test_responding_to_an_unknown_approval_raises():
    client, _, _ = make_client()
    try:
        with pytest.raises(ClaudeRequestError):
            client.respond("nope", {"decision": "accept"})
    finally:
        client.close()


# --- settings ---------------------------------------------------------------

def test_options_load_the_writers_settings_as_the_extension_does():
    """Claude in Prosview is Claude as the Claude Code extension runs it."""
    client, _, made = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: bool(made))
        options = made[0].options
        assert options["setting_sources"] == ["user", "project", "local"]
        assert options["system_prompt"] == {"type": "preset", "preset": "claude_code"}
        # Its own tools and permission mode; it asks through the callback.
        for key in ("tools", "allowed_tools", "permission_mode", "mcp_servers", "strict_mcp_config"):
            assert key not in options
        assert callable(options["can_use_tool"])
        assert "PreToolUse" in options["hooks"]
    finally:
        client.close()


def test_output_schema_becomes_structured_output():
    client, _, made = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        schema = {"type": "object", "properties": {}}
        client.request("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": "hi"}],
            "outputSchema": schema,
        })
        assert wait_for(lambda: bool(made))
        assert made[0].options["output_format"] == {"type": "json_schema", "schema": schema}
    finally:
        client.close()


def test_developer_instructions_survive_from_thread_start():
    client, _, made = make_client()
    try:
        thread_id = client.request(
            "thread/start", {"developerInstructions": "be careful"}
        )["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: bool(made))
        assert made[0].options["system_prompt"] == {
            "type": "preset", "preset": "claude_code", "append": "be careful",
        }
    finally:
        client.close()


# --- history ----------------------------------------------------------------

def test_thread_read_returns_turns_from_the_session_store():
    rows = [
        type("Row", (), {"message": {"role": "user", "content": "hello"}, "type": "user"})(),
        type("Row", (), {
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hi back"}]},
            "type": "assistant",
        })(),
    ]
    client, _, made = make_client(session_reader=lambda session_id, cwd: rows)
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: client._sessions[thread_id].session_id == "sess-1")
        result = client.request("thread/read", {"threadId": thread_id, "includeTurns": True})
        # Shaped the way DiscussManager parses history: one turn, holding the
        # user message and the answer that followed it.
        turns = result["thread"]["turns"]
        assert len(turns) == 1
        items = turns[0]["items"]
        assert items[0]["type"] == "userMessage"
        assert items[0]["content"][0]["text"] == "hello"
        assert items[1]["type"] == "agentMessage"
        assert items[1]["phase"] == "final_answer"
        assert items[1]["text"] == "hi back"
    finally:
        client.close()


def test_thread_read_before_any_turn_is_not_found():
    client, _, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        with pytest.raises(ClaudeRequestError) as excinfo:
            client.request("thread/read", {"threadId": thread_id, "includeTurns": True})
        assert excinfo.value.code == -32004
    finally:
        client.close()


# --- shutdown ---------------------------------------------------------------

def test_close_releases_a_pending_approval():
    """Closing must not strand a pending question holding a turn open."""
    client, seen, _ = make_client()
    thread_id = client.request("thread/start", {})["thread"]["id"]
    pending = _ask(client, thread_id, "Bash", {"command": "touch notes.txt"})
    assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
    client.close()
    assert pending.result(timeout=5)["behavior"] == "deny"


def test_close_disconnects_sessions_and_stops_the_client():
    client, _, made = make_client()
    thread_id = client.request("thread/start", {})["thread"]["id"]
    client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
    assert wait_for(lambda: bool(made) and made[0].connected)
    client.close()
    assert not client.alive
    assert wait_for(lambda: not made[0].connected)


# --- model selection --------------------------------------------------------

def _write_settings(tmp_path, payload):
    directory = tmp_path / "claude"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "settings.json").write_text(json.dumps(payload), encoding="utf-8")


def test_the_writers_configured_model_becomes_the_default(tmp_path):
    """"Default" in the picker means the model and effort the writer configured."""
    _write_settings(tmp_path, {"model": "opus", "effortLevel": "high"})
    client, _, made = make_client()
    try:
        assert client.user_model_defaults()["model"] == "opus"
        assert client.user_model_defaults()["effort"] == "high"
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: bool(made))
        options = made[0].options
        assert options["model"] == "opus"
        assert options["effort"] == "high"
    finally:
        client.close()


@pytest.mark.parametrize("payload", [
    {"model": "opus; rm -rf /", "effortLevel": "high"},
    {"model": "o" * 500, "effortLevel": "high"},
    {"model": {"nested": True}, "effortLevel": ["high"]},
    {"model": "opus", "effortLevel": "turbo"},
])
def test_an_unusable_settings_value_is_ignored_rather_than_forwarded(tmp_path, payload):
    _write_settings(tmp_path, payload)
    client, _, _made = make_client()
    try:
        defaults = client.user_model_defaults()
        assert defaults["model"] in {"", "opus"}
        assert defaults["effort"] in {"", "high"}
        if payload.get("effortLevel") == "turbo":
            assert defaults["effort"] == ""
        else:
            assert defaults["model"] == ""
    finally:
        client.close()


def test_a_missing_settings_file_means_no_model_is_sent(tmp_path):
    client, _, made = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: bool(made))
        assert "model" not in made[0].options
        assert "effort" not in made[0].options
    finally:
        client.close()


def test_a_turns_own_model_beats_the_configured_one(tmp_path):
    _write_settings(tmp_path, {"model": "opus", "effortLevel": "high"})
    client, _, made = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": "hi"}],
            "model": "haiku",
            "effort": "low",
        })
        assert wait_for(lambda: bool(made))
        assert made[0].options["model"] == "haiku"
        assert made[0].options["effort"] == "low"
    finally:
        client.close()


def test_changing_only_the_model_keeps_the_live_session(tmp_path):
    """set_model changes a running session, so the conversation's context survives."""
    client, _, made = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {
            "threadId": thread_id, "input": [{"type": "text", "text": "one"}], "model": "opus",
        })
        assert wait_for(lambda: bool(made))
        client.request("turn/start", {
            "threadId": thread_id, "input": [{"type": "text", "text": "two"}], "model": "haiku",
        })
        assert wait_for(lambda: made[0].models == ["haiku"])
        assert len(made) == 1, "the session was reused rather than reconnected"
    finally:
        client.close()


def test_changing_the_effort_reconnects_the_same_conversation(tmp_path):
    """Effort is fixed at connect time, so it costs a resume -- of the same session id."""
    client, _, made = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {
            "threadId": thread_id, "input": [{"type": "text", "text": "one"}], "effort": "low",
        })
        assert wait_for(lambda: bool(made))
        client.request("turn/start", {
            "threadId": thread_id, "input": [{"type": "text", "text": "two"}], "effort": "max",
        })
        assert wait_for(lambda: len(made) == 2)
        assert made[0].connected is False
        assert made[1].options["effort"] == "max"
        assert made[1].options["resume"] == thread_id, "the conversation is resumed, not replaced"
    finally:
        client.close()


def test_the_roster_reports_the_configured_default(tmp_path):
    _write_settings(tmp_path, {"model": "haiku", "effortLevel": "low"})
    client, _, _made = make_client()
    try:
        catalog = client.request("model/list", {})
        ids = [row["id"] for row in catalog["data"]]
        assert ids == ["opus", "sonnet", "fable", "haiku"]
        assert catalog["default"]["model"] == "haiku"
        assert catalog["default"]["effort"] == "low"
        assert [row["isDefault"] for row in catalog["data"]] == [False, False, False, True]
        # Every Claude model takes the same ladder, so the picker's effort row
        # never changes shape.
        ladders = {tuple(e["reasoningEffort"] for e in row["supportedReasoningEfforts"]) for row in catalog["data"]}
        assert ladders == {("low", "medium", "high", "xhigh", "max")}
    finally:
        client.close()


def test_a_missing_sdk_says_how_to_install_it(monkeypatch):
    import sys

    from proseview.claude_agent_client import ClaudeUnavailableError

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    client = ClaudeAgentClient(cwd=".", on_message=lambda message: None)
    with pytest.raises(ClaudeUnavailableError) as raised:
        client.inspect_capabilities()
    assert "pipx inject proseview claude-agent-sdk" in str(raised.value)
    assert 'pipx install "proseview[claude]"' in str(raised.value)


def test_a_web_search_asks_and_says_what_it_would_search():
    client, seen, _ = make_client()
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        _ask(client, thread_id, "WebSearch", {"query": "1990s Tehran taxi slang"})
        assert wait_for(lambda: any("requestApproval" in m.get("method", "") for m in seen))
        request = next(m for m in seen if "requestApproval" in m.get("method", ""))
        assert request["params"]["tool"] == "WebSearch"
        assert request["params"]["command"] == "Search the web for “1990s Tehran taxi slang”"
    finally:
        client.close()


def test_an_ephemeral_thread_reads_only_and_leaves_no_session_behind():
    """A highlight suggestion is one answer, not a conversation to resume."""
    client, seen, made = make_client(script=[ResultMessage(result='{"kind": "alternatives"}')])
    try:
        thread_id = client.request("thread/start", {
            "ephemeral": True,
            "tools": ["Read", "Grep", "Glob", "Write"],
            "settingSources": ["user", "project", "local"],
            "mcpServers": {"notes": {"command": "notes-mcp"}},
        })["thread"]["id"]
        client.request("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": "hi"}],
            "outputSchema": {"type": "object"},
        })
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        options = made[0].options
        assert options["tools"] == ["Read", "Grep", "Glob"], "a write tool is never handed over"
        assert options["allowed_tools"] == ["Read", "Grep", "Glob"]
        assert options["setting_sources"] == ["user", "project", "local"]
        assert options["mcp_servers"] == {"notes": {"command": "notes-mcp"}}
        assert options["extra_args"] == {"no-session-persistence": None, "strict-mcp-config": None}
        assert options["output_format"]["type"] == "json_schema"
    finally:
        client.close()


def test_an_ephemeral_thread_with_no_tools_gets_none():
    client, seen, made = make_client(script=[ResultMessage(result="{}")])
    try:
        thread_id = client.request("thread/start", {"ephemeral": True})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        assert made[0].options["tools"] == [] and made[0].options["mcp_servers"] == {}
    finally:
        client.close()


def test_an_ephemeral_thread_allows_its_tools_and_denies_the_rest_without_asking():
    import asyncio
    from proseview.claude_agent_client import _Session

    client, seen, made = make_client()
    try:
        session = _Session("t-1")
        session.thread_params = {"ephemeral": True, "tools": ["Read"]}
        allow = asyncio.run(client._permission_prompt(session, "Read", {}))
        deny = asyncio.run(client._permission_prompt(session, "Bash", {}))
        assert allow == {"behavior": "allow"} and deny["behavior"] == "deny"
        assert not any(m["method"].endswith("requestApproval") for m in seen)
    finally:
        client.close()


def test_an_ordinary_thread_keeps_its_tools_and_its_session():
    client, seen, made = make_client(script=[ResultMessage(result="ok")])
    try:
        thread_id = client.request("thread/start", {})["thread"]["id"]
        client.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": "hi"}]})
        assert wait_for(lambda: any(m["method"] == "turn/completed" for m in seen))
        assert "tools" not in made[0].options and "extra_args" not in made[0].options
    finally:
        client.close()
