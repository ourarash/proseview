"""Run the scene refresh code with controlled requests and timers in Node.

These exercise retries and overlapping requests without a browser or sleeps.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SELECTION_JS = Path(__file__).resolve().parents[1] / "proseview/templates/assets/js/60-selection.js"

HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const timers = new Map(), requests = [], rendered = [];
let timerId = 0;
const c = {
    document: {documentElement: {dataset: {view: 'scene'}}},
    paths: ['one.md', 'two.md'], curIdx: 0,
    contents: {'one.md': 'old one', 'two.md': 'old two'},
    meta: {}, highlightsByPath: {},
    _pmView: null, _pmEditMode: false, _pmDirty: false,
    _pendingSelfReloads: 0,
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, {fn, delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch(url) { return new Promise((resolve, reject) => requests.push({url, resolve, reject})); },
    updateModal() { rendered.push(c.contents[c.paths[c.curIdx]]); },
    setPmDirty(dirty) { c._pmDirty = dirty; },
};
vm.createContext(c);
const flush = () => new Promise(setImmediate);
async function tick() {
    assert.equal(timers.size, 1, 'one scheduled refresh');
    const [id, timer] = timers.entries().next().value;
    timers.delete(id);
    timer.fn();
    await flush();
}
async function respond(index, path, text) {
    requests[index].resolve({ok: true, json: async () => ({
        contents: {[path]: text}, meta: {[path]: {mtime: 2}},
        highlightsByPath: {[path]: {}},
    })});
    await flush();
}
"""


def _run_refresh_js(scenario: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    source = SELECTION_JS.read_text(encoding="utf-8")
    # Load the production refresh functions without the selection UI setup.
    refresh = source[source.index("        var _refreshTimer = null;"):source.index("        function hotSwapCss()")]
    script = HARNESS + "\nvm.runInContext(" + json.dumps(refresh) + ", c);\n"
    script += "(async () => {\n" + scenario + "\n})().catch(error => { console.error(error); process.exitCode = 1; });"
    result = subprocess.run(
        [node, "-"], input=script, text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", [
    "requests[0].reject(new Error('network interrupted'));",
    "requests[0].resolve({ok: false, status: 503});",
    "requests[0].resolve({ok: true, json: async () => { throw new SyntaxError('incomplete JSON'); }});",
])
def test_refresh_retries_transient_failure_without_another_file_event(failure: str):
    _run_refresh_js("""
        c.reloadOrDefer(['manuscript/one.md']);
    """ + failure + """
        await flush();
        assert.equal(c._scenesChangedOnDisk['one.md'], true);
        assert.equal(c.contents['one.md'], 'old one');
        assert.equal(c._refreshInFlight, false);
        await tick();
        assert.equal(requests.length, 2);
        await respond(1, 'one.md', 'latest agent edit');
        assert.equal(c.contents['one.md'], 'latest agent edit');
        assert.deepEqual(rendered, ['latest agent edit']);
        assert.equal(c._scenesChangedOnDisk['one.md'], undefined);
        assert.equal(timers.size, 0);
    """)


def test_refresh_retries_back_off_and_reset_after_success():
    _run_refresh_js("""
        c.reloadOrDefer(['one.md']);
        for (const [index, delay] of [1000, 2000, 4000, 8000, 10000, 10000].entries()) {
            requests[index].reject(new Error('offline'));
            await flush();
            assert.equal(timers.values().next().value?.delay, delay);
            await tick();
        }
        await respond(6, 'one.md', 'recovered');
        c.reloadOrDefer(['one.md']);
        requests[7].reject(new Error('new interruption'));
        await flush();
        assert.equal(timers.values().next().value?.delay, 1000);
    """)


@pytest.mark.parametrize("status", [403, 404])
def test_refresh_does_not_keep_retrying_a_permanent_error(status: int):
    _run_refresh_js(f"""
        c.reloadOrDefer(['one.md']);
        requests[0].resolve({{ok: false, status: {status}}});
        await flush();
        assert.equal(timers.size, 0);
        assert.equal(c._refreshInFlight, false);
    """)


@pytest.mark.parametrize("first_fails", [False, True])
def test_refresh_drains_queue_after_switching_scenes(first_fails: bool):
    first_response = (
        "requests[0].reject(new Error('interrupted')); await flush();" if first_fails
        else "await respond(0, 'one.md', 'new one');"
    )
    _run_refresh_js("""
        c.reloadOrDefer(['one.md']);
        c.curIdx = 1;
        c.reloadOrDefer(['two.md']);
    """ + first_response + """
        await tick();
        assert.equal(requests.length, 2);
        assert.equal(requests[1].url, '/scene-data?path=two.md');
        await respond(1, 'two.md', 'latest two');
        assert.deepEqual(rendered, ['latest two']);
        assert.equal(c._scenesChangedOnDisk['one.md'], true);
        assert.equal(c._refreshQueued, false);
    """)


def test_refresh_retry_preserves_unsaved_edits():
    _run_refresh_js("""
        c.reloadOrDefer(['one.md']);
        requests[0].reject(new Error('interrupted'));
        await flush();
        c._pmEditMode = true;
        c._pmDirty = true;
        await tick();
        assert.equal(requests.length, 1, 'no request while edits are unsaved');
        assert.equal(c.contents['one.md'], 'old one');
        assert.deepEqual(rendered, []);
        assert.equal(c._scenesChangedOnDisk['one.md'], true);
    """)


def test_refresh_response_preserves_edits_started_while_request_was_in_flight():
    _run_refresh_js("""
        c.reloadOrDefer(['one.md']);
        c._pmEditMode = true;
        c._pmDirty = true;
        await respond(0, 'one.md', 'agent edit');
        assert.equal(c.contents['one.md'], 'old one');
        assert.deepEqual(rendered, []);
        assert.equal(c._scenesChangedOnDisk['one.md'], true);
        assert.equal(timers.size, 0);
    """)
