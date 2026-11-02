"""Profiles and invitation-based Room conversations, isolated from user settings."""
import copy

import pytest

from proseview.config import Config, RoomConfig
from proseview.discuss import ContextError
from tests.test_highlight_suggestions import _manager, _repo


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


def test_profiles_and_presets_migrate_and_are_reusable_across_books(tmp_path):
    root = _repo(tmp_path)
    Config.load(root).with_overrides(room=RoomConfig(critic1_name="Plot Partner", critic1_prompt="Watch the stakes.")).save(root)
    before = (root / ".proseview.yaml").read_bytes()
    manager = _manager(root, [])
    other = _manager(_repo(tmp_path / "other"), [])
    try:
        settings = manager.room_settings()
        library = settings["library"]
        assert library["profiles"][0]["name"] == "Plot Partner"
        assert library["profiles"][0]["specialty"] == "Watch the stakes."
        assert library["default_profiles"] == [p["id"] for p in library["profiles"][:2]]
        assert len(library["presets"][0]["invitations"]) == settings["app"]["turns"]
        assert library["presets"][0]["recap"] in (1, 2)
        library["profiles"].append({"id": "reader", "name": "First Reader", "specialty": "Reader expectations", "style": "Curious and candid", "agent": "claude", "model": "", "effort": ""})
        library["default_profiles"] = ["reader", library["profiles"][0]["id"]]
        saved = manager.save_room_settings({"library": library})
        assert other.room_settings()["library"] == saved["library"]
        assert (root / ".proseview.yaml").read_bytes() == before
        invalid = copy.deepcopy(library)
        invalid["presets"][0]["profiles"][0] = "missing"
        with pytest.raises(ContextError):
            manager.save_room_settings({"library": invalid})
        assert manager.room_settings()["library"] == saved["library"]
    finally:
        manager.close()
        other.close()


def test_chat_preserves_full_history_and_keeps_format_and_profile_guidance_in_background(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        participants = manager.room_settings()["participants"]
        history = [{"role": "user", "text": "I approve only the first proposal."}]
        history.extend({"role": "critic", "seat": 1, "label": "Plot Partner · Codex", "text": f"Discussion {i}"} for i in range(65))
        history.append({"role": "user", "text": "Summarize everything we all agreed on."})
        result = manager.run_room_turn(scene="one.md", participants=participants, history=history, debate_id="full-room")
        assert result["passed"] is False
        prompt = clients[0].prompts[-1]
        assert history[0]["text"] in prompt and "Discussion 64" in prompt
        assert "italic blockquote" not in prompt
        background = clients[0].thread_start_params[-1]["developerInstructions"]
        assert "italic blockquote" in background
        assert "silence" in background.lower() and "writer" in background.lower()
        saved = manager.room_history({"action": "save", "session": {"id": "full-room", "scene": "one.md", "participants": participants, "turns": history}})
        reopened = manager.room_history({"action": "get", "id": saved["saved"]})["session"]
        assert len(reopened["turns"]) == len(history)
        assert reopened["participants"][0]["name"] == participants[0]["name"]
    finally:
        manager.close()


def test_pass_is_an_individual_outcome_and_survives_history(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        participants = manager.room_settings()["participants"]
        monkeypatch.setattr(manager, "_run_room_call", lambda *a, **kw: ("[ROOM_PASS]", "pass-thread"))
        result = manager.run_room_turn(scene="one.md", participants=participants, question="Anything to add?")
        assert result["passed"] is True and result["reply"] == ""
        manager.room_history({"action": "save", "session": {"id": "passed", "scene": "one.md", "participants": participants,
            "turns": [{"role": "user", "text": "Anything to add?"}, {"role": "critic", "seat": 1, "passed": True, "text": ""}]}})
        saved = manager.room_history({"action": "get", "id": "passed"})["session"]
        assert saved["turns"][1]["passed"] is True
    finally:
        manager.close()


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_profile_inherits_individual_chat_model_and_effort_and_keeps_tools(tmp_path, agent):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        individual = manager.open({"kind": "scene", "path": "one.md"}, agent)
        manager.set_model(individual["conversation_id"], {"model": "custom-model", "effort": "high"})
        participants = manager.room_settings()["participants"]
        participants[0]["agent"] = agent
        first = manager.run_room_turn(scene="one.md", participants=participants)
        assert first["model"] == "custom-model" and first["effort"] == "high"
        participants[0]["model"] = "other-model"
        result = manager.run_room_turn(scene="one.md", participants=participants)
        assert result["model"] == "other-model" and result["effort"] == "high"
        start, turn = clients[0].thread_start_params[-1], clients[0].turn_params[-1]
        assert start["approvalPolicy"] == turn["approvalPolicy"] == "on-request"
        assert "tools" not in start and "mcpServers" not in start
        assert turn["mayWrite"] and "outputSchema" not in turn
        assert individual["conversation_id"] != result["tool_conversation_id"]
    finally:
        manager.close()


def test_native_room_threads_resume_with_new_entries_and_recover_full_history(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        participants = manager.room_settings()["participants"]
        participants[1]["agent"] = "codex"
        original = "Start here. " + "Keep the complete proposal. " * 500
        history = [{"role": "user", "text": original}]
        first = manager.run_room_turn(scene="one.md", participants=participants, history=history, debate_id="resume")
        history.append({"role": "critic", "label": "Story Editor · Codex", "text": first["reply"]})
        history.append({"role": "user", "text": "Now consider another angle."})
        manager.run_room_turn(scene="one.md", participants=participants, history=history, debate_id="resume")
        client = clients[0]
        assert len(client.thread_start_params) == 1
        assert original not in client.prompts[-1] and "Now consider another angle." in client.prompts[-1]
        # A lost provider thread recovers the entire shared conversation.
        client.threads.clear()
        history.extend([{"role": "critic", "label": "Story Editor · Codex", "text": "Another angle."}, {"role": "user", "text": "Summarize everything."}])
        manager.run_room_turn(scene="one.md", participants=participants, history=history, debate_id="resume")
        assert original in client.prompts[-1] and "Summarize everything." in client.prompts[-1]
        manager.room_history({"action": "save", "session": {"id": "long-proposal", "scene": "one.md", "participants": participants, "turns": history}})
        assert manager.room_history({"action": "get", "id": "long-proposal"})["session"]["turns"][0]["text"] == original
    finally:
        manager.close()


@pytest.mark.parametrize("mutation", [
    lambda lib: lib.update(default_profiles=[{}, "voice-editor"]),
    lambda lib: lib["profiles"][0].update(agent="unknown"),
    lambda lib: lib["profiles"][1].update(id=lib["profiles"][0]["id"]),
    lambda lib: lib["presets"][0].update(invitations=[]),
    lambda lib: lib["presets"][0].update(recap=3),
    lambda lib: lib["presets"][0]["invitations"][0].update(seat=True),
])
def test_invalid_library_is_rejected_without_overwriting_saved_settings(tmp_path, mutation):
    manager = _manager(_repo(tmp_path), [])
    try:
        original = manager.room_settings()["library"]
        manager.save_room_settings({"library": original})
        invalid = copy.deepcopy(original)
        mutation(invalid)
        with pytest.raises(ContextError):
            manager.save_room_settings({"library": invalid})
        assert manager.room_settings()["library"] == original
    finally:
        manager.close()


def test_normal_room_reply_is_not_rewritten_by_legacy_debate_parser(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        text = "I agree with your decision.\n\nNOTHING NEW"
        monkeypatch.setattr(manager, "_run_room_call", lambda *a, **kw: (text, "thread"))
        result = manager.run_room_turn(scene="one.md", participants=manager.room_settings()["participants"])
        assert result["reply"] == text and not result["passed"]
    finally:
        manager.close()


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_room_invokes_only_an_explicit_available_skill_using_the_native_input(tmp_path, monkeypatch, agent):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        participants = manager.room_settings()["participants"]
        participants[0]["agent"] = agent
        skill = {"name": "scene-notes", "path": str(tmp_path / "scene-notes" / "SKILL.md")}
        looked_up = []
        def available(*, force_reload=False, agent="codex"):
            looked_up.append(agent)
            return [skill]
        monkeypatch.setattr(manager, "list_skills", available)
        manager.run_room_turn(scene="one.md", participants=participants, question="$scene-notes check this scene.", skill=skill)
        assert looked_up == [agent]
        assert clients[0].turn_params[-1]["input"][-1] == {"type": "skill", **skill}
        manager.run_room_turn(scene="one.md", participants=participants, history=[{"role": "user", "text": "$scene-notes was requested earlier."}, {"role": "user", "text": "Continue normally."}])
        assert len(clients[0].turn_params[-1]["input"]) == 1, "an old skill mention must not invoke the skill again"
        with pytest.raises(ContextError, match="unavailable"):
            manager.run_room_turn(scene="one.md", participants=participants, skill={**skill, "path": "/unavailable/SKILL.md"})
    finally:
        manager.close()


def test_room_history_has_no_artificial_entry_cutoff_and_uses_chat_timeout(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        participants = manager.room_settings()["participants"]
        history = [{"role": "user", "text": f"Message {index}"} for index in range(2100)]
        calls = []
        def run(*args, **kwargs):
            calls.append(kwargs)
            return "Reply.", "thread"
        monkeypatch.setattr(manager, "_run_room_call", run)
        manager.run_room_turn(scene="one.md", participants=participants, history=history)
        assert calls[0]["timeout"] == 60 * 60
        manager.room_history({"action": "save", "session": {"id": "long-room", "scene": "one.md", "turns": history, "participants": participants}})
        assert len(manager.room_history({"action": "get", "id": "long-room"})["session"]["turns"]) == 2100
    finally:
        manager.close()
