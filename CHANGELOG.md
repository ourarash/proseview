# Changelog

Notable changes in each Proseview release. When a version is tagged, its
section here becomes the release notes on GitHub.

## Unreleased

### Changed

- A note with a table opens in the rich editor. The table shows as a table
  and is saved exactly as written; change it in your text editor. A table
  inside a list or quote still opens the note as plain Markdown.

## 0.4.1 — 2026-10-08

### Added

- **Preview a scene as a PDF**: press `P` in the scene view, or choose
  *Preview as PDF…* from its More menu, to open Export on the shareable-PDF
  preview of just that scene.
- The file browser lists images and other files beside the scenes. Images
  show in the file view, text files open read-only, and anything else says
  Proseview cannot open it. None of them count as scenes or go into an export.
- Pressing `E` on a file that cannot be edited, such as an image, says why
  in a short note instead of doing nothing.

### Fixed

- Creating, renaming or deleting in the file browser no longer closes every
  open folder.
- Codex's notice about unknown requirements set by a managed account
  ("Ignoring unknown `features` requirement …") goes to the terminal once
  instead of appearing in the dock on every conversation.

## 0.4.0 — 2026-10-08

### Added

- **Edit notes in the file view**: story-bible pages, plans, and any other
  Markdown file in the book now have an `Edit` button (or press `E`), with `Mod-S`,
  backups, and the same changed-on-disk check as scenes (keep your version,
  or discard it and reload). Frontmatter is kept exactly, and a note with a
  table or raw HTML is edited as plain Markdown so nothing in it is lost.
  Only existing `.md` files inside the book can be saved this way: hidden and
  tooling folders and symlinks are refused. In `--demo`, saves stay in the
  tab. A read-only copy still offers no editing.
- **Modern and Romance** book styles, for the e-book and both PDFs. Modern:
  sans-serif headings, a large numeral for each chapter, no drop cap.
  Romance: chapter titles in a flowing script (Great Vibes, carried inside
  the e-book), numerals framed by florals, a floral mark between scenes. A style of your own can build on any style with
  `extends:`.
- **Front and back matter**: a copyright page (with an optional ISBN), a
  dedication, an "Also by" page, and your own pages from `front-matter/` and
  `back-matter/`, for the whole book and selections of chapters.
- **Smarter quick picks**: tick scenes by status, point of view, character,
  or "changed since" a date, or take the first 50 pages.
- **Export in the live demo**: every step, real previews, and ready-made
  EPUB and PDF downloads of the whole demo book in each style.

- **PDF export.** *Print book (PDF)* lays the book out as a paperback
  interior ready for KDP or IngramSpark: a trim size (5 × 8, 5.25 × 8,
  5.5 × 8.5, 6 × 9 in, or A5), mirrored margins with a gutter sized for the
  page count, running heads, page numbers, and chapters opening on a
  right-hand page. *Shareable PDF* is a Letter or A4 copy with the cover, a
  clickable contents page, bookmarks, and an optional watermark naming the
  reader. Both come from the same book as the EPUB, in the same Classic
  style, and both are in the Export dialog (with a page-spread preview) and
  on the command line (`--format pdf-print`, `pdf-share` or `all`, `--trim`,
  `--paper`, `--watermark`). Nothing else needs installing.
- HTML in a scene is understood in every export instead of being printed as
  text: `<img>` tags (including the dashboard's `/repo-asset/` addresses,
  curly-quoted attributes and tags spread over several lines) become real
  pictures sized by their `width`, `<br>`, `<b>`, `<i>`, `<sup>` and `<sub>`
  keep their meaning, `<p>`/`<div>` are paragraphs and can be centred, and
  any other tag is left out with its text kept.
- The **Manuscript** style: standard submission format for agents and
  editors, with your contact details and the word count on the title page
  (`--style manuscript --contact …`).
- Each PDF is checked after export: the page size, embedded fonts, KDP's
  page limits, and a manuscript's contact details.

- **Export from the dashboard.** An Export button in the top bar opens a
  three-step dialog: tick the chapters and scenes to include (or reorder
  them by dragging), pick the style and whether scene titles show, then fill
  in the title, subtitle, author and cover while a preview shows the styled
  pages. "Export this scene" and "Export this chapter" in the file browser's
  menu and the scene viewer's menu open it with that part already ticked.
  The finished book can be opened, shown in its folder, or downloaded.
- After each export a plain-language check says whether the book is ready
  for Apple Books, Kobo and KDP, or what to fix first: a missing title or
  author, a cover too small or too wide for stores, an image without a
  description. An image that cannot be found names its scene, with a button
  to open it.
- The dashboard remembers the book's details under `export:` in
  `.proseview.yaml`, and `proseview export` uses them as its defaults. New
  `--subtitle` option.

- Export part of the book: one chapter, one scene, several chapters (gaps
  allowed), hand-picked scenes, or a custom order, with `--chapters`,
  `--scenes` and `--order custom`. A single chapter or scene comes without a
  table of contents, and a single scene gets a small header naming the book
  and chapter.
- Saved selections: `--save-selection "Beta readers part 1"` remembers what
  you picked in `.proseview.yaml`, and `--selection` exports it again.
  `--list-selections` shows them.
- The Classic book style: serif body, "Chapter One" openers with a drop cap,
  and a centred break between scenes. Scene titles are hidden by default;
  `--scene-titles` shows them. `--style` takes a folder of your own.
- CI runs EPUBCheck, the validator the stores use, on every selection type.

### Changed

- `proseview export` writes the EPUB itself and no longer needs pandoc.
  `--engine pandoc` keeps the old path for one more release.
- Exports land in `exports/` inside the novel, named after the book and the
  day (`my-novel-2026-10-08.epub`), and the first export adds `exports/` to
  the novel's `.gitignore`. `--output` still writes anywhere.
- The book keeps one identifier, saved under `export:` in `.proseview.yaml`,
  so an e-reader replaces an earlier export instead of adding a second copy.
- The Claude tab's SDK installs as an extra: `pipx install "proseview[claude]"`,
  or `pipx inject proseview claude-agent-sdk` for an existing install. The
  dock gives that command when the SDK is missing.

### Fixed

- Files marked `scene: false` are left out of an export, as the dashboard
  leaves them out.
- `proseview export --output book.epub` makes an EPUB even when the last
  dashboard export was a PDF; a file name that contradicts `--format` is
  refused.
- Manuscript format uses Liberation Serif, which has Times New Roman's
  letter widths, bundled so it is the same on every computer.
- A chapter opening with a one-line paragraph gets small capitals but no drop
  cap, which used to hang into the next paragraph.
- When Claude cannot answer -- an exhausted plan, an API error -- the dock
  says why, instead of "Claude could not finish: success".
- Title pages, headings and the contents get the same curly quotes and
  dashes as the prose ("Alice’s", not "Alice's").
- The Classic drop cap spans exactly two lines; the third line no longer
  steps in around it.
- A single exported chapter or scene passes EPUBCheck: its contents page is
  no longer listed as a landmark outside the reading order.
- Saving a scene or note leaves every block you did not edit exactly as
  written. `[[wikilinks]]`, `> [!note]` callouts, `![[embeds]]`, `-` bullets
  and `_italic_` used to come back escaped or reformatted on every save.

## 0.3.1 — 2026-10-08

### Changed

- Graphite Dark is the default theme. A theme you picked is kept.
- On a phone the dashboard lays out for the screen: the file list starts
  closed, the search and theme menus fit instead of running off the edge, and
  the section tabs scroll in their own strip with the open one in sight.
- A snapshot can describe itself to link previews (`--title`,
  `--description`, `--site-url`, `--preview-image`), and leaves out the
  recent-changes card when the repository has no git history.
- A snapshot no longer offers to edit or delete TODOs and notes, add
  frontmatter, or tick off a frontmatter TODO; none of those can be saved.
- The demo book has TODOs and notes to show, and its first scene's
  frontmatter is back.

### Fixed

- TODO and NOTE comments no longer count as words, and no longer move reading
  time, vocabulary, sentence rhythm, or the goal history. The annotations
  themselves are found and shown as before.

## 0.3.0 — 2026-10-07

### Added

- `proseview snapshot` writes the dashboard as static, read-only files any web
  host can serve. Readers can browse scenes, search, and read the analysis, and
  no paths from your machine are published. With `--demo`, visitors can also
  try edit mode; their saves stay in their browser tab. The
  [live demo](https://ourarash.github.io/proseview/) is built that way.
- Review an agent's file edits after the turn, a change at a time: keep or drop
  each block, side by side or inline. What you keep is written in one step, the
  version it replaces goes to scene history, and the agent is told which edits
  you dropped.
- Save conflicts can be reviewed: when a scene changed on disk while you were
  editing it, compare the two before choosing to overwrite. The replaced text is
  kept in scene history.
- A sidebar file browser for creating, renaming, and moving files and folders to
  the trash, and for copying a file's path.
- Discuss: pick the model and reasoning effort per conversation. Every action is
  worded by a Markdown skill under `.proseview/skills/` that you can edit.
  Claude can now edit files when you ask for a change.
- Quick critique answers as numbered findings, each quoting its line and giving
  a fix.

### Changed

- Works with Codex CLI 0.160. Codex retired the `untrusted` approval policy,
  which now asks before every command, file reads included, so turns run
  `on-request` inside a read-only sandbox: reads need no answer, and a command
  that would write still asks. Paginated conversation history is read a page at
  a time, and a request to type into a running command is shown as one.
- Agent edits no longer stop mid-turn to ask; you review them afterwards.
  Commands and permission requests still ask, and a reading pass such as a
  critique declines any edit.
- Discuss conversations survive moving between files, and the dock says whether
  the agent is still working.

### Removed

- The in-browser terminal. Agents run through the Codex and Claude tabs.

### Fixed

- Switching a list between bullets and numbers no longer fails when the
  selection spans several items.
- The presets menu and the selection menu stay open when the page redraws
  underneath them.
- History offers to open a past conversation as soon as the running turn ends.
