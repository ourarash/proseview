        // ── Source line-number gutter ────────────────────────────────────
        var LINE_NUMBERS_KEY = 'proseview-line-numbers';
        var _lineNumbersOn = false;
        try { _lineNumbersOn = localStorage.getItem(LINE_NUMBERS_KEY) === '1'; } catch(e) {}

        function _applyLineNumbersClass() {
            var mc = document.querySelector('#sceneModal .modal-content');
            if (mc) mc.classList.toggle('line-numbers', _lineNumbersOn);
            var btn = document.getElementById('modalLineNumbersBtn');
            if (btn) {
                btn.classList.toggle('is-active', _lineNumbersOn);
                btn.title = _lineNumbersOn ? 'Hide source line numbers' : 'Show source line numbers';
            }
        }
        function _applyEditingProseClass() {
            var mc = document.querySelector('#sceneModal .modal-content');
            if (mc) mc.classList.toggle('editing-prose', !!_pmEditMode);
        }
        function toggleLineNumbers() {
            _lineNumbersOn = !_lineNumbersOn;
            try { localStorage.setItem(LINE_NUMBERS_KEY, _lineNumbersOn ? '1' : '0'); } catch(e) {}
            _applyLineNumbersClass();
        }

        // Build a DecorationSet that tags each top-level PM block with its
        // source line number (1-indexed). Pairs markdown-it tokens with PM
        // doc children in document order: both lists are emitted top-to-
        // bottom in the same sequence, so a single index pointer keeps them
        // in sync. We stop annotating if the counts diverge instead of
        // surfacing wrong numbers.
        function _buildLineNumberDecorations(doc, markdown, lineOffset, absPath) {
            var PM = window._PM;
            if (!PM || !PM.defaultMarkdownParser || !PM.defaultMarkdownParser.tokenizer) {
                return PM ? PM.DecorationSet.empty : null;
            }
            var tokens;
            try {
                tokens = PM.defaultMarkdownParser.tokenizer.parse(markdown, {});
            } catch (e) {
                return PM.DecorationSet.empty;
            }
            // lineOffset is the source-file line where this scene's body
            // begins (frontmatter + heading lines, supplied by the
            // generator as meta[path].txt_line_offset). Without it, our
            // numbers would restart at 1 per scene instead of matching
            // the underlying .md file.
            var base = (typeof lineOffset === 'number' && lineOffset >= 0) ? lineOffset : 0;
            var blockLines = [];
            for (var i = 0; i < tokens.length; i++) {
                var t = tokens[i];
                if (t.level !== 0) continue;
                if (!t.map) continue;
                if (t.nesting === 1 || t.nesting === 0) {
                    blockLines.push(base + t.map[0] + 1);
                    if (t.nesting === 1) {
                        // Skip everything until the matching close to avoid
                        // counting nested block opens (list items, etc.).
                        var depth = 1;
                        for (var j = i + 1; j < tokens.length; j++) {
                            if (tokens[j].nesting === 1) depth++;
                            else if (tokens[j].nesting === -1) {
                                depth--;
                                if (depth === 0) { i = j; break; }
                            }
                        }
                    }
                }
            }

            var decos = [];
            var idx = 0;
            doc.forEach(function(node, offset) {
                if (idx >= blockLines.length) return;
                var line = blockLines[idx];
                decos.push(PM.Decoration.node(offset, offset + node.nodeSize, {
                    'data-line': String(line)
                }));
                if (absPath) {
                    decos.push(PM.Decoration.widget(offset + 1, function() {
                        var a = document.createElement('a');
                        a.className = 'pm-line-jump';
                        a.href = buildEditorUrl(absPath, line);
                        a.target = '_blank';
                        a.rel = 'noopener';
                        a.title = 'Open line ' + line + ' in ' + editorLabel;
                        a.textContent = '↗';
                        return a;
                    }, { side: -1, ignoreSelection: true, key: 'lj:' + line }));
                }
                idx++;
            });
            return PM.DecorationSet.create(doc, decos);
        }

        var lnPluginKey = null;
        function _buildLnPlugin() {
            var PM = window._PM;
            if (!PM) return null;
            if (!lnPluginKey) lnPluginKey = new PM.PluginKey('proseviewLineNumbers');
            return new PM.Plugin({
                key: lnPluginKey,
                state: {
                    init: function() { return PM.DecorationSet.empty; },
                    apply: function(tr, set) {
                        var next = tr.getMeta(lnPluginKey);
                        if (next !== undefined) return next;
                        return set.map(tr.mapping, tr.doc);
                    }
                },
                props: {
                    decorations: function(state) { return lnPluginKey.getState(state); }
                }
            });
        }

        function setPmDirty(dirty) {
            _pmDirty = !!dirty;
            var bar = document.getElementById('sceneEditBar');
            var saveBtn = bar ? bar.querySelector('.scene-edit-save') : null;
            var stateEl = document.getElementById('sceneEditState');
            var title = document.getElementById('modalTitle');
            if (bar) {
                bar.classList.toggle('is-dirty', _pmDirty);
                if (_pmDirty) {
                    bar.classList.remove('is-saving', 'is-saved');
                }
            }
            if (saveBtn) saveBtn.disabled = !_pmDirty;
            if (stateEl) stateEl.textContent = _pmDirty ? 'Editing • unsaved' : 'Editing';
            if (title) title.classList.toggle('is-modified', _pmDirty);
            if (_pmSavedFlashTimer) {
                clearTimeout(_pmSavedFlashTimer);
                _pmSavedFlashTimer = null;
            }
        }

        function setPmSaving() {
            var bar = document.getElementById('sceneEditBar');
            var stateEl = document.getElementById('sceneEditState');
            if (bar) bar.classList.add('is-saving');
            if (stateEl) stateEl.textContent = 'Saving…';
        }

        function setPmSaved() {
            var bar = document.getElementById('sceneEditBar');
            var stateEl = document.getElementById('sceneEditState');
            var title = document.getElementById('modalTitle');
            if (bar) {
                bar.classList.remove('is-saving', 'is-dirty');
                bar.classList.add('is-saved');
            }
            if (stateEl) stateEl.textContent = 'Saved';
            if (title) title.classList.remove('is-modified');
            _pmDirty = false;
            var saveBtn = bar ? bar.querySelector('.scene-edit-save') : null;
            if (saveBtn) saveBtn.disabled = true;
            if (_pmSavedFlashTimer) clearTimeout(_pmSavedFlashTimer);
            _pmSavedFlashTimer = setTimeout(function() {
                if (!bar) return;
                bar.classList.remove('is-saved');
                if (stateEl) stateEl.textContent = _pmEditMode ? 'Editing' : '';
                _pmSavedFlashTimer = null;
            }, 1600);
        }
        var _pmAffordancePara = null;
        var _pmAffordancePos = -1;
        var _pmAffordanceTimer = null;
        var _pmAnnotationPos = -1;
        var _pmAnnotationAutoSave = false;
