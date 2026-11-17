"""Check a scene review's line links against the manuscript.

A review cites evidence as ``[label](manuscript/scene.md#L94)``. Reading ten
scenes at once, the model sometimes keeps the right line and names the wrong
scene, or quotes a passage from a few lines away. Each link is checked against
the text it stands for:

* A link that follows a quote (inline or as the blockquote above it) must
  point at lines holding that quote. If it does not, the quote is looked up in
  the cited scene and then in the other supplied scenes; a single match
  corrects the link.
* A quote spanning several lines gets a link covering all of them.
* A link into a scene the review was not given (a setup in an earlier
  chapter, say) is checked against that scene's own text.
* A link without a quote is checked by its words. If the cited lines share no
  distinctive word with the sentence citing them, and exactly one other supplied
  scene does at that line, the link is moved to that scene.

Links that still do not match are listed in a short note under the review, so
the writer knows which ones to check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .repo import read_repo_text

#: The receipt every scene review's request carries, naming its scenes.
_SCENES_RE = re.compile(r"\(Scenes analyzed \(\d+\): (?P<paths>[^\n]*?)\. Analyze the attached scenes")
_LINK_RE = re.compile(
    r"\[(?P<label>[^\]\n]*)\]\(<?(?P<path>[^)\s<>#]+)#L(?P<start>\d+)(?:[-–—]L?(?P<end>\d+))?>?\)"
)
# A quoted passage directly before a link: *"..."*, *...*, "..." or “...”.
_INLINE_QUOTE_RE = re.compile(r"(?:\*\"(?P<a>[^\"\n]{6,}?)\"?\*|\*(?P<b>[^*\n]{6,}?)\*|\"(?P<c>[^\"\n]{6,}?)\"|“(?P<d>[^”\n]{6,}?)”)")
_BETWEEN_QUOTE_AND_LINK = re.compile(r"^[\s,.;:()\[\]—–-]*$")
_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    "about after again being before could every first from have into just later might never other "
    "scene their there these thing those through under until where which while would your yours "
    "line lines still again what when with without that this then than them they were".split()
)
#: Lines around a cited line that may still hold its passage (hard-wrapped prose).
_WINDOW_BEFORE = 2
_WINDOW_AFTER = 8
#: How far a quote may begin from its cited line and still count as there.
_QUOTE_SLACK = 2


@dataclass
class _Scene:
    path: str
    lines: list[str]

    def window(self, start: int, end: int) -> str:
        lo = max(1, start - _WINDOW_BEFORE)
        hi = min(len(self.lines), max(start, end) + _WINDOW_AFTER)
        return " ".join(self.lines[lo - 1:hi])

    def find_all(self, probe: str) -> list[int]:
        """Every line where ``probe`` begins, allowing it to wrap across lines."""
        joined = ""
        starts: list[int] = []
        for line in self.lines:
            starts.append(len(joined))
            joined += line + " "
        found: list[int] = []
        at = joined.find(probe)
        while at >= 0:
            line = 1
            for index, offset in enumerate(starts, 1):
                if offset <= at:
                    line = index
                else:
                    break
            found.append(line)
            at = joined.find(probe, at + 1)
        return found

    def end_of(self, quote: str, start: int) -> int | None:
        """The line where ``quote`` ends, when it begins at ``start``.

        Found by its last words, so a quote across a paragraph break still
        resolves. None when the ending is not where the quote should be.
        """
        words = quote.split()
        tail = " ".join(words[-8:])
        if len(words) < 3 or len(tail) < 6:
            return None
        joined = ""
        starts: list[int] = []
        for line in self.lines:
            starts.append(len(joined))
            joined += line + " "
        begin = starts[start - 1] if 0 < start <= len(starts) else 0
        at = joined.find(tail, begin)
        if at < 0:
            return None
        last = at + len(tail) - 1
        end = max(index for index, offset in enumerate(starts, 1) if offset <= last)
        return end if end - start <= 40 else None

    def find(self, probe: str) -> int | None:
        found = self.find_all(probe)
        return found[0] if found else None

    def quote_starts_near(self, probe: str, start: int, end: int) -> bool:
        """Whether the quote begins at the cited lines, give or take a wrap."""
        return any(
            start - _QUOTE_SLACK <= line <= max(start, end) + _QUOTE_SLACK
            for line in self.find_all(probe)
        )


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    return " ".join(_WORD_RE.findall(text))


def _distinctive(text: str) -> set[str]:
    return {w for w in _normalize(text).split() if len(w) >= 5 and w not in _STOPWORDS}


def review_scene_paths(request_text: str) -> list[str]:
    """The scenes a review request supplied, in order."""
    text = str(request_text or "")
    if not (text.startswith("Craft review · ") or "\n\nScene review instructions:\n" in text):
        return []
    match = _SCENES_RE.search(request_text)
    if not match:
        return []
    return [part.strip() for part in match.group("paths").split(",") if part.strip()]


def _load(root: Path, paths: list[str], *, live_documents: dict[str, str] | None = None) -> dict[str, _Scene]:
    scenes: dict[str, _Scene] = {}
    base = root.resolve()
    for rel in paths:
        if live_documents and rel in live_documents:
            scenes[rel] = _Scene(rel, [_normalize(line) for line in live_documents[rel].split("\n")])
            continue
        target = (base / rel).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            continue
        try:
            text = read_repo_text(target)
        except (OSError, UnicodeError):
            continue
        scenes[rel] = _Scene(rel, [_normalize(line) for line in text.split("\n")])
    return scenes


def _quote_before(line: str, link_start: int) -> str:
    """The quoted passage that ends right before a link on the same line."""
    best = ""
    for match in _INLINE_QUOTE_RE.finditer(line, 0, link_start):
        if _BETWEEN_QUOTE_AND_LINK.match(line[match.end():link_start]):
            best = next(group for group in match.groups() if group)
    return best


def _blockquote_above(lines: list[str], index: int) -> tuple[str, bool, str]:
    """The first line of the blockquote directly above a link on its own line.

    Also says whether it is italic, the house style for quoted manuscript text,
    and gives the whole quote. A plain blockquote may be a suggested
    replacement rather than evidence.
    """
    j = index - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    block: list[str] = []
    while j >= 0 and lines[j].lstrip().startswith(">"):
        block.insert(0, lines[j])
        j -= 1
    whole = " ".join(re.sub(r"^[\s>]+", "", raw).strip().strip("*_").strip() for raw in block)
    for raw in block:
        body = re.sub(r"^[\s>]+", "", raw).strip()
        text = body.strip("*_").strip()
        if len(_normalize(text)) >= 6:
            return text, body.startswith(("*", "_")), whole
    return "", False, ""


def _probe(quote: str) -> str:
    """A searchable slice of a quote: its first words, without a dangling cut."""
    words = _normalize(quote).split()
    return " ".join(words[:10])


def _relabel(label: str, old_path: str, new_path: str, old_start: int, new_start: int,
             old_end: int | None, new_end: int | None) -> str:
    if new_path != old_path:
        label = label.replace(Path(old_path).name, Path(new_path).name)
        label = label.replace(Path(old_path).stem, Path(new_path).stem)
    if new_start != old_start:
        if old_end and new_end:
            label = re.sub(rf"\b{old_start}(\s*[-–—]\s*){old_end}\b", f"{new_start}\\g<1>{new_end}", label)
        label = re.sub(rf"(?<!\d){old_start}(?!\d)", str(new_start), label, count=1)
    if new_end and not old_end:
        label = re.sub(rf"\b([Ll])ine (\d+)\b", lambda m: f"{m.group(1)}ines {m.group(2)}–{new_end}", label, count=1)
    return label


def verify_review_citations(
    root: Path,
    request_text: str,
    answer: str,
    *,
    report_unfound: bool = True,
    live_documents: dict[str, str] | None = None,
) -> str:
    """Return ``answer`` with wrong-scene and drifted line links corrected.

    Only scene reviews are checked: links into the scenes they were given,
    and quoted links into other manuscript files. Anything that cannot be confirmed is listed in a closing note,
    unless ``report_unfound`` is off: a reopened review is checked against
    today's manuscript, where a revised passage is not the review's mistake.
    """
    paths = review_scene_paths(request_text)
    if not paths or "#L" not in str(answer or ""):
        return answer
    scenes = _load(root, paths, live_documents=live_documents)
    if not scenes:
        return answer

    outside: dict[str, _Scene | None] = {}

    def outside_scene(path: str) -> _Scene | None:
        if path not in outside:
            outside[path] = (_load(root, [path], live_documents=live_documents).get(path)
                             if path.endswith(".md") else None)
        return outside[path]

    corrected = 0
    unverified: list[str] = []
    out_lines = answer.split("\n")
    for index, line in enumerate(out_lines):
        if "#L" not in line:
            continue
        pieces: list[str] = []
        cursor = 0
        for match in _LINK_RE.finditer(line):
            path = match.group("path")
            supplied = path in scenes
            scene = scenes[path] if supplied else outside_scene(path)
            if scene is None:
                continue
            start = int(match.group("start"))
            end = int(match.group("end")) if match.group("end") else None
            new_path, new_start, new_end = path, start, end

            quote = _quote_before(line, match.start())
            flaggable = bool(quote)
            whole = quote
            if not quote and not line[:match.start()].strip("([ "):
                quote, flaggable, whole = _blockquote_above(out_lines, index)
            moved = False
            if quote:
                probe = _probe(quote)
                if len(probe) >= 6 and not scene.quote_starts_near(probe, start, end or start):
                    moved = True
                    found = scene.find(probe)
                    if found is not None:
                        new_start = found
                    else:
                        pool = [other for other in scenes.values() if other is not scene]
                        hits = [(other, other.find(probe)) for other in pool]
                        hits = [(other, at) for other, at in hits if at is not None]
                        if len(hits) == 1:
                            new_path, new_start = hits[0][0].path, hits[0][1]
                        elif flaggable:
                            unverified.append(match.group("label") or f"{Path(path).name} · Line {start}")
                    if new_start != start and end:
                        new_end = end + (new_start - start)
                located = len(probe) >= 6 and (
                    (new_path, new_start) != (path, start) or scene.quote_starts_near(probe, start, end or start))
                if located:
                    # Snapping a link to the line where its quote begins, a wrap
                    # away, and widening it to cover the whole quote are
                    # refinements, not mistakes worth reporting.
                    home = scenes.get(new_path) or outside_scene(new_path)
                    if home and not moved:
                        begins = [at for at in home.find_all(probe)
                                  if start - _QUOTE_SLACK <= at <= max(start, end or start) + _QUOTE_SLACK]
                        if begins and begins[0] != start:
                            new_start = begins[0]
                            if end:
                                new_end = max(end, new_start)
                    last = home.end_of(_normalize(whole), new_start) if home else None
                    if last and last > (new_end or new_start):
                        new_end = last
            elif not supplied:
                continue
            else:
                cell = line[:match.start()].split("|")[-1]
                words = _distinctive(" ".join(cell.split()[-14:]))
                if len(words) >= 2 and not (words & set(scene.window(start, end or start).split())):
                    matches = [
                        other for other in scenes.values()
                        if other is not scene and len(words & set(other.window(start, end or start).split())) >= 2
                    ]
                    if len(matches) == 1:
                        new_path, moved = matches[0].path, True

            if (new_path, new_start, new_end) == (path, start, end):
                continue
            if moved and (new_path, new_start) != (path, start):
                corrected += 1
            label = _relabel(match.group("label"), path, new_path, start, new_start, end, new_end)
            target = f"{new_path}#L{new_start}" + (f"-L{new_end}" if new_end else "")
            pieces.append(line[cursor:match.start()])
            pieces.append(f"[{label}]({target})")
            cursor = match.end()
        if pieces:
            pieces.append(line[cursor:])
            out_lines[index] = "".join(pieces)

    result = "\n".join(out_lines)
    notes: list[str] = []
    if corrected:
        notes.append(
            f"Prosview corrected {corrected} line {'link' if corrected == 1 else 'links'} "
            "that pointed at the wrong place."
        )
    if unverified and report_unfound:
        shown = ", ".join(dict.fromkeys(unverified))
        notes.append(
            "Prosview could not find the quoted text for "
            + ("this link" if len(set(unverified)) == 1 else "these links")
            + f" where it points: {shown}. Check before relying on "
            + ("it." if len(set(unverified)) == 1 else "them.")
        )
    if notes:
        result = result.rstrip() + "\n\n---\n*Citation check: " + " ".join(notes) + "*"
    return result
