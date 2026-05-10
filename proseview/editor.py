"""Editor URL builder.

Turns a ``Config`` plus an absolute scene path (optionally a line number)
into a ``scheme://...`` URL the browser can hand off to the user's editor.

Four built-in schemes share the ``scheme://file/{path}[:line]`` shape that
the VS Code family (VS Code, Cursor, Positron) and Zed all accept. The
``custom`` scheme interpolates a user-supplied template with ``{abs_path}``
and ``{line}`` placeholders. Unknown schemes are rejected at config-load
time, so ``build_url`` trusts its input and asserts rather than guards.

The generator calls this once per row in the scene table, and once per
modal navigation on the client. Path handling matters:
    - spaces and other unreserved chars survive via ``urllib.parse.quote``
    - a leading ``/`` on POSIX is preserved
    - the line suffix is omitted when ``line`` is ``None`` or ``1`` so the
      URL stays stable across most navigation (editors open at line 1 by
      default when no anchor is present)
"""

from __future__ import annotations

from urllib.parse import quote

from .config import Config

BUILTIN_TEMPLATES: dict[str, str] = {
    "vscode": "vscode://file/{abs_path}",
    "cursor": "cursor://file/{abs_path}",
    "zed": "zed://file/{abs_path}",
    "positron": "positron://file/{abs_path}",
}

BUILTIN_LABELS: dict[str, str] = {
    "vscode": "VS Code",
    "cursor": "Cursor",
    "zed": "Zed",
    "positron": "Positron",
    "custom": "Editor",
}


def build_url(cfg: Config, abs_path: str, line: int | None = None) -> str:
    """Return the editor URL for ``abs_path`` under ``cfg.editor``.

    For built-in schemes, ``line`` is appended as ``:{line}`` when greater
    than 1. The ``custom`` scheme always interpolates both placeholders,
    defaulting line to 1, to keep user templates single-shaped.
    """
    scheme = cfg.editor.scheme
    line_val = line if line and line > 0 else 1

    if scheme == "custom":
        assert cfg.editor.url_template, \
            "custom editor requires url_template (validated in Config.load)"
        return cfg.editor.url_template.format(abs_path=abs_path, line=line_val)

    template = BUILTIN_TEMPLATES[scheme]
    url = template.format(abs_path=quote(abs_path, safe="/"))
    if line_val > 1:
        url = f"{url}:{line_val}"
    return url


def label(cfg: Config) -> str:
    return BUILTIN_LABELS.get(cfg.editor.scheme, "Editor")
