"""Discuss must be able to sit on either agent without callers branching."""

from __future__ import annotations

from pathlib import Path

import pytest

from proseview.claude_agent_client import ClaudeAgentClient, sanitize_claude_message
from proseview.codex_app_server import CodexAppServer
from proseview.config import ConfigError, DiscussConfig
from proseview.discuss import DiscussManager, sanitize_agent_message


def _repo(tmp_path: Path, agent: str | None = None) -> Path:
    root = tmp_path / "novel"
    (root / "manuscript").mkdir(parents=True)
    (root / "manuscript" / "one.md").write_text("# One\n\nFirst.\n", encoding="utf-8")
    if agent is not None:
        (root / ".proseview.yaml").write_text(f"discuss:\n  agent: {agent}\n", encoding="utf-8")
    return root


def test_codex_remains_the_default(tmp_path):
    manager = DiscussManager(_repo(tmp_path))
    try:
        assert isinstance(manager._build_client(), CodexAppServer)
    finally:
        manager.close()


def test_claude_is_selected_from_configuration(tmp_path):
    manager = DiscussManager(_repo(tmp_path, "claude"))
    try:
        client = manager._build_client()
        assert isinstance(client, ClaudeAgentClient)
    finally:
        manager.close()


def test_each_transport_carries_its_own_translator(tmp_path):
    manager = DiscussManager(_repo(tmp_path))
    try:
        # The Codex transport has no translator of its own; the manager keeps
        # the module-level one as the default.
        assert manager._translate is sanitize_agent_message
        assert getattr(CodexAppServer, "translate", None) is None
        assert ClaudeAgentClient.translate is sanitize_claude_message
    finally:
        manager.close()


def test_unknown_agent_is_rejected_at_load(tmp_path):
    root = _repo(tmp_path, "gpt5")
    with pytest.raises(ConfigError, match="discuss.agent"):
        DiscussManager(root)


def test_agent_default_is_codex():
    assert DiscussConfig().agent == "codex"
