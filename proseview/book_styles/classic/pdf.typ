// Classic, as a PDF: a traditional novel for print or for sharing.
//
// Proseview writes `#let config = (...)` above this file and the book's
// content below it, as calls to the functions defined here. A PDF style is
// any pdf.typ that defines the same functions:
//
//   book(body)                      page set-up; wraps the whole document
//   title-page()                    the title page (and its blank back, in print)
//   contents()                      a table of contents, or nothing
//   chapter(number, title, outline) a chapter opener
//   chapter-end()                   marks where a chapter's text ends
//   opener(initial, words, joined)  a chapter's first paragraph
//   noindent(body)                  a paragraph after a break or a title
//   scene-break()                   between scenes, when titles are hidden
//   scene-title(body)               a scene's title, when titles are shown
//   single-scene(chapter, title)    the header of a single exported scene
//   appendix(label)                 an appendix heading
//   appendix-document(title)        one document inside an appendix
//   book-image(path, alt)           an image from a scene
//
// config holds: layout ("print" or "share"), title, subtitle, author, note,
// lang, region, page-width, page-height, inside, outside, top, bottom, size,
// recto (chapters start on a right-hand page), watermark, cover (a path or
// none), kind ("book", "selection", "chapter", "scene"), scene-break.

#let print = config.layout == "print"
#let leading = 0.62em

// Front matter and the blank left-hand page before a chapter carry no
// header or folio; a chapter's opening page carries a folio but no header.
#let page-kind() = {
  let p = here().page()
  let body = query(<body-start>)
  if body.len() == 0 or p < body.first().location().page() { return "front" }
  let starts = query(<chapter-start>).map(m => m.location().page())
  let ends = query(<chapter-end>).map(m => m.location().page())
  if starts.contains(p) { return "opener" }
  if ends.contains(p - 1) and starts.contains(p + 1) and not ends.contains(p) { return "blank" }
  "text"
}

#let running-head() = context {
  if page-kind() != "text" { return none }
  let label = if print and calc.even(here().page()) and config.author != "" {
    config.author
  } else {
    config.title
  }
  set text(size: 0.78em, tracking: 0.12em)
  align(center, smallcaps(label))
}

#let folio() = context {
  if page-kind() in ("front", "blank") { return none }
  set text(size: 0.85em)
  align(center, counter(page).display("1"))
}

#let book(body) = {
  set document(title: config.title, author: if config.author == "" { () } else { (config.author,) })
  set page(
    width: config.page-width,
    height: config.page-height,
    margin: if print {
      (inside: config.inside, outside: config.outside, top: config.top, bottom: config.bottom)
    } else {
      (x: config.outside, top: config.top, bottom: config.bottom)
    },
    binding: left,
    header: running-head(),
    footer: folio(),
    header-ascent: 40%,
    footer-descent: 40%,
    background: if config.watermark != "" {
      rotate(-38deg, text(size: 30pt, fill: luma(232), tracking: 0.05em, config.watermark))
    },
  )
  set text(
    font: "Libertinus Serif", size: config.size, lang: config.lang, region: config.region,
    hyphenate: true, number-type: "old-style",
  )
  set par(justify: true, leading: leading, spacing: leading, first-line-indent: (amount: 1.4em, all: true))
  set block(spacing: leading)
  // Chapters are found by their (invisible) level-one headings, so the PDF's
  // bookmarks and the contents link to them; the opener draws them itself.
  show heading.where(level: 1): it => block(height: 0pt, above: 0pt, below: 0pt, hide(it.body))
  show heading.where(level: 2): it => block(above: 2em, below: 1.2em, width: 100%,
    align(center, text(size: 1em, weight: "regular", tracking: 0.08em, smallcaps(it.body))))
  show heading: it => if it.level > 2 {
    block(above: 1.4em, below: 0.8em, text(size: 1em, weight: "regular", style: "italic", it.body))
  } else { it }
  show quote.where(block: true): it => pad(x: 1.6em, block(above: 1em, below: 1em, emph(it.body)))
  show link: it => if print { it } else { underline(stroke: 0.4pt, offset: 2pt, it) }
  show raw: set text(font: "DejaVu Sans Mono", size: 0.8em)
  body
}

#let cover-page() = {
  if config.cover != none {
    page(margin: 0pt, header: none, footer: none, background: none,
      image(config.cover, width: 100%, height: 100%, fit: "contain"))
  }
}

#let title-page() = {
  if not print { cover-page() }
  page(header: none, footer: none, {
    set par(first-line-indent: 0pt, justify: false)
    v(22%)
    align(center, {
      text(size: 2em, config.title)
      if config.subtitle != "" {
        v(0.6em)
        text(size: 1.15em, style: "italic", config.subtitle)
      }
      if config.author != "" {
        v(2.6em)
        text(size: 1.15em, tracking: 0.08em, smallcaps(config.author))
      }
      if config.note != "" {
        v(4em)
        text(size: 0.9em, style: "italic", config.note)
      }
    })
  })
  // The back of the title page stays blank, so chapter one opens on the right.
  if print { page(header: none, footer: none, []) }
}

#let contents() = {
  if print { return }
  page(header: none, footer: none, {
    set par(first-line-indent: 0pt, justify: false)
    v(10%)
    align(center, text(size: 1.1em, tracking: 0.2em, upper("Contents")))
    v(2em)
    show outline.entry.where(level: 1): set block(above: 0.9em)
    context outline(title: none, depth: if query(heading.where(level: 2)).len() > 0 { 2 } else { 1 }, indent: 1.4em)
  })
}

#let started = state("body-started", false)

#let chapter(number, title, outline-label) = {
  if print and config.recto {
    pagebreak(weak: true, to: "odd")
  } else {
    pagebreak(weak: true)
  }
  context if not started.get() {
    started.update(true)
    counter(page).update(1)
    [#metadata("body") <body-start>]
  }
  [#metadata("chapter") <chapter-start>]
  heading(level: 1, outline-label)
  set par(first-line-indent: 0pt)
  v(if print { 16% } else { 10% })
  align(center, {
    if number != none {
      text(size: 0.8em, tracking: 0.24em, upper(number))
    }
    if number != none and title != none { v(0.9em) }
    if title != none {
      text(size: 1.45em, style: if number == none { "normal" } else { "italic" }, title)
    }
  })
  v(2.6em)
}

#let chapter-end() = [#metadata("end") <chapter-end>]

#let single-scene(chapter-line, title) = {
  context if not started.get() {
    started.update(true)
    counter(page).update(1)
    [#metadata("body") <body-start>]
  }
  [#metadata("chapter") <chapter-start>]
  heading(level: 1, title)
  set par(first-line-indent: 0pt)
  v(6%)
  align(center, {
    text(size: 0.78em, tracking: 0.14em, upper(config.title))
    if chapter-line != none {
      linebreak()
      text(size: 0.78em, tracking: 0.14em, upper(chapter-line))
    }
    v(1em)
    text(size: 1.35em, style: "italic", title)
  })
  v(2.2em)
}

#let noindent(body) = par(first-line-indent: 0pt, body)

#let scene-break() = block(above: 1.3em, below: 1.3em, width: 100%,
  align(center, text(tracking: 0.1em, config.scene-break)))

#let scene-title(body) = heading(level: 2, body)

// A chapter's first paragraph: a two-line drop cap, and the words beside it
// in small capitals for the first line, as the EPUB style draws it. The
// words are measured into exactly two lines beside the letter; the rest of
// the paragraph then runs the full width.
#let opener(initial, words, joined: true) = context {
  let cap = measure(text(top-edge: "cap-height", bottom-edge: "baseline", [H])).height
  let lead = par.leading.to-absolute()
  let drop-size = text.size * ((2 * cap + lead) / cap)
  let drop = text(size: drop-size, top-edge: "cap-height", bottom-edge: "baseline", initial)
  let gap = if joined { 0.06em } else { 0.22em }
  let drop-width = measure(drop).width + gap.to-absolute()
  let space = [ ]
  let line-height(n) = n * cap + (n - 1) * lead + 0.5pt

  layout(region => {
    let width = region.width - drop-width
    // Exactly what will be set beside the letter: the first line's words in
    // small capitals, a forced break, then the second line's words.
    let set-words(first, rest) = {
      text(tracking: 0.04em, smallcaps(first.join(space)))
      if rest.len() > 0 {
        linebreak()
        rest.join(space)
      }
    }
    let height-of(body) = measure(block(width: width, par(justify: false, first-line-indent: 0pt, body))).height
    // The most words, from `from`, that fit in `lines` lines.
    let fit(lines, make) = {
      let (lo, hi) = (0, words.len())
      while lo < hi {
        let mid = calc.quo(lo + hi + 1, 2)
        if height-of(make(mid)) <= line-height(lines) { lo = mid } else { hi = mid - 1 }
      }
      lo
    }
    let first = fit(1, n => set-words(words.slice(0, n), ()))
    if first == 0 {
      // Nothing fits beside the letter (a very narrow page): a plain paragraph.
      par(first-line-indent: 0pt, [#initial#words.join(space)])
      return
    }
    let second = fit(2, n => set-words(words.slice(0, first), words.slice(first, calc.max(first, n))))
    let second = calc.max(first, second)
    let beside = {
      text(tracking: 0.04em, smallcaps(words.slice(0, first).join(space)))
      if second < words.len() or second > first { linebreak(justify: second < words.len()) }
      if second > first {
        words.slice(first, second).join(space)
        if second < words.len() { linebreak(justify: true) }
      }
    }
    block(above: 0pt, below: lead, grid(
      columns: (drop-width, width),
      align(left + top, drop),
      par(justify: true, first-line-indent: 0pt, beside),
    ))
    if second < words.len() {
      par(first-line-indent: 0pt, words.slice(second).join(space))
    }
  })
}

#let appendix(label) = {
  pagebreak(weak: true)
  [#metadata("chapter") <chapter-start>]
  heading(level: 1, label)
  v(8%)
  align(center, text(size: 1.3em, label))
  v(2em)
}

#let appendix-document(title) = block(above: 1.8em, below: 0.9em,
  text(size: 1.1em, weight: "bold", title))

#let book-image(path, alt: "") = block(above: 1em, below: 1em, width: 100%,
  align(center, image(path, alt: alt, width: 80%)))
