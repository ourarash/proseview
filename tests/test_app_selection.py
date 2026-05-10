"""Static regression tests for Proseview scene selection behavior."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "proseview" / "templates" / "assets" / "app.js"


def test_scene_selection_is_preserved_across_terminal_clicks():
    source = APP_JS.read_text(encoding="utf-8")

    # The live Selection is cached so +sel can paste even after the user
    # clicks into the terminal and moves the OS-level selection.
    assert "let currentSelectionRange = null;" in source
    assert "function rememberSceneSelection(sel)" in source
    assert "currentSelectionRange = range.cloneRange();" in source
    assert "function restoreSceneSelection()" in source
    assert "sel.addRange(currentSelectionRange.cloneRange());" in source
    assert "e.target.closest('#terminalPanel')" in source
    # The terminal grabs the cached selection on mousedown, then keeps
    # the visual via pinSelectionHighlight (no restoreSceneSelection
    # call on mouseup, otherwise focus would jump back into the prose).
    assert "terminalPanel.addEventListener('mousedown'" in source
    assert "pinSelectionHighlight(currentSelectionRange)" in source
