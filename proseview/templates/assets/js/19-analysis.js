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


            const body = document.getElementById('analysisTableBody');
            if (body) body.innerHTML = data.tableBody || '';
            renderFindings(data.findings || []);

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
            setText('analysisMattrExplanationText', lex.mattrText);
            setText('analysisMtldExplanationText', lex.mtldText);
            setLeftWidth('analysisMattrZone', lex.mattrZoneLeft, lex.mattrZoneWidth);
            setLeftWidth('analysisMattrMarker', lex.mattrMarkerLeft);
            setLeftWidth('analysisMtldZone', lex.mtldZoneLeft, lex.mtldZoneWidth);
            setLeftWidth('analysisMtldMarker', lex.mtldMarkerLeft);
            renderMtldReferences(lex);

            // Yield to the browser so offsetWidth is updated after unhiding
            requestAnimationFrame(function() {
                buildAnalysisCharts(data);
            });
        }

        // Two reference points, and they answer different questions. The book's
        // own median says which scenes are unlike the rest of this book -- the
        // question a writer revising actually has. The genre range says whether
        // the book sits anywhere normal at all.
        //
        // The wording is deliberate: "typical range" and not "benchmark". The
        // 0.72 factor threshold behind MTLD has a citation (McCarthy & Jarvis,
        // 2010); these genre ranges are consensus figures, not something
        // measured here, and the label should not claim otherwise.
        function renderMtldReferences(lex) {
            const el = document.getElementById('analysisMtldRefs');
            if (!el) return;
            el.replaceChildren();
            if (!lex.mtldMedian) return;
            const band = Array.isArray(lex.mtldBand) ? lex.mtldBand : null;
            const median = document.createElement('span');
            median.className = 'health-ref';
            const formattedMedian = typeof lex.mtldMedian === 'number' ? Math.round(lex.mtldMedian) + ' words' : lex.mtldMedian;
            median.textContent = 'Your typical scene: ' + formattedMedian;
            median.title = 'The middle score of your scenes: half are above it, half below.';
            el.appendChild(median);
            if (!band) return;
            const genre = document.createElement('span');
            genre.className = 'health-ref';
            genre.textContent = 'Usual for ' + (lex.genreLabel || 'your range') + ': ' + band[0] + '–' + band[1] + ' words';
            genre.title = 'A typical range for published books in this genre. Below it is the concern; above it is fine. Change the genre in Settings.';
            el.appendChild(genre);
        }

        // The tab opens with what stands out, in sentences, each naming its
        // scenes and offering the table filtered to them.
        function renderFindings(findings) {
            const list = document.getElementById('analysisFindings');
            if (!list) return;
            list.replaceChildren();
            findings.forEach(function(finding) {
                const item = document.createElement('li');
                item.className = 'finding';
                const text = document.createElement('p');
                text.className = 'finding-text';
                text.textContent = finding.text;
                if (finding.tip) {
                    const tip = document.createElement('span');
                    tip.className = 'info-tip';
                    tip.tabIndex = 0;
                    tip.setAttribute('role', 'img');
                    tip.setAttribute('aria-label', finding.tip);
                    tip.dataset.tip = finding.tip;
                    tip.textContent = 'i';
                    text.appendChild(tip);
                }
                item.appendChild(text);
                const scenes = finding.scenes || [];
                if (scenes.length || finding.filter) {
                    const row = document.createElement('p');
                    row.className = 'finding-scenes';
                    scenes.forEach(function(scene) {
                        const link = document.createElement('button');
                        link.type = 'button';
                        link.className = 'finding-scene';
                        link.textContent = scene.title;
                        link.title = scene.path;
                        link.addEventListener('click', function() { openSceneModal(scene.path); });
                        row.appendChild(link);
                    });
                    if (finding.filter) {
                        const show = document.createElement('button');
                        show.type = 'button';
                        show.className = 'finding-show';
                        show.textContent = 'Show in the table';
                        show.addEventListener('click', function() { showAnalysisRows(finding.filter); });
                        row.appendChild(show);
                    }
                    item.appendChild(row);
                }
                list.appendChild(item);
            });
        }

        function showAnalysisRows(filter) {
            const details = document.getElementById('analysisTableDetails');
            const select = document.getElementById('analysisIssueFilter');
            if (details) details.open = true;
            if (select) select.value = filter;
            applyAnalysisIssueFilter();
            if (details) details.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        function applyAnalysisIssueFilter() {
            const mode = (document.getElementById('analysisIssueFilter') || {}).value || 'all';
            document.querySelectorAll('#analysisSceneTable tbody tr.ch-row').forEach(function(row) {
                row.style.display = mode === 'all' ? '' : 'none';
            });
            document.querySelectorAll('#analysisSceneTable tbody tr.scene-row').forEach(function(row) {
                const dlg = parseFloat(row.dataset.dlg || '0');
                const sent = parseFloat(row.dataset.sent || '0');
                const rep = parseFloat(row.dataset.rep || '0');
                let show = true;
                if (mode === 'review') show = row.dataset.review === '1';
                else if (mode === 'repetition') show = rep > 25;
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
