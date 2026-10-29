# What Proseview expects of a manuscript

How Proseview finds your scenes, and every frontmatter key it reads.
Everything here is optional — Proseview renders what is there and falls
back gracefully on what is not.

[← back to the README](../README.md)

The book lives in one folder, `manuscript/` unless `manuscript_path` says
otherwise. Each folder in it is a chapter, and each `.md` file in a chapter is
a scene:

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

Files sitting directly in the manuscript folder are scenes too, in a chapter
named after the folder. Anything deeper than a chapter folder, such as
`ch02/review/notes.md`, is not a scene: it opens as a file and does
not count toward scenes or words. A scene can also opt out with
`scene: false` in its frontmatter, and a `chapter:` in frontmatter always
overrides the folder name. Folders and files are read in name order.
`README.md`, dotfiles, hidden folders and tool directories such as
`.obsidian/`, `.git/` and `node_modules/` are never scenes.

**No manuscript folder?** Proseview does not guess which files are the book.
It opens the folder as Markdown: you can read, edit and search every file and
ask Codex or Claude about it, and a short message on the dashboard asks where the
book is. **Choose manuscript folder…** writes `manuscript_path` to
`.proseview.yaml`, and the scene counts, Analysis, Timeline, Goals and Export
switch on. Pick a folder, or the whole folder (`manuscript_path: ./`), which
suits a flat pile of chapter files or a vault whose top-level folders are the
chapters:

```text
my-vault/                    my-novel/
├── Chapter 1/               ├── 01-opening.md
│   └── 01-arrival.md        ├── 02-meeting.md
├── Chapter 2/               └── 03-aftermath.md
│   └── 01-rain.md
└── .obsidian/   (skipped)
```

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
  **Word Count per Location** chart.
- `location` (string) synonym for `where` (older convention).
- `when` (string) "When" row in the scene card. Free-form.
- `pov` (string) "POV" row in the scene card. Free-form. A character named
  here counts as in the scene for **Character Presence**.
- `characters` (list of strings) "Characters" row in the scene card;
  each name is clickable to open the bio if
  `<characters_path>/<name>.md` exists. Also decides who is in the scene
  for the **Character Presence** and **Co-occurrence** charts; without it,
  a name in the prose counts.

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

## Callouts: letters, text messages and sidebars

A callout is a box of book text: a letter, a text message, a sign, a
sidebar. It is written as a quotation whose first line names its type,
GitHub's and Obsidian's syntax:

```markdown
> [!letter] A letter, undated
> Mara, if you are reading this, the boat has gone without me.
>
> — T.

> [!sms] Jonah, 11:42 pm
> are you up\
> i think i saw him

> [!WARNING]
> A box with no title.
```

- **The type** is any word of letters, digits and `-` (`letter`, `sms`,
  `note`, `warning`). It is not printed; it picks the box's colour, if you
  give it one.
- **The title** is the rest of the first line. A callout with no title shows
  no heading at all, so `> [!NOTE]` never prints the word "Note".
- **Folding** (`[!note]-` or `[!note]+` in Obsidian) is kept in the file but
  not acted on: callouts always show open, on screen and in print.
- Only a first line of exactly `[!type]` makes a callout. Any other
  quotation stays a quotation.

Callouts are book text, so they print in every export as a framed box (see
[Exporting](export.md)), and their words count. **TODOs and notes are
different**: they are comments (`<!-- TODO: ... -->`, `<!-- NOTE: ... -->`),
shown as small tinted labels while you write, and never printed. Keep private
reminders in comments and anything a reader should see in callouts.

In the scene editor the **Callout** button wraps the paragraph you are in (or
the selected paragraphs) in a callout, or takes the text back out of one.
While editing, the type sits on the box's top edge, where you can change it,
and an empty title line waits for a title.

### Colours

GitHub's five types come with a quiet background in every theme: `note` grey,
`tip` green, `important` violet, `warning` orange and `caution` red, each
chosen to stay clear of that theme's TODO and Note label tints. They colour
the screen only; a book prints them in a plain frame unless you give them a
`print` colour. Any other type has no fill until you give it one.

Any type can have its own background, set under `callouts:` in
`.proseview.yaml`. A type you set there replaces the built-in colours for that
type completely, and `none` takes a colour away. Give one colour for everywhere, or one for each screen
theme, plus `default` for the themes you leave out and `print` for EPUB, PDF
and Word:

```yaml
callouts:
  letter:
    background: "#f7f1e6"        # every theme, and print
  sms:
    background:
      default: "#eef3fb"
      dark: "#16233a"
      graphite-dark: "#232c33"
      # no print key: no colour in the book
  warning:
    background:
      graphite-dark: "#3a2a22"
  note:
    background: none               # no fill anywhere
```

The themes are `light`, `dark`, `docsify`, `hopscotch`, `graphite-light` and
`graphite-dark`. Colours are hex (`#rgb`, `#rrggbb`, or `#rrggbbaa` on
screen); a print colour must be opaque, since Word cannot shade with a
see-through colour. A type with no colour for a theme has no fill there, just
the frame. Nothing is mixed or guessed for you, so pick a dark colour for a
dark theme. Avoid the blue and amber tints of the TODO and Note labels, so a
coloured callout never looks like one.

A book style can set the same `callouts:` block in its `style.yaml`, so a
style of your own can bring its colours; `.proseview.yaml` wins over it,
setting by setting.
