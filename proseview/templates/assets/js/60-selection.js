        // ── Selection pill ───────────────────────────────────────────────────
        let pillDragging = false;
        let pillDragStartX = 0, pillDragStartY = 0;
        let pillCurrentX = 0, pillCurrentY = 0;
        let currentSelectionText = '';
        let currentSelectionRange = null;

        function nodeInsideElement(el, node) {
            if (!el || !node) return false;
            const target = node.nodeType === 3 ? node.parentNode : node;
            return !!(target && el.contains(target));
        }

        function rememberSceneSelection(sel) {
            const modalBody = document.getElementById('modalBody');
            if (!modalBody || !sel || sel.isCollapsed || !sel.rangeCount) return false;
            const text = sel.toString().trim();
            if (!text) return false;
            const range = sel.getRangeAt(0);
            if (
                !nodeInsideElement(modalBody, range.startContainer) ||
                !nodeInsideElement(modalBody, range.endContainer)
            ) {
                return false;
            }
            currentSelectionText = text;
            currentSelectionRange = range.cloneRange();
            return true;
        }

        function restoreSceneSelection() {
            if (!currentSelectionRange || !window.getSelection) return false;
            if (
                !document.body.contains(currentSelectionRange.startContainer) ||
                !document.body.contains(currentSelectionRange.endContainer)
            ) {
                currentSelectionRange = null;
                return false;
            }
            const sel = window.getSelection();
            if (!sel) return false;
            sel.removeAllRanges();
            sel.addRange(currentSelectionRange.cloneRange());
            return true;
        }

        function restoreSceneSelectionSoon() {
            if (!currentSelectionRange) return;
            setTimeout(function() { restoreSceneSelection(); }, 0);
        }

        function clearSceneSelectionMemory() {
            currentSelectionText = '';
            currentSelectionRange = null;
            clearPinnedSelectionHighlight();
        }

        // ── Pinned scene selection highlight ─────────────────────────────
        // The browser only ever shows one Selection at a time, and clicking
        // into the xterm canvas / its hidden textarea moves that selection
        // off the prose. To let the user select text, click into the
        // terminal, type, and then press +sel without losing the visual
        // marker, we paint the saved range with the CSS Custom Highlight
        // API. It survives focus changes because it isn't tied to Selection.
        var PINNED_HL_NAME = 'proseview-pinned-selection';
        var _pinnedHighlight = null;

        function pinSelectionHighlight(range) {
            if (!range) return;
            if (typeof CSS === 'undefined' || !CSS.highlights || typeof Highlight === 'undefined') return;
            try {
                _pinnedHighlight = new Highlight(range);
                CSS.highlights.set(PINNED_HL_NAME, _pinnedHighlight);
            } catch (e) {
                _pinnedHighlight = null;
            }
        }

        function clearPinnedSelectionHighlight() {
            if (typeof CSS !== 'undefined' && CSS.highlights) {
                try { CSS.highlights.delete(PINNED_HL_NAME); } catch (e) {}
            }
            _pinnedHighlight = null;
        }

        function getOrCreatePill() {
            let pill = document.getElementById('selectionPill');
            if (pill) return pill;
            pill = document.createElement('div');
            pill.id = 'selectionPill';
            pill.className = 'selection-pill';
            pill.innerHTML =
                '<button class="selection-pill-btn" id="selectionPillBtn" type="button">···</button>' +
                '<div class="selection-pill-menu" id="selectionPillMenu" hidden>' +
                    '<button class="selection-pill-action" id="selectionEditorBtn" type="button">↗ Open in editor at line</button>' +
                    '<button class="selection-pill-action" id="selectionTodoBtn" type="button">📝 Add TODO</button>' +
                    '<div class="selection-todo-form" id="selectionTodoForm" hidden>' +
                        '<textarea class="selection-todo-textarea" id="selectionTodoText" placeholder="Describe what needs to change..."></textarea>' +
                        '<div class="selection-todo-actions">' +
                            '<button class="selection-todo-copy-btn" id="selectionTodoCopy" type="button">Add to file</button>' +
                            '<button class="selection-todo-cancel-btn" id="selectionTodoCancel" type="button">Cancel</button>' +
                        '</div>' +
                    '</div>' +
                    (SKILLS.length ? '<div style="position:relative"><button class="selection-pill-action" id="selectionSkillsBtn" type="button">&#x2728; Skills &#x25BE;</button><div id="selectionSkillsMenu" class="skills-dropdown" style="display:none;left:100%;top:0;bottom:auto;right:auto;"></div></div>' : '') +
                    '<button class="selection-pill-action" id="selectionCodexBtn" type="button">&#x26A1; Run in Codex</button>' +
                    '<div class="selection-codex-form" id="selectionCodexForm" hidden>' +
                        '<textarea class="selection-todo-textarea" id="selectionCodexInstruction" placeholder="What should Codex do with this passage?" rows="3"></textarea>' +
                        '<label class="selection-codex-autoapprove"><input type="checkbox" id="selectionCodexAutoApprove"> Auto-approve changes</label>' +
                        '<div class="selection-todo-actions">' +
                            '<button class="selection-todo-copy-btn" id="selectionCodexRun" type="button">Run</button>' +
                            '<button class="selection-todo-cancel-btn" id="selectionCodexCancel" type="button">Cancel</button>' +
                        '</div>' +
                    '</div>' +
                    '<button class="selection-pill-action" id="selectionNoteBtn" type="button">📌 Add Note</button>' +
                    '<div class="selection-todo-form" id="selectionNoteForm" hidden>' +
                        '<select class="selection-note-tag" id="selectionNoteTag">' +
                            '<option value="note">note</option>' +
                            '<option value="continuity">continuity</option>' +
                            '<option value="character">character</option>' +
                            '<option value="theme">theme</option>' +
                            '<option value="question">question</option>' +
                        '</select>' +
                        '<textarea class="selection-todo-textarea" id="selectionNoteText" placeholder="Editorial observation..."></textarea>' +
                        '<div class="selection-todo-actions">' +
                            '<button class="selection-todo-copy-btn" id="selectionNoteCopy" type="button">Add to file</button>' +
                            '<button class="selection-todo-cancel-btn" id="selectionNoteCancel" type="button">Cancel</button>' +
                        '</div>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(pill);

            document.getElementById('selectionPillBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                const menu = document.getElementById('selectionPillMenu');
                const isOpen = !menu.hidden;
                menu.hidden = isOpen;
                if (!isOpen) {
                    document.getElementById('selectionTodoForm').hidden = true;
                    document.getElementById('selectionTodoText').value = '';
                    document.getElementById('selectionNoteForm').hidden = true;
                    document.getElementById('selectionNoteText').value = '';
                }
            });

            document.getElementById('selectionEditorBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                const selText = (window.getSelection() || {}).toString ? window.getSelection().toString().trim() : '';
                let line = (m.txt_line_offset || 0) + 1;
                if (selText && contents[p]) {
                    const needle = selText.substring(0, 50);
                    const idx = contents[p].indexOf(needle);
                    if (idx >= 0) line = (m.txt_line_offset || 0) + contents[p].substring(0, idx).split('\n').length;
                }
                window.open(buildEditorUrl(m.abs_path, line), '_blank');
                hideSelectionPill();
            });

            document.getElementById('selectionTodoBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionTodoForm').hidden = false;
                document.getElementById('selectionTodoText').focus();
            });

            document.getElementById('selectionTodoCopy').addEventListener('click', function(e) {
                e.stopPropagation();
                const todoText = document.getElementById('selectionTodoText').value.trim();
                if (!todoText) return;
                const btn = document.getElementById('selectionTodoCopy');
                function flash(msg) {
                    const orig = btn.textContent;
                    btn.textContent = msg || orig;
                    btn.disabled = true;
                    setTimeout(function() { btn.textContent = orig; btn.disabled = false; }, 1800);
                }
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                btn.disabled = true;
                fetch('/insert-todo', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        abs_path: m.abs_path,
                        selection_text: currentSelectionText,
                        txt_line_offset: m.txt_line_offset || 0,
                        todo_text: todoText,
                    })
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.ok) {
                        flash('Added!');
                        setTimeout(function() { location.reload(); }, 700);
                    } else {
                        btn.disabled = false;
                        alert('Could not insert TODO: ' + (data.error || 'unknown error'));
                    }
                }).catch(function(err) {
                    btn.disabled = false;
                    alert('Request failed: ' + err);
                });
            });

            document.getElementById('selectionTodoCancel').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionTodoText').value = '';
                document.getElementById('selectionTodoForm').hidden = true;
            });

            document.getElementById('selectionNoteBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionNoteForm').hidden = false;
                document.getElementById('selectionNoteText').focus();
            });

            document.getElementById('selectionNoteCopy').addEventListener('click', function(e) {
                e.stopPropagation();
                const noteText = document.getElementById('selectionNoteText').value.trim();
                if (!noteText) return;
                const tag = document.getElementById('selectionNoteTag').value;
                const btn = document.getElementById('selectionNoteCopy');
                function flash(msg) {
                    const orig = btn.textContent;
                    btn.textContent = msg;
                    btn.disabled = true;
                    setTimeout(function() { btn.textContent = orig; btn.disabled = false; }, 1800);
                }
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                btn.disabled = true;
                fetch('/add-note', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        abs_path: m.abs_path,
                        selection_text: currentSelectionText,
                        txt_line_offset: m.txt_line_offset || 0,
                        note_text: noteText,
                        tag: tag,
                    })
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.ok) {
                        flash('Added!');
                        setTimeout(function() { location.reload(); }, 700);
                    } else {
                        btn.disabled = false;
                        alert('Could not insert note: ' + (data.error || 'unknown error'));
                    }
                }).catch(function(err) {
                    btn.disabled = false;
                    alert('Request failed: ' + err);
                });
            });

            document.getElementById('selectionNoteCancel').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionNoteText').value = '';
                document.getElementById('selectionNoteForm').hidden = true;
            });

            if (SKILLS.length) {
                document.getElementById('selectionSkillsBtn').addEventListener('click', function(e) {
                    e.stopPropagation();
                    var menu = document.getElementById('selectionSkillsMenu');
                    var isOpen = menu.style.display !== 'none';
                    menu.style.display = isOpen ? 'none' : 'block';
                    if (!isOpen) {
                        menu.innerHTML = '';
                        var snippetSkills = SKILLS.filter(function(s) { return s.type === 'snippet'; });
                        snippetSkills.forEach(function(skill) {
                            var btn = document.createElement('button');
                            btn.className = 'skills-dropdown-item';
                            btn.textContent = skill.display_name;
                            btn.title = skill.short_description;
                            btn.onclick = function(ev) {
                                ev.stopPropagation();
                                menu.style.display = 'none';
                                if (curIdx < 0) return;
                                var p = paths[curIdx], m = meta[p];
                                if (!m) return;
                                var sel = currentSelectionText.trim();
                                var prompt = skill.default_prompt
                                    + (sel ? '\n\n"' + sel + '"' : '')
                                    + '\n\nin @' + p;
                                hideSelectionPill();
                                openCodexTerminal(prompt, m.abs_path, false, p);
                            };
                            menu.appendChild(btn);
                        });
                    }
                });
            }

            document.getElementById('selectionCodexBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionCodexForm').hidden = false;
                document.getElementById('selectionCodexInstruction').focus();
            });

            document.getElementById('selectionCodexRun').addEventListener('click', function(e) {
                e.stopPropagation();
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                const sel = currentSelectionText.trim();
                if (!sel) {
                    alert('Select some text in the scene first.');
                    return;
                }
                const instruction = document.getElementById('selectionCodexInstruction').value.trim();
                const autoApprove = document.getElementById('selectionCodexAutoApprove').checked;
                const fullPrompt = instruction
                    ? 'Run ' + instruction + ' on "' + sel + '" in @' + p
                    : 'Review "' + sel + '" in @' + p;
                hideSelectionPill();
                openCodexTerminal(fullPrompt, m.abs_path, autoApprove, p);
            });

            document.getElementById('selectionCodexCancel').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionCodexInstruction').value = '';
                document.getElementById('selectionCodexForm').hidden = true;
            });

            // Drag: only when clicking the pill background (not a button/textarea)
            pill.addEventListener('mousedown', function(e) {
                if (e.target.closest('button') || e.target.tagName === 'TEXTAREA') return;
                pillDragging = true;
                pillDragStartX = e.clientX - pillCurrentX;
                pillDragStartY = e.clientY - pillCurrentY;
                e.preventDefault();
            });

            return pill;
        }

        function collapseSelectionPillMenu() {
            const menu = document.getElementById('selectionPillMenu');
            if (menu) menu.hidden = true;
            ['selectionTodoForm', 'selectionNoteForm', 'selectionCodexForm'].forEach(function(id) {
                const el = document.getElementById(id);
                if (el) el.hidden = true;
            });
            ['selectionTodoText', 'selectionNoteText', 'selectionCodexInstruction'].forEach(function(id) {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            const skillsMenu = document.getElementById('selectionSkillsMenu');
            if (skillsMenu) skillsMenu.style.display = 'none';
        }

        function showSelectionPill(x, y, selText) {
            currentSelectionText = selText || '';
            const pill = getOrCreatePill();
            collapseSelectionPillMenu();
            pillCurrentX = Math.min(x, window.innerWidth - 160);
            pillCurrentY = Math.min(y + 8, window.innerHeight - 50);
            pill.style.left = pillCurrentX + 'px';
            pill.style.top = pillCurrentY + 'px';
            pill.style.display = 'flex';
        }

        function hideSelectionPill() {
            const pill = document.getElementById('selectionPill');
            if (pill) pill.style.display = 'none';
            collapseSelectionPillMenu();
        }

        function initSelectionPill() {
            const modalBody = document.getElementById('modalBody');
            if (!modalBody) return;

            modalBody.addEventListener('mouseup', function(e) {
                const pill = document.getElementById('selectionPill');
                if (pill && pill.contains(e.target)) return;
                setTimeout(function() {
                    const sel = window.getSelection();
                    if (!rememberSceneSelection(sel)) {
                        hideSelectionPill();
                        return;
                    }
                    // The live browser selection is what the user sees right
                    // now; drop any old pinned highlight so we don't paint
                    // two ranges. We re-pin only when focus is about to
                    // leave the prose (e.g., user clicks into the terminal).
                    clearPinnedSelectionHighlight();
                    const range = currentSelectionRange;
                    const rect = range.getBoundingClientRect();
                    showSelectionPill(rect.right, rect.bottom, currentSelectionText);
                }, 10);
            });

            document.addEventListener('mousedown', function(e) {
                const pill = document.getElementById('selectionPill');
                if (!pill || pill.style.display === 'none') return;
                if (e.target.closest('#terminalPanel')) return;
                if (!pill.contains(e.target) && !e.target.closest('#modalBody')) {
                    hideSelectionPill();
                    clearSceneSelectionMemory();
                }
            });

            const terminalPanel = document.getElementById('terminalPanel');
            if (terminalPanel) {
                let terminalMouseDown = null;
                terminalPanel.addEventListener('mousedown', function(e) {
                    // Snapshot the current prose selection AND paint it as a
                    // pinned highlight before xterm steals focus. The pinned
                    // highlight is what the user actually sees while they
                    // type into the terminal; the snapshot is what +sel
                    // pastes if the live Selection has been cleared by then.
                    if (window.getSelection) {
                        rememberSceneSelection(window.getSelection());
                    }
                    if (currentSelectionRange) {
                        pinSelectionHighlight(currentSelectionRange);
                    }
                    terminalMouseDown = {x: e.clientX, y: e.clientY};
                }, true);
                terminalPanel.addEventListener('mouseup', function(e) {
                    if (!terminalMouseDown) return;
                    terminalMouseDown = null;
                    // Intentionally do NOT call restoreSceneSelection here.
                    // Restoring the live Selection moves focus/caret back
                    // into the prose. In edit mode the prose is a
                    // contenteditable ProseMirror, so the next keystroke
                    // would type into the editor (and replace any selected
                    // range) instead of going to the terminal. The pinned
                    // CSS highlight already shows the user where their
                    // selection was, and +sel reads from the cached
                    // currentSelectionText snapshot, so we don't need the
                    // live Selection at all.
                }, true);
                // Prevent terminal header buttons from stealing focus (and clearing prose selection)
                var termHeader = terminalPanel.querySelector('.terminal-header');
                if (termHeader) {
                    termHeader.addEventListener('mousedown', function(e) {
                        if (e.target.closest('button')) e.preventDefault();
                    });
                }
            }

            document.addEventListener('mousemove', function(e) {
                if (!pillDragging) return;
                pillCurrentX = e.clientX - pillDragStartX;
                pillCurrentY = e.clientY - pillDragStartY;
                const pill = document.getElementById('selectionPill');
                if (pill) { pill.style.left = pillCurrentX + 'px'; pill.style.top = pillCurrentY + 'px'; }
            });

            document.addEventListener('mouseup', function() { pillDragging = false; });

            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') hideSelectionPill();
            });
        }

        // Global Esc -> exit edit mode (with unsaved-changes confirmation).
        // Capture phase so we run before any popover/selection handlers and
        // before ProseMirror's keymap.
        document.addEventListener('keydown', function(e) {
            if (e.key !== 'Escape') return;
            // Don't interfere if our own confirmation dialog is up; it has
            // its own Esc handler.
            if (_unsavedDialog) return;
            if (tryEscapeEditMode()) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);

        initSelectionPill();

        var _pendingReload = false;
        var _refreshTimer = null;
        var _refreshInFlight = false;
        var _refreshQueued = false;
        const TERMINAL_REFRESH_DEBOUNCE_MS = 150;

        function setPendingIndicator(visible) {
            var indicator = document.getElementById('termReloadIndicator');
            if (indicator) { indicator.hidden = !visible; }
        }

        function pathListContains(pathsList, path) {
            if (!pathsList || !pathsList.length || !path) return true;
            return pathsList.some(function(changed) {
                return changed === path || changed.endsWith('/' + path);
            });
        }

        function reloadOrDefer(changedPaths) {
            // Always do a partial refresh instead of location.reload() —
            // a full reload jolts the viewport (jump to top, then
            // scroll-restore back) and tears down the live editor. This
            // covers both self-saves and external file edits.
            // refreshContent() is a no-op for the open modal while
            // _pmEditMode is true so the editor stays mounted.
            if (_pendingSelfReloads > 0) _pendingSelfReloads--;
            refreshContent(changedPaths || null);
        }

        function scheduleContentRefresh(delay) {
            if (_termSessions.length === 0) {
                location.reload();
                return;
            }
            _pendingReload = true;
            if (_refreshInFlight) {
                _refreshQueued = true;
                setPendingIndicator(true);
                return;
            }
            if (_refreshTimer) clearTimeout(_refreshTimer);
            _refreshTimer = setTimeout(function() {
                _refreshTimer = null;
                refreshContent();
            }, delay);
        }

        function refreshContent(changedPaths) {
            var view = document.documentElement.dataset.view || '';
            if (view === 'file') {
                var titleEl = document.getElementById('filePreviewTitle');
                var filePath = titleEl ? titleEl.textContent.trim() : '';
                if (pathListContains(changedPaths, filePath) && typeof refreshFilePreview === 'function') {
                    refreshFilePreview({ silent: true, changedPaths: changedPaths || null });
                }
                return;
            }
            if (view !== 'scene' || curIdx < 0 || _pmEditMode) return;
            var scenePath = paths[curIdx];
            if (!pathListContains(changedPaths, scenePath)) return;
            if (_refreshInFlight) {
                _refreshQueued = true;
                _pendingReload = true;
                setPendingIndicator(true);
                return;
            }
            if (_refreshTimer) {
                clearTimeout(_refreshTimer);
                _refreshTimer = null;
            }
            _refreshInFlight = true;
            var refreshSucceeded = false;
            fetch('/scene-data?path=' + encodeURIComponent(scenePath), { cache: 'no-store' }).then(function(r) {
                if (!r.ok) throw new Error('Refresh failed: ' + r.status);
                return r.json();
            }).then(function(data) {
                if (data.contents && data.contents[scenePath] !== undefined) contents[scenePath] = data.contents[scenePath];
                if (data.meta && data.meta[scenePath]) meta[scenePath] = data.meta[scenePath];
                if (data.highlightsByPath && data.highlightsByPath[scenePath]) highlightsByPath[scenePath] = data.highlightsByPath[scenePath];
                refreshSucceeded = true;
                updateModal();
            }).catch(function() {
                _pendingReload = true;
                setPendingIndicator(true);
            }).finally(function() {
                _refreshInFlight = false;
                if (!refreshSucceeded) return;
                if (_refreshQueued) {
                    _refreshQueued = false;
                    scheduleContentRefresh(0);
                } else {
                    setPendingIndicator(false);
                }
            });
        }

        function hotSwapCss() {
            fetch('/app.css?t=' + Date.now(), { cache: 'no-store' })
                .then(function(r) { return r.text(); })
                .then(function(css) {
                    var styleEl = document.getElementById('proseview-app-css');
                    if (styleEl) styleEl.textContent = css;
                })
                .catch(function() {});
        }

        function showAssetReloadBanner() {
            // Terminal sessions now reattach across reload (server keeps the
            // PTYs alive, client replays the scrollback). The only thing a
            // reload destroys is an in-progress unsaved edit. So we only
            // surface the banner when the user is in edit mode -- otherwise
            // just refresh silently.
            var editing = (typeof _pmEditMode !== 'undefined') && _pmEditMode;
            if (!editing) {
                location.reload();
                return;
            }
            if (document.getElementById('assetReloadBanner')) return;
            var banner = document.createElement('div');
            banner.id = 'assetReloadBanner';
            banner.className = 'asset-reload-banner';
            banner.innerHTML =
                '<span class="asset-reload-banner-msg">Page assets updated</span>' +
                '<button type="button" class="asset-reload-banner-btn" onclick="location.reload()">Reload</button>' +
                '<button type="button" class="asset-reload-banner-dismiss" title="Dismiss" onclick="this.parentElement.remove()">&times;</button>';
            document.body.appendChild(banner);
        }

        (function connectSSE() {
            const es = new EventSource('/events');
            es.onmessage = function(e) {
                if (!e.data) return;
                var payload = null;
                if (e.data.charAt(0) === '{') {
                    try { payload = JSON.parse(e.data); } catch(err) { payload = null; }
                }
                if ((payload && (payload.type === 'reload' || payload.type === 'reload:content')) ||
                    e.data === 'reload' || e.data === 'reload:content') {
                    reloadOrDefer(payload && Array.isArray(payload.paths) ? payload.paths : null);
                } else if (e.data === 'reload:css') {
                    hotSwapCss();
                } else if (e.data === 'reload:html' || e.data === 'reload:js') {
                    showAssetReloadBanner();
                }
            };
            es.onerror = function() {
                es.close();
                setTimeout(connectSSE, 3000);
            };
        })();
