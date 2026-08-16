# Proseview: pre-alpha punch list

**Date:** 2026-08-15
**Scope:** what to fix before recruiting alpha users. Successor to
[public-launch-review.md](public-launch-review.md), reordered around a
correction: the product has one user because it has not been advertised, not
because distribution is broken. Stability comes before reach.

---

## Status, 2026-08-15

Landed: **1** (by you, in `51a53c8`), **2**, **3**, **7** (the 5xx half; the
console-error half also arrived in `51a53c8`), **5**, **8**, **12b**, **13**, **15**, and **16**.

Test counts moved from 280 unit / 164 browser to **337 unit / 167 browser**
(plus 47 in the stdlib HTTP tier).

### The headline: the dashboard rebuild is 75% faster

Measured on a real working manuscript — 48 scenes, 62k words:

| | Start of day | Now |
| --- | --- | --- |
| Server rebuild, paid after every save | 1690 ms | **418 ms** |
| Analysis tab, first open | n/a | 839 ms |
| Analysis tab, reopened | n/a | 32 ms |

Three changes got there: removing a duplicate manuscript index (item 13),
moving the MATTR/MTLD pass behind an on-demand Analysis tab (item 16), and
deleting the dead computation both left behind.

### Still open

The page is still ~2.9 MB, which measurement showed does not matter (item 13).
Item 15 is now done too: browser-side load went from ~600 ms to 124 ms and the
page makes no external requests at all. Item 17 records the next structural
win; item 14 records three load-sensitive tests worth pinning down.

---

## P0 — before inviting anyone

### 1. Land the in-flight Discuss work — DONE

`HEAD` is green (280 unit/integration tests). The working tree is not:
`test_selection_action_queues_while_thread_history_is_still_restoring`
([tests/test_discuss_manager.py:1275](../tests/test_discuss_manager.py#L1275))
fails deterministically, 5/5 runs, on a thread-join timeout. It is new work,
not a shipped regression. Finish it or revert it before it gets buried under
the next feature.

**Effort:** unknown, it is your branch.

### 2. Atomic writes on TODO/NOTE mutations — DONE (mtime guard still open)

All six mutators now route through `_atomic_write_text`, the same tmp-file and
`os.replace` pattern `save_scene_content` uses; the refactor also removed the
duplication between the TODO and NOTE variants. `tests/test_annotations.py`
covers it — these six functions previously had no unit tests at all.

**Still open:** the mtime guard. The client does not send `open_mtime` on these
calls, so wiring it up means a frontend change as well.

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

### 3. Fail loudly when annotation targeting misses — DONE

The `para_idx = 0` fallback is gone: a selection that no longer matches now
raises, and the client's existing error path surfaces it. Covered in
`tests/test_annotations.py` and by a browser regression test.

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

### 5. Read any folder of Markdown — DONE

`iter_scene_paths` required a two-level `manuscript/<dir>/*.md` tree, so an
Obsidian user pointing at a vault got an empty dashboard and no explanation.
Scenes are now any `.md` at any depth, and `resolve_manuscript_dir` falls back
to the repo root when there is no `manuscript/` directory — which is what makes
"point it at your vault" true rather than aspirational.

Chapters group by the first folder below the manuscript root, so the
conventional layout groups exactly as before and a deeper `ch01/drafts/02.md`
stays with its chapter. Hidden and tool directories (`.obsidian`, `.git`,
`node_modules`) are skipped, so pointing at a repo root does not sweep them in.

**The assumption was in four places, not one.** Discovery was the visible one;
the other three failed silently:

| Where | Symptom in a vault |
| --- | --- |
| `save_scene_content` | **Every save rejected** as "outside the manuscript directory" — the app was read-only, and only reading looked fine |
| `history.py` git pathspecs | `-- manuscript/` matched nothing, so history, Goals, streaks, and the word-count delta all quietly reported zero |
| `stats_for_commit` | `len(parts) >= 3` — the same two-level rule, applied to git history |
| `export.py` | Wrong directory, and chapters from `path.parent.name` |

Found by running a real vault against the real server rather than reasoning
about it. `tests/test_layouts.py` covers all of them.

**Effort:** ~half a day, against the 3–5 days originally estimated — the
reframing to "render any `.md`, degrade what does not apply" was right.

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

### 16. Overview and Analysis are separate tabs — DONE

The Overview tab priced out at 611 ms of its 1070 ms build being lexical and
style analysis that the tab you actually use does not read. It is now split:

- **Overview** (still the default): Goals, Recently Changed, Character
  Presence, Setting Stickiness, Co-Occurrence, and a four-column scene table.
  Everything here comes from frontmatter and word counts.
- **Analysis** (new): Editorial Alerts, Book-Wide Lexical Health, Rhythm &
  Pacing, Lexical Health Map, and the full eight-column table with its metric
  filters. Fetched from `/analysis.json` on first open, cached server-side
  against the same file-watch invalidation as the HTML, and routable at
  `#/tab/analysis`.

**One correction worth keeping.** The first cut skipped both the lexical *and*
style passes, and the browser tier immediately went red on three highlight
tests: [generator.py:297](../proseview/generator.py#L297) wires the `repeats`
reading-view highlight to `scene.repetition_examples`, and the scene modal's
stat grid reads the style fields. That would have shipped a silently degraded
reading view — no error, just an empty highlight pass and a grid of zeros.

`collect_scene_stats(lexical=False)` now skips **only** MATTR/MTLD, which
nothing outside the Analysis tab reads. The style pass always runs.

The e2e suite caught this, which is the argument for item 7 in one line.

### 17. Defer the style pass per scene

`analyze_style_shape` is ~385 ms of the remaining 418 ms build, and it still
runs for every scene on every rebuild because the reading view needs it — the
stat grid and the `repeats` highlight, both per-scene.

Computing it for the one scene being opened rather than all of them is the next
structural win, and it would take the rebuild close to the ~26 ms that a
metadata-only scan costs. Bigger job than item 16: the scene modal and
`build_scene_data` both assume the fields are already populated.

### 12b. An empty scene file crashes the whole dashboard — DONE

`analyze_style_shape("")` raises `ZeroDivisionError` at
[lexical.py:274](../proseview/lexical.py#L274) — `dlg_words / words` with no
guard on `words == 0`. Empty, whitespace-only, and frontmatter-only scenes all
hit it, and because the analysis runs for every scene on every build, one blank
file takes down the entire dashboard rather than that one scene.

Today you would have to create a blank scene to hit it. After item 5 it becomes
routine: any real Obsidian vault contains empty notes.

Fixed: the dialogue share is now guarded the same way the neighbouring
`dialogue_pct` on the next line always was.

### 13. Build cost and page weight at book length — PARTLY DONE

Measured against a real working manuscript: 48 scenes, 62k words.

**Fixed.** `build_dashboard` indexed the manuscript twice — once directly, and
once inside `working_copy_delta`, which wanted nothing but the word total. The
second pass ran the full lexical analysis of every scene and threw it away.
Passing the already-computed scenes through took the real book from **1.69s to
1.08s (-36%)**. `tests/test_scale.py` guards it; the guard is only meaningful
against a git repo, because the duplicate sat behind `is_git_repo`.

That gate is also why the synthetic fixture looked *faster* than the real book
despite having six times the scenes — it is not a git repo, so it never paid
the duplicate.

**Page weight turned out not to matter — do not fix it.** Measured end to end
on the real book, the 3.04 MB page costs 8 ms to download over loopback and
3 ms to `JSON.parse` (contents 1 ms, highlights 2 ms). Deferring both blobs to
a lazy fetch would save about **3 ms** while adding a load-order race. The
earlier "inlined manuscript is the likely cause of slowness" call was wrong;
it reasoned about bytes without measuring a local server, where transfer is
free.

Recorded for scale awareness only:

| Measure | Value |
| --- | --- |
| Manuscript on disk | 0.66 MB |
| Dashboard HTML | 3.97 MB (**6.0x**) |
| Largest single script | 3.06 MB |
| `build_dashboard` | 1.43 s |
| Scaling | 2.9x time for 3x scenes — linear, no hidden O(n²) |

The whole manuscript is inlined into the page as a JSON string literal
(`let contents = JSON.parse('…')`), and JSON escaping inflates it roughly 4.5x
over the bytes on disk. The browser downloads and parses all of it on every
load — and again on every live reload.

The real book measures 7.2x (0.42 MB on disk to 3.04 MB of page). Note that
`highlightsByPath` (0.94 MB) is the largest blob, not `contents` (0.36 MB).
`tests/test_scale.py` pins the ratio at 8.0x so it cannot quietly get worse.

### Where the time actually goes

On the real book, a page load costs **~1.7 s** when the dashboard is stale,
which during a writing session is after every save:

| Stage | Cost |
| --- | --- |
| Server regenerates the dashboard | ~1080 ms (was 1690 ms) |
| Request to first byte, cached | 3 ms |
| Download 3.04 MB over loopback | 8 ms |
| Browser DOM parse + scripts | 581 ms |
| — of which `JSON.parse` of both data blobs | 3 ms |
| — of which ProseMirror from esm.sh | ~170 ms (see item 15) |

The two real targets are the server rebuild and the CDN fetch. Bytes are not a
target at all.

Remaining server-side cost is dominated by `analyze_style_shape` (~42k
`re.findall` calls per build) and the git subprocesses in `working_copy_delta`.
The bigger structural win is to re-analyse only the scenes that changed instead
of the whole manuscript on every invalidation.

### 15. ProseMirror is fetched from a CDN on every load — DONE

Vendored under `templates/vendor/pm/` and served from the app's own origin.
Browser-side load on the real book went from **600 ms to 124 ms**, and the page
now issues **zero external requests**.

The win was far larger than the ~170 ms estimated, because the seven CDN
imports resolved as a *serial* dependency chain rather than in parallel.

The old objection in the template — that vendoring needs a build step — was
worth taking seriously and turned out not to hold.
[scripts/vendor_prosemirror.py](../scripts/vendor_prosemirror.py) walks the
esm.sh graph, downloads all 36 reachable modules, and rewrites the import
specifiers to point at each other on disk. No bundler, no build step; run it to
change versions and commit what it writes. Shared packages dedupe by resolved
URL, so there is exactly one `prosemirror-model` and `Schema` identity holds.

Two consequences worth knowing:

- **36 module requests per page load.** Free for a real user after the first
  visit, but in the browser tier every test gets a fresh context, and the extra
  round trips against a thread-per-request server were enough to lose timing
  races elsewhere. `_install_esm_cache` — which used to cache esm.sh and became
  dead the moment the CDN went away — now caches `/vendor/pm/*` in-process
  instead. The tier runs in 108 s, slightly faster than before this work.
- `tests/e2e/_esm_cache/` and the `PROSEVIEW_ESM_OFFLINE` CI flag are gone; the
  browser tier needs no network at all now.


### 14. Load-sensitive tests

`test_new_conversation_clears_projection_and_uses_a_new_thread` failed once in
roughly ten full-suite runs and has not reproduced since — 3/3 isolated, 6/6
full-suite. Timing-sensitive, like its neighbours in that file, which
coordinate real threads.

Two browser tests behave the same way. Under heavy machine load,
`test_proposal_review_fits_beside_dock_at_200_percent_zoom` and
`test_selection_action_started_from_dirty_editor_uses_live_target` each failed
once, both passing 3/3 alone and in repeated clean full runs. They sit in the
same cluster: selection actions driving the AI proposal panel.

Not urgent, but this is three tests in two tiers that pass or fail on machine
load, and flaky tests are how a suite stops being believed. Worth pinning down
before CI becomes the thing you trust for Windows (item 4).

### 14a. Original note

`test_new_conversation_clears_projection_and_uses_a_new_thread` failed once in
roughly ten full-suite runs and has not reproduced since — 3/3 isolated, 6/6
full-suite. Timing-sensitive, like its neighbours in that file, which
coordinate real threads.

Not urgent, but flaky tests are how a suite stops being believed, and this one
is in the tier that guards a headline feature. Worth pinning down before CI
becomes the thing you trust for Windows (item 4).

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
