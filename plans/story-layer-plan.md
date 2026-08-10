# Plan: story-layer analysis

**Date:** 2026-08-10
**Scope:** two features that read the structured frontmatter Proseview already
collects but barely uses — a chronology view, and a revision queue that tells
the writer what to do next.

---

## What the data actually looks like

Measured against `~/github/book` (48 scenes), because the design depends on it:

| Field | Coverage | Shape |
| --- | --- | --- |
| `chapter`, `title`, `status` | 97% | short strings |
| `when` | 97% | **relative prose**: "Same night, later", "Several weeks later, late October" |
| `where` | 97% | free-form place names |
| `pov` | 97% | **single POV** — Nima in 47/48 scenes |
| `characters`, `goal`, `conflict`, `outcome` | 97% | lists / sentences |

Two findings that killed earlier ideas:

- **`when` cannot be sorted.** 46 distinct values, all relative phrases. Any
  design that assumes a sortable date is dead on arrival.
- **POV balance is not a feature here.** One narrator. Build it and it renders
  a single flat line.

Both features below are designed around reading order, which is the only
ordering the data actually supports.

---

## Feature 1 — Chronology strip

### What it answers

"How much story time passes, where, and where are the jumps?" Today that
requires opening 48 files.

In this manuscript, chapter 1 is six scenes across **one night**; chapter 2
covers **a semester**. Nothing in Proseview shows that, and it is the kind of
pacing fact a writer revises on.

### Design: one row per scene

A `Timeline` tab beside Overview / TODOs / Notes. One row per scene **in
reading order** — never sorted by `when`:

```text
CHAPTER 1                                       6 scenes · 6,180 words
  Late night                  Underground strip club        1,240 w  draft
  Same night, near closing    strip club, moving              890 w  draft
  Same night, after leaving   Street and riverwalk          1,100 w  revision
  …

CHAPTER 2                                       7 scenes · 8,940 words
  Early fall, first semester  University swim club          1,430 w  draft
```

Each row: `when` verbatim, `where`, word count, status chip — grouped under a
chapter header carrying the chapter's totals. No inference, no glyphs. The
jump from "Same night" to "Early fall" is visible because the writer's own
words are adjacent.

### Time-gap classification: measured, then cut

The first design classified each transition as continuous / short gap / long
gap by pattern-matching `when`. **Two rounds of patterns were tested against
all 48 scenes:**

| Attempt | Classified |
| --- | --- |
| Prefix matching on common phrases | 37% |
| 11 regex rules covering "next day", "N days after", "morning after", season names | **47%** |

The remaining tail is not a tuning problem. It is prose:

> "That same night / early morning" · "Near the end of the party" ·
> "Hours after the assault, before lunch with Amir and Babak" ·
> "Thursday lunch hour"

**Decision: v1 ships no classifier.** Show `when` verbatim, in reading order,
grouped by chapter. The reader classifies these effortlessly by eye — six rows
reading "Same night…" followed by "Early fall" *is* the jump, rendered. A 47%
classifier adds a guessing failure mode to a view whose whole value is showing
the writer's own words back to them.

Recorded here so a future attempt does not repeat the measurement. If it is
revisited, the bar is: mark only high-confidence transitions, leave everything
else visually neutral, and never label a phrase "unknown" in the UI — a
writer's phrasing is not a data-entry error.

### Derived summary, per chapter

- scenes, words, and the span of `when` values from first to last
- distinct `where` values (a chapter that never leaves one room is a fact worth
  seeing)

### Explicitly not in scope

- Sorting or normalising `when` into dates
- A calendar or Gantt rendering
- POV lanes

### Work: chronology strip

| Step | Where |
| --- | --- |
| `story.py`: `TimelineRow`, `chapter_summary` | new module |
| Feed `SceneStats.fm` into the rows | `scenes.py` already carries frontmatter |
| Tab + table rendering | `generator.py`, `index.html.j2` |
| Unit tests: ordering, chapter grouping, missing `when`/`where` | `tests/test_story.py` |

Roughly a day. No new dependencies.

---

## Feature 2 — Revision queue

### The problem with today's alerts

`revision_signal()` is the best thing in the product and it is nearly right.
It already composes real sentences:

> repetition is probably showing at both levels. paragraphing is unusually
> staccato. watch: mug/mugsx3, openx3

Three gaps:

1. **It fires only on lexical outliers.** `scene_is_outlier` tests MATTR and
   MTLD only, so a scene with no `conflict`, a stale `status: draft` from four
   months ago, or five open TODOs is invisible.
2. **It diagnoses, it does not prescribe.** "Repetition is probably showing"
   tells the writer what is true, not what to do next.
3. **It has no queue.** Alerts are ranked by `scene_severity`, which sums
   lexical distance only. There is no single "start here" answer.

### Design: one ranked list

One ranked list on the dashboard: **"Next up"** — the five scenes most worth
opening, each with a reason and an action.

```text
1. ch05/03-patels-offer.md          score 8.2
   No conflict recorded, and 3 open TODOs.
   → Open the scene card and fill in conflict, or clear the TODOs.

2. ch02/01-argument.md              score 6.1
   Repetition at both levels; watch: three×5, paper×4.
   → Read with Repeats and Crutch Words on.
```

Each entry links straight into the scene view, with the relevant highlight
passes pre-enabled where that is the action.

### Signals to score

Lexical signals stay as they are. New structural signals, all from data that
already exists:

| Signal | Evidence | Suggested action |
| --- | --- | --- |
| Missing `conflict` or `goal` | frontmatter | fill in the scene card |
| `status: draft` untouched for N days | git mtime (already read for Recent Changes) | revise or mark done |
| Open TODOs / notes | already parsed by `scan_todos` / `scan_notes` | clear them |
| Character in `characters` with no bio | `story-bible/characters/` | write the bio |
| Chapter with no long gap and no location change | timeline data from Feature 1 | check pacing |

### Scoring

Keep it explainable. Every contributing signal is a weighted term, and the UI
**shows the terms**, not just the total. A writer who disagrees with the rank
should be able to see exactly why. Weights live in `.proseview.yaml` so they
can be tuned without editing code.

Never invent urgency: if nothing scores above a floor, the panel says the
manuscript looks fine rather than manufacturing five entries.

### Work: revision queue

| Step | Where |
| --- | --- |
| `structural_signals(scene, cfg, repo_state)` returning `(weight, reason, action)` | `story.py` |
| Merge with lexical severity into one ranked queue | `scenes.py` / `story.py` |
| "Next up" panel, above the charts | `generator.py`, `index.html.j2` |
| Deep link that opens a scene with passes pre-enabled | `15-search.js` pattern already does this |
| Tests per signal, plus the empty case | `tests/test_story.py` |

Roughly two days, most of it in scoring and copy.

---

## Order

Build the **chronology strip first**. It is smaller, it is visible immediately,
and it produces the chapter-level data the revision queue's pacing signal
needs. If it turns out you never open it, that is a cheap answer and a reason
not to build the second one.

## The honest risk

Both features are only as good as the frontmatter. Yours is 97% complete
because you maintain it by hand. A user who leaves `conflict` blank gets a
revision queue that nags about blank fields.

Mitigation: signals for *missing* data only fire when that field is populated
somewhere else in the manuscript. If a writer never uses `conflict`, Proseview
must not treat its absence as a defect.
