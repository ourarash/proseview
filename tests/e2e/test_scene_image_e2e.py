"""End-to-end browser tests for Scene Image generation, preview, chat cards, and inline editor."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="pip install -e '.[e2e]'")

from playwright.sync_api import Browser, Page  # noqa: E402

from proseview.scene_image import (  # noqa: E402
    save_chat_generated_image,
    save_scene_image_preview,
)

pytestmark = pytest.mark.e2e_browser

_SAMPLE_JPG = (
    Path(__file__).resolve().parents[2]
    / "proseview"
    / "templates"
    / "assets"
    / "scene-styles"
    / "ink_watercolor.jpg"
)
_SAMPLE_JPG_2 = (
    Path(__file__).resolve().parents[2]
    / "proseview"
    / "templates"
    / "assets"
    / "scene-styles"
    / "woodcut.jpg"
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_server(root: Path) -> tuple[subprocess.Popen[str], str]:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "proseview", "serve", "--root", str(root), "--port", str(port), "--no-open"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}/"
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(f"proseview exited early: {proc.stdout.read() if proc.stdout else ''}")
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return proc, url
        except Exception:
            time.sleep(0.15)
    proc.terminate()
    raise RuntimeError("proseview server did not become ready")


def _seed_book(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "proseview.yaml").write_text(
        "title: Scene Image E2E\nauthor: Test Author\nmanuscript: manuscript\n",
        encoding="utf-8",
    )
    ch = tmp_path / "manuscript" / "ch01"
    ch.mkdir(parents=True)
    scene = ch / "01-opening.md"
    scene.write_text(
        "---\ntitle: Opening at the Bar\nstatus: draft\n---\n\n"
        "The room smelled of rain and cedar.\n\n"
        "Nima looked up from his glass.\n",
        encoding="utf-8",
    )
    return tmp_path, scene


def test_scene_image_preview_switcher_insert_and_inline_editor(browser: Browser, tmp_path: Path) -> None:
    root, scene = _seed_book(tmp_path)
    rel = "ch01/01-opening.md"
    sample1 = _SAMPLE_JPG.read_bytes()
    sample2 = _SAMPLE_JPG_2.read_bytes()

    # Seed two preview takes (as produced by Codex or Agy)
    save_scene_image_preview(
        root, rel, sample1, ".jpg", "image/jpeg",
        agent="codex", style_id="ink_watercolor", style_name="Ink & Watercolor",
        alt="Amber bar at dusk",
    )
    save_scene_image_preview(
        root, rel, sample2, ".jpg", "image/jpeg",
        agent="agy", style_id="woodcut", style_name="Woodcut & Engraving",
        alt="Monochrome woodcut bar",
    )
    chat_meta = save_chat_generated_image(
        root, sample2, ".jpg", "image/jpeg",
        agent="agy", scene_path=rel, alt="Monochrome woodcut bar",
    )

    proc, url = _start_server(root)
    errors: list[str] = []
    try:
        page: Page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(8000)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        page.goto(url + f"#/scene/{rel}", wait_until="load")
        page.wait_for_selector(".scene-image-preview-card", state="visible")

        # 1. Preview host aligns with the reading column (never stretches full-bleed)
        widths = page.evaluate("""() => {
            const fm = document.getElementById('sceneFrontmatter').getBoundingClientRect();
            const si = document.getElementById('sceneImageHost').getBoundingClientRect();
            return {fmLeft: Math.round(fm.left), siLeft: Math.round(si.left), fmWidth: Math.round(fm.width), siWidth: Math.round(si.width)};
        }""")
        assert widths["siLeft"] == widths["fmLeft"]
        assert widths["siWidth"] == widths["fmWidth"]

        # 2. Take switcher cycles 2 / 2 -> 1 / 2
        assert page.locator(".scene-image-take-count").inner_text().strip() == "2 / 2"
        page.locator("#sceneImagePrevTake").click()
        page.wait_for_function("() => document.querySelector('.scene-image-take-count')?.textContent?.trim() === '1 / 2'")

        # 3. Discuss chat card renderer displays a real loaded image + actions
        card_ok = page.evaluate("""(payload) => {
            const host = document.createElement('div');
            document.body.appendChild(host);
            window.renderDiscussSceneImageCard(JSON.stringify(payload), host);
            const img = host.querySelector('img.discuss-scene-image-thumb');
            const btns = Array.from(host.querySelectorAll('button')).map(b => b.textContent.trim());
            const src = img ? img.getAttribute('src') : '';
            host.remove();
            return {src, btns};
        }""", chat_meta)
        assert card_ok["src"] == chat_meta["url"]
        assert "Use as preview" in card_ok["btns"] and "Insert into scene" in card_ok["btns"]

        # 4. Insert Take 1 -> saves under chapter assets/ as HTML <img width="600">
        page.locator("#sceneImageInsertBtn").click()
        page.wait_for_selector("#sceneProseHost .pm-scene-image", state="visible")
        saved_md = scene.read_text(encoding="utf-8")
        assert '<img src="/repo-asset/manuscript/ch01/assets/01-opening.jpg" alt="Amber bar at dusk" width="600">' in saved_md
        assert (root / "manuscript" / "ch01" / "assets" / "01-opening.jpg").is_file()

        # 5. Hover Edit -> opens calm IMAGE editor (never yellow NOTE), updates width to 500, toggles </> HTML
        page.locator("#sceneProseHost .pm-scene-image").hover()
        page.locator(".pm-scene-image-action", has_text="Edit").click()
        page.wait_for_selector(".pm-image-editor", state="visible")
        assert page.locator(".pm-image-editor-badge").inner_text().strip().lower() == "image"
        page.locator(".pm-image-editor-preset", has_text="500").click()
        page.locator(".pm-image-editor-mode-btn").click()
        assert 'width="500"' in page.locator(".pm-image-editor-raw").input_value()
        page.locator(".pm-image-editor .pm-annotation-save").click()
        page.wait_for_selector(".pm-image-editor", state="hidden")
        assert 'width="500"' in scene.read_text(encoding="utf-8")

        # 6. Hover Remove deletes the embedded image cleanly and auto-saves
        page.locator("#sceneProseHost .pm-scene-image").hover()
        page.locator(".pm-scene-image-action", has_text="Remove").click()
        page.wait_for_function("() => !document.querySelector('#sceneProseHost .pm-scene-image')")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and "<img" in scene.read_text(encoding="utf-8"):
            time.sleep(0.1)
        assert "<img" not in scene.read_text(encoding="utf-8")
        assert errors == []
        page.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
