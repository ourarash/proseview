"""Callouts in the scene editor (``templates/assets/js/14-callouts.js``).

Runs the editor's callout rule, schema and serializer in Node against the
vendored ProseMirror, as tests/test_lossless_markdown.py does for the save:
the same markers as :mod:`proseview.callouts` count as callouts, a callout
becomes a box with its title line, and a save writes ``> [!type]- Title``
back exactly. Skipped without Node (CI installs it).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from proseview.callouts import parse_marker

REPO_ROOT = Path(__file__).resolve().parents[1]
JS = REPO_ROOT / "proseview" / "templates" / "assets" / "js"
VENDOR = REPO_ROOT / "proseview" / "templates" / "vendor" / "pm"

SCRIPT = r"""
import { Schema } from '%(vendor)s/prosemirror-model.js';
import { schema as mdSchema, MarkdownParser, MarkdownSerializer,
         defaultMarkdownParser, defaultMarkdownSerializer } from '%(vendor)s/prosemirror-markdown.js';
import { readFileSync } from 'node:fs';

globalThis.window = {};
const load = (file, names) => new Function(readFileSync(file, 'utf8') + `\nreturn { ${names} };`)();
const C = load(%(callouts)s, 'parseCalloutMarker, calloutPlugin, calloutNodeSpec, calloutTitleNodeSpec, '
    + 'calloutParserTokens, calloutSerializerNodes');
const L = load(%(lossless)s, 'markdownSourceBlocks, serializeKeepingSource, tokenizerKeepingInlineHtml');

defaultMarkdownParser.tokenizer.set({ html: true });
C.calloutPlugin(defaultMarkdownParser.tokenizer);
const schema = new Schema({
    nodes: mdSchema.spec.nodes.addToEnd('annotation', { attrs: { raw: { default: '' } }, group: 'block', atom: true })
        .addToEnd('callout', C.calloutNodeSpec).addToEnd('callout_title', C.calloutTitleNodeSpec),
    marks: mdSchema.spec.marks,
});
const tokenizer = L.tokenizerKeepingInlineHtml(defaultMarkdownParser.tokenizer);
const parser = new MarkdownParser(schema, tokenizer, Object.assign({}, defaultMarkdownParser.tokens, C.calloutParserTokens, {
    html_block: { node: 'annotation', getAttrs: tok => ({ raw: tok.content.trim() }) },
}));
const serializer = new MarkdownSerializer(Object.assign({}, defaultMarkdownSerializer.nodes, C.calloutSerializerNodes, {
    annotation(state, node) { state.write(node.attrs.raw); state.closeBlock(node); },
}), defaultMarkdownSerializer.marks);

const { markdown, markers, edit } = JSON.parse(readFileSync(0, 'utf8'));
const out = { markers: markers.map(line => C.parseCalloutMarker(line)) };
if (markdown !== undefined) {
    let doc = parser.parse(markdown);
    out.tree = doc.toJSON();
    const saved = L.markdownSourceBlocks(tokenizer, markdown, doc, serializer);
    if (edit) {
        // Edit the first callout: its title, its type, or its last paragraph.
        const top = [];
        let done = false;
        doc.forEach(node => {
            if (done || node.type.name !== 'callout') { top.push(node); return; }
            done = true;
            const kids = [];
            node.forEach(child => kids.push(child));
            if (edit.title !== undefined) {
                kids[0] = schema.nodes.callout_title.create(null, edit.title ? schema.text(edit.title) : null);
            }
            if (edit.append !== undefined) {
                const last = kids[kids.length - 1];
                kids[kids.length - 1] = last.copy(last.content.addToEnd(schema.text(edit.append)));
            }
            top.push(node.type.create(Object.assign({}, node.attrs, edit.type ? { type: edit.type } : {}), kids));
        });
        doc = doc.type.create(doc.attrs, top);
    }
    out.saved = L.serializeKeepingSource(saved, doc, serializer);
    out.fresh = serializer.serialize(doc);
}
process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path: Path, **payload: object) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    script = tmp_path / "callouts.mjs"
    script.write_text(SCRIPT % {
        "vendor": VENDOR.as_uri(),
        "callouts": json.dumps(str(JS / "14-callouts.js")),
        "lossless": json.dumps(str(JS / "12-lossless-markdown.js")),
    }, encoding="utf-8")
    payload.setdefault("markers", [])
    proc = subprocess.run(
        [node, str(script)], input=json.dumps(payload), text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


MARKERS = [
    "[!NOTE]", "[!letter] A letter, undated", "[!sms]- Jonah, 11:42 pm", "[!Warning]+", "[!my-type]   Spaced  ",
    "[!] empty", "[!1st] digit first", "[note] no bang", " [!note] indented", "[!note]title glued", "text [!note]",
    "[!no te]",
]


def test_the_editor_and_the_exports_agree_on_what_is_a_marker(tmp_path: Path):
    got = _run(tmp_path, markers=MARKERS)["markers"]
    for line, js in zip(MARKERS, got):
        py = parse_marker(line)
        assert (None if js is None else (js["type"].lower(), js["fold"], js["title"])) == py, line


SCENE = """She found the letter.

> [!letter] A *letter*, undated
> Mara, if you are reading this.
>
> — T.

> Every harbour keeps one ghost.

> [!NOTE]-
> An untitled box.
"""


def test_a_callout_is_a_box_with_its_title_line(tmp_path: Path):
    tree = _run(tmp_path, markdown=SCENE)["tree"]["content"]
    assert [node["type"] for node in tree] == ["paragraph", "callout", "blockquote", "callout"]
    letter, untitled = tree[1], tree[3]
    assert letter["attrs"] == {"type": "letter", "fold": ""}
    assert letter["content"][0]["type"] == "callout_title"
    assert [part["text"] for part in letter["content"][0]["content"]] == ["A ", "letter", ", undated"]
    assert [node["type"] for node in letter["content"][1:]] == ["paragraph", "paragraph"]
    # No title: an empty title line, and the type kept as written.
    assert untitled["attrs"] == {"type": "NOTE", "fold": "-"}
    assert untitled["content"][0] == {"type": "callout_title"}


def test_an_unedited_scene_saves_byte_for_byte_and_serializes_the_same(tmp_path: Path):
    out = _run(tmp_path, markdown=SCENE)
    assert out["saved"] == SCENE
    # Even written fresh, the callouts keep their markers and lines.
    assert "> [!letter] A *letter*, undated\n> Mara, if you are reading this.\n>\n> — T.\n" in out["fresh"]
    assert out["fresh"].endswith("> [!NOTE]-\n> An untitled box.")
    assert "\\[!" not in out["fresh"]


def test_editing_a_callout_rewrites_only_that_callout_in_its_own_layout(tmp_path: Path):
    out = _run(tmp_path, markdown=SCENE, edit={"append": " Burn this."})
    assert out["saved"] == SCENE.replace("> — T.", "> — T. Burn this.")


def test_a_new_title_and_type_are_written_into_the_marker(tmp_path: Path):
    out = _run(tmp_path, markdown=SCENE, edit={"title": "From T.", "type": "sms"})
    assert out["saved"] == SCENE.replace("> [!letter] A *letter*, undated", "> [!sms] From T.")
    out = _run(tmp_path, markdown=SCENE, edit={"title": ""})
    assert out["saved"] == SCENE.replace("> [!letter] A *letter*, undated", "> [!letter]")


WRAPPED = """Before.

> [!letter] A note pinned to the hedge
> Alice, if you are reading this, the Rabbit has gone ahead.
> Do not wait by the river.
>
> — D.

> It was all very well to say
> "Drink me".
"""


def test_an_edited_callout_keeps_the_lines_of_its_paragraphs(tmp_path: Path):
    out = _run(tmp_path, markdown=WRAPPED, edit={"append": " (Burn this.)"})
    assert out["saved"] == WRAPPED.replace("> — D.", "> — D. (Burn this.)")
    out = _run(tmp_path, markdown=WRAPPED, edit={"title": "A note", "append": "!"})
    assert out["saved"] == WRAPPED.replace("hedge", "").replace("[!letter] A note pinned to the ", "[!letter] A note").replace("— D.", "— D.!")
