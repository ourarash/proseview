from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from proseview.codex_app_server import CodexRequestError
from proseview.discuss import DiscussManager, _Conversation


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript").mkdir(parents=True)
    (root / "manuscript" / "one.md").write_text("# One\n\nFirst document.\n", encoding="utf-8")
    (root / "manuscript" / "two.md").write_text("# Two\n\nSecond document.\n", encoding="utf-8")
    return root


class _FakeClient:
    def __init__(self, callback):
        self.callback = callback
        self.alive = True
        self.next_thread = 0
        self.next_turn = 0
        self.prompts: list[str] = []
        self.responses: list[tuple[object, dict]] = []
        self.interrupts: list[dict] = []
        self.active = 0
        self.max_active = 0
        self.turn_start_attempts = 0
        self.reject_turn_starts = False
        self.capabilities = {"reasoning_summary": True}
        self.threads: dict[str, dict] = {}
        self._lock = threading.Lock()

    def inspect_capabilities(self):
        return {"stable_discuss_protocol": True}

    def probe_capabilities(self):
        return {"stable_discuss_protocol": True}

    def start(self):
        return None

    def request(self, method, params):
        if method == "thread/read":
            thread = self.threads.get(params["threadId"])
            if thread is None:
                raise CodexRequestError(f"thread not found: {params['threadId']}", code=-32004)
            return {"thread": thread}
        if method == "thread/start":
            self.next_thread += 1
            thread = {"id": f"thread-{self.next_thread}", "turns": []}
            self.threads[thread["id"]] = thread
            return {"thread": thread}
        if method == "turn/start":
            self.turn_start_attempts += 1
            if self.reject_turn_starts:
                raise CodexRequestError(f"thread not found: {params['threadId']}", code=-32004)
            if params["threadId"] not in self.threads:
                raise CodexRequestError(f"thread not found: {params['threadId']}", code=-32004)
            self.next_turn += 1
            turn_id = f"turn-{self.next_turn}"
            thread_id = params["threadId"]
            self.prompts.append(params["input"][0]["text"])
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)

            def finish():
                self.callback({
                    "method": "item/reasoning/textDelta",
                    "params": {"threadId": thread_id, "turnId": turn_id, "delta": "RAW SECRET"},
                })
                self.callback({
                    "method": "item/reasoning/summaryTextDelta",
                    "params": {"threadId": thread_id, "turnId": turn_id, "delta": "Reading context"},
                })
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
                with self._lock:
                    self.active -= 1

            threading.Timer(0.04, finish).start()
            return {"turn": {"id": turn_id, "status": "inProgress"}}
        if method == "turn/interrupt":
            self.interrupts.append(dict(params))
            return {}
        raise AssertionError(method)

    def respond(self, request_id, result):
        self.responses.append((request_id, result))

    def respond_error(self, request_id, message):
        self.responses.append((request_id, {"error": message}))

    def close(self):
        self.alive = False


def _wait_for(predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_manager_serializes_one_document_and_filters_raw_reasoning(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []

    def factory(callback):
        client = _FakeClient(callback)
        clients.append(client)
        return client

    manager = DiscussManager(_repo(tmp_path), client_factory=factory)
    opened = manager.open({"kind": "scene", "path": "one.md"})
    cid = opened["conversation_id"]
    manager.submit(cid, client_request_id="a", question="First?")
    manager.submit(cid, client_request_id="b", question="Second?")
    _wait_for(lambda: len([m for m in manager.get_snapshot(cid)["messages"] if m["role"] == "assistant"]) == 2)

    snapshot = manager.get_snapshot(cid)
    assert [m["text"] for m in snapshot["messages"] if m["role"] == "assistant"] == ["Answer turn-1", "Answer turn-2"]
    assert "RAW SECRET" not in str(snapshot)
    assert snapshot["progress"] == ["Reading context"]
    assert clients[0].max_active == 1
    assert "First document." in clients[0].prompts[0]
    manager.close()


def test_manager_runs_different_documents_concurrently_and_is_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []

    def factory(callback):
        client = _FakeClient(callback)
        clients.append(client)
        return client

    manager = DiscussManager(_repo(tmp_path), client_factory=factory)
    one = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    two = manager.open({"kind": "scene", "path": "two.md"})["conversation_id"]
    first = manager.submit(one, client_request_id="same", question="One?")
    duplicate = manager.submit(one, client_request_id="same", question="Ignored duplicate")
    manager.submit(two, client_request_id="other", question="Two?")
    _wait_for(lambda: len(clients[0].prompts) == 2)

    assert first["client_request_id"] == duplicate["client_request_id"] == "same"
    assert first["accepted"] is duplicate["accepted"] is True
    assert clients[0].max_active == 2
    assert sum("One?" in prompt for prompt in clients[0].prompts) == 1
    assert not any("Ignored duplicate" in prompt for prompt in clients[0].prompts)
    manager.close()


def test_open_revalidates_and_forgets_a_cached_thread_that_codex_lost(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    conversation = manager._conversations[conversation_id]
    thread_id = manager._start_thread(conversation, clients[0])
    clients[0].threads.pop(thread_id)

    reopened = manager.open(document)

    assert reopened["connection"] == "Live"
    assert conversation.thread_id is None
    assert manager.state.get("scene", "one.md") is None
    manager.close()


def test_opening_a_valid_cached_thread_does_not_rewrite_unchanged_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    manager._start_thread(manager._conversations[conversation_id], clients[0])
    monkeypatch.setattr(manager.state, "set", lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected write")))

    reopened = manager.open(document)

    assert reopened["connection"] == "Live"
    assert reopened["unavailable_reason"] == ""
    manager.close()


def test_open_does_not_replace_local_messages_while_work_is_active(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    conversation = manager._conversations[conversation_id]
    thread_id = manager._start_thread(conversation, clients[0])
    clients[0].threads[thread_id]["turns"] = [{
        "items": [{"type": "userMessage", "content": [{"type": "text", "text": "Older question"}]}],
    }]
    conversation.messages = [
        {"role": "user", "text": "Older question"},
        {"role": "user", "text": "Queued question"},
    ]
    conversation.active_turn_id = "turn-active"
    conversation.active_done = threading.Event()

    reopened = manager.open(document)

    assert [message["text"] for message in reopened["messages"]] == ["Older question", "Queued question"]
    conversation.active_done.set()
    conversation.active_done = None
    conversation.active_turn_id = None
    manager.close()


def test_missing_thread_retries_the_same_question_once_on_a_new_thread(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    conversation = manager._conversations[conversation_id]
    stale_thread_id = manager._start_thread(conversation, clients[0])
    clients[0].threads.pop(stale_thread_id)

    manager.submit(conversation_id, client_request_id="recover", question="Can we continue?")
    _wait_for(lambda: any(message["role"] == "assistant" for message in manager.get_snapshot(conversation_id)["messages"]))

    snapshot = manager.get_snapshot(conversation_id)
    assert snapshot["connection"] == "Live"
    assert conversation.thread_id != stale_thread_id
    assert sum("Can we continue?" in prompt for prompt in clients[0].prompts) == 1
    assert any("new conversation" in notice["message"].lower() for notice in snapshot["notices"])
    manager.close()


def test_new_conversation_clears_projection_and_uses_a_new_thread(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    manager.submit(conversation_id, client_request_id="before", question="First thread")
    _wait_for(
        lambda: manager.get_snapshot(conversation_id)["active_turn_id"] is None
        and any(message["role"] == "assistant" for message in manager.get_snapshot(conversation_id)["messages"])
    )
    old_thread_id = manager._conversations[conversation_id].thread_id

    reset = manager.new_conversation(conversation_id)

    assert reset["messages"] == []
    assert reset["notices"] == []
    assert manager.state.get("scene", "one.md") is None
    manager.submit(conversation_id, client_request_id="after", question="Second thread")
    _wait_for(lambda: any(message["role"] == "assistant" for message in manager.get_snapshot(conversation_id)["messages"]))
    assert manager._conversations[conversation_id].thread_id != old_thread_id
    manager.close()


def test_missing_thread_recovery_is_bounded_to_one_retry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    conversation_id = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[conversation_id]
    manager._start_thread(conversation, clients[0])
    clients[0].reject_turn_starts = True

    manager.submit(conversation_id, client_request_id="bounded", question="Do not loop")
    _wait_for(lambda: manager.get_snapshot(conversation_id)["connection"] == "Unavailable")

    assert clients[0].turn_start_attempts == 2
    assert "thread not found" in manager.get_snapshot(conversation_id)["unavailable_reason"]
    manager.close()


def test_new_conversation_keeps_memory_mapping_when_durable_reset_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    conversation_id = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[conversation_id]
    thread_id = manager._start_thread(conversation, clients[0])
    conversation.messages = [{"role": "user", "text": "Keep me"}]
    monkeypatch.setattr(manager.state, "delete", lambda *_args: (_ for _ in ()).throw(OSError("state unavailable")))

    with pytest.raises(OSError, match="state unavailable"):
        manager.new_conversation(conversation_id)

    assert conversation.thread_id == thread_id
    assert conversation.messages == [{"role": "user", "text": "Keep me"}]
    manager.close()


def test_manager_surfaces_and_resolves_allowlisted_approval(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    manager._on_codex_message({
        "id": 91,
        "method": "item/commandExecution/requestApproval",
        "params": {
            "threadId": thread_id,
            "turnId": "turn-x",
            "itemId": "command-x",
            "command": "printf safe",
            "availableDecisions": ["accept", "decline"],
        },
    })

    approval = manager.get_snapshot(cid)["approvals"][0]
    assert approval["kind"] == "command"
    manager.approve(cid, "91", "decline")
    assert clients[0].responses == [(91, {"decision": "decline"})]
    assert manager.get_snapshot(cid)["approvals"][0]["status"] == "resolved"
    manager.close()


def test_restored_history_exposes_question_not_packaged_documents(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    cid = manager._conversation_id({"kind": "scene", "path": "one.md"})
    conversation = manager._conversations.setdefault(cid, _Conversation(cid, {"kind": "scene", "path": "one.md"}))
    manager._restore_thread(conversation, {
        "turns": [{"items": [
            {"type": "userMessage", "content": [{"type": "text", "text": "BEGIN UNTRUSTED DOCUMENT\nPRIVATE DOCUMENT BODY\n\nUSER QUESTION\nWhat is missing?"}]},
            {"type": "reasoning", "content": ["PRIVATE RAW REASONING"]},
            {"type": "agentMessage", "phase": "final_answer", "text": "A requirement."},
        ]}]
    })
    snapshot = conversation.snapshot()
    assert snapshot["messages"][0]["text"] == "What is missing?"
    assert "PRIVATE DOCUMENT BODY" not in str(snapshot)
    assert "PRIVATE RAW REASONING" not in str(snapshot)
    manager.close()


def test_concurrent_duplicate_submissions_enqueue_once(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    barrier = threading.Barrier(3)
    results: list[dict] = []

    def submit():
        barrier.wait()
        results.append(manager.submit(cid, client_request_id="duplicate", question="Only once"))

    workers = [threading.Thread(target=submit) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()
    _wait_for(lambda: len(clients[0].prompts) == 1)
    assert len(results) == 2 and results[0] == results[1]
    assert len([message for message in manager.get_snapshot(cid)["messages"] if message["role"] == "user"]) == 1
    manager.close()


def test_network_file_and_permission_approvals_are_allowlisted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    requests = [
        (101, "item/commandExecution/requestApproval", {"networkApprovalContext": {"host": "example.test"}}, "network"),
        (102, "item/fileChange/requestApproval", {}, "fileChange"),
        (103, "item/permissions/requestApproval", {"permissions": {"filesystem": ["one.md"]}}, "permissions"),
    ]
    for request_id, method, extra, expected_kind in requests:
        manager._on_codex_message({
            "id": request_id,
            "method": method,
            "params": {
                "threadId": thread_id,
                "turnId": "turn-x",
                "itemId": f"item-{request_id}",
                "availableDecisions": ["accept", "decline"],
                **extra,
            },
        })
        approval = next(item for item in manager.get_snapshot(cid)["approvals"] if item["request_id"] == str(request_id))
        assert approval["kind"] == expected_kind

    manager.approve(cid, "101", "decline")
    manager.approve(cid, "102", "accept")
    manager.approve(cid, "103", "accept", {"permissions": {"filesystem": ["one.md"], "network": ["bad"]}})
    assert clients[0].responses[-1] == (103, {"permissions": {"filesystem": ["one.md"]}, "scope": "turn"})
    manager.close()


def test_approval_without_advertised_decisions_is_declined(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    manager._on_codex_message({
        "id": 104,
        "method": "item/fileChange/requestApproval",
        "params": {"threadId": thread_id, "turnId": "turn-x", "itemId": "item-x"},
    })
    assert clients[0].responses == [(104, {"decision": "decline"})]
    assert manager.get_snapshot(cid)["approvals"] == []
    manager.close()
