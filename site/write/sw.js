// Every request the dashboard makes (pages, fetches, images, previews,
// downloads) is answered by Proseview running in the page's worker, not by a
// server: this hands each one to the page that holds the worker.

const BASE = new URL('./', self.location).pathname;
// The app's own files, served from the site as they are.
const SHELL = new Set(['', 'index.html', 'worker.js', 'sw.js', 'app.zip', 'pyodide', 'vendor']);

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  let path = url.pathname;
  let page = false;
  if (path.startsWith(BASE)) {
    const rest = path.slice(BASE.length);
    if (SHELL.has(rest.split('/')[0])) return;
    // book is the dashboard itself, in the page's frame.
    page = rest === 'book';
    path = page ? '/' : '/' + rest;
  }
  event.respondWith(forward(event.request, path + url.search, page));
});

async function shell() {
  const windows = await self.clients.matchAll({ type: 'window' });
  return windows.find((client) => client.frameType === 'top-level' && new URL(client.url).pathname.startsWith(BASE));
}

async function forward(request, path, page) {
  const client = await shell();
  if (!client) return new Response('Proseview is not open in this browser.', { status: 503 });
  const body = request.method === 'GET' || request.method === 'HEAD'
    ? null : new Uint8Array(await request.arrayBuffer());
  const headers = {};
  request.headers.forEach((value, key) => { headers[key] = value; });
  const answer = await new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = (message) => resolve(message.data);
    client.postMessage({ type: 'proseview-request', method: request.method, path, body, headers, page }, [channel.port2]);
  });
  const empty = answer.status === 204 || answer.status === 304;
  return new Response(empty ? null : answer.body, { status: answer.status, headers: answer.headers });
}
