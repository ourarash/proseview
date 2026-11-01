// Lets Chrome and Edge install the dashboard as its own app. Nothing is
// cached: every request still goes to the local server. The only thing added
// is a plain page, instead of the browser's error, when the app is opened
// while proseview is not running.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
    if (event.request.mode !== 'navigate') return;
    event.respondWith(fetch(event.request).catch(() => new Response(
        '<!DOCTYPE html><meta charset="utf-8"><title>Proseview</title>'
        + '<body style="font:16px system-ui;margin:4em auto;max-width:32em;padding:0 1em">'
        + '<h1 style="font-size:1.3em">Proseview is not running</h1>'
        + '<p>Run <code>proseview</code> in your book folder, then '
        + '<a href="/">reload</a>.</p>',
        {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8'}},
    )));
});
