"""Static regression tests for Proseview browser refresh behavior."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "proseview" / "templates" / "assets" / "app.js"


def _function_body(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for idx in range(brace, len(source)):
        if source[idx] == "{":
            depth += 1
        elif source[idx] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:idx]
    raise AssertionError(f"Could not find body for {name}")


def _strip_line_comments(body: str) -> str:
    out: list[str] = []
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def test_reload_or_defer_uses_partial_refresh():
    source = APP_JS.read_text(encoding="utf-8")
    reload_body = _strip_line_comments(_function_body(source, "reloadOrDefer"))

    # reloadOrDefer must never trigger a full page reload directly --
    # that would jolt the viewport and tear down the live editor.
    assert "location.reload()" not in reload_body
    assert "refreshContent()" in reload_body
    assert "_pendingSelfReloads" in reload_body

    # Partial-refresh plumbing remains in place.
    assert "var _refreshInFlight = false;" in source
    assert "var _refreshQueued = false;" in source
    assert "fetch('/data.json')" in source
    assert "if (data.highlightsByPath) highlightsByPath = data.highlightsByPath;" in source
