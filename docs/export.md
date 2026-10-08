# Exporting your book: EPUB and PDF

[← back to the README](../README.md)

Proseview turns your manuscript, or any part of it, into:

- an **e-book (EPUB)** for Apple Books, Kobo, Kindle Direct Publishing and
  every e-reader;
- a **print book (PDF)**: a paperback interior to upload to KDP or
  IngramSpark, at the trim size you choose;
- a **shareable PDF**: a copy to send to a beta reader, an agent or an
  editor, as a finished-looking book or in standard manuscript format.

Nothing else needs installing: Proseview writes all three itself.

## Exporting from the dashboard

Click **Export** in the top bar. The dialog has three steps:

1. **What to export.** Every chapter is ticked to start with. Untick
   chapters, or open one with its arrow to tick single scenes. The line at
   the bottom keeps count: "3 chapters, 14 scenes, 41,200 words". Quick picks
   fill the ticks for you: *Whole book*, *First three chapters*, *First 50
   pages* (estimated from the trim size, in whole scenes), and any selection
   you have saved. **Or tick scenes by** a scene's *status* or *point of view*
   (the `status:` and `pov:` in its frontmatter), a *character* (listed under
   `characters:`, or named in the text, as the presence chart counts them),
   or *changed since* a date (from git, or the file's date), for instance to
   send beta readers only what changed since their last round. To put things in a different order (a synopsis
   packet, one character's arc), turn on **Reorder** and drag them, or use the
   arrow buttons. **Save this selection…** keeps what you ticked under a name.
2. **Format and style.** Choose *E-book (EPUB)*, *Print book (PDF)*,
   *Shareable PDF*, or *All formats* to make the three at once. Each shows
   the few options it needs:
   - e-book: EPUB 3 is what the stores expect; EPUB 2 is only for older
     e-readers;
   - print book: the **trim size** (5 × 8, 5.25 × 8, 5.5 × 8.5, 6 × 9 in, or
     A5; 5.5 × 8.5 in is the most common for novels), and whether chapters
     start on a right-hand page, as most printed novels do;
   - shareable PDF: US Letter or A4, and an optional **watermark** such as
     "Advance copy for Sam", printed faintly across every page. The watermark
     names one reader, so it is never remembered for the next export.

   Then choose the style (see [How it looks](#how-it-looks)) and whether
   scene titles show.
3. **Book details.** The title, subtitle, author and cover. Drop a cover
   image on the box or choose one; it is saved in your novel's folder as
   `cover.jpg` (or `.png`). With the Manuscript style you also give your
   contact details for its title page. **Front and back matter** (see
   [below](#front-and-back-matter)) opens a few more fields: the copyright
   page, an ISBN, a dedication and your other books. Beside the form is a preview, laid out
   exactly as the export will be: an e-reader page for an EPUB, facing pages
   for a print book, single pages for a shareable PDF. Use the arrows to turn
   pages and the menu to jump. A PDF preview lays out the first three
   chapters, so it stays quick on a long novel; the export has them all.

Click **Export**. When the book is ready you can **Open** it, **Show in
folder**, or **Download** a copy. Books land in an `exports/` folder inside
your novel, named after the book and the day:

| Format | File |
| --- | --- |
| E-book | `alices-adventures-in-wonderland-2026-10-08.epub` |
| Print book | `alices-adventures-in-wonderland-print-2026-10-08.pdf` |
| Shareable PDF | `alices-adventures-in-wonderland-2026-10-08.pdf` |
| Manuscript | `alices-adventures-in-wonderland-manuscript-2026-10-08.pdf` |

To export just one scene or chapter, right-click it in the file browser (or
use its **…** button), or open the scene and use the **…** menu in its
toolbar: **Export this scene** and **Export this chapter** open the dialog
with that part already ticked.

### Is it ready for the stores?

After every export Proseview checks the book and says so in plain words:
**Ready for Apple Books, Kobo and KDP**, or what to fix first, each with a
button that takes you there:

- the title is still the folder's name, or the author is missing
- there is no cover, or it is too small (stores ask for at least 1600 px on
  the short side; 1600 × 2560 px is a safe size) or wider than a book
- an image has no description (the text between the brackets in
  `![The bridge at night](images/bridge.png)`), which readers who listen to
  the book hear, and which European stores now ask for

A part of the book (a chapter, a scene, a selection) is meant for readers
rather than a store, so it is only checked for soundness: **Ready to share
with readers**. If a scene uses an image that cannot be found, the export
stops, names the scene, and offers to open it.

A PDF is read back and checked too: every page is the size you chose, every
font is embedded (KDP rejects an interior with a missing font), and a
paperback has the 24 to 828 pages KDP prints. A whole book that passes is
**Ready to upload to KDP as a 5.5 × 8.5 in paperback interior**. A
manuscript without contact details asks for them, since an agent needs a way
to reply.

The print PDF is the *interior* only. KDP and IngramSpark take the cover as a
separate file sized for your page count and paper, so the cover you choose
here goes on the e-book and the shareable PDF, not inside the print book.

The dashboard remembers the book's details in `.proseview.yaml`, so the next
export starts where you left off (see [What Proseview remembers](#what-proseview-remembers)).

## Exporting from the command line

```bash
proseview export --root /path/to/your/novel --author "Your Name"
# → exports/your-novel-2026-10-08.epub
proseview export --format pdf-print --trim 6x9
# → exports/your-novel-print-2026-10-08.pdf
proseview export --format pdf-share --watermark "Advance copy for Sam"
proseview export --format pdf-share --style manuscript --contact "you@example.com\n+1 555 0100"
proseview export --format all          # the e-book and both PDFs
```

Scenes are compiled in the same order the dashboard counts them, and titles
and chapters use frontmatter where present and fall back to the filename and
folder, exactly as the scene table does. Files marked `scene: false` are left
out, as the dashboard leaves them out.

`--output` writes anywhere else instead of `exports/`. In a git repository,
the first export adds `exports/` to your `.gitignore` so a book is never
committed by accident.

### Choosing what to export

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

#### Saved selections

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

**Classic** is a traditional novel, and looks the same in the e-book and the
PDFs: a serif body, chapter openers reading "Chapter One" above the chapter's
title, a two-line drop cap with a small-caps first line, and a centred
`*   *   *` between scenes. In print it adds running heads (the author on
left-hand pages, the title on right-hand ones), page numbers, no head on a
chapter's opening page, and an inside margin that widens with the page count
so no words disappear into the fold. The shareable PDF adds the cover, a
contents page you can click, and bookmarks for every chapter.

**Modern** has a clean serif text with sans-serif headings, a large numeral
for each chapter, no drop cap, and a pause of three dots between scenes.

**Romance** has a large italic chapter title under a numeral framed by floral
ornaments, a drop cap, and a floral mark between scenes.

**Manuscript** is standard submission format, for a Shareable PDF only:
12 pt Liberation Serif (the same letter widths as Times New Roman), double-spaced, 1 inch margins, every paragraph indented, "Chapter 1"
a third of the way down the page, a centred `#` between scenes, a title page
with your name, contact details and the word count ("about 85,000 words"),
and "Surname / TITLE / page" at the top of each page.

Scene titles are hidden, because novels mark a change of scene with the break
rather than a heading. To show them as headings (and list them in the table
of contents):

```bash
proseview export --scene-titles
```

A chapter whose first paragraph is a single line keeps its small capitals but
no drop cap, which would otherwise hang into the paragraph below.

PDFs use the open-licence fonts that come with Proseview (Libertinus Serif
for the text, Noto Sans for Modern's headings, Liberation Serif for
Manuscript), never the fonts installed on your computer, so a book looks the
same on every machine and every font is embedded in the file.

A style is a folder holding `epub.css` for the e-book and `pdf.typ` (a
[Typst](https://typst.app/docs/) template) for the PDFs, either or both,
plus an optional `style.yaml` (chapter numbering as `words`, `numerals`,
`number` or `none`; the scene-break text; whether scene titles show;
`formats` to limit what it makes). A style can build on another with
`extends: classic`: its stylesheet is added after the base one, and its PDFs
use the base layout with the choices it sets under `pdf:` (`body_font`,
`heading_font`, `opener` as `classic`, `modern` or `romance`, `drop_cap`,
`ornament`). That is all Modern and Romance are. Point `--style` at a folder of your own to use it, and add
`--css` for small overrides on top of an e-book style. The comment at the top
of the built-in `classic/pdf.typ` lists what a PDF template defines.

Defaults for these go in `.proseview.yaml` (see below).

## Front and back matter

A whole book, or a selection of several chapters, gets pages before and after
the story. A single chapter or scene, sent to a reader for that one piece,
and a manuscript for an agent, go without.

- **Copyright page**, on by default: "Copyright © 2026 Your Name. All rights
  reserved.", and the ISBN when you give one. In a print book it sits on the
  back of the title page.
- **Dedication**, when you write one.
- **Also by**: list your other books, one per line, for a page at the back.
- **Your own pages**: Markdown files in a `front-matter/` or `back-matter/`
  folder in your novel, in name order, for an epigraph, a foreword,
  acknowledgements, "About the Author", anything. Number them to set the
  order (`01-epigraph.md`). A file named for a kind of page
  (`dedication.md`, `copyright.md`) replaces the one Proseview would write.

Front matter comes after the title page and before the contents; back matter
after the last chapter. E-readers learn what each page is, and the back
matter is listed in the contents.

## What Proseview remembers

Everything under `export:` in `.proseview.yaml` is shared by the dashboard
and the command line. The dashboard writes the book details after each
successful export; the command line reads them as its defaults, and a flag
given on the command line wins for that run.

```yaml
export:
  title: Alice's Adventures in Wonderland
  author: Lewis Carroll
  language: en-GB
  format: epub          # pdf-print, pdf-share or all
  epub_version: epub3   # or epub2
  trim: 5.5x8.5         # 5x8, 5.25x8, 6x9 or a5
  paper: letter         # or a4
  recto_chapters: true  # print chapters open on a right-hand page
  contact: "you@example.com\n+1 555 0100"   # a manuscript's title page
  copyright_page: true
  isbn: 978-1-23456-789-0
  dedication: For Alice
  also_by: [Through the Looking-Glass]
  matter_files: true    # include front-matter/ and back-matter/
  style: classic
  scene_titles: false
  cover_image: cover.jpg   # a path inside the novel's folder
  identifier: urn:uuid:…
```

### Book identifier

The first export saves a book identifier to `.proseview.yaml`:

```yaml
export:
  identifier: urn:uuid:…
```

Every later export reuses it, so an e-reader replaces last week's copy instead
of shelving a second book. Keep it once you have shared or published the book.

## In the online demo

The [live demo](https://ourarash.github.io/proseview/) has no Proseview
running behind it, so it cannot build what you pick. Its Export dialog works
all the same, with every step and real previews, and downloads a ready-made
copy of the whole demo book in the format and style you chose. `proseview
snapshot --demo` builds those copies for any book (`--book-title` and
`--book-author` name them).

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

- **Images** in a scene (`![The bridge at night](images/bridge.png)`, or an
  HTML `<img>` tag) are copied into the book. PNG, JPEG, GIF, SVG and WebP work. An image that cannot
  be found, sits outside the repository, or is a web address stops the export
  and names the scene, because an e-book cannot load images from the internet.
- **Links** to web pages stay clickable. Links to other files in your
  repository, such as a character sheet, keep their text but lose the link,
  since there is nothing in the book for them to open.
- **TODO and NOTE comments** never reach the book, and neither does any other
  HTML comment.
- **HTML** in a scene is understood rather than printed. An `<img>` tag is a
  picture, like a Markdown image: its `src` can be a path in the book or the
  dashboard's own `/repo-asset/...` address, its `alt` becomes the image
  description, and `width="600"` is read as a share of the page (600 pixels
  is the full width, 300 half). `<br>` is a line break; `<em>`/`<i>`,
  `<strong>`/`<b>`, `<sup>` and `<sub>` keep their meaning; `<p>` and `<div>`
  are paragraphs, centred with `align="center"` or `<center>`. Any other tag
  is left out and its text kept, and `<script>`, `<style>` and `<iframe>`
  are left out with everything inside them. Tags written with curly quotes
  (as word processors type them) or over several lines work too.

## All options

`--output`, `--title`, `--subtitle`, `--author`, `--language`, `--epub-version` (`epub3`, or
`epub2` for older readers), `--cover-image` (JPEG, PNG, GIF or WebP),
repeatable `--css`, repeatable `--appendix`, `--chapters`, `--scenes`,
`--order`, `--selection`, `--save-selection`, `--list-selections`, `--style`,
`--scene-titles` / `--no-scene-titles`, `--format` (`epub`, `pdf-print`,
`pdf-share` or `all`), `--trim`, `--paper`, `--recto-chapters` /
`--no-recto-chapters`, `--watermark`, `--contact`, and `--engine`.

### The pandoc engine

`--engine pandoc` builds the EPUB with [pandoc](https://pandoc.org/installing.html)
the way earlier versions did, for one more release while the built-in writer
settles. It makes EPUBs only. It honours selections, the identifier and every option above except
`--style` and `--scene-titles`, and it needs pandoc installed
(`brew install pandoc` or `apt install pandoc`). It will be removed in a later
release.
