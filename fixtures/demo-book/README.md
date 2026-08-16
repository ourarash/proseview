# Demo manuscript — *Alice's Adventures in Wonderland*

Used for Proseview's screenshots, README clips, and manual testing. Not used by
the test suite; `fixtures/demo-repo` is the test fixture.

## Source and licence

Text: *Alice's Adventures in Wonderland* by Lewis Carroll (1865), from
[Project Gutenberg ebook #11](https://www.gutenberg.org/ebooks/11).
The work is in the public domain worldwide.

The Project Gutenberg header, footer, and licence boilerplate are stripped, so
nothing here carries the PG trademark or its terms — only Carroll's text.

## What was added

The source is a single plain-text file. To make it a Proseview manuscript:

- split into 39 scenes across the 12 chapters, at paragraph boundaries,
  targeting ~700 words each
- scene titles written by hand
- `thread:` set to the motif each scene belongs to — `rabbit`, `size`, `court`,
  `wonderland` — which interleave across the book rather than running in blocks
- `day:` set to the scene's beat number, since the story is one continuous
  afternoon
- `characters:` detected from the recurring cast
- Gutenberg's `_italics_` converted to Markdown

Rebuild with `scripts/build_demo_book.py`.
