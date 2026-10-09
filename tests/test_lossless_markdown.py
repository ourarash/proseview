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
const parser = new MarkdownParser(schema, defaultMarkdownParser.tokenizer,
    Object.assign({}, defaultMarkdownParser.tokens, {
        html_block: { node: 'annotation', getAttrs: tok => ({ raw: tok.content.trim() }) },
        html_inline: { ignore: true },
    }));
const serializer = new MarkdownSerializer(Object.assign({}, defaultMarkdownSerializer.nodes, {
    annotation(state, node) { state.write(node.attrs.raw); state.closeBlock(node); },
}), defaultMarkdownSerializer.marks);
const { markdownSourceBlocks, serializeKeepingSource } = new Function(
    readFileSync(%(helper)s, 'utf8') + '\nreturn { markdownSourceBlocks, serializeKeepingSource };')();

const { markdown, edit } = JSON.parse(readFileSync(0, 'utf8'));
let doc = parser.parse(markdown);
const saved = markdownSourceBlocks(defaultMarkdownParser.tokenizer, markdown, doc, serializer);
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
