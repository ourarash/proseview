from __future__ import annotations

import threading
import time
from pathlib import Path
import hashlib
import json

import pytest

from proseview.codex_app_server import CodexRequestError
import proseview.discuss as discuss_module
from proseview.discuss import (
    ContextError,
    DiscussManager,
    default_skill_body,
    DiscussStateStore,
    _Conversation,
    _merge_activity,
    validate_action_result,
)
from proseview.scenes import extract_scene_text, split_frontmatter

# Shared with the cross-transport conformance suite so both exercise the
# same double rather than drifting apart.
from .transport_fakes import CodexFakeClient as _FakeClient, fake_factory


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript").mkdir(parents=True)
    (root / "manuscript" / "one.md").write_text("# One\n\nFirst document.\n", encoding="utf-8")
    (root / "manuscript" / "two.md").write_text("# Two\n\nSecond document.\n", encoding="utf-8")
    return root


def _wait_for(predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def _scene_revision(path: Path) -> str:
    _frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return hashlib.sha256(extract_scene_text(body).encode("utf-8")).hexdigest()


def test_canon_refactor_scans_configured_story_scope_and_creates_reviewable_finding(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\n", encoding="utf-8"
    )
    (root / "manuscript" / "ch01").mkdir()
    (root / "manuscript" / "ch01" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\n", encoding="utf-8"
    )
    (root / "story-bible" / "characters").mkdir(parents=True)
    (root / "story-bible" / "characters" / "mira.md").write_text(
        "# Mira\n\nMira grew up in Chicago.\n", encoding="utf-8"
    )
    (root / "continuity").mkdir()
    (root / "continuity" / "known-lies.md").write_text(
        "Mira sometimes claims Boston to strangers.\n", encoding="utf-8"
    )
    clients: list[_FakeClient] = []
    def factory(callback, _agent=None):
        client = _FakeClient(callback)
        client.continuity_file = "manuscript/ch01/one.md"
        clients.append(client)
        return client

    manager = DiscussManager(root, client_factory=factory)
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    submitted = manager.submit(
        cid,
        client_request_id="canon-1",
        question="Mira grew up in Chicago, not Boston.",
        action_id="canon_refactor",
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")

    task = manager.get_snapshot(cid)["tasks"][0]
    assert submitted["task_id"] == task["id"]
    assert task["kind"] == "continuity_report"
    assert task["scope"]["files_scanned"] == 5
    assert task["result"]["findings"][0]["id"]
    assert task["result"]["findings"][0]["decision"] == "open"
    assert task["result"]["findings"][0]["proposal_eligible"] is True
    assert clients[0].turn_params[0]["outputSchema"]["properties"]["kind"]["enum"] == ["continuity_report"]
    assert "manuscript/one.md" in clients[0].prompts[0]
    assert "story-bible/characters/mira.md" in clients[0].prompts[0]
    assert "continuity/known-lies.md" in clients[0].prompts[0]
    assert clients[0].turn_params[0]["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}

    proposal = manager.proposal_for_refactor_finding(cid, task["id"], task["result"]["findings"][0]["id"])
    assert proposal["file"] == "ch01/one.md"
    assert proposal["quote"] == "Mira learned winter in Boston."
    assert proposal["options"][0]["text"] == "Mira learned winter in Chicago."
    assert proposal["origin"] == "managed_continuity_refactor"
    assert (root / "manuscript" / "one.md").read_text(encoding="utf-8") == "# One\n\nMira learned winter in Boston.\n"
    manager.close()


def test_non_scene_manuscript_finding_cannot_enter_scene_proposal_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\n", encoding="utf-8"
    )
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    submitted = manager.submit(
        cid, client_request_id="canon-nonscene", question="Change a fact.", action_id="canon_refactor"
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")
    finding = manager.get_snapshot(cid)["tasks"][0]["result"]["findings"][0]

    assert finding["proposal_eligible"] is False
    with pytest.raises(ValueError, match="only manuscript scene findings"):
        manager.proposal_for_refactor_finding(cid, submitted["task_id"], finding["id"])
    manager.close()


def test_canon_refactor_rejects_agent_citations_outside_scanned_context(tmp_path: Path):
    task = {
        "kind": "continuity_report",
        "context_files": {"manuscript/one.md": {"content": "# One\n\nOnly Chicago appears.\n", "mtime_ns": 1}},
    }
    with pytest.raises(ValueError, match="evidence was not found"):
        validate_action_result(json.dumps({
            "kind": "continuity_report",
            "summary": "A contradiction.",
            "findings": [{
                "category": "direct",
                "file": "manuscript/one.md",
                "line": 3,
                "quote": "Mira grew up in Boston.",
                "explanation": "Contradiction.",
                "replacement": "Mira grew up in Chicago.",
            }],
        }), task)


def test_model_intentional_category_does_not_become_a_writer_decision():
    task = {
        "id": "report-1",
        "kind": "continuity_report",
        "context_files": {
            "manuscript/one.md": {
                "content": "# One\n\nMira tells strangers she grew up in Boston.\n",
                "mtime_ns": 1,
            }
        },
    }
    result = validate_action_result(json.dumps({
        "kind": "continuity_report",
        "summary": "One likely intentional reference.",
        "findings": [{
            "category": "intentional",
            "file": "manuscript/one.md",
            "line": 3,
            "quote": "Mira tells strangers she grew up in Boston.",
            "explanation": "This may be a deliberate lie.",
            "replacement": "",
        }],
    }), task)

    assert result["findings"][0]["category"] == "intentional"
    assert result["findings"][0]["decision"] == "open"


@pytest.mark.parametrize(
    ("line", "quote"),
    [
        (2, "origin: Boston"),
        (7, "<!-- NOTE[continuity]: Boston was a cover story. -->"),
    ],
)
def test_frontmatter_and_annotations_are_not_offered_as_scene_edits(line: int, quote: str):
    content = (
        "---\norigin: Boston\n---\n# One\n\nVisible scene prose.\n"
        "<!-- NOTE[continuity]: Boston was a cover story. -->\n"
    )
    result = validate_action_result(json.dumps({
        "kind": "continuity_report",
        "summary": "One repository reference.",
        "findings": [{
            "category": "judgment",
            "file": "manuscript/ch01/one.md",
            "line": line,
            "quote": quote,
            "explanation": "This is metadata, not visible scene prose.",
            "replacement": "origin: Chicago",
        }],
    }), {
        "id": "report-metadata",
        "kind": "continuity_report",
        "manuscript_subdir": "manuscript",
        "context_files": {"manuscript/ch01/one.md": {"content": content, "mtime_ns": 1}},
    })

    assert result["findings"][0]["proposal_eligible"] is False


def test_failed_refactor_validation_discards_private_scan_bodies(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    client: _FakeClient | None = None

    def factory(callback, _agent=None):
        nonlocal client
        client = _FakeClient(callback)
        client.invalid_continuity_result = True
        return client

    manager = DiscussManager(root, client_factory=factory)
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    submitted = manager.submit(
        cid,
        client_request_id="canon-invalid",
        question="Change a fact across the story.",
        action_id="canon_refactor",
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "failed")

    assert submitted["task_id"] not in manager._task_context
    manager.close()


def test_refactor_scan_rejects_a_source_changed_during_context_capture(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\n", encoding="utf-8"
    )
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    original_build = manager.refactor_context.build

    def build_then_change(*args, **kwargs):
        bundle = original_build(*args, **kwargs)
        (root / "manuscript" / "one.md").write_text("# One\n\nChanged during scan.\n", encoding="utf-8")
        return bundle

    monkeypatch.setattr(manager.refactor_context, "build", build_then_change)
    with pytest.raises(ValueError, match="changed while it was being scanned"):
        manager.submit(
            cid,
            client_request_id="canon-raced",
            question="Change a fact across the story.",
            action_id="canon_refactor",
        )

    assert not manager._task_context
    manager.close()


def test_refactor_finding_becomes_stale_and_intentional_decisions_feed_verification(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\n", encoding="utf-8"
    )
    (root / "manuscript" / "ch01").mkdir()
    (root / "manuscript" / "ch01" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\n", encoding="utf-8"
    )

    def factory(callback, _agent=None):
        client = _FakeClient(callback)
        client.continuity_file = "manuscript/ch01/one.md"
        return client

    manager = DiscussManager(root, client_factory=factory)
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    submitted = manager.submit(
        cid, client_request_id="canon-stale", question="Mira grew up in Chicago, not Boston.", action_id="canon_refactor"
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")
    task = manager.get_snapshot(cid)["tasks"][0]
    finding_id = task["result"]["findings"][0]["id"]

    decision = manager.set_refactor_finding_decision(cid, submitted["task_id"], finding_id, "intentional")
    assert decision["decision"] == "intentional"
    verified = manager.submit(
        cid,
        client_request_id="verify-1",
        question="",
        action_id="verify_refactor",
        verify_of_task_id=submitted["task_id"],
    )
    _wait_for(lambda: len(manager.get_snapshot(cid)["tasks"]) == 2 and len(manager._client_for("codex").prompts) == 2)
    verify_task = next(row for row in manager.get_snapshot(cid)["tasks"] if row["id"] == verified["task_id"])
    assert verify_task["verify_of"] == submitted["task_id"]
    assert "intentionally preserved" in manager._client_for("codex").prompts[-1]
    _wait_for(
        lambda: next(
            row for row in manager.get_snapshot(cid)["tasks"] if row["id"] == verified["task_id"]
        )["status"] == "ready"
    )
    verify_task = next(row for row in manager.get_snapshot(cid)["tasks"] if row["id"] == verified["task_id"])
    assert verify_task["result"]["findings"][0]["decision"] == "intentional"

    (root / "manuscript" / "ch01" / "one.md").write_text("# One\n\nChanged elsewhere.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed since the impact scan"):
        manager.proposal_for_refactor_finding(cid, submitted["task_id"], finding_id)
    manager.close()


def test_verification_bounds_prior_decision_quotes_for_a_maximum_report(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\n", encoding="utf-8"
    )
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    submitted = manager.submit(
        cid, client_request_id="canon-max", question="Change a fact.", action_id="canon_refactor"
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")
    conversation = manager._get(cid)
    with conversation.lock:
        parent = conversation.tasks[submitted["task_id"]]
        seed = parent["result"]["findings"][0]
        parent["result"]["findings"] = [
            {**seed, "id": f"finding-{index}", "quote": "x" * 4000, "decision": "intentional"}
            for index in range(discuss_module.REFACTOR_FINDINGS_MAX)
        ]

    manager.submit(
        cid,
        client_request_id="verify-max",
        question="",
        action_id="verify_refactor",
        verify_of_task_id=submitted["task_id"],
    )
    _wait_for(lambda: len(manager._client_for("codex").prompts) == 2)

    verification_prompt = manager._client_for("codex").prompts[-1]
    assert verification_prompt.count("intentionally preserved") == discuss_module.REFACTOR_FINDINGS_MAX
    internal_question = verification_prompt.rsplit("\n\nUSER QUESTION\n", 1)[-1]
    assert len(internal_question.encode("utf-8")) <= discuss_module.REFACTOR_QUESTION_MAX
    manager.close()


def test_verification_does_not_carry_intentional_decision_to_changed_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text(
        "# One\n\nMira learned winter in Boston.\nMira later moved to Chicago.\n", encoding="utf-8"
    )
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    submitted = manager.submit(
        cid, client_request_id="canon-changed", question="Change a fact.", action_id="canon_refactor"
    )
    _wait_for(lambda: manager.get_snapshot(cid)["tasks"][0]["status"] == "ready")
    parent = manager.get_snapshot(cid)["tasks"][0]
    manager.set_refactor_finding_decision(
        cid, submitted["task_id"], parent["result"]["findings"][0]["id"], "intentional"
    )
    manager._client_for("codex").continuity_line = 4
    manager._client_for("codex").continuity_quote = "Mira later moved to Chicago."
    verified = manager.submit(
        cid,
        client_request_id="verify-changed",
        question="",
        action_id="verify_refactor",
        verify_of_task_id=submitted["task_id"],
    )
    _wait_for(
        lambda: next(
            row for row in manager.get_snapshot(cid)["tasks"] if row["id"] == verified["task_id"]
        )["status"] == "ready"
    )
    verification = next(
        row for row in manager.get_snapshot(cid)["tasks"] if row["id"] == verified["task_id"]
    )
    assert verification["result"]["findings"][0]["decision"] == "open"
    manager.close()


# --- skills own the wording -------------------------------------------------

def test_first_run_offers_the_default_skills_to_the_repository(tmp_path: Path, monkeypatch):
    """The buttons are convenience; the skill files are the thing."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=fake_factory)

    shipped = {path.parent.name for path in (Path(discuss_module.__file__).parent / "skills").glob("*/SKILL.md")}
    installed = {path.parent.name for path in (root / ".proseview/skills").glob("*/SKILL.md")}
    assert shipped and shipped == installed
    assert "Quick critique" not in (root / ".proseview/skills" / "quick_critique" / "SKILL.md").read_text(encoding="utf-8")
    manager.close()


def test_a_writers_own_skill_is_what_the_button_sends(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    (root / ".proseview/skills" / "quick_critique" / "SKILL.md").write_text(
        "---\nname: quick_critique\n---\n\nRead this like a hostile reviewer.\n", encoding="utf-8"
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    manager.submit(cid, client_request_id="own-skill", question="", selection="First document.", action_id="quick_critique")
    _wait_for(lambda: bool(clients[0].prompts))
    assert "Read this like a hostile reviewer." in clients[0].prompts[0]

    asked = [m["text"] for m in manager.get_snapshot(cid)["messages"] if m["role"] == "user"]
    assert asked == ["Read this like a hostile reviewer."]
    manager.close()


def test_a_button_explains_itself_from_the_skill_the_writer_can_edit(tmp_path: Path, monkeypatch):
    """The card under a button is wording, so it lives where wording lives.

    Read on every request rather than at startup: a writer who rewrites the
    description has changed what the button promises, and reopening the panel
    is the whole ceremony they should need.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=fake_factory)

    shipped = {row["id"]: row for row in manager.list_actions()}
    assert shipped["quick_critique"]["description"] == discuss_module.default_skill_description("quick_critique")
    assert shipped["quick_critique"]["description"]

    (root / ".proseview/skills" / "quick_critique" / "SKILL.md").write_text(
        '---\nname: quick_critique\ndescription: "Read it like a hostile reviewer."\n---\n\nBody.\n',
        encoding="utf-8",
    )
    rewritten = {row["id"]: row for row in manager.list_actions()}
    assert rewritten["quick_critique"]["description"] == "Read it like a hostile reviewer."
    manager.close()


def test_a_skill_installed_before_descriptions_existed_still_explains_its_button(
    tmp_path: Path, monkeypatch
):
    """Field by field, not file by file.

    The writer's copy owns the prompt it has always owned; the shipped default
    supplies only the line their file never had.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=fake_factory)
    (root / ".proseview/skills" / "style_consistency" / "SKILL.md").write_text(
        "---\nname: style_consistency\n---\n\nOnly the findings that hurt.\n", encoding="utf-8"
    )

    row = {r["id"]: r for r in manager.list_actions()}["style_consistency"]
    assert row["description"] == discuss_module.default_skill_description("style_consistency")
    assert discuss_module.action_instruction(root, "style_consistency") == "Only the findings that hurt."
    manager.close()


def test_a_deleted_skill_is_not_reinstalled_on_the_next_run(tmp_path: Path, monkeypatch):
    """Deleting one is a decision, and starting Prosview again must not undo it."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    DiscussManager(root, client_factory=fake_factory).close()

    removed = root / ".proseview/skills" / "pacing_tension"
    for path in sorted(removed.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    removed.rmdir()

    DiscussManager(root, client_factory=fake_factory).close()
    assert not removed.exists()


def _seed_legacy_skill_offers(tmp_path: Path, root: Path, names: list[str]) -> Path:
    """Write the bookkeeping a repository carried before the directory moved.

    Names, and no record of where they were put -- which is exactly what a
    repository that last ran Prosview with skills in the manuscript root has.
    """
    store = DiscussStateStore(root)
    state = tmp_path / "state" / "proseview" / "discuss.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"version": 1, "repositories": {store.root_key: {"offered_skills": names}}}),
        encoding="utf-8",
    )
    return state


def test_moving_the_skills_directory_offers_them_again_where_skills_now_live(
    tmp_path: Path, monkeypatch
):
    """A remembered offer is only meaningful for the directory it was made in.

    Repositories that ran Prosview before the skills directory moved had every
    name on record, so the new location was never populated and the writer was
    left with buttons whose wording no file of theirs controlled.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    shipped = sorted(
        path.parent.name for path in (Path(discuss_module.__file__).parent / "skills").glob("*/SKILL.md")
    )
    _seed_legacy_skill_offers(tmp_path, root, shipped)
    assert not (root / ".proseview/skills").exists()

    DiscussManager(root, client_factory=fake_factory).close()

    installed = sorted(path.parent.name for path in (root / ".proseview/skills").glob("*/SKILL.md"))
    assert installed == shipped


def test_an_unrecorded_offer_is_read_off_the_directory_it_left_behind(tmp_path: Path):
    """The one case with nothing on record: let the files answer.

    Skills sitting in the current directory were offered there, so the names
    still hold and a deletion among them stays deleted. An empty directory is
    the pre-move repository, and it gets the whole set.
    """
    root = _repo(tmp_path)
    names = ["quick_critique", "style_consistency"]

    assert discuss_module.offers_to_honor(root, names, "") == []

    skill = root / ".proseview/skills" / "quick_critique"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: quick_critique\n---\n\nMine.\n", encoding="utf-8")
    assert discuss_module.offers_to_honor(root, names, "") == names
    # Recorded elsewhere is recorded for elsewhere, however full this is.
    assert discuss_module.offers_to_honor(root, names, "skills") == []
    assert discuss_module.offers_to_honor(root, names, ".proseview/skills") == names


def test_a_skill_deleted_after_the_move_is_still_not_reinstalled(tmp_path: Path, monkeypatch):
    """Re-offering happens once, on the move -- not every time the panel opens.

    Recording the directory alongside the names is what draws that line, so it
    is recorded even on a run that installs nothing.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    DiscussManager(root, client_factory=fake_factory).close()

    skills = root / ".proseview/skills"
    for path in sorted(skills.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    skills.rmdir()

    DiscussManager(root, client_factory=fake_factory).close()
    assert not skills.exists()


def test_a_reading_pass_is_a_message_and_never_becomes_a_proposal(tmp_path: Path, monkeypatch):
    """A critique writes nothing, so it carries none of a rewrite's machinery.

    It is an ordinary question with an ordinary answer: no schema, no card, no
    result to validate and nothing to go stale.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    manager.submit(cid, client_request_id="critique-1", question="", selection="First document.", action_id="quick_critique")
    _wait_for(lambda: any(m["role"] == "assistant" for m in manager.get_snapshot(cid)["messages"]))

    snapshot = manager.get_snapshot(cid)
    assert snapshot["tasks"] == []
    # What the writer is shown having sent is what was sent.
    asked = [m["text"] for m in snapshot["messages"] if m["role"] == "user"]
    # Compared against the skill itself rather than a copy of its prose: the
    # contract is that the writer sees exactly what was sent, and a skill's
    # wording is meant to be edited without breaking that.
    assert asked == [default_skill_body("quick_critique")]
    assert asked[0], "the skill body should not be empty"
    client = manager._client_for("codex")
    assert "First document." in client.prompts[0]
    assert "outputSchema" not in client.turn_params[0]
    # Reading is still reading: nothing may be written on this turn.
    assert client.turn_params[0]["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    manager.close()


def test_managed_skill_is_discovered_and_sent_as_a_real_skill_input(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    skills = manager.list_skills()
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    manager.submit(
        cid, client_request_id="skill-1", question="Review this passage", selection="First document.",
        skill={"name": skills[0]["name"], "path": skills[0]["path"]},
    )
    _wait_for(lambda: bool(clients[0].turn_params))
    assert clients[0].turn_params[0]["input"][1] == {
        "type": "skill", "name": "scene-review", "path": "/.proseview/skills/scene-review/SKILL.md"
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


def test_what_codex_says_between_commands_is_a_step_in_its_place(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=fake_factory)
    cid = manager.open({"kind": "scene", "path": "one.md"}, "codex")["conversation_id"]
    client = manager._client_for("codex")
    client.hold_next_turn = True
    manager.submit(cid, client_request_id="notes-1", question="Compare the chapters")
    _wait_for(lambda: manager.get_snapshot(cid)["active_turn_id"] is not None)
    turn_id = manager.get_snapshot(cid)["active_turn_id"]
    thread_id = next(iter(client.threads))
    common = {"threadId": thread_id, "turnId": turn_id}
    client.callback({"method": "item/completed", "params": {**common, "item": {
        "type": "agentMessage", "id": "msg-1", "phase": "commentary", "text": "I'll compare the two chapters.",
    }}})
    client.callback({"method": "item/completed", "params": {**common, "item": {
        "type": "commandExecution", "id": "cmd-1", "status": "completed", "command": "bash -lc 'cat one.md'",
    }}})

    rows = manager.get_snapshot(cid)["activities"]
    assert [(row["kind"], row.get("text") or row.get("command")) for row in rows] == [
        ("commentary", "I'll compare the two chapters."),
        ("commandExecution", "bash -lc 'cat one.md'"),
    ]
    assert rows[0]["turn_id"] == turn_id
    manager.stop(cid, turn_id)
    manager.close()


def test_a_finished_tool_keeps_the_command_it_started_with(tmp_path: Path, monkeypatch):
    """The Claude transport reports a start and an outcome as two messages.

    Replacing the record with the second one left the trail saying a nameless
    tool completed, with no sign of what had run.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=fake_factory)
    cid = manager.open({"kind": "scene", "path": "one.md"}, "claude")["conversation_id"]
    client = manager._client_for("claude")
    client.hold_next_turn = True
    manager.submit(cid, client_request_id="tools-1", question="Look through the manuscript")
    _wait_for(lambda: manager.get_snapshot(cid)["active_turn_id"] is not None)

    turn_id = manager.get_snapshot(cid)["active_turn_id"]
    thread_id = next(iter(client.threads))
    common = {"threadId": thread_id, "turnId": turn_id, "itemId": "tool-1"}
    client.callback({"method": "tool/started", "params": {
        **common, "tool": "Bash", "command": "grep -rn 'pocket-watch' manuscript",
    }})
    client.callback({"method": "tool/completed", "params": {
        **common, "tool": "", "status": "completed", "output": "no matches",
    }})

    activity = manager.get_snapshot(cid)["activities"][0]
    assert activity["kind"] == "commandExecution"
    assert activity["command"] == "grep -rn 'pocket-watch' manuscript"
    assert activity["status"] == "completed"
    # Filed under the turn that ran it, so a trail can be drawn per turn.
    assert activity["turn_id"] == turn_id

    manager.stop(cid, turn_id)
    manager.close()


def test_a_repeated_progress_heartbeat_is_recorded_once(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=fake_factory)
    cid = manager.open({"kind": "scene", "path": "one.md"}, "claude")["conversation_id"]
    client = manager._client_for("claude")
    client.hold_next_turn = True
    manager.submit(cid, client_request_id="beat-1", question="Think about this")
    _wait_for(lambda: manager.get_snapshot(cid)["active_turn_id"] is not None)

    turn_id = manager.get_snapshot(cid)["active_turn_id"]
    thread_id = next(iter(client.threads))
    for _ in range(4):
        client.callback({"method": "assistant/progress", "params": {
            "threadId": thread_id, "turnId": turn_id, "text": "Thinking\n",
        }})

    assert manager.get_snapshot(cid)["progress"] == ["Thinking\n"]
    manager.stop(cid, turn_id)
    manager.close()


# --- scene passes -----------------------------------------------------------

def test_a_scene_pass_reads_the_whole_scene_without_a_selection(tmp_path: Path, monkeypatch):
    """The passes writers repeat were reachable only after selecting prose.

    Opening the dock on a scene and asking "what is wrong with this" is the
    ordinary case, and it had no entry point at all.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    root = _repo(tmp_path)
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    manager.submit(
        cid, client_request_id="pass-1", question="",
        action_id="quick_critique", action_scope="scene",
    )
    _wait_for(lambda: any(m["role"] == "assistant" for m in manager.get_snapshot(cid)["messages"]))

    prompt = clients[0].prompts[0]
    # The whole scene went with the turn -- and the title line is not prose.
    assert "BEGIN USER SELECTION\nFirst document.\nEND USER SELECTION" in prompt
    assert manager.get_snapshot(cid)["tasks"] == []
    manager.close()


def test_a_scene_pass_refuses_a_rewrite_action(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=fake_factory)
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    with pytest.raises(ContextError, match="only a reading pass"):
        manager.submit(
            cid, client_request_id="pass-2", question="",
            action_id="tighten", action_scope="scene",
        )
    manager.close()


def test_a_style_pass_hands_the_agent_what_prosview_already_found(tmp_path: Path, monkeypatch):
    """Detection is not the model's job here, and the prompt has to say so.

    ``highlights.py`` is deterministic, offline and exact. An agent asked to
    hunt for passives would miss some, invent others, and answer differently
    every run; handing it the hits leaves it only the judgement.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text(
        "# One\n\n"
        "She felt a chill of something coming.\n\n"
        "The door was opened by the wind. She felt cold. The cold was everywhere, "
        "and the cold would not leave.\n",
        encoding="utf-8",
    )
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    manager.submit(
        cid, client_request_id="style-1", question="",
        action_id="style_consistency", action_scope="scene",
    )
    _wait_for(lambda: clients[0].prompts)

    prompt = clients[0].prompts[-1]
    assert "BEGIN PROSVIEW NOTES" in prompt
    assert "passive construction: The door was opened by the wind." in prompt
    assert "filter verb: She felt a chill of something coming." in prompt
    assert "repeated word" in prompt
    # Whole sentences, never bare hits: "felt" cannot be quoted back at a writer.
    assert "filter verb: felt" not in prompt
    manager.close()


def test_a_style_pass_on_clean_prose_costs_nothing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=fake_factory)
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    with pytest.raises(ContextError, match="nothing mechanical to flag"):
        manager.submit(
            cid, client_request_id="style-2", question="",
            action_id="style_consistency", action_scope="scene",
        )
    assert manager.get_snapshot(cid)["tasks"] == []
    manager.close()


def test_a_style_finding_outside_the_observations_is_refused():
    """The evidence set is the whole point: cite it or the finding is invented."""
    task = {
        "kind": "critique",
        "action_id": "style_consistency",
        "max_results": 5,
        "target": {"selection": "She felt cold. The door was opened by the wind."},
        "style_observations": ["The door was opened by the wind."],
    }
    payload = json.dumps({"kind": "critique", "findings": [{
        "observation": "The emotion is named, not shown.",
        "evidence": "She felt cold.",
        "why_it_matters": "Naming the feeling does the reader's work for them.",
        "next_step": "Give the cold something to act on.",
    }]})
    with pytest.raises(ContextError, match="not one of the style observations"):
        validate_action_result(payload, task)

    grounded = json.dumps({"kind": "critique", "findings": [{
        "observation": "The wind does the work in the passive.",
        "evidence": "The door was opened by the wind.",
        "why_it_matters": "The agent of the sentence arrives last.",
        "next_step": "Let the wind open the door.",
    }]})
    assert validate_action_result(grounded, task)["findings"][0]["evidence"] == "The door was opened by the wind."


def test_manager_serializes_one_document_and_filters_raw_reasoning(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []

    def factory(callback, _agent=None):
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
    assert "Open file: manuscript/one.md" in clients[0].prompts[0]
    manager.close()


def test_an_ordinary_question_says_where_the_writer_is_and_sends_no_files(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    root = _repo(tmp_path)
    manager = DiscussManager(
        root,
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    (root / "story-bible").mkdir()
    (root / "story-bible" / "alice.md").write_text("Alice is seven.\n", encoding="utf-8")
    mention = "story-bible/alice.md"

    manager.submit(
        cid,
        client_request_id="mentions",
        question=f"Does this contradict @{mention}?",
        attachments=[{"kind": "file", "path": mention}],
        include_current_document=True,
    )
    _wait_for(lambda: bool(clients[0].prompts))
    prompt = clients[0].prompts[0]
    assert prompt.startswith("PROSEVIEW CONTEXT\nOpen file: manuscript/one.md\nMentioned: " + mention)
    assert prompt.endswith(f"USER QUESTION\nDoes this contradict @{mention}?")
    # No file text, and no instructions about how to answer.
    assert "First document." not in prompt and "Alice is seven." not in prompt
    assert "BEGIN UNTRUSTED DOCUMENT" not in prompt
    assert "Discuss only" not in prompt

    # An unsaved draft is not on disk to be read, so it goes along.
    scene = root / "manuscript" / "one.md"
    manager.submit(
        cid,
        client_request_id="draft",
        question="And now?",
        live_document={"content": "# One\n\nA draft not yet saved.\n", "base_mtime": scene.stat().st_mtime},
    )
    _wait_for(lambda: len(clients[0].prompts) == 2)
    assert "Unsaved draft of manuscript/one.md" in clients[0].prompts[1]
    assert "A draft not yet saved." in clients[0].prompts[1]
    manager.close()


def test_manager_omits_current_document_when_user_removes_it(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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


def test_manager_serializes_project_turns_across_documents_and_is_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []

    def factory(callback, _agent=None):
        client = _FakeClient(callback)
        clients.append(client)
        return client

    manager = DiscussManager(_repo(tmp_path), client_factory=factory)
    one = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    two = manager.open({"kind": "scene", "path": "two.md"})["conversation_id"]
    assert one == two
    first = manager.submit(
        one, client_request_id="same", question="One?", document={"kind": "scene", "path": "one.md"}
    )
    duplicate = manager.submit(
        one, client_request_id="same", question="Ignored duplicate",
        document={"kind": "scene", "path": "one.md"},
    )
    manager.submit(
        two, client_request_id="other", question="Two?", document={"kind": "scene", "path": "two.md"}
    )
    _wait_for(lambda: len(clients[0].prompts) == 2)

    assert first["client_request_id"] == duplicate["client_request_id"] == "same"
    assert first["accepted"] is duplicate["accepted"] is True
    assert clients[0].max_active == 1
    assert sum("One?" in prompt for prompt in clients[0].prompts) == 1
    assert not any("Ignored duplicate" in prompt for prompt in clients[0].prompts)
    manager.close()


def test_open_revalidates_and_forgets_a_cached_thread_that_codex_lost(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
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
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
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
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: _FakeClient(callback))
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
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
    notice = next(
        notice for notice in snapshot["notices"]
        if "new conversation" in notice["message"].lower()
    )
    assert notice["id"].startswith("notice-")
    assert notice["client_request_id"] == "recover"
    assert next(message for message in snapshot["messages"] if message["role"] == "assistant")[
        "client_request_id"
    ] == "recover"

    dismissed = manager.dismiss_notice(conversation_id, notice["id"])

    assert dismissed == {"dismissed": True, "notice_id": notice["id"]}
    assert manager.get_snapshot(conversation_id)["notices"] == []
    with pytest.raises(ContextError, match="notice was not found"):
        manager.dismiss_notice(conversation_id, notice["id"])
    manager.close()


def test_new_conversation_clears_projection_and_uses_a_new_thread(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
    )
    document = {"kind": "scene", "path": "one.md"}
    conversation_id = manager.open(document)["conversation_id"]
    manager.submit(conversation_id, client_request_id="before", question="First thread")
    # active_turn_id clears before the worker finishes winding the turn down,
    # and new_conversation refuses while anything is still in flight. Waiting
    # only on the turn id makes this racy under load.
    _wait_for(
        lambda: manager.get_snapshot(conversation_id)["active_turn_id"] is None
        and manager.get_snapshot(conversation_id)["active_request_id"] is None
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
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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


def test_migrated_legacy_action_uses_its_recorded_source_when_opened_elsewhere(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    legacy_thread: dict = {}
    clients: list[_FakeClient] = []

    def factory(callback, _agent=None):
        client = _FakeClient(callback)
        client.threads[legacy_thread["id"]] = legacy_thread
        clients.append(client)
        return client

    manager = DiscussManager(root, client_factory=factory)
    source = {"kind": "scene", "path": "one.md"}
    source_conversation = _Conversation("legacy-source", source)
    task, question, _schema, _skill = manager._action_task(
        source_conversation,
        document=source,
        request_id="legacy-action",
        action_id="tighten",
        selection="First document.",
    )
    header, prompt_body = question.split("\n", 1)
    provenance = json.loads(header.removeprefix("PROSVIEW_SELECTION_ACTION_V1 "))
    provenance.pop("document")
    legacy_question = (
        "PROSVIEW_SELECTION_ACTION_V1 "
        + json.dumps(provenance, sort_keys=True, separators=(",", ":"))
        + "\n"
        + prompt_body
    )
    prompt = manager.context.build(
        source, legacy_question, selection="First document."
    ).prompt
    legacy_thread.update({
        "id": "legacy-action-thread",
        "turns": [{"id": "legacy-action-turn", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": prompt}]},
            {"type": "agentMessage", "phase": "final_answer", "text": json.dumps({
                "kind": "alternatives",
                "summary": "A tighter beat.",
                "alternatives": [
                    {"text": "Revised document.", "rationale": "Removes repetition."},
                    {"text": "Document, revised.", "rationale": "Changes the rhythm."},
                ],
            })},
        ]}],
    })
    manager.state.path.parent.mkdir(parents=True, exist_ok=True)
    manager.state.path.write_text(json.dumps({
        "version": 2,
        "repositories": {manager.state.root_key: {
            "scene:one.md": {
                "active": legacy_thread["id"],
                "threads": [{
                    "thread_id": legacy_thread["id"],
                    "title": "Legacy rewrite",
                    "preview": "First document.",
                    "created_at": 1,
                    "updated_at": 2,
                    "renamed": False,
                }],
            },
        }},
    }), encoding="utf-8")

    conversation_id = manager.open({"kind": "scene", "path": "two.md"})["conversation_id"]
    restored = manager.get_snapshot(conversation_id)["tasks"][0]
    exported = manager.export_conversation(conversation_id, legacy_thread["id"])

    assert restored["id"] == task["id"]
    assert restored["target"]["document"] == source
    assert restored["status"] == "ready"
    assert exported["document"] == source
    assert exported["documents"] == [source]
    assert exported["tasks"][0]["target"]["document"] == source
    manager.close()


def test_legacy_action_with_ambiguous_history_origins_never_uses_current_scene(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    thread_id = "ambiguous-legacy-action"
    thread: dict = {}

    def factory(callback, _agent=None):
        client = _FakeClient(callback)
        client.threads[thread_id] = thread
        return client

    manager = DiscussManager(root, client_factory=factory)
    source = {"kind": "scene", "path": "one.md"}
    source_conversation = _Conversation("legacy-source", source)
    _task, question, _schema, _skill = manager._action_task(
        source_conversation,
        document=source,
        request_id="legacy-action",
        action_id="tighten",
        selection="First document.",
    )
    header, prompt_body = question.split("\n", 1)
    provenance = json.loads(header.removeprefix("PROSVIEW_SELECTION_ACTION_V1 "))
    provenance.pop("document")
    prompt = manager.context.build(
        source,
        "PROSVIEW_SELECTION_ACTION_V1 "
        + json.dumps(provenance, sort_keys=True, separators=(",", ":"))
        + "\n"
        + prompt_body,
        selection="First document.",
    ).prompt
    thread.update({
        "id": thread_id,
        "turns": [{"id": "ambiguous-turn", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": prompt}]},
            {"type": "agentMessage", "phase": "final_answer", "text": json.dumps({
                "kind": "alternatives",
                "summary": "A tighter beat.",
                "alternatives": [
                    {"text": "Revised document.", "rationale": "Removes repetition."},
                    {"text": "Document, revised.", "rationale": "Changes the rhythm."},
                ],
            })},
        ]}],
    })
    manager.state.path.parent.mkdir(parents=True, exist_ok=True)
    manager.state.path.write_text(json.dumps({
        "version": 3,
        "repositories": {manager.state.root_key: {"agents": {
            "codex": {
                "active": thread_id,
                "active_initialized": True,
                "legacy_active": {},
                "history_limit": 50,
                "threads": [{
                    "thread_id": thread_id,
                    "title": "Ambiguous legacy rewrite",
                    "preview": "",
                    "created_at": 1,
                    "updated_at": 2,
                    "renamed": False,
                    "documents": [source, {"kind": "scene", "path": "two.md"}],
                }],
            },
        }}},
    }), encoding="utf-8")

    conversation_id = manager.open({"kind": "scene", "path": "two.md"})["conversation_id"]
    restored = manager.get_snapshot(conversation_id)["tasks"][0]
    exported = manager.export_conversation(conversation_id, thread_id)

    assert restored["target"]["document"] is None
    assert restored["status"] == "stale"
    assert exported["document"] is None
    assert exported["documents"] == [source, {"kind": "scene", "path": "two.md"}]
    manager.close()


def test_history_rename_export_and_remove_use_safe_projection(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    thread_id = manager._start_thread(manager._get(cid), manager._client_for("codex"))
    manager._client_for("codex").threads[thread_id] = {"id": "different-thread", "turns": [{"items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "PRIVATE OTHER THREAD"}]},
    ]}]}

    with pytest.raises(ValueError, match="different conversation"):
        manager.export_conversation(cid, thread_id)
    manager.close()


def test_history_open_rejects_a_missing_codex_thread_identity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    thread_id = manager._start_thread(manager._get(cid), manager._client_for("codex"))
    manager._client_for("codex").threads[thread_id] = {"turns": [{"items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "Context\n\nUSER QUESTION\nDo not project me"}]},
    ]}]}
    manager.new_conversation(cid)

    with pytest.raises(ValueError, match="different conversation"):
        manager.open_conversation(cid, thread_id)
    assert manager.get_snapshot(cid)["messages"] == []
    manager.close()


def test_restored_history_omits_unrecognized_user_prompt_envelopes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: _FakeClient(callback))
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


@pytest.mark.parametrize("first_agent", ["codex", "claude"])
def test_discuss_state_store_migrates_document_history_to_project_agents(
    tmp_path: Path, first_agent: str
):
    root = _repo(tmp_path)
    state_path = tmp_path / "discuss.json"
    store = DiscussStateStore(root, path=state_path)
    state_path.write_text(json.dumps({
        "version": 2,
        "repositories": {store.root_key: {
            "scene:one.md": {
                "active": "codex-one",
                "threads": [{
                    "thread_id": "codex-one", "title": "Opening", "preview": "First",
                    "created_at": 1, "updated_at": 2, "renamed": True,
                }],
            },
            "scene:two.md": {
                "active": "codex-two",
                "threads": [{
                    "thread_id": "codex-two", "title": "Next scene", "preview": "Second",
                    "created_at": 3, "updated_at": 4, "renamed": False,
                }],
            },
            "claude\u0000scene:two.md": {
                "active": "claude-two",
                "threads": [{
                    "thread_id": "claude-two", "title": "Claude pass", "preview": "Other provider",
                    "created_at": 5, "updated_at": 6, "renamed": False,
                }],
            },
            "claude\u0000scene:one.md": {
                "active": "claude-one",
                "threads": [{
                    "thread_id": "claude-one", "title": "Claude opening", "preview": "Preferred file",
                    "created_at": 1, "updated_at": 2, "renamed": False,
                }],
            },
        }},
    }), encoding="utf-8")

    second_agent = "claude" if first_agent == "codex" else "codex"
    active = {
        first_agent: store.get("scene", "one.md", first_agent),
        second_agent: store.get("scene", "one.md", second_agent),
    }
    assert active == {"codex": "codex-one", "claude": "claude-one"}
    assert {row["thread_id"] for row in store.list("file", "notes.md")} == {
        "codex-one", "codex-two",
    }
    assert {row["thread_id"] for row in store.list("scene", "one.md", "claude")} == {
        "claude-one", "claude-two",
    }

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["version"] == 3
    agents = saved["repositories"][store.root_key]["agents"]
    assert agents["codex"]["active"] == "codex-one"
    assert agents["claude"]["active"] == "claude-one"
    assert "scene:one.md" not in saved["repositories"][store.root_key]


def test_discuss_state_store_migrates_v1_thread_pointer_to_project_history(tmp_path: Path):
    root = _repo(tmp_path)
    state_path = tmp_path / "discuss.json"
    store = DiscussStateStore(root, path=state_path)
    state_path.write_text(json.dumps({
        "version": 1,
        "repositories": {store.root_key: {"scene:one.md": "legacy-thread"}},
    }), encoding="utf-8")

    assert store.get("scene", "two.md") == "legacy-thread"
    assert [row["thread_id"] for row in store.list("file", "notes.md")] == ["legacy-thread"]
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["version"] == 3


def test_discuss_state_store_preserves_all_unique_rows_when_legacy_buckets_merge(tmp_path: Path):
    root = _repo(tmp_path)
    state_path = tmp_path / "discuss.json"
    store = DiscussStateStore(root, path=state_path)

    def legacy_entry(prefix: str, start: int) -> dict:
        rows = [{
            "thread_id": f"{prefix}-{index}",
            "title": f"Conversation {index}",
            "preview": "",
            "created_at": float(start + index),
            "updated_at": float(start + index),
            "renamed": False,
        } for index in range(discuss_module.CONVERSATION_HISTORY_MAX)]
        return {"active": rows[-1]["thread_id"], "threads": rows}

    state_path.write_text(json.dumps({
        "version": 2,
        "repositories": {store.root_key: {
            "scene:one.md": legacy_entry("one", 0),
            "scene:two.md": legacy_entry("two", 1000),
        }},
    }), encoding="utf-8")

    rows = store.list("scene", "one.md")
    assert len(rows) == discuss_module.CONVERSATION_HISTORY_MAX * 2
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(saved["repositories"][store.root_key]["agents"]["codex"]["threads"]) == len(rows)


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
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: _FakeClient(callback))
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


def test_selection_action_queues_while_thread_history_is_still_restoring(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._get(cid)
    restored_thread = manager._start_thread(conversation, clients[0])
    read_started = threading.Event()
    release_read = threading.Event()
    original_request = clients[0].request

    def blocking_request(method, params, *, timeout=None):
        if method == "thread/read":
            read_started.set()
            release_read.wait(timeout=2)
        return original_request(method, params, timeout=timeout)

    monkeypatch.setattr(clients[0], "request", blocking_request)
    restore = threading.Thread(
        target=manager.open,
        args=({"kind": "scene", "path": "one.md"},),
        daemon=True,
    )
    restore.start()
    assert read_started.wait(timeout=1)

    submitted: list[dict] = []
    submit = threading.Thread(
        target=lambda: submitted.append(manager.submit(
            cid,
            client_request_id="action-during-restore",
            question="",
            selection="First document.",
            action_id="tighten",
        )),
        daemon=True,
    )
    submit.start()
    try:
        assert submit.join(timeout=0.25) is None and submitted, (
            "selection action enqueue waited for the external thread/read request"
        )
    finally:
        release_read.set()
        restore.join(timeout=2)
        submit.join(timeout=2)
        _wait_for(lambda: any(
            message["role"] == "assistant" for message in manager.get_snapshot(cid)["messages"]
        ))
        manager.close()


def test_dequeued_question_blocks_reset_and_history_switch_until_it_finishes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
    original_client_for = manager._client_for

    def stalled_client(agent):
        claimed.set()
        release.wait(timeout=2)
        return original_client_for(agent)

    monkeypatch.setattr(manager, "_client_for", stalled_client)
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
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
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
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    manager._on_agent_message("codex", {
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
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: _FakeClient(callback))
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
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
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


def test_explicit_selection_range_disambiguates_repeated_marked_text(tmp_path: Path, monkeypatch):
    """An ambiguous quote is how an edit lands on the wrong paragraph."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    (root / "manuscript" / "one.md").write_text("# One\n\nA *quiet* room was quiet.\n", encoding="utf-8")
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    result = manager.submit(
        cid,
        client_request_id="marked-range",
        question="",
        selection="quiet",
        selection_range={"start": 2, "end": 7},
        selection_snapshot={
            "editor_text": "A quiet room was quiet.",
            "source_revision": _scene_revision(root / "manuscript" / "one.md"),
        },
        action_id="tighten",
    )
    assert result["accepted"] is True

    # The same word without a range appears twice, and is refused rather than
    # handed to an agent that would have to guess which one was meant.
    with pytest.raises(ContextError, match="appears more than once"):
        manager.submit(
            cid,
            client_request_id="marked-ambiguous",
            question="",
            selection="quiet",
            action_id="tighten",
        )
    manager.close()

def test_selection_snapshot_validates_browser_offsets_without_reconstructing_markdown(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    scene = root / "manuscript" / "one.md"
    scene.write_text(
        "---\ntitle: The King\n---\n\n"
        '<img src="/repo-asset/king.png" alt="The king">\n\n'
        "# The King\n\n"
        "But I have another theory.\n\n"
        "What if the whole thing was just a rumor the king started to save his pride?\n",
        encoding="utf-8",
    )
    editor_text = (
        "The King\nBut I have another theory.\n"
        "What if the whole thing was just a rumor the king started to save his pride?"
    )
    selection = "What if the whole thing was just a rumor the king started to save his pride?"
    start = editor_text.index(selection)
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    result = manager.submit(
        cid,
        client_request_id="rendered-snapshot",
        question="",
        selection=selection,
        selection_range={"start": start, "end": start + len(selection)},
        selection_snapshot={
            "editor_text": editor_text,
            "source_revision": _scene_revision(scene),
        },
        action_id="tighten",
    )

    # Accepting proves the browser offsets validated against the rendered
    # scene without Prosview rebuilding the markdown to check them.
    assert result["accepted"] is True
    manager.close()


def test_selection_snapshot_rejects_a_scene_revision_that_changed_after_selection(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    scene = root / "manuscript" / "one.md"
    original_revision = _scene_revision(scene)
    scene.write_text("# One\n\nFirst document changed externally.\n", encoding="utf-8")
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: _FakeClient(callback))
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]

    with pytest.raises(ContextError, match="changed after you selected"):
        manager.submit(
            cid,
            client_request_id="stale-rendered-snapshot",
            question="",
            selection="First document.",
            selection_range={"start": 0, "end": 15},
            selection_snapshot={
                "editor_text": "First document.",
                "source_revision": original_revision,
            },
            action_id="tighten",
        )
    manager.close()


def test_selection_action_uses_bounded_live_editor_context(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    clients: list[_FakeClient] = []
    manager = DiscussManager(root, client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    scene = root / "manuscript" / "one.md"
    live = "Local preface. First document.\n"
    manager.submit(
        cid,
        client_request_id="live-selection",
        question="",
        selection="First document.",
        selection_range={"start": 15, "end": 30},
        selection_snapshot={
            "editor_text": live.rstrip("\n"),
            "source_revision": _scene_revision(scene),
        },
        live_document={"content": live, "base_mtime": scene.stat().st_mtime},
        action_id="tighten",
    )
    _wait_for(lambda: bool(clients[0].prompts))
    # The unsaved buffer is what the agent was given, not the file on disk.
    assert "Local preface. First document." in clients[0].prompts[0]
    manager.close()


def test_pending_queue_item_can_be_removed_individually(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
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


def test_stop_recovers_when_codex_has_unloaded_the_active_thread(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    client = clients[0]
    client.hold_next_turn = True
    client.interrupt_error = CodexRequestError("thread not loaded: thread-1", code=-32000)

    continuity = manager.submit(
        cid,
        client_request_id="continuity-held",
        question="",
        action_id="scene_continuity",
    )
    _wait_for(lambda: bool(manager.get_snapshot(cid)["active_turn_id"]))
    rewrite = manager.submit(
        cid,
        client_request_id="rewrite-queued",
        question="",
        selection="First document.",
        action_id="custom_rewrite",
        custom_instruction="Make this more direct.",
    )

    active_turn_id = manager.get_snapshot(cid)["active_turn_id"]
    assert active_turn_id
    manager.stop(cid, active_turn_id)
    # The queued rewrite is an ordinary turn now, so it is answered rather than
    # marked ready -- but it must still survive the lost thread.
    _wait_for(lambda: any(
        message["role"] == "assistant" for message in manager.get_snapshot(cid)["messages"]
    ))

    snapshot = manager.get_snapshot(cid)
    tasks = {task["id"]: task for task in snapshot["tasks"]}
    assert tasks[continuity["task_id"]]["status"] == "cancelled"
    assert tasks[continuity["task_id"]]["error"] == "Stopped by writer"
    assert rewrite["accepted"] is True
    assert client.next_thread == 2
    assert snapshot["connection"] == "Live"
    assert snapshot["unavailable_reason"] == ""
    assert snapshot["active_turn_id"] is None
    assert snapshot["queue"] == []
    manager.close()


def test_delayed_stop_error_cannot_detach_the_next_queued_turn(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1],
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    client = clients[0]
    client.hold_next_turn = True
    client.complete_turn_before_interrupt_error = True
    client.interrupt_error = CodexRequestError("thread not loaded: thread-1", code=-32000)

    manager.submit(cid, client_request_id="held", question="First turn")
    _wait_for(lambda: bool(manager.get_snapshot(cid)["active_turn_id"]))
    manager.submit(cid, client_request_id="next", question="Second turn")
    stopped_turn_id = manager.get_snapshot(cid)["active_turn_id"]
    assert stopped_turn_id

    manager.stop(cid, stopped_turn_id)
    _wait_for(lambda: len([
        message for message in manager.get_snapshot(cid)["messages"]
        if message["role"] == "assistant"
    ]) == 1)

    snapshot = manager.get_snapshot(cid)
    assert client.next_thread == 1
    assert manager._conversations[cid].thread_id == "thread-1"
    assert snapshot["active_turn_id"] is None
    assert snapshot["queue"] == []
    assert snapshot["connection"] == "Live"
    manager.close()


def test_commands_and_permissions_ask_but_a_file_change_does_not(tmp_path: Path, monkeypatch):
    """Only the things that cannot be taken back stop to ask.

    A file edit is answered on the spot: every one of them is reversible from
    the end-of-turn review, and holding the agent while the writer rules on
    prose they have not read yet buys nothing. Running a command or widening
    permissions has no undo, so those still wait for an answer.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    requests = [
        (101, "item/commandExecution/requestApproval", {"networkApprovalContext": {"host": "example.test"}}, "network"),
        (103, "item/permissions/requestApproval", {"permissions": {"filesystem": ["one.md"]}}, "permissions"),
    ]
    for request_id, method, extra, expected_kind in requests:
        manager._on_agent_message("codex", {
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

    manager._on_agent_message("codex", {
        "id": 102,
        "method": "item/fileChange/requestApproval",
        "params": {
            "threadId": thread_id,
            "turnId": "turn-x",
            "itemId": "item-102",
            "availableDecisions": ["accept", "decline"],
            "item": {"id": "item-102", "changes": [{"path": "manuscript/one.md", "kind": "modified"}]},
        },
    })
    assert (102, {"decision": "accept"}) in clients[0].responses
    assert not [row for row in manager.get_snapshot(cid)["approvals"] if row["request_id"] == "102"]
    # Answering it is also when the version to review against is taken.
    assert "manuscript/one.md" in manager._get(cid).file_before

    manager.approve(cid, "101", "decline")
    manager.approve(cid, "103", "accept", {"permissions": {"filesystem": ["one.md"], "network": ["bad"]}})
    assert clients[0].responses[-1] == (103, {"permissions": {"filesystem": ["one.md"]}, "scope": "turn"})
    manager.close()


def test_approval_without_advertised_decisions_is_declined(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    manager._on_agent_message("codex", {
        "id": 104,
        "method": "item/fileChange/requestApproval",
        "params": {"threadId": thread_id, "turnId": "turn-x", "itemId": "item-x"},
    })
    assert clients[0].responses == [(104, {"decision": "decline"})]
    assert manager.get_snapshot(cid)["approvals"] == []
    manager.close()


def test_codex_turns_ask_on_request_inside_a_read_only_sandbox(tmp_path: Path, monkeypatch):
    """Codex retired ``untrusted``; sent anyway, it now asks before every read.

    ``on-request`` inside a read-only sandbox is what Prosview relied on the
    old policy for: reading needs no answer, a command that would write stops
    at an approval, and an edit arrives as a file change the writer reviews.
    A rewrite runs read-only too. A workspace-write sandbox would let a shell
    command change the manuscript without asking and with nothing kept to
    review it against.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    started: list[dict] = []

    class Recording(_FakeClient):
        def request(self, method, params, *, timeout=None):
            if method == "thread/start":
                started.append(dict(params))
            return super().request(method, params, timeout=timeout)

    clients: list[_FakeClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(Recording(callback)) or clients[-1],
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    manager.submit(cid, client_request_id="ask-1", question="Fix the typo in the opening.")
    manager.submit(cid, client_request_id="pass-1", question="", action_id="quick_critique", action_scope="scene")
    _wait_for(lambda: len(clients[0].turn_params) == 2 and manager.get_snapshot(cid)["active_request_id"] is None)

    assert started and all(params["approvalPolicy"] == "on-request" for params in started)
    for params in clients[0].turn_params:
        assert params["approvalPolicy"] == "on-request"
        assert params["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    # What tells the two turns apart now is whether an edit is taken.
    assert [params["mayWrite"] for params in clients[0].turn_params] == [True, False]
    manager.close()


def test_a_reading_pass_declines_an_edit_that_a_question_takes(tmp_path: Path, monkeypatch):
    """The sandbox no longer tells a reading pass from a request to change things.

    Every Codex turn runs read-only, so each edit reaches Prosview as an
    approval. A question the writer asked takes it, to be reviewed after the
    turn. A reading pass exists to report, and declines it.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manager = DiscussManager(_repo(tmp_path), client_factory=fake_factory)
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    client = manager._client_for("codex")

    def run_held(request_id: str, **submit) -> str:
        client.hold_next_turn = True
        manager.submit(cid, client_request_id=request_id, **submit)
        _wait_for(lambda: manager.get_snapshot(cid)["active_request_id"] == request_id
                  and manager.get_snapshot(cid)["active_turn_id"] is not None)
        return manager.get_snapshot(cid)["active_turn_id"]

    def ask_to_edit(approval_id: int, turn_id: str) -> None:
        manager._on_agent_message("codex", {
            "id": approval_id,
            "method": "item/fileChange/requestApproval",
            "params": {
                "threadId": manager._get(cid).thread_id,
                "turnId": turn_id,
                "itemId": f"edit-{approval_id}",
                "availableDecisions": ["accept", "decline"],
                "item": {"id": f"edit-{approval_id}", "changes": [{"path": "manuscript/one.md", "kind": "modified"}]},
            },
        })

    turn_id = run_held("pass-1", question="", action_id="quick_critique", action_scope="scene")
    ask_to_edit(201, turn_id)
    assert (201, {"decision": "decline"}) in client.responses
    assert "manuscript/one.md" not in manager._get(cid).file_before
    assert any("reading pass" in notice["message"] for notice in manager.get_snapshot(cid)["notices"])
    manager.stop(cid, turn_id)
    _wait_for(lambda: manager.get_snapshot(cid)["active_request_id"] is None)

    turn_id = run_held("ask-1", question="Fix the typo in the opening.")
    ask_to_edit(202, turn_id)
    assert (202, {"decision": "accept"}) in client.responses
    assert "manuscript/one.md" in manager._get(cid).file_before
    manager.stop(cid, turn_id)
    manager.close()


def test_typing_into_a_running_command_asks_as_input_not_as_a_command(tmp_path: Path, monkeypatch):
    """Codex now asks before it sends input to a command that is already running.

    The request is a command approval of kind ``writeStdin`` whose command is
    ``write_stdin --session-id N <input>``. Shown as a shell command it reads
    as nonsense and offers answers Codex does not take. It is input, typed into
    the command that is running, and the answer is to send it or to stop.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    clients: list[_FakeClient] = []
    manager = DiscussManager(_repo(tmp_path), client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1])
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    conversation.activities["exec-1"] = {
        "id": "exec-1", "kind": "commandExecution", "command": "/bin/bash -lc 'python3 ask.py'",
    }
    manager._on_agent_message("codex", {
        "id": 301,
        "method": "item/commandExecution/requestApproval",
        "params": {
            "threadId": thread_id,
            "turnId": "turn-x",
            "itemId": "exec-1",
            "kind": "writeStdin",
            "command": "write_stdin --session-id 7 'yes please\n'",
        },
    })

    approval = next(row for row in manager.get_snapshot(cid)["approvals"] if row["request_id"] == "301")
    assert approval["kind"] == "stdin"
    assert approval["input"] == "yes please\n"
    assert approval["command"] == "/bin/bash -lc 'python3 ask.py'"
    assert approval["available_decisions"] == ["accept", "cancel"]
    with pytest.raises(ContextError, match="not available"):
        manager.approve(cid, "301", "decline")
    manager.approve(cid, "301", "accept")
    assert clients[0].responses[-1] == (301, {"decision": "accept"})

    # An ordinary command approval is unchanged by the new field.
    manager._on_agent_message("codex", {
        "id": 302,
        "method": "item/commandExecution/requestApproval",
        "params": {"threadId": thread_id, "turnId": "turn-x", "itemId": "exec-2",
                   "kind": "command", "command": "/bin/bash -lc 'echo hi > out.txt'",
                   "availableDecisions": ["accept", "decline"]},
    })
    approval = next(row for row in manager.get_snapshot(cid)["approvals"] if row["request_id"] == "302")
    assert approval["kind"] == "command"
    assert approval["command"] == "/bin/bash -lc 'echo hi > out.txt'"
    assert approval.get("input", "") == ""
    manager.close()


_PAGED_TURNS = [
    {"id": "t1", "items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "Context\n\nUSER QUESTION\nFirst question"}]},
        {"type": "agentMessage", "phase": "final_answer", "text": "First answer"},
    ]},
    {"id": "t2", "items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "Context\n\nUSER QUESTION\nSecond question"}]},
        {"type": "agentMessage", "phase": "final_answer", "text": "Second answer"},
    ]},
]


class _PagedHistoryClient(_FakeClient):
    """A Codex that keeps the stored thread's history paginated."""

    def __init__(self, callback, *, mode="paginated", paging_error=None):
        super().__init__(callback)
        self.capabilities = {**self.capabilities, "paginated_history": True}
        self.mode = mode
        self.paging_error = paging_error
        self.calls: list[tuple[str, dict]] = []

    def request(self, method, params, *, timeout=None):
        if params.get("threadId") != "stored":
            return super().request(method, params, timeout=timeout)
        self.calls.append((method, dict(params)))
        if method == "thread/read":
            if params.get("includeTurns"):
                if self.mode == "paginated" and self.paging_error is None:
                    raise AssertionError("a paginated thread was hydrated whole")
                return {"thread": {"id": "stored", "historyMode": self.mode, "turns": list(_PAGED_TURNS)}}
            return {"thread": {"id": "stored", "historyMode": self.mode, "turns": []}}
        if method == "thread/turns/list":
            if self.paging_error is not None:
                raise self.paging_error
            assert params["itemsView"] == "full"
            # Newest first: if a history is ever longer than Discuss reads,
            # what it leaves out is the oldest turns, not the latest.
            assert params["sortDirection"] == "desc"
            if params.get("cursor") is None:
                return {"data": [_PAGED_TURNS[1]], "nextCursor": "page-2"}
            assert params["cursor"] == "page-2"
            return {"data": [_PAGED_TURNS[0]], "nextCursor": None}
        return super().request(method, params, timeout=timeout)


def _restored_messages(tmp_path: Path, client_options: dict) -> tuple[list[str], list[tuple[str, dict]]]:
    clients: list[_PagedHistoryClient] = []
    manager = DiscussManager(
        _repo(tmp_path),
        client_factory=lambda callback, _agent=None: clients.append(
            _PagedHistoryClient(callback, **client_options)
        ) or clients[-1],
    )
    manager.state.set("scene", "one.md", "stored", "codex")
    snapshot = manager.open({"kind": "scene", "path": "one.md"})
    manager.close()
    return [message["text"] for message in snapshot["messages"]], clients[0].calls


def test_a_paginated_thread_is_restored_a_page_at_a_time(tmp_path: Path, monkeypatch):
    """Codex 0.160 starts threads with paginated history.

    Hydrating one whole through ``thread/read`` is deprecated for them, so
    Discuss reads the metadata, sees the mode, and pages the turns in order.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    messages, calls = _restored_messages(tmp_path, {})

    assert messages == ["First question", "First answer", "Second question", "Second answer"]
    assert [method for method, _params in calls] == ["thread/read", "thread/turns/list", "thread/turns/list"]
    assert calls[0][1]["includeTurns"] is False


def test_a_legacy_thread_on_a_paging_server_is_read_whole(tmp_path: Path, monkeypatch):
    """A thread started before the upgrade keeps the history mode it began with."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    messages, calls = _restored_messages(tmp_path, {"mode": "legacy"})

    assert messages == ["First question", "First answer", "Second question", "Second answer"]
    assert [(method, params.get("includeTurns")) for method, params in calls] == [
        ("thread/read", False), ("thread/read", True),
    ]


def test_paging_that_the_server_refuses_falls_back_to_a_whole_read(tmp_path: Path, monkeypatch):
    """Paging is the preferred read, not the only one that works.

    A server that publishes the method but will not serve it (older builds
    gate it behind the experimental API) still answers the read it always has.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    refused = CodexRequestError("thread/turns/list requires experimentalApi capability", code=-32600)
    messages, calls = _restored_messages(tmp_path, {"paging_error": refused})

    assert messages == ["First question", "First answer", "Second question", "Second answer"]
    assert [(method, params.get("includeTurns")) for method, params in calls] == [
        ("thread/read", False), ("thread/turns/list", None), ("thread/read", True),
    ]


# ── Reviewing a turn's file changes against the version it started from ───────
# Nothing here reverses a recorded diff. Prosview keeps the text as it stood
# before the agent touched it, so the review compares two versions it holds and
# the writer's choice can always be assembled.

_SCENE_BEFORE = "# One\n\nFirst document.\n\nmiddle\n\nSecond document.\n"
_SCENE_AFTER = "# One\n\nFirst draft.\n\nmiddle\n\nSecond draft.\n"


def _turn_touching(tmp_path: Path, path: str = "manuscript/one.md"):
    root = _repo(tmp_path)
    clients: list[_FakeClient] = []
    manager = DiscussManager(
        root, client_factory=lambda callback, _agent=None: clients.append(_FakeClient(callback)) or clients[-1]
    )
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    conversation = manager._conversations[cid]
    thread_id = manager._start_thread(conversation, clients[0])
    conversation.active_turn_id = "turn-x"
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_SCENE_BEFORE, encoding="utf-8")
    manager._on_agent_message("codex", {
        "id": 301,
        "method": "item/fileChange/requestApproval",
        "params": {
            "threadId": thread_id,
            "turnId": "turn-x",
            "itemId": "item-1",
            "availableDecisions": ["accept", "decline"],
            "item": {"id": "item-1", "changes": [{"path": path, "kind": "modified"}]},
        },
    })
    return root, manager, cid, target


def test_the_version_before_the_turn_is_captured_before_the_write(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    files = manager.turn_file_changes(cid)["files"]
    assert [row["path"] for row in files] == ["manuscript/one.md"]
    assert files[0]["before"] == _SCENE_BEFORE
    assert files[0]["after"] == _SCENE_AFTER
    assert [block["after"] for block in files[0]["blocks"]] == ["First draft.\n", "Second draft.\n"]
    manager.close()


def test_a_later_sighting_does_not_overwrite_the_original(tmp_path: Path):
    """Only the first sighting counts, or the writer reviews an edit against itself."""
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")
    manager._capture_before(manager._get(cid), [{"path": "manuscript/one.md"}])

    assert manager.turn_file_changes(cid)["files"][0]["before"] == _SCENE_BEFORE
    manager.close()


def test_keeping_some_blocks_writes_exactly_that_file(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    result = manager.apply_file_selection(cid, "manuscript/one.md", [1])

    assert result == {"path": "manuscript/one.md", "kept": [1], "dropped": 1, "total": 2}
    assert target.read_text(encoding="utf-8") == "# One\n\nFirst draft.\n\nmiddle\n\nSecond document.\n"
    manager.close()


def test_keeping_nothing_puts_the_file_back_exactly(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    manager.apply_file_selection(cid, "manuscript/one.md", [])

    assert target.read_text(encoding="utf-8") == _SCENE_BEFORE
    manager.close()


def test_what_the_writer_kept_becomes_the_baseline(tmp_path: Path):
    """A second look offers the edits still standing, not the ones already refused."""
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    manager.apply_file_selection(cid, "manuscript/one.md", [1])

    assert manager.turn_file_changes(cid)["files"] == []
    manager.close()


def test_a_file_that_moved_since_you_looked_is_refused(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")
    stale = manager.turn_file_changes(cid)["files"][0]["fingerprint"]
    target.write_text(_SCENE_AFTER + "\nA line you typed while reading.\n", encoding="utf-8")

    with pytest.raises(ContextError, match="changed since you looked"):
        manager.apply_file_selection(cid, "manuscript/one.md", [1], fingerprint=stale)
    # Refused means untouched: the line survives.
    assert "A line you typed while reading." in target.read_text(encoding="utf-8")
    manager.close()


def test_dropping_changes_tells_the_agent_and_keeping_them_all_does_not(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    manager.apply_file_selection(cid, "manuscript/one.md", [1, 2])
    assert manager._get(cid).agent_notes == []

    target.write_text(_SCENE_AFTER.replace("middle", "MIDDLE"), encoding="utf-8")
    manager.apply_file_selection(cid, "manuscript/one.md", [])
    owed = manager._get(cid).agent_notes
    assert owed and "dropped 1 of 1" in owed[0]
    manager.close()


def test_the_replaced_version_is_kept_in_scene_history(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path)
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    manager.apply_file_selection(cid, "manuscript/one.md", [])

    saved = sorted((root / ".proseview" / "backups").rglob("*.json"))
    assert saved, "the agent's version should stay restorable"
    assert json.loads(saved[-1].read_text(encoding="utf-8"))["content"] == _SCENE_AFTER
    manager.close()


def test_review_reaches_files_outside_the_manuscript(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path, path="story-bible/characters.md")
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    files = manager.turn_file_changes(cid)["files"]
    assert [row["path"] for row in files] == ["story-bible/characters.md"]
    manager.apply_file_selection(cid, "story-bible/characters.md", [2])
    assert target.read_text(encoding="utf-8") == "# One\n\nFirst document.\n\nmiddle\n\nSecond draft.\n"
    manager.close()


def test_a_file_the_agent_creates_reviews_as_entirely_new(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path, path="manuscript/two.md")
    target.unlink()
    manager._get(cid).file_before.clear()
    manager._capture_before(manager._get(cid), [{"path": "manuscript/two.md"}])
    target.write_text("Brand new scene.\n", encoding="utf-8")

    files = manager.turn_file_changes(cid)["files"]
    assert files[0]["before"] == ""
    assert [block["kind"] for block in files[0]["blocks"]] == ["added"]
    manager.apply_file_selection(cid, "manuscript/two.md", [])
    assert target.read_text(encoding="utf-8") == ""
    manager.close()


def test_a_file_written_with_no_warning_is_named_rather_than_left_out(tmp_path: Path):
    """The one shape the review cannot cover, said out loud.

    The version to compare against is taken when the agent announces a write.
    An agent that writes with no announcement leaves nothing to compare, and a
    review that quietly omitted the file would read as though it were untouched.
    """
    root, manager, cid, target = _turn_touching(tmp_path)
    conversation = manager._get(cid)
    conversation.file_before.clear()
    conversation.activities["item-1"] = {
        "id": "item-1",
        "kind": "fileChange",
        "status": "completed",
        "changes": [{"path": "manuscript/one.md", "kind": "modified", "diff": ""}],
    }
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    review = manager.turn_file_changes(cid)
    assert review["files"] == []
    assert review["unreviewable"] == ["manuscript/one.md"]
    manager.close()


def test_a_file_that_was_announced_is_not_called_unreviewable(tmp_path: Path):
    root, manager, cid, target = _turn_touching(tmp_path)
    manager._get(cid).activities["item-1"] = {
        "id": "item-1",
        "kind": "fileChange",
        "status": "completed",
        "changes": [{"path": "manuscript/one.md", "kind": "modified", "diff": ""}],
    }
    target.write_text(_SCENE_AFTER, encoding="utf-8")

    review = manager.turn_file_changes(cid)
    assert [row["path"] for row in review["files"]] == ["manuscript/one.md"]
    assert review["unreviewable"] == []
    manager.close()


def test_a_saved_thread_the_agent_has_not_loaded_is_resumed_not_replaced(tmp_path: Path, monkeypatch):
    """After a restart Codex has the conversation on disk but not loaded, and
    turn/start says "thread not loaded". Proseview started a new conversation
    then, so the agent lost everything said before."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _repo(tmp_path)
    clients: list[_FakeClient] = []

    def factory(callback, _agent=None):
        client = _FakeClient(callback)
        clients.append(client)
        return client

    manager = DiscussManager(root, client_factory=factory)
    cid = manager.open({"kind": "scene", "path": "one.md"})["conversation_id"]
    manager.submit(cid, client_request_id="q1", question="First question.")
    _wait_for(lambda: len(manager.get_snapshot(cid)["messages"]) >= 2)
    thread_id = manager._get(cid).thread_id
    clients[0].unloaded.add(thread_id)

    manager.submit(cid, client_request_id="q2", question="Second question.")
    _wait_for(lambda: len(manager.get_snapshot(cid)["messages"]) >= 4)

    assert clients[0].resumes == [thread_id]
    assert manager._get(cid).thread_id == thread_id
    notices = " ".join(str(n.get("message")) for n in manager.get_snapshot(cid).get("notices", []))
    assert "was unavailable" not in notices
    manager.close()
