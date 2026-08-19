"""Discuss runs both agents side by side, not one selected by configuration."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from proseview.claude_agent_client import ClaudeAgentClient, sanitize_claude_message
from proseview.codex_app_server import CodexAppServer
from proseview.config import ConfigError, DiscussConfig
from proseview.discuss import (
    DEFAULT_AGENT,
    DiscussManager,
    DiscussStateStore,
    sanitize_agent_message,
)


def _repo(tmp_path: Path, default_agent: str | None = None) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript").mkdir(parents=True)
    (root / "manuscript" / "one.md").write_text("# One\n\nFirst.\n", encoding="utf-8")
    if default_agent is not None:
        (root / ".proseview.yaml").write_text(
            f"discuss:\n  agent: {default_agent}\n", encoding="utf-8"
        )
    return root


class _FakeClient:
    """Enough of a transport to prove routing, with a per-instance identity."""

    def __init__(self, callback, agent: str = "codex"):
        self.agent = agent
        self.callback = callback
        self.alive = True
        self.capabilities = {"reasoning_summary": False}
        self.threads: dict[str, dict] = {}
        self.turns = 0
        self.closed = False
        self._lock = threading.Lock()

    def inspect_capabilities(self):
        return {"stable_discuss_protocol": True}

    def probe_capabilities(self):
        return {"stable_discuss_protocol": True}

    def start(self):
        return None

    def request(self, method, params, *, timeout=None):
        if method == "thread/start":
            with self._lock:
                thread_id = f"t{len(self.threads) + 1}-{id(self)}"
                self.threads[thread_id] = {"id": thread_id, "turns": []}
            return {"thread": {"id": thread_id}}
        if method == "thread/read":
            thread_id = params["threadId"]
            if thread_id not in self.threads:
                from proseview.codex_app_server import CodexRequestError

                raise CodexRequestError("thread not found", code=-32004)
            return {"thread": self.threads[thread_id]}
        if method == "turn/start":
            with self._lock:
                self.turns += 1
                turn_id = f"u{self.turns}-{id(self)}"
            return {"turn": {"id": turn_id}}
        if method == "turn/interrupt":
            return {}
        return {}

    def respond(self, request_id, result):
        return None

    def respond_error(self, request_id, message, code=-32601):
        return None

    def close(self):
        self.closed = True
        self.alive = False


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- transports -------------------------------------------------------------

def test_each_agent_builds_its_own_transport(tmp_path):
    manager = DiscussManager(_repo(tmp_path))
    try:
        assert isinstance(manager._build_client("codex"), CodexAppServer)
        assert isinstance(manager._build_client("claude"), ClaudeAgentClient)
    finally:
        manager.close()


def test_each_transport_carries_its_own_translator():
    # Codex has no translator of its own; the module-level one is the default.
    assert getattr(CodexAppServer, "translate", None) is None
    assert ClaudeAgentClient.translate is sanitize_claude_message
    assert sanitize_agent_message is not sanitize_claude_message


def test_unknown_agent_is_rejected(tmp_path):
    manager = DiscussManager(_repo(tmp_path))
    try:
        with pytest.raises(ValueError, match="unknown agent"):
            manager.open({"kind": "scene", "path": "one.md"}, "gpt5")
    finally:
        manager.close()


# --- independent conversations ----------------------------------------------

def test_one_document_has_a_separate_conversation_per_agent(tmp_path):
    made: list[_FakeClient] = []

    def factory(callback, agent):
        client = _FakeClient(callback, agent)
        made.append(client)
        return client

    manager = DiscussManager(_repo(tmp_path), client_factory=factory)
    try:
        doc = {"kind": "scene", "path": "one.md"}
        codex = manager.open(doc, "codex")
        claude = manager.open(doc, "claude")
        assert codex["conversation_id"] != claude["conversation_id"]
        assert codex["agent"] == "codex"
        assert claude["agent"] == "claude"
        # Two transports, one per agent — not one shared connection.
        assert len(made) == 2
    finally:
        manager.close()


def test_both_agents_can_hold_a_turn_at_the_same_time(tmp_path):
    manager = DiscussManager(_repo(tmp_path), client_factory=_FakeClient)
    try:
        doc = {"kind": "scene", "path": "one.md"}
        codex = manager.open(doc, "codex")["conversation_id"]
        claude = manager.open(doc, "claude")["conversation_id"]

        manager.submit(codex, client_request_id="c1", question="Ask Codex something")
        manager.submit(claude, client_request_id="k1", question="Ask Claude something")

        assert _wait_for(lambda: manager.get_snapshot(codex)["active_turn_id"] is not None)
        assert _wait_for(lambda: manager.get_snapshot(claude)["active_turn_id"] is not None)
        # Neither turn blocks the other: both are live simultaneously.
        assert manager.get_snapshot(codex)["active_turn_id"]
        assert manager.get_snapshot(claude)["active_turn_id"]
    finally:
        manager.close()


def test_one_agent_failing_leaves_the_other_alone(tmp_path):
    manager = DiscussManager(_repo(tmp_path), client_factory=_FakeClient)
    try:
        doc = {"kind": "scene", "path": "one.md"}
        codex = manager.open(doc, "codex")["conversation_id"]
        claude = manager.open(doc, "claude")["conversation_id"]
        manager.submit(codex, client_request_id="c1", question="Something")
        manager.submit(claude, client_request_id="k1", question="Something")
        assert _wait_for(lambda: manager.get_snapshot(codex)["active_turn_id"] is not None)
        assert _wait_for(lambda: manager.get_snapshot(claude)["active_turn_id"] is not None)

        manager._on_agent_failure("codex", RuntimeError("codex fell over"))

        assert manager.get_snapshot(codex)["connection"] == "Unavailable"
        assert manager.get_snapshot(claude)["connection"] != "Unavailable"
    finally:
        manager.close()


def test_events_route_to_the_agent_that_sent_them(tmp_path):
    manager = DiscussManager(_repo(tmp_path), client_factory=_FakeClient)
    try:
        doc = {"kind": "scene", "path": "one.md"}
        codex = manager.open(doc, "codex")["conversation_id"]
        claude = manager.open(doc, "claude")["conversation_id"]
        manager.submit(codex, client_request_id="c1", question="Q")
        assert _wait_for(lambda: manager._get(codex).thread_id is not None)
        thread_id = manager._get(codex).thread_id

        # The same thread id arriving from the other agent must not be
        # mistaken for this conversation.
        manager._on_agent_message("claude", {
            "method": "item/agentMessage/delta",
            "params": {"threadId": thread_id, "delta": "leaked"},
        })
        assert manager._get(claude).messages == []
        assert not any("leaked" in str(m) for m in manager._get(codex).messages)
    finally:
        manager.close()


# --- history isolation ------------------------------------------------------

def test_codex_history_keys_are_unchanged(tmp_path):
    """Conversations recorded before a second agent existed must stay reachable."""
    assert DiscussStateStore._doc_key("scene", "one.md") == "scene:one.md"
    assert DiscussStateStore._doc_key("scene", "one.md", "codex") == "scene:one.md"
    assert DiscussStateStore._doc_key("scene", "one.md", "claude") != "scene:one.md"


def test_history_does_not_leak_between_agents(tmp_path, monkeypatch):
    store = DiscussStateStore(tmp_path, path=tmp_path / "state.json")
    store.set("scene", "one.md", "codex-thread", "codex")
    store.set("scene", "one.md", "claude-thread", "claude")
    assert store.get("scene", "one.md", "codex") == "codex-thread"
    assert store.get("scene", "one.md", "claude") == "claude-thread"
    assert [row["thread_id"] for row in store.list("scene", "one.md", "codex")] == ["codex-thread"]
    assert [row["thread_id"] for row in store.list("scene", "one.md", "claude")] == ["claude-thread"]


def test_removing_one_agents_conversation_keeps_the_other(tmp_path):
    store = DiscussStateStore(tmp_path, path=tmp_path / "state.json")
    store.set("scene", "one.md", "codex-thread", "codex")
    store.set("scene", "one.md", "claude-thread", "claude")
    assert store.remove("scene", "one.md", "codex-thread", "codex")
    assert store.get("scene", "one.md", "claude") == "claude-thread"


# --- availability and defaults ----------------------------------------------

def test_agents_reports_both_with_availability(tmp_path):
    manager = DiscussManager(_repo(tmp_path), client_factory=_FakeClient)
    try:
        rows = manager.agents()
        assert [row["id"] for row in rows] == ["codex", "claude"]
        assert [row["label"] for row in rows] == ["Codex", "Claude"]
        assert all("available" in row and "reason" in row for row in rows)
    finally:
        manager.close()


def test_an_unavailable_agent_explains_itself(tmp_path, monkeypatch):
    manager = DiscussManager(_repo(tmp_path))
    try:
        def broken(agent):
            if agent == "claude":
                raise RuntimeError("claude-agent-sdk is not installed")

        monkeypatch.setattr(manager, "_probe_agent", broken)
        rows = {row["id"]: row for row in manager.agents()}
        assert rows["claude"]["available"] is False
        assert "not installed" in rows["claude"]["reason"]
        assert rows["codex"]["available"] is True
    finally:
        manager.close()


def test_default_agent_is_codex_and_configurable():
    assert DEFAULT_AGENT == "codex"
    assert DiscussConfig().agent == "codex"


def test_configured_default_agent_is_reported(tmp_path):
    manager = DiscussManager(_repo(tmp_path, "claude"))
    try:
        assert manager.context.cfg.discuss.agent == "claude"
    finally:
        manager.close()


def test_unknown_default_agent_is_rejected_at_load(tmp_path):
    with pytest.raises(ConfigError, match="discuss.agent"):
        DiscussManager(_repo(tmp_path, "gpt5"))
