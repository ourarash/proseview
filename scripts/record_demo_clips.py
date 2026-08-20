"""Record Proseview demo clips against the fictional demo book.

Never point this at a real manuscript: the output is meant for a public README.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
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


def book_with_history() -> Path:
    """A throwaway git copy of the demo book.

    The Goals panel and Recently Modified read git. Without a repository the
    dashboard renders "Git is not available", which is a poor thing to lead a
    README with and not what a reader will see against their own manuscript.
    """
    tmp = Path(tempfile.mkdtemp(prefix="proseview-demo-"))
    root = tmp / "book"
    shutil.copytree(BOOK, root)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Proseview Demo", "GIT_AUTHOR_EMAIL": "demo@example.com",
        "GIT_COMMITTER_NAME": "Proseview Demo", "GIT_COMMITTER_EMAIL": "demo@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "Demo manuscript"], cwd=root, check=True, env=env)
    return root


def start_server(port: int, root: Path | None = None):
    proc = subprocess.Popen(
        [sys.executable, "-m", "proseview", "--root", str(root or BOOK),
         "--no-open", "--port", str(port)],
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
    # Against a throwaway copy, never the committed fixture: the writing clip
    # saves a line to disk, and a demo must not edit the repository it ships in.
    root = book_with_history()
    proc, base = start_server(port, root)
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
        shutil.rmtree(root.parent, ignore_errors=True)
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


# ── Flows ───────────────────────────────────────────────────────────────────
# One function per clip. Each drives the real UI against the demo book; nothing
# here fakes a result. Pauses are deliberate: a clip that moves at machine speed
# is unreadable, and a README GIF is watched once without a scrub bar.

SCENE = "ch01/01-down-the-rabbit-hole.md"


def beat(page, ms: int = 900) -> None:
    """A readable pause between actions."""
    page.wait_for_timeout(ms)


def flow_highlights(page, base, docs):
    """The Analysis panel, and passes switching on as their rows are clicked."""
    open_scene(page, base, SCENE)
    beat(page, 900)
    # Driven through the panel rather than toggleHighlight(): the clip exists
    # to show where the switches are. Colour that arrives with nothing visibly
    # touching it teaches a reader nothing about how to turn a pass on.
    page.click("#sceneModal .discuss-open-btn")
    page.wait_for_selector("#discussPanel:not([hidden])")
    beat(page, 700)
    page.click("#utilityTabAnalysis")
    page.wait_for_selector("#scenePassList", state="visible")
    beat(page, 1400)
    for pass_name in ("repeats", "filter_verbs", "sensory", "passive_voice"):
        row = page.locator("#pass-row-" + pass_name)
        row.scroll_into_view_if_needed()
        row.hover()
        beat(page, 350)
        row.click()
        beat(page, 1400)
    beat(page, 800)
    # Off again, so the clip ends on clean prose rather than a wall of colour.
    # With passes on, the All button reads Clear.
    page.click("#scenePassAllBtn")
    beat(page, 900)


def flow_writing(page, base, docs):
    """Reading view becomes the writing surface, and Mod-S saves."""
    open_scene(page, base, SCENE)
    beat(page, 800)
    page.click("#sceneEditBtn")
    page.wait_for_function("() => window._pmEditMode === true")
    beat(page)
    page.evaluate(
        """() => {
            const host = document.querySelector('#sceneProseHost .ProseMirror');
            const paras = host.querySelectorAll('p');
            const last = paras[paras.length - 1];
            last.scrollIntoView({block: 'center'});
            const range = document.createRange();
            range.selectNodeContents(last);
            range.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            host.focus();
        }"""
    )
    beat(page, 500)
    page.keyboard.type(" Down, down, down.", delay=45)
    beat(page, 900)
    page.keyboard.press("Meta+s")
    beat(page, 1500)


def flow_search(page, base, docs):
    """Mod-K from a scene: paths, metadata, TODOs, notes, and prose."""
    open_scene(page, base, SCENE)
    beat(page, 1100)
    page.evaluate("() => focusSearch()")
    page.wait_for_selector("#searchBox", state="visible")
    beat(page, 600)
    page.fill("#searchBox", "")
    page.type("#searchBox", "rabbit hole", delay=60)
    beat(page, 2600)


def flow_timeline(page, base, docs):
    """The shape of the book: chapter proportion, lanes, reading vs story order."""
    page.goto(base, wait_until="load")
    beat(page, 900)
    page.evaluate("() => showTab('timeline')")
    page.wait_for_selector("#timelineContent", state="visible")
    beat(page, 1800)
    page.mouse.wheel(0, 320)
    beat(page, 1500)
    scene_marks = page.locator("#timelineContent [data-scene], #timelineContent .timeline-scene")
    if scene_marks.count():
        scene_marks.first.hover()
        beat(page, 1800)


def flow_agents(page, base, docs):
    """Two agent tabs, each its own conversation, both live at once.

    Requires `codex` and `claude` authenticated on this machine. The answers in
    the clip are real: a scripted stand-in would be a claim about output that
    never happened.
    """
    open_scene(page, base, SCENE)
    beat(page, 900)
    page.evaluate("() => showDiscussAgentTab('codex')")
    page.wait_for_selector("#discussPanel:not([hidden])")
    page.wait_for_selector("#discussSend:not([disabled])", timeout=30000)
    beat(page, 1200)

    page.fill("#discussInput", "In one sentence, what is Alice feeling here?")
    beat(page, 700)
    page.click("#discussSend")
    # Let the answer stream in far enough to read.
    page.wait_for_function(
        "() => (window._discussSnapshot?.messages || []).some(m => m.role === 'assistant')",
        timeout=120000,
    )
    beat(page, 2400)

    page.click("#utilityTabClaude")
    page.wait_for_function("() => _discussAgent === 'claude'")
    page.wait_for_selector("#discussSend:not([disabled])", timeout=30000)
    beat(page, 1400)
    page.fill("#discussInput", "In one sentence, what is Alice feeling here?")
    beat(page, 700)
    page.click("#discussSend")
    page.wait_for_function(
        "() => (window._discussSnapshot?.messages || []).some(m => m.role === 'assistant')",
        timeout=120000,
    )
    beat(page, 2600)

    # Back to Codex: its conversation is still there, untouched.
    page.click("#utilityTabCodex")
    page.wait_for_function("() => _discussAgent === 'codex'")
    beat(page, 2400)


FLOWS = {
    "demo-highlights": flow_highlights,
    "demo-writing": flow_writing,
    "demo-search": flow_search,
    "demo-timeline": flow_timeline,
    "demo-agents": flow_agents,
}


def to_gif(webm: Path, out: Path, fps: int = 8, width: int = 780) -> Path:
    """Two-pass palette conversion: a shared palette banks badly on prose."""
    palette = webm.parent / "palette.png"
    scale = f"fps={fps},scale={width}:-1:flags=lanczos"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(webm), "-vf", f"{scale},palettegen=stats_mode=diff",
         str(palette)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(webm), "-i", str(palette),
         # No dithering: flat UI colour dithers into noise, and noise is bytes.
         "-lavfi", f"{scale},paletteuse=dither=none",
         str(out)],
        check=True, capture_output=True,
    )
    print(f"  -> {out.name}: {out.stat().st_size // 1024} KB")
    return out


def main(argv: list[str]) -> int:
    names = argv[1:] or [n for n in FLOWS if n != "demo-agents"] + list(SHOTS)
    unknown = [n for n in names if n not in FLOWS and n not in SHOTS]
    if unknown:
        print(f"unknown target(s): {', '.join(unknown)}")
        print(f"available: {', '.join(list(FLOWS) + list(SHOTS))}")
        return 2
    if not shutil.which("ffmpeg"):
        print("ffmpeg is required to write the GIFs")
        return 2
    dest = REPO / "docs" / "images"
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        if name in SHOTS:
            print(f"capturing {name} ...")
            capture(name, SHOTS[name])
            continue
        print(f"recording {name} ...")
        webm = record(name, FLOWS[name])
        to_gif(webm, dest / f"{name}.gif")
    return 0



# ── Stills ──────────────────────────────────────────────────────────────────
# The two PNGs in the README. Same demo book, same theme as the clips, so the
# gallery reads as one product rather than three eras of it.

def shot_dashboard(page, base, docs):
    page.goto(base, wait_until="load")
    page.wait_for_selector("#tab-overview", state="visible")
    # One chapter opened to its scenes. This still leads the README, and a
    # column of closed ch01..ch12 folders never shows what a chapter holds.
    page.wait_for_selector("#sidebarTree .dir-toggle")
    # Wide enough for a scene filename to sit on one line. The sidebar is
    # drag-resizable, so this is a width a reader can have, not a mock-up.
    page.evaluate("() => document.documentElement.style.setProperty('--sidebar-w', '300px')")
    page.get_by_role("treeitem", name="ch01", exact=True).click()
    page.wait_for_selector('#sidebarTree [data-path*="ch01/"]', state="visible")
    page.wait_for_timeout(1800)


def shot_analytics(page, base, docs):
    page.goto(base, wait_until="load")
    page.evaluate("() => showTab('analysis')")
    page.wait_for_selector("#tab-analysis", state="visible")
    # Charts animate in; a still taken too early catches half-drawn bars.
    page.wait_for_timeout(2600)


SHOTS = {
    "dashboard": shot_dashboard,
    "analytics": shot_analytics,
}


def capture(name: str, flow, port: int = 7861) -> Path:
    out = REPO / "docs" / "images" / f"{name}.png"
    root = book_with_history()
    proc, base = start_server(port, root)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            ctx.add_init_script(f"localStorage.setItem('proseview-theme','{THEME}')")
            page = ctx.new_page()
            flow(page, base, scenes(base))
            page.screenshot(path=str(out), full_page=False)
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(root.parent, ignore_errors=True)
    print(f"  -> {out.name}: {out.stat().st_size // 1024} KB")
    return out

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
