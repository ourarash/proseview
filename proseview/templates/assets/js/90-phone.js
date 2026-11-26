        // ── Phone ────────────────────────────────────────────────────────────────
        // `proseview --remote` serves this page to the writer's phone over
        // Tailscale. On a phone-sized touch screen the page gets the
        // `pv-phone` class: a short home (continue reading, chapters, files),
        // scenes read full width with a Read / Edit / Ask bar, a plain-text
        // Quick edit that works with dictation, a tap-a-paragraph TODO / note
        // sheet, and a banner when the Mac can't be reached. Everything typed
        // is kept on the phone until it is saved, so a sleeping Mac or a
        // reload loses nothing; saves still check the file's original mtime,
        // so the laptop's edits are never silently overwritten.

        var pvPhone = (function() {
            var root = document.documentElement;
            var PHONE_QUERY = '(max-width: 760px) and (pointer: coarse)';
            var NARROW_QUERY = '(max-width: 760px)';
            var DRAFT_PREFIX = 'proseview-phone-draft:';
            var LAST_SCENE_KEY = 'proseview-phone-last-scene:';
            var state = {
                edit: null,        // {kind, path, absPath, title, mtime, original}
                note: null,        // {path, absPath, text, line, kind}
                offline: false,
                pinging: false,
            };

            function isRemote() { return root.dataset.remote === 'phone'; }

            function wantsPhone() {
                try {
                    if (window.matchMedia(PHONE_QUERY).matches) return true;
                    return isRemote() && window.matchMedia(NARROW_QUERY).matches;
                } catch (err) {
                    return false;
                }
            }

            function el(tag, attrs, children) {
                var node = document.createElement(tag);
                Object.keys(attrs || {}).forEach(function(key) {
                    if (key === 'text') node.textContent = attrs[key];
                    else if (key === 'onclick') node.addEventListener('click', attrs[key]);
                    else if (key === 'className') node.className = attrs[key];
                    else node.setAttribute(key, attrs[key]);
                });
                (children || []).forEach(function(child) { if (child) node.appendChild(child); });
                return node;
            }

            function bookKey() {
                return typeof repoRoot === 'string' ? repoRoot : '';
            }

            // ── Drafts ──────────────────────────────────────────────────────────
            // One per file and kind ('edit' or 'note'), with the mtime the file
            // had when editing began: that, not the file's mtime now, is what
            // the save is checked against.

            function draftKey(kind, path) { return DRAFT_PREFIX + bookKey() + ':' + kind + ':' + path; }

            function readDraft(kind, path) {
                try {
                    var raw = localStorage.getItem(draftKey(kind, path));
                    var draft = raw ? JSON.parse(raw) : null;
                    return draft && typeof draft.text === 'string' ? draft : null;
                } catch (err) {
                    return null;
                }
            }

            function writeDraft(kind, path, draft) {
                try {
                    localStorage.setItem(draftKey(kind, path), JSON.stringify(draft));
                    return true;
                } catch (err) {
                    return false;
                }
            }

            function clearDraft(kind, path) {
                try { localStorage.removeItem(draftKey(kind, path)); } catch (err) { /* nothing kept */ }
            }

            // ── Connection ──────────────────────────────────────────────────────

            function ping() {
                var controller = typeof AbortController === 'function' ? new AbortController() : null;
                var timer = setTimeout(function() { if (controller) controller.abort(); }, 5000);
                return fetch('/api/privacy', {cache: 'no-store', signal: controller ? controller.signal : undefined})
                    .then(function(response) { clearTimeout(timer); return response.ok; })
                    .catch(function() { clearTimeout(timer); return false; });
            }

            function showOffline() {
                state.offline = true;
                var banner = document.getElementById('pvOfflineBanner');
                if (banner) banner.hidden = false;
                root.classList.add('pv-offline');
            }

            function hideOffline() {
                state.offline = false;
                var banner = document.getElementById('pvOfflineBanner');
                if (banner) banner.hidden = true;
                root.classList.remove('pv-offline');
                var retry = document.getElementById('pvOfflineRetry');
                if (retry) { retry.disabled = false; retry.textContent = 'Retry'; }
            }

            // The event stream dropped. Only the phone says so: on the laptop
            // the stream reconnects on its own and Proseview is right there.
            // Returns true when it has taken over a closed stream.
            function connectionDown(reason) {
                if (!root.classList.contains('pv-phone') && !isRemote()) return false;
                if (state.pinging) return true;
                state.pinging = true;
                ping().then(function(ok) {
                    state.pinging = false;
                    if (!ok) {
                        showOffline();
                        return;
                    }
                    if (reason === 'closed') {
                        // The server answers: it was restarted, so the page's
                        // session is gone and only a reload brings it back.
                        // Drafts are kept on the phone, so that is safe.
                        if (typeof showAssetReloadBanner === 'function') {
                            showAssetReloadBanner('Proseview was restarted. Reload the page to continue. Anything you were typing is kept.');
                        }
                    }
                });
                return true;
            }

            function connectionUp() {
                if (state.offline) hideOffline();
            }

            function retry() {
                var button = document.getElementById('pvOfflineRetry');
                if (button) { button.disabled = true; button.textContent = 'Trying…'; }
                return ping().then(function(ok) {
                    if (!ok) {
                        if (button) { button.disabled = false; button.textContent = 'Retry'; }
                        return false;
                    }
                    hideOffline();
                    // Reconnect and catch up in place: a reload would take the
                    // text in Quick edit or the chat box with it.
                    if (typeof window.pvReconnectEvents === 'function') window.pvReconnectEvents();
                    if (typeof refreshContent === 'function') {
                        try { refreshContent(null); } catch (err) { /* the next change refreshes */ }
                    }
                    return true;
                });
            }

            function buildOfflineBanner() {
                if (document.getElementById('pvOfflineBanner')) return;
                var banner = el('div', {id: 'pvOfflineBanner', className: 'pv-offline-banner', role: 'alert', hidden: ''}, [
                    el('span', {className: 'pv-offline-text', text: 'Your Mac is asleep or Proseview stopped. Your text stays here.'}),
                    el('button', {type: 'button', id: 'pvOfflineRetry', className: 'pv-btn pv-btn-small', text: 'Retry', onclick: function() { retry(); }}),
                ]);
                banner.hidden = true;
                document.body.appendChild(banner);
            }

            // ── Keyboard ────────────────────────────────────────────────────────
            // Sheets size themselves to the visual viewport, so the on-screen
            // keyboard never covers Save or the text being typed.

            function trackViewport() {
                var vv = window.visualViewport;
                if (!vv) return;
                var update = function() {
                    root.style.setProperty('--pv-vvh', Math.round(vv.height) + 'px');
                    root.style.setProperty('--pv-vvtop', Math.round(vv.offsetTop) + 'px');
                };
                vv.addEventListener('resize', update);
                vv.addEventListener('scroll', update);
                update();
            }

            // ── Home ────────────────────────────────────────────────────────────

            function sceneTitle(p) {
                var m = (typeof meta !== 'undefined' && meta[p]) || {};
                return m.title || p.split('/').pop().replace(/\.md$/i, '').replace(/[-_]+/g, ' ');
            }

            function chapters() {
                var list = [];
                var byName = {};
                (typeof paths !== 'undefined' ? paths : []).forEach(function(p) {
                    var m = meta[p] || {};
                    var name = m.chapter || p.split('/').slice(0, -1).join('/') || 'Scenes';
                    if (!byName[name]) {
                        byName[name] = {name: name, scenes: []};
                        list.push(byName[name]);
                    }
                    byName[name].scenes.push(p);
                });
                return list;
            }

            function lastScene() {
                try {
                    var p = localStorage.getItem(LAST_SCENE_KEY + bookKey());
                    return p && paths.indexOf(p) >= 0 ? p : '';
                } catch (err) {
                    return '';
                }
            }

            function rememberScene(p) {
                try { localStorage.setItem(LAST_SCENE_KEY + bookKey(), p); } catch (err) { /* convenience only */ }
            }

            function sceneStatus(p) {
                var fm = (meta[p] && meta[p].fm) || {};
                return typeof fm.status === 'string' ? fm.status : '';
            }

            function renderHome() {
                var overview = document.getElementById('tab-overview');
                if (!overview || typeof paths === 'undefined') return;
                var home = document.getElementById('phoneHome');
                if (!home) {
                    home = el('section', {id: 'phoneHome', className: 'pv-home', 'aria-label': 'Your book'});
                    overview.insertBefore(home, overview.firstChild);
                }
                home.replaceChildren();
                var actions = el('div', {className: 'pv-home-actions'}, [
                    el('button', {type: 'button', className: 'pv-btn pv-btn-primary', text: 'Read the book', onclick: function() { openBookView(); }}),
                    el('button', {type: 'button', className: 'pv-btn', text: 'Files', onclick: function() { setSidebarOpen(true); }}),
                ]);
                var last = lastScene() || paths[0];
                if (last) {
                    var chapterList = chapters();
                    var where = '';
                    chapterList.forEach(function(ch) {
                        var at = ch.scenes.indexOf(last);
                        if (at >= 0) where = ch.name + ' · scene ' + (at + 1) + ' of ' + ch.scenes.length;
                    });
                    home.appendChild(el('button', {type: 'button', className: 'pv-continue', onclick: function() { openSceneModal(last); }}, [
                        el('span', {className: 'pv-eyebrow', text: lastScene() ? 'Continue reading' : 'Start reading'}),
                        el('span', {className: 'pv-continue-title', text: sceneTitle(last)}),
                        el('span', {className: 'pv-muted', text: where}),
                    ]));
                }
                home.appendChild(actions);
                var list = chapters();
                home.appendChild(el('h2', {className: 'pv-section-title', text: 'Chapters · ' + list.length + ' · ' + paths.length + ' scenes'}));
                var chaptersBox = el('div', {className: 'pv-chapters'});
                list.forEach(function(ch) {
                    var details = el('details', {className: 'pv-chapter'});
                    if (ch.scenes.indexOf(last) >= 0) details.open = true;
                    details.appendChild(el('summary', {}, [
                        el('span', {className: 'pv-chapter-name', text: ch.name}),
                        el('span', {className: 'pv-count', text: String(ch.scenes.length)}),
                    ]));
                    ch.scenes.forEach(function(p) {
                        var status = sceneStatus(p);
                        details.appendChild(el('button', {type: 'button', className: 'pv-row', onclick: function() { openSceneModal(p); }}, [
                            el('span', {className: 'pv-row-title', text: sceneTitle(p)}),
                            status ? el('span', {className: 'pv-pill', text: status}) : null,
                        ]));
                    });
                    chaptersBox.appendChild(details);
                });
                home.appendChild(chaptersBox);
                renderTodos(home);
            }

            // Every TODO in the book, each opening its scene at the TODO.
            function renderTodos(home) {
                var todos = [];
                paths.forEach(function(p) {
                    ((meta[p] && meta[p].todos) || []).forEach(function(todo) {
                        if (todo && todo.text) todos.push({path: p, text: todo.text});
                    });
                });
                if (!todos.length) return;
                var details = el('details', {className: 'pv-chapters pv-todos'});
                details.appendChild(el('summary', {}, [
                    el('span', {className: 'pv-chapter-name', text: 'TODOs'}),
                    el('span', {className: 'pv-count', text: String(todos.length)}),
                ]));
                todos.forEach(function(todo) {
                    details.appendChild(el('button', {type: 'button', className: 'pv-row pv-todo-row', onclick: function() { openTodo(todo); }}, [
                        el('span', {className: 'pv-row-title'}, [
                            el('span', {className: 'pv-todo-text', text: todo.text}),
                            el('span', {className: 'pv-muted pv-todo-scene', text: sceneTitle(todo.path)}),
                        ]),
                    ]));
                });
                home.appendChild(details);
            }

            function openTodo(todo) {
                if (openSceneModal(todo.path) === false) return;
                var tries = 0;
                (function reveal() {
                    var marks = document.querySelectorAll('#sceneProseHost .pm-annotation-todo');
                    var match = Array.prototype.find.call(marks, function(mark) {
                        return mark.textContent.indexOf(todo.text.slice(0, 60)) >= 0;
                    });
                    if (match) {
                        match.scrollIntoView({block: 'center'});
                        return;
                    }
                    if (++tries < 20) setTimeout(reveal, 100);
                })();
            }

            // ── Scene / file bar ────────────────────────────────────────────────

            function currentTarget() {
                var view = root.dataset.view || '';
                if (view === 'scene' && typeof paths !== 'undefined' && curIdx >= 0 && paths[curIdx]) {
                    var p = paths[curIdx];
                    return {kind: 'scene', path: p, absPath: meta[p].abs_path, title: sceneTitle(p)};
                }
                if (view === 'file' && typeof sidebarCurrentPath === 'function') {
                    var path = sidebarCurrentPath();
                    if (path) return {kind: 'file', path: path, title: path.split('/').pop()};
                }
                return null;
            }

            function buildBar() {
                if (document.getElementById('pvSceneBar')) return;
                var bar = el('nav', {id: 'pvSceneBar', className: 'pv-scene-bar', 'aria-label': 'Scene actions'}, [
                    el('button', {type: 'button', id: 'pvReadBtn', className: 'pv-bar-btn', text: 'Read on', onclick: function() {
                        var t = currentTarget();
                        if (t && t.kind === 'scene') openBookView(t.path, {layout: 'text'});
                    }}),
                    el('button', {type: 'button', id: 'pvEditBtn', className: 'pv-bar-btn', text: 'Edit', onclick: function() { openQuickEdit(); }}),
                    el('button', {type: 'button', id: 'pvAskBtn', className: 'pv-bar-btn', text: 'Ask', onclick: function(event) { openAsk(event.currentTarget); }}),
                ]);
                document.body.appendChild(bar);
            }

            function syncBar() {
                var t = currentTarget();
                var read = document.getElementById('pvReadBtn');
                var edit = document.getElementById('pvEditBtn');
                if (read) read.hidden = !t || t.kind !== 'scene';
                if (edit) {
                    var yaml = t && /\.ya?ml$/i.test(t.path);
                    edit.disabled = !!yaml;
                    edit.title = yaml ? 'YAML files are read-only on the phone' : '';
                }
                if (t && t.kind === 'scene') rememberScene(t.path);
            }

            function openAsk(trigger) {
                if (typeof showDiscussAgentTab !== 'function') return;
                // The agent last used, as on the laptop.
                showDiscussAgentTab(typeof _discussAgent === 'string' ? _discussAgent : 'codex', trigger);
            }

            // ── Quick edit ──────────────────────────────────────────────────────

            // The frontmatter block of a note and its body, as split_note_header
            // splits them on the server, which keeps the block on save.
            function splitNote(raw) {
                var lines = raw.split(/(?<=\n)/);
                if (lines.length && lines[0].trim() === '---') {
                    for (var i = 1; i < lines.length; i++) {
                        var t = lines[i].trim();
                        if (t === '---' || t === '...') {
                            return lines.slice(i + 1).join('').replace(/^\n+/, '');
                        }
                    }
                }
                return raw;
            }

            function loadFresh(target) {
                if (target.kind === 'scene') {
                    return fetch('/scene-data?path=' + encodeURIComponent(target.path), {cache: 'no-store'})
                        .then(function(r) { if (!r.ok) throw new Error('Could not open the scene (' + r.status + ')'); return r.json(); })
                        .then(function(data) {
                            return {text: data.contents[target.path], mtime: data.meta[target.path].mtime,
                                    absPath: data.meta[target.path].abs_path};
                        });
                }
                return fetch('/repo-file?path=' + encodeURIComponent(target.path), {cache: 'no-store'})
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (!data || !data.ok || !data.node || data.node.body === null || data.node.too_large || data.node.not_utf8) {
                            throw new Error((data && data.error) || 'This file cannot be edited here.');
                        }
                        return {text: splitNote(data.node.body), mtime: data.node.mtime, absPath: data.node.abs_path};
                    });
            }

            function editStatus(message, isError) {
                var line = document.getElementById('pvEditStatus');
                if (!line) return;
                line.textContent = message || '';
                line.classList.toggle('pv-error', !!isError);
            }

            function buildEditSheet() {
                if (document.getElementById('pvEditSheet')) return;
                var area = el('textarea', {id: 'pvEditText', className: 'pv-textarea', 'aria-label': 'Text', enterkeyhint: 'enter',
                                           autocapitalize: 'sentences', spellcheck: 'true'});
                area.addEventListener('input', function() { keepEditDraft(); });
                var sheet = el('section', {id: 'pvEditSheet', className: 'pv-sheet pv-edit-sheet', role: 'dialog', 'aria-modal': 'true',
                                           'aria-labelledby': 'pvEditTitle'}, [
                    el('header', {className: 'pv-sheet-bar'}, [
                        el('button', {type: 'button', className: 'pv-btn pv-btn-quiet', text: 'Cancel', onclick: function() { cancelQuickEdit(); }}),
                        el('h2', {id: 'pvEditTitle', className: 'pv-sheet-title'}),
                        el('button', {type: 'button', id: 'pvEditSave', className: 'pv-btn pv-btn-primary', text: 'Save', onclick: function() { saveQuickEdit(false); }}),
                    ]),
                    el('p', {id: 'pvEditStatus', className: 'pv-status', 'aria-live': 'polite'}),
                    area,
                ]);
                sheet.hidden = true;
                document.body.appendChild(sheet);
            }

            function keepEditDraft() {
                var e = state.edit;
                var area = document.getElementById('pvEditText');
                if (!e || !area) return;
                clearTimeout(keepEditDraft.timer);
                keepEditDraft.timer = setTimeout(function() {
                    if (area.value === e.original) {
                        clearDraft('edit', e.path);
                        editStatus('');
                        return;
                    }
                    var kept = writeDraft('edit', e.path, {text: area.value, mtime: e.mtime, kind: e.kind, savedAt: Date.now()});
                    editStatus(kept ? 'Draft saved on this phone' : 'Could not keep a draft on this phone. Copy your text before leaving.', !kept);
                }, 400);
            }

            function openQuickEdit() {
                var target = currentTarget();
                if (!target || /\.ya?ml$/i.test(target.path)) return;
                buildEditSheet();
                var sheet = document.getElementById('pvEditSheet');
                var area = document.getElementById('pvEditText');
                document.getElementById('pvEditTitle').textContent = target.title;
                var draft = readDraft('edit', target.path);
                var show = function(text, mtime, absPath, original, message) {
                    state.edit = {kind: target.kind, path: target.path, absPath: absPath, title: target.title,
                                  mtime: mtime, original: original};
                    area.value = text;
                    sheet.hidden = false;
                    root.classList.add('pv-sheet-open');
                    editStatus(message || '');
                    area.focus({preventScroll: true});
                };
                editStatus('Opening…');
                sheet.hidden = false;
                area.value = '';
                loadFresh(target).then(function(fresh) {
                    if (draft) {
                        // The draft's own mtime stays the baseline, so a change
                        // made on the laptop meanwhile still raises a conflict.
                        show(draft.text, draft.mtime, fresh.absPath, fresh.text, 'Your unsaved draft is back.');
                    } else {
                        show(fresh.text, fresh.mtime, fresh.absPath, fresh.text, '');
                    }
                }).catch(function(err) {
                    if (draft) {
                        show(draft.text, draft.mtime, target.absPath || '', null,
                             'Your unsaved draft is back. The Mac cannot be reached, so it can be saved once it is.');
                        return;
                    }
                    closeEditSheet();
                    if (err instanceof TypeError) showOffline();
                    else if (typeof sidebarShowToast === 'function') sidebarShowToast(err.message, true);
                });
            }

            function closeEditSheet() {
                var sheet = document.getElementById('pvEditSheet');
                if (sheet) sheet.hidden = true;
                closeConflict();
                root.classList.remove('pv-sheet-open');
                state.edit = null;
            }

            function cancelQuickEdit() {
                var e = state.edit;
                var area = document.getElementById('pvEditText');
                if (e && area && e.original !== null && area.value !== e.original) {
                    // Cancel only closes: the draft stays, and Edit brings it
                    // back. Discard is in the conflict sheet and after a save.
                    writeDraft('edit', e.path, {text: area.value, mtime: e.mtime, kind: e.kind, savedAt: Date.now()});
                    if (typeof sidebarShowToast === 'function') sidebarShowToast('Draft kept on this phone. Edit brings it back.');
                }
                closeEditSheet();
            }

            function saveQuickEdit(overwrite) {
                var e = state.edit;
                var area = document.getElementById('pvEditText');
                var button = document.getElementById('pvEditSave');
                if (!e || !area) return;
                var text = area.value;
                writeDraft('edit', e.path, {text: text, mtime: e.mtime, kind: e.kind, savedAt: Date.now()});
                button.disabled = true;
                editStatus('Saving…');
                var request = e.kind === 'scene'
                    ? {url: '/save-scene', body: {abs_path: e.absPath, content: text, open_mtime: e.mtime, overwrite: !!overwrite}}
                    : {url: '/api/files/save', body: {path: e.path, content: text, open_mtime: e.mtime, overwrite: !!overwrite}};
                fetch(request.url, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(request.body)})
                    .then(function(response) {
                        return response.json().catch(function() { return {}; }).then(function(data) {
                            return {status: response.status, data: data};
                        });
                    })
                    .then(function(result) {
                        button.disabled = false;
                        if (result.status === 409 || (result.data && result.data.conflict)) {
                            editStatus('');
                            openConflict();
                            return;
                        }
                        if (result.status >= 400 || !result.data || result.data.ok === false) {
                            editStatus((result.data && result.data.error) || 'Could not save. Your text is kept on this phone.', true);
                            return;
                        }
                        clearDraft('edit', e.path);
                        closeEditSheet();
                        if (typeof sidebarShowToast === 'function') sidebarShowToast('Saved');
                        if (e.kind === 'scene' && typeof refreshSceneIfChangedOnDisk === 'function') refreshSceneIfChangedOnDisk(e.path);
                        else if (typeof refreshFilePreview === 'function') refreshFilePreview({silent: true});
                    })
                    .catch(function() {
                        button.disabled = false;
                        editStatus('Not saved: the Mac cannot be reached. Your text is kept on this phone.', true);
                        showOffline();
                    });
            }

            function openConflict() {
                var sheet = document.getElementById('pvConflictSheet');
                if (!sheet) {
                    sheet = el('section', {id: 'pvConflictSheet', className: 'pv-sheet pv-small-sheet', role: 'alertdialog', 'aria-modal': 'true',
                                           'aria-labelledby': 'pvConflictTitle'}, [
                        el('h2', {id: 'pvConflictTitle', className: 'pv-sheet-heading', text: 'Changed on the Mac'}),
                        el('p', {className: 'pv-muted', text: 'This file was changed on the Mac after you started editing here.'}),
                        el('div', {className: 'pv-stack'}, [
                            el('button', {type: 'button', className: 'pv-btn pv-btn-primary', text: 'Keep mine', onclick: function() {
                                closeConflict(); saveQuickEdit(true);
                            }}),
                            el('button', {type: 'button', id: 'pvConflictCopy', className: 'pv-btn', text: 'Copy my draft', onclick: function() { copyDraft(); }}),
                            el('button', {type: 'button', className: 'pv-btn pv-btn-danger', text: 'Discard and reload', onclick: function() { discardAndReload(); }}),
                        ]),
                    ]);
                    sheet.hidden = true;
                    document.body.appendChild(sheet);
                }
                sheet.hidden = false;
            }

            function closeConflict() {
                var sheet = document.getElementById('pvConflictSheet');
                if (sheet) sheet.hidden = true;
            }

            function copyDraft() {
                var area = document.getElementById('pvEditText');
                var button = document.getElementById('pvConflictCopy');
                if (!area) return;
                var done = function(ok) {
                    if (button) button.textContent = ok ? 'Copied' : 'Select and copy it in the editor';
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(area.value).then(function() { done(true); }, function() { done(false); });
                } else {
                    area.select();
                    try { done(document.execCommand('copy')); } catch (err) { done(false); }
                }
            }

            function discardAndReload() {
                var e = state.edit;
                if (!e) return;
                clearDraft('edit', e.path);
                closeEditSheet();
                if (e.kind === 'scene' && typeof refreshSceneIfChangedOnDisk === 'function') refreshSceneIfChangedOnDisk(e.path);
                if (typeof refreshContent === 'function') {
                    try { refreshContent([e.path]); } catch (err) { /* next change refreshes */ }
                }
            }

            // ── + TODO / Note ───────────────────────────────────────────────────
            // A tap on a paragraph only marks it and shows a small pill, so a
            // stray tap while reading never opens anything.

            function paragraphText(p) {
                var copy = p.cloneNode(true);
                copy.querySelectorAll('.ProseMirror-widget, [contenteditable="false"]').forEach(function(w) { w.remove(); });
                return copy.textContent.replace(/\s+/g, ' ').trim();
            }

            function clearTapped() {
                document.querySelectorAll('.pv-tapped').forEach(function(p) { p.classList.remove('pv-tapped'); });
                var pill = document.getElementById('pvNotePill');
                if (pill) pill.hidden = true;
            }

            function onSceneTap(event) {
                if (!root.classList.contains('pv-phone') || root.dataset.view !== 'scene') return;
                if (event.target.closest('a, button, input, textarea, select, summary, .fm, [contenteditable="true"]')) return;
                var selection = window.getSelection && window.getSelection();
                if (selection && String(selection).trim()) return;
                var p = event.target.closest('#sceneProseHost p');
                if (!p) { clearTapped(); return; }
                if (p.classList.contains('pv-tapped')) { clearTapped(); return; }
                var text = paragraphText(p);
                if (!text) return;
                clearTapped();
                p.classList.add('pv-tapped');
                var pill = document.getElementById('pvNotePill');
                if (!pill) {
                    pill = el('button', {type: 'button', id: 'pvNotePill', className: 'pv-note-pill', text: '+ TODO / Note',
                                         onclick: function(e) { e.stopPropagation(); openNoteSheet(); }});
                }
                pill.dataset.text = text;
                p.insertAdjacentElement('afterend', pill);
                pill.hidden = false;
            }

            function buildNoteSheet() {
                if (document.getElementById('pvNoteSheet')) return;
                var area = el('textarea', {id: 'pvNoteText', className: 'pv-textarea pv-note-textarea', 'aria-label': 'TODO or note text',
                                           placeholder: 'TODO or note text', enterkeyhint: 'enter', autocapitalize: 'sentences'});
                area.addEventListener('input', function() {
                    var n = state.note;
                    if (!n) return;
                    var kept = writeDraft('note', n.path, {text: area.value, kind: n.kind, anchor: n.text, savedAt: Date.now()});
                    var hint = document.getElementById('pvNoteStatus');
                    if (hint) {
                        hint.textContent = kept ? (area.value ? 'Draft saved on this phone' : '') : 'Could not keep a draft on this phone.';
                        hint.classList.toggle('pv-error', !kept);
                    }
                });
                var kindButton = function(kind, label) {
                    return el('button', {type: 'button', className: 'pv-seg', 'data-kind': kind, 'aria-pressed': 'false', text: label,
                                         onclick: function() { setNoteKind(kind); }});
                };
                var sheet = el('section', {id: 'pvNoteSheet', className: 'pv-sheet pv-note-sheet', role: 'dialog', 'aria-modal': 'true',
                                           'aria-label': 'Add a TODO or note'}, [
                    el('header', {className: 'pv-sheet-bar'}, [
                        el('button', {type: 'button', className: 'pv-btn pv-btn-quiet', text: 'Cancel', onclick: function() { closeNoteSheet(); }}),
                        el('div', {className: 'pv-segmented', role: 'group', 'aria-label': 'Kind'}, [kindButton('todo', 'TODO'), kindButton('note', 'Note')]),
                        el('button', {type: 'button', id: 'pvNoteAdd', className: 'pv-btn pv-btn-primary', text: 'Add', onclick: function() { addNote(); }}),
                    ]),
                    el('blockquote', {id: 'pvNoteQuote', className: 'pv-quote'}),
                    area,
                    el('p', {id: 'pvNoteStatus', className: 'pv-status', 'aria-live': 'polite'}),
                ]);
                sheet.hidden = true;
                document.body.appendChild(sheet);
            }

            function setNoteKind(kind) {
                if (state.note) state.note.kind = kind;
                document.querySelectorAll('#pvNoteSheet .pv-seg').forEach(function(button) {
                    button.setAttribute('aria-pressed', button.dataset.kind === kind ? 'true' : 'false');
                });
            }

            function openNoteSheet() {
                var t = currentTarget();
                var pill = document.getElementById('pvNotePill');
                if (!t || t.kind !== 'scene' || !pill) return;
                buildNoteSheet();
                var draft = readDraft('note', t.path);
                var anchor = (draft && draft.anchor === pill.dataset.text) ? draft : null;
                state.note = {path: t.path, absPath: t.absPath, text: pill.dataset.text, kind: anchor ? anchor.kind : 'todo'};
                var quote = state.note.text;
                document.getElementById('pvNoteQuote').textContent = quote.length > 140 ? quote.slice(0, 140) + '…' : quote;
                document.getElementById('pvNoteText').value = anchor ? anchor.text : '';
                document.getElementById('pvNoteStatus').textContent = anchor && anchor.text ? 'Your unsaved draft is back.' : '';
                setNoteKind(state.note.kind);
                document.getElementById('pvNoteSheet').hidden = false;
                root.classList.add('pv-sheet-open');
                document.getElementById('pvNoteText').focus({preventScroll: true});
            }

            function closeNoteSheet() {
                var sheet = document.getElementById('pvNoteSheet');
                if (sheet) sheet.hidden = true;
                root.classList.remove('pv-sheet-open');
                state.note = null;
            }

            function addNote() {
                var n = state.note;
                var area = document.getElementById('pvNoteText');
                var button = document.getElementById('pvNoteAdd');
                var status = document.getElementById('pvNoteStatus');
                if (!n || !area) return;
                var text = area.value.replace(/\s+/g, ' ').trim();
                if (!text) { status.textContent = 'Type or dictate the ' + (n.kind === 'todo' ? 'TODO' : 'note') + ' first.'; return; }
                var m = meta[n.path] || {};
                var body = {abs_path: n.absPath, selection_text: n.text, txt_line_offset: m.txt_line_offset || 0, open_mtime: m.mtime};
                var url = n.kind === 'todo' ? '/insert-todo' : '/add-note';
                if (n.kind === 'todo') body.todo_text = text;
                else { body.note_text = text; body.tag = 'note'; }
                button.disabled = true;
                status.textContent = 'Adding…';
                status.classList.remove('pv-error');
                fetch(url, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body)})
                    .then(function(response) { return response.json().catch(function() { return {}; }); })
                    .then(function(data) {
                        button.disabled = false;
                        if (!data || !data.ok) {
                            var why = data && data.conflict
                                ? 'The scene changed on the Mac. Your text is kept; close and tap the paragraph again.'
                                : ((data && data.error) || 'Could not add it. Your text is kept on this phone.');
                            status.textContent = why;
                            status.classList.add('pv-error');
                            return;
                        }
                        clearDraft('note', n.path);
                        closeNoteSheet();
                        clearTapped();
                        if (typeof sidebarShowToast === 'function') sidebarShowToast(n.kind === 'todo' ? 'TODO added' : 'Note added');
                        if (typeof refreshSceneIfChangedOnDisk === 'function') refreshSceneIfChangedOnDisk(n.path);
                    })
                    .catch(function() {
                        button.disabled = false;
                        status.textContent = 'Not added: the Mac cannot be reached. Your text is kept on this phone.';
                        status.classList.add('pv-error');
                        showOffline();
                    });
            }

            // ── Chat ────────────────────────────────────────────────────────────
            // Return never sends on the phone; the Send button does.

            function guardComposerEnter(event) {
                if (!root.classList.contains('pv-phone')) return;
                if (event.key !== 'Enter' || event.target.id !== 'discussInput') return;
                if (event.isComposing) return;
                event.stopImmediatePropagation();
            }

            // ── Laptop: the QR code and the phone dot ───────────────────────────

            function remotePhones(count) {
                root.dataset.remotePhones = String(count || 0);
            }

            // ── Wiring ──────────────────────────────────────────────────────────

            function apply() {
                var phone = wantsPhone();
                root.classList.toggle('pv-phone', phone);
                if (phone) {
                    buildOfflineBanner();
                    buildBar();
                    renderHome();
                    syncBar();
                }
            }

            function init() {
                apply();
                try {
                    window.matchMedia(NARROW_QUERY).addEventListener('change', apply);
                } catch (err) { /* older browsers keep the first layout */ }
                trackViewport();
                // Views change by attribute, not always by a hash change
                // (opening a scene replaces the history entry).
                var lastView = root.dataset.view || '';
                var lastScenePath = '';
                new MutationObserver(function() {
                    if (!root.classList.contains('pv-phone')) return;
                    var view = root.dataset.view || '';
                    var scene = view === 'scene' && curIdx >= 0 ? paths[curIdx] : '';
                    if (view === lastView && scene === lastScenePath) return;
                    lastView = view;
                    lastScenePath = scene;
                    clearTapped();
                    syncBar();
                    if (!view) renderHome();
                }).observe(root, {attributes: true, attributeFilter: ['data-view']});
                window.addEventListener('hashchange', function() {
                    if (!root.classList.contains('pv-phone')) return;
                    clearTapped();
                    syncBar();
                });
                document.addEventListener('click', onSceneTap);
                document.addEventListener('keydown', guardComposerEnter, true);
                document.addEventListener('visibilitychange', function() {
                    // Phones leave half-dead connections behind after sleep.
                    if (document.visibilityState === 'visible' && root.classList.contains('pv-phone')) {
                        ping().then(function(ok) {
                            if (ok) {
                                if (state.offline) retry();
                                else if (typeof window.pvReconnectEvents === 'function') window.pvReconnectEvents();
                            } else {
                                showOffline();
                            }
                        });
                    }
                });
                var input = document.getElementById('discussInput');
                if (input) input.setAttribute('enterkeyhint', 'enter');
            }

            window.pvConnectionDown = connectionDown;
            window.pvConnectionUp = connectionUp;
            window.pvRemotePhones = remotePhones;

            return {
                init: init,
                apply: apply,
                retry: retry,
                showOffline: showOffline,
                openQuickEdit: openQuickEdit,
                openNoteSheet: openNoteSheet,
                splitNote: splitNote,
                state: state,
            };
        })();

        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', pvPhone.init);
        else pvPhone.init();
