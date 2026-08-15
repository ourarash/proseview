        function activeRouteKey() {
            const route = parseHashRoute();
            if (!route) return '/tab/' + (currentTab || 'overview');
            if (route.kind === 'tab') return '/tab/' + (VALID_TABS.includes(route.arg) ? route.arg : 'overview');
            if (route.kind === 'scene' && route.arg) return '/scene/' + route.arg;
            if (route.kind === 'file' && route.arg) return '/file/' + route.arg;
            return '/tab/' + (currentTab || 'overview');
        }

        function activeScrollContainer() {
            const route = parseHashRoute();
            if (route && route.kind === 'scene') return document.querySelector('#sceneModal .modal-content');
            if (route && route.kind === 'file') return document.getElementById('filePreviewBody');
            return window;
        }

        function readScrollTop(container) {
            if (!container) return null;
            return container === window ? (window.scrollY || window.pageYOffset || 0) : container.scrollTop;
        }

        function writeScrollTop(container, top) {
            if (!container) return;
            // Use 'instant' behavior so route restoration bypasses
            // scroll-behavior:smooth on .modal-content. Without this,
            // a refresh visibly animates from 0 to the saved position.
            if (typeof container.scrollTo === 'function') {
                try {
                    container.scrollTo({ top: top, left: 0, behavior: 'instant' });
                    return;
                } catch (err) {
                    // 'instant' rejected by older browsers; fall through.
                }
            }
            if (container === window) window.scrollTo(0, top);
            else container.scrollTop = top;
        }

        function loadSavedScrollTop(key) {
            try {
                const raw = sessionStorage.getItem(VIEW_SCROLL_STORAGE_PREFIX + key);
                if (raw === null) return null;
                const parsed = parseInt(raw, 10);
                return Number.isNaN(parsed) ? null : Math.max(0, parsed);
            } catch (err) {
                return null;
            }
        }

        function saveActiveScrollPosition() {
            if (routeHydrating) return;
            const key = activeRouteKey();
            const top = readScrollTop(activeScrollContainer());
            if (!key || top === null) return;
            try {
                sessionStorage.setItem(VIEW_SCROLL_STORAGE_PREFIX + key, String(Math.round(top)));
            } catch (err) {
                // Ignore storage errors and keep default refresh behavior.
            }
        }

        function scheduleScrollSave() {
            if (scrollSaveQueued) return;
            scrollSaveQueued = true;
            requestAnimationFrame(function() {
                scrollSaveQueued = false;
                saveActiveScrollPosition();
            });
        }

        function restoreActiveScrollPosition() {
            const top = loadSavedScrollTop(activeRouteKey());
            if (top === null) return;
            const delays = [0, 40, 120, 260];
            delays.forEach(function(delay) {
                window.setTimeout(function() {
                    const container = activeScrollContainer();
                    if (!container) return;
                    writeScrollTop(container, top);
                }, delay);
            });
        }

        function buildEditorUrl(absPath, line) {
            const lineVal = (line && line > 1) ? line : 1;
            if (editorScheme === 'custom' && editorUrlTemplate) {
                return editorUrlTemplate
                    .replace('{abs_path}', encodeURI(absPath))
                    .replace('{line}', String(lineVal));
            }
            const base = editorScheme + '://file/' + encodeURI(absPath);
            return lineVal > 1 ? base + ':' + lineVal : base;
        }

        // Highlight toggles persist across scenes and across reloads.
        // The user's pick of "show passive voice" is a global preference,
        // not a per-scene state, so resetting on every open felt fiddly.
        function _loadHighlightPrefs() {
            var defaults = {};
            PASS_ORDER.forEach(function(p) { defaults[p] = false; });
            try {
                var raw = localStorage.getItem(HIGHLIGHTS_STORAGE_KEY);
                if (!raw) return defaults;
                var saved = JSON.parse(raw);
                if (!saved || typeof saved !== 'object') return defaults;
                PASS_ORDER.forEach(function(p) {
                    if (typeof saved[p] === 'boolean') defaults[p] = saved[p];
                });
            } catch (err) {
                // Ignore storage / JSON errors and fall back to defaults.
            }
            return defaults;
        }

        function _saveHighlightPrefs() {
            try {
                localStorage.setItem(HIGHLIGHTS_STORAGE_KEY, JSON.stringify(hls));
            } catch (err) {
                // localStorage is full / disabled; the current-session
                // toggles still work, just not across reloads.
            }
        }

        function openSceneModal(p) {
            // Guard against a path that is not in the scene index: rendering
            // meta[undefined] throws and leaves the user on a dead click.
            if (paths.indexOf(p) === -1) return;
            saveActiveScrollPosition();
            curIdx = paths.indexOf(p);
            hls = _loadHighlightPrefs();
            updateModal();
            resetSceneToolbarForRoute();
            document.documentElement.dataset.view = 'scene';
            routeToHash('/scene/' + encodeURIComponent(p), true);
            restoreActiveScrollPosition();
            // Reveal the scene in the sidebar: highlight it and expand the
            // chapter folders above it.
            if (typeof revealSidebarItem === 'function') revealSidebarItem({ scenePath: p });
            if (typeof updateTerminalShortcuts === 'function') updateTerminalShortcuts();
            if (typeof discussFollowActiveDocument === 'function') discussFollowActiveDocument();
        }

        function openRelatedDoc(path) {
            closeSceneModal();
            previewRepoFile(path);
        }

        function updateModal() {
            const p = paths[curIdx], m = meta[p], b = document.getElementById('modalBody'), a = document.getElementById('modalAlerts'), s = document.getElementById('modalStats');
            document.getElementById('modalTitle').innerText = p;
            const _modalEditorBtn = document.getElementById('modalEditorBtn');
            _modalEditorBtn.style.display = 'flex';
            _modalEditorBtn.href = buildEditorUrl(m.abs_path);
            _modalEditorBtn.title = 'Open in ' + editorLabel;

            // Tone is derived from dialogue density and sentence length:
            //   energy = 10 + (dlg_words/words * 5) - (avg_sent / 2)
            // High energy = lots of short dialogue lines (Talky).
            // Low energy = sparse dialogue, longer sentences (Internal).
            const toneLabel = m.energy > 12 ? 'Talky' : (m.energy < 7 ? 'Internal' : 'Mixed');
            const toneTitle = 'Tone (energy ' + m.energy.toFixed(1) + '). '
                + 'Talky: high dialogue, short sentences. '
                + 'Internal: sparse dialogue, longer sentences.';
            s.innerHTML = '<div class="scene-stat-box"><span class="val">' + m.words.toLocaleString() + '</span><span class="lbl">Words</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.dlg_pct.toFixed(1) + '%</span><span class="lbl">Dialogue %</span></div>' +
                        '<div class="scene-stat-box"><span class="val" title="' + toneTitle + '">' + toneLabel + '</span><span class="lbl">Tone</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.sensory.toFixed(1) + '</span><span class="lbl">Sensory Density</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.first_person.toFixed(1) + '</span><span class="lbl">1st Person</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.passive.toFixed(1) + '</span><span class="lbl">Passive Rate</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.avg_sent.toFixed(1) + '</span><span class="lbl">Avg. Sentence</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.crutch.toFixed(1) + '</span><span class="lbl">Crutch Rate</span></div>';

            const dlgKeywords = (m.top_dlg && m.top_dlg.length) ? m.top_dlg.join(', ') : 'None found';
            a.innerHTML = '<div class="modal-note">' +
                        'Toggle a pass to highlight its matches in the scene below. ' +
                        'Each color marks one pass; sensory hits include a category in the tooltip. ' +
                        'Top dialogue keywords this scene: <span style="color:var(--primary); font-weight:bold;">' + dlgKeywords + '</span>' +
                        '</div>';
            const row = document.createElement('div');
            row.className = 'alert-tag-row';
            const allBtn = document.createElement('button');
            allBtn.id = 'tag-all';
            allBtn.className = 'alert-tag-all';
            allBtn.type = 'button';
            allBtn.textContent = 'All';
            allBtn.onclick = toggleAllHighlights;
            row.appendChild(allBtn);
            PASS_ORDER.forEach(name => addTag(row, name, PASS_LABELS[name]));
            a.appendChild(row);
            render();
        }

        function updateFontSize(v) {
            const size = normalizeModalFontSize(v);
            const modalBody = document.getElementById('modalBody');
            const slider = document.getElementById('modalFontSize');
            if (modalBody) modalBody.style.fontSize = size + 'px';
            if (slider) slider.value = String(size);
            try {
                localStorage.setItem(MODAL_FONT_SIZE_STORAGE_KEY, String(size));
            } catch (err) {
                // Ignore storage errors and keep the current session size.
            }
        }

        // ── Compact scene toolbar ───────────────────────────────────────
        // This is presentation state only. It never changes a manuscript,
        // and the persisted preference deliberately has a small allow-list so
        // stale or edited localStorage values fail safely to auto-hide.
        const SCENE_TOOLBAR_MODE_STORAGE_KEY = 'proseview-scene-toolbar-mode';
        const SCENE_TOOLBAR_MODES = ['auto', 'pinned', 'hidden'];
        var _sceneToolbarMode = loadSceneToolbarMode();
        var _sceneToolbarLastScrollTop = 0;
        var _sceneToolbarHideTimer = null;

        function loadSceneToolbarMode() {
            try {
                var saved = localStorage.getItem(SCENE_TOOLBAR_MODE_STORAGE_KEY);
                return SCENE_TOOLBAR_MODES.indexOf(saved) >= 0 ? saved : 'auto';
            } catch (err) {
                return 'auto';
            }
        }

        function sceneToolbarHeader() {
            return document.querySelector('#sceneModal .modal-header');
        }

        function sceneToolbarReducedMotion() {
            return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        }

        function sceneToolbarMenuIsOpen() {
            return !!document.querySelector('.scene-toolbar-popover:not([hidden])');
        }

        function setSceneToolbarHidden(hidden) {
            var header = sceneToolbarHeader();
            if (!header) return;
            header.dataset.toolbarHidden = hidden ? 'true' : 'false';
        }

        function clearSceneToolbarHideTimer() {
            window.clearTimeout(_sceneToolbarHideTimer);
            _sceneToolbarHideTimer = null;
        }

        function sceneToolbarModeRequiresHidden() {
            return _sceneToolbarMode === 'hidden' ||
                !!document.querySelector('#sceneModal .modal-content.modal-focus');
        }

        function revealSceneToolbar(temporary) {
            clearSceneToolbarHideTimer();
            setSceneToolbarHidden(false);
            if (temporary && sceneToolbarModeRequiresHidden()) {
                _sceneToolbarHideTimer = window.setTimeout(function() {
                    _sceneToolbarHideTimer = null;
                    var header = sceneToolbarHeader();
                    if (!header || !sceneToolbarModeRequiresHidden() ||
                            header.contains(document.activeElement) || sceneToolbarMenuIsOpen()) return;
                    setSceneToolbarHidden(true);
                }, 1800);
            }
        }

        function syncSceneToolbarModeControls() {
            var header = sceneToolbarHeader();
            if (header) header.dataset.toolbarMode = _sceneToolbarMode;
            document.querySelectorAll('input[name="sceneToolbarMode"]').forEach(function(input) {
                input.checked = input.value === _sceneToolbarMode;
            });
        }

        function setSceneToolbarMode(mode, persist) {
            if (SCENE_TOOLBAR_MODES.indexOf(mode) < 0) mode = 'auto';
            clearSceneToolbarHideTimer();
            _sceneToolbarMode = mode;
            syncSceneToolbarModeControls();
            if (persist !== false) {
                try { localStorage.setItem(SCENE_TOOLBAR_MODE_STORAGE_KEY, mode); } catch (err) {}
            }
            var focusLayout = !!document.querySelector('#sceneModal .modal-content.modal-focus');
            if (focusLayout || mode === 'hidden') {
                closeSceneToolbarMenus();
                setSceneToolbarHidden(true);
            } else {
                setSceneToolbarHidden(false);
            }
        }

        function closeSceneToolbarMenus(options) {
            var restoreFocus = !!(options && options.restoreFocus);
            var focusedOpener = null;
            document.querySelectorAll('.scene-toolbar-popover').forEach(function(menu) {
                if (menu.hidden) return;
                var opener = document.querySelector('[aria-controls="' + menu.id + '"]');
                menu.hidden = true;
                if (opener) {
                    opener.setAttribute('aria-expanded', 'false');
                    focusedOpener = focusedOpener || opener;
                }
            });
            if (typeof closeAgentMenus === 'function') closeAgentMenus();
            if (restoreFocus && focusedOpener) focusedOpener.focus();
        }

        function toggleSceneToolbarMenu(menuId, opener) {
            var menu = document.getElementById(menuId);
            if (!menu || !opener) return;
            var opening = menu.hidden;
            closeSceneToolbarMenus();
            if (!opening) return;
            revealSceneToolbar(false);
            menu.hidden = false;
            opener.setAttribute('aria-expanded', 'true');
        }

        function resetSceneToolbarForRoute() {
            var scroller = document.querySelector('#sceneModal .modal-content');
            clearSceneToolbarHideTimer();
            _sceneToolbarLastScrollTop = scroller ? scroller.scrollTop : 0;
            closeSceneToolbarMenus();
            syncSceneToolbarModeControls();
            var focusLayout = !!(scroller && scroller.classList.contains('modal-focus'));
            setSceneToolbarHidden(focusLayout || _sceneToolbarMode === 'hidden');
        }

        function handleSceneToolbarScroll(event) {
            if (event.target !== document.querySelector('#sceneModal .modal-content')) return;
            var current = event.target.scrollTop;
            var delta = current - _sceneToolbarLastScrollTop;
            _sceneToolbarLastScrollTop = current;
            if (_sceneToolbarMode !== 'auto' || sceneToolbarReducedMotion()) return;
            if (document.querySelector('#sceneModal .modal-content.modal-focus')) return;
            if (current < 24 || delta < -8) {
                revealSceneToolbar(false);
            } else if (current > 80 && delta > 8 && !sceneToolbarMenuIsOpen()) {
                setSceneToolbarHidden(true);
            }
        }

        function initSceneToolbar() {
            var header = sceneToolbarHeader();
            var scroller = document.querySelector('#sceneModal .modal-content');
            if (!header || !scroller) return;
            syncSceneToolbarModeControls();
            setSceneToolbarHidden(_sceneToolbarMode === 'hidden');
            scroller.addEventListener('scroll', handleSceneToolbarScroll, { passive: true });
            header.addEventListener('focusin', function() { revealSceneToolbar(false); });
            header.addEventListener('focusout', function() {
                window.setTimeout(function() {
                    if (header.contains(document.activeElement) || sceneToolbarMenuIsOpen()) return;
                    if (_sceneToolbarMode === 'hidden' || scroller.classList.contains('modal-focus')) {
                        setSceneToolbarHidden(true);
                    }
                }, 0);
            });
            header.addEventListener('mouseenter', function() { revealSceneToolbar(false); });
            header.addEventListener('mouseleave', function() {
                if (_sceneToolbarMode !== 'hidden' && !scroller.classList.contains('modal-focus')) return;
                clearSceneToolbarHideTimer();
                _sceneToolbarHideTimer = window.setTimeout(function() {
                    _sceneToolbarHideTimer = null;
                    if (sceneToolbarModeRequiresHidden() && !header.contains(document.activeElement) &&
                            !sceneToolbarMenuIsOpen()) setSceneToolbarHidden(true);
                }, 500);
            });
            document.addEventListener('pointerdown', function(event) {
                if (!event.target.closest('.scene-toolbar-menu-wrap')) closeSceneToolbarMenus();
            });
        }

        function openBio(name) {
            const slug = name.toLowerCase().replace(/\s+/g, '-');
            const bio = bios[slug] || "# Bio not found for " + name;
            const b = document.getElementById('modalBody');
            const s = document.getElementById('modalStats');
            const a = document.getElementById('modalAlerts');
            const t = document.getElementById('modalTitle');

            t.innerText = "Character Bible: " + name;
            document.getElementById('modalEditorBtn').style.display = 'none';
            s.innerHTML = "";
            a.innerHTML = '<div class="alert-tag alert-tag-active" onclick="updateModal()">\u2190 Back to Scene</div>';
            b.innerHTML = '<div class="bio-card">' + marked.parse(bio) + '</div>';
            document.querySelector('.modal-content').scrollTop = 0;
        }

        function addTag(a, id, txt) {
            const t = document.createElement('div');
            t.className = 'alert-tag';
            t.id = 'tag-' + id;
            t.innerText = txt;
            if (hls[id]) t.classList.add('alert-tag-active');
            t.onclick = () => toggleHighlight(id);
            a.appendChild(t);
        }
        function toggleHighlight(id) {
            hls[id] = !hls[id];
            document.getElementById('tag-'+id).classList.toggle('alert-tag-active', hls[id]);
            _saveHighlightPrefs();
            syncAllBtn();
            if (window._PM && _pmView) { updatePMHighlightDecorations(); } else { render(); }
        }
        function syncAllBtn() { const btn = document.getElementById('tag-all'); if (!btn) return; const anyOn = PASS_ORDER.some(k => hls[k]); btn.textContent = anyOn ? 'Clear' : 'All'; }
        function toggleAllHighlights() {
            const anyOn = PASS_ORDER.some(k => hls[k]);
            PASS_ORDER.forEach(k => { hls[k] = !anyOn; const el = document.getElementById('tag-'+k); if (el) el.classList.toggle('alert-tag-active', hls[k]); });
            _saveHighlightPrefs();
            syncAllBtn();
            if (window._PM && _pmView) { updatePMHighlightDecorations(); } else { render(); }
        }

        function attrEscape(s) {
            return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        function renderCharacterTags(chars) {
            return chars.map(function(c) {
                return '<div class="sc-char-tag" data-char-name="' +
                    attrEscape(c) +
                    '" onclick="openBio(this.dataset.charName)" title="Read bio">' +
                    escHtml(c) +
                    '</div>';
            }).join('');
        }

        function render() {
            const p = paths[curIdx], b = document.getElementById('modalBody'), m = meta[p];
            const fm = m.fm || {};
            const chars = Array.isArray(fm.characters) ? fm.characters : (typeof fm.characters === 'string' ? [fm.characters] : []);
            const relatedDocs = Array.isArray(m.related_docs) ? m.related_docs : [];
            const sceneTodos = Array.isArray(m.todos) ? m.todos : [];
            const todosByPara = {};
            const fmTodos = [];
            sceneTodos.forEach(function(t) {
                if (t.paragraph_index >= 0) {
                    if (!todosByPara[t.paragraph_index]) todosByPara[t.paragraph_index] = [];
                    todosByPara[t.paragraph_index].push(t);
                } else {
                    fmTodos.push(t);
                }
            });
            const sceneNotes = Array.isArray(m.notes) ? m.notes : [];
            const notesByPara = {};
            sceneNotes.forEach(function(n) {
                if (!notesByPara[n.paragraph_index]) notesByPara[n.paragraph_index] = [];
                notesByPara[n.paragraph_index].push(n);
            });

            const editorHref = buildEditorUrl(m.abs_path);
            let relatedHtml = '<div class="scene-card-related">' +
                              '<div class="sc-row">' +
                              '<span class="sc-label">Related Docs</span>';
            if (relatedDocs.length) {
                relatedHtml += '<ul class="related-doc-list">';
                relatedDocs.forEach(doc => {
                    const docHref = buildEditorUrl(doc.abs_path || '');
                    relatedHtml += '<li class="related-doc-item">' +
                                   '<button type="button" class="related-doc-link" data-path="' + attrEscape(doc.path || '') + '" onclick="openRelatedDoc(this.dataset.path)">' + escHtml(doc.path || '') + '</button>' +
                                   '<a class="related-doc-editor-icon" href="' + docHref + '" target="_blank" title="Open in ' + attrEscape(editorLabel) + '">\u2197</a>' +
                                   '</li>';
                });
                relatedHtml += '</ul>';
            } else {
                relatedHtml += '<div class="related-doc-empty">No related planning or continuity docs matched this scene.</div>';
            }
            relatedHtml += '</div></div>';
            // Story-layer fields, labelled with the keys this repo actually
            // uses, so the row is traceable back to the frontmatter. Optional:
            // a manuscript that does not use them shows no row rather than a
            // line of "Unknown".
            const storyFields = (typeof storyModel === 'object' && storyModel) || {};
            const threadKey = storyFields.thread_field || 'thread';
            const dayKey = storyFields.day_field || 'day';
            const cap = function(t) { return t.charAt(0).toUpperCase() + t.slice(1); };
            const storyRow = function(label, value) {
                return value === undefined || value === null || value === ''
                    ? ''
                    : '<div class="sc-row"><span class="sc-label">' + escHtml(cap(label))
                      + '</span><span class="sc-value">' + escHtml(String(value)) + '</span></div>';
            };

            let cardHtml = '<div class="scene-card">' +
                           '<div class="scene-card-meta">' +
                           '<div class="sc-row scene-card-top">' +
                           '<span class="sc-label">Scene File</span>' +
                           '<a class="editor-btn" href="' + editorHref + '" target="_blank">\u2197 Open in ' + editorLabel + '</a>' +
                           '</div>' +
                           '<div class="sc-row"><span class="sc-label">POV</span><span class="sc-value">' + (fm.pov || "Unknown") + '</span></div>' +
                           storyRow(threadKey, fm[threadKey]) +
                           '<div class="sc-row"><span class="sc-label">When</span><span class="sc-value">' + (fm.when || "Unknown") + '</span></div>' +
                           storyRow(dayKey, fm[dayKey]) +
                           '<div class="sc-row"><span class="sc-label">Where</span><span class="sc-value">' + (fm.where || fm.location || "Unknown") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">Characters</span><div class="sc-characters">' +
                           renderCharacterTags(chars) + '</div></div>' +
                           '</div>' +
                           '<div class="scene-card-arc">' +
                           '<div class="sc-row"><span class="sc-label">Goal</span><span class="sc-value">' + (fm.goal || "Not defined") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">Conflict</span><span class="sc-value">' + (fm.conflict || "Not defined") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">Outcome</span><span class="sc-value">' + (fm.outcome || "Not defined") + '</span></div>' +
                           '</div>' +
                           relatedHtml +
                           '</div>';

            // Build tasks panel (all TODOs + notes sorted by paragraph order)
            const allTasks = [];
            sceneTodos.forEach(function(t) { allTasks.push({type: 'todo', para: t.paragraph_index, item: t}); });
            sceneNotes.forEach(function(n) { allTasks.push({type: 'note', para: n.paragraph_index, item: n}); });
            allTasks.sort(function(a, b) { return a.para - b.para; });
            let tasksHtml = '';
            if (allTasks.length) {
                const rows = allTasks.map(function(task) {
                    const jumpBtn = task.para >= 0
                        ? '<button class="task-jump-btn" type="button" data-para-idx="' + task.para + '" title="Scroll to paragraph">&#x2193;</button>'
                        : '';
                    const entry = task.type === 'todo'
                        ? todoEntryHtml(task.item, m.abs_path)
                        : noteEntryHtml(task.item, m.abs_path);
                    return '<div class="task-row">' + jumpBtn + entry + '</div>';
                }).join('');
                tasksHtml = '<div class="scene-tasks-section">' +
                    '<div class="scene-tasks-header"><span class="scene-tasks-label">Tasks</span>' +
                    '<span class="scene-tasks-count">' + allTasks.length + '</span></div>' +
                    rows + '</div>';
            }

            if (fmTodos.length) {
                const lineItems = fmTodos.map(function(t) {
                    return '<li class="scene-todo-item">' + escHtml(t.text) + '</li>';
                }).join('');
                cardHtml += '<div class="scene-todos-section"><div class="scene-todos-label">Scene TODOs (frontmatter)</div><ul class="scene-todos-list">' + lineItems + '</ul></div>';
            }

            // ProseMirror is the only renderer. If the module is still
            // loading, the inline ESM bootstrap at the bottom of the
            // template re-invokes render() once window._PM is ready.
            b.innerHTML = cardHtml + tasksHtml + '<div id="sceneProseHost"></div>';
            if (window._PM) mountProseView(p);
            b.scrollTop = 0;
        }

        function navigateScene(d) {
            _pmEditMode = false;
            saveActiveScrollPosition();
            curIdx = Math.max(0, Math.min(paths.length - 1, curIdx + d));
            updateModal();
            const p = paths[curIdx];
            if (p) {
                routeToHash('/scene/' + encodeURIComponent(p), true);
                restoreActiveScrollPosition();
                if (typeof discussFollowActiveDocument === 'function') discussFollowActiveDocument();
            }
        }
        function closeSceneModal() {
            saveActiveScrollPosition();
            hideSelectionPill();
            clearSceneSelectionMemory();
            hideInsertAffordance();
            closeAnnotationPopover();
            if (_pmView) { _pmView.destroy(); _pmView = null; }
            _pmEditMode = false;
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) editBar.hidden = true;
            exitFocusMode();
            delete document.documentElement.dataset.view;
            routeToHash('/tab/' + currentTab, true);
            if (typeof updateTerminalShortcuts === 'function') updateTerminalShortcuts();
            if (typeof discussFollowActiveDocument === 'function') discussFollowActiveDocument();
            restoreActiveScrollPosition();
        }

        function toggleFocusMode() {
            var mc = document.querySelector('#sceneModal .modal-content');
            if (!mc) return;
            var entering = !mc.classList.contains('modal-focus');
            clearSceneToolbarHideTimer();
            mc.classList.toggle('modal-focus', entering);
            var btn = document.getElementById('modalFocusBtn');
            if (btn) {
                btn.classList.toggle('is-active', entering);
                btn.setAttribute('aria-pressed', entering ? 'true' : 'false');
            }
            closeSceneToolbarMenus();
            setSceneToolbarHidden(entering || _sceneToolbarMode === 'hidden');
        }

        function exitFocusMode() {
            clearSceneToolbarHideTimer();
            var mc = document.querySelector('#sceneModal .modal-content');
            if (mc) mc.classList.remove('modal-focus');
            var btn = document.getElementById('modalFocusBtn');
            if (btn) {
                btn.classList.remove('is-active');
                btn.setAttribute('aria-pressed', 'false');
            }
            setSceneToolbarHidden(_sceneToolbarMode === 'hidden');
        }

        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey || e.altKey || e.metaKey) return;
            var tag = (e.target.tagName || '').toUpperCase();
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (document.documentElement.dataset.view !== 'scene') return;
            if ((e.key === 'f' || e.key === 'F') && !_pmEditMode) {
                e.preventDefault();
                toggleFocusMode();
            } else if ((e.key === 'e' || e.key === 'E') && !_pmEditMode) {
                e.preventDefault();
                toggleSceneEdit();
            } else if ((e.key === 'b' || e.key === 'B') && !_pmEditMode) {
                e.preventDefault();
                setSidebarOpen(document.documentElement.dataset.sidebar === 'closed');
            }
        });

        document.addEventListener('keydown', function(e) {
            if (e.key !== 'Escape' || !sceneToolbarMenuIsOpen()) return;
            e.preventDefault();
            e.stopImmediatePropagation();
            closeSceneToolbarMenus({ restoreFocus: true });
        });

        initSceneToolbar();
