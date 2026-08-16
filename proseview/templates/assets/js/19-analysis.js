        // ── Analysis tab ────────────────────────────────────────────────────
        //
        // The lexical and style passes cost roughly 60% of a dashboard build
        // and nothing on the Overview tab reads them, so the server no longer
        // runs them on every rebuild. This tab fetches them from
        // /analysis.json the first time it is opened, and again after a
        // content reload has invalidated the server's cache.

        let _analysisLoaded = false;
        let _analysisLoading = false;

        function markAnalysisStale() {
            _analysisLoaded = false;
            if (currentTab === 'analysis') buildAnalysisTab();
        }

        function setAnalysisStatus(text) {
            const el = document.getElementById('analysisStatus');
            if (!el) return;
            el.textContent = text || '';
            el.hidden = !text;
        }

        function buildAnalysisTab() {
            if (_analysisLoaded || _analysisLoading) return;
            _analysisLoading = true;
            setAnalysisStatus('Analysing the manuscript\u2026');

            // Without a deadline a stalled request leaves the tab saying
            // "Analysing…" forever, which is indistinguishable from working.
            const controller = new AbortController();
            const deadline = setTimeout(function() { controller.abort(); }, 30000);

            fetch('/analysis.json', { headers: pvHeaders(), signal: controller.signal })
                .then(function(r) {
                    if (!r.ok) throw new Error('analysis failed (' + r.status + ')');
                    return r.json();
                })
                .then(function(data) {
                    // Unhide first: makeChart sizes each canvas from its
                    // parent's offsetWidth, which is 0 while the panel is
                    // hidden and silently falls back to a 400px default.
                    const content = document.getElementById('analysisContent');
                    if (content) content.hidden = false;
                    setAnalysisStatus('');
                    renderAnalysis(data);
                    _analysisLoaded = true;
                })
                .catch(function(err) {
                    setAnalysisStatus(err.name === 'AbortError'
                        ? 'The analysis timed out. Reload to try again.'
                        : 'Could not analyse the manuscript: ' + err.message);
                })
                .finally(function() {
                    clearTimeout(deadline);
                    _analysisLoading = false;
                });
        }

        function renderAnalysis(data) {
            const alerts = document.getElementById('analysisAlerts');
            if (alerts) alerts.innerHTML = data.alertsHtml || '';

            const body = document.getElementById('analysisTableBody');
            if (body) body.innerHTML = data.tableBody || '';

            const lex = data.lexical || {};
            const setText = function(id, value) {
                const el = document.getElementById(id);
                if (el) el.textContent = value || '';
            };
            const setLeftWidth = function(id, left, width) {
                const el = document.getElementById(id);
                if (!el) return;
                el.style.left = left + '%';
                if (width !== undefined) el.style.width = width + '%';
            };
            setText('analysisMattrText', lex.mattrText);
            setText('analysisMtldText', lex.mtldText);
            setLeftWidth('analysisMattrZone', lex.mattrZoneLeft, lex.mattrZoneWidth);
            setLeftWidth('analysisMattrMarker', lex.mattrMarkerLeft);
            setLeftWidth('analysisMtldZone', lex.mtldZoneLeft, lex.mtldZoneWidth);
            setLeftWidth('analysisMtldMarker', lex.mtldMarkerLeft);

            buildAnalysisCharts(data);
        }

        function applyAnalysisIssueFilter() {
            const mode = (document.getElementById('analysisIssueFilter') || {}).value || 'all';
            document.querySelectorAll('#analysisSceneTable tbody tr.scene-row').forEach(function(row) {
                const dlg = parseFloat(row.dataset.dlg || '0');
                const sent = parseFloat(row.dataset.sent || '0');
                const rep = parseFloat(row.dataset.rep || '0');
                let show = true;
                if (mode === 'repetition') show = rep > 25;
                else if (mode === 'clipped') show = sent < 8;
                else if (mode === 'talky') show = dlg > 45;
                else if (mode === 'dense') show = dlg < 8;
                else if (mode === 'todos') show = parseInt(row.dataset.todos || '0', 10) > 0;
                else if (mode === 'notes') show = parseInt(row.dataset.notes || '0', 10) > 0;
                row.style.display = show ? '' : 'none';
            });
        }

        function sortAnalysisTable(col) {
            sortTableEl(document.getElementById('analysisSceneTable'), col);
        }
