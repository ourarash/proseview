"""Turn Project Gutenberg's Alice into a Proseview demo manuscript.

Alice's Adventures in Wonderland (1865) is public domain. Only the book text is
used; the Gutenberg header and footer are stripped so no PG trademark or licence
boilerplate ships in the fixture.

Chapters are split into scenes at paragraph boundaries, targeting roughly 700
words each, so the dashboard shows a real book's worth of rows rather than a
handful.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent / "alice.txt"
OUT = Path("/Users/ari/github/proseview/fixtures/demo-book")

TARGET_WORDS = 700

#: Recurring cast, matched case-sensitively on whole words.
CAST = [
    "Alice", "White Rabbit", "Mouse", "Dodo", "Lory", "Eaglet", "Bill",
    "Caterpillar", "Duchess", "Cheshire Cat", "Hatter", "March Hare",
    "Dormouse", "Queen", "King", "Gryphon", "Mock Turtle", "Knave", "Pigeon",
    "Footman", "Cook",
]

#: Titles and storylines, written by hand rather than sliced off the first
#: sentence: this manuscript is the demo's shop window, and "However, this
#: bottle was _not_ marked poison, so" is not a scene title.
#:
#: Threads follow Alice's recurring motifs, which genuinely interleave -- the
#: size changes and the White Rabbit both recur across the trial -- so the
#: Timeline lanes show real crossings rather than three consecutive blocks.
SCENES: list[tuple[str, str]] = [
    ("Down the Rabbit-Hole", "rabbit"),
    ("Down, Down, Down", "rabbit"),
    ("Drink Me", "size"),
    ("Curiouser and Curiouser", "size"),
    ("The Pool of Tears", "size"),
    ("A French Mouse", "wonderland"),
    ("A Queer-Looking Party", "wonderland"),
    ("The Caucus-Race", "wonderland"),
    ("Everyone Remembers Dinah", "wonderland"),
    ("The Rabbit Sends in a Little Bill", "rabbit"),
    ("Filling the Whole House", "size"),
    ("Bill Down the Chimney", "rabbit"),
    ("The Puppy and the Mushroom", "size"),
    ("Advice from a Caterpillar", "wonderland"),
    ("You Are Old, Father William", "wonderland"),
    ("Serpent!", "size"),
    ("Pig and Pepper", "wonderland"),
    ("The Duchess's Kitchen", "wonderland"),
    ("The Baby That Was a Pig", "wonderland"),
    ("The Cheshire Cat", "wonderland"),
    ("A Mad Tea-Party", "wonderland"),
    ("A Raven and a Writing-Desk", "wonderland"),
    ("The Treacle Well", "wonderland"),
    ("Painting the Roses Red", "court"),
    ("Off With Her Head", "court"),
    ("The Queen's Croquet-Ground", "court"),
    ("A Head to Cut Off", "court"),
    ("The Duchess Finds a Moral", "wonderland"),
    ("Everything's Got a Moral", "wonderland"),
    ("The Mock Turtle's Story", "wonderland"),
    ("The Lobster-Quadrille", "wonderland"),
    ("Whiting, and Why", "wonderland"),
    ("Voice of the Lobster", "wonderland"),
    ("Who Stole the Tarts?", "court"),
    ("The Hatter's Evidence", "court"),
    ("Suppressing the Guinea-Pigs", "court"),
    ("Alice's Evidence", "size"),
    ("Rule Forty-Two", "court"),
    ("Sentence First, Verdict Afterwards", "court"),
]


def strip_gutenberg(text: str) -> str:
    start = text.index("*** START OF THE PROJECT GUTENBERG")
    start = text.index("\n", start) + 1
    end = text.index("*** END OF THE PROJECT GUTENBERG")
    return text[start:end]


def chapters(text: str) -> list[tuple[str, str, str]]:
    """Return (roman, title, body) per chapter."""
    parts = re.split(r"^CHAPTER ([IVXL]+)\.\s*\n(.+?)\n", text, flags=re.M)
    out = []
    for i in range(1, len(parts), 3):
        out.append((parts[i], parts[i + 1].strip(), parts[i + 2]))
    return out


def paragraphs(body: str) -> list[str]:
    blocks = [re.sub(r"\s*\n\s*", " ", b).strip() for b in re.split(r"\n\s*\n", body)]
    return [b for b in blocks if b and not b.startswith("[Illustration")]


def split_into_scenes(paras: list[str]) -> list[list[str]]:
    scenes, current, words = [], [], 0
    for para in paras:
        current.append(para)
        words += len(para.split())
        if words >= TARGET_WORDS:
            scenes.append(current)
            current, words = [], 0
    if current:
        if scenes and words < TARGET_WORDS // 3:
            scenes[-1].extend(current)   # avoid a stub scene
        else:
            scenes.append(current)
    return scenes


def to_markdown(prose: str) -> str:
    """Convert Gutenberg's plain-text conventions to Markdown.

    ``_word_`` is its italic marker; left alone it shows up as literal
    underscores in the reading view.
    """
    return re.sub(r"_([^_\n]+)_", r"*\1*", prose)


def main() -> int:
    text = strip_gutenberg(SRC.read_text(encoding="utf-8"))
    beat = 0
    total_scenes = 0

    for path in sorted((OUT / "manuscript").rglob("*.md")):
        path.unlink()

    for chapter_no, (roman, chapter_title, body) in enumerate(chapters(text), start=1):
        scenes = split_into_scenes(paragraphs(body))
        chapter_dir = OUT / "manuscript" / f"ch{chapter_no:02d}"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        for i, paras in enumerate(scenes, start=1):
            prose = "\n\n".join(paras)
            beat += 1
            total_scenes += 1

            prose = to_markdown(prose)
            cast = [name for name in CAST if re.search(rf"\b{re.escape(name)}\b", prose)]
            title, thread = SCENES[beat - 1]

            front = [
                "---",
                f"title: {title}",
                f"chapter: {roman}. {chapter_title}",
                "status: drafted",
                f"thread: {thread}",
                f"day: {beat}",
                f"pov: Alice",
            ]
            if cast:
                front.append("characters:")
                front += [f"  - {name}" for name in cast[:6]]
            front.append("---")

            (chapter_dir / f"{i:02d}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40]}.md").write_text(
                "\n".join(front) + f"\n\n# {title}\n\n{prose}\n", encoding="utf-8"
            )

    print(f"  {total_scenes} scenes across {chapter_no} chapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
