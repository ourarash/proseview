# EPUB export

[← back to the README](../README.md)

```bash
proseview export --root /path/to/your/novel --author "Your Name"
# → exports/your-novel-2026-10-08.epub
```

Nothing else needs installing: Proseview writes the EPUB itself. Scenes are
compiled in the same order the dashboard counts them, and titles and chapters
use frontmatter where present and fall back to the filename and folder, exactly
as the scene table does. Files marked `scene: false` are left out, as the
dashboard leaves them out.

Books land in an `exports/` folder inside your novel, named after the book and
the day. In a git repository, the first export adds `exports/` to your
`.gitignore` so a book is never committed by accident. `--output` writes
anywhere else instead.

## Choosing what to export

With no options, the whole book is exported with a title page and a table of
contents. To export part of it:

```bash
proseview export --chapters 3                 # one chapter
proseview export --scenes ch01/02-the-bridge  # one scene
proseview export --chapters 3,7-9             # several chapters, gaps allowed
proseview export --scenes 1.2,4.1             # hand-picked scenes
proseview export --scenes 9.1 --chapters 1 --order custom
```

| You pick | What you get |
| --- | --- |
| Nothing | The whole book, with a title page and table of contents |
| One chapter | The chapter opener and its scenes, no table of contents |
| One scene | The scene alone under a small header (book, chapter, scene title), handy for a critique group |
| Several chapters | Book order kept; the title page notes which, e.g. "Chapters 3, 7–9" |
| A mix of scenes | Scenes grouped under their chapters, in book order |
| `--order custom` | Exactly the order you typed, for a synopsis packet or one character's arc |

**Chapters** can be named by number (`3`), range (`7-9`), folder (`ch03`), or
title (`"The Bridge"`). **Scenes** can be named by path below the manuscript
folder (`ch03/02-the-fall`), file name (`02-the-fall`), title, or
chapter.scene number (`3.2` is the second scene of chapter three). Both flags
take a comma-separated list and can be repeated. Chapter numbers count from
the start of the whole book, so chapter seven is still "Chapter Seven" when
you export it alone.

A part of the book gets its own file name (`my-novel-chapter-3-…`,
`my-novel-scene-the-fall-…`), so it never overwrites the full book, and its own
identifier, so an e-reader keeps it apart from the novel.

### Saved selections

Name a selection to reuse it:

```bash
proseview export --chapters 1-3 --save-selection "Beta readers part 1"
proseview export --selection "Beta readers part 1"
proseview export --list-selections
```

Selections live in `.proseview.yaml`, chapters by folder and scenes by path so
they keep their meaning when you insert a chapter earlier in the book. Scenes
you add later to a saved chapter are picked up automatically. You can also
write them by hand:

```yaml
export:
  selections:
    Beta readers part 1:
      chapters: [ch01, ch02, ch03]
    The Hatter's arc:
      order: custom
      items:
        - scene: ch07/01-a-mad-tea-party
        - scene: '11.2'   # quote chapter.scene numbers: YAML reads 11.10 as 11.1
```

## How it looks

Books use the **Classic** style: a serif body, chapter openers reading
"Chapter One" above the chapter's title, a drop cap and small-caps first line,
and a centred `*   *   *` between scenes. Scene titles are hidden, because
novels mark a change of scene with the break rather than a heading. To show
them as headings (and list them in the table of contents):

```bash
proseview export --scene-titles
```

A style is a folder holding `epub.css` and an optional `style.yaml` (chapter
numbering as `words`, `numerals` or `none`; the scene-break text; whether scene
titles show). Point `--style` at a folder of your own to use it, and add
`--css` for small overrides on top of the style.

Defaults for these go in `.proseview.yaml`:

```yaml
export:
  style: classic
  scene_titles: false
```

## Book identifier

The first export saves a book identifier to `.proseview.yaml`:

```yaml
export:
  identifier: urn:uuid:…
```

Every later export reuses it, so an e-reader replaces last week's copy instead
of shelving a second book. Keep it once you have shared or published the book.

## Appendices

Append other folders after the manuscript — planning notes, an outline, a
story bible — one appendix per folder, in the order you name them:

```bash
proseview export --list-appendix-folders     # what can I append?
proseview export --appendix plans --appendix outline
```

Each folder contributes the Markdown files sitting directly inside it. Nested
directories are left out, so an archive like `plans/done/` stays out of the
book, and `README.md` is skipped. Appendix headings are pushed below the
table-of-contents depth so they do not compete with your chapters.

## What goes into the book

- **Images** in a scene (`![The bridge at night](images/bridge.png)`) are
  copied into the EPUB. PNG, JPEG, GIF, SVG and WebP work. An image that cannot
  be found, sits outside the repository, or is a web address stops the export
  and names the scene, because an e-book cannot load images from the internet.
- **Links** to web pages stay clickable. Links to other files in your
  repository, such as a character sheet, keep their text but lose the link,
  since there is nothing in the book for them to open.
- **TODO and NOTE comments** never reach the book, and neither does any other
  HTML comment. Other raw HTML is shown as text rather than passed through, so
  one stray tag cannot make the book unreadable.

## All options

`--output`, `--title`, `--author`, `--language`, `--epub-version` (`epub3`, or
`epub2` for older readers), `--cover-image` (JPEG, PNG, GIF or WebP),
repeatable `--css`, repeatable `--appendix`, `--chapters`, `--scenes`,
`--order`, `--selection`, `--save-selection`, `--list-selections`, `--style`,
`--scene-titles` / `--no-scene-titles`, `--format` (`epub` for now), and
`--engine`.

### The pandoc engine

`--engine pandoc` builds the EPUB with [pandoc](https://pandoc.org/installing.html)
the way earlier versions did, for one more release while the built-in writer
settles. It honours selections, the identifier and every option above except
`--style` and `--scene-titles`, and it needs pandoc installed
(`brew install pandoc` or `apt install pandoc`). It will be removed in a later
release.
