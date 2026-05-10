"""Tests for :mod:`proseview.editor`.

M3 contract:
    - every built-in scheme emits ``scheme://file/{abs_path}[:line]``
    - ``line <= 1`` omits the suffix
    - ``custom`` interpolates both placeholders and defaults line to 1
    - unknown schemes are rejected at config load (covered in test_config)
    - a ``custom`` scheme without ``url_template`` fails config load
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from proseview.config import Config, ConfigError, EditorConfig  # noqa: E402
from proseview.editor import build_url, label  # noqa: E402


def _cfg(scheme: str, url_template: str | None = None) -> Config:
    return Config(editor=EditorConfig(scheme=scheme, url_template=url_template))


@pytest.mark.parametrize("scheme,prefix", [
    ("vscode", "vscode://file/"),
    ("cursor", "cursor://file/"),
    ("zed", "zed://file/"),
    ("positron", "positron://file/"),
])
def test_builtin_schemes_render_file_urls(scheme: str, prefix: str):
    url = build_url(_cfg(scheme), "/Users/ari/book/manuscript/ch01/01.md")
    assert url == f"{prefix}/Users/ari/book/manuscript/ch01/01.md"


def test_builtin_urls_encode_spaces_but_preserve_slashes():
    url = build_url(_cfg("vscode"), "/home/me/my book/ch01/scene one.md")
    assert url == "vscode://file//home/me/my%20book/ch01/scene%20one.md"


def test_line_suffix_appended_for_builtin_when_greater_than_one():
    url = build_url(_cfg("zed"), "/a/b/c.md", line=42)
    assert url == "zed://file//a/b/c.md:42"


def test_line_suffix_omitted_for_line_none_or_one():
    assert build_url(_cfg("vscode"), "/a.md") == "vscode://file//a.md"
    assert build_url(_cfg("vscode"), "/a.md", line=1) == "vscode://file//a.md"
    assert build_url(_cfg("vscode"), "/a.md", line=0) == "vscode://file//a.md"


def test_custom_template_always_interpolates_both_placeholders():
    cfg = _cfg("custom", "myed://open?path={abs_path}&line={line}")
    assert build_url(cfg, "/a/b.md") == "myed://open?path=/a/b.md&line=1"
    assert build_url(cfg, "/a/b.md", line=17) == "myed://open?path=/a/b.md&line=17"


def test_custom_without_template_raises_in_config_load(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "editor:\n  scheme: custom\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(tmp_path)


def test_unknown_scheme_raises_in_config_load(tmp_path: Path):
    (tmp_path / ".proseview.yaml").write_text(
        "editor:\n  scheme: bogus\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Config.load(tmp_path)


def test_label_returns_human_name_for_each_scheme():
    assert label(_cfg("vscode")) == "VS Code"
    assert label(_cfg("cursor")) == "Cursor"
    assert label(_cfg("zed")) == "Zed"
    assert label(_cfg("positron")) == "Positron"
    assert label(_cfg("custom", "x://{abs_path}")) == "Editor"
