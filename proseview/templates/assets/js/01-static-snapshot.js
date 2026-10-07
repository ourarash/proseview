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

            window.fetch = function(input, init) {
                const url = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
                if (url.pathname === '/analysis.json') return realFetch('analysis.json', init);
                if (url.pathname === '/api/scene/lexical') return sceneLexical(url);
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
