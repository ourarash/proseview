"""Check a finished EPUB and say, in plain words, whether it is ready.

Two kinds of check run after every dashboard export:

- :func:`structural_problems` reopens the file and checks what e-readers and
  store validators rely on: the ``mimetype`` entry, a manifest that matches
  the zip, a usable spine, well-formed pages, and links that land. It is the
  same check the test suite runs on every selection type, so a writer gets the
  guarantee the tests give without installing EPUBCheck (which needs Java).
- :func:`readiness` adds what a store asks of the book itself: a title and an
  author, a cover big enough for a store page, and a description for every
  image.

Findings are written for a writer, not a developer. Each names its cause and,
where there is one, the scene to open.
"""

from __future__ import annotations

import posixpath
import re
import struct
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree as ET

from .book import Book

OPF_NS = "{http://www.idpf.org/2007/opf}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
XHTML_NS = "{http://www.w3.org/1999/xhtml}"

#: The shortest side stores accept for a cover. Apple Books asks for 1400 px,
#: Kobo and KDP for 1600 px or more, so 1600 satisfies all three.
MIN_COVER_SIDE = 1600
#: KDP's ideal is 1.6:1 (2560 × 1600); anything squarer reads as a mistake.
MIN_COVER_RATIO = 1.3

STORES = "Apple Books, Kobo and KDP"


@dataclass(frozen=True)
class Finding:
    """One thing the writer should know about the exported book.

    ``level`` is ``error`` (the file is broken), ``warning`` (fix before a
    store will take it), or ``info`` (worth knowing, nothing to fix).
    ``fix`` names what the dashboard can do about it: ``scene`` (open
    *scene*), ``title``, ``author`` or ``cover`` (focus that field).
    """

    level: str
    message: str
    fix: str = ""
    scene: str = ""
    scene_title: str = ""

    def to_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value}


# --------------------------------------------------------------------------
# Structure


def structural_problems(path: Path) -> list[str]:
    """Return what is wrong with the EPUB container at *path*; empty when sound."""
    problems: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            files = {info.filename: archive.read(info) for info in infos}
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"the file cannot be opened as an e-book ({exc})"]

    if not infos or infos[0].filename != "mimetype":
        problems.append("the mimetype entry is not first")
    elif infos[0].compress_type != zipfile.ZIP_STORED or infos[0].extra:
        problems.append("the mimetype entry is compressed")
    if files.get("mimetype") != b"application/epub+zip":
        problems.append("the mimetype entry is wrong")

    try:
        container = ET.fromstring(files["META-INF/container.xml"])
        rootfile = container.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        opf = ET.fromstring(files[opf_path]) if opf_path else None
    except (KeyError, ET.ParseError):
        opf_path, opf = None, None
    if opf is None:
        return problems + ["the package file is missing or unreadable"]

    base = posixpath.dirname(opf_path)
    manifest = {item.get("id"): item for item in opf.iter(f"{OPF_NS}item")}
    hrefs = {posixpath.normpath(posixpath.join(base, item.get("href") or "")) for item in manifest.values()}
    packaged = set(files) - {"mimetype", "META-INF/container.xml", opf_path}
    if hrefs != packaged:
        problems.append("the list of contents does not match the files inside")
    spine = [ref.get("idref") for ref in opf.iter(f"{OPF_NS}itemref")]
    if not spine or any(idref not in manifest for idref in spine) or len(spine) != len(set(spine)):
        problems.append("the reading order is empty or names missing pages")

    unique = opf.get("unique-identifier")
    if not [el for el in opf.iter(f"{DC_NS}identifier") if el.get("id") == unique and (el.text or "").strip()]:
        problems.append("the book has no identifier")
    if opf.get("version") == "3.0":
        if not [i for i in manifest.values() if "nav" in (i.get("properties") or "").split()]:
            problems.append("the table of contents is missing")
        if not any(m.get("property") == "dcterms:modified" for m in opf.iter(f"{OPF_NS}meta")):
            problems.append("the book has no modification date")

    pages: dict[str, ET.Element] = {}
    for name, data in files.items():
        if name.endswith((".xhtml", ".ncx")):
            try:
                pages[name] = ET.fromstring(data)
            except ET.ParseError:
                problems.append(f"the page {posixpath.basename(name)} is not well-formed")
    ids = {name: [el.get("id") for el in tree.iter() if el.get("id")] for name, tree in pages.items()}
    for name, values in ids.items():
        if len(values) != len(set(values)):
            problems.append(f"the page {posixpath.basename(name)} repeats an anchor")
    for name, tree in pages.items():
        here = posixpath.dirname(name)
        for el in tree.iter():
            for attr in ("href", "src"):
                target = el.get(attr)
                if not target or target.startswith(("http:", "https:", "mailto:")):
                    continue
                file_part, fragment = urldefrag(target)
                resolved = posixpath.normpath(posixpath.join(here, unquote(file_part))) if file_part else name
                if resolved not in files or (fragment and fragment not in ids.get(resolved, [])):
                    problems.append(f"the page {posixpath.basename(name)} links to {target}, which is not there")
    return problems


# --------------------------------------------------------------------------
# Image sizes, without an imaging library


def image_size(data: bytes) -> tuple[int, int] | None:
    """``(width, height)`` of a PNG, JPEG, GIF or WebP, or ``None`` if unknown."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8 ":
            width, height = struct.unpack("<HH", data[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8X":
            return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
        return None
    if data.startswith(b"\xff\xd8"):
        at = 2
        while at + 9 < len(data):
            if data[at] != 0xFF:
                at += 1
                continue
            marker = data[at + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                at += 2
                continue
            length = struct.unpack(">H", data[at + 2:at + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[at + 5:at + 9])
                return width, height
            at += 2 + length
    return None


def cover_findings(data: bytes | None, *, whole_book: bool) -> list[Finding]:
    """What a store would say about the cover, if anything."""
    if data is None:
        if not whole_book:
            return []
        return [Finding("warning", "There is no cover yet. Stores need one before they list a book.", fix="cover")]
    size = image_size(data)
    if size is None:
        return []
    width, height = size
    if min(width, height) < MIN_COVER_SIDE:
        return [Finding(
            "warning",
            f"The cover is {width} × {height} px. Stores ask for at least {MIN_COVER_SIDE} px "
            f"on the short side; {MIN_COVER_SIDE} × {MIN_COVER_SIDE * 8 // 5} px is a safe size.",
            fix="cover",
        )]
    if height < width * MIN_COVER_RATIO:
        return [Finding(
            "warning",
            f"The cover is {width} × {height} px, wider than a book. Store covers are tall: "
            "about 1.6 times taller than wide.",
            fix="cover",
        )]
    return []


# --------------------------------------------------------------------------
# Readiness


_SCENE_ID = re.compile(r"scene-(\d+)-(\d+)")


def _images_without_descriptions(path: Path, book: Book) -> list[Finding]:
    by_position = {(s.chapter_number, s.scene_number): s for s in book.scenes}
    found: dict[str, Finding] = {}
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith(".xhtml") and "/cover" not in n]
        for name in names:
            try:
                tree = ET.fromstring(archive.read(name))
            except ET.ParseError:
                continue
            for section in tree.iter():
                match = _SCENE_ID.fullmatch(section.get("id") or "")
                if not match:
                    continue
                scene = by_position.get((int(match.group(1)), int(match.group(2))))
                images = [img for img in section.iter(f"{XHTML_NS}img") if not (img.get("alt") or "").strip()]
                if scene is not None and images and scene.key not in found:
                    found[scene.key] = Finding(
                        "warning",
                        f"An image in “{scene.title}” has no description. Readers who listen to "
                        "the book hear the description, and European stores ask for one: write it "
                        "between the brackets, like ![The bridge at night](…).",
                        fix="scene", scene=scene.key, scene_title=scene.title,
                    )
    return list(found.values())


def readiness(
    path: Path,
    book: Book,
    *,
    title_given: bool,
    cover: bytes | None,
) -> dict:
    """Check the exported book at *path*; return a headline and the findings.

    *title_given* is whether the writer set a title rather than letting it
    fall back to the folder name. A part of the book (a chapter, a scene, a
    selection) is meant for readers rather than a store, so it is only checked
    for soundness, not held to a store's rules about details and covers.
    """
    findings: list[Finding] = []
    problems = structural_problems(path)
    if problems:
        findings.append(Finding(
            "error",
            "The file did not come out right: " + "; ".join(problems[:3])
            + ". Please export again; if it happens twice, report it with this message.",
        ))
    whole_book = book.kind == "book"
    if whole_book:
        if not title_given:
            findings.append(Finding(
                "warning", f"The title “{book.title}” comes from the folder name. Add the book’s real title.",
                fix="title",
            ))
        if not book.author.strip():
            findings.append(Finding(
                "warning", "Add the author’s name. Stores and e-readers show it with the title.", fix="author",
            ))
        findings += cover_findings(cover, whole_book=True)
        findings += _images_without_descriptions(path, book)

    if any(f.level == "error" for f in findings):
        headline, ready = "This file has a problem", False
    elif any(f.level == "warning" for f in findings):
        headline, ready = "Almost ready: fix the items below before publishing", False
    elif whole_book:
        headline, ready = f"Ready for {STORES}", True
    else:
        headline, ready = "Ready to share with readers", True
    return {"ready": ready, "headline": headline, "findings": [f.to_dict() for f in findings]}
