# Fonts bundled for PDF export

PDFs are laid out with fonts that ship with Proseview, never the fonts on the
writer's computer, so a book looks the same everywhere and every font can be
embedded in the file. Typst's own fonts (Libertinus Serif, New Computer Modern,
DejaVu Sans Mono) come with the `typst` package; these are added here.

| Files | Family | Used by | Copyright | Licence |
| --- | --- | --- | --- | --- |
| `LiberationSerif-*.ttf` | Liberation Serif 2 (metric-compatible with Times New Roman) | Manuscript | Digitized data copyright (c) 2010 Google Corporation; copyright (c) 2012 Red Hat, Inc. | SIL Open Font License 1.1 |
| `NotoSans-Regular.ttf`, `NotoSans-Bold.ttf` | Noto Sans | Modern (headings) | Copyright 2022 The Noto Project Authors (https://github.com/notofonts/latin-greek-cyrillic) | SIL Open Font License 1.1 |
| `GreatVibes-Regular.ttf` | Great Vibes (a script face, from github.com/google/fonts) | Romance (chapter titles; also embedded in its EPUBs) | Copyright 2015 The Great Vibes Pro Project Authors (https://github.com/googlefonts/great-vibes) | SIL Open Font License 1.1 |

The licence allows the fonts to be bundled with software and embedded in
documents, EPUBs included (the licence travels in each font's metadata). The licence text is in `OFL.txt`.
