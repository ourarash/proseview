        // ── Confirm-on-discard dialog for Esc-out-of-edit ─────────────────
        // Returns true if the keydown should be considered handled (i.e. we
        // either cancelled cleanly or popped a confirmation; the caller
        // should stop further Esc handlers from also firing).
        function tryEscapeEditMode() {
            if (!_pmEditMode) return false;
            if (!_pmDirty) {
                cancelSceneEdit();
                return true;
            }
            showUnsavedDialog();
            return true;
        }

        var _unsavedDialog = null;
        function showUnsavedDialog(options) {
            if (_unsavedDialog) return;
            options = options || {};
            var returnFocus = document.activeElement;
            var overlay = document.createElement('div');
            overlay.className = 'unsaved-dialog-overlay';
            overlay.innerHTML =
                '<div class="unsaved-dialog" role="dialog" aria-modal="true" aria-labelledby="unsavedDialogTitle">' +
                    '<div class="unsaved-dialog-title" id="unsavedDialogTitle">Unsaved changes</div>' +
                    '<div class="unsaved-dialog-body">You have unsaved edits in this scene. Save them before exiting edit mode?</div>' +
                    '<div class="unsaved-dialog-actions">' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-cancel" data-action="cancel">Cancel</button>' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-discard" data-action="discard">Discard</button>' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-save" data-action="save">Save</button>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(overlay);
            _unsavedDialog = overlay;
            var inerted = Array.from(document.body.children).filter(function(el) {
                return el !== overlay && !el.inert;
            });
            inerted.forEach(function(el) { el.inert = true; });
            function close() {
                if (!_unsavedDialog) return;
                document.removeEventListener('keydown', onKey, true);
                _unsavedDialog.remove();
                _unsavedDialog = null;
                inerted.forEach(function(el) { el.inert = false; });
                if (returnFocus && returnFocus.isConnected && typeof returnFocus.focus === 'function') {
                    returnFocus.focus({preventScroll: true});
                }
            }
            function onKey(e) {
                if (e.key === 'Escape') {
                    e.preventDefault(); e.stopPropagation();
                    close();
                } else if (e.key === 'Tab') {
                    var controls = Array.from(overlay.querySelectorAll('button:not([disabled])'));
                    if (!controls.length) return;
                    var first = controls[0], last = controls[controls.length - 1];
                    if (e.shiftKey && document.activeElement === first) {
                        last.focus(); e.preventDefault(); e.stopPropagation();
                    } else if (!e.shiftKey && document.activeElement === last) {
                        first.focus(); e.preventDefault(); e.stopPropagation();
                    }
                }
            }
            overlay.addEventListener('click', function(e) {
                var btn = e.target.closest('button[data-action]');
                if (!btn && e.target === overlay) { close(); return; }
                if (!btn) return;
                var action = btn.dataset.action;
                close();
                if (action === 'save') {
                    saveSceneEdit(options.onContinue);
                } else if (action === 'discard') {
                    if (cancelSceneEdit() !== false && typeof options.onContinue === 'function') {
                        options.onContinue();
                    }
                }
            });
            document.addEventListener('keydown', onKey, true);
            var saveBtn = overlay.querySelector('.unsaved-dialog-save');
            if (saveBtn) saveBtn.focus();
        }

        function parseAnnotationRaw(raw) {
            var m = raw.match(/^<!--\s*TODO:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: 'TODO', text: m[1] };
            m = raw.match(/^<!--\s*NOTE\[(\w+)\]:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: m[1], text: m[2] };
            m = raw.match(/^<!--\s*NOTE:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: 'NOTE', text: m[1] };
            return { tag: 'TODO', text: raw.replace(/^<!--\s*/, '').replace(/\s*-->$/, '') };
        }

        function buildAnnotationRaw(tag, text) {
            if (tag === 'TODO') return '<!-- TODO: ' + text + ' -->';
            if (tag === 'NOTE') return '<!-- NOTE: ' + text + ' -->';
            return '<!-- NOTE[' + tag + ']: ' + text + ' -->';
        }

        function initAffordance(view) {
            var btn = document.getElementById('pmInsertAffordance');
            if (!btn) return;

            btn.onmouseenter = function() { clearTimeout(_pmAffordanceTimer); };
            btn.onmouseleave = function() { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); };
            btn.onclick = function() {
                if (_pmAffordancePos < 0 || !_pmView) return;
                var PM = window._PM;
                var annotNode = PM.mySchema.nodes.annotation.create({ raw: '<!-- TODO:  -->' });
                var insertPos = _pmAffordancePos;
                var wasDirty = _pmDirty;
                var tr = _pmView.state.tr.insert(insertPos, annotNode);
                _pmView.dispatch(tr);
                hideInsertAffordance();
                setTimeout(function() { openAnnotationPopover(insertPos, annotNode, { insertedFrom: { wasDirty: wasDirty } }); }, 0);
            };

            view.dom.addEventListener('mousemove', function(e) {
                if (!_pmEditMode) { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); return; }
                var p = e.target.closest && e.target.closest('p');
                if (!p || !view.dom.contains(p)) { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); return; }
                clearTimeout(_pmAffordanceTimer);
                if (p !== _pmAffordancePara) {
                    _pmAffordancePara = p;
                    try { _pmAffordancePos = view.posAtDOM(p, 0) - 1; }
                    catch(err) { _pmAffordancePos = -1; }
                }
                if (_pmAffordancePos >= 0) {
                    var rect = p.getBoundingClientRect();
                    btn.style.top = (rect.top + 2) + 'px';
                    btn.style.left = (rect.left - 30) + 'px';
                    btn.hidden = false;
                }
            });

            view.dom.addEventListener('mouseleave', function() {
                _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180);
            });
        }

        function hideInsertAffordance() {
            clearTimeout(_pmAffordanceTimer);
            var btn = document.getElementById('pmInsertAffordance');
            if (btn) btn.hidden = true;
            _pmAffordancePara = null;
            _pmAffordancePos = -1;
        }

        function openAnnotationPopover(nodePos, node, options) {
            if (!_pmView) return;
            var dom = _pmView.nodeDOM(nodePos);
            if (dom && dom._annotationStartEdit) {
                dom._annotationStartEdit(!!(options && options.autoSave), options && options.insertedFrom);
            }
        }

        function closeAnnotationPopover() {
            _pmAnnotationPos = -1;
            _pmAnnotationAutoSave = false;
        }

        function saveAnnotationPopover() {
            return;
        }

        function deleteAnnotationNode() {
            return;
        }

        window.onclick = e => {
        };
        function _sceneRowMatchesFilter(r, f) {
            const d = parseFloat(r.dataset.dlg), s = parseFloat(r.dataset.sent), rp = parseFloat(r.dataset.rep);
            const todos = parseInt(r.dataset.todos || '0', 10);
            const notes = parseInt(r.dataset.notes || '0', 10);
            const words = parseInt(r.dataset.words || '0', 10);
            const missingBeats = r.dataset.missingBeats === '1';
            return f === 'all'
                || (f === 'repetition' && rp > 25)
                || (f === 'clipped' && s < 8.5)
                || (f === 'talky' && d > 45)
                || (f === 'dense' && d < 8)
                || (f === 'todos' && todos > 0)
                || (f === 'notes' && notes > 0)
                || (f === 'stubs' && words < 200)
                || (f === 'missing-beats' && missingBeats)
                || (f.startsWith('status-') && r.dataset.status === f.slice(7));
        }

        function applyIssueFilter() {
            const sel = document.getElementById('issueFilter');
            const f = sel ? sel.value : 'all';
            document.querySelectorAll('.ch-row').forEach(r => r.style.display = f === 'all' ? '' : 'none');
            document.querySelectorAll('.scene-row').forEach(r => {
                r.style.display = _sceneRowMatchesFilter(r, f) ? '' : 'none';
            });
            document.querySelectorAll('.scene-overview-card').forEach(c => {
                c.style.display = _sceneRowMatchesFilter(c, f) ? '' : 'none';
            });
        }

        window.renderOverviewSceneCards = function() {
            const grid = document.getElementById('sceneCardsGrid');
            if (!grid) return;
            grid.replaceChildren();
            if (typeof paths === 'undefined' || typeof meta === 'undefined') return;
            paths.forEach(function(p) {
                const m = meta[p] || {};
                const words = typeof m.words === 'number' ? m.words : 0;
                const todos = (m.todos ? m.todos.length : 0) + (m.fm_todos ? m.fm_todos.length : 0);
                const notes = m.notes ? m.notes.length : 0;
                const missingBeats = (!m.goal || !m.conflict) ? '1' : '0';
                const card = document.createElement('article');
                card.className = 'scene-overview-card' + (words < 200 ? ' is-stub' : '');
                card.dataset.scenePath = p;
                card.dataset.dlg = String(m.dlg_pct || 0);
                card.dataset.sent = String(m.avg_sent || 0);
                card.dataset.rep = String(m.rep_pct || 0);
                card.dataset.status = String(m.status || 'none');
                card.dataset.todos = String(todos);
                card.dataset.notes = String(notes);
                card.dataset.words = String(words);
                card.dataset.missingBeats = missingBeats;

                const head = document.createElement('div');
                head.className = 'scene-overview-card-head';
                const link = document.createElement('a');
                link.href = 'javascript:void(0)';
                link.className = 'scene-overview-card-title scene-table-link';
                link.dataset.scenePath = p;
                link.textContent = m.title || p;
                link.onclick = function() { openSceneModal(p); };
                const wordsBadge = document.createElement('span');
                wordsBadge.className = 'scene-overview-card-words' + (words < 200 ? ' is-stub' : '');
                wordsBadge.textContent = words.toLocaleString() + 'w' + (words < 200 ? ' · stub (< 200w)' : '');
                const wordsTip = words < 200
                    ? 'Short draft / stub: this scene has fewer than 200 words of prose and still needs drafting.'
                    : 'Prose words in this scene (excluding YAML frontmatter and HTML comments).';
                wordsBadge.dataset.tip = wordsTip;
                head.append(link, wordsBadge);
                card.appendChild(head);

                const sub = document.createElement('div');
                sub.className = 'scene-overview-card-sub';
                const metaParts = [m.chapter || ''];
                if (m.pov) metaParts.push('POV: ' + m.pov);
                if (m.where) metaParts.push(m.where);
                if (m.when) metaParts.push(m.when);
                sub.textContent = metaParts.filter(Boolean).join(' · ');
                card.appendChild(sub);

                const beatTips = {
                    Goal: 'From goal: in this scene\u2019s YAML frontmatter \u2014 what the POV character wants at the start of the scene.',
                    Conflict: 'From conflict: in this scene\u2019s YAML frontmatter \u2014 what obstacle or friction stands in their way.',
                    Outcome: 'From outcome: in this scene\u2019s YAML frontmatter \u2014 how the scene turns out (for example, yes-but or no-and).'
                };
                const beats = document.createElement('dl');
                beats.className = 'scene-overview-card-beats';
                [['Goal', m.goal], ['Conflict', m.conflict], ['Outcome', m.outcome]].forEach(function(pair) {
                    const row = document.createElement('div');
                    row.className = 'scene-overview-card-beat' + (!pair[1] ? ' is-missing' : '');
                    const dt = document.createElement('dt');
                    dt.textContent = pair[0];
                    dt.dataset.tip = beatTips[pair[0]] || '';
                    const dd = document.createElement('dd');
                    dd.textContent = pair[1] || 'Not set in frontmatter';
                    row.append(dt, dd);
                    beats.appendChild(row);
                });
                card.appendChild(beats);

                const foot = document.createElement('div');
                foot.className = 'scene-overview-card-foot';
                if (m.status) {
                    const st = document.createElement('span');
                    st.className = 'scene-status status-' + m.status;
                    st.textContent = m.status;
                    foot.appendChild(st);
                }
                if (todos > 0) {
                    const tb = document.createElement('span');
                    tb.className = 'todo-badge';
                    tb.textContent = '📝 ' + todos + ' TODO' + (todos > 1 ? 's' : '');
                    foot.appendChild(tb);
                }
                if (notes > 0) {
                    const nb = document.createElement('span');
                    nb.className = 'note-badge';
                    nb.textContent = '💬 ' + notes;
                    foot.appendChild(nb);
                }
                if (foot.childNodes.length) card.appendChild(foot);
                grid.appendChild(card);
            });
            applyIssueFilter();
        };

        window.setOverviewSceneView = function(mode) {
            const table = document.getElementById('sceneTable');
            const grid = document.getElementById('sceneCardsGrid');
            const tableBtn = document.getElementById('sceneViewTableBtn');
            const cardsBtn = document.getElementById('sceneViewCardsBtn');
            const showCards = mode === 'cards';
            if (showCards && grid && !grid.childNodes.length) {
                window.renderOverviewSceneCards();
            }
            if (table) table.hidden = showCards;
            if (grid) grid.hidden = !showCards;
            if (tableBtn) {
                tableBtn.classList.toggle('is-active', !showCards);
                tableBtn.setAttribute('aria-pressed', showCards ? 'false' : 'true');
            }
            if (cardsBtn) {
                cardsBtn.classList.toggle('is-active', showCards);
                cardsBtn.setAttribute('aria-pressed', showCards ? 'true' : 'false');
            }
            applyIssueFilter();
        };
