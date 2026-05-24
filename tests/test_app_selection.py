"""Static regression tests for Proseview scene selection behavior."""

from __future__ import annotations

from pathlib import Path

JS_DIR = Path(__file__).resolve().parents[1] / "proseview" / "templates" / "assets" / "js"


def _read_app_js() -> str:
    """Concatenate the topical JS files in the same order generator.py does."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js")))


class _AppJs:
    @staticmethod
    def read_text(encoding: str = "utf-8") -> str:
        return _read_app_js()


APP_JS = _AppJs()


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


def test_ai_proposal_bridge_keeps_apply_in_browser_editor():
    source = APP_JS.read_text(encoding="utf-8")

    assert "function buildAiProposalPlugin(PM)" in source
    assert "function handleAiProposalEvent(payload)" in source
    assert "function aiMaybeRefocusActiveProposal(scenePath)" in source
    assert "aiMaybeRefocusActiveProposal(p)" in source
    assert "function aiResolveQuoteRange(map, quote)" in source
    assert "proposal.resolved_quote || proposal.quote" in source
    assert source.index("var quoteRange = aiResolveQuoteRange") < source.index("if (proposal.range")
    assert "status: 'failed'" in source
    assert "error: range.error" in source
    assert "proposal.status === 'failed'" in source
    assert "Use current selection" in source
    assert "Accept selected" in source
    assert "ORIGINAL" in source
    assert "ISSUE" in source
    assert "function aiLineLabel(proposal, range)" in source
    assert "function aiTopLevelRange(range)" in source
    assert "function aiClearNativeSelection()" in source
    assert "function aiForceClearProposalHighlightDom()" in source
    assert "function aiScrollRangeIntoView(range)" in source
    assert "clearSceneSelectionMemory" in source
    assert "clearPinnedSelectionHighlight" in source
    assert "data-ai-proposal" in source
    assert "background-color: rgba(14, 165, 233, 0.38)" in source
    assert "function aiApplyProposal(proposal, optionIndex)" in source
    assert "var applyRange = {from: _aiProposalRange.from, to: _aiProposalRange.to}" in source
    assert "new PM.MarkdownParser" in source
    assert "parsed.firstChild.content" in source
    assert "var blockRange = aiTopLevelRange" in source
    assert "parsed.content" in source
    assert "PM.TextSelection.create(tr.doc, safeSelectionPos, safeSelectionPos)" in source
    assert "PM.TextSelection.near" in source
    assert "tr.setMeta(_aiProposalPluginKey, PM.DecorationSet.empty)" in source
    assert "aiForceClearProposalHighlightDom();" in source
    assert "setTimeout(aiClearNativeSelection, 0)" in source
    assert "setTimeout(aiClearNativeSelection, 80)" in source
    assert "setPmDirty(true)" in source
    assert ".setSelection(window._PM.TextSelection.create" not in source
    assert "Refine in terminal" in source
    assert "/ai/proposals/" in source
    assert "proseview-ai-client-id" in source
    # After the apply, the browser PATCHes status='accepted' which the server
    # broadcasts back as an 'updated' SSE event. handleAiProposalEvent must
    # treat 'accepted' as terminal and clear the proposal locally, otherwise
    # the just-applied proposal is re-focused against a doc that no longer
    # contains the original quote and the fallback highlight lands at stale
    # coordinates.
    assert "proposal.status === 'skipped' || proposal.status === 'accepted'" in source
