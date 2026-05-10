        function mountProseView(p) {
            if (_pmView) { _pmView.destroy(); _pmView = null; }
            var PM = window._PM;
            if (!PM) return;
            var host = document.getElementById('sceneProseHost');
            if (!host) return;

            var markdown = (contents[p] || '').trim();

            var parser = new PM.MarkdownParser(
                PM.mySchema,
                PM.defaultMarkdownParser.tokenizer,
                Object.assign({}, PM.defaultMarkdownParser.tokens, {
                    html_block: {
                        block: 'annotation',
                        getAttrs: function(tok) { return { raw: tok.content.trim() }; }
                    }
                })
            );

            var doc = parser.parse(markdown);

            var lnPlugin = _buildLnPlugin();
            var plugins = [
                PM.buildHlPlugin(),
                lnPlugin,
                PM.history(),
                PM.keymap(Object.assign({}, PM.baseKeymap, {
                    'Mod-z': PM.undo,
                    'Mod-y': PM.redo,
                    'Mod-Shift-z': PM.redo,
                    'Mod-b': PM.toggleMark(PM.mySchema.marks.strong),
                    'Mod-i': PM.toggleMark(PM.mySchema.marks.em),
                    'Mod-s': function() { saveSceneEdit(); return true; }
                }))
            ];

            var state = PM.EditorState.create({ doc: doc, plugins: plugins });
            _pmView = new PM.EditorView(host, {
                state: state,
                editable: function() { return _pmEditMode; },
                // Keep the cursor away from the very top/bottom of the
                // modal scroll container so arrow-key navigation produces
                // small, frequent scrolls instead of one large jump when
                // the cursor finally hits the edge.
                scrollThreshold: 80,
                scrollMargin: 80,
                // Track unsaved changes so the edit pill / title can show a
                // modified indicator. Only flips on transactions that
                // actually change the document, not selection-only ones.
                dispatchTransaction: function(tr) {
                    var newState = _pmView.state.apply(tr);
                    _pmView.updateState(newState);
                    if (_pmEditMode && tr.docChanged && !_pmDirty) {
                        setPmDirty(true);
                    }
                },
                handleClickOn: function(view, pos, node, nodePos, event, direct) {
                    if (node.type.name === 'annotation' && direct && _pmEditMode) {
                        setTimeout(function() { openAnnotationPopover(nodePos, node); }, 0);
                    }
                    return false;
                }
            });

            initAffordance(_pmView);
            updatePMHighlightDecorations();

            // Tag each top-level block with its source line and apply the
            // toggle's current state (so a freshly-mounted scene reflects
            // the saved preference).
            try {
                var lnSet = _buildLineNumberDecorations(_pmView.state.doc, markdown, (meta[p] && meta[p].txt_line_offset) || 0, meta[p] && meta[p].abs_path);
                if (lnSet) {
                    var tr = _pmView.state.tr.setMeta(lnPluginKey, lnSet);
                    _pmView.dispatch(tr);
                }
            } catch (e) {}
            _applyLineNumbersClass();
            _applyEditingProseClass();
        }

        function updatePMHighlightDecorations() {
            if (!_pmView || !window._PM) return;
            var p = paths[curIdx];
            var PM = window._PM;
            var sceneHls = highlightsByPath[p] || { paragraphs: [], highlights: {} };
            var hlData = sceneHls.highlights || {};
            var doc = _pmView.state.doc;

            var paraNodes = [];
            doc.descendants(function(node, pos) {
                if (node.type.name === 'paragraph') paraNodes.push(pos);
            });

            var decorations = [];
            PASS_ORDER.forEach(function(name) {
                if (!hls[name]) return;
                var insts = hlData[name] || [];
                insts.forEach(function(inst) {
                    var paraIdx = inst.paragraph_index;
                    var offsets = inst.char_offsets;
                    if (!offsets || paraIdx >= paraNodes.length) return;
                    var nodePos = paraNodes[paraIdx];
                    var from = nodePos + 1 + offsets[0];
                    var to = nodePos + 1 + offsets[1];
                    if (from >= to || to > doc.content.size) return;
                    var cls = PASS_CLASSES[name] || '';
                    var title = PASS_LABELS[name] || name;
                    if (inst.note) title += ' (' + inst.note + ')';
                    var attrs = { class: cls, title: title };
                    if (name === 'repeats' && inst.note) attrs['data-count'] = inst.note;
                    decorations.push(PM.Decoration.inline(from, to, attrs));
                });
            });

            var decoSet = PM.DecorationSet.create(doc, decorations);
            var tr = _pmView.state.tr.setMeta(PM.hlPluginKey, decoSet);
            _pmView.dispatch(tr);
        }

        function toggleSceneEdit() {
            if (!window._PM) return;
            if (_pmEditMode) {
                cancelSceneEdit();
                return;
            }
            if (!_pmView) {
                render();
                if (!_pmView) return;
            }
            _pmEditMode = true;
            _pmView.setProps({ editable: function() { return true; } });
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) editBar.hidden = false;
            var btn = document.getElementById('sceneEditBtn');
            if (btn) btn.textContent = '✗ Cancel';
            var p = paths[curIdx];
            _pmOpenMtime = meta[p] && meta[p].mtime;
            setPmDirty(false);
            _applyEditingProseClass();
            _pmView.focus();
        }

        function saveSceneEdit() {
            if (!_pmView || !_pmEditMode) return;
            if (!_pmDirty) return;
            var PM = window._PM;
            var p = paths[curIdx];

            var nodes = Object.assign({}, PM.defaultMarkdownSerializer.nodes, {
                annotation: function(state, node) {
                    state.write(node.attrs.raw);
                    state.closeBlock(node);
                }
            });
            var serializer = new PM.MarkdownSerializer(nodes, PM.defaultMarkdownSerializer.marks);
            var markdown = serializer.serialize(_pmView.state.doc);

            // Stay in edit mode while the request is in flight; reflect
            // progress in the pill instead of yanking the bar away.
            setPmSaving();

            // The save will trigger an SSE "reload" event via the server's
            // file-watcher invalidation. Mark it expected so reloadOrDefer
            // can swallow it (else we'd get a jolting full page reload).
            _pendingSelfReloads++;
            if (_pendingSelfReloadTimer) clearTimeout(_pendingSelfReloadTimer);
            _pendingSelfReloadTimer = setTimeout(function() {
                _pendingSelfReloads = 0;
                _pendingSelfReloadTimer = null;
            }, 4000);

            var absPath = meta[p] && meta[p].abs_path;
            fetch('/save-scene', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ abs_path: absPath, content: markdown, open_mtime: _pmOpenMtime })
            }).then(function(r) {
                if (r.status === 409) {
                    setPmDirty(true);
                    alert('Conflict: the file was modified externally. Close and reopen to reload.');
                    return null;
                }
                return r.json();
            }).then(function(data) {
                if (!data) return;
                if (!data.ok) { setPmDirty(true); return; }
                if (data.mtime) _pmOpenMtime = data.mtime;
                contents[p] = markdown;
                setPmSaved();
                cancelSceneEdit();
            }).catch(function(err) {
                setPmDirty(true);
                alert('Save failed: ' + (err && err.message || 'unknown error'));
            });
        }

        function cancelSceneEdit() {
            _pmEditMode = false;
            setPmDirty(false);
            _applyEditingProseClass();
            hideInsertAffordance();
            closeAnnotationPopover();
            if (_pmView) _pmView.setProps({ editable: function() { return false; } });
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) {
                editBar.hidden = true;
                editBar.classList.remove('is-saving', 'is-saved', 'is-dirty');
            }
            var btn = document.getElementById('sceneEditBtn');
            if (btn) btn.textContent = '✏ Edit';
            var p = paths[curIdx];
            mountProseView(p);
        }

