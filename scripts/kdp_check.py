"""Check print PDFs against KDP's published paperback interior requirements.

    python scripts/kdp_check.py --root fixtures/demo-book --out exports/preview/kdp \
        --title "Alice's Adventures in Wonderland" --author "Lewis Carroll"

Builds the book's print interior in each style and trim size asked for, then
checks each PDF the way KDP's interior rules describe them (paperback, no
bleed), without uploading anything:

- every page is exactly the trim size, with no bleed added
- every font is embedded; nothing is encrypted; no form fields
- no transparency groups or soft masks (KDP flattens them, sometimes badly)
- the page count is within 24-828
- no text smaller than 7 pt
- the ink on every page stays inside KDP's margins: at least 0.25 in from the
  outside, top and bottom edges, and at least the gutter KDP asks for at that
  page count from the binding edge (left on right-hand pages, right on left)
- no more than two blank pages in a row before the last page

The margin check looks at where ink actually lands on each page, from the
same Typst layout rendered as images, so a running head or page number that
crept into the margin would show up. Writes a report beside the PDFs.
This is the strongest check possible offline; KDP's own previewer remains the
final word.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from proseview.book_styles import load_style  # noqa: E402
from proseview.config import Config  # noqa: E402
from proseview.export import export_book, prepare_book  # noqa: E402
from proseview.pdf import KDP_MAX_PAGES, KDP_MIN_PAGES, TRIM_SIZES, PdfOptions, gutter_for, render_pages  # noqa: E402
from proseview.pdf_check import pdf_facts  # noqa: E402

PPI = 72
#: KDP's minimum inside margin (no bleed) by page count, inches.
KDP_GUTTER = ((150, 0.375), (300, 0.5), (500, 0.625), (700, 0.75), (828, 0.875))
KDP_OUTSIDE = 0.25
MIN_FONT_PT = 7.0


def kdp_gutter(pages: int) -> float:
    return next((inches for limit, inches in KDP_GUTTER if pages <= limit), KDP_GUTTER[-1][1])


def _points(length: str) -> float:
    value, unit = float(length[:-2]), length[-2:]
    return value * (72.0 if unit == "in" else 72.0 / 25.4)


def png_ink_box(data: bytes, threshold: int = 235) -> tuple[int, int, int, int, int, int] | None:
    """Bounding box of non-white pixels in an 8-bit RGB(A) PNG: (x0, y0, x1, y1, width, height)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width = 8, b"", 0
    height = colour = 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and colour in (2, 6), "expects 8-bit RGB or RGBA"
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    channels = 4 if colour == 6 else 3
    raw = zlib.decompress(idat)
    stride = width * channels
    previous = bytearray(stride)
    x0, y0, x1, y1 = width, height, -1, -1
    at = 0
    for y in range(height):
        kind = raw[at]
        line = bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b = previous[i]
            c = previous[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        previous = line
        for x in range(width):
            px = x * channels
            alpha = line[px + 3] if channels == 4 else 255
            if alpha > 40 and min(line[px], line[px + 1], line[px + 2]) < threshold:
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
    return None if x1 < 0 else (x0, y0, x1, y1, width, height)


def smallest_font(data: bytes) -> float:
    """The smallest size set with Tf in the PDF's (Flate-compressed) content streams."""
    sizes = []
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        try:
            text = zlib.decompress(data[start:end])
        except zlib.error:
            continue
        sizes += [float(s) for s in re.findall(rb"/\S+\s+([\d.]+)\s+Tf", text)]
    return min(sizes) if sizes else 0.0


def check(pdf: Path, pngs: list[bytes], trim: str) -> list[str]:
    data = pdf.read_bytes()
    facts = pdf_facts(data)
    width, height = (round(_points(v), 1) for v in TRIM_SIZES[trim])
    problems = []
    if facts.page_sizes != ((width, height),):
        problems.append(f"page sizes {facts.page_sizes}, expected {width} × {height} pt")
    if re.search(rb"/(BleedBox|TrimBox)", data):
        problems.append("carries a bleed or trim box")
    if facts.unembedded_fonts:
        problems.append(f"fonts not embedded: {facts.unembedded_fonts}")
    if b"/Encrypt" in data:
        problems.append("encrypted")
    if b"/AcroForm" in data:
        problems.append("has form fields")
    if re.search(rb"/S\s*/Transparency", data) or b"/SMask" in data:
        problems.append("uses transparency (groups or soft masks)")
    if not KDP_MIN_PAGES <= facts.pages <= KDP_MAX_PAGES:
        problems.append(f"{facts.pages} pages, outside KDP's {KDP_MIN_PAGES}-{KDP_MAX_PAGES}")
    small = smallest_font(data)
    if small and small < MIN_FONT_PT:
        problems.append(f"text as small as {small:g} pt (KDP asks for at least {MIN_FONT_PT:g})")
    if len(pngs) != facts.pages:
        problems.append(f"rendered {len(pngs)} pages but the PDF has {facts.pages}")

    gutter = kdp_gutter(facts.pages)
    blank_run = worst_run = 0
    for number, png in enumerate(pngs, start=1):
        box = png_ink_box(png)
        if box is None:
            blank_run += 1
            if number < len(pngs):
                worst_run = max(worst_run, blank_run)
            continue
        blank_run = 0
        x0, y0, x1, y1, w, h = box
        left, right = x0 / PPI, (w - 1 - x1) / PPI
        top, bottom = y0 / PPI, (h - 1 - y1) / PPI
        # Page 1 is a right-hand page: its binding edge is on the left.
        inside, outside = (left, right) if number % 2 else (right, left)
        if inside < gutter - 0.02:
            problems.append(f"page {number}: ink {inside:.2f} in from the binding edge, KDP asks {gutter} in")
        for name, value in (("outside", outside), ("top", top), ("bottom", bottom)):
            if value < KDP_OUTSIDE - 0.02:
                problems.append(f"page {number}: ink {value:.2f} in from the {name} edge, KDP asks {KDP_OUTSIDE} in")
    if worst_run > 2:
        problems.append(f"{worst_run} blank pages in a row (KDP allows 2 before the last page)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--author", default="")
    parser.add_argument("--styles", default="classic,romance")
    parser.add_argument("--trims", default="5.5x8.5,6x9")
    args = parser.parse_args()
    root = args.root.resolve()
    cfg = Config.load(root)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’]", "", (args.title or root.name).lower())).strip("-")
    lines = ["# KDP interior check", "", f"Book: {args.title or root.name}", ""]
    failures = 0
    for style in args.styles.split(","):
        for trim in args.trims.split(","):
            pdf = args.out / f"{stem}-{style}-{trim}.pdf"
            result = export_book(root, cfg, pdf, fmt="pdf-print", style=style, trim=trim,
                                 title=args.title, author=args.author)
            book = prepare_book(root, cfg, title=args.title, author=args.author)
            pngs, _ = render_pages(book, PdfOptions(layout="print", style=load_style(style), trim=trim), ppi=PPI)
            problems = check(pdf, pngs, trim)
            failures += bool(problems)
            status = "PASS" if not problems else "FAIL"
            gutter = gutter_for(result.pages)
            lines.append(f"- {status} {pdf.name}: {result.pages} pages, gutter {gutter} in "
                         f"(KDP minimum {kdp_gutter(result.pages)} in), smallest text {smallest_font(pdf.read_bytes()):g} pt")
            lines += [f"    - {p}" for p in problems]
            print(lines[-1 - len(problems)])
            for p in problems:
                print("    ", p)
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
