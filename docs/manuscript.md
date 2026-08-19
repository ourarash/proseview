# What Proseview expects of a manuscript

How Proseview finds your scenes, and every frontmatter key it reads.
Everything here is optional — Proseview renders what is there and falls
back gracefully on what is not.

[← back to the README](../README.md)

A Proseview scene is any `.md` file under the manuscript directory, at any
depth. The conventional layout is:

```text
my-novel/
├── manuscript/
│   ├── ch01/
│   │   ├── 01-opening.md
│   │   └── 02-meeting.md
│   └── ch02/
│       └── 01-aftermath.md
└── .proseview.yaml          # optional
```

**Already have a folder of Markdown?** Point Proseview at it. If there is no
`manuscript/` directory, the whole folder is the manuscript — so an Obsidian
vault, a flat pile of chapter files, or any nesting you already use works with
no configuration and no reorganising:

```text
my-vault/                    my-novel/
├── daily.md                 ├── 01-opening.md
├── chapters/                ├── 02-meeting.md
│   └── one.md               └── 03-aftermath.md
└── .obsidian/   (skipped)
```

A file inside the manuscript that is not prose — a `review/` folder, a
per-chapter outline — can opt out with `scene: false` in its frontmatter, so it
stays browsable without counting toward scene or word totals.

Scenes group into chapters by their first folder below the manuscript root, and
a `chapter:` in frontmatter always overrides that. Folders and files are read in
name order. `README.md`, dotfiles, hidden folders, and tool directories such as
`.obsidian/`, `.git/`, and `node_modules/` are never indexed; nor are extensions
other than `.md`. Set `manuscript_path` to point somewhere else, or to `./` to
force the repo root.

Git is optional for the core dashboard, but revision history, goals, streaks,
and recent changes require the root to be a Git worktree.

Scene files use simple frontmatter:

```markdown
---
title: Opening Ledger
chapter: Chapter 1
status: draft
where: River loft
when: Day 1, before opening
pov: Rena
characters:
  - Rena
  - Lowe
goal: Rena needs to clear a weekly ledger before the shop opens
conflict: The safe refuses a code she has used since spring
outcome: She opens the shop in the red
todos:
  - Tighten the opening paragraph
---

# Opening Ledger

The loft smelled of cold coffee and the slow algebra of...
```

Every field is optional. Proseview reads what's there and falls back
gracefully on what isn't. Frontmatter supports simple scalar values and block
lists like the examples above; inline YAML lists are not interpreted as lists.

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

#### Story layer (optional)

- `thread` (string) the storyline a scene belongs to — `present`, `1943`,
  whatever you call them. Scenes sharing a value share a lane in the Timeline
  tab. Up to eight threads render; the rest fold into `other`.
- `day` (number) where the scene sits in story time. Counting up and counting
  down both work — Proseview detects the direction rather than assuming it.
  Scenes sharing a day keep their reading order. `day: "Day 93"` is read as
  `93`.

Both are optional and independent. With neither, the Timeline still shows the
shape of the book; with only `thread`, the lanes appear; with `day` on two or
more scenes, reading order can be compared with story order.

#### Tasks

- `todos` (list of strings) each entry shows up as a frontmatter-level
  TODO in the Tasks panel. Inline `<!-- TODO: ... -->` comments inside
  the prose are picked up too and get a line anchor.

A scene with no frontmatter still renders, just with `Unknown` /
`Not defined` placeholders in the scene card and the file's stem as
its title.
