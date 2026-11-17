"""Send-now (steer vs interrupt + mention order) tests across Codex, Claude, and Group."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from proseview.codex_app_server import CodexRequestError
from proseview.discuss import DiscussManager

from .test_highlight_suggestions import _repo
from .transport_fakes import ClaudeFakeClient, CodexFakeClient


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


class _ControllableCodex(CodexFakeClient):
    def __init__(self, callback, agent: str = "codex", *, hold_first: bool = True):
        super().__init__(callback, agent)
        self.hold_first = hold_first
        self.first_turn_started = threading.Event()
        self.first_turn_release = threading.Event()
        self.first_turn_interrupted = False
        self.held_turn_id: str | None = None
        self.event_log: list[tuple[str, str]] = []

    def request(self, method, params, *, timeout=None):
        if method == "turn/steer":
            self.steers.append(dict(params))
            self.event_log.append(("steer", params["input"][0]["text"]))
            if self.steer_error is not None:
                raise self.steer_error
            return {"turnId": params.get("expectedTurnId") or self.held_turn_id or "turn-1"}
        if method == "turn/interrupt":
            self.interrupts.append(dict(params))
            self.event_log.append(("interrupt", str(params.get("turnId") or "")))
            if self.held_turn_id and params.get("turnId") == self.held_turn_id and not self.first_turn_release.is_set():
                self.first_turn_interrupted = True
                self.first_turn_release.set()
            if self.interrupt_error is not None:
                raise self.interrupt_error
            return {}
        if method == "turn/start" and self.hold_first and self.next_turn == 0:
            self.turn_start_attempts += 1
            self.next_turn += 1
            turn_id = f"turn-{self.next_turn}"
            self.held_turn_id = turn_id
            thread_id = params["threadId"]
            prompt = params["input"][0]["text"]
            self.prompts.append(prompt)
            self.turn_params.append(dict(params))
            self.event_log.append(("start", prompt))

            def finish_held():
                self.first_turn_started.set()
                self.first_turn_release.wait(5.0)
                if self.first_turn_interrupted:
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
                            "item": {"id": f"answer-{turn_id}", "type": "agentMessage", "phase": "final_answer", "text": f"Answer {turn_id}"},
                        },
                    })
                    self.callback({
                        "method": "turn/completed",
                        "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}},
                    })

            threading.Thread(target=finish_held, daemon=True).start()
            return {"turn": {"id": turn_id, "status": "inProgress"}}
        if method == "turn/start":
            self.event_log.append(("start", params["input"][0]["text"]))
        return super().request(method, params, timeout=timeout)


class _ControllableClaude(ClaudeFakeClient):
    def __init__(self, callback, agent: str = "claude", *, hold_first: bool = True):
        super().__init__(callback, agent)
        self.hold_first = hold_first
        self.first_turn_started = threading.Event()
        self.first_turn_release = threading.Event()
        self.first_turn_interrupted = False
        self.held_turn_id: str | None = None
        self.event_log: list[tuple[str, str]] = []

    def request(self, method, params, *, timeout=None):
        if method == "turn/interrupt":
            self.interrupts.append(dict(params))
            self.event_log.append(("interrupt", str(params.get("turnId") or "")))
            if self.held_turn_id and params.get("turnId") == self.held_turn_id and not self.first_turn_release.is_set():
                self.first_turn_interrupted = True
                self.first_turn_release.set()
            return {}
        if method == "turn/start" and self.hold_first and self.next_turn == 0:
            self.next_turn += 1
            turn_id = f"claude-turn-{self.next_turn}"
            self.held_turn_id = turn_id
            thread_id = params["threadId"]
            prompt = params["input"][0]["text"]
            self.prompts.append(prompt)
            self.turn_params.append(dict(params))
            self.event_log.append(("start", prompt))

            def finish_held():
                self.first_turn_started.set()
                self.first_turn_release.wait(5.0)
                if self.first_turn_interrupted:
                    self.callback({
                        "method": "turn/completed",
                        "params": {"threadId": thread_id, "turnId": turn_id, "status": "interrupted", "error": ""},
                    })
                else:
                    common = {"threadId": thread_id, "turnId": turn_id}
                    self.callback({
                        "method": "assistant/message",
                        "params": {**common, "itemId": f"answer-{turn_id}", "phase": "final_answer", "text": f"Answer {turn_id}"},
                    })
                    self.callback({"method": "turn/completed", "params": {**common, "status": "completed", "error": ""}})

            threading.Thread(target=finish_held, daemon=True).start()
            return {"turn": {"id": turn_id}}
        if method == "turn/start":
            self.event_log.append(("start", params["input"][0]["text"]))
        return super().request(method, params, timeout=timeout)


def _controllable_manager(root: Path, *, hold: tuple[str, ...] = ("codex", "claude")):
    created: dict[str, _ControllableCodex | _ControllableClaude] = {}

    def factory(callback, agent="codex"):
        hold_first = agent in hold
        client = (
            _ControllableClaude(callback, agent, hold_first=hold_first)
            if agent == "claude"
            else _ControllableCodex(callback, agent, hold_first=hold_first)
        )
        created[agent] = client
        return client

    return DiscussManager(root, client_factory=factory), created


def _initial_group(manager: DiscussManager, key: str = "send-now-group") -> dict:
    return {
        "id": key,
        "scene": "one.md",
        "participants": manager.group_settings()["participants"],
        "turns": [],
        "title": "Conversation",
    }


def _group_cmd(manager: DiscussManager, action: str = "state", key: str = "send-now-group", **kw):
    return manager.group_command({
        "action": action,
        "group_id": key,
        "request_id": kw.pop("request_id", f"req-{time.monotonic_ns()}"),
        **kw,
    })


def test_codex_send_now_steers_active_turn_and_keeps_queue_behind(tmp_path: Path):
    manager, clients = _controllable_manager(_repo(tmp_path))
    try:
        opened = manager.open({"kind": "scene", "path": "one.md"}, agent="codex")
        cid = opened["conversation_id"]
        doc = {"kind": "scene", "path": "one.md"}

        manager.submit(cid, client_request_id="q1", question="HOLD_TURN First question", document=doc)
        wait_for(lambda: "codex" in clients and clients["codex"].first_turn_started.is_set())
        wait_for(lambda: manager.get_snapshot(cid)["active_turn_id"] == "turn-1")

        manager.submit(cid, client_request_id="q2", question="Queued behind", document=doc)
        res = manager.submit(cid, client_request_id="q3", question="Steer now", document=doc, immediate=True)

        assert res["status"] == "steered"
        codex = clients["codex"]
        assert len(codex.steers) == 1
        assert codex.steers[0]["expectedTurnId"] == "turn-1"
        assert "Steer now" in codex.steers[0]["input"][0]["text"]
        assert codex.interrupts == []

        snap = manager.get_snapshot(cid)
        user_texts = [m["text"] for m in snap["messages"] if m["role"] == "user"]
        assert user_texts == ["HOLD_TURN First question", "Steer now", "Queued behind"]

        codex.first_turn_release.set()
        done = wait_for(lambda: (s := manager.get_snapshot(cid))["active_turn_id"] is None
                        and s["active_request_id"] is None and not s["queue"] and s)
        assert [m["role"] for m in done["messages"]].count("assistant") == 2
    finally:
        manager.close()


def test_codex_send_now_falls_back_to_interrupt_and_front_of_queue_when_steer_rejected(tmp_path: Path):
    manager, clients = _controllable_manager(_repo(tmp_path))
    try:
        opened = manager.open({"kind": "scene", "path": "one.md"}, agent="codex")
        cid = opened["conversation_id"]
        doc = {"kind": "scene", "path": "one.md"}

        manager.submit(cid, client_request_id="q1", question="HOLD_TURN First question", document=doc)
        wait_for(lambda: "codex" in clients and clients["codex"].first_turn_started.is_set())
        wait_for(lambda: manager.get_snapshot(cid)["active_turn_id"] == "turn-1")

        codex = clients["codex"]
        codex.steer_error = CodexRequestError("method not found: turn/steer", code=-32601)

        manager.submit(cid, client_request_id="q2", question="Queued later", document=doc)
        res = manager.submit(cid, client_request_id="q3", question="Immediate fallback", document=doc, immediate=True)

        assert res["status"] == "queued"
        assert len(codex.steers) == 1
        assert len(codex.interrupts) == 1 and codex.interrupts[0]["turnId"] == "turn-1"

        wait_for(lambda: (s := manager.get_snapshot(cid))["active_turn_id"] is None
                 and s["active_request_id"] is None and not s["queue"])
        start_prompts = [payload for kind, payload in codex.event_log if kind == "start"]
        assert "First question" in start_prompts[0]
        assert "Immediate fallback" in start_prompts[1]
        assert "Queued later" in start_prompts[2]
    finally:
        manager.close()


def test_claude_send_now_interrupts_active_turn_and_runs_ahead_of_queue(tmp_path: Path):
    manager, clients = _controllable_manager(_repo(tmp_path))
    try:
        opened = manager.open({"kind": "scene", "path": "one.md"}, agent="claude")
        cid = opened["conversation_id"]
        doc = {"kind": "scene", "path": "one.md"}

        manager.submit(cid, client_request_id="c1", question="HOLD_TURN Claude first", document=doc)
        wait_for(lambda: "claude" in clients and clients["claude"].first_turn_started.is_set())
        wait_for(lambda: manager.get_snapshot(cid)["active_turn_id"] == "claude-turn-1")

        manager.submit(cid, client_request_id="c2", question="Claude queued second", document=doc)
        res = manager.submit(cid, client_request_id="c3", question="Claude urgent", document=doc, immediate=True)

        assert res["status"] == "queued"
        claude = clients["claude"]
        assert len(claude.interrupts) == 1
        assert claude.interrupts[0]["turnId"] == "claude-turn-1"

        wait_for(lambda: (s := manager.get_snapshot(cid))["active_turn_id"] is None
                 and s["active_request_id"] is None and not s["queue"])
        start_prompts = [payload for kind, payload in claude.event_log if kind == "start"]
        assert "Claude first" in start_prompts[0]
        assert "Claude urgent" in start_prompts[1]
        assert "Claude queued second" in start_prompts[2]
    finally:
        manager.close()


def test_group_send_now_steers_codex_and_queues_second_seat_while_cancelling_stale_seat(tmp_path: Path):
    manager, clients = _controllable_manager(_repo(tmp_path), hold=("codex",))
    try:
        _group_cmd(manager, "submit", initial=_initial_group(manager), message_id="m1", text="Original both", seats=[1, 2])
        wait_for(lambda: "codex" in clients and clients["codex"].first_turn_started.is_set())
        wait_for(lambda: bool(manager._group_runs))

        _group_cmd(manager, "submit", message_id="m2", text="Steer both now", seats=[1, 2], immediate=True)

        codex = clients["codex"]
        assert len(codex.steers) == 1
        assert "Steer both now" in codex.steers[0]["input"][0]["text"]
        assert codex.interrupts == []

        state = _group_cmd(manager)
        stale_m1_seat2 = [s for s in state["steps"] if s.get("message_id") == "m1" and s["seat"] == 2]
        assert stale_m1_seat2 and stale_m1_seat2[0]["state"] == "cancelled"
        m2_seat2 = [s for s in state["steps"] if s.get("message_id") == "m2" and s["seat"] == 2]
        assert m2_seat2 and m2_seat2[0]["state"] == "queued"

        codex.first_turn_release.set()
        done = wait_for(lambda: (s := _group_cmd(manager))["status"] == "idle" and s)

        critic_turns = [t for t in done["turns"] if t["role"] == "critic"]
        assert [t["seat"] for t in critic_turns] == [1, 2]
        user_turns = [t["text"] for t in done["turns"] if t["role"] == "user"]
        assert user_turns == ["Original both", "Steer both now"]
        assert "Steer both now" in clients["claude"].prompts[0]
    finally:
        manager.close()


def test_group_send_now_interrupts_codex_to_follow_mention_order_when_claude_tagged_first(tmp_path: Path):
    manager, clients = _controllable_manager(_repo(tmp_path), hold=("codex",))
    try:
        _group_cmd(manager, "submit", initial=_initial_group(manager), message_id="m1", text="Codex working", seats=[1, 2])
        wait_for(lambda: "codex" in clients and clients["codex"].first_turn_started.is_set())
        wait_for(lambda: bool(manager._group_runs))

        _group_cmd(
            manager,
            "submit",
            message_id="m2",
            text="@VoiceEditor @StoryEditor answer in this order",
            seats=[2, 1],
            immediate=True,
        )

        codex = clients["codex"]
        assert codex.steers == []
        assert len(codex.interrupts) == 1

        done = wait_for(lambda: (s := _group_cmd(manager))["status"] == "idle" and any(t.get("message_id") == "m2" for t in s["turns"]) and s)
        critic_turns = [t for t in done["turns"] if t["role"] == "critic"]
        assert [t["seat"] for t in critic_turns] == [2, 1]
        assert done["error"] == ""
    finally:
        manager.close()


def test_group_send_now_interrupts_claude_active_turn_and_runs_both_tagged_seats(tmp_path: Path):
    manager, clients = _controllable_manager(_repo(tmp_path), hold=("claude",))
    try:
        _group_cmd(manager, "submit", initial=_initial_group(manager), message_id="m1", text="@VoiceEditor hold", seats=[2])
        wait_for(lambda: "claude" in clients and clients["claude"].first_turn_started.is_set())
        wait_for(lambda: bool(manager._group_runs))

        _group_cmd(manager, "submit", message_id="m2", text="@all urgent pivot", seats=[1, 2], immediate=True)

        claude = clients["claude"]
        assert len(claude.interrupts) == 1

        done = wait_for(lambda: (s := _group_cmd(manager))["status"] == "idle" and any(t.get("message_id") == "m2" for t in s["turns"]) and s)
        critic_turns = [t for t in done["turns"] if t["role"] == "critic"]
        assert [t["seat"] for t in critic_turns] == [1, 2]
        assert done["error"] == ""
    finally:
        manager.close()
