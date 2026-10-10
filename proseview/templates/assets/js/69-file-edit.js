        // ── Editing notes in the file view ───────────────────────────────────────
        // Markdown outside the manuscript (the story bible, plans, outlines)
        // opens in the file view. Edit turns that view into an editor: the
        // scenes' own rich editor when the note round-trips through it intact,
        // otherwise the note's Markdown as plain text, so a table or a bit of
        // HTML is never rewritten by the act of editing. Saves go through
        // /api/files/save, which keeps the frontmatter, backs up the version it
        // replaces, and refuses to overwrite a file changed in another editor.

        var fileEdit = {
            path: '',
            mode: '',          // 'rich' or 'source'
            view: null,        // the ProseMirror view in rich mode
            sourceBlocks: null, // the note's blocks as written (12-lossless-markdown.js)
            lastCaret: null,    // {path, pos} when the editor last closed
            textarea: null,    // the textarea in source mode
            frontmatter: '',
            mtime: null,
            dirty: false,
            saving: false,
            original: '',
        };

        // Safe to call before this file's state exists: the dashboard renders
        // a file named in the URL while the page is still loading.
        function fileEditActive() { return typeof fileEdit !== 'undefined' && !!fileEdit && !!fileEdit.path; }

        function fileEditAllowed(node) {
            if (!node || !node.is_text || node.too_large || node.body === null || node.not_utf8) return false;
            if (!/\.(md|markdown)$/i.test(node.name || node.path || '')) return false;
            return !window.PROSEVIEW_STATIC || !!window.PROSEVIEW_STATIC_EDITS;
        }

        // Why the file on show cannot be edited, for E pressed on it; '' when
        // it can be (the editor may just be loading).
        function fileEditRefusal() {
            if (window.PROSEVIEW_STATIC && !window.PROSEVIEW_STATIC_EDITS) return 'This copy is read-only.';
            var path = typeof sidebarCurrentPath === 'function' ? sidebarCurrentPath() : '';
            var node = path && typeof repoFileByPath !== 'undefined' ? repoFileByPath[path] : null;
            if (!node) return '';
            if (!/\.(md|markdown)$/i.test(node.name || node.path || '')) return 'Only Markdown files can be edited in Proseview.';
            if (node.too_large) return 'This file is too large to edit in Proseview.';
            if (node.not_utf8) return 'This file is not saved as UTF-8, so Proseview shows it but does not edit it.';
            return '';
        }

        // Called by renderRepoFile every time the file view shows a file.
        function fileEditAfterRender(node) {
            var button = document.getElementById('filePreviewEditBtn');
            if (button) button.hidden = !fileEditAllowed(node);
        }

        // The text between a header's --- fences.
        function frontmatterInner(header) {
            var lines = String(header || '').replace(/\n$/, '').split('\n');
            return lines.length >= 2 ? lines.slice(1, -1).join('\n') : '';
        }

        function splitNoteHeader(raw) {
            // Mirrors split_note_header in server.py: the frontmatter block is
            // kept exactly as written and is not part of what is edited.
            var lines = raw.split('\n');
            if (lines.length && lines[0].trim() === '---') {
                for (var i = 1; i < lines.length; i++) {
                    var t = lines[i].trim();
                    if (t === '---' || t === '...') {
                        return {header: lines.slice(0, i + 1).join('\n') + '\n', body: lines.slice(i + 1).join('\n').replace(/^\n+/, '')};
                    }
                }
            }
            return {header: '', body: raw};
        }

        // The scene tokenizer plus tables. A table at the top of the note
        // becomes one table_raw token holding its source lines, which the
        // parser turns into a read-only raw_block; a save writes it back as
        // it was. Scenes keep the stock tokenizer.
        var _fileEditTokenizer = null;
        function fileEditTokenizer(PM) {
            if (_fileEditTokenizer) return _fileEditTokenizer;
            var md = new PM.defaultMarkdownParser.tokenizer.constructor('commonmark', {html: true}).enable('table');
            _fileEditTokenizer = {parse: function(src, env) {
                var lines = src.split('\n');
                var tokens = tokenizerKeepingInlineHtml(md).parse(src, env);
                var out = [];
                for (var i = 0; i < tokens.length; i++) {
                    var t = tokens[i];
                    if (t.type !== 'table_open' || t.level !== 0 || !t.map) { out.push(t); continue; }
                    var raw = new t.constructor('table_raw', '', 0);
                    raw.map = t.map;
                    raw.block = true;
                    raw.content = lines.slice(t.map[0], t.map[1]).join('\n').replace(/\s+$/, '');
                    out.push(raw);
                    while (i < tokens.length && !(tokens[i].type === 'table_close' && tokens[i].level === 0)) i++;
                }
                return out;
            }};
            return _fileEditTokenizer;
        }

        function fileEditParser(PM) {
            return new PM.MarkdownParser(
                PM.mySchema,
                fileEditTokenizer(PM),
                Object.assign({}, PM.defaultMarkdownParser.tokens, {
                    html_block: {node: 'annotation', getAttrs: function(tok) { return {raw: tok.content.trim()}; }},
                    html_inline: {ignore: true},
                    table_raw: {node: 'raw_block', getAttrs: function(tok) { return {raw: tok.content}; }},
                })
            );
        }

        // A table shown as a table, kept out of the editing.
        function fileEditRawBlockView(node) {
            var dom = document.createElement('div');
            dom.className = 'pm-raw-block';
            dom.contentEditable = 'false';
            dom.title = 'Tables are kept as written. Change them in your text editor.';
            renderSafeMarkdown(dom, node.attrs.raw, {basePath: fileEdit.path});
            return {dom: dom, ignoreMutation: function() { return true; }};
        }

        function fileEditSerializer(PM) {
            var nodes = Object.assign({}, PM.defaultMarkdownSerializer.nodes, {
                annotation: function(state, node) { state.write(node.attrs.raw); state.closeBlock(node); },
                raw_block: function(state, node) { state.write(node.attrs.raw); state.closeBlock(node); },
            });
            return new PM.MarkdownSerializer(nodes, PM.defaultMarkdownSerializer.marks);
        }

        function fileEditWords(text) {
            return (String(text).toLowerCase().match(/[\p{L}\p{N}]+/gu) || []).join(' ');
        }

        // Why a note must be edited as plain text, or '' when the rich editor keeps it intact.
        function fileEditPlainReason(body) {
            var PM = window._PM;
            if (!PM) return 'the editor is still loading';
            // A table inside a list or a quote has no block of its own to keep.
            try {
                if (fileEditTokenizer(PM).parse(body, {}).some(function(t) { return t.type === 'table_open'; })) {
                    return 'it has a table inside a list or quote';
                }
            } catch (error) {
                return 'it uses Markdown the editor cannot keep exactly';
            }
            // HTML on a line of its own is kept as a block; HTML inside a line
            // would be dropped by the rich editor.
            var inline = body.replace(/<!--[\s\S]*?-->/g, '').replace(/^[ \t]*<[^>\n]+>[ \t]*$/gm, '');
            if (/<\/?[a-zA-Z][^>\n]*>/.test(inline)) return 'it has HTML in its lines';
            try {
                var doc = fileEditParser(PM).parse(body);
                var back = fileEditSerializer(PM).serialize(doc);
                if (fileEditWords(back) !== fileEditWords(body)) return 'it uses Markdown the editor cannot keep exactly';
            } catch (error) {
                return 'it uses Markdown the editor cannot keep exactly';
            }
            return '';
        }

        function fileEditStatus(text) {
            var status = document.getElementById('fileEditStatus');
            if (status) status.textContent = text;
        }

        function fileEditSetDirty(dirty) {
            fileEdit.dirty = dirty;
            var save = document.getElementById('fileEditSave');
            if (save) save.disabled = !dirty || fileEdit.saving;
            fileEditStatus(dirty ? 'Unsaved changes' : (fileEdit.mode === 'source'
                ? 'Editing the Markdown as text' : 'Editing'));
        }

        function toggleFileEdit() {
            if (fileEditActive()) {
                cancelFileEdit();
                return;
            }
            var path = (typeof sidebarCurrentPath === 'function' && sidebarCurrentPath())
                || document.getElementById('filePreviewTitle').textContent;
            startFileEdit(path);
        }

        function startFileEdit(path) {
            if (!path || fileEditActive()) return;
            fileEditStatus('Opening…');
            // Always from disk: the cached copy may be older than the file.
            fetch('/repo-file?path=' + encodeURIComponent(path), {cache: 'no-store'}).then(function(response) {
                return response.json();
            }).then(function(data) {
                if (!data || !data.ok || !data.node || !fileEditAllowed(data.node)) {
                    throw new Error((data && data.error) || 'This file cannot be edited here.');
                }
                if (typeof repoFileByPath !== 'undefined') repoFileByPath[path] = data.node;
                mountFileEditor(data.node);
            }).catch(function(error) {
                if (typeof sidebarShowToast === 'function') sidebarShowToast(error.message, true);
            });
        }

        function mountFileEditor(node) {
            var parts = splitNoteHeader(node.body);
            var body = document.getElementById('filePreviewBody');
            var reason = fileEditPlainReason(parts.body);
            fileEdit.path = node.path;
            fileEdit.frontmatter = parts.header;
            fileEdit.frontmatterDraft = null;
            fileEdit.mtime = node.mtime;
            fileEdit.original = parts.body;
            fileEdit.mode = reason ? 'source' : 'rich';
            body.replaceChildren();
            body.classList.add('is-editing');
            var fmHost = document.createElement('div');
            fmHost.id = 'fileFrontmatter';
            body.appendChild(fmHost);
            renderFileFrontmatter();

            if (fileEdit.mode === 'rich') {
                var PM = window._PM;
                var host = document.createElement('div');
                host.className = 'file-edit-host';
                body.appendChild(host);
                var plugins = [
                    PM.history(),
                    PM.keymap(Object.assign({}, PM.baseKeymap, {
                        'Mod-z': PM.undo, 'Mod-y': PM.redo, 'Mod-Shift-z': PM.redo,
                        'Mod-b': PM.toggleMark(PM.mySchema.marks.strong),
                        'Mod-i': PM.toggleMark(PM.mySchema.marks.em),
                        'Mod-s': function() { saveFileEdit(false); return true; },
                        'Escape': function() { cancelFileEdit(); return true; },
                    })),
                ];
                if (PM.inputRules && PM.wrappingInputRule) {
                    plugins.push(PM.inputRules({rules: [
                        PM.wrappingInputRule(/^\s*([-+*])\s$/, PM.mdSchema.nodes.bullet_list, {tight: true}),
                        PM.wrappingInputRule(/^(\d+)\.\s$/, PM.mdSchema.nodes.ordered_list, function(m) { return {order: +m[1], tight: true}; }),
                    ]}));
                }
                var doc = fileEditParser(PM).parse(parts.body);
                fileEdit.sourceBlocks = markdownSourceBlocks(fileEditTokenizer(PM), parts.body, doc, fileEditSerializer(PM));
                fileEdit.view = new PM.EditorView(host, {
                    state: PM.EditorState.create({doc: doc, plugins: plugins}),
                    dispatchTransaction: function(tr) {
                        fileEdit.view.updateState(fileEdit.view.state.apply(tr));
                        if (tr.docChanged && !fileEdit.dirty) fileEditSetDirty(true);
                    },
                    nodeViews: {annotation: PM.createAnnotationNodeView, raw_block: fileEditRawBlockView},
                });
                if (fileEdit.lastCaret && fileEdit.lastCaret.path === node.path) {
                    var at = doc.resolve(Math.max(0, Math.min(fileEdit.lastCaret.pos, doc.content.size)));
                    fileEdit.view.dispatch(fileEdit.view.state.tr.setSelection(PM.TextSelection.near(at)).scrollIntoView());
                }
                fileEdit.view.focus();
            } else {
                var note = document.createElement('p');
                note.className = 'file-edit-note';
                note.textContent = 'This file opens as plain Markdown because ' + reason
                    + ', so it is saved exactly as you type it.';
                var area = document.createElement('textarea');
                area.className = 'file-edit-source';
                area.value = parts.body;
                area.setAttribute('aria-label', 'Markdown of ' + node.path);
                area.spellcheck = true;
                area.addEventListener('input', function() {
                    if (!fileEdit.dirty) fileEditSetDirty(true);
                    fileEditAutosize(area);
                });
                area.addEventListener('keydown', function(event) {
                    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
                        event.preventDefault();
                        saveFileEdit(false);
                    } else if (event.key === 'Escape') {
                        event.preventDefault();
                        cancelFileEdit();
                    }
                });
                body.appendChild(note);
                body.appendChild(area);
                fileEdit.textarea = area;
                fileEditAutosize(area);
                area.focus();
            }
            document.getElementById('fileEditBar').hidden = false;
            document.getElementById('fileEditConflict').hidden = true;
            var button = document.getElementById('filePreviewEditBtn');
            button.querySelector('span').textContent = 'Editing';
            button.setAttribute('aria-pressed', 'true');
            fileEditSetDirty(false);
        }

        // The file's frontmatter as a YAML box above the editor, or a button
        // to add one.
        function renderFileFrontmatter() {
            var host = document.getElementById('fileFrontmatter');
            if (!host) return;
            host.replaceChildren();
            if (!fileEdit.frontmatter && fileEdit.frontmatterDraft === null) {
                host.appendChild(addFrontmatterButton(function() {
                    fileEdit.frontmatterDraft = '';
                    renderFileFrontmatter();
                    host.querySelector('textarea').focus();
                }));
                return;
            }
            var text = fileEdit.frontmatterDraft !== null ? fileEdit.frontmatterDraft : frontmatterInner(fileEdit.frontmatter);
            var editor = frontmatterEditor(text, function(value) {
                fileEdit.frontmatterDraft = value;
                if (!fileEdit.dirty) fileEditSetDirty(true);
            });
            editor.querySelector('textarea').addEventListener('keydown', function(event) {
                if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
                    event.preventDefault();
                    saveFileEdit(false);
                }
            });
            host.appendChild(editor);
        }

        function fileEditAutosize(area) {
            area.style.height = 'auto';
            area.style.height = Math.max(320, area.scrollHeight + 4) + 'px';
        }

        function fileEditContent() {
            if (fileEdit.mode === 'rich' && fileEdit.view) return serializeKeepingSource(fileEdit.sourceBlocks, fileEdit.view.state.doc, fileEditSerializer(window._PM));
            return fileEdit.textarea ? fileEdit.textarea.value : '';
        }

        function unmountFileEditor() {
            if (fileEdit.view) {
                // Where the caret was, so E picks up from there.
                fileEdit.lastCaret = {path: fileEdit.path, pos: fileEdit.view.state.selection.head};
                fileEdit.view.destroy();
            }
            fileEdit.view = null;
            fileEdit.sourceBlocks = null;
            fileEdit.textarea = null;
            fileEdit.path = '';
            fileEdit.dirty = false;
            fileEdit.saving = false;
            document.getElementById('fileEditBar').hidden = true;
            document.getElementById('filePreviewBody').classList.remove('is-editing');
            var button = document.getElementById('filePreviewEditBtn');
            if (button) {
                button.querySelector('span').textContent = 'Edit';
                button.removeAttribute('aria-pressed');
            }
        }

        function cancelFileEdit(force) {
            if (!fileEditActive()) return;
            if (fileEdit.dirty && !force && !window.confirm('Discard your changes to ' + fileEdit.path + '?')) return;
            var path = fileEdit.path;
            unmountFileEditor();
            var node = typeof repoFileByPath !== 'undefined' ? repoFileByPath[path] : null;
            if (node) renderRepoFile(node, {route: false});
        }

        function saveFileEdit(overwrite) {
            if (!fileEditActive() || fileEdit.saving) return;
            if (!fileEdit.dirty && !overwrite) {
                cancelFileEdit(true);
                return;
            }
            var path = fileEdit.path;
            var content = fileEditContent();
            var frontmatter = fileEdit.frontmatterDraft !== null && fileEdit.frontmatterDraft !== frontmatterInner(fileEdit.frontmatter)
                ? fileEdit.frontmatterDraft : null;
            showFrontmatterError(document.getElementById('fileFrontmatter'), '');
            fileEdit.saving = true;
            document.getElementById('fileEditSave').disabled = true;
            fileEditStatus('Saving…');
            if (typeof _pendingSelfReloads !== 'undefined') _pendingSelfReloads++;
            fetch('/api/files/save', {
                method: 'POST',
                headers: pvHeaders(),
                body: JSON.stringify({path: path, content: content, open_mtime: fileEdit.mtime, overwrite: !!overwrite, frontmatter: frontmatter}),
            }).then(function(response) {
                return response.json().catch(function() { return {}; }).then(function(data) {
                    return {status: response.status, data: data};
                });
            }).then(function(result) {
                fileEdit.saving = false;
                if (result.status === 409) {
                    fileEditStatus('This file changed on disk since you opened it.');
                    document.getElementById('fileEditConflict').hidden = false;
                    document.getElementById('fileEditSave').disabled = true;
                    return;
                }
                if (!result.data.ok) {
                    fileEditSetDirty(true);
                    var message = result.data.error || 'something went wrong';
                    if (/frontmatter/i.test(message)) showFrontmatterError(document.getElementById('fileFrontmatter'), message);
                    fileEditStatus('Not saved: ' + message);
                    return;
                }
                var header = fileEdit.frontmatter;
                if (frontmatter !== null) {
                    var inner = frontmatter.replace(/^\n+|\n+$/g, '');
                    header = inner ? '---\n' + inner + '\n---\n' : '';
                }
                var raw = header ? header + '\n' + content.replace(/\n+$/, '') + '\n' : content.replace(/\n+$/, '') + '\n';
                var cached = (typeof repoFileByPath !== 'undefined' && repoFileByPath[path]) || {path: path, name: path.split('/').pop()};
                cached.body = raw;
                cached.mtime = result.data.mtime;
                cached.size = new Blob([raw]).size;
                if (typeof repoFileByPath !== 'undefined') repoFileByPath[path] = cached;
                unmountFileEditor();
                renderRepoFile(cached, {route: false});
                if (typeof sidebarShowToast === 'function') sidebarShowToast('Saved ' + path + '.');
            }).catch(function() {
                fileEdit.saving = false;
                fileEditSetDirty(true);
                fileEditStatus('Not saved: Proseview could not be reached. Is it still running?');
            });
        }

        (function initFileEdit() {
            var save = document.getElementById('fileEditSave');
            if (!save) return;
            save.addEventListener('click', function() { saveFileEdit(false); });
            document.getElementById('fileEditCancel').addEventListener('click', function() { cancelFileEdit(); });
            document.getElementById('fileEditOverwrite').addEventListener('click', function() { saveFileEdit(true); });
            document.getElementById('fileEditReload').addEventListener('click', function() {
                var path = fileEdit.path;
                unmountFileEditor();
                if (typeof repoFileByPath !== 'undefined') delete repoFileByPath[path];
                previewRepoFile(path, {route: false});
            });
            window.addEventListener('beforeunload', function(event) {
                if (fileEdit.dirty) {
                    event.preventDefault();
                    event.returnValue = '';
                }
            });
            // E opens the editor, as it does on a scene.
            document.addEventListener('keydown', function(event) {
                if (event.key !== 'e' && event.key !== 'E') return;
                if (event.ctrlKey || event.altKey || event.metaKey || event.defaultPrevented) return;
                if (document.documentElement.dataset.view !== 'file' || fileEditActive()) return;
                var target = event.target;
                var tag = (target && target.tagName || '').toUpperCase();
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (target && target.isContentEditable)) return;
                var button = document.getElementById('filePreviewEditBtn');
                if (!button || button.hidden || button.getClientRects().length === 0) {
                    var why = fileEditRefusal();
                    if (why && typeof sidebarShowToast === 'function') sidebarShowToast(why);
                    return;
                }
                event.preventDefault();
                toggleFileEdit();
            });
            // The rich editor loads after the page; show Edit once it is there.
            window.addEventListener('proseview:editor-ready', function() {
                if (document.documentElement.dataset.view !== 'file') return;
                var path = typeof sidebarCurrentPath === 'function' ? sidebarCurrentPath() : '';
                var node = path && typeof repoFileByPath !== 'undefined' ? repoFileByPath[path] : null;
                if (node) fileEditAfterRender(node);
            });
        })();
