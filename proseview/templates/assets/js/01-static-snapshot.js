        // ── Static snapshot ──────────────────────────────────────────────────
        // `proseview snapshot` writes this page as static files with no server
        // behind it. The reads a reader needs were written beside the page;
        // everything else -- saving, annotations, agents, live reload --
        // answers that the copy is read-only rather than failing on the
        // network. Every call site names a route from the origin root, which a
        // copy hosted under a project path would miss, so they all come here.
        (function installStaticSnapshot() {
            if (!window.PROSEVIEW_STATIC) return;
            const realFetch = window.fetch.bind(window);
            let lexicalByScene = null;

            function jsonResponse(body, status) {
                return new Response(JSON.stringify(body), {
                    status: status || 200,
                    headers: {'Content-Type': 'application/json'},
                });
            }

            function sceneLexical(url) {
                if (!lexicalByScene) {
                    lexicalByScene = realFetch('scene-lexical.json').then(function(response) {
                        return response.json();
                    });
                }
                const scene = url.searchParams.get('path') || '';
                return lexicalByScene.then(function(rows) {
                    return rows[scene]
                        ? jsonResponse(rows[scene])
                        : jsonResponse({ok: false, error: 'scene not found'}, 404);
                });
            }

            // The demo lets a visitor try edit mode. A save is accepted here
            // and goes no further: the editor keeps the text in memory, so it
            // lasts until the tab is reloaded and is never uploaded.
            let demoSaves = 0;
            function demoSave() {
                demoSaves += 1;
                return Promise.resolve(jsonResponse({
                    ok: true, mtime: Date.now() / 1000, revision: 'demo-' + demoSaves,
                }));
            }

            // Export, in the demo only: the books were built when the snapshot
            // was written (export_demo.py), one per style and format, and the
            // dialog's requests are answered from them.
            let demoExports = null;
            let lastExport = null;
            function exportIndex() {
                if (!demoExports) {
                    demoExports = realFetch('export/files.json').then(function(response) { return response.json(); });
                }
                return demoExports;
            }
            function demoBody(init) {
                try { return JSON.parse((init && init.body) || '{}'); } catch (error) { return {}; }
            }
            function demoFormats(details) {
                const format = details.format || 'epub';
                return format === 'all' ? ['epub', 'pdf-print', 'pdf-share'] : [format];
            }
            const notInDemo = 'The demo cannot save files. On your own computer, Proseview does this for you.';
            function demoExport(url, init) {
                const path = url.pathname;
                if (path === '/api/export/outline') return realFetch('export/outline.json');
                if (path === '/api/export/preview') {
                    const body = demoBody(init);
                    const details = body.details || {};
                    const formats = demoFormats(details);
                    const format = formats.indexOf(body.preview) >= 0 ? body.preview : formats[0];
                    return realFetch('export/previews/' + (details.style || 'classic') + '-' + format + '.json');
                }
                if (path === '/api/export/start') {
                    lastExport = demoBody(init).details || {};
                    return Promise.resolve(jsonResponse({ok: true, id: 'demo', state: 'running', step: 'Starting', fraction: 0}, 202));
                }
                if (path === '/api/export/jobs/demo') {
                    return exportIndex().then(function(index) {
                        const details = lastExport || {};
                        const files = demoFormats(details).map(function(format) {
                            return index.files[(details.style || 'classic') + '-' + format];
                        }).filter(Boolean);
                        return jsonResponse({
                            ok: true, id: 'demo', state: 'done', step: 'Done', fraction: 1,
                            result: Object.assign({files: files, kind: 'book', saved_selection: ''}, index.book),
                        });
                    });
                }
                return Promise.resolve(jsonResponse({ok: false, error: notInDemo}, 400));
            }

            window.fetch = function(input, init) {
                const url = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
                if (window.PROSEVIEW_STATIC_EDITS && url.pathname.indexOf('/api/export/') === 0) return demoExport(url, init);
                if (url.pathname === '/analysis.json') return realFetch('analysis.json', init);
                if (url.pathname === '/api/scene/lexical') return sceneLexical(url);
                if (url.pathname === '/save-scene' && window.PROSEVIEW_STATIC_EDITS) return demoSave();
                if (url.pathname === '/api/files/save' && window.PROSEVIEW_STATIC_EDITS) return demoSave();
                return Promise.resolve(jsonResponse({ok: false, error: 'This is a read-only snapshot.'}, 503));
            };

            // Nothing will ever change underneath a snapshot, so live reload
            // listens to a source that stays connecting and never speaks.
            function StaticEventSource(url) {
                this.url = String(url);
                this.readyState = 0;
                this.onmessage = null;
                this.onerror = null;
                this.onopen = null;
            }
            StaticEventSource.CONNECTING = 0;
            StaticEventSource.OPEN = 1;
            StaticEventSource.CLOSED = 2;
            StaticEventSource.prototype.addEventListener = function() {};
            StaticEventSource.prototype.removeEventListener = function() {};
            StaticEventSource.prototype.close = function() { this.readyState = 2; };
            window.EventSource = StaticEventSource;
        })();
