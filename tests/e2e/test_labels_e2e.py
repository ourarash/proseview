"""Browser tests for calm Markdown scene labels and color coding.

Opt-in, like the rest of the browser tier: ``pytest -m e2e_browser``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Page, expect  # noqa: E402

from .conftest import (  # noqa: E402
    REPO_ROOT,
    ProseviewServer,
    _close_open_pages,
    _start_server,
    _stop_server,
)

pytestmark = pytest.mark.e2e_browser

DEMO = REPO_ROOT / "fixtures" / "demo-book"
SCENE_A = "ch01/01-down-the-rabbit-hole.md"
SCENE_B = "ch01/02-down-down-down.md"


@pytest.fixture
def labels_server(tmp_path: Path, agent_bin: Path, fake_home: Path) -> Iterator[ProseviewServer]:
    root = tmp_path / "alice"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("exports", ".proseview"))
    with (root / ".proseview.yaml").open("a", encoding="utf-8") as cfg:
        cfg.write(
            "\nlabels:\n"
            "  palette:\n"
            "    Main Plot: c0\n"
            "    Subplot B: c2\n"
        )
    a_path = root / "manuscript" / SCENE_A
    a_text = a_path.read_text(encoding="utf-8")
    if a_text.startswith("---\n"):
        a_path.write_text(
            a_text.replace("---\n", "---\n# Keep comment\nlabel: Main Plot\n", 1),
            encoding="utf-8",
        )
    else:
        a_path.write_text("---\n# Keep comment\nlabel: Main Plot\n---\n\n" + a_text, encoding="utf-8")

    # Add a bare scene with no frontmatter at all
    bare_path = root / "manuscript" / "ch01" / "09-bare.md"
    bare_path.write_text("# Bare Scene\n\nNo frontmatter here yet.\n", encoding="utf-8")

    server = _start_server(root, agent_bin, fake_home)
    try:
        yield server
    finally:
        _close_open_pages()
        _stop_server(server)


def test_sidebar_overview_book_and_appearance_label_modes(page: Page, labels_server: ProseviewServer):
    page.goto(labels_server.url("/"), wait_until="load")
    page.evaluate("() => setSidebarOpen(true)")

    # Sidebar: labeled scene icon gets --label-color, unlabeled does not.
    sidebar_a = page.locator(f'#sidebarTree .file-link[data-scene-path="{SCENE_A}"]')
    sidebar_b = page.locator(f'#sidebarTree .file-link[data-scene-path="{SCENE_B}"]')
    expect(sidebar_a).to_have_attribute("data-label-color", "1")
    expect(sidebar_a).to_have_attribute("data-label", "Main Plot")
    assert sidebar_b.get_attribute("data-label-color") is None

    # Overview Table: shows dot + pill, filter isolates labeled or unlabeled scenes.
    row_a = page.locator(f'#sceneTable tr.scene-row[data-label="Main Plot"]')
    expect(row_a.locator(".table-label-dot")).to_be_visible()
    expect(row_a.locator(".label-pill")).to_have_text("Main Plot")

    page.select_option("#issueFilter", "label:Main Plot")
    expect(row_a).to_be_visible()
    expect(page.locator('#sceneTable tr.scene-row[data-label=""]:visible')).to_have_count(0)

    # Cards view: 3px left border accent + pill in footer.
    page.click("#sceneViewCardsBtn")
    card_a = page.locator(f'.scene-overview-card[data-scene-path="{SCENE_A}"]')
    expect(card_a).to_have_attribute("data-label-color", "1")
    expect(card_a).to_be_visible()
    expect(card_a.locator(".label-pill")).to_have_text("Main Plot")
    border_left = card_a.evaluate("el => getComputedStyle(el).borderLeftWidth")
    assert border_left == "3px"

    # Appearance setting: Subtle -> Soft sidebar rows -> Off (persists across reload)
    page.click("#settingsOpenBtn")
    page.click("#settingsTabAppearance")
    expect(page.locator("#setting_label_mode")).to_have_value("subtle")
    page.select_option("#setting_label_mode", "rows")
    expect(page.locator("html")).to_have_attribute("data-label-mode", "rows")
    row_bg = sidebar_a.evaluate("el => getComputedStyle(el).backgroundColor")
    assert row_bg != "rgba(0, 0, 0, 0)"

    page.select_option("#setting_label_mode", "off")
    expect(page.locator("html")).to_have_attribute("data-label-mode", "off")
    expect(card_a.locator(".label-pill")).to_be_hidden()
    expect(row_a.locator(".table-label-dot")).to_be_hidden()

    page.reload(wait_until="load")
    expect(page.locator("html")).to_have_attribute("data-label-mode", "off")

    # Restore subtle mode and verify Read the book scene dot updates live when recolored.
    page.click("#settingsOpenBtn")
    page.click("#settingsTabAppearance")
    page.select_option("#setting_label_mode", "subtle")
    page.keyboard.press("Escape")
    page.click("#bookOpenBtn")
    book_a = page.locator(f'.book-scene[data-path="{SCENE_A}"]')
    expect(book_a.locator(".book-label-dot")).to_be_attached()
    expect(book_a.locator(".book-label-dot")).to_be_visible()
    page.evaluate("() => openAppearanceSettings()")
    page.locator(
        '#settingsLabelPaletteList .settings-label-palette-item[data-label-name="Main Plot"] '
        'button.label-color-swatch[title="Red"]'
    ).click()
    expect(book_a.locator(".book-label-dot")).to_have_attribute("style", "--label-color: var(--story-c7);")


def test_reading_mode_label_dropdown_writes_yaml_and_hides_in_edit_mode(
    page: Page, labels_server: ProseviewServer,
):
    page.goto(labels_server.url(f"/#/scene/{SCENE_A.replace('/', '%2F')}"), wait_until="load")
    page.wait_for_function("() => !!window._PM")

    # Dropdown appears in reading mode with pill CSS and current label + inline YAML dot.
    picker_btn = page.locator("#sceneFrontmatter .scene-label-picker-btn")
    expect(picker_btn).to_be_visible()
    expect(picker_btn).to_contain_text("Main Plot")
    expect(page.locator("#sceneFrontmatter .fm-label-dot")).to_be_visible()
    btn_style = picker_btn.evaluate(
        "el => ({ fs: parseFloat(getComputedStyle(el).fontSize), r: parseFloat(getComputedStyle(el).borderRadius) })"
    )
    assert btn_style["fs"] <= 12.0
    assert btn_style["r"] >= 100.0

    # Verify a saved non-default theme persists across reload alongside scene label scripts.
    page.evaluate("() => selectTheme('graphite-dark')")
    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")
    expect(page.locator("html")).to_have_attribute("data-theme", "graphite-dark")
    picker_btn = page.locator("#sceneFrontmatter .scene-label-picker-btn")

    # Manual frontmatter edit with trailing YAML comment parses cleanly without leaking the comment into the label.
    page.click("#sceneEditBtn")
    expect(picker_btn).to_be_hidden()
    fm_editor = page.locator("#sceneFrontmatter textarea.fm-editor")
    expect(fm_editor).to_be_visible()
    fm_editor.fill(fm_editor.input_value().replace("label: Main Plot", "label: Main Plot # inline note"))
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("() => !window._pmEditMode")
    expect(page.locator("#sceneFrontmatter .scene-label-picker-btn")).to_have_text("Main Plot▾")
    expect(page.locator("#sceneFrontmatter .fm-label-link")).to_have_text("Main Plot")

    # Switch label to configured "Subplot B" via the inline frontmatter label link -> writes YAML cleanly.
    page.locator("#sceneFrontmatter .fm-label-link").click()
    page.locator('#sceneFrontmatter .fm-label-wrap .scene-label-item', has_text="Subplot B").click()
    expect(page.locator("#sceneFrontmatter .scene-label-picker-btn")).to_contain_text("Subplot B")
    expect(page.locator("#sceneFrontmatter .fm-label-link")).to_contain_text("Subplot B")

    disk_a = (labels_server.root / "manuscript" / SCENE_A).read_text(encoding="utf-8")
    assert "# Keep comment" in disk_a
    assert "label: Subplot B" in disk_a
    assert "label: Main Plot" not in disk_a

    # Switch back using the header pill dropdown too.
    page.locator("#sceneFrontmatter .scene-label-picker-btn").click()
    page.locator('#sceneFrontmatter .scene-label-picker .scene-label-item', has_text="Main Plot").click()
    expect(page.locator("#sceneFrontmatter .fm-label-link")).to_contain_text("Main Plot")
    page.locator("#sceneFrontmatter .scene-label-picker-btn").click()
    page.locator('#sceneFrontmatter .scene-label-picker .scene-label-item', has_text="Subplot B").click()
    expect(page.locator("#sceneFrontmatter .scene-label-picker-btn")).to_contain_text("Subplot B")

    # Add a brand new label on the bare scene (with no prior frontmatter).
    page.goto(labels_server.url("/#/scene/ch01%2F09-bare.md"), wait_until="load")
    page.wait_for_function("() => !!window._PM")
    bare_btn = page.locator("#sceneFrontmatter .scene-label-picker-btn")
    expect(bare_btn).to_contain_text("+ Label")
    bare_btn.click()
    page.locator('.scene-label-popover .scene-label-item', has_text="+ New").click()
    page.fill(".scene-label-new-input", "Flashback")
    page.click(".scene-label-new-submit")
    try:
        expect(page.locator("#sceneFrontmatter .scene-label-picker-btn")).to_contain_text("Flashback")
    except AssertionError as exc:
        # Fails on Linux CI only; say what the page and the file held.
        state = page.evaluate("""() => ({
            toast: document.getElementById('sidebarFileToast')?.textContent,
            label: (meta['ch01/09-bare.md'] || {}).label,
            open: paths[curIdx], view: document.documentElement.dataset.view,
        })""")
        on_disk = (labels_server.root / "manuscript" / "ch01" / "09-bare.md").read_text(encoding="utf-8")
        raise AssertionError(f"{exc}\npage: {state}\nfile: {on_disk!r}") from None

    disk_bare = (labels_server.root / "manuscript" / "ch01" / "09-bare.md").read_text(encoding="utf-8")
    assert disk_bare.startswith("---\nlabel: Flashback\n---\n")
    assert "# Bare Scene" in disk_bare

    # Clear the label back off the bare scene -> removes frontmatter block cleanly,
    # while keeping the newly created label saved in .proseview.yaml and available in the picker.
    page.locator("#sceneFrontmatter .scene-label-picker-btn").click()
    page.locator('.scene-label-popover .scene-label-item.is-clear').click()
    expect(page.locator("#sceneFrontmatter .scene-label-picker-btn")).to_contain_text("+ Label")
    disk_bare_after = (labels_server.root / "manuscript" / "ch01" / "09-bare.md").read_text(encoding="utf-8")
    assert disk_bare_after.startswith("# Bare Scene")
    assert "Flashback:" in (labels_server.root / ".proseview.yaml").read_text(encoding="utf-8")

    page.locator("#sceneFrontmatter .scene-label-picker-btn").click()
    expect(page.locator('.scene-label-popover .scene-label-item', has_text="Flashback")).to_be_visible()
    page.reload(wait_until="load")
    page.wait_for_function("() => !!window._PM")
    page.locator("#sceneFrontmatter .scene-label-picker-btn").click()
    expect(page.locator('.scene-label-popover .scene-label-item', has_text="Flashback")).to_be_visible()


def test_timeline_color_by_chapter_or_label_toggle(page: Page, labels_server: ProseviewServer):
    page.goto(labels_server.url("/"), wait_until="load")
    page.click('button[data-tab="timeline"]')

    chapter_btn = page.locator('.story-color-btn', has_text="Color by: Chapter")
    label_btn = page.locator('.story-color-btn', has_text="Label")
    expect(chapter_btn).to_have_attribute("aria-pressed", "true")
    expect(label_btn).to_have_attribute("aria-pressed", "false")

    first_seg = page.locator(".story-strip .story-seg").first
    second_seg = page.locator(".story-strip .story-seg").nth(1)
    # In chapter mode both ch01 scenes share chapter color; in label mode unlabeled scene turns neutral border.
    assert first_seg.evaluate("el => el.style.background") == second_seg.evaluate("el => el.style.background")

    label_btn.click()
    expect(page.locator('.story-color-btn', has_text="Label")).to_have_attribute("aria-pressed", "true")
    assert first_seg.evaluate("el => el.style.background") != second_seg.evaluate("el => el.style.background")


def test_sidebar_context_menu_label_picker_and_custom_color_picker(
    page: Page, labels_server: ProseviewServer,
):
    page.goto(labels_server.url("/"), wait_until="load")
    page.evaluate("() => setSidebarOpen(true)")

    # Expand ch01 and right-click an unlabeled scene in the file explorer to open its context menu.
    page.locator('#sidebarTree .dir-toggle[data-path="manuscript/ch01"]').click()
    sidebar_b = page.locator(f'#sidebarTree .file-link[data-scene-path="{SCENE_B}"]')
    sidebar_b.click(button="right")

    label_trigger = page.locator('#sidebarContextMenu .sidebar-context-label-trigger')
    expect(label_trigger).to_be_visible()
    label_trigger.click()

    # Assign "Subplot B" directly from the sidebar right-click menu.
    page.locator('#sidebarContextMenu .scene-label-item', has_text="Subplot B").click()
    expect(sidebar_b).to_have_attribute("data-label", "Subplot B")
    expect(sidebar_b).to_have_attribute("data-label-color", "1")

    disk_b = (labels_server.root / "manuscript" / SCENE_B).read_text(encoding="utf-8")
    assert "label: Subplot B" in disk_b

    # Open Settings -> Appearance -> Labels via "Manage labels..." from the context label menu.
    sidebar_b.click(button="right")
    page.locator('#sidebarContextMenu .sidebar-context-label-trigger').click()
    page.locator('#sidebarContextMenu .scene-label-item.is-manage').click()
    expect(page.locator("#settingsTabAppearance")).to_have_attribute("aria-selected", "true")
    palette_row = page.locator("#settingsLabelPaletteRow")
    expect(palette_row).to_be_visible()

    main_item = page.locator("#settingsLabelPaletteList .settings-label-palette-item", has_text="Main Plot")
    color_well = main_item.locator("input.label-color-well")
    color_well.fill("#4f7cac")
    color_well.dispatch_event("change")

    sidebar_a = page.locator(f'#sidebarTree .file-link[data-scene-path="{SCENE_A}"]')
    expect(sidebar_a).to_have_attribute("style", "--label-color: #4f7cac;")

    yaml_text = (labels_server.root / ".proseview.yaml").read_text(encoding="utf-8")
    assert "#4f7cac" in yaml_text

    # Reload and verify the custom hex color persists across page reloads.
    page.reload(wait_until="load")
    page.evaluate("() => setSidebarOpen(true)")
    expect(page.locator(f'#sidebarTree .file-link[data-scene-path="{SCENE_A}"]')).to_have_attribute(
        "style", "--label-color: #4f7cac;"
    )


def test_settings_label_add_rename_and_remove_syncs_disk_and_ui(
    page: Page, labels_server: ProseviewServer,
):
    page.goto(labels_server.url("/"), wait_until="load")
    page.evaluate("() => setSidebarOpen(true)")
    page.locator('#sidebarTree .dir-toggle[data-path="manuscript/ch01"]').click()

    page.click("#settingsOpenBtn")
    page.click("#settingsTabAppearance")
    palette_row = page.locator("#settingsLabelPaletteRow")
    expect(palette_row).to_be_visible()

    # 1. Add a new label from Settings -> Labels.
    add_form = page.locator("#settingsLabelPaletteList form.settings-label-add-form")
    add_form.locator("input.settings-label-add-input").fill("Flashback")
    add_form.locator('button[type="submit"]').click()

    flashback_item = page.locator('#settingsLabelPaletteList .settings-label-palette-item[data-label-name="Flashback"]')
    expect(flashback_item).to_be_visible()
    assert "Flashback:" in (labels_server.root / ".proseview.yaml").read_text(encoding="utf-8")

    # 2. Rename "Main Plot" -> "Hero Arc" and verify both .proseview.yaml and SCENE_A on disk + sidebar update.
    main_item = page.locator('#settingsLabelPaletteList .settings-label-palette-item[data-label-name="Main Plot"]')
    main_item.locator(".settings-label-action-btn", has_text="Rename").click()
    rename_form = page.locator("#settingsLabelPaletteList form.settings-label-rename-form")
    rename_form.locator("input.settings-label-rename-input").fill("Hero Arc")
    rename_form.locator('button[type="submit"]').click()

    hero_item = page.locator('#settingsLabelPaletteList .settings-label-palette-item[data-label-name="Hero Arc"]')
    expect(hero_item).to_be_visible()
    expect(hero_item.locator(".settings-label-palette-color")).to_have_text("Blue")
    expect(main_item).to_have_count(0)

    sidebar_a = page.locator(f'#sidebarTree .file-link[data-scene-path="{SCENE_A}"]')
    expect(sidebar_a).to_have_attribute("data-label", "Hero Arc")
    assert "label: Hero Arc" in (labels_server.root / "manuscript" / SCENE_A).read_text(encoding="utf-8")
    yaml_after_rename = (labels_server.root / ".proseview.yaml").read_text(encoding="utf-8")
    assert "Hero Arc: blue" in yaml_after_rename
    assert "Main Plot:" not in yaml_after_rename

    # Clicking a named swatch writes the human color name (not c0..c7) to .proseview.yaml.
    flashback_item.locator('button.label-color-swatch[title="Red"]').click()
    expect(flashback_item.locator(".settings-label-palette-color")).to_have_text("Red")
    assert "Flashback: red" in (labels_server.root / ".proseview.yaml").read_text(encoding="utf-8")

    # 3. Remove "Hero Arc" -> asks for confirmation because 1 scene uses it, then clears scene + config.
    hero_item.locator(".settings-label-action-btn", has_text="Remove").click()
    confirm_btn = hero_item.locator(".settings-label-action-btn", has_text="Confirm remove")
    expect(confirm_btn).to_be_visible()
    confirm_btn.click()

    expect(hero_item).to_have_count(0)
    expect(sidebar_a).not_to_have_attribute("data-label", "Hero Arc")
    assert "label:" not in (labels_server.root / "manuscript" / SCENE_A).read_text(encoding="utf-8")
    assert "Hero Arc:" not in (labels_server.root / ".proseview.yaml").read_text(encoding="utf-8")

    # Reload and verify Flashback stays and Hero Arc remains removed.
    page.reload(wait_until="load")
    page.click("#settingsOpenBtn")
    page.click("#settingsTabAppearance")
    expect(
        page.locator('#settingsLabelPaletteList .settings-label-palette-item[data-label-name="Flashback"]')
    ).to_be_visible()
    expect(
        page.locator('#settingsLabelPaletteList .settings-label-palette-item[data-label-name="Hero Arc"]')
    ).to_have_count(0)


def test_label_picker_yaml_update_keeps_other_list_items(page: Page, labels_server: ProseviewServer):
    page.goto(labels_server.url(f"/#/scene/{SCENE_A.replace('/', '%2F')}"), wait_until="load")
    page.wait_for_function("() => typeof updateYamlScalarField === 'function'")
    results = page.evaluate("""() => [
        updateYamlScalarField('label: [draft, "pov, Mara"]\\ntitle: X', 'label', 'revised'),
        updateYamlScalarField('label:\\n- draft\\n- pov\\ntitle: X', 'label', 'revised'),
        updateYamlScalarField('label:\\n  - draft\\n  - pov', 'label', ''),
        updateYamlScalarField('label: [draft]', 'label', ''),
        updateYamlScalarField('# c\\nlabel: draft\\nx: 1', 'label', 'Next'),
    ]""")
    assert results == [
        'label: [revised, "pov, Mara"]\ntitle: X',
        "label:\n- revised\n- pov\ntitle: X",
        "label:\n  - pov",
        "",
        "# c\nlabel: Next\nx: 1",
    ]
