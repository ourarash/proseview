// Runs Proseview's Python with Pyodide, off the page's main thread. The book
// is /my-novel, kept in the browser's storage (IndexedDB) and saved back after
// every change.
import { loadPyodide } from './pyodide/pyodide.mjs';

let pyodide = null;

const ready = (async () => {
  pyodide = await loadPyodide({ indexURL: new URL('./pyodide/', import.meta.url).href });
  const app = await (await fetch(new URL('./app.zip', import.meta.url))).arrayBuffer();
  pyodide.unpackArchive(app, 'zip', { extractDir: '/app' });
  pyodide.FS.mkdirTree('/my-novel');
  pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, '/my-novel');
  await sync(true);
  pyodide.runPython(`
import json, sys
sys.path.insert(0, "/app")
from proseview import browser
browser.seed()

def answer(method, path, body, headers):
    reply = browser.request(method, path, body.to_bytes() if body is not None else b"", json.loads(headers))
    return reply["status"], json.dumps(reply["headers"]), reply["body"], json.dumps(reply["events"])
`);
  await sync(false);
  return pyodide.globals.get('answer');
})();

function sync(load) {
  return new Promise((resolve, reject) => pyodide.FS.syncfs(load, (err) => (err ? reject(err) : resolve())));
}

self.onmessage = async (event) => {
  const { id, method, path, body, headers } = event.data;
  let reply;
  try {
    const answer = await ready;
    const result = answer(method, path, body || undefined, JSON.stringify(headers || {}));
    const [status, headersJson, payload, events] = result.toJs();
    result.destroy();
    const bytes = payload instanceof Uint8Array ? payload : payload.toJs();
    reply = { id, status, headers: JSON.parse(headersJson), body: bytes, events: JSON.parse(events) };
    if (method !== 'GET' && method !== 'HEAD') await sync(false);
  } catch (err) {
    reply = { id, status: 500, headers: { 'Content-Type': 'text/plain' }, body: new TextEncoder().encode(String(err)), events: [] };
  }
  self.postMessage(reply, [reply.body.buffer]);
};
