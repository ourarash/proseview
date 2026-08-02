# Proseview

> A local dashboard and AI harness for novelists who write in Markdown. ✍️

Proseview reads your manuscript folder, gives you a writer-grade view of
its structure and prose, and turns the same surface into a place where you
can read, edit, annotate, and bring an AI assistant to any paragraph
without leaving the page.

It runs entirely on your machine. No cloud, no telemetry, no lock-in. Your
files stay where they are.

![status](https://img.shields.io/badge/status-alpha-orange)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

## ✨ What you get

- 📊 **Dashboard.** Word count, chapter pacing, lexical health (MATTR /
  MTLD), sentence-rhythm variance, character presence, location
  stickiness, character co-occurrence, plus a sortable scene table.
- 📖 **Reading view.** Open a scene as a typographic page with a real
  reader font. The dashboard chrome gets out of the way.
- ✏️ **WYSIWYG editor.** ProseMirror-backed. Same surface as the reading
  view, just with `Edit` toggled on. Mod-S saves. Conflict guard checks
  the file mtime so a concurrent change in your editor never gets
  silently overwritten.
- 🎨 **Editorial highlights.** Toggle nine prose passes on top of any
  scene: repetition, passive voice, filter verbs, crutch words,
  hyperbole, lyrical reach, sensory density, comedy beats, first-person
  rate. Each pass is a single click.
- 🗒️ **Inline TODOs and Notes.** Select a passage, drop a `TODO` or a
  tagged `NOTE` (continuity / character / theme / question), and it
  lands in the file as a Markdown comment. Survives in git.
- 🤖 **AI on the selection.** Send the highlighted passage to Codex,
  Claude, or Gemini in one click. An in-browser terminal hosts the
  conversation; the agent can see the file, the selection, and your
  repo. Your tools, your prompts.
- 💬 **Discuss with Codex.** Open a document-aware conversation beside
  any scene or supported repository text file. Prosview sends the current
  document automatically and only adds selections, files, or folders you
  explicitly attach. Safe progress summaries, plans, tool activity, approval
  requests, and streamed answers stay visible while you read.
- 🧰 **In-browser terminal.** xterm.js wired to a real PTY. Run `codex`,
  `claude`, or any shell command without leaving the dashboard. Tabs
  persist across page reloads.
- 🔁 **Live reload.** Save a file in your editor and the dashboard
  picks up the change over Server-Sent Events. No manual refresh.
- 🔗 **Deep links.** Every scene and file has a URL. Copy the address
  bar to share or revisit a view. Back / forward work.
- 🎨 **Themes and fonts.** Light, Dark, Docsify, Hopscotch. Reader,
  Literary, Inter, Georgia, Baskerville, Sans, Mono.
- 🧪 **Tested.** 260+ tests: unit coverage of the analytics engine, scene
  parsing, save guards, history, and refresh behavior, plus end-to-end
  tiers that boot the real server and drive the real UI in a browser.

## 🚀 Quick start

```bash
git clone https://github.com/ourarash/prosview.git
cd prosview
pip install -r requirements.txt

# Run the dashboard against your novel repo
python -m proseview --root /path/to/your/novel
```

A browser tab will open at `http://localhost:7842`. Press Ctrl-C to stop.

If you'd rather install proseview as a tool:

```bash
pip install -e .
proseview --root /path/to/your/novel
```

## 📁 What proseview expects

A folder of Markdown scene files, one folder per chapter. The minimum
viable repo:

```
my-novel/
├── manuscript/
│   ├── ch01/
│   │   ├── 01-opening.md
│   │   └── 02-meeting.md
│   └── ch02/
│       └── 01-aftermath.md
└── .proseview.yaml          # optional
```

Scene files use simple frontmatter:

```markdown
---
title: Opening
chapter: Chapter 1
status: draft
where: A bar in the West Village
when: Friday night, late
pov: Nima
characters: [Nima, Mira]
goal: Nima needs to get the question on the table
conflict: He's afraid she already has someone
outcome: She agrees to dinner; he leaves rattled
todos:
  - Tighten the opening paragraph
---

# Opening

The bar was loud and the music was bad...
```

Every field is optional. Proseview reads what's there and falls back
gracefully on what isn't.

### 📝 Frontmatter contract

These are the keys proseview recognizes. Any other keys are passed
through and ignored. Every field is optional.

#### Identity

- `title` (string) header of the scene viewer; defaults to a Title-Case
  version of the filename stem.
- `chapter` (string) "Chapter" column in the scene table and the
  chapter rows of charts; defaults to the chapter folder name.
- `status` (string) color-coded status badge. Conventional values:
  `draft`, `revision`, `done`. Anything else renders as a generic chip;
  missing means `unknown`.

#### Scene context

- `where` (string) "Where" row in the scene card. Also feeds the
  **Setting Stickiness** chart (Words per Location).
- `location` (string) synonym for `where` (older convention).
- `when` (string) "When" row in the scene card. Free-form.
- `pov` (string) "POV" row in the scene card. Free-form.
- `characters` (list of strings) "Characters" row in the scene card;
  each name is clickable to open the bio if
  `<characters_path>/<name>.md` exists. Also feeds the **Character
  Presence** and **Co-occurrence** charts.

#### Arc

- `goal` (string) "Goal" row in the arc panel.
- `conflict` (string) "Conflict" row in the arc panel.
- `outcome` (string) "Outcome" row in the arc panel.

#### Tasks

- `todos` (list of strings) each entry shows up as a frontmatter-level
  TODO in the Tasks panel. Inline `<!-- TODO: ... -->` comments inside
  the prose are picked up too and get a line anchor.

A scene with no frontmatter still renders, just with `Unknown` /
`Not defined` placeholders in the scene card and the file's stem as
its title.

## ⚙️ Configuration

`proseview` works with zero config. Drop a `.proseview.yaml` at the
repo root if you want to customize:

```yaml
# Where the manuscript lives. Default: manuscript/
manuscript_path: manuscript/

# Where character bios live. Default: story-bible/characters
characters_path: story-bible/characters

# Where AI skill prompts live. Default: skills
skills_path: skills

# Word-count goal for the finished book.
target_words: 80000

# Daily word goal (drives the "days to finish" estimate).
daily_target: 500

# Healthy band for local lexical variety (MATTR).
mattr_band: [0.74, 0.77]

# Healthy band for whole-scene lexical variety (MTLD).
mtld_band: [105, 130]

# Editor URL handler. One of: vscode, cursor, zed, positron, custom.
editor:
  scheme: vscode

# Folders shown in the file tree alongside the manuscript.
repo_tab:
  folders: [plans, continuity, outline, story-bible, docs, templates]
```

Every key has a sensible default; missing folders are simply skipped.

## 🧠 The analytics

Lexical health is real, not vibes:

- 📐 **MATTR** (moving-average type-token ratio, window 100). Measures
  *local* vocabulary variety. Low = the same words inside a paragraph;
  high = constant rotation that may feel jittery.
- 📐 **MTLD** (measure of textual lexical diversity). Measures
  *whole-scene* variety. Low = the scene keeps circling the same ground;
  high = the scene keeps reaching.
- 📐 **Sentence rhythm.** Per-chapter standard deviation of sentence
  length. Static / Rhythmic / Dynamic zones are annotated on the chart.
- 📐 **Dialogue percentage**, **passive voice rate**, **crutch-word rate**,
  **first-person density**, **sensory density**, **filter-verb rate**,
  **paragraph length**.

Every scene gets a row in the deep-dive table; outliers get listed under
Editorial Alerts with a one-line revision signal.

## 🤝 Working with AI

Four places where AI shows up, all opt-in:

1. **Selection menu.** Highlight any text in a scene. The pill that
   appears includes `Add TODO`, `Add Note`, and (if the corresponding
   tools are installed locally) `Run in Codex` and `Skills`. Skills are
   reusable prompts you keep in `skills/<name>/SKILL.md`; they show up
   automatically in the menu.
2. **Agent menu.** From the scene header, launch a conversation with
   Codex, Claude, or Gemini scoped to that file. The conversation runs
   in the in-browser terminal so you can keep reading the prose
   underneath while the agent works.
3. **Discuss.** Choose `Discuss` in a scene or text-file header to use the
   shared right utility dock. Prosview starts the local `codex app-server`
   lazily, uses your existing Codex login and configured model, and keeps full
   history in Codex's normal storage. Prosview persists only a hashed
   document-to-thread mapping in your user state directory. Raw reasoning is
   discarded; only Codex-authored progress summaries reach the browser. Tool
   and file actions remain subject to visible, user-reviewed approvals. If a
   stored Codex thread disappears, Prosview starts a replacement on the next
   question instead of leaving the document stuck. Use `New conversation` to
   intentionally clear the document's current discussion; the prior thread
   remains available in Codex history. The visible document is attached by
   default for each question; remove its context chip to omit it, or use the
   compact add-context control (keyboard shortcut `@`) to attach repository
   files and folders explicitly.
4. **TODOs as Markdown.** Every TODO and Note is a plain
   `<!-- TODO: ... -->` or `<!-- NOTE[tag]: ... -->` comment in the
   scene file. Your AI assistant can see them through the file, your
   repo can track them through git, and you can grep them.

## 🛣️ Roadmap

This is alpha. Things that are working and things that are coming:

- ✅ Live server, live reload, ProseMirror editor, highlights, TODOs,
  notes, deep links, in-browser terminal, agent menu, and document-aware
  Discuss conversations with Codex.
- ✅ Vendored front-end dependencies. chart.js, marked, xterm and
  friends ship with the package and load from `/vendor/`. ProseMirror
  modules are pinned to specific versions on esm.sh.
- ✅ Modularized front-end. The JS lives in nine topical files under
  `templates/assets/js/`, concatenated at render time.
- ✅ `proseview init` writes a starter `.proseview.yaml` so a fresh
  novel repo gets a working configuration with one command.
- ✅ Persisted UI prefs. Your highlight-pass toggles and theme choices
  survive scene navigation and reloads.
- 🚧 Diff-confirm for AI-suggested edits (selection runs in a terminal
  today; nothing applies edits without your approval, but the diff UX
  is still terminal-only).
- 🚧 Repo-wide search.
- 🚧 Configurable agent list (Codex / Claude / Gemini are presets today).
- 🚧 Continuity surfacing (warn when a scene contradicts a known fact).
- 🚧 Frontmatter editor (status, where, todos) inside the scene viewer
  so you don't need to drop into your text editor for routine fields.

See [plans/roadmap.md](plans/roadmap.md) for the full punch list.

## 🧪 Development

```bash
pip install -e ".[dev]"
pytest
```

That runs the unit suite plus an HTTP end-to-end tier that boots a real
`proseview` subprocess and drives every endpoint — saves and the conflict
guard, TODOs and notes, the AI proposal bridge through the actual CLI, live
reload over SSE, and PTY terminals — asserting on bytes written to disk.
Discuss integration tests use a deterministic fake app-server and isolated
home/state directories; they never contact Codex, the network, or your profile.
~15 seconds, no extra dependencies.

A browser tier drives the real UI in Chromium (editor round-trip fidelity,
the selection menu, highlight passes, deep links, agents, terminals, Discuss
streaming/approvals/shared-dock behavior, and applying an AI proposal end to
end). It's opt-in:

```bash
pip install -e ".[e2e]"
python -m playwright install chromium
pytest -m e2e_browser
```

Both tiers work on a throwaway copy of `fixtures/demo-repo`. See
[CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 📜 License

MIT. See [LICENSE](LICENSE).
