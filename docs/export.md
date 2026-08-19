# EPUB export

[← back to the README](../README.md)

```bash
proseview export --root /path/to/your/novel --author "Your Name"
# → output/your-novel.epub
```

Scenes are compiled in the same order the dashboard counts them: chapters
become top-level sections, scenes become sub-sections, and pandoc builds the
table of contents from that structure. Titles and chapters use frontmatter
where present and fall back to the filename and folder, exactly as the scene
table does.

### Appendices

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

Options: `--output`, `--title`, `--author`, `--language`, `--epub-version`
(`epub3` / `epub2`), `--cover-image`, repeatable `--css`, and repeatable
`--appendix`.

**Requires [pandoc](https://pandoc.org/installing.html)** (`brew install pandoc`
or `apt install pandoc`). Only EPUB export needs it; the dashboard runs without
it, and the export command explains how to install it when it is missing.
