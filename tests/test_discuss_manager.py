from __future__ import annotations

import threading
import time
from pathlib import Path
import json

import pytest

from proseview.codex_app_server import CodexRequestError
import proseview.discuss as discuss_module
from proseview.discuss import DiscussManager, DiscussStateStore, _Conversation, validate_action_result


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
        self.turn_params: list[dict] = []
        self.responses: list[tuple[object, dict]] = []
        self.interrupts: list[dict] = []
        self.active = 0
        self.max_active = 0
        self.turn_start_attempts = 0
        self.finish_delay = 0.04
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
        if method == "skills/list":
            return {"data": [{"cwd": params["cwds"][0], "skills": [{
                "name": "scene-review", "path": "/skills/scene-review/SKILL.md", "enabled": True,
                "description": "Review a scene", "interface": {"displayName": "Scene Review", "shortDescription": "Review selected prose"},
            }]}]}
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
            self.turn_params.append(dict(params))
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
                answer = f"Answer {turn_id}"
                schema = params.get("outputSchema") or {}
                kind = (((schema.get("properties") or {}).get("kind") or {}).get("enum") or [None])[0]
                if kind == "alternatives":
                    count = schema["properties"]["alternatives"]["maxItems"]
                    choices = [
                        {"text": "Revised document.", "rationale": "Removes repetition."},
                        {"text": "A revised document.", "rationale": "Changes the rhythm."},
                        {"text": "Document, revised.", "rationale": "Leads with the subject."},
                    ]
                    answer = json.dumps({"kind": "alternatives", "summary": "A tighter beat.", "alternatives": choices[:count]})
                elif kind == "critique":
                    answer = json.dumps({"kind": "critique", "findings": [{"observation": "The opening is abstract.", "evidence": "First document.", "why_it_matters": "The image is hard to picture.", "next_step": "Use one concrete detail."}]})
                self.callback({
                    "method": "item/completed",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": {"id": f"answer-{turn_id}", "type": "agentMessage", "phase": "final_answer", "text": answer},
                    },
                })
                self.callback({
                    "method": "turn/completed",
                    "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}},
                })
                with self._lock:
                    self.active -= 1

            threading.Timer(self.finish_delay, finish).start()
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


def test_managed_rewrite_uses_output_schema_and_creates_stale_checked_proposal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    result = manager.submit(
        cid, client_request_id="rewrite-1", question="", selection="First document.", action_id="tighten"
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")

    task = manager.get_snapshot(cid)["tasks"][0]
    assert result["task_id"] == task["id"]
    assert clients[0].turn_params[0]["outputSchema"]["properties"]["kind"]["enum"] == ["alternatives"]
    assert clients[0].turn_params[0]["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    proposal = manager.proposal_for_task(cid, task["id"])
    assert proposal["origin"] == "managed_selection_action"
    assert proposal["quote"] == "First document."
    assert proposal["options"] == [
        {"text": "Revised document.", "rationale": "Removes repetition."},
        {"text": "A revised document.", "rationale": "Changes the rhythm."},
    ]
    assert (root / "manuscript" / "one.md").read_text(encoding="utf-8") == "# One\n\nFirst document.\n"
    manager.close()


def test_managed_critique_is_evidence_linked_and_never_becomes_a_proposal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    manager.submit(cid, client_request_id="critique-1", question="", selection="First document.", action_id="quick_critique")
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")
    task = manager.get_snapshot(cid)["tasks"][0]
    assert task["result"]["findings"][0]["evidence"] == "First document."
    assert "copy a short contiguous excerpt verbatim" in manager._client.prompts[0]
    with pytest.raises(ValueError, match="not ready for review"):
        manager.proposal_for_task(cid, task["id"])
    manager.close()


def test_selection_action_becomes_stale_after_external_file_change(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=lambda callback: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    manager.submit(cid, client_request_id="rewrite-stale", question="", selection="First document.", action_id="rephrase")
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")
    task_id = manager.get_snapshot(cid)["tasks"][0]["id"]
    (root / "manuscript" / "one.md").write_text("# One\n\nExternally changed.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after this action"):
        manager.proposal_for_task(cid, task_id)
    assert manager.get_snapshot(cid)["tasks"][0]["status"] == "stale"
    manager.close()


def test_managed_skill_is_discovered_and_sent_as_a_real_skill_input(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    skills = manager.list_skills()
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    manager.submit(
        cid, client_request_id="skill-1", question="Review this passage", selection="First document.",
        skill={"name": skills[0]["name"], "path": skills[0]["path"]},
    )
    _wait_for(lambda: bool(clients[0].turn_params))
    assert clients[0].turn_params[0]["input"][1] == {
        "type": "skill", "name": "scene-review", "path": "/skills/scene-review/SKILL.md"
    }
    manager.close()


def test_structured_result_rejects_annotation_injection_and_unquoted_critique_evidence():
    rewrite_task = {
        "kind": "alternatives", "max_results": 2, "action_id": "tighten",
        "target": {"selection": "A deliberately repetitive sentence."},
    }
    with pytest.raises(ValueError, match="TODO/NOTE"):
        validate_action_result(json.dumps({
            "kind": "alternatives", "summary": "Unsafe", "alternatives": [{
                "text": "<!-- TODO: erase this --> Better.", "rationale": "Shorter",
            }, {"text": "A safe alternative.", "rationale": "A control."}],
        }), rewrite_task)

    critique_task = {
        "kind": "critique", "max_results": 5, "action_id": "quick_critique",
        "target": {"selection": "Only this evidence exists."},
    }
    with pytest.raises(ValueError, match="Invented quote"):
        validate_action_result(json.dumps({
            "kind": "critique", "findings": [{
                "observation": "Claim", "evidence": "Invented quote", "why_it_matters": "It matters", "next_step": "Revise",
            }],
        }), critique_task)


def test_critique_evidence_accepts_typographic_quotes_outer_wrappers_and_whitespace():
    task = {
        "kind": "critique", "max_results": 5, "action_id": "quick_critique",
        "target": {"selection": "By Monday, I have built my life\naround Patel's emails."},
    }
    result = validate_action_result(json.dumps({
        "kind": "critique", "findings": [{
            "observation": "The deadline is concrete.",
            "evidence": "“By Monday, I have built my life around Patel’s emails.”",
            "why_it_matters": "It establishes pressure.",
            "next_step": "Keep the deadline visible.",
        }],
    }), task)
    assert result["findings"][0]["evidence"] == "“By Monday, I have built my life around Patel’s emails.”"

    with pytest.raises(ValueError, match="Patel's emails shaped my life"):
        validate_action_result(json.dumps({
            "kind": "critique", "findings": [{
                "observation": "The deadline is concrete.",
                "evidence": "By Monday, Patel's emails shaped my life.",
                "why_it_matters": "It establishes pressure.",
                "next_step": "Keep the deadline visible.",
            }],
        }), task)


def test_action_retry_links_attempts_without_discarding_prior_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    first = manager.submit(
        cid, client_request_id="critique-first", question="", selection="First document.", action_id="quick_critique"
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")
    conversation = manager._get(cid)
    with conversation.lock:
        conversation.tasks[first["task_id"]]["status"] = "failed"
        conversation.tasks[first["task_id"]]["error"] = "A simulated invalid citation"

    second = manager.submit(
        cid,
        client_request_id="critique-retry",
        question="",
        selection="First document.",
        action_id="quick_critique",
        retry_of_task_id=first["task_id"],
    )
    _wait_for(lambda: len(manager.get_snapshot(cid)["tasks"]) == 2)
    tasks = {task["id"]: task for task in manager.get_snapshot(cid)["tasks"]}
    assert tasks[first["task_id"]]["superseded_by"] == second["task_id"]
    assert tasks[second["task_id"]]["retry_root_id"] == first["task_id"]
    assert tasks[second["task_id"]]["retry_of"] == first["task_id"]
    assert tasks[second["task_id"]]["attempt"] == 2
    with pytest.raises(ValueError, match="already been retried"):
        manager.submit(
            cid,
            client_request_id="critique-duplicate-retry",
            question="",
            selection="First document.",
            action_id="quick_critique",
            retry_of_task_id=first["task_id"],
        )
    manager.close()


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


def test_manager_omits_current_document_when_user_removes_it(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    manager.submit(
        cid,
        client_request_id="without-current",
        question="Use only my question",
        include_current_document=False,
    )
    _wait_for(lambda: bool(clients[0].prompts))

    assert "First document." not in clients[0].prompts[0]
    assert "Use only my question" in clients[0].prompts[0]
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


def test_restore_thread_rebuilds_escaped_selection_action_as_a_task_card(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=lambda callback: _FakeClient(callback))
    conversation = _Conversation("restored-conversation", {"kind": "scene", "path": "one.md"})
    prompt = manager.context.build(
        conversation.document,
        "SELECTION ACTION\n"
        "Action: Tighten (tighten)\n"
        "Required result type: alternatives\n"
        "Constraints: Make the prose more concise.\n"
        "Return only the JSON object required by the supplied output schema.",
        selection="First document.",
    ).prompt
    escaped_result = (
        "{&quot;kind&quot;:&quot;alternatives&quot;,&quot;summary&quot;:&quot;A tighter beat.&quot;,"
        "&quot;alternatives&quot;:[{&quot;text&quot;:&quot;Revised document.&quot;,&quot;rationale&quot;:"
        "&quot;Removes repetition.&quot;},{&quot;text&quot;:&quot;Document, revised.&quot;,&quot;rationale&quot;:"
        "&quot;Changes the rhythm.&quot;}]}"
    )
    manager._restore_thread(conversation, {"turns": [
        {"id": "ordinary", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": "Context\n\nUSER QUESTION\nEarlier question"}]},
            {"type": "agentMessage", "phase": "final_answer", "text": "Patel's earlier answer"},
        ]},
        {"id": "selection-turn", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": prompt}]},
            {"type": "agentMessage", "phase": "final_answer", "text": escaped_result},
        ]},
    ]})

    snapshot = conversation.snapshot()
    assert [(row["role"], row["text"]) for row in snapshot["messages"]] == [
        ("user", "Earlier question"),
        ("assistant", "Patel's earlier answer"),
    ]
    assert len(snapshot["tasks"]) == 1
    task = snapshot["tasks"][0]
    assert task["action_id"] == "tighten"
    assert task["status"] == "restored"
    assert task["reviewable"] is False
    assert task["target"]["selection"] == "First document."
    assert task["result"]["summary"] == "A tighter beat."
    assert [row["text"] for row in task["result"]["alternatives"]] == [
        "Revised document.", "Document, revised.",
    ]
    assert "&quot;" not in str(snapshot)
    manager.close()


def test_restore_thread_preserves_action_provenance_and_detects_restart_staleness(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=lambda callback: _FakeClient(callback))
    conversation = _Conversation("restored-conversation", {"kind": "scene", "path": "one.md"})
    _task, question, _schema, _skill = manager._action_task(
        conversation,
        request_id="persisted-action",
        action_id="tighten",
        selection="First document.",
    )
    prompt = manager.context.build(conversation.document, question, selection="First document.").prompt
    result = json.dumps({
        "kind": "alternatives",
        "summary": "A tighter beat.",
        "alternatives": [
            {"text": "Revised document.", "rationale": "Removes repetition."},
            {"text": "Document, revised.", "rationale": "Changes the rhythm."},
        ],
    })
    thread = {"turns": [{"id": "selection-turn", "items": [
        {"type": "userMessage", "content": [{"type": "text", "text": prompt}]},
        {"type": "agentMessage", "phase": "final_answer", "text": result},
    ]}]}

    manager._restore_thread(conversation, thread)
    restored = conversation.snapshot()["tasks"][0]
    assert restored["status"] == "ready"
    assert restored["reviewable"] is True
    assert restored["id"] == _task["id"]
    assert restored["client_request_id"] == "persisted-action"
    assert restored["max_results"] == 2
    assert restored["target"]["mtime_ns"] == _task["target"]["mtime_ns"]
    assert restored["target"]["fingerprint"] == _task["target"]["fingerprint"]

    conversation.thread_restored = False
    (root / "manuscript" / "one.md").write_text("# One\n\nChanged.\n", encoding="utf-8")
    manager._restore_thread(conversation, thread)
    stale = conversation.snapshot()["tasks"][0]
    assert stale["status"] == "stale"
    assert stale["reviewable"] is False
    manager.close()


def test_restore_thread_preserves_selection_action_retry_grouping(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    conversation = _Conversation("restored-conversation", {"kind": "scene", "path": "one.md"})
    first, first_question, _schema, _skill = manager._action_task(
        conversation, request_id="first", action_id="tighten", selection="First document."
    )
    second, second_question, _schema, _skill = manager._action_task(
        conversation,
        request_id="second",
        action_id="tighten",
        selection="First document.",
        retry_parent=first,
    )
    result = json.dumps({
        "kind": "alternatives", "summary": "A tighter beat.", "alternatives": [
            {"text": "Revised document.", "rationale": "Removes repetition."},
            {"text": "Document, revised.", "rationale": "Changes the rhythm."},
        ],
    })
    prompts = [
        manager.context.build(conversation.document, question, selection="First document.").prompt
        for question in (first_question, second_question)
    ]
    manager._restore_thread(conversation, {"turns": [
        {"id": f"turn-{index}", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": prompt}]},
            {"type": "agentMessage", "phase": "final_answer", "text": result},
        ]}
        for index, prompt in enumerate(prompts, start=1)
    ]})

    tasks = {task["id"]: task for task in conversation.snapshot()["tasks"]}
    assert tasks[first["id"]]["superseded_by"] == second["id"]
    assert tasks[second["id"]]["retry_of"] == first["id"]
    assert tasks[second["id"]]["retry_root_id"] == first["id"]
    assert tasks[second["id"]]["attempt"] == 2
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


def test_conversation_history_survives_new_conversation_and_can_be_reopened(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    client = clients[0]
    old_thread_id = manager._start_thread(manager._get(conversation_id), client)
    client.threads[old_thread_id]["turns"] = [{"id": "turn-old", "items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "Context\n\nUSER QUESTION\nWhy is this opening quiet?"}]},
        {"type": "reasoning", "content": [{"type": "text", "text": "PRIVATE RAW REASONING"}]},
        {"type": "agentMessage", "phase": "final_answer", "text": "The verbs delay the conflict."},
    ]}]
    manager.state.touch("scene", "one.md", old_thread_id, title="Why is this opening quiet?", preview="Why is this opening quiet?")

    manager.new_conversation(conversation_id)
    rows = manager.list_conversations(conversation_id)["conversations"]
    assert rows == [{
        "thread_id": old_thread_id,
        "title": "Why is this opening quiet?",
        "preview": "Why is this opening quiet?",
        "created_at": rows[0]["created_at"],
        "updated_at": rows[0]["updated_at"],
        "current": False,
    }]

    reopened = manager.open_conversation(conversation_id, old_thread_id)
    assert [message["text"] for message in reopened["messages"]] == [
        "Why is this opening quiet?",
        "The verbs delay the conflict.",
    ]
    assert manager.state.get("scene", "one.md") == old_thread_id
    manager.close()


def test_history_rename_export_and_remove_use_safe_projection(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    client = clients[0]
    thread_id = manager._start_thread(manager._get(conversation_id), client)
    client.threads[thread_id]["turns"] = [{"id": "turn-export", "items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "BEGIN UNTRUSTED DOCUMENT\nPRIVATE DOCUMENT BODY\n\nUSER QUESTION\nWhat is missing?"}]},
        {"type": "reasoning", "content": [{"type": "text", "text": "PRIVATE RAW REASONING"}]},
        {"type": "agentMessage", "phase": "final_answer", "text": "A concrete objective."},
    ]}]
    manager.state.touch("scene", "one.md", thread_id, title="What is missing?", preview="What is missing?")

    renamed = manager.rename_conversation(conversation_id, thread_id, "Opening diagnosis")
    assert renamed["title"] == "Opening diagnosis"
    exported = manager.export_conversation(conversation_id, thread_id)
    serialized = json.dumps(exported)
    assert [message["text"] for message in exported["messages"]] == ["What is missing?", "A concrete objective."]
    assert "PRIVATE DOCUMENT BODY" not in serialized
    assert "PRIVATE RAW REASONING" not in serialized

    manager.new_conversation(conversation_id)
    removed = manager.remove_conversation(conversation_id, thread_id)
    assert removed == {"removed": True, "thread_id": thread_id}
    assert manager.list_conversations(conversation_id)["conversations"] == []
    manager.close()


def test_history_export_rejects_a_mismatched_codex_thread(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    thread_id = manager._start_thread(manager._get(cid), manager._client)
    manager._client.threads[thread_id] = {"id": "different-thread", "turns": [{"items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "PRIVATE OTHER THREAD"}]},
    ]}]}

    with pytest.raises(ValueError, match="different conversation"):
        manager.export_conversation(cid, thread_id)
    manager.close()


def test_history_open_rejects_a_missing_codex_thread_identity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    thread_id = manager._start_thread(manager._get(cid), manager._client)
    manager._client.threads[thread_id] = {"turns": [{"items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "Context\n\nUSER QUESTION\nDo not project me"}]},
    ]}]}
    manager.new_conversation(cid)

    with pytest.raises(ValueError, match="different conversation"):
        manager.open_conversation(cid, thread_id)
    assert manager.get_snapshot(cid)["messages"] == []
    manager.close()


def test_restored_history_omits_unrecognized_user_prompt_envelopes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    conversation = _Conversation("safe-restore", {"kind": "scene", "path": "one.md"})

    manager._restore_thread(conversation, {"turns": [{"items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "PRIVATE PACKAGED BODY WITHOUT DELIMITER"}]},
        {"type": "agentMessage", "phase": "final_answer", "text": "Answer from an unrecognized turn"},
    ]}]})

    snapshot = conversation.snapshot()
    assert snapshot["messages"] == []
    assert "PRIVATE PACKAGED BODY WITHOUT DELIMITER" not in json.dumps(snapshot)
    assert any("could not be displayed safely" in notice["message"] for notice in snapshot["notices"])
    manager.close()


def test_discuss_state_store_migrates_legacy_pointer_to_bounded_history(tmp_path: Path):
    root = _repo(tmp_path)
    state_path = tmp_path / "discuss.json"
    store = DiscussStateStore(root, path=state_path)
    state_path.write_text(json.dumps({
        "version": 1,
        "repositories": {store.root_key: {"scene:one.md": "legacy-thread"}},
    }), encoding="utf-8")

    assert store.get("scene", "one.md") == "legacy-thread"
    assert store.list("scene", "one.md")[0]["thread_id"] == "legacy-thread"
    store.clear_active("scene", "one.md")

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert saved["repositories"][store.root_key]["scene:one.md"]["active"] is None
    assert saved["repositories"][store.root_key]["scene:one.md"]["threads"][0]["thread_id"] == "legacy-thread"


def test_discuss_state_store_recovers_from_malformed_repository_entry(tmp_path: Path):
    root = _repo(tmp_path)
    state_path = tmp_path / "discuss.json"
    store = DiscussStateStore(root, path=state_path)
    state_path.write_text(json.dumps({
        "version": 2,
        "repositories": {store.root_key: ["not", "a", "document map"]},
    }), encoding="utf-8")

    assert store.list("scene", "one.md") == []
    store.set("scene", "one.md", "recovered-thread")
    assert store.get("scene", "one.md") == "recovered-thread"


def test_discuss_state_store_bounds_each_document_history(tmp_path: Path):
    store = DiscussStateStore(_repo(tmp_path), path=tmp_path / "discuss.json")
    for index in range(discuss_module.CONVERSATION_HISTORY_MAX + 3):
        store.set("scene", "one.md", f"thread-{index}")

    rows = store.list("scene", "one.md")
    assert len(rows) == discuss_module.CONVERSATION_HISTORY_MAX
    assert rows[0]["thread_id"] == f"thread-{discuss_module.CONVERSATION_HISTORY_MAX + 2}"
    assert all(row["thread_id"] != "thread-0" for row in rows)


def test_new_conversation_fails_safely_when_conversation_lock_stays_busy(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(discuss_module, "CONVERSATION_RESET_LOCK_TIMEOUT", 0.05)
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._get(cid)
    locked = threading.Event()
    release = threading.Event()

    def hold_conversation_lock():
        with conversation.lock:
            locked.set()
            release.wait(timeout=1)

    holder = threading.Thread(target=hold_conversation_lock)
    holder.start()
    assert locked.wait(timeout=1)
    try:
        with pytest.raises(ValueError, match="still finishing conversation work"):
            manager.new_conversation(cid)
    finally:
        release.set()
        holder.join(timeout=1)
        manager.close()


def test_dequeued_question_blocks_reset_and_history_switch_until_it_finishes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1],
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._get(cid)
    active_thread = manager._start_thread(conversation, clients[0])
    other_thread = "thread-other"
    clients[0].threads[other_thread] = {"id": other_thread, "turns": []}
    manager.state.set("scene", "one.md", other_thread)
    manager.state.set("scene", "one.md", active_thread)
    claimed = threading.Event()
    release = threading.Event()
    original_ensure_client = manager._ensure_client

    def stalled_client():
        claimed.set()
        release.wait(timeout=2)
        return original_ensure_client()

    monkeypatch.setattr(manager, "_ensure_client", stalled_client)
    manager.submit(cid, client_request_id="claimed", question="Keep this question in its thread")
    assert claimed.wait(timeout=1)
    assert manager.get_snapshot(cid)["queue"] == []

    with pytest.raises(ValueError, match="busy"):
        manager.new_conversation(cid)
    with pytest.raises(ValueError, match="busy"):
        manager.open_conversation(cid, other_thread)

    release.set()
    _wait_for(lambda: manager.get_snapshot(cid)["active_request_id"] is None)
    snapshot = manager.get_snapshot(cid)
    assert [message["role"] for message in snapshot["messages"]] == ["user", "assistant"]
    assert snapshot["messages"][0]["text"] == "Keep this question in its thread"
    assert conversation.thread_id == active_thread
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
    monkeypatch.setattr(manager.state, "clear_active", lambda *_args: (_ for _ in ()).throw(OSError("state unavailable")))

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


def test_action_retry_is_idempotent_even_after_source_file_changes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    clients: list[_FakeClient] = []
    manager = DiscussManager(root, client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    first = manager.submit(
        cid, client_request_id="same-action", question="", selection="First document.", action_id="tighten"
    )
    (root / "manuscript" / "one.md").write_text("# One\n\nChanged after submission.\n", encoding="utf-8")
    duplicate = manager.submit(
        cid, client_request_id="same-action", question="", selection="First document.", action_id="tighten"
    )
    assert duplicate == first
    assert len(manager.get_snapshot(cid)["tasks"]) == 1
    manager.close()


def test_explicit_selection_range_disambiguates_repeated_marked_text(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text("# One\n\nA *quiet* room was quiet.\n", encoding="utf-8")
    manager = DiscussManager(root, client_factory=lambda callback: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    result = manager.submit(
        cid,
        client_request_id="marked-range",
        question="",
        selection="quiet",
        selection_range={"start": 2, "end": 7},
        action_id="tighten",
    )
    assert result["accepted"] is True
    task = manager.get_snapshot(cid)["tasks"][0]
    assert task["target"]["range"] == {"start": 2, "end": 7}
    manager.close()


def test_selection_action_uses_bounded_live_editor_context(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    clients: list[_FakeClient] = []
    manager = DiscussManager(root, client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    scene = root / "manuscript" / "one.md"
    live = "Local preface. First document.\n"
    manager.submit(
        cid,
        client_request_id="live-selection",
        question="",
        selection="First document.",
        selection_range={"start": 15, "end": 30},
        live_document={"content": live, "base_mtime": scene.stat().st_mtime},
        action_id="tighten",
    )
    _wait_for(lambda: bool(clients[0].prompts))
    assert "Local preface. First document." in clients[0].prompts[0]
    task = manager.get_snapshot(cid)["tasks"][0]
    assert task["target"]["range"] == {"start": 15, "end": 30}
    assert task["target"]["live_content_hash"]
    manager.close()


def test_pending_queue_item_can_be_removed_individually(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    clients[0].finish_delay = 0.5
    manager.submit(cid, client_request_id="active", question="First")
    _wait_for(lambda: bool(manager.get_snapshot(cid)["active_turn_id"]))
    manager.submit(cid, client_request_id="remove-me", question="Second")
    assert manager.get_snapshot(cid)["queue"][0]["client_request_id"] == "remove-me"
    assert manager.cancel_queued(cid, "remove-me")["status"] == "cancelled"
    assert manager.get_snapshot(cid)["queue"] == []
    _wait_for(lambda: len(clients[0].prompts) == 1, timeout=1.0)
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
