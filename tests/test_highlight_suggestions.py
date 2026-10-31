"""Suggest on a highlight: one request to an agent, outside every conversation.

The writer clicks a mark and asks for rewrites. That must not start a chat,
appear in History, or leave a session in the agent's own resume list; it may
read the book but never write; and what it is told, sees and runs with comes
from settings the writer controls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proseview.config import Config, SuggestionsConfig
from proseview.discuss import ContextError, DiscussManager
from proseview.lexical import glue_share_pct
from proseview.suggestions import (
    DEFAULT_PASS_PROMPTS,
    DEFAULT_PROMPT,
    AgentSuggestionSettings,
    SuggestionAppSettings,
    claude_instruction_files,
    pass_prompt_keys,
    render_prompt,
)

from .transport_fakes import ClaudeFakeClient, CodexFakeClient


@pytest.fixture(autouse=True)
def isolated_agent_settings(tmp_path, monkeypatch):
    """Keep the developer's own Codex, Claude and Prosview settings out of it."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex" / "config.toml").write_text(
        '[mcp_servers.docs]\nurl = "https://example.test/mcp"\n\n'
        '[mcp_servers.repl]\ncommand = "repl"\n', encoding="utf-8")
    (tmp_path / "claude").mkdir()
    (tmp_path / "claude" / ".claude.json").write_text(
        json.dumps({"mcpServers": {"notes": {"command": "notes-mcp"}}}), encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript").mkdir(parents=True)
    (root / "manuscript" / "one.md").write_text(
        "---\ncharacters:\n  - Mira\n---\n# One\n\nFirst document.\n\nMira left at dawn.\n", encoding="utf-8")
    (root / "story-bible" / "characters").mkdir(parents=True)
    (root / "story-bible" / "characters" / "mira.md").write_text("Mira never swears.\n", encoding="utf-8")
    return root


@pytest.fixture(params=["codex", "claude"])
def agent(request):
    return request.param


def _manager(root: Path, clients: list):
    def factory(callback, agent="codex"):
        client = (ClaudeFakeClient if agent == "claude" else CodexFakeClient)(callback, agent)
        clients.append(client)
        return client
    return DiscussManager(root, client_factory=factory)


def _suggest(manager: DiscussManager, agent: str, **overrides):
    args = dict(pass_name="sticky_sentences", label="Sticky Sentences",
                explanation="Marks sentences of 10+ words where more than 60% are glue words.",
                note="64% glue words", text="First document.", paragraph="First document.",
                scene="one.md")
    args.update(overrides)
    return manager.suggest_for_highlight(agent, **args)


def test_a_suggestion_returns_checked_alternatives_and_how_it_was_made(tmp_path: Path, agent: str):
    clients: list = []
    manager = _manager(_repo(tmp_path), clients)
    try:
        result = _suggest(manager, agent, chat_model="m-1", chat_effort="low")
    finally:
        manager.close()
    assert [row["text"] for row in result["alternatives"]] == [
        "Revised document.", "A revised document.", "Document, revised."]
    used = result["used"]
    assert used["agent"] == agent and used["model"] == "m-1" and used["effort"] == "low"
    assert used["tools"] == "read"
    assert used["timings"]["total"] >= used["timings"]["thread_started"] >= 0


def test_a_suggestion_runs_outside_every_conversation_and_cannot_write(tmp_path: Path, agent: str):
    clients: list = []
    manager = _manager(_repo(tmp_path), clients)
    try:
        _suggest(manager, agent)
        assert manager._threads == {} and manager._one_offs == {} and manager._conversations == {}
    finally:
        manager.close()
    (start,) = clients[0].thread_start_params
    assert start["ephemeral"] is True and start["approvalPolicy"] == "never"
    (turn,) = clients[0].turn_params
    assert turn["mayWrite"] is False
    assert turn["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}
    assert turn["outputSchema"]["properties"]["alternatives"]["maxItems"] == 3


def test_codex_gets_read_only_tools_and_no_mcp_servers_by_default(tmp_path: Path):
    clients: list = []
    manager = _manager(_repo(tmp_path), clients)
    try:
        result = _suggest(manager, "codex")
    finally:
        manager.close()
    config = clients[0].thread_start_params[0]["config"]
    assert config["mcp_servers.docs.enabled"] is False and config["mcp_servers.repl.enabled"] is False
    assert config["web_search"] == "disabled"
    assert "project_doc_max_bytes" not in config, "AGENTS.md is read as the chat reads it"
    assert result["used"]["mcp_servers"] == []


def test_an_mcp_server_switched_on_is_left_on(tmp_path: Path):
    SuggestionAppSettings().save({"codex": AgentSuggestionSettings(mcp_on=["docs"]),
                                  "claude": AgentSuggestionSettings(mcp_on=["notes"])})
    clients: list = []
    manager = _manager(_repo(tmp_path), clients)
    try:
        codex = _suggest(manager, "codex")
        claude = _suggest(manager, "claude")
    finally:
        manager.close()
    by_agent = {c.agent: c for c in clients}
    config = by_agent["codex"].thread_start_params[0]["config"]
    assert "mcp_servers.docs.enabled" not in config and config["mcp_servers.repl.enabled"] is False
    assert by_agent["claude"].thread_start_params[0]["mcpServers"] == {"notes": {"command": "notes-mcp"}}
    assert codex["used"]["mcp_servers"] == ["docs"] and claude["used"]["mcp_servers"] == ["notes"]


def test_claude_reads_its_project_instructions_as_the_chat_does(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "CLAUDE.md").write_text("Follow @AGENTS.md\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# House rules\n", encoding="utf-8")
    clients: list = []
    manager = _manager(root, clients)
    try:
        result = _suggest(manager, "claude")
    finally:
        manager.close()
    start = clients[0].thread_start_params[0]
    assert start["settingSources"] == ["user", "project", "local"]
    assert start["tools"] == ["Read", "Grep", "Glob"]
    assert "House rules" not in start["developerInstructions"], "Claude loads it; Prosview does not paste it"
    assert result["used"]["instruction_files"] == ["CLAUDE.md", "AGENTS.md"]


def test_instructions_switched_off_reach_neither_agent(tmp_path: Path):
    root = _repo(tmp_path)
    Config().with_overrides(suggestions=SuggestionsConfig(instructions=False)).save(root)
    clients: list = []
    manager = _manager(root, clients)
    try:
        _suggest(manager, "codex")
        _suggest(manager, "claude")
    finally:
        manager.close()
    by_agent = {c.agent: c for c in clients}
    assert by_agent["codex"].thread_start_params[0]["config"]["project_doc_max_bytes"] == 0
    assert by_agent["claude"].thread_start_params[0]["settingSources"] == ["user"]


def test_no_tools_means_no_tools(tmp_path: Path):
    SuggestionAppSettings().save({"codex": AgentSuggestionSettings(tools="none"),
                                  "claude": AgentSuggestionSettings(tools="none")})
    clients: list = []
    manager = _manager(_repo(tmp_path), clients)
    try:
        _suggest(manager, "claude")
    finally:
        manager.close()
    assert clients[0].thread_start_params[0]["tools"] == []
    assert "Do not use any tools" in clients[0].prompts[0]


def test_the_whole_scene_goes_along_when_asked(tmp_path: Path):
    root = _repo(tmp_path)
    Config().with_overrides(suggestions=SuggestionsConfig(context="scene")).save(root)
    clients: list = []
    manager = _manager(root, clients)
    try:
        result = _suggest(manager, "codex")
    finally:
        manager.close()
    prompt = clients[0].prompts[0]
    assert "THE WHOLE SCENE, FOR CONTEXT" in prompt and "Mira left at dawn." in prompt
    assert "Mira never swears." not in prompt, "character notes are not sent"
    assert "character_files" not in result["used"]


def test_a_leftover_characters_setting_is_ignored_quietly(tmp_path: Path, recwarn):
    root = _repo(tmp_path)
    (root / ".proseview.yaml").write_text("suggestions:\n  characters: true\n  context: scene\n", encoding="utf-8")
    cfg = Config.load(root)
    assert cfg.suggestions.context == "scene"
    assert not [w for w in recwarn if "characters" in str(w.message)]
    cfg.save(root)
    assert "characters" not in (root / ".proseview.yaml").read_text(encoding="utf-8")


def test_a_scene_outside_the_manuscript_is_not_read(tmp_path: Path):
    root = _repo(tmp_path)
    Config().with_overrides(suggestions=SuggestionsConfig(context="scene")).save(root)
    (root / "secret.md").write_text("Not prose.\n", encoding="utf-8")
    clients: list = []
    manager = _manager(root, clients)
    try:
        _suggest(manager, "codex", scene="../secret.md")
    finally:
        manager.close()
    assert "Not prose." not in clients[0].prompts[0]


def test_sticky_suggestions_carry_each_options_glue_share(tmp_path: Path):
    manager = _manager(_repo(tmp_path), [])
    try:
        result = _suggest(manager, "codex")
        other = _suggest(manager, "codex", pass_name="echoes")
    finally:
        manager.close()
    assert result["original_glue_pct"] == glue_share_pct("First document.")
    assert [row["glue_pct"] for row in result["alternatives"]] == [
        glue_share_pct(row["text"]) for row in result["alternatives"]]
    assert "glue_pct" not in other["alternatives"][0] and "original_glue_pct" not in other


def test_a_suggestion_refuses_an_empty_passage(tmp_path: Path):
    manager = _manager(_repo(tmp_path), [])
    try:
        with pytest.raises(ContextError):
            _suggest(manager, "codex", text="   ")
    finally:
        manager.close()


def test_a_suggestion_that_never_finishes_times_out(tmp_path: Path):
    manager = _manager(_repo(tmp_path), [])
    try:
        manager._client_for("codex").hold_next_turn = True
        with pytest.raises(ContextError, match="too long"):
            _suggest(manager, "codex", timeout=0.2)
        assert manager._one_offs == {}
    finally:
        manager.close()


# -- prompts -----------------------------------------------------------------

def _render(cfg: SuggestionsConfig, **overrides) -> str:
    args = dict(pass_name="echoes", check="Echoes", explanation="Marks a word that comes back.",
                note="9 words after “walked”", flagged="walking", passage="She was walking again.",
                context="She walked out. She was walking again.", context_label="ITS PARAGRAPH",
                count=3, tools="read")
    args.update(overrides)
    return render_prompt(cfg, **args)


def test_the_default_prompt_fills_its_placeholders_and_keeps_the_fixed_part():
    prompt = _render(SuggestionsConfig())
    assert "“Echoes” check" in prompt and "9 words after" in prompt
    assert "Change the repeated word (walking)" in prompt
    assert "<<<\nShe was walking again.\n>>>" in prompt
    assert "Give exactly 3 different rewrites" in prompt
    assert "ITS PARAGRAPH, FOR CONTEXT" in prompt


def test_a_writers_prompts_replace_the_defaults_but_not_the_fixed_part():
    cfg = SuggestionsConfig(prompt="Keep it British. Check: {check}. Unknown {thing} stays.",
                            pass_prompts=(("echoes", "Never touch {flagged}."),))
    prompt = _render(cfg)
    assert prompt.startswith("Keep it British. Check: Echoes. Unknown {thing} stays.")
    assert "Never touch walking." in prompt
    assert "Change the repeated word" not in prompt
    assert "Give exactly 3 different rewrites" in prompt


def test_an_emptied_check_prompt_adds_nothing():
    prompt = _render(SuggestionsConfig(pass_prompts=(("echoes", ""),)))
    assert "Change the repeated word" not in prompt


def test_a_dialogue_tag_mark_gets_each_of_its_kinds():
    note = "Other than said or asked: “replied”; Adverb on a dialogue tag: “shyly”"
    assert pass_prompt_keys("dialogue_tags", note) == ["dialogue_tags.fancy", "dialogue_tags.adverb"]
    prompt = _render(SuggestionsConfig(), pass_name="dialogue_tags", note=note)
    assert DEFAULT_PASS_PROMPTS["dialogue_tags.fancy"] in prompt
    assert DEFAULT_PASS_PROMPTS["dialogue_tags.adverb"] in prompt


# -- settings ------------------------------------------------------------------

def test_settings_round_trip_and_only_changes_reach_the_book(tmp_path: Path):
    root = _repo(tmp_path)
    manager = _manager(root, [])
    try:
        shown = manager.suggestion_settings()
        assert shown["book"]["prompt"] == DEFAULT_PROMPT
        assert shown["app"]["codex"] == {"model": "", "effort": "", "tools": "read", "mcp_on": []}
        assert [s["name"] for s in shown["mcp"]["codex"]] == ["docs", "repl"]
        assert [s["name"] for s in shown["mcp"]["claude"]] == ["notes"]

        book = dict(shown["book"])
        book["context"] = "scene"
        book["pass_prompts"] = dict(book["pass_prompts"], echoes="Mine.")
        saved = manager.save_suggestion_settings({
            "book": book,
            "app": {"claude": {"model": "sonnet", "effort": "low", "tools": "web", "mcp_on": ["notes"]}},
        })
    finally:
        manager.close()
    yaml_text = (root / ".proseview.yaml").read_text(encoding="utf-8")
    assert "context: scene" in yaml_text and "echoes: Mine." in yaml_text
    assert "\n  prompt:" not in yaml_text, "an unchanged prompt is not written"
    assert "sonnet" not in yaml_text, "the model belongs to this computer, not the book"
    assert saved["app"]["claude"]["model"] == "sonnet" and saved["app"]["codex"]["model"] == ""
    assert saved["book"]["pass_prompts"]["echoes"] == "Mine."


def test_claude_instruction_files_follow_imports(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text("See @docs/style.md and AGENTS.md\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "style.md").write_text("Short lines.\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Rules.\n", encoding="utf-8")
    # A plain mention is not an import; Claude would have to read it.
    assert claude_instruction_files(tmp_path) == ["CLAUDE.md", "docs/style.md"]


def test_glue_share_pct():
    assert glue_share_pct("") == 0
    assert glue_share_pct("the of in her") == 100
    assert glue_share_pct("Rain hammered the roof.") == 25


def test_history_names_a_save_that_applied_or_undid_a_suggestion():
    from proseview.server import _suggestion_save_source

    assert _suggestion_save_source({"check": "Sticky Sentences", "agent": "codex"}) == "Suggestion: Sticky Sentences (Codex)"
    assert _suggestion_save_source({"check": "Echoes", "agent": "claude"}) == "Suggestion: Echoes (Claude)"
    assert _suggestion_save_source({"check": "Echoes", "undone": True}) == "Suggestion undone: Echoes"
    # Only checked parts reach History, which shows them as text.
    assert _suggestion_save_source({"check": "<img src=x onerror=alert(1)>", "agent": "codex"}) == "Manual Save"
    assert _suggestion_save_source({"check": "Echoes", "agent": "gpt"}) == "Manual Save"
    assert _suggestion_save_source(None) == "Manual Save"


def test_a_manner_phrase_gets_the_adverb_prompt():
    assert pass_prompt_keys("dialogue_tags", "Describes how it was said: “with a sigh”") == ["dialogue_tags.adverb"]
