# Proseview: pre-alpha punch list

**Date:** 2026-08-15
**Scope:** what to fix before recruiting alpha users. Successor to
[public-launch-review.md](public-launch-review.md), reordered around a
correction: the product has one user because it has not been advertised, not
because distribution is broken. Stability comes before reach.

---

## P0 — before inviting anyone

### 1. Land the in-flight Discuss work

`HEAD` is green (280 unit/integration tests). The working tree is not:
`test_selection_action_queues_while_thread_history_is_still_restoring`
([tests/test_discuss_manager.py:1275](../tests/test_discuss_manager.py#L1275))
fails deterministically, 5/5 runs, on a thread-join timeout. It is new work,
not a shipped regression. Finish it or revert it before it gets buried under
the next feature.

**Effort:** unknown, it is your branch.

### 2. Atomic writes + mtime guard on TODO/NOTE mutations

Scene save is correct: mtime conflict check, then tmp file and `os.replace`
([proseview/server.py:452-491](../proseview/server.py#L452-L491)).

The six annotation mutators are not. `add_todo`, `edit_todo`, `delete_todo`,
`add_note`, `edit_note`, `delete_note` all write with a bare `path.write_text`
([727](../proseview/server.py#L727), [742](../proseview/server.py#L742),
[772](../proseview/server.py#L772), [818](../proseview/server.py#L818), and
the two note paths below). Interrupt one mid-write and the scene is
truncated. None of them checks mtime, so a concurrent edit in Obsidian or Vim
goes undetected.

Reuse the `save_scene` pattern. It is already written.

**Effort:** ~1 day.

### 3. Fail loudly when annotation targeting misses

`add_todo` and `add_note` locate the paragraph by the selection's first 50
characters. When that string is not found they fall back to `para_idx = 0`
([proseview/server.py:702-706](../proseview/server.py#L702-L706), mirrored in
`add_note`) and insert at the top of the scene with no error.

This fires exactly when the writer changed the paragraph since the page
loaded. It is not a crash; it is quiet wrongness inside their manuscript, and
it is the single most likely reason an alpha user stops trusting the tool.

Return an error instead. Same for `edit_todo` / `delete_todo`, which match on
comment text with `replace(..., 1)` and so hit the wrong one when two
identical TODOs exist.

**Effort:** ~2 hours.

### 4. Windows support, with Windows CI

`import fcntl` at [proseview/server.py:12](../proseview/server.py#L12) is
unconditional, so Windows fails at import, not merely at the terminal. Guard
it, disable the terminal tab on Windows, and add Windows to CI — without the
CI leg it silently rots.

Ship the basic version. A working Windows terminal needs ConPTY and is a
separate week; label the terminal Unix-only until then.

**Effort:** 1–2 days basic.

### 5. Read any folder of Markdown

`iter_scene_paths` requires a two-level `manuscript/<dir>/*.md` tree
([proseview/scenes.py:243](../proseview/scenes.py#L243)). The README positions
Proseview as a companion to Obsidian and Longform, but an Obsidian user who
installs it today points it at a vault and sees an empty dashboard.

Support flat directories, arbitrary nesting, and vault layouts.

**Effort:** 3–5 days.

### 6. Conditional: performance on a real manuscript

Open question. If the app is genuinely sluggish against a full book rather
than the 4-scene fixture, this is P0 and outranks everything above — a slow
tool loses alpha users faster than a buggy one. If the slowness is only in
how long self-dogfooding takes to surface bugs, ignore this item.

---

## P1 — during the alpha

### 7. Instrument the e2e tier, then add a random walker

Before any AI is involved, make an e2e run fail on any `console.error`,
unhandled rejection, HTTP 5xx, or unexpected `ok: false` response. Then walk
the UI randomly. This is a monkey test: no model, deterministic, CI-friendly,
and it will surface real bugs immediately.

**Effort:** ~2 days.

### 8. A manuscript-sized fixture

`fixtures/demo-repo` is four scenes. The interesting bugs — chart rendering,
search ranking, pagination, the paragraph matching in item 3 — live at 80k
words and 300 scenes. Extend the existing `LARGE_SCENE_REL` generator into a
full book.

**Effort:** ~1 day.

### 9. Green browser tier in CI, all platforms

137 browser tests exist. Confirm they pass on macOS, Linux, and Windows before
advertising anywhere.

### 10. Benchmarked analytics

"Your MTLD versus published literary fiction." This is AutoCrit's entire moat
and the reason someone picks Proseview over novelWriter. Everything else on
these lists is table stakes; this is the differentiator. Deferred behind
stability, not behind features.

**Effort:** 5–8 days.

### 11. Discuss beyond Codex

A headline feature bet on one vendor's CLI. The seam is already named
([proseview/discuss.py:793](../proseview/discuss.py#L793)). Claude Code CLI at
minimum.

**Effort:** 5–8 days.

### 12. docx and PDF export

The same pandoc call as EPUB with a different writer, plus a PDF engine.
Writers send `.docx` to editors.

**Effort:** ~1 day.

---

## P2 — later, or never

- **Goal-driven AI exploratory agent.** Worth building *after* item 7, for the
  journeys a random walker cannot reach. Two rules: every finding ships with
  its action sequence or a Playwright trace, and findings go to a file you
  review, never straight to the issue tracker.
- **Live demo on GitHub Pages, README GIF.** Both cheap and both real, but
  they are reach, and reach is not the current bottleneck.
- **VSCode extension** (8–12 d). Serves developers who write fiction — the one
  audience already unblocked by `pipx install`. Build only if alpha users ask.
- **Electron app** (20–30 d, plus signing and notarization costs). The
  eventual path to novelists without a terminal, and the most expensive thing
  on any of these lists. A double-clickable PyInstaller binary (~4 d) buys most
  of it first.

## Explicitly rejected

**AI-generated feature requests.** An agent has no manuscript, no stake, and
no memory of last week. It proposes what writing tools generally have, not
what your users need. High volume, low signal, and you are the only person
triaging.

**Alpha users are not replaceable by any of this.** No synthetic tester
produces the sentence "I stopped opening it after week two, because…", which
is the only sentence that tells you whether the product is worth building. You
need about five people. Items 4 and 5 gate recruiting them: before those land,
most candidates bounce at install.
