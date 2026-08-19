import pytest

# The default pytest run installs only ".[dev]", which has no playwright.
# Without this the module fails to import and takes the whole run with it.
pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page  # noqa: E402

from .conftest import ProseviewServer  # noqa: E402
from .test_browser_e2e import (  # noqa: E402
    _wait_until,
    append_to_paragraph,
    enter_edit_mode,
    open_scene,
    save_scene,
)

def _create_history_backup(page: Page, server: ProseviewServer):
    path = server.scene_path()
    open_scene(page, server)
    enter_edit_mode(page)
    append_to_paragraph(page, "The loft smelled of cold coffee", " A new sentence for history.")
    with page.expect_response("**/save-scene*"):
        save_scene(page)
    _wait_until(lambda: "A new sentence for history." in path.read_text(encoding="utf-8"))

def _open_history_tab(page: Page):
    page.evaluate("() => showScenePanelTab('history')")
    page.wait_for_selector("#sceneHistoryPane:not([hidden])")
    page.wait_for_selector("#historyListContent .history-item", state="visible")

def test_diff_modal_escape_key_closes_modal_only(page: Page, server: ProseviewServer):
    _create_history_backup(page, server)
    _open_history_tab(page)
    
    page.wait_for_timeout(100)
    page.evaluate("document.querySelector('#historyListContent').innerHTML")
    page.evaluate("document.querySelector('#historyListContent .history-item').click()")
    page.wait_for_selector("#diffModalOverlay:not([hidden])")
    
    page.keyboard.press("Escape")
    page.wait_for_selector("#diffModalOverlay", state="hidden")
    
    assert page.locator("#utilityTabHistory").evaluate("el => el.classList.contains('active')")

def test_diff_modal_restore_button_restores_file(page: Page, server: ProseviewServer):
    path = server.scene_path()
    original_text = path.read_text(encoding="utf-8")
    
    _create_history_backup(page, server)
    _open_history_tab(page)
    
    page.wait_for_timeout(100)
    page.evaluate("document.querySelector('#historyListContent .history-item').click()")
    page.wait_for_selector("#diffModalOverlay:not([hidden])")
    
    with page.expect_response("**/api/scene/history/restore"):
        page.locator("#diffModalRestoreBtn").click()
        
    page.wait_for_selector("#diffModalOverlay", state="hidden")
    
    _wait_until(lambda: path.read_text(encoding="utf-8") == original_text)

def test_diff_modal_preview_direction(page: Page, server: ProseviewServer):
    _create_history_backup(page, server)
    _open_history_tab(page)
    
    page.wait_for_timeout(100)
    page.evaluate("document.querySelector('#historyListContent .history-item').click()")
    page.wait_for_selector("#diffModalOverlay:not([hidden])")
    
    # Wait for the diff to load (the loading text will disappear)
    page.wait_for_function("() => !document.getElementById('diffModalContent').innerText.includes('Loading diff...')")
    
    # We added " A new sentence for history." to the current file.
    # The past version does NOT have it.
    # Restoring the past version will DELETE it.
    # Therefore, it should be marked as deleted (.diff_sub) in the diff preview.
    sub_text = page.locator(".diff_sub").inner_text()
    assert "A new sentence for history." in sub_text, "Expected the newly added text to be marked for deletion (red) when previewing a past version."
