"""The editors' lossless save (``templates/assets/js/12-lossless-markdown.js``).

Runs the helper in Node against the vendored ProseMirror, with the same parser
and serializer the scene editor uses: an unedited document comes back byte for
byte, and an edit rewrites only the block it touched. Skipped without Node
(CI installs it).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "proseview" / "templates" / "assets" / "js" / "12-lossless-markdown.js"
VENDOR = REPO_ROOT / "proseview" / "templates" / "vendor" / "pm"

NOTE = """Jack met [[Jack Mercer]] at the docks.

> [!note] Continuity
> He limps on the left side.
> Since chapter two.

![[map-of-the-harbor]]

- rope
- tar
- _salt_

She said it was ==important==, and _meant_ it.

<!-- TODO: check the tide tables -->

* * *

Last line with a [[link|alias]].
"""

# Edits the doc with ProseMirror's own model, then prints what the editor saves.
SCRIPT = r"""
import { Schema } from '%(vendor)s/prosemirror-model.js';
import { schema as mdSchema, MarkdownParser, MarkdownSerializer,
         defaultMarkdownParser, defaultMarkdownSerializer } from '%(vendor)s/prosemirror-markdown.js';
import { readFileSync } from 'node:fs';

defaultMarkdownParser.tokenizer.set({ html: true });
const schema = new Schema({
    nodes: mdSchema.spec.nodes.addBefore('image', 'annotation', {
        attrs: { raw: { default: '' } }, group: 'block', atom: true,
    }),
    marks: mdSchema.spec.marks,
});
let parser;
const makeParser = () => new MarkdownParser(schema, tokenizer,
    Object.assign({}, defaultMarkdownParser.tokens, {
        html_block: { node: 'annotation', getAttrs: tok => ({ raw: tok.content.trim() }) },
    }));
const serializer = new MarkdownSerializer(Object.assign({}, defaultMarkdownSerializer.nodes, {
    annotation(state, node) { state.write(node.attrs.raw); state.closeBlock(node); },
}), defaultMarkdownSerializer.marks);
const { markdownSourceBlocks, serializeKeepingSource, tokenizerKeepingInlineHtml } = new Function(
    readFileSync(%(helper)s, 'utf8')
    + '\nreturn { markdownSourceBlocks, serializeKeepingSource, tokenizerKeepingInlineHtml };')();
const tokenizer = tokenizerKeepingInlineHtml(defaultMarkdownParser.tokenizer);
parser = makeParser();

const { markdown, edit } = JSON.parse(readFileSync(0, 'utf8'));
let doc = parser.parse(markdown);
const saved = markdownSourceBlocks(tokenizer, markdown, doc, serializer);
const blocks = [];
doc.forEach(node => blocks.push(node));
if (edit.append !== undefined) {
    const node = blocks[edit.block];
    blocks[edit.block] = node.copy(node.content.append(
        schema.nodes.paragraph.create(null, schema.text(edit.append)).content));
}
if (edit.insert !== undefined) {
    blocks.splice(edit.block, 0, parser.parse(edit.insert).firstChild);
}
if (edit.remove !== undefined) blocks.splice(edit.remove, 1);
doc = doc.type.create(doc.attrs, blocks);
process.stdout.write(JSON.stringify({ lossless: !!saved, out: serializeKeepingSource(saved, doc, serializer) }));
"""


def _save(tmp_path: Path, markdown: str, **edit: object) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = tmp_path / "save.mjs"
    script.write_text(SCRIPT % {"vendor": VENDOR.as_uri(), "helper": json.dumps(str(HELPER))}, encoding="utf-8")
    proc = subprocess.run(
        [node, str(script)], input=json.dumps({"markdown": markdown, "edit": edit}),
        text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["lossless"], "the blocks should pair with the markdown-it tokens"
    return result["out"]


def test_an_unedited_note_saves_byte_for_byte(tmp_path: Path):
    assert _save(tmp_path, NOTE) == NOTE


def test_editing_one_paragraph_rewrites_only_that_paragraph(tmp_path: Path):
    out = _save(tmp_path, NOTE, block=0, append=" Then he left.")
    assert out == NOTE.replace("at the docks.", "at the docks. Then he left.", 1).replace(
        "[[Jack Mercer]] at", "\\[\\[Jack Mercer\\]\\] at", 1)


def test_an_inserted_scene_break_keeps_the_blocks_around_it(tmp_path: Path):
    out = _save(tmp_path, NOTE, block=1, insert="* * *")
    assert out == NOTE.replace("\n\n> [!note]", "\n\n---\n\n> [!note]", 1)


def test_a_deleted_block_leaves_the_rest_as_written(tmp_path: Path):
    out = _save(tmp_path, NOTE, remove=3)
    assert out == NOTE.replace("- rope\n- tar\n- _salt_\n\n", "", 1)


def test_deleting_the_last_block_keeps_the_final_newline(tmp_path: Path):
    out = _save(tmp_path, NOTE, remove=7)
    assert out == NOTE.replace("\n\nLast line with a [[link|alias]].\n", "\n", 1)


def test_inline_html_is_kept_as_text_rather_than_breaking_the_editor(tmp_path: Path):
    """``<br>`` inside a paragraph once made the parser throw, blanking the scene."""
    markdown = "He said it was important.<br>\nThen he left.\n\nA <span>quiet</span> morning.\n"
    assert _save(tmp_path, markdown) == markdown
    edited = _save(tmp_path, markdown, block=1, append=" Rain.")
    assert edited == "He said it was important.<br>\nThen he left.\n\nA <span>quiet</span> morning. Rain.\n"


WRAPPED = """As the next few weeks passed, our email exchange never settled into anything
solid. We sent each other jokes, short replies, and funny videos. Then
nothing for hours, sometimes days.

Campus made that kind of caution easy.
"""


def test_an_edited_paragraph_keeps_its_line_wrapping(tmp_path: Path):
    """A writer who wraps at 80 columns does not get one long line back."""
    out = _save(tmp_path, WRAPPED, block=0, append=" I would check my inbox - 1. then again.")
    first = out.split("\n\n")[0].split("\n")
    assert max(len(line) for line in first) <= 80
    assert " ".join(first) == (
        "As the next few weeks passed, our email exchange never settled into anything solid. "
        "We sent each other jokes, short replies, and funny videos. Then nothing for hours, "
        "sometimes days. I would check my inbox - 1. then again."
    )
    # No wrapped line may start a list, which would change what it means.
    assert not any(line.startswith(("- ", "1. ")) for line in first[1:])
    assert out.endswith("\n\nCampus made that kind of caution easy.\n")


def test_an_edit_moves_only_the_line_breaks_around_it(tmp_path: Path):
    out = _save(tmp_path, WRAPPED, block=0, append=" Again.")
    assert out == WRAPPED.replace("sometimes days.", "sometimes days. Again.", 1)
    chat = "Amir: hi\nNima: hey\nAmir: you up?\n\nEnd.\n"
    assert _save(tmp_path, chat, block=0, append=" no") == "Amir: hi\nNima: hey\nAmir: you up? no\n\nEnd.\n"
