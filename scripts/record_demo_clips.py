"""Record Proseview demo clips against the fictional demo book.

Never point this at a real manuscript: the output is meant for a public README.
"""
from __future__ import annotations

import json
import os
import re
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
#: Beat maps saved by a real agent against the demo book's opening scene.
#: Make one by opening that scene in a copy of the demo book, choosing the
#: Beats tab and Generate Beat Map, then copy .proseview/beatmaps/ here.
BEATMAPS = SCRATCH / "beatmaps"
THEME = "graphite-dark"
#: The Claude model the agents clip asks, independent of local Claude settings.
CLIP_CLAUDE_MODEL = "opus"
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
    # A few days of writing, not one commit made a moment ago: from that the
    # Progress card read the whole book as written today, with every scene
    # "changed today". Chapters 1-10 land three days back, 11 and 12 one day
    # each after, and every file carries the day it was committed.
    chapters = sorted(p.name for p in (root / "manuscript").iterdir() if p.is_dir())
    batches = [
        (3, [p for p in root.iterdir() if p.name not in {"manuscript", ".git"}]
            + [root / "manuscript" / c for c in chapters[:-2]]
            + [p for p in (root / "manuscript").iterdir() if p.is_file()]),
        (2, [root / "manuscript" / chapters[-2]]),
        (1, [root / "manuscript" / chapters[-1]]),
    ]
    for days_ago, paths in batches:
        when = time.time() - days_ago * 86400
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when))
        for path in paths:
            for item in [path, *path.rglob("*")] if path.is_dir() else [path]:
                os.utime(item, (when, when))
        subprocess.run(["git", "add", "--", *[str(p.relative_to(root)) for p in paths]],
                       cwd=root, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", f"Draft"], cwd=root, check=True,
                       env={**env, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    # A beat map an agent made earlier for the opening scene (see
    # flow_beatmap). A real agent takes a minute or two to map a scene, which
    # is too long to sit through in a README clip.
    if BEATMAPS.is_dir():
        shutil.copytree(BEATMAPS, root / ".proseview" / "beatmaps")
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
            ROOM_MARKS["start"] = time.monotonic()
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
    # "Queen" reaches a file, scenes, a note and the prose: every group the
    # clip claims. ("rabbit hole" matched nothing -- the text says
    # "rabbit-hole" -- and the clip ended on "No matches".)
    page.type("#searchBox", "Queen", delay=60)
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


def attach_current_scene(page) -> None:
    attach = page.get_by_role("button", name=re.compile(r"^Attach current document"))
    if attach.count():
        attach.first.click()
        page.wait_for_selector("#discussContext .discuss-chip-current")
    beat(page, 700)


def flow_agents(page, base, docs):
    """Two agent tabs, each its own conversation, both live at once.

    Requires `codex` and `claude` authenticated on this machine. The answers in
    the clip are real: a scripted stand-in would be a claim about output that
    never happened.
    """
    # Codex reports warnings about the recording machine's own account
    # configuration into the conversation. They say nothing about Proseview and
    # name that account's settings, so they are kept out of a public clip.
    page.add_init_script("""
        new MutationObserver(() => document.querySelectorAll('.discuss-notice').forEach(n => {
            if (/requirements layers/.test(n.textContent)) n.remove();
        })).observe(document.documentElement, {childList: true, subtree: true});
    """)
    open_scene(page, base, SCENE)
    beat(page, 900)
    page.evaluate("() => showDiscussAgentTab('codex')")
    page.wait_for_selector("#discussPanel:not([hidden])")
    page.wait_for_selector("#discussSend:not([disabled])", timeout=30000)
    beat(page, 1200)

    # A question carries no file until it is attached; ask about the scene on
    # screen, the way a writer would.
    attach_current_scene(page)
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
    # Pin the model through the picker's own path rather than whatever the
    # recording machine's Claude settings default to, which may have no
    # credits left; the chip in the clip then names the model that answered.
    page.evaluate("() => saveDiscussModel({model: CLIP_CLAUDE_MODEL, effort: 'high'}, '')".replace(
        "CLIP_CLAUDE_MODEL", repr(CLIP_CLAUDE_MODEL)))
    page.wait_for_function(
        "model => window._discussSnapshot && window._discussSnapshot.model.model === model",
        arg=CLIP_CLAUDE_MODEL,
    )
    attach_current_scene(page)
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


def flow_beatmap(page, base, docs):
    """The Beats tab: the tension line, the beats, and moments that find their paragraph.

    Needs a beat map in docs/_clips/beatmaps (see BEATMAPS); the map in the
    clip is what an agent made for this scene.
    """
    page.add_init_script("localStorage.setItem('proseview-frontmatter-collapsed','true')")
    open_scene(page, base, SCENE)
    page.evaluate("() => setSidebarOpen(false)")
    beat(page, 900)
    page.evaluate("() => showScenePanelTab('beats')")
    page.wait_for_selector(".sidebar-beat-group", timeout=30000)
    beat(page, 1800)
    cards = page.locator(".sidebar-moment-card")
    for i in range(min(3, cards.count())):
        cards.nth(i).hover()
        beat(page, 300)
        cards.nth(i).click()
        beat(page, 1600)
    groups = page.locator(".sidebar-beat-group")
    if groups.count() > 2:
        groups.nth(2).click(position={"x": 60, "y": 14})
        beat(page, 1400)
        moment = page.locator(".sidebar-moment-card").first
        if moment.count():
            moment.click()
            beat(page, 2000)


def flow_review(page, base, docs):
    """A scene review: Quick critique on Codex, from findings to applied edits.

    Requires `codex` signed in on this machine. The review and the edit are
    real, so both waits are long; main() plays them fast. Compare shows one
    suggestion against the passage; two findings are ticked, one gets a note,
    Prepare request fills the composer, and Codex applies them on the
    throwaway copy of the demo book.
    """
    page.add_init_script("localStorage.setItem('proseview-frontmatter-collapsed','true')")
    page.add_init_script("""
        new MutationObserver(() => document.querySelectorAll('.discuss-notice').forEach(n => {
            if (/requirements layers/.test(n.textContent)) n.remove();
        })).observe(document.documentElement, {childList: true, subtree: true});
    """)
    open_scene(page, base, SCENE)
    page.evaluate("() => setSidebarOpen(false)")
    beat(page, 900)
    page.evaluate("() => showDiscussAgentTab('codex')")
    page.wait_for_selector("#discussSend:not([disabled])", timeout=30000)
    beat(page, 1200)
    # A new chat already shows the review cards; otherwise open them.
    run = page.get_by_role("button", name="Run Quick critique with defaults", exact=True)
    if not run.is_visible():
        page.click("#discussCraftButton")
    run.wait_for(state="visible")
    run.hover()
    beat(page, 1800)
    REVIEW_MARKS["send"] = time.monotonic() - ROOM_MARKS["start"]
    run.click()
    # Wait for the finished review: the turn is done and its findings carry
    # Compare buttons. Codex's first "Thought" message is not the answer.
    page.wait_for_function(
        """() => {
            const status = document.getElementById('discussTurnStatus');
            const state = status ? status.dataset.state : '';
            return (state === 'done' || state === 'idle')
                && document.querySelectorAll('#discussLog .discuss-quote-compare').length >= 2;
        }""",
        timeout=900000, polling=1000,
    )
    REVIEW_MARKS["done"] = time.monotonic() - ROOM_MARKS["start"]
    beat(page, 1200)
    # Read down through the findings.
    heading = page.locator("#discussLog h3").first
    if heading.count():
        heading.scroll_into_view_if_needed()
        page.evaluate("() => { const h = document.querySelector('#discussLog h3'); if (h) h.scrollIntoView({block: 'start'}); }")
    beat(page, 2600)
    for _ in range(3):
        page.mouse.move(1050, 400)
        page.mouse.wheel(0, 200)
        beat(page, 1500)
    # Compare one suggestion with the passage as it stands.
    compare = page.locator("#discussLog .discuss-quote-compare")
    if compare.count() > 1:
        compare.nth(1).scroll_into_view_if_needed()
        beat(page, 700)
        compare.nth(1).hover()
        beat(page, 600)
        compare.nth(1).click()
        beat(page, 3200)
        page.keyboard.press("Escape")
        beat(page, 900)
    # Select two findings, note one, and ask Codex to apply them.
    picks = page.locator("#discussLog .edit-selection-control input")
    for i in range(min(2, picks.count())):
        picks.nth(i).scroll_into_view_if_needed()
        beat(page, 600)
        picks.nth(i).check()
        beat(page, 1200)
        if i == 0:
            note = page.locator("#discussLog .edit-selection-add-note").first
            if note.count():
                note.click()
                field = page.locator("#discussLog .edit-selection-note-host textarea").first
                field.wait_for(state="visible")
                field.type("Keep it as short as Alice would say it.", delay=35)
                beat(page, 1000)
    prepare = page.locator(".edit-selection-prepare").first
    prepare.wait_for(state="visible")
    prepare.hover()
    beat(page, 800)
    prepare.click()
    beat(page, 2200)  # The composer now reads "Apply items ..." with the note.
    REVIEW_MARKS["apply"] = time.monotonic() - ROOM_MARKS["start"]
    page.click("#discussSend")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        accept = page.get_by_role("button", name="Accept once", exact=True)
        if accept.count() and accept.first.is_visible():
            accept.first.click()
        if page.evaluate("""() => {
                const status = document.getElementById('discussTurnStatus');
                const state = status ? status.dataset.state : '';
                return (state === 'done' || state === 'idle')
                    && !!document.querySelector('#discussLog .discuss-review');
            }"""):
            break
        page.wait_for_timeout(1000)
    REVIEW_MARKS["applied"] = time.monotonic() - ROOM_MARKS["start"]
    beat(page, 800)
    # The saved edit: its card, with Undo all and Looks good.
    card = page.locator("#discussLog .discuss-review").last
    if card.count():
        card.scroll_into_view_if_needed()
        beat(page, 2600)
        card.get_by_role("button", name="Looks good").hover()
        beat(page, 1600)
    # End on the card. A finding Codex reworded (say, for a note) stays
    # "Requested" rather than "Applied", which reads as a failure in a clip.

#: Times in the review clip, in seconds from the start of the recording.
REVIEW_MARKS: dict[str, float] = {}


def flow_room(page, base, docs):
    """The Group: editors on different agents debate one question in one conversation.

    Uses the Group editors saved on the recording machine (two or three, each
    on Codex, Claude or Agy); the clip waits for every one of them.

    Requires `codex` and `claude` signed in on this machine. The answers are
    real, so the clip is long while they think; main() speeds that part up.
    """
    page.add_init_script("localStorage.setItem('proseview-frontmatter-collapsed','true')")
    page.add_init_script("""
        new MutationObserver(() => document.querySelectorAll('.discuss-notice').forEach(n => {
            if (/requirements layers/.test(n.textContent)) n.remove();
        })).observe(document.documentElement, {childList: true, subtree: true});
    """)
    open_scene(page, base, SCENE)
    page.evaluate("() => setSidebarOpen(false)")
    beat(page, 900)
    page.evaluate("() => showScenePanelTab('group')")
    page.wait_for_selector("#groupInput", state="visible", timeout=30000)
    beat(page, 1600)
    page.click("#groupInput")
    page.keyboard.type("Should Alice's Latitude-and-Longitude musing stay or go? Two sentences each, "
                       "and push back on each other.", delay=35)
    beat(page, 700)
    ROOM_MARKS["send"] = time.monotonic() - ROOM_MARKS["start"]
    page.keyboard.press("Enter")
    page.wait_for_function(
        """() => { const s = _groupSessionsByScene[_groupCurrentScenePath()];
            const seats = (s && s.participants && s.participants.length) || 2;
            return s && s.turns.filter(t => t.role === 'critic').length >= seats && !s.busy
                && !s.queue.length && (!s.runtime || ['idle', 'review'].includes(s.runtime.status)); }""",
        timeout=600000,
    )
    ROOM_MARKS["done"] = time.monotonic() - ROOM_MARKS["start"]
    beat(page, 1200)
    # Read the debate: back up to the question, then down through every answer.
    body = "document.getElementById('groupBody')"
    page.evaluate(f"""() => {{ const el = {body}; const q = el && [...el.querySelectorAll('*')]
        .find(n => n.children.length === 0 && /stay or go/.test(n.textContent));
        if (q) q.scrollIntoView({{block: 'start'}}); else if (el) el.scrollTop = 0; }}""")
    beat(page, 2200)
    for _ in range(12):
        done = page.evaluate(f"""() => {{ const el = {body}; if (!el) return true;
            el.scrollBy({{top: 150, behavior: 'smooth'}});
            return el.scrollTop + el.clientHeight >= el.scrollHeight - 4; }}""")
        beat(page, 1300)
        if done:
            break
    beat(page, 1500)

#: Times in the room clip, in seconds from the start of the recording.
ROOM_MARKS: dict[str, float] = {}


def flow_illustration(page, base, docs):
    """A scene illustration: pick a style, Codex draws it, Insert puts it in the scene.

    A real Codex image generation (about a minute); main() plays the wait fast.
    """
    fold_frontmatter = """() => {
        const fm = document.querySelector('#sceneProseHost .fm, #sceneModal .fm');
        if (fm && !fm.classList.contains('is-collapsed')) fm.querySelector('.fm-toggle').click();
    }"""
    open_scene(page, base, SCENE)
    page.evaluate(fold_frontmatter)
    beat(page, 1000)
    page.click("#sceneImageOptionsBtn")
    page.wait_for_selector("#sceneImageMenu .scene-image-style-card")
    beat(page, 1400)
    page.click('#sceneImageMenu .scene-image-style-card[data-style-id="woodcut"]')
    beat(page, 1000)
    page.click("#sceneImagePopGenBtn")
    ILLUSTRATION_MARKS["send"] = time.monotonic() - ROOM_MARKS["start"]
    page.wait_for_selector("#sceneImageInsertBtn", timeout=300_000)
    ILLUSTRATION_MARKS["done"] = time.monotonic() - ROOM_MARKS["start"]
    beat(page, 2600)
    page.hover("#sceneImageInsertBtn")
    beat(page, 500)
    page.click("#sceneImageInsertBtn")
    page.wait_for_selector("#sceneProseHost img")
    page.evaluate(fold_frontmatter)
    beat(page, 700)
    # The inserted picture sits above the opening paragraphs, as it will in
    # the book.
    page.evaluate("""() => {
        const img = document.querySelector('#sceneProseHost img');
        img.scrollIntoView({block: 'start'});
    }""")
    beat(page, 3000)


#: Times in the illustration clip, in seconds from the start of the recording.
ILLUSTRATION_MARKS: dict[str, float] = {}


FLOWS = {
    "demo-highlights": flow_highlights,
    "demo-writing": flow_writing,
    "demo-search": flow_search,
    "demo-timeline": flow_timeline,
    "demo-agents": flow_agents,
    "demo-beatmap": flow_beatmap,
    "demo-room": flow_room,
    "demo-review": flow_review,
    "demo-illustration": flow_illustration,
}
#: Clips that need a signed-in agent, left out of a plain run.
AGENT_CLIPS = {"demo-agents", "demo-room", "demo-review", "demo-illustration"}


def speed_up(webm: Path, start: float, end: float, factor: int = 12,
             more: tuple[tuple[float, float], ...] = ()) -> Path:
    """Play the stretch between start and end seconds (and any `more`) `factor` times faster."""
    spans = [(a, b) for a, b in [(start, end), *more] if b - a >= 3]
    if not spans:
        return webm
    out = webm.with_name("trimmed.mp4")
    parts, cursor = [], 0.0
    for a, b in sorted(spans):
        parts += [f"trim={cursor}:{a},setpts=PTS-STARTPTS", f"trim={a}:{b},setpts=(PTS-STARTPTS)/{factor}"]
        cursor = b
    parts.append(f"trim={cursor},setpts=PTS-STARTPTS")
    graph = "".join(f"[0:v]{part}[p{i}];" for i, part in enumerate(parts))
    graph += "".join(f"[p{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
    subprocess.run(["ffmpeg", "-y", "-i", str(webm), "-filter_complex", graph, "-map", "[v]",
                    "-an", str(out)], check=True, capture_output=True)
    return out


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
    names = argv[1:] or [n for n in FLOWS if n not in AGENT_CLIPS] + list(SHOTS)
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
        if name == "demo-room" and "done" in ROOM_MARKS:
            # The editors take a while to think; play that stretch fast.
            webm = speed_up(webm, ROOM_MARKS["send"] + 2.5, ROOM_MARKS["done"] - 1.5)
        if name == "demo-review" and "done" in REVIEW_MARKS:
            # A review takes minutes; show only that it is working.
            more = ((REVIEW_MARKS["apply"] + 3, REVIEW_MARKS["applied"] - 1),) if "applied" in REVIEW_MARKS else ()
            webm = speed_up(webm, REVIEW_MARKS["send"] + 3, REVIEW_MARKS["done"] - 1, factor=60, more=more)
        if name == "demo-illustration" and "done" in ILLUSTRATION_MARKS:
            # Codex takes about a minute to draw; show only that it is working.
            webm = speed_up(webm, ILLUSTRATION_MARKS["send"] + 2.5, ILLUSTRATION_MARKS["done"] - 1, factor=20)
        to_gif(webm, dest / f"{name}.gif")
    return 0



# ── Stills ──────────────────────────────────────────────────────────────────
# The PNGs in the README. Same demo book, same theme as the clips, so the
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


def shot_book(page, base, docs):
    # The intro note shows the first few times; a still should show the book.
    page.add_init_script("localStorage.setItem('proseview-book-intro-seen','3')")
    page.goto(f"{base}#/book", wait_until="load")
    page.wait_for_function("() => document.documentElement.dataset.view === 'book'")
    page.wait_for_timeout(1500)


def shot_writing(page, base, docs):
    # The landing page's opening image: a scene mid-sentence in the editor,
    # with its chapter open in the sidebar beside it. The frontmatter is
    # folded, as a writer who has chosen that sees it, so the prose leads.
    page.add_init_script("localStorage.setItem('proseview-frontmatter-collapsed','true')")
    open_scene(page, base, SCENE)
    page.evaluate("() => document.documentElement.style.setProperty('--sidebar-w', '300px')")
    page.click("#sceneEditBtn")
    page.wait_for_function("() => window._pmEditMode === true")
    page.evaluate(
        """() => {
            const host = document.querySelector('#sceneProseHost .ProseMirror');
            const para = host.querySelectorAll('p')[2];
            const range = document.createRange();
            range.selectNodeContents(para);
            range.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            host.focus();
        }"""
    )
    page.keyboard.type(" Down, down, down.")
    # Back to the top of the scene, so its title shows above the prose.
    page.evaluate(
        """() => {
            let el = document.querySelector('#sceneProseHost');
            while (el && !(el.scrollHeight > el.clientHeight && getComputedStyle(el).overflowY !== 'visible')) el = el.parentElement;
            (el || document.scrollingElement).scrollTop = 0;
        }"""
    )
    page.wait_for_timeout(1200)


def shot_export_formats(page, base, docs):
    # The Export dialog's second step with Print book chosen, so its trim
    # size and right-hand chapters show under every format card.
    page.goto(base, wait_until="load")
    page.wait_for_selector("#tab-overview", state="visible")
    page.get_by_role("button", name="Export").first.click()
    page.wait_for_selector("#exportTree .export-chapter")
    page.get_by_role("button", name="Next: Format and style").click()
    page.get_by_role("radio", name="Print book (PDF)").check()
    page.wait_for_timeout(800)


def shot_export_preview(page, base, docs):
    # The third step: the book's details beside a preview of the print
    # book's facing pages, as Export will make them.
    shot_export_formats(page, base, docs)
    page.get_by_role("button", name="Next: Book details").click()
    page.wait_for_selector("#exportPaperView .pdf-page canvas", state="visible", timeout=120000)
    page.wait_for_timeout(1500)


def shot_demo_preview(page, base, docs):
    # The demo site's link preview: the size link previews use, 1200x630.
    page.set_viewport_size({"width": 1200, "height": 630})
    shot_analytics(page, base, docs)


def shot_storylines(page, base, docs):
    # The landing page's storylines row: the Timeline tab's charts alone,
    # without the sidebar and header, so the lanes read at page width.
    # Tall enough that the charts and the lanes fit without scrolling.
    page.set_viewport_size({"width": VIEWPORT["width"], "height": 1100})
    page.goto(base, wait_until="load")
    page.evaluate("() => showTab('timeline')")
    page.wait_for_selector("#tab-timeline", state="visible")
    # Charts animate in; a still taken too early catches half-drawn bars.
    page.wait_for_timeout(2600)
    # From "Proportion of the book" down to the storylines' note, with a
    # margin of the page's own background around it.
    return page.evaluate(
        """() => {
            const host = document.getElementById('timelineContent');
            const top = host.getBoundingClientRect().top;
            // The first note sums up the charts, the second the storylines.
            const note = host.querySelectorAll('.story-note')[1];
            const box = host.getBoundingClientRect();
            const bottom = note ? note.getBoundingClientRect().bottom : box.bottom;
            const pad = 24;
            return {x: box.left - pad, y: top - pad, width: box.width + 2 * pad, height: bottom - top + 2 * pad};
        }"""
    )


SHOTS = {
    "write-a-scene": shot_writing,
    "storylines": shot_storylines,
    "export-formats": shot_export_formats,
    "export-preview": shot_export_preview,
    "demo-preview": shot_demo_preview,
    "dashboard": shot_dashboard,
    "analytics": shot_analytics,
    "read-the-book": shot_book,
    "beat-map": None,  # set below
}


def shot_beatmap(page, base, docs):
    # The Beats tab beside the opening scene, with a moment chosen and its
    # paragraph marked in the prose. Needs a map in BEATMAPS.
    page.add_init_script("localStorage.setItem('proseview-frontmatter-collapsed','true')")
    open_scene(page, base, SCENE)
    page.evaluate("() => setSidebarOpen(false)")
    page.evaluate("() => showScenePanelTab('beats')")
    page.wait_for_selector(".sidebar-beat-group", timeout=30000)
    page.locator(".sidebar-moment-card").nth(2).click()
    page.wait_for_timeout(1500)


SHOTS["beat-map"] = shot_beatmap


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
            target = flow(page, base, scenes(base))
            # A still may name the part of the window it shows; otherwise it is the window.
            if target is not None:
                page.screenshot(path=str(out), clip=target)
            else:
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
