        // ── Repo-wide search palette ──────────────────────────────────────
        // Pure client-side. Everything searchable is already in browser
        // memory: contents[path] (full prose), meta[path] (frontmatter,
        // todos, notes, abs_path), repoFileByPath (non-scene files under
        // repo_tab.folders). For a typical novel (~80k words / ~500KB)
        // substring scanning is microseconds in V8, so we just rescan on
        // every keystroke with a 50 ms debounce. No index, no library, no
        // server endpoint.

        const SEARCH_MIN_LEN = 2;
        const SEARCH_RESULT_CAP = 30;
        const SEARCH_PROSE_PER_SCENE = 2;
        const SEARCH_DEBOUNCE_MS = 50;
        const SEARCH_GROUP_ORDER = [
            ['FILES',  'Files'],
            ['SCENES', 'Scenes'],
            ['TODOS',  'TODOs'],
            ['NOTES',  'Notes'],
            ['PROSE',  'In prose'],
        ];
        const SEARCH_SCENE_FIELDS = [
            ['title',     function(fm) { return fm.title; }],
            ['chapter',   function(fm) { return fm.chapter; }],
            ['status',    function(fm) { return fm.status; }],
            ['where',     function(fm) { return fm.where || fm.location; }],
            ['pov',       function(fm) { return fm.pov; }],
            ['when',      function(fm) { return fm.when; }],
            ['goal',      function(fm) { return fm.goal; }],
            ['conflict',  function(fm) { return fm.conflict; }],
            ['outcome',   function(fm) { return fm.outcome; }],
        ];

        var _searchResults = [];
        var _searchCursor = -1;
        var _searchDebounceTimer = null;
        var _searchTotalHits = 0;
        const _searchParaOffsets = new Map();

        function _searchEscHtml(s) {
            return String(s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function _searchHighlight(haystack, needle) {
            // Wrap each case-insensitive needle occurrence in
            // <span class="search-hit">. Escapes HTML around the matches.
            if (!haystack) return '';
            const lowered = haystack.toLowerCase();
            const n = needle.toLowerCase();
            if (!n) return _searchEscHtml(haystack);
            let out = '';
            let cursor = 0;
            let idx;
            while ((idx = lowered.indexOf(n, cursor)) !== -1) {
                out += _searchEscHtml(haystack.substring(cursor, idx));
                out += '<span class="search-hit">' +
                    _searchEscHtml(haystack.substring(idx, idx + needle.length)) +
                    '</span>';
                cursor = idx + needle.length;
            }
            out += _searchEscHtml(haystack.substring(cursor));
            return out;
        }

        function _paraOffsetsFor(path) {
            // Map char-position-in-prose -> paragraph_blocks() index, so
            // a prose hit can navigate to the matching paragraph via the
            // existing _scrollToPara() jump-and-flash mechanism. Mirrors
            // paragraph_blocks() in scenes.py: split on blank lines, drop
            // heading blocks. Cached per scene because we rebuild only on
            // demand.
            if (_searchParaOffsets.has(path)) return _searchParaOffsets.get(path);
            const c = contents[path] || '';
            const paras = c.split(/\n\s*\n/);
            const offsets = [];
            let cursor = 0;
            let nonHeadingIdx = 0;
            for (const para of paras) {
                if (!para) continue;
                const start = c.indexOf(para, cursor);
                if (start < 0) continue;
                const end = start + para.length;
                const isHeading = /^\s*#/.test(para);
                offsets.push({
                    start: start,
                    end: end,
                    paraIdx: isHeading ? -1 : nonHeadingIdx,
                });
                if (!isHeading) nonHeadingIdx++;
                cursor = end;
            }
            _searchParaOffsets.set(path, offsets);
            return offsets;
        }

        function _paraAt(path, pos) {
            const offsets = _paraOffsetsFor(path);
            for (let i = 0; i < offsets.length; i++) {
                const o = offsets[i];
                if (pos >= o.start && pos < o.end) return o.paraIdx;
            }
            return -1;
        }

        function _proseSnippet(text, pos, needleLen) {
            const start = Math.max(0, pos - 32);
            const end = Math.min(text.length, pos + needleLen + 32);
            let s = text.substring(start, end).replace(/\s+/g, ' ').trim();
            if (start > 0) s = '… ' + s;
            if (end < text.length) s = s + ' …';
            return s;
        }

        function _runSearch(query) {
            // Returns a flat array of result objects, capped at
            // SEARCH_RESULT_CAP. Each result has at least:
            //   { category, path, isScene, primary, secondary }
            // Prose / todo / note results also carry `para` for the
            // scroll-into-view jump.
            const out = [];
            _searchTotalHits = 0;
            const q = query.toLowerCase();
            if (!q || q.length < SEARCH_MIN_LEN) return out;

            const seenFiles = new Set();
            const seenScenes = new Set();

            // 1. FILES — scene paths first, then non-scene repo files.
            for (let i = 0; i < paths.length; i++) {
                const p = paths[i];
                if (p.toLowerCase().indexOf(q) === -1) continue;
                seenFiles.add(p);
                _searchTotalHits++;
                if (out.length < SEARCH_RESULT_CAP) {
                    out.push({
                        category: 'FILES', path: p, isScene: true,
                        primary: p, secondary: 'scene',
                        primaryHi: _searchHighlight(p, query),
                    });
                }
            }
            const repoNodes = (typeof repoFileByPath === 'object' && repoFileByPath) || {};
            const repoKeys = Object.keys(repoNodes);
            for (let i = 0; i < repoKeys.length; i++) {
                const fp = repoKeys[i];
                if (seenFiles.has(fp)) continue;
                const node = repoNodes[fp];
                const nameHit = node && node.name && node.name.toLowerCase().indexOf(q) !== -1;
                const pathHit = fp.toLowerCase().indexOf(q) !== -1;
                if (!nameHit && !pathHit) continue;
                seenFiles.add(fp);
                _searchTotalHits++;
                if (out.length < SEARCH_RESULT_CAP) {
                    out.push({
                        category: 'FILES', path: fp, isScene: false,
                        primary: fp, secondary: 'file',
                        primaryHi: _searchHighlight(fp, query),
                    });
                }
            }

            // 2. SCENES — frontmatter / metadata / characters / arc.
            for (let i = 0; i < paths.length; i++) {
                const p = paths[i];
                if (seenScenes.has(p)) continue;
                const m = meta[p];
                if (!m) continue;
                const fm = m.fm || {};
                let matchedField = null;
                let matchedValue = null;

                for (let j = 0; j < SEARCH_SCENE_FIELDS.length; j++) {
                    const fname = SEARCH_SCENE_FIELDS[j][0];
                    const val = SEARCH_SCENE_FIELDS[j][1](fm);
                    if (val && String(val).toLowerCase().indexOf(q) !== -1) {
                        matchedField = fname;
                        matchedValue = String(val);
                        break;
                    }
                }
                if (!matchedField) {
                    const chars = Array.isArray(fm.characters) ? fm.characters : [];
                    for (let k = 0; k < chars.length; k++) {
                        const c = String(chars[k]);
                        if (c.toLowerCase().indexOf(q) !== -1) {
                            matchedField = 'character';
                            matchedValue = c;
                            break;
                        }
                    }
                }
                if (!matchedField) continue;
                seenScenes.add(p);
                _searchTotalHits++;
                if (out.length < SEARCH_RESULT_CAP) {
                    out.push({
                        category: 'SCENES', path: p, isScene: true,
                        primary: p,
                        secondary: matchedField + ': ' + matchedValue,
                        primaryHi: _searchEscHtml(p),
                        secondaryHi: _searchEscHtml(matchedField) + ': '
                            + _searchHighlight(matchedValue, query),
                    });
                }
            }

            // 3. TODOS
            for (let i = 0; i < paths.length; i++) {
                const p = paths[i];
                const m = meta[p];
                if (!m || !Array.isArray(m.todos)) continue;
                for (let j = 0; j < m.todos.length; j++) {
                    const t = m.todos[j];
                    if (!t || !t.text) continue;
                    if (t.text.toLowerCase().indexOf(q) === -1) continue;
                    _searchTotalHits++;
                    if (out.length >= SEARCH_RESULT_CAP) continue;
                    out.push({
                        category: 'TODOS', path: p, isScene: true,
                        para: typeof t.paragraph_index === 'number' ? t.paragraph_index : -1,
                        todoText: t.text,
                        primary: t.text,
                        secondary: (t.line ? 'L' + t.line + ' · ' : '') + p,
                        primaryHi: _searchHighlight(t.text, query),
                        secondaryHi: _searchEscHtml(
                            (t.line ? 'L' + t.line + ' · ' : '') + p
                        ),
                    });
                }
            }

            // 4. NOTES
            for (let i = 0; i < paths.length; i++) {
                const p = paths[i];
                const m = meta[p];
                if (!m || !Array.isArray(m.notes)) continue;
                for (let j = 0; j < m.notes.length; j++) {
                    const n = m.notes[j];
                    if (!n || !n.text) continue;
                    const matchesText = n.text.toLowerCase().indexOf(q) !== -1;
                    const matchesTag = n.tag && n.tag.toLowerCase().indexOf(q) !== -1;
                    if (!matchesText && !matchesTag) continue;
                    _searchTotalHits++;
                    if (out.length >= SEARCH_RESULT_CAP) continue;
                    const tagLabel = n.tag ? '[' + n.tag + '] ' : '';
                    out.push({
                        category: 'NOTES', path: p, isScene: true,
                        para: typeof n.paragraph_index === 'number' ? n.paragraph_index : -1,
                        noteText: n.text,
                        noteTag: n.tag || 'note',
                        primary: tagLabel + n.text,
                        secondary: (n.line ? 'L' + n.line + ' · ' : '') + p,
                        primaryHi: _searchHighlight(tagLabel + n.text, query),
                        secondaryHi: _searchEscHtml(
                            (n.line ? 'L' + n.line + ' · ' : '') + p
                        ),
                    });
                }
            }

            // 5. PROSE
            for (let i = 0; i < paths.length; i++) {
                const p = paths[i];
                const text = contents[p];
                if (!text) continue;
                const lowered = text.toLowerCase();
                let pos = 0;
                let perScene = 0;
                while (perScene < SEARCH_PROSE_PER_SCENE) {
                    const idx = lowered.indexOf(q, pos);
                    if (idx === -1) break;
                    _searchTotalHits++;
                    if (out.length < SEARCH_RESULT_CAP) {
                        const para = _paraAt(p, idx);
                        const snippet = _proseSnippet(text, idx, query.length);
                        out.push({
                            category: 'PROSE', path: p, isScene: true,
                            para: para,
                            primary: snippet,
                            secondary: p + (para >= 0 ? ' · ¶' + (para + 1) : ''),
                            primaryHi: _searchHighlight(snippet, query),
                            secondaryHi: _searchEscHtml(
                                p + (para >= 0 ? ' · ¶' + (para + 1) : '')
                            ),
                        });
                    }
                    perScene++;
                    pos = idx + query.length;
                }
            }

            return out;
        }

        function _renderResults(results, query) {
            const panel = document.getElementById('searchResults');
            if (!panel) return;
            if (!query || query.length < SEARCH_MIN_LEN) {
                panel.hidden = true;
                panel.innerHTML = '';
                return;
            }
            if (!results.length) {
                panel.hidden = false;
                panel.innerHTML = '<div class="search-empty">No matches for “'
                    + _searchEscHtml(query) + '”.</div>';
                return;
            }

            const grouped = {};
            for (let i = 0; i < SEARCH_GROUP_ORDER.length; i++) {
                grouped[SEARCH_GROUP_ORDER[i][0]] = [];
            }
            for (let i = 0; i < results.length; i++) {
                grouped[results[i].category].push({ row: results[i], idx: i });
            }

            let html = '';
            for (let g = 0; g < SEARCH_GROUP_ORDER.length; g++) {
                const cat = SEARCH_GROUP_ORDER[g][0];
                const label = SEARCH_GROUP_ORDER[g][1];
                const rows = grouped[cat];
                if (!rows.length) continue;
                html += '<div class="search-group-label">' + label + '</div>';
                for (let i = 0; i < rows.length; i++) {
                    const item = rows[i];
                    const r = item.row;
                    const activeCls = item.idx === _searchCursor ? ' search-row-active' : '';
                    html += '<div class="search-row' + activeCls
                        + '" data-idx="' + item.idx + '">'
                        + '<div class="search-row-primary">' + r.primaryHi + '</div>'
                        + '<div class="search-row-secondary">'
                        + (r.secondaryHi || _searchEscHtml(r.secondary || '')) + '</div>'
                        + '</div>';
                }
            }

            const hidden = _searchTotalHits - results.length;
            if (hidden > 0) {
                html += '<div class="search-more">+' + hidden + ' more hits hidden</div>';
            }

            panel.innerHTML = html;
            panel.hidden = false;
            _ensureSearchCursorVisible();
        }

        function _ensureSearchCursorVisible() {
            const panel = document.getElementById('searchResults');
            if (!panel || _searchCursor < 0) return;
            const row = panel.querySelector('.search-row[data-idx="' + _searchCursor + '"]');
            if (row && row.scrollIntoView) {
                row.scrollIntoView({ block: 'nearest' });
            }
        }

        function _moveSearchCursor(delta) {
            if (!_searchResults.length) return;
            _searchCursor = Math.max(0, Math.min(_searchResults.length - 1, _searchCursor + delta));
            const panel = document.getElementById('searchResults');
            if (!panel) return;
            const rows = panel.querySelectorAll('.search-row');
            for (let i = 0; i < rows.length; i++) {
                const idx = parseInt(rows[i].dataset.idx, 10);
                rows[i].classList.toggle('search-row-active', idx === _searchCursor);
            }
            _ensureSearchCursorVisible();
        }

        // Walks the live Tasks panel and finds the row whose entry's
        // data attributes match the search hit's task. Returns the
        // matched .task-row (or .todo-entry / .note-entry as a fallback)
        // or null if nothing matches. Used to scroll to and flash the
        // matching task row after navigating to a scene from search.
        function _findTaskRowInScene(kind, text, tag) {
            const selector = kind === 'todo' ? '.todo-entry[data-todo-text]'
                                             : '.note-entry[data-note-text]';
            const entries = document.querySelectorAll(selector);
            for (let i = 0; i < entries.length; i++) {
                const e = entries[i];
                let matches;
                if (kind === 'todo') {
                    matches = e.dataset.todoText === text;
                } else {
                    matches = e.dataset.noteText === text
                        && (!tag || e.dataset.noteTag === tag);
                }
                if (matches) return e.closest('.task-row') || e;
            }
            return null;
        }

        function _flashAndScrollTo(el) {
            if (!el || typeof el.scrollIntoView !== 'function') return false;
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.classList.add('para-flash');
            setTimeout(function() { el.classList.remove('para-flash'); }, 1600);
            return true;
        }

        function _jumpToTaskRow(kind, text, tag, attempt) {
            attempt = attempt || 0;
            const row = _findTaskRowInScene(kind, text, tag);
            if (row) { _flashAndScrollTo(row); return; }
            if (attempt < 4) {
                setTimeout(function() {
                    _jumpToTaskRow(kind, text, tag, attempt + 1);
                }, 80);
            }
        }

        function _activateSearchResult(idx) {
            const r = _searchResults[idx];
            if (!r) return;
            _closeSearch(true);

            if (r.category === 'FILES' && !r.isScene) {
                if (typeof previewRepoFile === 'function') previewRepoFile(r.path);
                return;
            }
            if (typeof openSceneModal === 'function') {
                openSceneModal(r.path);
            }

            // TODO / Note hits: jump to the matching row in the Tasks
            // panel at the top of the scene viewer. That row has the
            // Edit / Delete buttons inline, and its ↓ arrow already
            // jumps to the prose paragraph if the user wants that next.
            if (r.category === 'TODOS' && r.todoText) {
                setTimeout(function() {
                    _jumpToTaskRow('todo', r.todoText, null);
                }, 80);
                return;
            }
            if (r.category === 'NOTES' && r.noteText) {
                setTimeout(function() {
                    _jumpToTaskRow('note', r.noteText, r.noteTag);
                }, 80);
                return;
            }

            // Prose hits: scroll to the matching paragraph in the
            // editor surface, the same path the Tasks-panel ↓ arrow
            // uses (retries while ProseMirror finishes mounting).
            if (typeof r.para === 'number' && r.para >= 0
                && typeof _scrollToPara === 'function') {
                setTimeout(function() { _scrollToPara(r.para); }, 120);
            }
        }

        function _closeSearch(clearInput) {
            const panel = document.getElementById('searchResults');
            const inp = document.getElementById('searchBox');
            if (panel) { panel.hidden = true; panel.innerHTML = ''; }
            if (inp) {
                if (clearInput) inp.value = '';
                inp.blur();
            }
            _searchResults = [];
            _searchCursor = -1;
        }

        function _handleSearchInput(e) {
            const q = e.target.value;
            if (_searchDebounceTimer) clearTimeout(_searchDebounceTimer);
            _searchDebounceTimer = setTimeout(function() {
                _searchResults = _runSearch(q);
                _searchCursor = _searchResults.length ? 0 : -1;
                _renderResults(_searchResults, q);
            }, SEARCH_DEBOUNCE_MS);
        }

        function _handleSearchKeydown(e) {
            if (e.key === 'Escape') {
                _closeSearch(true);
                e.preventDefault();
                return;
            }
            if (e.key === 'ArrowDown') {
                _moveSearchCursor(1);
                e.preventDefault();
                return;
            }
            if (e.key === 'ArrowUp') {
                _moveSearchCursor(-1);
                e.preventDefault();
                return;
            }
            if (e.key === 'Enter') {
                if (_searchCursor >= 0) _activateSearchResult(_searchCursor);
                e.preventDefault();
                return;
            }
        }

        function focusSearch() {
            const inp = document.getElementById('searchBox');
            if (!inp) return;
            inp.focus();
            inp.select();
            if (inp.value && inp.value.length >= SEARCH_MIN_LEN) {
                _searchResults = _runSearch(inp.value);
                _searchCursor = _searchResults.length ? 0 : -1;
                _renderResults(_searchResults, inp.value);
            }
        }

        // Wiring. The bundle is concatenated and inlined at the bottom of
        // <body>, so the #searchBox element already exists when this code
        // runs.
        (function _wireSearch() {
            const inp = document.getElementById('searchBox');
            const panel = document.getElementById('searchResults');
            if (!inp || !panel) return;

            inp.addEventListener('input', _handleSearchInput);
            inp.addEventListener('keydown', _handleSearchKeydown);
            inp.addEventListener('focus', function() {
                if (inp.value && inp.value.length >= SEARCH_MIN_LEN) {
                    _searchResults = _runSearch(inp.value);
                    _searchCursor = _searchResults.length ? 0 : -1;
                    _renderResults(_searchResults, inp.value);
                }
            });

            // Click on a result row activates it.
            panel.addEventListener('click', function(e) {
                const row = e.target.closest('.search-row');
                if (!row) return;
                const idx = parseInt(row.dataset.idx, 10);
                if (!Number.isFinite(idx)) return;
                _activateSearchResult(idx);
            });

            // Click outside the palette closes it.
            document.addEventListener('click', function(e) {
                if (e.target.closest('#searchBox')) return;
                if (e.target.closest('#searchResults')) return;
                if (!panel.hidden) _closeSearch(false);
            });

            // Global Cmd-K / Ctrl-K focuses the search input. Bound at
            // document level so it works from anywhere on the page,
            // including the scene viewer and the file preview. The
            // existing scene-mode shortcuts (F/E/B) bail out when the
            // active element is an INPUT, so they don't fight us.
            document.addEventListener('keydown', function(e) {
                if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    focusSearch();
                }
            });
        })();
