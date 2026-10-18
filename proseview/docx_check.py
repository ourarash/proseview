"""Check a finished Word document and say, in plain words, whether it is ready.

The file is reopened and checked for what Word relies on to open it without
offering to "recover" it: the parts a document must have, XML that parses,
relationships that land, a content type for every part, and paragraph styles
that are all defined. A manuscript is also checked for the contact details
an agent needs to reply, as the PDF check does.
"""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .book import Book
from .epub_check import Finding

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"

REQUIRED_PARTS = (
    "[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels",
)


def structural_problems(path: Path) -> list[str]:
    """What is wrong with the Word document at *path*; empty when it is sound."""
    try:
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"the file cannot be opened as a Word document ({exc})"]
    missing = [name for name in REQUIRED_PARTS if name not in files]
    if missing:
        return ["it is missing " + ", ".join(missing)]

    problems: list[str] = []
    trees = {}
    for name, data in files.items():
        if name.endswith((".xml", ".rels")):
            try:
                trees[name] = ET.fromstring(data)
            except ET.ParseError as exc:
                problems.append(f"{name} is not well-formed ({exc})")
    if problems:
        return problems

    types = trees["[Content_Types].xml"]
    defaults = {node.get("Extension", "").lower() for node in types.iter(f"{_CT}Default")}
    overrides = {node.get("PartName", "").lstrip("/") for node in types.iter(f"{_CT}Override")}
    for name in files:
        if name == "[Content_Types].xml" or name in overrides:
            continue
        if name.rsplit(".", 1)[-1].lower() not in defaults:
            problems.append(f"{name} has no content type")
    problems += [f"the content types name {part}, which is not in the file" for part in overrides - set(files)]

    relationships: dict[str, set[str]] = {}
    for rels_name in [n for n in trees if n.endswith(".rels")]:
        folder = posixpath.dirname(posixpath.dirname(rels_name))
        ids = set()
        for rel in trees[rels_name].iter(f"{_PKG_REL}Relationship"):
            ids.add(rel.get("Id", ""))
            if rel.get("TargetMode") == "External":
                continue
            target = posixpath.normpath(posixpath.join(folder, rel.get("Target", "")))
            if target not in files:
                problems.append(f"{rels_name} points at {target}, which is not in the file")
        source = posixpath.join(folder, posixpath.basename(rels_name)[: -len(".rels")])
        relationships[source] = ids

    styles = {node.get(f"{_W}styleId") for node in trees["word/styles.xml"].iter(f"{_W}style")}
    for part in [n for n in trees if n.startswith("word/") and not n.endswith(".rels")]:
        tree = trees[part]
        for tag in ("pStyle", "rStyle"):
            for node in tree.iter(f"{_W}{tag}"):
                if node.get(f"{_W}val") not in styles:
                    problems.append(f"{part} uses a style that is not defined ({node.get(f'{_W}val')})")
                    break
        known = relationships.get(part, set())
        for node in tree.iter():
            for attr in (f"{_R}id", f"{_R}embed"):
                rid = node.get(attr)
                if rid and rid not in known:
                    problems.append(f"{part} refers to {rid}, which it does not define")
    if not "".join(node.text or "" for node in trees["word/document.xml"].iter(f"{_W}t")).strip():
        problems.append("it has no text")
    return problems


def readiness(
    path: Path,
    book: Book,
    *,
    style: str = "",
    title_given: bool = True,
    contact: str = "",
) -> dict:
    """Check the document at *path*; return a headline and the findings, like the EPUB and PDF checks."""
    findings: list[Finding] = []
    problems = structural_problems(path)
    if problems:
        findings.append(Finding(
            "error",
            "The file did not come out right: " + "; ".join(problems[:3])
            + ". Please export again; if it happens twice, report it with this message.",
        ))
    whole_book = book.kind == "book"
    manuscript = style == "manuscript"
    if whole_book and not title_given:
        findings.append(Finding(
            "warning", f"The title “{book.title}” comes from the folder name. Add the book’s real title.",
            fix="title",
        ))
    if (whole_book or manuscript) and not book.author.strip():
        findings.append(Finding(
            "warning", "Add the author’s name. It goes on the title page"
            + (" and at the top of every page." if manuscript else "."), fix="author",
        ))
    if manuscript and not contact.strip():
        findings.append(Finding(
            "warning", "Add your contact details (email, phone) so an agent can reply. They go on the "
            "title page.", fix="contact",
        ))

    if any(f.level == "error" for f in findings):
        headline, ready = "This file has a problem", False
    elif any(f.level == "warning" for f in findings):
        headline, ready = "Almost ready: fix the items below first", False
    elif manuscript:
        headline, ready = "Ready to send to an agent or editor", True
    else:
        headline, ready = "Ready to open in Word, Google Docs or Pages", True
    return {"ready": ready, "headline": headline, "findings": [f.to_dict() for f in findings], "pages": 0}
