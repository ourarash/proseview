"""Browser tests for the privacy screen: hold Cmd (Ctrl) and tap J twice.

The spreadsheet covers the page without touching it, so an unsaved edit, its
caret and scroll come back exactly as they were. With a password set, the
server checks it and keeps a reload covered.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page  # noqa: E402

from .conftest import ProseviewServer  # noqa: E402
from .test_browser_e2e import append_to_paragraph, enter_edit_mode, open_scene  # noqa: E402

pytestmark = pytest.mark.e2e_browser

COVERED = "() => document.getElementById('privacyScreen').open"
UNCOVERED = "() => !document.getElementById('privacyScreen').open"


def _mod(page: Page) -> str:
    return "Meta" if page.evaluate("PRIVACY_MAC") else "Control"


def _double_tap_held(page: Page) -> None:
    """Cmd held down throughout, J tapped twice."""
    mod = _mod(page)
    page.keyboard.down(mod)
    page.keyboard.press("j")
    page.keyboard.press("j")
    page.keyboard.up(mod)


def _double_tap_repressed(page: Page) -> None:
    """Cmd+J, let go, Cmd+J again."""
    mod = _mod(page)
    page.keyboard.press(f"{mod}+j")
    page.keyboard.press(f"{mod}+j")


def _caret(page: Page) -> dict:
    return page.evaluate(
        """() => {
            const sel = window.getSelection();
            return {
                node: sel.anchorNode && sel.anchorNode.textContent,
                offset: sel.anchorOffset,
                active: document.activeElement && document.activeElement.className,
                scroll: document.querySelector('#sceneModal .modal-content').scrollTop,
            };
        }"""
    )


def _set_password(server: ProseviewServer, password: str | None) -> None:
    code = (
        "from proseview.privacy import set_password, clear_password;"
        + (f"set_password({password!r})" if password else "clear_password()")
    )
    subprocess.run([sys.executable, "-c", code], env=server.env, check=True)


def _reset(server: ProseviewServer) -> None:
    """No password and nothing covered: the flag outlives the server."""
    code = (
        "from proseview.privacy import clear_password, covered_path;"
        "clear_password(); covered_path().unlink(missing_ok=True)"
    )
    subprocess.run([sys.executable, "-c", code], env=server.env, check=True)


@pytest.fixture(autouse=True)
def _clean_privacy(server: ProseviewServer):
    # The test home is shared, so a test that fails while covered must not
    # leave every later page covered.
    _reset(server)
    yield
    _reset(server)


def test_cover_keeps_an_unsaved_edit_caret_and_scroll(page: Page, server: ProseviewServer):
    open_scene(page, server)
    enter_edit_mode(page)
    append_to_paragraph(page, "The loft smelled", " UNSAVED-WORDS")
    page.wait_for_function("() => window._pmDirty === true")
    before = _caret(page)
    title = page.title()

    # One Cmd+J alone does nothing, not even type a j.
    page.keyboard.press(f"{_mod(page)}+j")
    page.wait_for_timeout(600)
    assert page.evaluate(UNCOVERED)
    # Holding Cmd+J down auto-repeats; that is not a double tap.
    mod = _mod(page)
    page.keyboard.down(mod)
    page.keyboard.down("j")
    page.keyboard.down("j")
    page.keyboard.up("j")
    page.keyboard.up(mod)
    page.wait_for_timeout(600)
    assert page.evaluate(UNCOVERED)

    _double_tap_held(page)
    page.wait_for_function(COVERED)
    assert page.title() == "Budget"
    assert "svg" in page.evaluate("document.querySelector('link[rel=icon]').href")
    assert page.locator("#privacyScreen").is_visible()
    assert page.locator(".privacy-grid td", has_text="Groceries").is_visible()
    # Esc, Tab, typing and clicks reach nothing behind it.
    page.keyboard.press("Escape")
    page.keyboard.press("Tab")
    page.keyboard.type("xyz")
    page.mouse.click(300, 300)
    assert page.evaluate(COVERED)
    assert page.evaluate("document.getElementById('privacyScreen').contains(document.activeElement)")
    assert page.evaluate("window._pmEditMode") is True

    page.wait_for_timeout(600)
    _double_tap_repressed(page)
    page.wait_for_function(UNCOVERED)
    assert page.title() == title
    assert page.evaluate("window._pmEditMode") is True
    assert page.evaluate("window._pmDirty") is True
    assert _caret(page) == before
    host = page.locator("#sceneProseHost .ProseMirror")
    assert "UNSAVED-WORDS" in host.inner_text()
    assert "xyz" not in host.inner_text()
    # Typing carries on at the caret.
    page.keyboard.type("+MORE")
    assert "UNSAVED-WORDS+MORE" in host.inner_text()


def test_a_reload_stays_covered_without_a_password(page: Page, server: ProseviewServer):
    open_scene(page, server)
    with page.expect_response("**/api/privacy/lock"):
        _double_tap_held(page)
    page.wait_for_function(COVERED)

    page.reload(wait_until="load")
    assert page.evaluate("document.documentElement.dataset.privacy") == "locked"
    page.wait_for_function(COVERED)
    assert page.title() == "Budget"
    assert not page.locator("#sceneProseHost").is_visible()

    # A new tab opens covered too.
    other = page.context.new_page()
    other.goto(server.base_url, wait_until="load")
    other.wait_for_function(COVERED)
    assert other.title() == "Budget"

    # No password: the shortcut uncovers at once, and every tab follows.
    with page.expect_response("**/api/privacy/unlock"):
        _double_tap_held(page)
    page.wait_for_function(UNCOVERED)
    assert page.locator("#privacyPassword").is_hidden()
    other.wait_for_function(UNCOVERED)
    other.close()

    page.reload(wait_until="load")
    page.wait_for_selector("#sceneProseHost .ProseMirror", state="visible")
    assert page.evaluate(UNCOVERED)


def test_password_keeps_a_reload_covered_until_given(page: Page, server: ProseviewServer):
    _set_password(server, "letmein")
    try:
        open_scene(page, server)
        with page.expect_response("**/api/privacy/lock"):
            _double_tap_held(page)
        page.wait_for_function(COVERED)

        page.reload(wait_until="load")
        assert page.evaluate("document.documentElement.dataset.privacy") == "locked"
        page.wait_for_function(COVERED)
        assert page.title() == "Budget"
        assert not page.locator("#sceneProseHost").is_visible()

        # A wrong password puts the box away and the sheet stays.
        _double_tap_held(page)
        box = page.locator("#privacyPassword")
        box.wait_for(state="visible")
        box.type("nope")
        with page.expect_response("**/api/privacy/unlock"):
            page.keyboard.press("Enter")
        box.wait_for(state="hidden")
        assert page.evaluate(COVERED)

        page.wait_for_timeout(600)
        _double_tap_repressed(page)
        box.wait_for(state="visible")
        box.type("letmein")
        page.keyboard.press("Enter")
        page.wait_for_function(UNCOVERED)
        page.wait_for_selector("#sceneProseHost .ProseMirror", state="visible")
        assert page.title() != "Budget"

        page.reload(wait_until="load")
        page.wait_for_selector("#sceneProseHost .ProseMirror", state="visible")
        assert page.evaluate(UNCOVERED)
    finally:
        _set_password(server, None)


def test_cover_goes_over_an_open_dialog_and_leaves_esc_to_it(page: Page, server: ProseviewServer):
    page.goto(server.base_url, wait_until="load")
    page.evaluate("openSettings()")
    page.wait_for_function("() => document.querySelector('dialog.settings-dialog[open]') !== null")

    _double_tap_held(page)
    page.wait_for_function(COVERED)
    assert page.evaluate("document.activeElement.closest('#privacyScreen') !== null")
    page.keyboard.press("Escape")
    assert page.evaluate("document.querySelector('dialog.settings-dialog[open]') !== null")

    page.wait_for_timeout(600)
    _double_tap_held(page)
    page.wait_for_function(UNCOVERED)
    # The dialog is as it was, and a single Esc still closes it.
    assert page.evaluate("document.querySelector('dialog.settings-dialog').contains(document.activeElement)")
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.querySelector('dialog.settings-dialog[open]') === null")


def test_settings_sets_changes_and_removes_the_password(page: Page, server: ProseviewServer):
    _set_password(server, None)
    try:
        page.goto(server.base_url, wait_until="load")
        page.evaluate("openSettings()")
        row = page.locator("#privacySettingsRow")
        row.wait_for(state="visible")
        status = page.locator("#privacyPasswordStatus")
        assert status.inner_text() == "Password: none"

        # Set: typed twice, and a mismatch is caught before anything is sent.
        page.click("#privacySetBtn")
        assert page.locator("#privacyCurrent").is_hidden()
        page.fill("#privacyNew", "first")
        page.fill("#privacyNewAgain", "frist")
        page.click("#privacyFormSubmit")
        assert page.locator("#privacyPasswordMsg").inner_text() == "The two do not match"
        page.fill("#privacyNewAgain", "first")
        with page.expect_response("**/api/privacy/password"):
            page.click("#privacyFormSubmit")
        page.wait_for_function("() => document.getElementById('privacyPasswordStatus').textContent === 'Password set'")
        assert page.locator("#privacyPasswordForm").is_hidden()
        assert page.locator("#privacySetBtn").is_hidden()

        # Change needs the current one.
        page.click("#privacyChangeBtn")
        page.fill("#privacyCurrent", "wrong")
        page.fill("#privacyNew", "second")
        page.fill("#privacyNewAgain", "second")
        page.click("#privacyFormSubmit")
        page.wait_for_function("() => document.getElementById('privacyPasswordMsg').textContent === 'Wrong password'")
        page.fill("#privacyCurrent", "first")
        page.keyboard.press("Enter")
        page.wait_for_selector("#privacyPasswordForm", state="hidden")

        # The new password is the one the privacy screen asks for.
        page.evaluate("closeSettings()")
        with page.expect_response("**/api/privacy/lock"):
            _double_tap_held(page)
        page.wait_for_timeout(600)
        _double_tap_held(page)
        box = page.locator("#privacyPassword")
        box.wait_for(state="visible")
        box.type("second")
        page.keyboard.press("Enter")
        page.wait_for_function(UNCOVERED)

        # Remove asks only for the current one.
        page.evaluate("openSettings()")
        page.click("#privacyRemoveBtn")
        assert page.locator("#privacyNew").is_hidden()
        page.fill("#privacyCurrent", "second")
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.getElementById('privacyPasswordStatus').textContent === 'Password: none'")
    finally:
        _set_password(server, None)
