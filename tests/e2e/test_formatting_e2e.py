import pytest
from playwright.sync_api import Page
from .conftest import open_scene

@pytest.mark.e2e_browser
def test_editor_list_and_quote_formatting(page: Page, server):
    open_scene(page, server, "intro.md")
    page.wait_for_selector(".ProseMirror")
    
    page.click(".ProseMirror")
    page.keyboard.type("List item")
    page.keyboard.press("Shift+ArrowLeft")
    page.keyboard.press("Shift+ArrowLeft")
    
    page.click("#sceneToolbarReveal", force=True)
    
    page.click("button[aria-label='Bullet List']")
    has_list = page.evaluate("() => { const pm = document.querySelector('.ProseMirror').pmView; let found = false; pm.state.doc.descendants(node => { if (node.type.name === 'bullet_list') found = true; }); return found; }")
    assert has_list, "Bullet list was not created"
