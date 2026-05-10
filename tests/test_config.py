"""Tests for the ``.proseview.yaml`` loader and defaults.

M1 contract: every book-specific constant lives in the config; a missing
``.proseview.yaml`` yields defaults without warning; unknown keys warn but
still load; invalid values fail loudly.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import (  # noqa: E402
    Config,
    ConfigError,
    EditorConfig,
    RepoTabConfig,
    _parse_yaml,
)


def test_defaults_when_file_missing(tmp_path: Path):
    cfg = Config.load(tmp_path)
    assert cfg == Config()
    assert cfg.manuscript_path == "manuscript/"
    assert cfg.target_words == 80000
    assert cfg.mattr_band == (0.74, 0.77)
    assert cfg.editor.scheme == "vscode"


def test_roundtrip_full_config(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        """
        manuscript_path: book/
        target_words: 90000
        daily_target: 750
        mattr_band: [0.70, 0.80]
        mtld_band: [100, 140]
        chapter_pattern: "part*"
        characters:
          - Alpha
          - Bravo
        locations:
          - Riverfront
        editor:
          scheme: cursor
        """.strip(),
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path)
    assert cfg.manuscript_path == "book/"
    assert cfg.target_words == 90000
    assert cfg.daily_target == 750
    assert cfg.mattr_band == (0.70, 0.80)
    assert cfg.mtld_band == (100.0, 140.0)
    assert cfg.chapter_pattern == "part*"
    assert cfg.characters == ("Alpha", "Bravo")
    assert cfg.locations == ("Riverfront",)
    assert cfg.editor == EditorConfig(scheme="cursor", url_template=None)


def test_manuscript_path_is_normalized_with_trailing_slash(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "manuscript_path: book\n", encoding="utf-8",
    )
    cfg = Config.load(tmp_path)
    assert cfg.manuscript_path == "book/"
    assert cfg.manuscript_subdir == "book"


def test_custom_editor_requires_url_template(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "editor:\n  scheme: custom\n", encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="url_template"):
        Config.load(tmp_path)


def test_custom_editor_accepts_url_template(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        'editor:\n  scheme: custom\n  url_template: "emacsclient:{abs_path}#L{line}"\n',
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path)
    assert cfg.editor.scheme == "custom"
    assert cfg.editor.url_template == "emacsclient:{abs_path}#L{line}"


def test_unknown_editor_scheme_rejected(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "editor:\n  scheme: nano\n", encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="nano"):
        Config.load(tmp_path)


def test_unknown_top_level_key_warns_but_loads(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "target_words: 65000\nmystery_key: 42\n", encoding="utf-8",
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = Config.load(tmp_path)
    assert cfg.target_words == 65000
    assert any("mystery_key" in str(w.message) for w in caught)


def test_invalid_band_raises(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "mattr_band: [0.74]\n", encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="mattr_band"):
        Config.load(tmp_path)


def test_invalid_target_words_raises(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "target_words: many\n", encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="target_words"):
        Config.load(tmp_path)


def test_repo_tab_defaults_are_populated():
    cfg = Config()
    assert cfg.repo_tab == RepoTabConfig()
    assert "plans" in cfg.repo_tab.folders
    assert "manuscript" not in cfg.repo_tab.folders
    assert cfg.repo_tab.preview_max_bytes == 512 * 1024


def test_repo_tab_config_loaded(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "repo_tab:\n"
        "  folders:\n"
        "    - craft\n"
        "    - process\n"
        "  preview_max_bytes: 2048\n",
        encoding="utf-8",
    )
    cfg = Config.load(tmp_path)
    assert cfg.repo_tab.folders == ("craft", "process")
    assert cfg.repo_tab.preview_max_bytes == 2048


def test_repo_tab_preview_max_bytes_must_be_positive(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "repo_tab:\n  preview_max_bytes: 0\n", encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="preview_max_bytes"):
        Config.load(tmp_path)


def test_yaml_parser_handles_comments_and_blanks():
    parsed = _parse_yaml(
        """
# top-level comment
target_words: 42
mattr_band: [0.70, 0.80]

characters:
  # nested comment
  - Nima
  - Mira
"""
    )
    assert parsed["target_words"] == 42
    assert parsed["mattr_band"] == [0.70, 0.80]
    assert parsed["characters"] == ["Nima", "Mira"]
