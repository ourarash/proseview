"""Check a finished PDF and say, in plain words, whether it is ready.

The PDF is read back and checked for what a printer or a reader relies on:
the page size is the trim size that was asked for, every font is embedded
(KDP rejects an interior with a missing font), and the page count is one a
paperback can have. A shareable PDF is checked for soundness only, and a
manuscript for the contact details an agent needs to reply.

Typst writes plain PDF objects (no compressed object streams), so this needs
no PDF library: the page boxes and font descriptors are readable as bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .book import Book
from .epub_check import Finding
from .pdf import KDP_MAX_PAGES, KDP_MIN_PAGES, PAPER_LABELS, TRIM_LABELS, TRIM_SIZES, page_count

_POINTS_PER = {"in": 72.0, "mm": 72.0 / 25.4}


@dataclass(frozen=True)
class PdfFacts:
    pages: int
    #: (width, height) in points of every distinct page box.
    page_sizes: tuple[tuple[float, float], ...]
    fonts: int
    unembedded_fonts: tuple[str, ...]


def _points(length: str) -> float:
    match = re.fullmatch(r"([\d.]+)(in|mm)", length)
    return float(match.group(1)) * _POINTS_PER[match.group(2)]


def pdf_facts(data: bytes) -> PdfFacts:
    """Page count, page sizes and font embedding, read from the PDF's objects."""
    sizes = set()
    for box in re.findall(rb"/MediaBox\s*\[\s*([-\d.\s]+)\]", data):
        x0, y0, x1, y1 = (float(v) for v in box.split())
        sizes.add((round(x1 - x0, 1), round(y1 - y0, 1)))
    descriptors = re.findall(rb"<<(?:(?!>>).)*?/Type\s*/FontDescriptor.*?>>", data, re.DOTALL)
    unembedded = []
    for descriptor in descriptors:
        if not re.search(rb"/FontFile[23]?\b", descriptor):
            name = re.search(rb"/FontName\s*/([^\s/>]+)", descriptor)
            unembedded.append(name.group(1).decode("latin-1") if name else "unknown")
    return PdfFacts(page_count(data), tuple(sorted(sizes)), len(descriptors), tuple(unembedded))


def structural_problems(path: Path, *, expected: tuple[str, str] | None = None) -> list[str]:
    """What is wrong with the PDF at *path*; empty when it is sound."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [f"the file cannot be read ({exc})"]
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        return ["the file is not a complete PDF"]
    facts = pdf_facts(data)
    problems = []
    if facts.pages == 0:
        problems.append("it has no pages")
    if facts.unembedded_fonts:
        problems.append("these fonts are not embedded: " + ", ".join(facts.unembedded_fonts))
    if expected is not None:
        width, height = (round(_points(v), 1) for v in expected)
        if any(abs(w - width) > 0.6 or abs(h - height) > 0.6 for w, h in facts.page_sizes):
            problems.append("some pages are not the size that was asked for")
    return problems


def readiness(
    path: Path,
    book: Book,
    *,
    layout: str,
    trim: str = "",
    paper: str = "",
    style: str = "",
    title_given: bool = True,
    contact: str = "",
) -> dict:
    """Check the PDF at *path*; return a headline and the findings, like the EPUB check."""
    from .pdf import PAPER_SIZES

    expected = TRIM_SIZES.get(trim) if layout == "print" else PAPER_SIZES.get(paper)
    findings: list[Finding] = []
    problems = structural_problems(path, expected=expected)
    if problems:
        findings.append(Finding(
            "error",
            "The file did not come out right: " + "; ".join(problems[:3])
            + ". Please export again; if it happens twice, report it with this message.",
        ))
    pages = page_count(path.read_bytes()) if path.is_file() else 0
    whole_book = book.kind == "book"
    manuscript = style == "manuscript"

    if whole_book and not title_given:
        findings.append(Finding(
            "warning", f"The title “{book.title}” comes from the folder name. Add the book’s real title.",
            fix="title",
        ))
    if (whole_book or manuscript) and not book.author.strip():
        findings.append(Finding(
            "warning", "Add the author’s name. It goes on the title page and the running heads.", fix="author",
        ))
    if manuscript and not contact.strip():
        findings.append(Finding(
            "warning", "Add your contact details (email, phone) so an agent can reply. They go on the "
            "title page.", fix="contact",
        ))
    if layout == "print" and whole_book:
        if pages < KDP_MIN_PAGES:
            findings.append(Finding(
                "warning", f"The book is {pages} pages. A paperback needs at least {KDP_MIN_PAGES}.",
            ))
        elif pages > KDP_MAX_PAGES:
            findings.append(Finding(
                "warning", f"The book is {pages} pages. KDP prints paperbacks up to {KDP_MAX_PAGES}; "
                "try a larger trim size.",
            ))

    if any(f.level == "error" for f in findings):
        headline, ready = "This file has a problem", False
    elif any(f.level == "warning" for f in findings):
        headline, ready = "Almost ready: fix the items below first", False
    elif layout == "print" and whole_book:
        headline, ready = f"Ready to upload to KDP as a {TRIM_LABELS.get(trim, trim)} paperback interior", True
    elif manuscript:
        headline, ready = "Ready to send to an agent or editor", True
    elif layout == "print":
        headline, ready = f"A {TRIM_LABELS.get(trim, trim)} proof of this part, ready to print", True
    else:
        headline, ready = f"Ready to share ({PAPER_LABELS.get(paper, paper)}, {pages} pages)", True
    return {"ready": ready, "headline": headline, "findings": [f.to_dict() for f in findings], "pages": pages}
