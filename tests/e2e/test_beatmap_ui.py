import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page
from .conftest import ProseviewServer, SCENE_REL
from .test_browser_e2e import open_scene

pytestmark = pytest.mark.e2e_browser


def test_beatmap_ui_improvements(page: Page, server: ProseviewServer, tmp_path: Path):
    open_scene(page, server, SCENE_REL)

    # 1. Verify Top Bar Heights: Sidebar header and Scene Toolbar
    sidebar_h = page.evaluate("document.querySelector('.sidebar-header').getBoundingClientRect().height")
    print(f"\nSidebar header height: {sidebar_h}px")
    assert abs(sidebar_h - 49.0) <= 0.5, f"Sidebar header is {sidebar_h}px, expected 49px"

    toolbar_h = page.evaluate("document.querySelector('#sceneModal .modal-header').getBoundingClientRect().height")
    print(f"Scene toolbar height: {toolbar_h}px")
    assert abs(toolbar_h - 49.0) <= 0.5, f"Toolbar header is {toolbar_h}px, expected 49px"

    # Open right panel dock
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_selector(".discuss-header")
    dock_h = page.evaluate("document.querySelector('.discuss-header').getBoundingClientRect().height")
    print(f"Discuss dock header height: {dock_h}px")
    assert abs(dock_h - 49.0) <= 0.5, f"Dock header is {dock_h}px, expected 49px"

    # 2. Switch to Beats tab and generate
    page.click("#utilityTabBeats")
    page.wait_for_selector(".beatmap-generate-btn")
    page.click(".beatmap-generate-btn")
    page.wait_for_selector(".sidebar-beat-group", timeout=10000)

    # 3. Test Collapse Button
    collapse_btns = page.query_selector_all(".beat-collapse-btn")
    assert len(collapse_btns) >= 3, f"Expected collapse buttons on beats, found {len(collapse_btns)}"

    # Moments visible initially for selected beat
    moments_before = len(page.query_selector_all(".sidebar-moment-card"))
    assert moments_before > 0, "Expected moments to be visible"

    # Click collapse button on active beat
    page.wait_for_timeout(300)
    page.evaluate("document.querySelector('.sidebar-beat-group.selected .beat-collapse-btn').click()")
    page.wait_for_timeout(200)

    # After collapse, 0 moments should be in the DOM
    moments_after = len(page.query_selector_all(".sidebar-moment-card"))
    print(f"Moments before: {moments_before}, after collapse: {moments_after}")
    assert moments_after == 0, f"Moments should be collapsed to 0, found {moments_after}"

    # Click expand again
    page.evaluate("document.querySelector('.sidebar-beat-group.selected .beat-collapse-btn').click()")
    page.wait_for_timeout(200)
    moments_reopened = len(page.query_selector_all(".sidebar-moment-card"))
    assert moments_reopened == moments_before, "Moments should be restored after expanding"

    # 4. Test clicking bottom moment does not reset scroll
    moments = page.query_selector_all(".sidebar-moment-card")
    page.evaluate("document.querySelector('#beatmapDockScroll').style.maxHeight = '120px'")
    page.evaluate("document.querySelector('#beatmapDockScroll').scrollTop = 40")
    scroll_before = page.evaluate("document.querySelector('#beatmapDockScroll').scrollTop")
    page.evaluate("document.querySelectorAll('.sidebar-moment-card')[document.querySelectorAll('.sidebar-moment-card').length - 1].click()")
    page.wait_for_timeout(200)
    scroll_after = page.evaluate("document.querySelector('#beatmapDockScroll').scrollTop")
    print(f"Scroll before click: {scroll_before}, after click: {scroll_after}")
    assert scroll_after > 0, f"Scroll was reset to {scroll_after}"

    # 5. Toggle Horizontal Top Strip
    page.click("#paneToggleStripBtn")
    page.wait_for_timeout(300)

    strip_pos = page.evaluate("window.getComputedStyle(document.querySelector('#sceneBeatMapStripContainer')).position")
    strip_top = page.evaluate("window.getComputedStyle(document.querySelector('#sceneBeatMapStripContainer')).top")
    print(f"Horizontal strip position: {strip_pos}, top: {strip_top}")
    assert strip_pos == "sticky", f"Horizontal strip should be sticky, got {strip_pos}"
    assert strip_top == "49px", f"Horizontal strip top should be 49px, got {strip_top}"

    # Verify right dock is NOT empty while horizontal strip is visible
    dock_beats = len(page.query_selector_all(".sidebar-beat-group"))
    print(f"Dock beat groups visible simultaneously: {dock_beats}")
    assert dock_beats >= 3, "Right dock should keep beats populated while horizontal strip is open"

    # Click on beat 2 card in horizontal overview
    beat_cards = page.query_selector_all(".beat-nav-card")
    assert len(beat_cards) >= 3
    beat_cards[1].click()
    page.wait_for_timeout(200)

    # Verify that all beat cards are STILL visible (not hidden/zoomed)!
    cards_still_visible = len(page.query_selector_all(".beat-nav-card"))
    print(f"Beat cards visible after clicking beat 2: {cards_still_visible}")
    assert cards_still_visible == len(beat_cards), "Beat cards should stay visible in overview when beat is clicked"

    # Test closing horizontal strip via close button
    page.click("#stripCloseBtn")
    page.wait_for_timeout(200)
    strip_hidden = page.evaluate("document.querySelector('#sceneBeatMapStripContainer').hidden")
    assert strip_hidden is True, "Horizontal strip should be hidden after clicking close button"

    # 6. Verify Dynamic Peak Beat Caption (Bug 8 fix)
    peak_text = page.evaluate("document.querySelector('.beatmap-dock-header ~ * .tension-curve-header > span:last-child').textContent")
    print(f"Dock peak caption: {peak_text}")
    assert "Peak: Beat 2" in peak_text, f"Expected Peak: Beat 2, found {peak_text}"

    # 7. Verify XSS Protection for Moment Types (Bug 1 fix)
    # Inject a beatmap with an XSS moment type via window.updateBeatMapState
    page.evaluate("""
        window._xssRan = false;
        window.updateBeatMapState({
            beatmap: {
                scene_path: 'ch01/01-opening.md',
                analyzed_revision_hash: 'testhash',
                beats: [{
                    order: 1,
                    title: 'XSS Test Beat',
                    summary: 'Test',
                    estimated_tension: 60,
                    is_turning_point: false,
                    moments: [{
                        order: 1,
                        type: '"><script>window._xssRan=true<\\/script><b id="injected">',
                        text: 'Safe text',
                        source_ref: { paragraph: 0, exact_quote: '', valid_anchor: false }
                    }]
                }]
            }
        });
    """)
    page.wait_for_timeout(200)
    xss_ran = page.evaluate("window._xssRan")
    injected_el = page.query_selector("#injected")
    assert xss_ran is False, "XSS script executed through moment type!"
    assert injected_el is None, "HTML was injected into DOM through moment type!"

    # 8. Verify Unresolved Reference / Invalid Anchor Handling (Bug 7 fix)
    # Show horizontal strip with the invalid anchor beatmap
    page.click("#paneToggleStripBtn")
    page.wait_for_timeout(200)
    jump_btn_disabled = page.evaluate("document.getElementById('btnJumpToMoment').disabled")
    jump_btn_text = page.evaluate("document.getElementById('btnJumpToMoment').textContent")
    print(f"Jump button with invalid anchor: disabled={jump_btn_disabled}, text={jump_btn_text}")
    assert jump_btn_disabled is True, "Jump button should be disabled for unresolved reference"
    assert "Unresolved" in jump_btn_text

    # 9. Verify 8-beat single row horizontal scrolling (no 2-row wrap)
    page.evaluate("""
        var beats8 = [];
        for (var i = 1; i <= 8; i++) {
            beats8.push({
                order: i,
                title: 'Beat ' + i + ' long narrative description',
                summary: 'Summary for beat ' + i,
                estimated_tension: 30 + i * 5,
                is_turning_point: (i === 6),
                moments: [{ order: i, type: 'action', text: 'Action in beat ' + i, source_ref: { paragraph: 0, valid_anchor: true } }]
            });
        }
        window.updateBeatMapState({
            beatmap: {
                scene_path: 'ch01/01-opening.md',
                analyzed_revision_hash: 'testhash',
                beats: beats8
            }
        });
    """)
    page.wait_for_timeout(200)

    # Verify all 8 cards are in a single horizontal row (same offsetTop)
    card_tops = page.evaluate("""
        Array.from(document.querySelectorAll('.beat-cards-overview .beat-nav-card')).map(function(c) {
            return c.offsetTop;
        });
    """)
    print(f"8-beat card vertical offsets (should all be equal): {card_tops}")
    assert len(card_tops) == 8, f"Expected 8 beat cards, found {len(card_tops)}"
    assert len(set(card_tops)) == 1, f"Cards wrapped into multiple rows! Offsets: {card_tops}"

    # 10. Verify Double-Click opens moments zoom view
    page.dblclick(".beat-cards-overview .beat-nav-card[data-beat-order='2']")
    page.wait_for_timeout(200)
    is_zoomed = page.evaluate("document.querySelector('.beat-moments-zoom') !== null")
    print(f"Moments view open after double click: {is_zoomed}")
    assert is_zoomed is True, "Double click should open the moments view"

    # 11. Verify Escape key closes moments zoom view
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    is_zoomed_after_esc = page.evaluate("document.querySelector('.beat-moments-zoom') !== null")
    overview_visible = page.evaluate("document.querySelector('.beat-cards-overview') !== null")
    print(f"Moments view open after Escape: {is_zoomed_after_esc}, overview visible: {overview_visible}")
    assert is_zoomed_after_esc is False, "Escape key should close moments view"
    assert overview_visible is True, "Overview should be restored after Escape"

    # 12. Verify Dramatic Tension Tooltip & Rubric
    tension_btn = page.query_selector(".tension-info-btn")
    assert tension_btn is not None, "Dramatic tension info button should exist"
    page.hover(".tension-info-btn")
    page.wait_for_timeout(200)
    page.screenshot(path=tmp_path / "tension_tooltip_verified.png")
    popover_title = page.evaluate("document.querySelector('.tension-tooltip-title').textContent")
    popover_text = page.evaluate("document.querySelector('.tension-rubric-grid').textContent")
    print(f"Tension tooltip title: {popover_title}")
    assert "Dramatic Tension (0–100)" in popover_title
    assert "0–25" in popover_text and "76–100" in popover_text
    assert "Low" in popover_text and "Crisis" in popover_text
    page.mouse.move(0, 0)
    page.wait_for_timeout(200)

    # 13. Verify Beat Order Injection Protection (Bug 1)
    page.evaluate("""
        window._xssRan2 = false;
        window.updateBeatMapState({
            beatmap: {
                scene_path: 'ch01/01-opening.md',
                analyzed_revision_hash: 'testhash',
                beats: [{
                    order: '1"><script>window._xssRan2=true<\\/script><b id="injected2">',
                    title: 'Injected Beat',
                    summary: 'Test',
                    estimated_tension: 50,
                    moments: []
                }]
            }
        });
    """)
    page.wait_for_timeout(200)
    assert page.evaluate("window._xssRan2") is False, "XSS executed through beat.order!"
    assert page.query_selector("#injected2") is None, "HTML injected through beat.order!"

    # 14. Verify Colorful Tension Curve, Pacing Bar & Beat Dots
    page.evaluate("""
        var beats5 = [
            { order: 1, title: 'Beat 1', summary: 'S1', estimated_tension: 25, moments: [{ order: 1, type: 'action', text: 'T1', source_ref: { paragraph: 0, valid_anchor: true } }] },
            { order: 2, title: 'Beat 2', summary: 'S2', estimated_tension: 45, moments: [{ order: 2, type: 'action', text: 'T2', source_ref: { paragraph: 1, valid_anchor: true } }] },
            { order: 3, title: 'Beat 3', summary: 'S3', estimated_tension: 55, moments: [{ order: 3, type: 'action', text: 'T3', source_ref: { paragraph: 2, valid_anchor: true } }] },
            { order: 4, title: 'Beat 4', summary: 'S4', estimated_tension: 85, is_turning_point: true, moments: [{ order: 4, type: 'action', text: 'T4', source_ref: { paragraph: 3, valid_anchor: true } }] },
            { order: 5, title: 'Beat 5', summary: 'S5', estimated_tension: 40, moments: [{ order: 5, type: 'action', text: 'T5', source_ref: { paragraph: 4, valid_anchor: true } }] }
        ];
        window.updateBeatMapState({
            beatmap: {
                scene_path: 'ch01/01-opening.md',
                analyzed_revision_hash: 'testhash_colors',
                beats: beats5
            }
        });
    """)
    page.wait_for_timeout(200)

    # Verify SVG contains linearGradient with multi-color stops
    grad_stops = page.evaluate("""
        Array.from(document.querySelectorAll('#sceneBeatMapStripContainer svg linearGradient stop')).map(function(s) {
            return s.getAttribute('stop-color');
        });
    """)
    print(f"Gradient stops colors: {grad_stops}")
    assert "#34d399" in grad_stops, f"Expected #34d399 in gradient stops, got {grad_stops}"
    assert "#fbbf24" in grad_stops, f"Expected #fbbf24 in gradient stops, got {grad_stops}"
    assert "#38bdf8" in grad_stops, f"Expected #38bdf8 in gradient stops, got {grad_stops}"
    assert "#f87171" in grad_stops, f"Expected #f87171 in gradient stops, got {grad_stops}"
    assert "#c084fc" in grad_stops, f"Expected #c084fc in gradient stops, got {grad_stops}"

    # Verify Pacing Bar Segments
    segments = page.query_selector_all("#sceneBeatMapStripContainer .pacing-segment")
    assert len(segments) == 5, f"Expected 5 pacing segments, found {len(segments)}"

    segment_colors = page.evaluate("""
        Array.from(document.querySelectorAll('#sceneBeatMapStripContainer .pacing-segment')).map(function(el) {
            return el.style.background;
        });
    """)
    print(f"Pacing bar segment colors: {segment_colors}")
    assert any("52, 211, 153" in c or "#34d399" in c for c in segment_colors), "Beat 1 mint segment missing"
    assert any("251, 191, 36" in c or "#fbbf24" in c for c in segment_colors), "Beat 2 gold segment missing"
    assert any("56, 189, 248" in c or "#38bdf8" in c for c in segment_colors), "Beat 3 sky blue segment missing"
    assert any("248, 113, 113" in c or "#f87171" in c for c in segment_colors), "Beat 4 coral segment missing"
    assert any("192, 132, 252" in c or "#c084fc" in c for c in segment_colors), "Beat 5 purple segment missing"

    # Verify clicking pacing segment 3 selects beat 3
    segments[2].click()
    page.wait_for_timeout(200)
    selected_beat = page.evaluate("document.querySelector('#sceneBeatMapStripContainer .beat-nav-card.selected').getAttribute('data-beat-order')")
    print(f"Selected beat after clicking pacing segment 3: {selected_beat}")
    assert selected_beat == "3", f"Expected beat 3 selected, got {selected_beat}"

    # Verify beat color dots in beat cards
    dots = page.query_selector_all("#sceneBeatMapStripContainer .beat-color-dot")
    assert len(dots) >= 5, f"Expected at least 5 beat color dots, found {len(dots)}"

    # Capture verified screenshot of the colorful tension curve and pacing bar
    page.screenshot(path=tmp_path / "colorful_tension_curve_verified.png")

    # 15. Verify Right Panel Alignment between Curve Nodes and Pacing Segments
    alignment_diffs = page.evaluate("""
        var diffs = [];
        for (var b = 1; b <= 5; b++) {
            var node = document.querySelector('#sceneBeatMapPane .curve-node[data-beat-order="' + b + '"]');
            var seg = document.querySelector('#sceneBeatMapPane .pacing-segment[data-beat-order="' + b + '"]');
            if (node && seg) {
                var nodeRect = node.getBoundingClientRect();
                var segRect = seg.getBoundingClientRect();
                var nodeCenter = nodeRect.left + nodeRect.width / 2;
                var segCenter = segRect.left + segRect.width / 2;
                diffs.push({ beat: b, diff: Math.abs(nodeCenter - segCenter) });
            }
        }
        diffs;
    """)
    print(f"Dock curve node to pacing segment horizontal center diffs: {alignment_diffs}")
    assert len(alignment_diffs) == 5, f"Expected 5 aligned pairs, got {alignment_diffs}"
    for item in alignment_diffs:
        assert item["diff"] <= 2.0, f"Beat {item['beat']} misaligned: {item['diff']}px diff"

    # 16. Verify Calm Active Dot Styling (no fluorescent white glow, calm radius)
    active_node_w = page.evaluate("document.querySelector('#sceneBeatMapPane .curve-node.active-node').getBoundingClientRect().width")
    active_node_filter = page.evaluate("window.getComputedStyle(document.querySelector('#sceneBeatMapPane .curve-node.active-node')).filter")
    print(f"Active node width: {active_node_w}px, filter: {active_node_filter}")
    assert active_node_w <= 9.0, f"Active node is too large: {active_node_w}px"
    assert active_node_filter == "none", f"Active node has distracting filter: {active_node_filter}"

    # 17. Verify Tooltip on Dot Hover
    node2 = page.query_selector("#sceneBeatMapPane .curve-node[data-beat-order='2']")
    assert node2 is not None
    node2.hover()
    page.wait_for_timeout(200)

    tip_visible = page.evaluate("document.querySelector('#sceneBeatMapPane .tension-dot-tooltip.visible') !== null")
    tip_text = page.evaluate("document.querySelector('#sceneBeatMapPane .tension-dot-tooltip').textContent")
    print(f"Dot tooltip visible: {tip_visible}, content: {tip_text}")
    assert tip_visible is True, "Dot tooltip should be visible on hover"
    assert "Beat 2" in tip_text, f"Expected Beat 2 in tooltip, got: {tip_text}"
    assert "45 / 100" in tip_text, f"Expected tension 45/100 in tooltip, got: {tip_text}"
    assert "Moderate" in tip_text, f"Expected Moderate rubric in tooltip, got: {tip_text}"

    # Take screenshot of tooltip and aligned calm tension curve
    page.screenshot(path=tmp_path / "calm_aligned_tension_verified.png")

    # 18. Verify Calm Delete Beat Map UI
    delete_btn = page.query_selector("#paneDeleteContainer .beatmap-delete-btn")
    assert delete_btn is not None, "Delete button should be present in dock toolbar"
    delete_btn.click()
    page.wait_for_timeout(200)

    # Verify calm inline confirmation is displayed
    confirm_wrap = page.query_selector("#paneDeleteContainer .beatmap-delete-confirm-wrap")
    assert confirm_wrap is not None, "Inline confirmation should appear when delete button is clicked"
    confirm_text = page.evaluate("document.querySelector('#paneDeleteContainer .beatmap-delete-confirm-wrap').textContent")
    assert "Delete map?" in confirm_text
    assert "Cancel" in confirm_text
    assert "Delete" in confirm_text

    # Take screenshot of calm delete confirmation
    page.screenshot(path=tmp_path / "calm_delete_confirm_verified.png")

    # Test Cancel returns calmly to delete icon
    cancel_btn = page.query_selector("#paneDeleteContainer .beatmap-delete-cancel-btn")
    assert cancel_btn is not None
    cancel_btn.click()
    page.wait_for_timeout(200)
    assert page.query_selector("#paneDeleteContainer .beatmap-delete-confirm-wrap") is None
    assert page.query_selector("#paneDeleteContainer .beatmap-delete-btn") is not None

    # Click delete again and confirm
    page.click("#paneDeleteContainer .beatmap-delete-btn")
    page.wait_for_timeout(200)
    page.click("#paneDeleteContainer .beatmap-delete-confirm-btn")
    page.wait_for_selector(".beatmap-generate-btn", timeout=5000)

    # Verify both right dock and horizontal strip transitioned to empty state
    empty_gen_btn = page.query_selector(".beatmap-generate-btn")
    assert empty_gen_btn is not None, "UI should smoothly return to empty state after deletion"

    print("\nALL VERIFICATIONS PASSED!")


def test_beatmap_settings_modal_ui(page: Page, server: ProseviewServer, tmp_path: Path):
    open_scene(page, server, SCENE_REL)

    # Open Settings and select Beat Map tab
    page.evaluate("openBeatMapSettings()")
    page.wait_for_selector("#settingsPanelBeatmap:not([hidden])")
    page.wait_for_selector("#beatmapSettingsBody .suggestion-prompt", timeout=5000)

    # Verify presence of key UI elements
    tab_btn = page.query_selector("#settingsTabBeatmap")
    assert tab_btn is not None
    assert tab_btn.get_attribute("aria-selected") == "true"

    labels = page.evaluate("""
        Array.from(document.querySelectorAll('#beatmapSettingsBody .settings-label')).map(el => el.textContent.trim())
    """)
    assert "Default Agent" in labels
    assert "Model" in labels
    assert "Target Pacing" in labels
    assert "Project Instructions" in labels
    assert "Narrative Structure Prompt" in labels
    assert "Dramatic Tension Rubric" in labels

    # Check reset buttons initial state (disabled because defaults match)
    reset_btn_first = page.locator("#beatmapSettingsBody .suggestion-prompt button").first
    assert reset_btn_first.is_disabled() is True

    # Type into the prompt textarea
    prompt_area = page.locator("#beatmapSettingsBody textarea").first
    prompt_area.fill("Custom Author Instructions for Beat Extraction: Focus on micro-expressions.")

    # Reset button should now be enabled
    page.wait_for_timeout(100)
    assert reset_btn_first.is_disabled() is False

    # Clicking Reset to default should restore default prompt and disable reset button
    reset_btn_first.click()
    page.wait_for_timeout(100)
    assert reset_btn_first.is_disabled() is True
    reverted_val = prompt_area.input_value()
    assert "Divide this scene into chronological narrative beats" in reverted_val

    # Take screenshot of the Beat Map settings UI
    page.screenshot(path=tmp_path / "beatmap_settings_modal_verified.png")

    # Test editing and saving persists via Save changes button
    prompt_area.fill("Custom Author Instructions: ensure climax is mapped.")
    save_btn = page.locator("#settingsSaveBtn")
    assert save_btn.is_enabled() is True
    save_btn.click()
    page.wait_for_selector("#settingsSaveBtn:has-text('Saved')", timeout=5000)

    # Check settings reloaded from server reflect the custom prompt
    res = server.get_json("/api/discuss/beatmap-settings")
    assert res["settings"]["book"]["prompt"] == "Custom Author Instructions: ensure climax is mapped."
