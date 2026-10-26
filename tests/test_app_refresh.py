"""Static regression tests for Proseview browser refresh behavior."""

from __future__ import annotations

from pathlib import Path

JS_DIR = Path(__file__).resolve().parents[1] / "proseview" / "templates" / "assets" / "js"


def _read_app_js() -> str:
    """Concatenate the topical JS files in the same order generator.py does."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js")))


class _AppJs:
    """Adapter so existing tests can keep using ``APP_JS.read_text(...)``."""
    @staticmethod
    def read_text(encoding: str = "utf-8") -> str:
        return _read_app_js()


APP_JS = _AppJs()


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
    assert "refreshContent(changedPaths || null)" in reload_body
    assert "_pendingSelfReloads" in reload_body

    # Partial-refresh plumbing remains in place.
    assert "var _refreshInFlight = false;" in source
    assert "var _refreshQueued = false;" in source
    assert "fetch('/scene-data?path=' + encodeURIComponent(scenePath)" in source
    assert "highlightsByPath[scenePath] = data.highlightsByPath[scenePath]" in source


def test_refresh_content_targets_active_view_only():
    source = APP_JS.read_text(encoding="utf-8")
    refresh_body = _function_body(source, "refreshContent")

    assert "refreshFilePreview({ silent: true" in refresh_body
    assert "fetch('/scene-data?path=' + encodeURIComponent(scenePath)" in refresh_body
    assert "pathListContains(changedPaths, filePath)" in refresh_body
    assert "pathListContains(changedPaths, scenePath)" in refresh_body
    assert "view !== 'scene'" in refresh_body
    assert "JSON.parse(e.data)" in source


def test_file_preview_refresh_can_run_silently():
    source = APP_JS.read_text(encoding="utf-8")
    body = _function_body(source, "refreshFilePreview")

    assert "options = options || {};" in body
    assert "!options.silent" in body
    assert "pathListContains(options.changedPaths, path)" in body


def test_file_list_change_refreshes_the_sidebar_in_place():
    """A file added, moved or deleted outside Proseview updates the file
    explorer without reloading the page or touching the open view."""
    source = APP_JS.read_text(encoding="utf-8")
    body = _strip_line_comments(_function_body(source, "refreshFileList"))

    assert "location.reload" not in body
    assert "_dashboardStale" not in body
    assert "renderSidebarTree()" in body
    assert "sidebarRememberExpanded({})" in body
    assert "history.replaceState" in body
    assert "refreshFileList(files)" in _function_body(source, "reloadOrDefer")


def test_file_editor_takes_a_change_on_disk_without_closing():
    """A note being edited stays in its editor when it changes on disk: with
    nothing unsaved it takes the new text, and unsaved work is left alone
    for the save's conflict check, with no prompt."""
    source = APP_JS.read_text(encoding="utf-8")
    preview = _strip_line_comments(_function_body(source, "refreshFilePreview"))
    assert "refreshFileEditor(path)" in preview
    assert preview.index("refreshFileEditor(path)") < preview.index("previewRepoFile(path")

    body = _strip_line_comments(_function_body(source, "refreshFileEditor"))
    assert "!fileEdit.dirty && !fileEdit.saving" in body
    assert "mountFileEditor(data.node, {quiet: true})" in body
    assert "location.reload" not in body
    assert "showUnsavedDialog" not in body
