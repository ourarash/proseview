"""Unit and integration tests for /btw ephemeral side questions (Codex and Claude)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from proseview.claude_agent_client import ClaudeRequestError
from proseview.codex_app_server import CodexRequestError
from proseview.discuss import ContextError, DiscussManager

from .test_highlight_suggestions import _repo
from .transport_fakes import AgyFakeClient, ClaudeFakeClient, CodexFakeClient


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


def wait_for(predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


class _HoldMainCodex(CodexFakeClient):
    """Fake Codex client that holds only the marked main or side turn."""

    def __init__(self, callback, agent: str = "codex"):
        super().__init__(callback, agent)
        self.held_turn_started = threading.Event()
        self.held_turn_release = threading.Event()
        self.held_interrupted = False
        self.held_turn_id: str | None = None
        self.side_held_started = threading.Event()
        self.side_held_release = threading.Event()
        self.side_interrupted = False
        self.side_turn_id: str | None = None

    def request(self, method, params, *, timeout=None):
        if method == "turn/interrupt":
            self.interrupts.append(dict(params))
            if self.held_turn_id and params.get("turnId") == self.held_turn_id:
                self.held_interrupted = True
                self.held_turn_release.set()
            if self.side_turn_id and params.get("turnId") == self.side_turn_id:
                self.side_interrupted = True
                self.side_held_release.set()
            return {}
        if method == "turn/start":
            text = params["input"][0]["text"]
            if "HOLD_MAIN" in text:
                self.next_turn += 1
                turn_id = f"turn-{self.next_turn}"
                self.held_turn_id = turn_id
                thread_id = params["threadId"]
                self.prompts.append(text)
                self.turn_params.append(dict(params))

                def finish():
                    self.held_turn_started.set()
                    self.held_turn_release.wait(5.0)
                    if self.held_interrupted:
                        self.callback({
                            "method": "turn/completed",
                            "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "interrupted"}},
                        })
                    else:
                        self.callback({
                            "method": "item/completed",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "item": {"id": f"ans-{turn_id}", "type": "agentMessage", "phase": "final_answer", "text": f"Main {turn_id}"},
                            },
                        })
                        self.callback({
                            "method": "turn/completed",
                            "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}},
                        })

                threading.Thread(target=finish, daemon=True).start()
                return {"turn": {"id": turn_id, "status": "inProgress"}}
            if "HOLD_SIDE" in text:
                self.next_turn += 1
                turn_id = f"turn-{self.next_turn}"
                self.side_turn_id = turn_id
                thread_id = params["threadId"]
                self.prompts.append(text)
                self.turn_params.append(dict(params))

                def finish_side():
                    self.side_held_started.set()
                    self.side_held_release.wait(5.0)
                    status = "interrupted" if self.side_interrupted else "completed"
                    if not self.side_interrupted:
                        self.callback({
                            "method": "item/completed",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "item": {"id": f"ans-{turn_id}", "type": "agentMessage", "phase": "final_answer", "text": "Side answer"},
                            },
                        })
                    self.callback({
                        "method": "turn/completed",
                        "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": status}},
                    })

                threading.Thread(target=finish_side, daemon=True).start()
                return {"turn": {"id": turn_id, "status": "inProgress"}}
        return super().request(method, params, timeout=timeout)


class _HoldMainClaude(ClaudeFakeClient):
    """Fake Claude client that holds only turns tagged HOLD_MAIN."""

    def __init__(self, callback, agent: str = "claude"):
        super().__init__(callback, agent)
        self.held_turn_started = threading.Event()
        self.held_turn_release = threading.Event()

    def request(self, method, params, *, timeout=None):
        if method == "turn/start" and "HOLD_MAIN" in params["input"][0]["text"]:
            self.next_turn += 1
            turn_id = f"claude-turn-{self.next_turn}"
            thread_id = params["threadId"]
            text = params["input"][0]["text"]
            self.prompts.append(text)
            self.turn_params.append(dict(params))

            def finish():
                self.held_turn_started.set()
                self.held_turn_release.wait(5.0)
                common = {"threadId": thread_id, "turnId": turn_id}
                self.callback({
                    "method": "assistant/message",
                    "params": {**common, "itemId": f"ans-{turn_id}", "phase": "final_answer", "text": "Main claude done"},
                })
                self.callback({"method": "turn/completed", "params": {**common, "status": "completed", "error": ""}})

            threading.Thread(target=finish, daemon=True).start()
            return {"turn": {"id": turn_id}}
        return super().request(method, params, timeout=timeout)


def _manager(root: Path):
    created: dict[str, CodexFakeClient | ClaudeFakeClient] = {}

    def factory(callback, agent="codex"):
        client = _HoldMainClaude(callback, agent) if agent == "claude" else _HoldMainCodex(callback, agent)
        created[agent] = client
        return client

    return DiscussManager(root, client_factory=factory), created


def _events(manager: DiscussManager, cid: str) -> list[tuple[str, dict]]:
    _snap, replay, _sub = manager.subscribe(cid, 0)
    return [(ev.type, ev.data) for ev in (replay or [])]


def test_codex_btw_forks_and_runs_in_parallel_without_polluting_main_chat(tmp_path: Path):
    manager, clients = _manager(_repo(tmp_path))
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="codex")["conversation_id"]

        # Seed a completed turn so the parent thread exists on the client.
        manager.submit(cid, client_request_id="m0", question="Initial warm-up", document=doc)
        wait_for(lambda: not manager.get_snapshot(cid)["active_turn_id"] and len(manager.get_snapshot(cid)["messages"]) == 2)

        # Now start a held main turn AND queue another main item behind it.
        manager.submit(cid, client_request_id="m1", question="HOLD_MAIN long main edit", document=doc)
        codex = clients["codex"]
        assert isinstance(codex, _HoldMainCodex)
        wait_for(codex.held_turn_started.is_set)
        manager.submit(cid, client_request_id="m2", question="Queued behind main", document=doc)

        # Run /btw side question in parallel while main turn is held.
        res = manager.side_question(cid, client_request_id="btw-1", question="/btw How old was Mira?", document=doc)
        assert res["status"] == "running"
        assert res["question"] == "How old was Mira?"

        completed = wait_for(
            lambda: next(
                (data for name, data in _events(manager, cid) if name == "side_question.completed" and data.get("side_question_id") == res["side_question_id"]),
                None,
            )
        )
        assert completed["mode"] == "fork"
        assert completed["text"]

        # Verify thread/fork params and workspace-write edit capability.
        assert len(codex.forks) == 1
        assert codex.forks[0]["threadId"] == "thread-1"
        assert codex.forks[0]["ephemeral"] is True
        assert codex.forks[0]["sandbox"] == "workspace-write"
        assert codex.forks[0]["allowWrite"] is True
        forked_turn = next(p for p in codex.turn_params if p["threadId"] != "thread-1")
        assert forked_turn["mayWrite"] is True
        assert forked_turn["sandboxPolicy"]["type"] == "workspaceWrite"

        # Main turn was NOT interrupted or steered while /btw finished.
        assert codex.interrupts == []
        assert codex.steers == []
        assert manager.get_snapshot(cid)["active_turn_id"] == codex.held_turn_id

        # Release main turn and verify main messages/queue never contain /btw.
        codex.held_turn_release.set()
        done = wait_for(lambda: (s := manager.get_snapshot(cid))["active_turn_id"] is None and not s["queue"] and s)
        user_texts = [m["text"] for m in done["messages"] if m["role"] == "user"]
        assert user_texts == ["Initial warm-up", "HOLD_MAIN long main edit", "Queued behind main"]
        assert not any("How old was Mira" in m.get("text", "") for m in done["messages"])
    finally:
        manager.close()


def test_claude_btw_forks_read_only_and_keeps_queue_untouched(tmp_path: Path):
    manager, clients = _manager(_repo(tmp_path))
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="claude")["conversation_id"]

        manager.submit(cid, client_request_id="c0", question="Claude warmup", document=doc)
        wait_for(lambda: not manager.get_snapshot(cid)["active_turn_id"] and len(manager.get_snapshot(cid)["messages"]) == 2)

        manager.submit(cid, client_request_id="c1", question="HOLD_MAIN Claude busy work", document=doc)
        claude = clients["claude"]
        assert isinstance(claude, _HoldMainClaude)
        wait_for(claude.held_turn_started.is_set)

        res = manager.side_question(cid, client_request_id="btw-c", question="/btw Check name spelling", document=doc)
        completed = wait_for(
            lambda: next(
                (data for name, data in _events(manager, cid) if name == "side_question.completed" and data.get("side_question_id") == res["side_question_id"]),
                None,
            )
        )
        assert completed["mode"] == "fork"
        assert len(claude.forks) == 1
        assert claude.forks[0]["ephemeral"] is True
        assert claude.forks[0]["allowWrite"] is True
        assert {"Read", "Grep", "Glob", "Edit", "Write"}.issubset(set(claude.forks[0]["tools"]))
        forked_turn = next(p for p in claude.turn_params if p["threadId"] != "claude-thread-1")
        assert forked_turn["mayWrite"] is True
        assert claude.interrupts == []

        claude.held_turn_release.set()
        done = wait_for(lambda: (s := manager.get_snapshot(cid))["active_turn_id"] is None and s)
        assert not any("Check name spelling" in m.get("text", "") for m in done["messages"])
    finally:
        manager.close()


def test_btw_falls_back_to_seeded_ephemeral_thread_when_fork_fails(tmp_path: Path):
    manager, clients = _manager(_repo(tmp_path))
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="codex")["conversation_id"]
        manager.submit(cid, client_request_id="s1", question="Remember Boston winter", document=doc)
        wait_for(lambda: not manager.get_snapshot(cid)["active_turn_id"] and len(manager.get_snapshot(cid)["messages"]) == 2)

        codex = clients["codex"]
        codex.fork_error = CodexRequestError("method not found: thread/fork", code=-32601)

        res = manager.side_question(cid, client_request_id="btw-fallback", question="/btw Where did Mira learn winter?", document=doc)
        completed = wait_for(
            lambda: next(
                (data for name, data in _events(manager, cid) if name == "side_question.completed" and data.get("side_question_id") == res["side_question_id"]),
                None,
            )
        )
        assert completed["mode"] == "seeded"
        assert "method not found" in completed["fallback_reason"]
        # Seeded prompt carries recent visible conversation background.
        assert "Remember Boston winter" in codex.prompts[-1]
        assert "BACKGROUND CONVERSATION" in codex.prompts[-1]
        assert codex.thread_start_params[-1]["ephemeral"] is True

        # Main thread state store still points only to thread-1, never the ephemeral fallback thread.
        assert manager.state.get("scene", "one.md", "codex") == "thread-1"
    finally:
        manager.close()


def test_btw_declines_unexpected_approval_requests_and_supports_cancel(tmp_path: Path):
    manager, clients = _manager(_repo(tmp_path))
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="codex")["conversation_id"]
        codex = clients["codex"]
        assert isinstance(codex, _HoldMainCodex)

        res = manager.side_question(cid, client_request_id="btw-cancel", question="/btw HOLD_SIDE hold until closed", document=doc)
        wait_for(codex.side_held_started.is_set)

        # Simulate fileChange approval (accepted for writable /btw) and shell command approval (still declined).
        side_thread_id = codex.turn_params[-1]["threadId"]
        codex.callback({
            "id": 9900,
            "method": "item/fileChange/requestApproval",
            "params": {"threadId": side_thread_id, "turnId": codex.side_turn_id},
        })
        assert (9900, {"decision": "accept"}) in codex.responses
        codex.callback({
            "id": 9901,
            "method": "item/commandExecution/requestApproval",
            "params": {"threadId": side_thread_id, "turnId": codex.side_turn_id, "command": "rm -rf /"},
        })
        assert (9901, {"decision": "decline"}) in codex.responses
        assert manager.get_snapshot(cid)["approvals"] == []

        assert manager.cancel_side_question(cid, res["side_question_id"]) is True
        cancelled = wait_for(
            lambda: next(
                (data for name, data in _events(manager, cid) if name == "side_question.cancelled" and data.get("side_question_id") == res["side_question_id"]),
                None,
            )
        )
        assert cancelled["side_question_id"] == res["side_question_id"]
        assert cancelled["client_request_id"] == "btw-cancel"
    finally:
        manager.close()


def test_btw_emits_client_request_id_when_side_question_fails_early(tmp_path: Path):
    manager, clients = _manager(_repo(tmp_path))
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="codex")["conversation_id"]
        clients["codex"].reject_turn_starts = True

        res = manager.side_question(cid, client_request_id="btw-fail-early", question="/btw Will fail immediately", document=doc)
        failed = wait_for(
            lambda: next(
                (data for name, data in _events(manager, cid) if name == "side_question.failed" and data.get("side_question_id") == res["side_question_id"]),
                None,
            )
        )
        assert failed["client_request_id"] == "btw-fail-early"
        assert failed["error"]
    finally:
        manager.close()


def test_btw_rejects_empty_question_after_prefix(tmp_path: Path):
    manager, _clients = _manager(_repo(tmp_path))
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="codex")["conversation_id"]
        with pytest.raises(ContextError, match="enter a question after /btw"):
            manager.side_question(cid, question="/btw   ")
    finally:
        manager.close()


def test_btw_passes_prior_turns_from_same_side_tab_without_touching_main_messages(tmp_path: Path):
    manager, clients = _manager(_repo(tmp_path))
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="codex")["conversation_id"]
        res = manager.side_question(
            cid,
            client_request_id="btw-followup",
            question="And what about Chapter 3?",
            prior_turns=[{"question": "How old was Mira?", "answer": "Twenty-four in Chapter 2."}],
            document=doc,
        )
        wait_for(
            lambda: next(
                (data for name, data in _events(manager, cid) if name == "side_question.completed" and data.get("side_question_id") == res["side_question_id"]),
                None,
            )
        )
        codex = clients["codex"]
        assert "EARLIER IN THIS SIDE QUESTION (/btw) TAB" in codex.prompts[-1]
        assert "Twenty-four in Chapter 2." in codex.prompts[-1]
        assert "And what about Chapter 3?" in codex.prompts[-1]
        assert manager.get_snapshot(cid)["messages"] == []
    finally:
        manager.close()


def test_btw_runs_seeded_ephemeral_turn_on_agy(tmp_path: Path):
    clients: dict[str, object] = {}

    def factory(callback, agent):
        if agent == "agy":
            client = AgyFakeClient(callback)
        elif agent == "claude":
            client = ClaudeFakeClient(callback)
        else:
            client = CodexFakeClient(callback)
        clients[agent] = client
        return client

    manager = DiscussManager(_repo(tmp_path), client_factory=factory)
    try:
        doc = {"kind": "scene", "path": "one.md"}
        cid = manager.open(doc, agent="agy")["conversation_id"]
        manager.submit(cid, client_request_id="main-1", question="Main turn first", document=doc)
        wait_for(lambda: any(m.get("role") == "assistant" for m in manager.get_snapshot(cid)["messages"]))

        res = manager.side_question(
            cid,
            client_request_id="btw-agy-1",
            question="/btw What happened earlier?",
            document=doc,
        )
        assert res["agent"] == "agy"
        completed = wait_for(
            lambda: next(
                (data for name, data in _events(manager, cid) if name == "side_question.completed" and data.get("side_question_id") == res["side_question_id"]),
                None,
            )
        )
        assert completed["mode"] == "seeded"
        assert completed["text"]
        assert len(manager.get_snapshot(cid)["messages"]) == 2
    finally:
        manager.close()
