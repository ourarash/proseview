"""One behaviour suite, run against both agent transports.

``sanitize_agent_message`` is documented as the seam where a wire protocol
becomes Prosview's event vocabulary, and everything above it is supposed to be
indifferent to which agent answered. That claim was only ever tested against
Codex.

Every test here runs twice, once per agent, against doubles that speak
genuinely different protocols. A failure on one agent and not the other means
a translator disagrees with its sibling — which is exactly the bug this suite
exists to catch, because in the product it would surface as a feature that
silently works on one tab and not the other.

Codex-specific depth (continuity reports, proposal staleness, thread recovery)
stays in ``test_discuss_manager.py``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from proseview.discuss import ContextError, DiscussManager

from .transport_fakes import ClaudeFakeClient, CodexFakeClient, fake_factory

AGENTS = ["codex", "claude"]


@pytest.fixture(params=AGENTS)
def agent(request):
    return request.param


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "novel"
    (root / "manuscript").mkdir(parents=True)
    (root / "manuscript" / "one.md").write_text("# One\n\nFirst document.\n", encoding="utf-8")
    (root / "manuscript" / "two.md").write_text("# Two\n\nSecond document.\n", encoding="utf-8")
    return root


@pytest.fixture
def session(repo: Path, agent: str):
    """A manager, an open conversation on the agent under test, and its client."""
    manager = DiscussManager(repo, client_factory=fake_factory)
    cid = manager.open({"kind": "scene", "path": "one.md"}, agent)["conversation_id"]

    class _Session:
        def __init__(self):
            self.manager = manager
            self.cid = cid
            self.agent = agent

        @property
        def client(self):
            return manager._client_for(agent)

        def snapshot(self):
            return manager.get_snapshot(cid)

    try:
        yield _Session()
    finally:
        manager.close()


def _wait_for(predicate, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def _wait_for_settled_answer(session):
    """An assistant message, and the turn that produced it finished.

    Assistant text reaches the projection before turn teardown runs, so waiting
    on the message alone leaves the conversation briefly busy -- long enough, on
    a loaded runner, for the next manager call to be refused as busy.
    """
    def settled():
        snapshot = session.snapshot()
        return bool(
            any(m["role"] == "assistant" for m in snapshot["messages"])
            and snapshot["active_turn_id"] is None
            and snapshot["active_request_id"] is None
        )

    _wait_for(settled)


# --- identity ---------------------------------------------------------------

def test_snapshot_reports_the_agent_that_owns_it(session):
    assert session.snapshot()["agent"] == session.agent


def test_the_manager_uses_the_transports_own_translator(session):
    translator = session.manager._translators[session.agent]
    expected = getattr(type(session.client), "translate", None)
    if expected is None:
        from proseview.discuss import sanitize_agent_message

        assert translator is sanitize_agent_message
    else:
        assert translator is expected


# --- a plain question -------------------------------------------------------

def test_a_question_produces_an_assistant_message(session):
    session.manager.submit(session.cid, client_request_id="q1", question="What happens here?")
    _wait_for(lambda: any(
        m["role"] == "assistant" for m in session.snapshot()["messages"]
    ))
    messages = session.snapshot()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["text"] == "What happens here?"
    assert messages[1]["text"]


def test_the_document_and_question_reach_the_agent(session):
    session.manager.submit(session.cid, client_request_id="q1", question="Whose voice is this?")
    _wait_for(lambda: bool(session.client.prompts))
    prompt = session.client.prompts[-1]
    assert "USER QUESTION" in prompt
    assert "Whose voice is this?" in prompt
    assert "First document." in prompt


def test_the_project_conversation_survives_document_navigation(session):
    """A file chooses turn context; it does not own the agent thread."""
    session.manager.submit(session.cid, client_request_id="q1", question="Remember this opening")
    _wait_for_settled_answer(session)
    before = session.snapshot()

    reopened = session.manager.open({"kind": "scene", "path": "two.md"}, session.agent)

    assert reopened["conversation_id"] == session.cid
    assert reopened["messages"] == before["messages"]
    session.manager.submit(
        session.cid,
        client_request_id="q2",
        question="What changes here?",
        document={"kind": "scene", "path": "two.md"},
    )
    _wait_for(lambda: len(session.client.prompts) == 2)
    assert "Second document." in session.client.prompts[-1]
    assert "First document." not in session.client.prompts[-1]
    assert session.manager.list_conversations(session.cid)["conversations"]


def test_raw_reasoning_never_reaches_the_projection(session):
    """Both transports drop unedited model reasoning at the seam."""
    session.manager.submit(session.cid, client_request_id="q1", question="Think about this")
    _wait_for(lambda: any(m["role"] == "assistant" for m in session.snapshot()["messages"]))
    snapshot = session.snapshot()
    blob = repr(snapshot)
    assert "RAW SECRET" not in blob
    # The summarised progress line is what the writer is allowed to see.
    assert any("Reading context" in line for line in snapshot["progress"])


# --- selection actions ------------------------------------------------------

def test_a_selection_action_is_validated_into_alternatives(session):
    session.manager.submit(
        session.cid,
        client_request_id="a1",
        question="",
        selection="First document.",
        action_id="tighten",
    )
    _wait_for(lambda: session.snapshot()["tasks"] and
              session.snapshot()["tasks"][0]["status"] in {"ready", "failed"})
    task = session.snapshot()["tasks"][0]
    assert task["status"] == "ready", task.get("error")
    assert task["kind"] == "alternatives"
    assert len(task["result"]["alternatives"]) == 2
    assert all(row["text"] and row["rationale"] for row in task["result"]["alternatives"])


def test_a_selection_action_sends_its_output_schema(session):
    session.manager.submit(
        session.cid,
        client_request_id="a1",
        question="",
        selection="First document.",
        action_id="tighten",
    )
    _wait_for(lambda: bool(session.client.turn_params))
    schema = session.client.turn_params[-1].get("outputSchema")
    assert schema, "a structured action must carry its schema to the agent"
    assert schema["properties"]["kind"]["enum"] == ["alternatives"]


def test_a_critique_is_validated_into_findings(session):
    session.manager.submit(
        session.cid,
        client_request_id="c1",
        question="",
        selection="First document.",
        action_id="quick_critique",
    )
    _wait_for(lambda: session.snapshot()["tasks"] and
              session.snapshot()["tasks"][0]["status"] in {"ready", "failed"})
    task = session.snapshot()["tasks"][0]
    assert task["status"] == "ready", task.get("error")
    assert task["result"]["findings"][0]["observation"]


def test_structured_results_never_appear_as_chat(session):
    """A structured action has its own UI; its JSON must not leak into the log."""
    session.manager.submit(
        session.cid,
        client_request_id="a1",
        question="",
        selection="First document.",
        action_id="tighten",
    )
    _wait_for(lambda: session.snapshot()["tasks"] and
              session.snapshot()["tasks"][0]["status"] == "ready")
    assert session.snapshot()["messages"] == []


# --- queueing and turn lifecycle --------------------------------------------

def test_questions_queue_and_drain_in_order(session):
    session.manager.submit(session.cid, client_request_id="q1", question="First question")
    session.manager.submit(session.cid, client_request_id="q2", question="Second question")
    _wait_for(lambda: len([
        m for m in session.snapshot()["messages"] if m["role"] == "assistant"
    ]) == 2, timeout=5.0)
    asked = [p for p in session.client.prompts]
    assert "First question" in asked[0]
    assert "Second question" in asked[1]


def test_a_repeated_request_id_is_accepted_once(session):
    first = session.manager.submit(session.cid, client_request_id="dup", question="Only once")
    second = session.manager.submit(session.cid, client_request_id="dup", question="Only once")
    assert first["client_request_id"] == second["client_request_id"]
    _wait_for(lambda: any(m["role"] == "assistant" for m in session.snapshot()["messages"]))
    assert len([m for m in session.snapshot()["messages"] if m["role"] == "user"]) == 1


def test_a_queued_question_can_be_cancelled(session):
    session.client.hold_next_turn = True
    session.manager.submit(session.cid, client_request_id="q1", question="Held question")
    session.manager.submit(session.cid, client_request_id="q2", question="Queued question")
    _wait_for(lambda: any(
        item["client_request_id"] == "q2" for item in session.snapshot()["queue"]
    ))
    session.manager.cancel_queued(session.cid, "q2")
    assert all(item["client_request_id"] != "q2" for item in session.snapshot()["queue"])


def test_stopping_an_active_turn_clears_it(session):
    session.client.hold_next_turn = True
    session.manager.submit(session.cid, client_request_id="q1", question="A long question")
    _wait_for(lambda: session.snapshot()["active_turn_id"] is not None)
    turn_id = session.snapshot()["active_turn_id"]
    session.manager.stop(session.cid, turn_id)
    _wait_for(lambda: session.snapshot()["active_turn_id"] is None)
    assert session.client.interrupts, "the agent was never told to stop"
    assert session.client.interrupts[-1]["turnId"] == turn_id


def test_stopping_a_turn_that_is_not_active_is_refused(session):
    with pytest.raises(ContextError, match="turn is not active"):
        session.manager.stop(session.cid, "no-such-turn")


# --- history ----------------------------------------------------------------

def test_a_conversation_is_recorded_in_history(session):
    session.manager.submit(session.cid, client_request_id="q1", question="Remember me")
    _wait_for(lambda: any(m["role"] == "assistant" for m in session.snapshot()["messages"]))
    rows = session.manager.list_conversations(session.cid)["conversations"]
    assert rows, "the conversation should appear in this project's history"
    assert rows[0]["thread_id"]


def test_history_is_scoped_to_the_agent(repo: Path, agent: str):
    """Two agents on one document keep separate history."""
    manager = DiscussManager(repo, client_factory=fake_factory)
    try:
        doc = {"kind": "scene", "path": "one.md"}
        mine = manager.open(doc, agent)["conversation_id"]
        other_agent = "claude" if agent == "codex" else "codex"
        theirs = manager.open(doc, other_agent)["conversation_id"]
        manager.submit(mine, client_request_id="q1", question="Only in my history")
        _wait_for(lambda: any(
            m["role"] == "assistant" for m in manager.get_snapshot(mine)["messages"]
        ))
        assert manager.list_conversations(mine)["conversations"]
        assert manager.list_conversations(theirs)["conversations"] == []
    finally:
        manager.close()


def test_a_new_conversation_clears_the_projection(session):
    session.manager.submit(session.cid, client_request_id="q1", question="Old conversation")
    _wait_for_settled_answer(session)
    session.manager.new_conversation(session.cid)
    assert session.snapshot()["messages"] == []


# --- failure handling -------------------------------------------------------

def test_a_transport_failure_marks_only_this_conversation_unavailable(session):
    session.manager.submit(session.cid, client_request_id="q1", question="A question")
    _wait_for(lambda: any(m["role"] == "assistant" for m in session.snapshot()["messages"]))
    session.client.hold_next_turn = True
    session.manager.submit(session.cid, client_request_id="q2", question="Another question")
    _wait_for(lambda: session.snapshot()["active_turn_id"] is not None)
    session.manager._on_agent_failure(session.agent, RuntimeError("transport died"))
    snapshot = session.snapshot()
    assert snapshot["connection"] == "Unavailable"
    assert "transport died" in snapshot["unavailable_reason"]


def test_an_unusable_selection_is_refused_before_reaching_the_agent(session):
    with pytest.raises(ContextError):
        session.manager.submit(
            session.cid,
            client_request_id="bad",
            question="",
            selection="text that is not in this document",
            action_id="tighten",
        )
    assert session.client.prompts == []


# --- approvals --------------------------------------------------------------

def test_an_approval_request_surfaces_and_resolves(repo: Path, agent: str):
    """Both transports raise approvals through the same manager path."""
    manager = DiscussManager(repo, client_factory=fake_factory)
    try:
        cid = manager.open({"kind": "scene", "path": "one.md"}, agent)["conversation_id"]
        client = manager._client_for(agent)
        client.hold_next_turn = True
        manager.submit(cid, client_request_id="q1", question="Something needing a tool")
        _wait_for(lambda: manager.get_snapshot(cid)["active_turn_id"] is not None)
        conversation = manager._get(cid)
        thread_id, turn_id = conversation.thread_id, conversation.active_turn_id

        if agent == "claude":
            request_id = client.ask_approval(thread_id, turn_id)
        else:
            request_id = "approval-1"
            client.callback({
                "id": request_id,
                "method": "item/commandExecution/requestApproval",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "command": "rm -rf /",
                    "cwd": ".",
                    "availableDecisions": ["accept", "decline"],
                },
            })

        _wait_for(lambda: bool(manager.get_snapshot(cid)["approvals"]))
        approval = manager.get_snapshot(cid)["approvals"][0]
        assert approval["status"] == "pending"
        assert approval["command"] == "rm -rf /"

        manager.approve(cid, approval["request_id"], "decline")
        assert client.responses[-1][0] == request_id
        assert client.responses[-1][1] == {"decision": "decline"}
        assert manager.get_snapshot(cid)["approvals"][0]["status"] == "resolved"
    finally:
        manager.close()


# --- the doubles themselves -------------------------------------------------

def test_the_two_doubles_really_speak_different_protocols():
    """Guards the suite itself: shared emitting code would prove nothing."""
    codex_methods, claude_methods = [], []
    codex = CodexFakeClient(lambda m: codex_methods.append(m["method"]))
    claude = ClaudeFakeClient(lambda m: claude_methods.append(m["method"]))
    for client, sink in ((codex, codex_methods), (claude, claude_methods)):
        thread = client.request("thread/start", {})["thread"]["id"]
        client.finish_delay = 0
        client.request("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "hi"}]})
        deadline = time.monotonic() + 2
        while not sink and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
    assert codex_methods and claude_methods
    # turn/completed is common to both protocols, but carries a different
    # payload shape in each. Everything that actually conveys content differs,
    # which is what makes the shared behaviour suite meaningful.
    codex_content = set(codex_methods) - {"turn/completed"}
    claude_content = set(claude_methods) - {"turn/completed"}
    assert codex_content and claude_content
    assert not codex_content & claude_content, (
        "the doubles emit the same methods, so the translators are not being exercised"
    )
