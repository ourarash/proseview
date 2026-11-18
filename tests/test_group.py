"""Profiles and invitation-based Group conversations, isolated from user settings."""
import copy

import pytest

from proseview.config import Config, GroupConfig
from proseview.discuss import ContextError
from tests.test_highlight_suggestions import _manager, _repo


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))


def test_profiles_and_presets_migrate_and_are_reusable_across_books(tmp_path):
    root = _repo(tmp_path)
    Config.load(root).with_overrides(group=GroupConfig(critic1_name="Plot Partner", critic1_prompt="Watch the stakes.")).save(root)
    before = (root / ".proseview.yaml").read_bytes()
    manager = _manager(root, [])
    other = _manager(_repo(tmp_path / "other"), [])
    try:
        settings = manager.group_settings()
        library = settings["library"]
        assert library["profiles"][0]["name"] == "Plot Partner"
        assert library["profiles"][0]["specialty"] == "Watch the stakes."
        assert library["default_profiles"] == [p["id"] for p in library["profiles"][:3]]
        assert len(library["presets"][0]["invitations"]) == settings["app"]["turns"]
        assert library["presets"][0]["recap"] in (1, 2, 3)
        library["profiles"].append({"id": "reader", "name": "First Reader", "specialty": "Reader expectations", "style": "Curious and candid", "agent": "claude", "model": "", "effort": ""})
        library["default_profiles"] = ["reader", library["profiles"][0]["id"]]
        saved = manager.save_group_settings({"library": library})
        assert other.group_settings()["library"] == saved["library"]
        assert (root / ".proseview.yaml").read_bytes() == before
        invalid = copy.deepcopy(library)
        invalid["presets"][0]["profiles"][0] = "missing"
        with pytest.raises(ContextError):
            manager.save_group_settings({"library": invalid})
        assert manager.group_settings()["library"] == saved["library"]
    finally:
        manager.close()
        other.close()


def test_chat_preserves_full_history_and_keeps_format_and_profile_guidance_in_background(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        participants = manager.group_settings()["participants"]
        history = [{"role": "user", "text": "I approve only the first proposal."}]
        history.extend({"role": "critic", "seat": 1, "label": "Plot Partner · Codex", "text": f"Discussion {i}"} for i in range(65))
        history.append({"role": "user", "text": "Summarize everything we all agreed on."})
        result = manager.run_group_turn(scene="one.md", participants=participants, history=history, debate_id="full-group")
        assert result["passed"] is False
        prompt = clients[0].prompts[-1]
        assert history[0]["text"] in prompt and "Discussion 64" in prompt
        assert "italic blockquote" not in prompt
        background = clients[0].thread_start_params[-1]["developerInstructions"]
        assert "italic blockquote" in background
        assert "silence" in background.lower() and "writer" in background.lower()
        saved = manager.group_history({"action": "save", "session": {"id": "full-group", "scene": "one.md", "participants": participants, "turns": history}})
        reopened = manager.group_history({"action": "get", "id": saved["saved"]})["session"]
        assert len(reopened["turns"]) == len(history)
        assert reopened["participants"][0]["name"] == participants[0]["name"]
    finally:
        manager.close()


def test_prose_edit_format_and_self_contained_recaps_apply_with_custom_group_guidance():
    from proseview.group import GENERAL_CHAT_GUIDANCE, PROSE_EDIT_FORMAT, RECAP_GUIDANCE, SECOND_OPINION_RECAP, chat_instructions
    profiles = [{"seat": 1, "name": "Reader", "specialty": "Voice", "style": "Direct", "agent": "codex", "handle": "reader", "aliases": []}]
    for custom in ('', 'Keep the narrator affectionate.', GENERAL_CHAT_GUIDANCE):
        instructions = chat_instructions(profiles[0], profiles, custom_instructions=custom)
        assert instructions.count(PROSE_EDIT_FORMAT.strip()) == 1
        assert instructions.count(RECAP_GUIDANCE.strip()) == 1
        if custom:
            assert custom.strip() in instructions
    assert PROSE_EDIT_FORMAT in SECOND_OPINION_RECAP
    assert 'italic blockquote' in PROSE_EDIT_FORMAT and 'plain blockquote' in PROSE_EDIT_FORMAT
    assert 'explicit file-and-line' in PROSE_EDIT_FORMAT
    assert '## Agreed edits' in SECOND_OPINION_RECAP and '## Choices for you' in SECOND_OPINION_RECAP
    assert 'final corrected wording' in SECOND_OPINION_RECAP


def test_pass_is_an_individual_outcome_and_survives_history(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        participants = manager.group_settings()["participants"]
        monkeypatch.setattr(manager, "_run_group_call", lambda *a, **kw: ("[GROUP_PASS]", "pass-thread"))
        result = manager.run_group_turn(scene="one.md", participants=participants, question="Anything to add?")
        assert result["passed"] is True and result["reply"] == ""
        manager.group_history({"action": "save", "session": {"id": "passed", "scene": "one.md", "participants": participants,
            "turns": [{"role": "user", "text": "Anything to add?"}, {"role": "critic", "seat": 1, "passed": True, "text": ""}]}})
        saved = manager.group_history({"action": "get", "id": "passed"})["session"]
        assert saved["turns"][1]["passed"] is True
    finally:
        manager.close()


def test_book_history_lists_all_scenes_with_useful_titles_and_stays_private_to_the_book(tmp_path):
    manager = _manager(root := _repo(tmp_path), [])
    other = _manager(_repo(tmp_path / "other"), [])
    try:
        for key, scene, text in [("opening", "one.md", "Help me strengthen the opening."), ("ending", "two.md", "Can we revisit the ending?")]:
            manager.group_history({"action": "save", "session": {"id": key, "scene": scene, "title": "Conversation", "turns": [{"role": "user", "text": text}]}})
        rows = manager.group_history({"action": "list"})["sessions"]
        assert [(row["id"], row["scene"], row["title"]) for row in rows] == [
            ("ending", "two.md", "Can we revisit the ending?"), ("opening", "one.md", "Help me strengthen the opening.")]
        assert [row["id"] for row in manager.group_history({"action": "list", "scene": "one.md"})["sessions"]] == ["opening"]
        assert other.group_history({"action": "list"})["sessions"] == []
    finally:
        manager.close()
        other.close()


def test_saving_new_groups_does_not_silently_remove_older_history(tmp_path):
    manager = _manager(_repo(tmp_path), [])
    try:
        for index in range(35):
            manager.group_history({"action": "save", "session": {"id": f"group-{index}", "scene": "one.md", "turns": [{"role": "user", "text": f"Discussion {index}"}]}})
        assert len(manager.group_history({"action": "list"})["sessions"]) == 35
        assert manager.group_history({"action": "get", "id": "group-0"})["session"]["turns"][0]["text"] == "Discussion 0"
    finally:
        manager.close()


def test_native_group_conversation_continues_when_the_scene_changes(tmp_path):
    manager = _manager(root := _repo(tmp_path), clients := [])
    (root / "manuscript" / "two.md").write_text((root / "manuscript" / "one.md").read_text())
    try:
        participants = manager.group_settings()["participants"]
        history = [{"role": "user", "scene": "one.md", "text": "Consider the opening."}]
        first = manager.run_group_turn(scene="one.md", participants=participants, history=history, debate_id="same-group")
        history.extend([{"role": "critic", "scene": "one.md", "text": first["reply"]}, {"role": "user", "scene": "two.md", "text": "Now consider this other scene."}])
        manager.run_group_turn(scene="two.md", participants=participants, history=history, debate_id="same-group")
        assert len(clients[0].thread_start_params) == 1
        assert "`two.md`" in clients[0].prompts[-1]
        assert "CURRENT SCENE" in clients[0].prompts[-1]
        assert "Now consider this other scene." in clients[0].prompts[-1]
    finally:
        manager.close()


def test_group_guidance_updates_refresh_native_instructions_without_losing_history(tmp_path, monkeypatch):
    from proseview import group
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        participants = manager.group_settings()['participants']
        history = [{'role': 'user', 'text': 'Keep this original discussion context.'}]
        first = manager.run_group_turn(scene='one.md', participants=participants, history=history, debate_id='format-update')
        history.extend([{'role': 'critic', 'seat': 1, 'text': first['reply']}, {'role': 'user', 'text': 'Now recap the agreed edits.'}])
        monkeypatch.setattr(group, 'RECAP_GUIDANCE', group.RECAP_GUIDANCE + ' UPDATED_RECAP_GUIDANCE')
        manager.run_group_turn(scene='one.md', participants=participants, history=history, debate_id='format-update')
        assert len(clients[0].thread_start_params) == 2
        assert 'UPDATED_RECAP_GUIDANCE' in clients[0].thread_start_params[-1]['developerInstructions']
        assert history[0]['text'] in clients[0].prompts[-1]
        assert history[-1]['text'] in clients[0].prompts[-1]
    finally:
        manager.close()


@pytest.mark.parametrize("agent", ["codex", "claude", "agy"])
def test_profile_inherits_individual_chat_model_and_effort_and_keeps_tools(tmp_path, agent):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        individual = manager.open({"kind": "scene", "path": "one.md"}, agent)
        manager.set_model(individual["conversation_id"], {"model": "custom-model", "effort": "high"})
        participants = manager.group_settings()["participants"]
        participants[0]["agent"] = agent
        first = manager.run_group_turn(scene="one.md", participants=participants)
        assert first["model"] == "custom-model" and first["effort"] == "high"
        participants[0]["model"] = "other-model"
        result = manager.run_group_turn(scene="one.md", participants=participants)
        assert result["model"] == "other-model" and result["effort"] == "high"
        start, turn = clients[0].thread_start_params[-1], clients[0].turn_params[-1]
        assert start["approvalPolicy"] == turn["approvalPolicy"] == "on-request"
        assert "tools" not in start and "mcpServers" not in start
        assert turn["mayWrite"] and "outputSchema" not in turn
        assert individual["conversation_id"] != result["tool_conversation_id"]
    finally:
        manager.close()


def test_native_group_threads_resume_with_new_entries_and_recover_full_history(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        participants = manager.group_settings()["participants"]
        participants[1]["agent"] = "codex"
        original = "Start here. " + "Keep the complete proposal. " * 500
        history = [{"role": "user", "text": original}]
        first = manager.run_group_turn(scene="one.md", participants=participants, history=history, debate_id="resume")
        assert "SCENE FRONTMATTER (background context — may be outdated after revisions; if you base a proposal on these frontmatter notes, still make it and briefly mention to the writer that it is based on the frontmatter, which might be outdated)" in clients[0].prompts[0]
        history.append({"role": "critic", "label": "Story Editor · Codex", "text": first["reply"]})
        history.append({"role": "user", "text": "Now consider another angle."})
        manager.run_group_turn(scene="one.md", participants=participants, history=history, debate_id="resume")
        client = clients[0]
        assert len(client.thread_start_params) == 1
        assert original not in client.prompts[-1] and "Now consider another angle." in client.prompts[-1]
        # A lost provider thread recovers the entire shared conversation.
        client.threads.clear()
        history.extend([{"role": "critic", "label": "Story Editor · Codex", "text": "Another angle."}, {"role": "user", "text": "Summarize everything."}])
        manager.run_group_turn(scene="one.md", participants=participants, history=history, debate_id="resume")
        assert original in client.prompts[-1] and "Summarize everything." in client.prompts[-1]
        manager.group_history({"action": "save", "session": {"id": "long-proposal", "scene": "one.md", "participants": participants, "turns": history}})
        assert manager.group_history({"action": "get", "id": "long-proposal"})["session"]["turns"][0]["text"] == original
    finally:
        manager.close()


@pytest.mark.parametrize("mutation", [
    lambda lib: lib.update(default_profiles=[{}, "voice-editor"]),
    lambda lib: lib["profiles"][0].update(agent="unknown"),
    lambda lib: lib["profiles"][1].update(id=lib["profiles"][0]["id"]),
    lambda lib: lib["presets"][0].update(invitations=[]),
    lambda lib: lib["presets"][0].update(recap=4),
    lambda lib: lib["presets"][0]["invitations"][0].update(seat=True),
])
def test_invalid_library_is_rejected_without_overwriting_saved_settings(tmp_path, mutation):
    manager = _manager(_repo(tmp_path), [])
    try:
        original = manager.group_settings()["library"]
        manager.save_group_settings({"library": original})
        invalid = copy.deepcopy(original)
        mutation(invalid)
        with pytest.raises(ContextError):
            manager.save_group_settings({"library": invalid})
        assert manager.group_settings()["library"] == original
    finally:
        manager.close()


def test_normal_group_reply_is_not_rewritten_by_legacy_debate_parser(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        text = "I agree with your decision.\n\nNOTHING NEW"
        monkeypatch.setattr(manager, "_run_group_call", lambda *a, **kw: (text, "thread"))
        result = manager.run_group_turn(scene="one.md", participants=manager.group_settings()["participants"])
        assert result["reply"] == text and not result["passed"]
    finally:
        manager.close()


@pytest.mark.parametrize("agent", ["codex", "claude", "agy"])
def test_group_invokes_only_an_explicit_available_skill_using_the_native_input(tmp_path, monkeypatch, agent):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        participants = manager.group_settings()["participants"]
        participants[0]["agent"] = agent
        skill = {"name": "scene-notes", "path": str(tmp_path / "scene-notes" / "SKILL.md")}
        looked_up = []
        def available(*, force_reload=False, agent="codex"):
            looked_up.append(agent)
            return [skill]
        monkeypatch.setattr(manager, "list_skills", available)
        manager.run_group_turn(scene="one.md", participants=participants, question="$scene-notes check this scene.", skill=skill)
        assert looked_up == [agent]
        assert clients[0].turn_params[-1]["input"][-1] == {"type": "skill", **skill}
        manager.run_group_turn(scene="one.md", participants=participants, history=[{"role": "user", "text": "$scene-notes was requested earlier."}, {"role": "user", "text": "Continue normally."}])
        assert len(clients[0].turn_params[-1]["input"]) == 1, "an old skill mention must not invoke the skill again"
        with pytest.raises(ContextError, match="unavailable"):
            manager.run_group_turn(scene="one.md", participants=participants, skill={**skill, "path": "/unavailable/SKILL.md"})
    finally:
        manager.close()


def test_group_history_has_no_artificial_entry_cutoff_and_uses_chat_timeout(tmp_path, monkeypatch):
    manager = _manager(_repo(tmp_path), [])
    try:
        participants = manager.group_settings()["participants"]
        history = [{"role": "user", "text": f"Message {index}"} for index in range(2100)]
        calls = []
        def run(*args, **kwargs):
            calls.append(kwargs)
            return "Reply.", "thread"
        monkeypatch.setattr(manager, "_run_group_call", run)
        manager.run_group_turn(scene="one.md", participants=participants, history=history)
        assert calls[0]["timeout"] == 60 * 60
        manager.group_history({"action": "save", "session": {"id": "long-group", "scene": "one.md", "turns": history, "participants": participants}})
        assert len(manager.group_history({"action": "get", "id": "long-group"})["session"]["turns"]) == 2100
    finally:
        manager.close()


def test_agy_group_profile_persists_resumes_and_recovers_missing_thread(tmp_path):
    manager = _manager(_repo(tmp_path), clients := [])
    try:
        settings = manager.group_settings()
        assert "agy" in settings["chat_models"]
        library = settings["library"]
        library["profiles"].append({
            "id": "agy-editor",
            "name": "Agy Editor",
            "specialty": "Pacing",
            "style": "Direct",
            "agent": "agy",
            "model": "gemini-4-argon",
            "effort": "medium",
        })
        library["default_profiles"] = ["agy-editor", library["profiles"][0]["id"]]
        saved = manager.save_group_settings({"library": library})
        assert saved["participants"][0]["agent"] == "agy"

        participants = saved["participants"]
        history = [{"role": "user", "text": "Original writer request."}]
        first = manager.run_group_turn(scene="one.md", participants=participants, history=history, debate_id="agy-group")
        assert first["reply"]

        history.extend([
            {"role": "critic", "seat": 1, "agent": "agy", "label": "Agy Editor · Agy", "text": first["reply"]},
            {"role": "user", "text": "Follow up."},
        ])
        # Simulate lost Agy ACP session after restart -> AgyRequestError triggers full-history recovery.
        clients[0].threads.clear()
        second = manager.run_group_turn(scene="one.md", participants=participants, history=history, debate_id="agy-group")
        assert second["reply"]
        assert "Original writer request." in clients[0].prompts[-1]
        assert "Follow up." in clients[0].prompts[-1]

        unpinned = [{**participants[0], "model": "", "effort": ""}, participants[1]]
        third = manager.run_group_turn(scene="one.md", participants=unpinned, history=history, debate_id="agy-group-default")
        assert third["model"] == "Agy default"
    finally:
        manager.close()


def test_two_vs_three_seat_workflows_moderator_and_config_roundtrip(tmp_path):
    from proseview.discuss import _parse_group_moderator_output
    from proseview.group import adapt_preset_for_participants
    from proseview.suggestions import _clean_group_session

    root = _repo(tmp_path)
    Config.load(root).with_overrides(
        group=GroupConfig(critic3_name="Timeline Keeper", critic3_prompt="Track every hour and prop.")
    ).save(root)
    reloaded = Config.load(root)
    assert reloaded.group.critic3_name == "Timeline Keeper"
    assert reloaded.group.critic3_prompt == "Track every hour and prop."

    manager = _manager(root, [])
    try:
        settings = manager.group_settings()
        participants = settings["participants"]
        assert len(participants) == 3
        assert participants[2]["name"] == "Timeline Keeper" and participants[2]["agent"] == "agy"

        second_op = next(p for p in settings["library"]["presets"] if p["id"] == "second_opinion")
        folded = adapt_preset_for_participants(second_op, participants[:2])
        assert all(s["seat"] in (1, 2) for s in folded["invitations"]) and folded["recap"] == 2

        legacy_two = {
            "id": "second_opinion",
            "invitations": [{"seat": 2, "prompt": "Audit."}, {"seat": 1, "prompt": "Respond."}],
            "recap": 2,
        }
        expanded = adapt_preset_for_participants(legacy_two, participants)
        assert [s["seat"] for s in expanded["invitations"]] == [2, 3, 1] and expanded["recap"] == 3

        parsed = _parse_group_moderator_output(
            '{"agreed": [{"title": "Fix date", "line": "17", "original": "Nov", "replacement": "Oct", "why": "Matches ch03", "proposed_by": "Critic 3", "accepted": true}],'
            ' "suggested": [],'
            ' "open": [{"issue": "Clock pause", "critic1": "Cut", "critic2": "Keep", "critic3": "Keep if October fixed"}]}'
        )
        assert parsed["plan"][0]["proposed_by"] == "Critic 3"
        assert parsed["open"][0]["critic3"] == "Keep if October fixed"

        session = _clean_group_session({
            "id": "three-seat-hist",
            "scene": "one.md",
            "participants": participants,
            "turns": [{"role": "critic", "seat": 3, "agent": "agy", "text": "Timeline note."}],
            "plans": [{"after_turn": 1, "agent": "claude", "items": [], "open": parsed["open"]}],
        })
        assert session["turns"][0]["seat"] == 3
        assert session["plans"][0]["open"][0]["critic3"] == "Keep if October fixed"
    finally:
        manager.close()
