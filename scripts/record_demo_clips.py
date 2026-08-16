"""Record Proseview demo clips against the fictional demo book.

Never point this at a real manuscript: the output is meant for a public README.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path("/Users/ari/github/proseview")
BOOK = REPO / "fixtures" / "demo-book"
SCRATCH = Path(__file__).resolve().parents[1] / "docs" / "_clips"
THEME = "graphite-dark"
VIEWPORT = {"width": 1280, "height": 760}

SELECT_JS = """(needle) => {
    const host = document.getElementById('sceneProseHost');
    const w = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
    let n = null, i = -1;
    while ((n = w.nextNode())) { i = n.data.indexOf(needle); if (i >= 0) break; }
    if (!n) return false;
    n.parentElement.scrollIntoView({block: 'center'});
    const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + needle.length);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    host.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    return true; }"""

CLEAR_SELECTION_JS = """() => {
    const m = document.getElementById('selectionPillMenu'); if (m) m.hidden = true;
    const p = document.getElementById('selectionPill'); if (p) p.hidden = true;
    window.getSelection().removeAllRanges(); }"""


def start_server(port: int):
    proc = subprocess.Popen(
        [sys.executable, "-m", "proseview", "--root", str(BOOK), "--no-open", "--port", str(port)],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://localhost:{port}"
    for _ in range(400):
        try:
            urllib.request.urlopen(base, timeout=2).read()
            return proc, base
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("server never came up")


def scenes(base: str) -> dict:
    return json.loads(urllib.request.urlopen(base + "/data.json", timeout=30).read())["contents"]


def record(name: str, flow, port: int = 7860) -> Path:
    out = SCRATCH / "clips" / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    proc, base = start_server(port)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(
                viewport=VIEWPORT, record_video_dir=str(out), record_video_size=VIEWPORT
            )
            ctx.add_init_script(f"localStorage.setItem('proseview-theme','{THEME}')")
            page = ctx.new_page()
            flow(page, base, scenes(base))
            ctx.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    webm = next(out.glob("*.webm"))
    print(f"  {name}: {webm.stat().st_size // 1024} KB")
    return webm


def open_scene(page, base, rel):
    page.goto(f"{base}#/scene/{rel}", wait_until="load")
    page.wait_for_selector("#sceneProseHost .ProseMirror")


# Not recorded here: the AI / Discuss flow. It needs a logged-in agent CLI, and
# the point of a clip is to show what the tool actually produces -- a scripted
# stand-in would be a claim about output that never happened. Run this on a
# machine with `codex` authenticated and drive the Discuss panel to capture one.
