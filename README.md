# Proseview

**A writing studio for novels in plain Markdown.**

[![CI](https://github.com/ourarash/proseview/actions/workflows/ci.yml/badge.svg)](https://github.com/ourarash/proseview/actions/workflows/ci.yml)
![status](https://img.shields.io/badge/status-alpha-orange)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)

[Website](https://ourarash.github.io/proseview/) ·
[Try a sample book](https://ourarash.github.io/proseview/demo/#/scene/ch01%2F01-down-the-rabbit-hole.md) ·
[Start a book in your browser](https://ourarash.github.io/proseview/write/) ·
[Quick start](#quick-start)

Proseview turns a folder of Markdown scenes into a place to write a book. Read
and edit each scene on a typeset page, read the whole manuscript from start to
finish, revise with prose analysis, and export an e-book, a print-ready PDF or
a Word document. Your files stay plain `.md` where they are, so Proseview works
alongside Obsidian, VS Code, Vim, git or any other tool, and a save changes
only what you edited.

Everything runs on your computer: no account, subscription, database or
telemetry. Asking an AI is optional and goes through the Codex or Claude you
already use.

```bash
pipx install "proseview[claude]"
proseview --root /path/to/your/novel
```

![The Proseview dashboard with the file sidebar open on chapter one's scenes: a Progress card with the words against the goal, today's words, words a day, the writing streak, words per chapter and days to finish, above the scene list](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/dashboard.png)

**Try it first.** The [sample book](https://ourarash.github.io/proseview/demo/#/scene/ch01%2F01-down-the-rabbit-hole.md)
is the dashboard for *Alice's Adventures in Wonderland*, in your browser: read,
search, open the analysis, edit a scene and export it. [Start a book in your
browser](https://ourarash.github.io/proseview/write/) runs Proseview itself
with nothing to install; the book stays in that browser, and you can download
it as a folder to carry on in the installed app.

## Features

### Write

- **A typeset page that is also the editor.** Press `E` to edit the page you
  are reading; `Mod-S` saves and returns to reading. A save rewrites only the
  paragraphs you changed, and a conflict guard never overwrites a change made
  in another editor.
- **Read the book.** The whole manuscript as one continuous text, or page by
  page exactly as Export will print it, and it reopens where you stopped.
- **Every Markdown file.** Story bible, plans and notes open and edit the same
  way, with backups. Obsidian wikilinks, callouts and embeds stay as written.
- **Files and search.** Create, rename and move files from the sidebar;
  `Mod-K` searches paths, metadata, TODOs, notes and prose from anywhere.
- **Live reload and deep links.** Save in your own editor and the page
  follows. Every scene has a URL. Six themes and seven fonts.
- **Privacy screen.** Hold `Mod` and tap `J` twice (`Mod-J J`) to cover the
  page with a plain budget spreadsheet; do it again to uncover it, with your
  edit, caret and scroll as you left them.
  [Optional password →](docs/configuration.md#privacy-screen-password)

### Revise

- **Dashboard.** A Progress card for the book against its goal, with today's
  words, pace, writing streak and days to finish, and **What changed**: the
  words written and cut in each scene. Below it, the scenes you worked on last
  and the scene list.
- **Analysis.** Opens with what stands out, in plain sentences that name the
  scenes, then who is in each chapter, words by place and word variety. Every
  figure has an ⓘ that says what it measures.
  [What the numbers mean →](docs/analytics.md)
- **Editorial highlights.** Nine prose passes marked on the page, each with
  its match count: repetition, passive voice, filter verbs, crutch words,
  hyperbole, lyrical reach, sensory density, repeated sentence openings and
  first-person slips.
- **Timeline.** The shape of the book, storylines as lanes, and reading order
  against the order events happen.
- **TODOs and notes.** Select a passage and add a `TODO` or a tagged `NOTE`;
  it is saved in the file as a Markdown comment, and the Tasks tab lists them
  all.
- **File history.** Earlier versions of a scene, restored through a diff you
  can read first.

### Publish

- **EPUB, PDF and Word.** Export the whole book, a chapter, a scene or any mix
  as a styled e-book, a print-ready paperback interior (5 × 8 to 6 × 9 in, or
  A5), a PDF to share, or a Word document for an editor's tracked changes, in
  four styles including standard manuscript format. Preview the pages first,
  and get a plain-language check that the book is ready for the stores.
  [Export guide →](docs/export.md)
- **A read-only copy to share.** `proseview snapshot` writes the dashboard as
  a static site for beta readers. [Details →](#share-a-read-only-copy)

### Ask an agent (optional)

Proseview has no model and needs no API key. It drives the Codex and Claude
command-line tools already signed in on your computer, one tab each in the side
panel, each with its own conversation about the project. An agent sees the file
you have open, your selection and any file you `@`mention, and reads the rest of
the project itself, as it does in the VS Code extensions. Claude uses your own
Claude settings (permissions, `CLAUDE.md`, skills, MCP servers); Codex asks
before running a command that would change something.

An edit an agent makes is saved and summarised in a card with the diff,
**Undo all** and **Looks good**. Reading passes such as Quick critique make no
edits, and continuity questions come back with citations. Nothing runs until
you ask. [How the AI features work →](docs/ai.md)

## Screenshots

### Editorial passes

Each prose pass shows its match count for the scene; switching one on marks
the page you are reading.

![The Analysis panel open beside a scene, with four highlight passes switched on from their rows and the matching words marked in the prose](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/demo-highlights.gif)

### Editing

`Edit` turns the page you were reading into the page you type into, with the
same typography. `Mod-S` saves the file and returns to reading. A scene's
frontmatter sits above its prose as YAML you can edit, and a typo that is not
valid YAML is pointed out rather than saved.

![Typing a new closing line into a scene and saving it with Mod-S, with the word count updating](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/demo-writing.gif)

### Read the book

The whole manuscript as one continuous text, with a quiet bar for progress,
scene and chapter skips and a chapter list. **Print layout** shows the same
book as Export lays it out, page by page, in your chosen style and trim.

![Read the book: the opening of the demo manuscript as one continuous text, with the progress and chapter bar along the bottom](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/read-the-book.png)

### Analysis

![The Analysis tab: What stands out, in plain sentences that name the scenes, above a chart of how many scenes each character is in, chapter by chapter](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/analytics.png)

### Timeline

Chapter proportions, words per scene, storylines as lanes, and reading order
against the order events happen, so a scene read far from where it happens is
easy to spot.

![The Timeline tab showing chapter proportion, words per scene, three storyline lanes, and reading order against story order, with a scene card on hover](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/demo-timeline.gif)

### Agents

Codex and Claude each keep their own conversation. Opening another file does
not reset either one; the next question simply says which file you are in.

![The Codex and Claude tabs answering the same question about a scene in separate conversations, with each answer staying in its own tab](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/demo-agents.gif)

### Search

![The search palette open over a scene, showing file, scene, and prose matches grouped by kind](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/demo-search.gif)

### Export

Choose the format and style, then see the pages exactly as the file will be.

![The Export dialog's second step: format cards for E-book, Print book, Shareable PDF and All formats, the print book's trim size and right-hand chapter option, and thumbnails of the Classic, Modern and Romance styles](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/export-formats.png)

![The Export dialog's third step: title, author and cover beside a preview of the print book showing two facing pages with running heads and page numbers](https://raw.githubusercontent.com/ourarash/proseview/main/docs/images/export-preview.png)

The screenshots use the bundled demo manuscript, *Alice's Adventures in
Wonderland* (public domain), split into 39 scenes across 12 chapters. See
[fixtures/demo-book](fixtures/demo-book/README.md).

## Quick start

Requires Python 3.11+ on macOS, Linux or Windows.

```bash
pipx install "proseview[claude]"
proseview --root /path/to/your/novel
```

A browser tab opens at `http://localhost:7842`; press Ctrl-C to stop. The
`[claude]` extra adds what the Claude tab needs; leave it off if you will not
use Claude.

Proseview's book features read a `manuscript/` folder with one folder per
chapter and one Markdown file per scene. Frontmatter is optional. Point it at a
folder without a manuscript, such as an Obsidian vault, and it opens as plain
Markdown you can read, edit and search; **Choose manuscript folder…** tells it
where the book is.

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

[Layout and frontmatter →](docs/manuscript.md)

### Share a read-only copy

```bash
proseview snapshot --root /path/to/your/novel --out ~/my-novel-site
```

This writes the dashboard as static files any web host can serve, including
GitHub Pages. Readers can browse scenes, search and read the analysis; nothing
on it edits and no server runs, and paths from your computer are replaced by
the folder's name. `--demo` also lets visitors try editing (saved only in their
browser) and download ready-made EPUB, PDF and Word files. `--title`,
`--site-url` and `--preview-image` set how a link to it looks when shared.

## Configuration

Proseview needs no config file. A `.proseview.yaml` at the root of the book can
change where things live, set word goals, choose which agent tab opens first,
or point the Timeline at your own frontmatter keys; `proseview init` writes a
starter file. Goals, genre and colour theme can also be changed in Settings,
behind the gear in the header.

```yaml
manuscript_path: manuscript/
target_words: 80000
discuss:
  agent: codex
```

[Every key, with defaults →](docs/configuration.md)

## Documentation

- [Manuscript layout and frontmatter](docs/manuscript.md)
- [Configuration reference](docs/configuration.md)
- [Working with AI](docs/ai.md)
- [What the numbers mean](docs/analytics.md)
- [Exporting: EPUB, PDF and Word](docs/export.md)

## Status

Proseview is alpha: everything described above works today. Still unfinished:

- The `$` skill picker on the Claude tab lists only Codex's skills; Claude
  still uses your Claude skills on its own.
- Read the book does not yet update live when a scene changes on disk.

The full list is in [plans/roadmap.md](plans/roadmap.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```

This runs over a thousand unit tests and an HTTP end-to-end tier that starts a
real `proseview` process and checks what reaches the disk: saves and the
conflict guard, TODOs and notes, the agent bridge and live reload. Agent tests
use a deterministic fake and never contact Codex, Claude or the network.

A browser tier drives the real interface in Chromium:

```bash
pip install -e ".[e2e]"
python -m playwright install chromium
pytest -m e2e_browser
```

Both tiers work on a throwaway copy of `fixtures/demo-repo`. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
