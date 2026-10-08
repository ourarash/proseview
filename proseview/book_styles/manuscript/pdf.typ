// Manuscript: standard submission format, as agents and editors ask for it.
//
// Defines the same functions as classic/pdf.typ (see the list there), laid
// out the way a submission is: Letter or A4, 1 in margins, 12 pt type,
// double-spaced, ragged right, every paragraph indented half an inch, a
// title page with the author's contact details and the word count, and
// "Surname / TITLE / page" at the top right of every text page.

#let leading = 1.5em

#let surname = {
  let parts = config.author.split(" ").filter(p => p != "")
  if parts.len() == 0 { "" } else { parts.last() }
}

#let page-kind() = {
  let p = here().page()
  let body = query(<body-start>)
  if body.len() == 0 or p < body.first().location().page() { "front" } else { "text" }
}

#let running-head() = context {
  if page-kind() == "front" { return none }
  let parts = ()
  if surname != "" { parts.push(surname) }
  parts.push(upper(config.title))
  // Counted from the first text page; the header is laid out before the
  // page counter is reset there, so it is worked out rather than read.
  parts.push(str(here().page() - query(<body-start>).first().location().page() + 1))
  set text(size: 12pt)
  align(right, parts.join(" / "))
}

#let book(body) = {
  set document(title: config.title, author: if config.author == "" { () } else { (config.author,) })
  set page(
    width: config.page-width,
    height: config.page-height,
    margin: 1in,
    header: running-head(),
    footer: none,
    header-ascent: 50%,
    background: if config.watermark != "" {
      rotate(-38deg, text(size: 30pt, fill: luma(235), config.watermark))
    },
  )
  set text(font: "Libertinus Serif", size: 12pt, lang: config.lang, region: config.region, hyphenate: false)
  set par(justify: false, leading: leading, spacing: leading, first-line-indent: (amount: 0.5in, all: true))
  set block(spacing: leading)
  show heading.where(level: 1): it => block(height: 0pt, above: 0pt, below: 0pt, hide(it.body))
  show heading: it => if it.level > 1 {
    block(above: leading, below: leading, width: 100%, align(center, text(weight: "regular", it.body)))
  } else { it }
  show quote.where(block: true): it => pad(left: 0.5in, it.body)
  show raw: set text(font: "DejaVu Sans Mono", size: 11pt)
  body
}

#let cover-page() = none

#let title-page() = page(header: none, {
  set par(first-line-indent: 0pt, leading: 0.65em, spacing: 0.65em)
  grid(
    columns: (1fr, auto),
    {
      if config.author != "" { config.author; linebreak() }
      for line in config.contact.split("\n").filter(l => l.trim() != "") { line.trim(); linebreak() }
    },
    align(right, config.word-count),
  )
  v(1fr)
  align(center, {
    upper(config.title)
    if config.subtitle != "" { linebreak(); config.subtitle }
    if config.author != "" { v(1.5em); [by #config.author] }
    if config.note != "" { v(1.5em); emph(config.note) }
  })
  v(1fr)
  v(1fr)
})

#let contents() = none

#let started = state("body-started", false)

#let start-body() = context if not started.get() {
  started.update(true)
  counter(page).update(1)
  [#metadata("body") <body-start>]
}

#let chapter(number, title, outline-label) = {
  pagebreak(weak: true)
  start-body()
  heading(level: 1, outline-label)
  v(2.2in)
  set par(first-line-indent: 0pt)
  align(center, {
    if number != none { number }
    if number != none and title != none { linebreak() }
    if title != none { title }
  })
  v(leading)
}

#let chapter-end() = none

#let single-scene(chapter-line, title) = {
  start-body()
  heading(level: 1, title)
  v(1.5in)
  set par(first-line-indent: 0pt)
  align(center, {
    upper(config.title)
    if chapter-line != none { linebreak(); chapter-line }
    linebreak()
    title
  })
  v(leading)
}

// Every paragraph is indented in a manuscript, even after a break.
#let noindent(body) = par(body)

#let scene-break() = block(above: 0pt, below: 0pt, width: 100%, align(center, par(first-line-indent: 0pt, config.scene-break)))

#let scene-title(body) = heading(level: 2, body)

#let opener(initial, words, joined: true) = {
  let rest = words.join([ ])
  par(if joined { [#initial#rest] } else { [#initial #rest] })
}

#let appendix(label) = {
  pagebreak(weak: true)
  heading(level: 1, label)
  v(2.2in)
  align(center, par(first-line-indent: 0pt, label))
  v(leading)
}

#let appendix-document(title) = block(above: leading, below: 0pt, par(first-line-indent: 0pt, strong(title)))

#let book-image(path, alt: "") = block(width: 100%, align(center, image(path, alt: alt, width: 70%)))
