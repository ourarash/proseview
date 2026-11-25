from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from proseview.beatmap import generate_scene_beatmap  # noqa: E402
from .conftest import ProseviewServer, SCENE_REL  # noqa: E402
from .test_browser_e2e import open_discuss, open_scene, wait_for_discuss_answer  # noqa: E402

pytestmark = pytest.mark.e2e_browser


def test_prompt_context_popover_and_dedup_e2e(page: Page, server: ProseviewServer):
    # Pre-generate a beat map so it shows up with a real KB size in the popover.
    generate_scene_beatmap(server.root, SCENE_REL)

    requests = []
    page.on(
        "request",
        lambda req: requests.append(req.post_data_json)
        if "/api/discuss/conversations/" in req.url and req.url.endswith("/questions")
        else None,
    )

    open_scene(page, server, SCENE_REL)
    open_discuss(page)
    page.wait_for_function("() => document.querySelector('#discussConnection').innerText.startsWith('Live')")

    # Resting state: quiet filename trigger with no +N badge, popover hidden.
    trigger = page.locator("#discussPromptContextTrigger")
    expect(trigger).to_be_visible()
    expect(trigger).to_contain_text(SCENE_REL)
    expect(trigger.locator(".discuss-sees-badge")).to_have_count(0)
    picker = page.locator("#discussPromptContextPicker")
    expect(picker).to_be_hidden()

    # Click trigger to open upward Prompt Context popover.
    trigger.click()
    expect(picker).to_be_visible()
    expect(trigger).to_have_attribute("aria-expanded", "true")

    # Popover sits cleanly above the composer row without overflowing horizontally.
    box = picker.bounding_box()
    composer_box = page.locator("#discussComposerArea").bounding_box()
    panel_box = page.locator("#discussPanel").bounding_box()
    assert box is not None and composer_box is not None and panel_box is not None
    assert box["y"] + box["height"] <= composer_box["y"] + 2
    assert box["x"] >= panel_box["x"] - 1
    assert box["x"] + box["width"] <= panel_box["x"] + panel_box["width"] + 1

    # All 4 switches start OFF (beat map off by default) and show token estimates.
    beatmap_row = picker.locator('[data-context-key="beatmap"]')
    full_scene_row = picker.locator('[data-context-key="full_scene"]')
    expect(beatmap_row).to_have_attribute("aria-checked", "false")
    expect(beatmap_row).to_contain_text("tok")
    expect(full_scene_row).to_have_attribute("aria-checked", "false")

    # Turn 1 (lean default): sends beatmap=false.
    page.keyboard.press("Escape")
    expect(picker).to_be_hidden()

    page.fill("#discussInput", "Tighten the opening line.")
    page.click("#discussSend")
    wait_for_discuss_answer(page, "Fake answer")
    assert len(requests) == 1
    assert requests[0]["prompt_context"] == {
        "beatmap": False,
        "full_scene": False,
        "frontmatter": False,
        "adjacent": False,
    }

    # Per-message quiet token chips appear on both user & assistant messages and open a breakdown popover.
    user_chip = page.locator("#discussLog .discuss-message.user .discuss-usage-chip").first
    asst_chip = page.locator("#discussLog .discuss-message.assistant .discuss-usage-chip").first
    expect(user_chip).to_be_visible()
    expect(user_chip).to_contain_text("tok")
    expect(asst_chip).to_be_visible()
    expect(asst_chip).to_contain_text("tok")

    user_chip.click()
    usage_pop = page.locator("#discussUsagePopover")
    expect(usage_pop).to_be_visible()
    expect(usage_pop).to_contain_text("Total prompt")
    page.keyboard.press("Escape")
    expect(usage_pop).to_be_hidden()

    asst_chip.click()
    expect(usage_pop).to_be_visible()
    expect(usage_pop).to_contain_text("Output")
    page.keyboard.press("Escape")
    expect(usage_pop).to_be_hidden()

    # Open popover, toggle Scene beat map ON -> +1 badge appears on trigger.
    trigger.click()
    expect(picker).to_be_visible()
    beatmap_row.click()
    expect(beatmap_row).to_have_attribute("aria-checked", "true")
    expect(trigger.locator(".discuss-sees-badge")).to_have_text("+1")

    # Turn 2: sends beatmap=true, closes popover automatically.
    page.fill("#discussInput", "Check pacing against the beat map.")
    page.click("#discussSend")
    expect(picker).to_be_hidden()
    wait_for_discuss_answer(page, "Fake answer")
    assert len(requests) == 2
    assert requests[1]["prompt_context"]["beatmap"] is True

    # Reopen popover -> Scene beat map now shows "In thread ✓".
    trigger.click()
    expect(picker).to_be_visible()
    expect(beatmap_row).to_contain_text("In thread ✓")

    # Reset to lean turns everything off and removes +1 badge.
    page.click("#discussPromptContextResetLean")
    expect(beatmap_row).to_have_attribute("aria-checked", "false")
    expect(trigger.locator(".discuss-sees-badge")).to_have_count(0)
