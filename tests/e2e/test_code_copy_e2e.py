"""Browser tests for the copy icon on code blocks in agent replies.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page  # noqa: E402

from .conftest import ProseviewServer  # noqa: E402

pytestmark = pytest.mark.e2e_browser


def test_agent_code_block_copies_its_text(page: Page, server: ProseviewServer):
    """The icon copies the block's exact text; scene and file views get none."""
    page.goto(server.base_url, wait_until="load")
    page.evaluate(
        """() => {
            window.__copied = null;
            Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: {writeText: (text) => { window.__copied = text; return Promise.resolve(); }},
            });
            const host = document.createElement('div');
            host.id = '__codeHost';
            host.className = 'discuss-message';
            document.body.appendChild(host);
            renderDiscussMarkdown(host, 'Run:\\n\\n```sh\\nrm a.md b.md\\ngit add -A ch06\\n```\\n');
            const plain = document.createElement('div');
            renderSafeMarkdown(plain, '```\\nx\\n```');
            window.__plainButtons = plain.querySelectorAll('.md-copy-btn').length;
        }"""
    )
    button = page.locator("#__codeHost .md-copy-btn")
    assert button.count() == 1
    assert page.evaluate("window.__plainButtons") == 0

    # Hidden until the block is hovered.
    assert button.evaluate("b => getComputedStyle(b).opacity") == "0"
    page.locator("#__codeHost pre").hover()
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('#__codeHost .md-copy-btn')).opacity === '1'"
    )

    # It floats on the block's top edge, above the code rather than over it.
    button_box = button.bounding_box()
    pre_box = page.locator("#__codeHost pre").bounding_box()
    assert button_box["y"] + button_box["height"] / 2 <= pre_box["y"] + 2

    button.click()
    page.wait_for_function("() => window.__copied !== null")
    assert page.evaluate("window.__copied") == "rm a.md b.md\ngit add -A ch06"
    assert button.get_attribute("title") == "Copied"


def test_agent_blockquote_copies_its_plain_text(page: Page, server: ProseviewServer):
    """A quote copies its paragraphs without the '>' marks; file views get none."""
    page.goto(server.base_url, wait_until="load")
    page.evaluate(
        """() => {
            window.__copied = null;
            Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: {writeText: (text) => { window.__copied = text; return Promise.resolve(); }},
            });
            const host = document.createElement('div');
            host.id = '__quoteHost';
            host.className = 'discuss-message';
            document.body.appendChild(host);
            renderDiscussMarkdown(host, 'Try:\\n\\n> First line.\\n>\\n> Second para.\\n');
            const plain = document.createElement('div');
            renderSafeMarkdown(plain, '> x');
            window.__plainButtons = plain.querySelectorAll('.md-copy-btn').length;
        }"""
    )
    button = page.locator("#__quoteHost .md-copy-btn")
    assert button.count() == 1
    assert button.get_attribute("aria-label") == "Copy quote"
    assert page.evaluate("window.__plainButtons") == 0

    page.locator("#__quoteHost blockquote").hover()
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('#__quoteHost .md-copy-btn')).opacity === '1'"
    )
    button.click()
    page.wait_for_function("() => window.__copied !== null")
    copied = page.evaluate("window.__copied")
    assert copied.startswith("First line.") and copied.endswith("Second para.")
    assert "\n" in copied and ">" not in copied


def test_user_message_copies_the_text_sent(page: Page, server: ProseviewServer):
    """The writer's own bubble copies exactly what they sent, without the label."""
    page.goto(server.base_url, wait_until="load")
    sent = "Merge scenes 3 and 4.\n\nKeep `the ledger` line."
    page.evaluate(
        """sent => {
            window.__copied = null;
            Object.defineProperty(navigator, 'clipboard', {
                configurable: true,
                value: {writeText: (text) => { window.__copied = text; return Promise.resolve(); }},
            });
            _discussSnapshot = {connection: 'Live', tasks: [], notices: [], messages: [
                {role: 'user', text: sent},
                {role: 'assistant', text: 'Done.'},
            ]};
            renderDiscussSnapshot();
        }""",
        sent,
    )
    bubble = page.locator("#discussLog .discuss-message.user")
    assert bubble.locator("> .md-copy-btn").count() == 1
    assert page.locator("#discussLog .discuss-message.assistant .md-copy-btn").count() == 0
    bubble.locator("> .md-copy-btn").evaluate("b => b.click()")
    page.wait_for_function("() => window.__copied !== null")
    assert page.evaluate("window.__copied") == sent
