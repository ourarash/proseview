---
title: Proseview Spinoff and Hardening Plan
status: draft
date: 2026-05-08
---

# Proseview spinoff and hardening plan

## Why this exists

Proseview started from
[implementation-plan.md](implementation-plan.md)
and grew through several rounds of vibe coding. The current product is useful
to write against, but it is no longer planned. Several features were added on
top of the dashboard (terminal, scene editor, agent menu, file preview panel,
notes / todos, mood label) without revisiting the original information
architecture. The result is a single 3,400 line `app.js` driving a UI that
mixes a modal markdown viewer, an inline file panel, a scene editor, a tab
nav, and a sidebar tree, with a server-mode / static-mode duality cutting
across all of them.

The next step is to move proseview into its own repository, fix the rough
edges that have accumulated, and make the feature set defensible. This file
is the working punch list for that effort. Items are sorted by importance
and intentionally not tied to a single milestone.

LOC reference (for future-me): `app.js` 3,436, `app.css` 1,331,
`server.py` 1,016, `generator.py` 574.

## P0. Decisions to make before the spinoff

These are the load-bearing decisions. Everything below assumes them.

### 1. Server-first, retire static-only mode

Today the same HTML is generated twice: once as a server-rendered live page
with ProseMirror, terminals, notes / todos, save endpoints, and SSE; once as
a static file where most of those features are silent no-ops. The split is
visible across the codebase:

- [generator.py](../proseview/generator.py) and [server.py](../proseview/server.py)
  both run `build_dashboard`, with `serve_mode=True` flipping behavior.
- [server.py:49](../proseview/server.py) defines `_extract_script_vars`,
  which recovers JSON the generator just embedded by parsing the HTML it
  wrote. This is a smell. The server should produce JSON directly and the
  template should consume it.
- The terminal tab, agent menu, edit mode, refresh button, notes, and todos
  all check `proseview_has_server` in the template and are dead UI in the
  static build.

Recommendation: drop static-only as a primary mode. Keep `proseview build` as
a one-shot read-only snapshot for CI or sharing, but route every interactive
feature through the server. This removes the dual rendering paths in
`render()` (app.js around line 807), the dual highlight rendering paths
(app.js 762 vs 911), and the conditional UI scattered through the template.

### 2. Make the markdown viewer a real view, not a modal

Right now opening a scene shows a fixed-position modal overlay
(`#modalBody`, app.css around line 435). It is the primary way users read
prose, yet it is implemented as the kind of UI that signals "secondary,
dismissible." The file preview is a separate inline panel. So one click on a
scene opens a modal, one click on a file opens an in-page panel, and the two
do not share scroll, navigation, or selection state.

Recommendation: collapse both into one routed view. The dashboard, the scene
viewer, and the file viewer become three top-level routes, all in the same
content area. Sidebar stays. Modal goes away. URL fragments (already used for
deep links) become the source of truth, with back / forward working.

This also fixes a subtle bug: closing the modal currently destroys the
ProseMirror view; reopening the same scene rebuilds it from scratch
([wysiwyg-scene-editor.md](wysiwyg-scene-editor.md) M2). With a routed view
the editor lifecycle aligns with navigation.

### 3. Unify reading and editing into one ProseMirror surface

The plan in [wysiwyg-scene-editor.md](wysiwyg-scene-editor.md) already
specified this: same surface, `editable: false` for reading, `editable: true`
for editing. The implementation diverged. There is now a `_pmEditMode` flag
flipping a separate edit bar, plus a parallel `marked.parse()` rendering path
for the static / read case. That is what feels stitched together.

Recommendation, paired with item 1: ProseMirror is the only renderer.
Reading is `editable: false` with a visible `Edit` button. Edit mode adds the
save bar, the line gutter, and selection pills. The toggle is visual only;
the document model never changes. Delete the `marked.parse()` branch in
`render()`.

### 4. Decouple from this book repo

These coupling points must move into config or convention before the spinoff:

- `manuscript/` is configurable (`manuscript_path`), good.
- [generator.py:278](../proseview/generator.py) reads `story-bible/characters/` from a
  hardcoded path. Make it a config key (`characters_path`) or a generic
  "named entities" loader.
- [config.py:24](../proseview/config.py) hardcodes `plans, continuity, outline, story-bible,
  docs, templates` as the default repo-tab folders. These are this book's
  folders, not a general novel layout. The default should be empty or
  derived; the README documents the convention.
- Skills directory is hardcoded to `skills/` in
  [generator.py:518](../proseview/generator.py). Make it configurable
  (`skills_path`) and fall back gracefully when absent.
- `.proseview.yaml` location is fine at repo root, but document that it is
  the only required entry point.
- [repo.py:242](../proseview/repo.py) builds the recent-changes card from a hardcoded
  content-folder list. Drive it from config.

A single `proseview init` command that drops a starter `.proseview.yaml` and
writes a short `AGENTS.md` style brief is the right ergonomic for new repos.

## P1. Bugs and rough edges to fix before the spinoff

### 5. Kill the "Pensive 🧠 / Action ⚡ / Balanced ⚖️" label or replace it

In [app.js around line 698](../proseview/templates/assets/app.js), each scene gets a label
based on:

```js
m.energy > 12 ? 'Action ⚡' : (m.energy < 7 ? 'Pensive 🧠' : 'Balanced ⚖️')
```

`energy` is defined in [lexical.py:274](../proseview/lexical.py) as
`10.0 + (dlg_words / words * 5.0) - (avg_sent / 2.0)`. So "Pensive" really
means "low dialogue and long sentences." It pretends to be a mood; it is two
numbers behind a brain emoji. This is what the user means by "very dumb."

Two acceptable fixes:

- Drop the label entirely and surface the underlying numbers (dialogue %,
  avg sentence words) which are already shown in the table.
- Rename to what it actually measures, e.g. "Talky / Mixed / Internal," and
  document the thresholds in a tooltip.

Either way, do not call it Pensive without earning it.

### 6. Remove dead UI and dead code

- `.hl-adverb` styles in [app.css:471](../proseview/templates/assets/app.css)
  with no corresponding pass in `PASS_ORDER`.
- `flavor_words` column in the scene table renders empty because the field
  is computed under a different name in `SceneStats`. Either wire it up or
  drop the column.
- Multiple inline `onclick` handlers in [index.html.j2](../proseview/templates/index.html.j2)
  (lines 58, 74, 79, 87 onwards). Migrate to event delegation when app.js is
  modularized (item 8).
- Stale plan files. [implementation-plan.md](implementation-plan.md) is
  Phase 1; [phase-3-implementation-plan.md](phase-3-implementation-plan.md)
  describes a Codex skill API that does not match the current server. Mark
  them historical or delete them on spinoff.

### 7. Replace the JSON-via-HTML round trip in the server

[server.py:49](../proseview/server.py) parses the HTML to recover JSON for `/data.json`.
The flow should be: generator builds a typed payload, server returns it as
JSON on `/data.json`, template fetches it on load. The HTML stops carrying
duplicate state. This also halves the work `invalidate()` does on every save.

### 8. Modularize app.js

3,436 lines in one global-scoped file is the single biggest risk to anyone
who touches this code six months from now. The split that fits the codebase:

- `state.js` (the global flags currently at the top of app.js)
- `router.js` (URL fragment parsing, view switching)
- `prose/` (ProseMirror setup, schema, annotation node, save / cancel)
- `highlights/` (the nine highlight passes; today they each appear inline)
- `charts/` (presence, rhythm, location, co-occurrence, scatter)
- `panels/` (todos tab, notes tab, file preview, sidebar)
- `terminal.js` (xterm wiring)
- `theme.js` and `font.js`

Adopt vanilla ES modules with `<script type="module">`. No framework needed.
Vite or esbuild is overkill for a single-page dashboard, but if a build step
becomes useful, esbuild produces one bundle and one source map and adds two
config files.

### 9. Cover the unprotected surface with tests

Today's tests cover the analytics engine well and the UI layer not at all.
Before the spinoff, add at least:

- Headless smoke test of the dashboard (Playwright): load, switch tabs, open
  a scene, toggle a highlight, enter edit mode, save, see the scene update.
- ProseMirror round-trip test: parse a scene with TODO and NOTE annotations,
  serialize back, byte-equal except for trailing newline.
- A `/data.json` contract test (replaces the current HTML scraping test in
  `_extract_script_vars`).
- A `proseview build` snapshot test on the demo fixture.

### 10. Vendor the CDN dependencies

[index.html.j2](../proseview/templates/index.html.j2) loads chart.js,
chartjs-plugin-annotation, marked, xterm, xterm/addon-fit, and the
ProseMirror modules from `cdn.jsdelivr.net` and `esm.sh`. This means the
dashboard breaks offline and breaks again the day a major version of any of
these ships an incompatible change. Vendor them under `proseview/templates/vendor/`
or use a thin esbuild step. Pin versions either way.

## P2. Maintainability and developer experience

### 11. Replace the in-house YAML parser with PyYAML

[config.py:253](../proseview/config.py) hand-rolls a partial YAML parser. It works for the
current shape but each new config option pays a tax. PyYAML or `ruamel.yaml`
is one line of `requirements.txt` and removes 50 lines of code.

### 12. Promote `serve` to a proper subcommand

[cli.py:54](../proseview/cli.py) detects `serve` by manually inspecting `argv[0]`. Switch
to `argparse` subcommands: `proseview build`, `proseview serve`, `proseview init`.

### 13. Persist UI preferences

Highlight toggles reset on every scene open
([app.js around line 759](../proseview/templates/assets/app.js)). Theme and font are
persisted; highlights and the issue filter should be too. Single `localStorage`
namespace, single helper.

### 14. Document the frontmatter contract

The scene file shape (`title`, `chapter`, `status`, `where`, `todos`, etc.)
is currently documented only in
[templates/scene.md](../../templates/scene.md) inside the book repo. Move
that contract into the proseview README so a new user knows what the
dashboard reads.

### 15. Repo identity and release plumbing (implemented)

Package identity, MIT license, Python version floor, `pyproject.toml`,
`python -m proseview`, the `proseview` console-script entry point, and
CONTRIBUTING.md now exist. Remaining CI hardening belongs with item 9.

## P3. Features that would actually help

These are bigger than fixes and should land after the spinoff. They are
sorted by how much they help the writer or the AI loop.

### 16. Terminal-driven inline AI proposal bridge

The selection pill UI and embedded terminal are already there. The next AI
step should let Codex run in the terminal, analyze a scene, and send structured
proposals back to Proseview. Proseview highlights the relevant markdown range,
shows replacement options, and applies accepted edits through the existing
ProseMirror save path.

Detailed plan:
[inline-ai-proposal-bridge.md](inline-ai-proposal-bridge.md).

### 17. Diff-confirm for any AI write

When an agent suggests an edit (paragraph polish, scene revision, frontmatter
update), surface a unified diff in the UI before writing. Approve / reject
per hunk. Server already has the atomic write path
(`save_scene_content` in [server.py:101](../proseview/server.py)); add a
`/propose-edit` endpoint that returns a diff and a `/apply-edit` endpoint
that takes the approved hunks.

### 18. Frontmatter editor

`status`, `where`, scene `todos` are the fields the writer changes most
often. Today they are edited by opening the file in VSCode. A small panel in
the scene view that shows frontmatter as a form would replace 80% of those
context switches. The annotation node work in
[wysiwyg-scene-editor.md](wysiwyg-scene-editor.md) is the right model: keep
the markdown source as the source of truth, give it a structured editor.

### 19. Real focus mode

`F` already toggles a focus mode. Today it hides the sidebar and shrinks the
chrome but the modal still feels like a modal. Combined with item 2 (route,
not modal), focus mode becomes "the URL is `/scene/...`, the chrome is
gone, the prose fills the page, the highlights and selection pills still
work." That is the single feature most likely to make the writer open
proseview every morning.

### 20. Search (implemented)

A repo-wide search box that hits prose, frontmatter, todos, and notes, with
the same routing as the rest of the app, would replace another reason to
open VSCode. Cheap to build on top of the JSON payload that already exists
once item 7 lands.

### 21. Continuity surfacing

The book has a `continuity/` folder. Today proseview shows it in the file
tree and nothing else. Two cheap wins:

- Show inline warnings when a scene contradicts a known continuity fact
  (start with simple substring checks; upgrade to AI later).
- Show "facts established in this scene" alongside the scene view, derived
  from continuity files.

This is the kind of feature where the dashboard pays for itself even on a
day with no AI assistance.

## What to do first

If only one weekend is available before the spinoff, do items 1, 2, 3, 5,
and 7. That is: pick server-first, kill the modal in favor of a routed view,
unify reading and editing into one ProseMirror surface, retire the Pensive
label, and stop round-tripping JSON through HTML. Everything else is paid
debt that can ship from the new repo.
