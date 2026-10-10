        function mountProseView(p) {
            if (_pmView) { _pmView.destroy(); _pmView = null; }
            var PM = window._PM;
            if (!PM) return;
            var host = document.getElementById('sceneProseHost');
            if (!host) return;

            var markdown = (contents[p] || '').trim();

            // Annotation is an atom node, and markdown-it emits a single
            // html_block token (not an open/close pair), so we use the
            // ``node:`` spec form rather than ``block:`` -- otherwise older
            // prosemirror-markdown registers html_block_open / _close
            // handlers that never match and the parser throws
            // "Token type `html_block` not supported".
            //
            // Inline HTML (raw HTML inside a paragraph) stays as literal
            // text; see tokenizerKeepingInlineHtml.
            var tokenizer = tokenizerKeepingInlineHtml(PM.defaultMarkdownParser.tokenizer);
            var parser = new PM.MarkdownParser(
                PM.mySchema,
                tokenizer,
                Object.assign({}, PM.defaultMarkdownParser.tokens, {
                    html_block: {
                        node: 'annotation',
                        getAttrs: function(tok) { return { raw: tok.content.trim() }; }
                    },
                    html_inline: { ignore: true }
                })
            );

            var doc = parser.parse(markdown);
            // What each block was in the file, so a save leaves untouched
            // blocks byte for byte (see 12-lossless-markdown.js).
            _pmSourceBlocks = markdownSourceBlocks(tokenizer, markdown, doc, sceneEditorSerializer(PM));

            var lnPlugin = _buildLnPlugin();

            function buildListInputRules(PM) {
                if (!PM.inputRules || !PM.wrappingInputRule) return null;
                return PM.inputRules({
                    rules: [
                        PM.wrappingInputRule(/^\s*([-+*])\s$/, PM.mdSchema.nodes.bullet_list, { tight: true }),
                        PM.wrappingInputRule(/^(\d+)\.\s$/, PM.mdSchema.nodes.ordered_list, match => ({order: +match[1], tight: true}), (match, node) => node.childCount + node.attrs.order == +match[1])
                    ]
                });
            }

            var plugins = [
                PM.buildHlPlugin(),
                lnPlugin,
                (typeof buildAiProposalPlugin === 'function' ? buildAiProposalPlugin(PM) : null),
                buildListInputRules(PM),
                PM.history(),
                PM.keymap(Object.assign({}, PM.baseKeymap, {
                    'Mod-z': PM.undo,
                    'Mod-y': PM.redo,
                    'Mod-Shift-z': PM.redo,
                    'Mod-b': PM.toggleMark(PM.mySchema.marks.strong),
                    'Mod-i': PM.toggleMark(PM.mySchema.marks.em),
                    'Mod-`': PM.toggleMark(PM.mySchema.marks.code),
                    'Mod-e': PM.toggleMark(PM.mySchema.marks.code),
                    'Enter': function(state, dispatch, view) {
                        return PM.chainCommands(PM.splitListItem(state.schema.nodes.list_item), PM.baseKeymap.Enter)(state, dispatch, view);
                    },
                    'Mod-Shift-8': function() { window.toggleList('bullet_list'); return true; },
                    'Mod-Shift-7': function() { window.toggleList('ordered_list'); return true; },
                    // Edit is a mode you enter on purpose, so saving finishes
                    // it, as the Save button does. E brings the caret back.
                    'Mod-s': function() { saveSceneEdit(); return true; }
                }))
            ].filter(Boolean);

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
                nodeViews: {
                    annotation: PM.createAnnotationNodeView
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
            if (typeof aiMaybeRefocusActiveProposal === 'function') {
                setTimeout(function() { aiMaybeRefocusActiveProposal(p); }, 0);
            }
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
                if (node.isTextblock) paraNodes.push(pos);
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
                    if (name === 'sensory' && inst.note) title += ' (' + inst.note + ')';
                    
                    var desc = PASS_INLINE_TIPS ? (PASS_INLINE_TIPS[name] || '') : '';
                    if (desc.indexOf('{word}') !== -1) desc = desc.split('{word}').join(inst.text);
                    
                    var attrs = { class: cls };
                    if (name === 'repeats') {
                        var parts = (inst.note || '').split('/');
                        var paraCount = parts[0] || '?';
                        var sceneCount = parts[1] || '?';
                        if (desc.indexOf('{para}') !== -1) desc = desc.split('{para}').join(paraCount);
                        if (desc.indexOf('{scene}') !== -1) desc = desc.split('{scene}').join(sceneCount);
                        attrs['data-count'] = paraCount + ' / ' + sceneCount;
                    }
                    
                    attrs['data-hl-title'] = title;
                    attrs['data-hl-desc'] = desc;
                    
                    decorations.push(PM.Decoration.inline(from, to, attrs));
                });
            });

            var decoSet = PM.DecorationSet.create(doc, decorations);
            var tr = _pmView.state.tr.setMeta(PM.hlPluginKey, decoSet);
            _pmView.dispatch(tr);
        }

        // The paragraph at the top of the reading view and where it sits, so
        // switching into or out of edit mode -- which swaps the frontmatter
        // block and the editor's own spacing -- leaves the page where it was.
        // Top-level blocks of the scene as [{index, dom}], by document
        // position: the DOM also holds widgets (line numbers, affordances)
        // that differ between reading and editing, so DOM order is not it.
        function _sceneBlocks() {
            var blocks = [];
            if (!_pmView) return blocks;
            _pmView.state.doc.forEach(function(node, offset, index) {
                var dom = _pmView.nodeDOM(offset);
                if (dom && dom.getBoundingClientRect) blocks.push({index: index, dom: dom});
            });
            return blocks;
        }

        function _sceneReadingAnchor() {
            var scrollEl = document.querySelector('#sceneModal .modal-content');
            if (!scrollEl || !_pmView) return null;
            var top = scrollEl.getBoundingClientRect().top;
            var blocks = _sceneBlocks();
            for (var i = 0; i < blocks.length; i++) {
                var rect = blocks[i].dom.getBoundingClientRect();
                if (rect.bottom > top + 1) return {scrollEl: scrollEl, index: blocks[i].index, offset: rect.top - top};
            }
            return null;
        }

        function _restoreSceneReadingAnchor(anchor) {
            if (!anchor) return;
            var block = _sceneBlocks().filter(function(b) { return b.index === anchor.index; })[0];
            if (!block) return;
            var top = anchor.scrollEl.getBoundingClientRect().top;
            var delta = (block.dom.getBoundingClientRect().top - top) - anchor.offset;
            // Instantly: the reading column scrolls smoothly, and an animated
            // correction is itself the jump this exists to prevent.
            if (delta) {
                _sceneScrollIsOursUntil = performance.now() + 100;
                anchor.scrollEl.scrollTo({top: anchor.scrollEl.scrollTop + delta, behavior: 'instant'});
            }
        }

        // Hold the anchor for the next moments too: the remounted editor
        // decorates its blocks (line numbers, highlights) a frame or two later,
        // which moves them again. Stops as soon as the writer scrolls.
        function _holdSceneReadingAnchor(anchor) {
            if (!anchor) return;
            _restoreSceneReadingAnchor(anchor);
            var expected = anchor.scrollEl.scrollTop;
            [16, 60, 150, 300].forEach(function(delay) {
                setTimeout(function() {
                    if (Math.abs(anchor.scrollEl.scrollTop - expected) > 1) return;
                    _restoreSceneReadingAnchor(anchor);
                    expected = anchor.scrollEl.scrollTop;
                }, delay);
            });
        }

        function toggleSceneEdit() {
            // A snapshot has nowhere to save to, so reading is all it offers --
            // unless it is the demo, whose saves stay in the visitor's tab.
            if (!window._PM || (window.PROSEVIEW_STATIC && !window.PROSEVIEW_STATIC_EDITS)) return;
            if (_pmEditMode) {
                cancelSceneEdit();
                return;
            }
            if (!_pmView) {
                render();
                if (!_pmView) return;
            }
            var anchor = _sceneReadingAnchor();
            _pmEditMode = true;
            _pmView.setProps({ editable: function() { return true; } });
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) editBar.hidden = false;
            var btn = document.getElementById('sceneEditBtn');
            if (btn) btn.textContent = '✗ Cancel';
            var p = paths[curIdx];
            _pmOpenMtime = meta[p] && meta[p].mtime;
            _pmFrontmatterDraft = null;
            renderSceneFrontmatter(p);
            setPmDirty(false);
            _applyEditingProseClass();
            // Back to the caret of the last edit of this scene, unless the
            // writer has since put it somewhere else.
            if (_pmLastCaret && _pmLastCaret.path === p && _pmView.state.selection.head <= 1) {
                var size = _pmView.state.doc.content.size;
                var at = _pmView.state.doc.resolve(Math.max(0, Math.min(_pmLastCaret.pos, size)));
                _pmView.dispatch(_pmView.state.tr.setSelection(window._PM.TextSelection.near(at)));
            }
            // Pressing E does not move the page. A caret that is not on screen
            // goes to the paragraph being read, so typing does not jump either.
            _restoreSceneReadingAnchor(anchor);
            if (anchor) {
                var coords = null;
                try { coords = _pmView.coordsAtPos(_pmView.state.selection.head); } catch (e) {}
                var view = anchor.scrollEl.getBoundingClientRect();
                if (!coords || coords.top < view.top + 80 || coords.bottom > view.bottom - 80) {
                    // The first paragraph that starts on screen, clear of the
                    // editor's scroll margin, so placing the caret scrolls nothing.
                    var blocks = _sceneBlocks();
                    var block = null;
                    for (var i = 0; i < blocks.length && !block; i++) {
                        if (blocks[i].index >= anchor.index && blocks[i].dom.getBoundingClientRect().top >= view.top + 80) block = blocks[i].dom;
                    }
                    try {
                        if (!block) throw new Error('no paragraph on screen');
                        var pos = _pmView.posAtDOM(block, 0);
                        _pmView.dispatch(_pmView.state.tr.setSelection(window._PM.TextSelection.near(_pmView.state.doc.resolve(pos))));
                    } catch (e) {}
                }
            }
            _pmView.focus();
            _holdSceneReadingAnchor(anchor);
        }

        // The scene's frontmatter above its prose: highlighted while reading,
        // a YAML box in edit mode.
        function renderSceneFrontmatter(p) {
            var host = document.getElementById('sceneFrontmatter');
            if (!host) return;
            host.replaceChildren();
            var text = meta[p] ? meta[p].frontmatter_text : null;
            if (_pmEditMode && (text === null || text === undefined) && _pmFrontmatterDraft === null) {
                host.appendChild(addFrontmatterButton(function() {
                    _pmFrontmatterDraft = '';
                    renderSceneFrontmatter(p);
                    var area = host.querySelector('textarea');
                    if (area) area.focus();
                }));
            } else if (_pmEditMode) {
                var editor = frontmatterEditor(_pmFrontmatterDraft !== null ? _pmFrontmatterDraft : (text || ''), function(value) {
                    _pmFrontmatterDraft = value;
                    if (!_pmDirty) setPmDirty(true);
                });
                editor.querySelector('textarea').addEventListener('keydown', function(event) {
                    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
                        event.preventDefault();
                        saveSceneEdit();
                    }
                });
                host.appendChild(editor);
            } else if (text !== null && text !== undefined) {
                host.appendChild(renderFrontmatterBlock(text));
            }
        }

        function sceneEditorSerializer(PM) {
            var nodes = Object.assign({}, PM.defaultMarkdownSerializer.nodes, {
                annotation: function(state, node) {
                    state.write(node.attrs.raw);
                    state.closeBlock(node);
                }
            });
            return new PM.MarkdownSerializer(nodes, PM.defaultMarkdownSerializer.marks);
        }

        function serializeSceneEditorMarkdown() {
            if (!_pmView || !window._PM) return '';
            return serializeKeepingSource(_pmSourceBlocks, _pmView.state.doc, sceneEditorSerializer(window._PM));
        }

        function currentSceneLiveDocumentSnapshot() {
            if (!_pmView || !_pmDirty || !_pmEditMode || _pmOpenMtime === null || _pmOpenMtime === undefined) return null;
            return {content: serializeSceneEditorMarkdown(), base_mtime: _pmOpenMtime};
        }

        function saveSceneEdit(onSaved, exitEditMode, overwrite) {
            if (!_pmView || !_pmEditMode) return;
            if (!_pmDirty) return;
            if (_pmSaveInFlight) return;
            var p = paths[curIdx];
            var markdown = serializeSceneEditorMarkdown();
            var savedFrontmatter = (meta[p] && meta[p].frontmatter_text) || '';
            var frontmatter = _pmFrontmatterDraft !== null && _pmFrontmatterDraft !== savedFrontmatter
                ? _pmFrontmatterDraft : null;
            _pmSaveInFlight = true;
            showFrontmatterError(document.getElementById('sceneFrontmatter'), '');

            // Stay in edit mode while the request is in flight; reflect
            // progress in the pill instead of yanking the bar away.
            setPmSaving();

            // The save will trigger an SSE "reload" event via the server's
            // file-watcher invalidation. Mark it expected so reloadOrDefer
            // can swallow it (else we'd get a jolting full page reload).
            // A frontmatter change moves story fields the whole dashboard
            // shows, so that reload is wanted and is let through.
            if (frontmatter === null) _pendingSelfReloads++;
            if (_pendingSelfReloadTimer) clearTimeout(_pendingSelfReloadTimer);
            _pendingSelfReloadTimer = setTimeout(function() {
                _pendingSelfReloads = 0;
                _pendingSelfReloadTimer = null;
            }, 4000);

            var absPath = meta[p] && meta[p].abs_path;
            fetch('/save-scene', {
                method: 'POST',
                headers: pvHeaders(),
                body: JSON.stringify({
                    abs_path: absPath,
                    content: markdown,
                    open_mtime: _pmOpenMtime,
                    frontmatter: frontmatter,
                    // Set only by the conflict dialog's explicit "mine wins".
                    // The server still backs up the version it replaces.
                    overwrite: !!overwrite
                })
            }).then(function(r) {
                if (r.status === 409) {
                    _pmSaveInFlight = false;
                    setPmDirty(true);
                    _pmConflictDraft = markdown;
                    var conflictButton = document.getElementById('sceneConflictReopen');
                    if (conflictButton) conflictButton.hidden = false;
                    openSceneConflictDialog();
                    return null;
                }
                return r.json();
            }).then(function(data) {
                if (!data) return;
                _pmSaveInFlight = false;
                if (!data.ok) {
                    setPmDirty(true);
                    var message = data.error || 'The scene could not be saved.';
                    if (!/frontmatter/i.test(message) || !showFrontmatterError(document.getElementById('sceneFrontmatter'), message)) {
                        alert('Save failed: ' + message);
                    }
                    return;
                }
                if (frontmatter !== null && meta[p]) {
                    meta[p].frontmatter_text = frontmatter.replace(/^\n+|\n+$/g, '') || null;
                    _pmFrontmatterDraft = null;
                    _dashboardStale = true;
                }
                if (data.mtime) _pmOpenMtime = data.mtime;
                // meta is the baseline every later write reads: the next edit
                // session and the annotation endpoints. refreshContent() would
                // normally carry the new mtime in, but it is a no-op while the
                // editor is open and never retries, so our own save has to
                // advance it. Leaving it stale makes the *next* save look like
                // someone else changed the file underneath us.
                if (meta[p] && data.mtime) meta[p].mtime = data.mtime;
                if (meta[p] && data.revision) meta[p].revision = data.revision;
                contents[p] = markdown;
                var liveMarkdown = serializeSceneEditorMarkdown();
                if (liveMarkdown !== markdown) {
                    setPmDirty(true);
                    return;
                }
                setPmSaved();
                clearSceneConflictState();
                if (typeof aiMarkAppliedProposalsSaved === 'function') aiMarkAppliedProposalsSaved();
                var historyPane = document.getElementById('sceneHistoryPane');
                if (historyPane && !historyPane.hidden && paths[curIdx] && typeof loadSceneHistory === 'function') {
                    loadSceneHistory(paths[curIdx]);
                }
                if (exitEditMode !== false) cancelSceneEdit();
                if (typeof onSaved === 'function') onSaved();
            }).catch(function(err) {
                _pmSaveInFlight = false;
                setPmDirty(true);
                alert('Save failed: ' + (err && err.message || 'unknown error'));
            });
        }

        function openSceneConflictDialog() {
            var dialog = document.getElementById('sceneConflictDialog');
            if (!dialog || !_pmConflictDraft) return;
            var status = document.getElementById('sceneConflictStatus');
            if (status) status.textContent = '';
            if (!dialog.open) dialog.showModal();
            var keep = dialog.querySelector('button');
            if (keep) keep.focus();
        }

        function keepEditingAfterConflict() {
            var dialog = document.getElementById('sceneConflictDialog');
            if (dialog && dialog.open) dialog.close('keep-editing');
            if (_pmView) _pmView.focus();
        }

        function currentConflictDraft() {
            // The writer may continue editing after the first 409. Use what is
            // in the editor now, not the snapshot captured at conflict time, so
            // no recovery action silently omits later work.
            return (_pmEditMode && _pmView) ? serializeSceneEditorMarkdown() : (_pmConflictDraft || '');
        }

        function clearSceneConflictState() {
            _pmConflictDraft = null;
            var conflictButton = document.getElementById('sceneConflictReopen');
            if (conflictButton) conflictButton.hidden = true;
            var dialog = document.getElementById('sceneConflictDialog');
            if (dialog && dialog.open) dialog.close('resolved');
        }

        function showConflictDiff() {
            var p = paths[curIdx];
            var absPath = meta[p] && meta[p].abs_path;
            if (!absPath) return;
            // A modal <dialog> renders in the top layer, so it would sit over
            // the diff overlay. Close it; closeDiffModal() brings it back.
            var dialog = document.getElementById('sceneConflictDialog');
            if (dialog && dialog.open) dialog.close('show-diff');
            openConflictDiffModal(absPath, currentConflictDraft());
        }

        function overwriteDiskWithConflictDraft() {
            var dialog = document.getElementById('sceneConflictDialog');
            if (dialog && dialog.open) dialog.close('overwrite');
            var overlay = document.getElementById('diffModalOverlay');
            if (overlay && !overlay.hidden) {
                // Drop the conflict chrome first so closeDiffModal() does not
                // read this as an unresolved conflict and reopen the dialog.
                document.getElementById('diffModalOverwriteBtn').hidden = true;
                closeDiffModal();
            }
            saveSceneEdit(null, false, true);
        }

        function copyConflictDraft() {
            var status = document.getElementById('sceneConflictStatus');
            var draft = currentConflictDraft();
            var copied = function() { if (status) status.textContent = 'Draft copied to the clipboard.'; };
            var failed = function() { if (status) status.textContent = 'Clipboard access was unavailable. Keep editing to preserve the draft.'; };
            if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(draft).then(copied, failed);
            else failed();
        }

        function reloadConflictDiskVersion() {
            var p = paths[curIdx];
            var dialog = document.getElementById('sceneConflictDialog');
            if (dialog && dialog.open) dialog.close('reload-disk');
            clearSceneConflictState();
            cancelSceneEdit();
            refreshContent([p]);
        }

        function cancelSceneEdit() {
            // The response still owns the acknowledged snapshot while a save
            // is in flight. Exiting now would let it mutate hidden editor
            // state and make the durable file disagree with the page.
            if (_pmSaveInFlight) return false;
            // Before anything changes the layout.
            var anchor = _sceneReadingAnchor();
            if (typeof aiDiscardAppliedProposals === 'function') aiDiscardAppliedProposals();
            _pmEditMode = false;
            _pmSaveInFlight = false;
            clearSceneConflictState();
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
            // Where the caret was, so E picks up from there.
            if (_pmView) _pmLastCaret = {path: p, pos: _pmView.state.selection.head};
            var scrollEl = document.querySelector('#sceneModal .modal-content');
            var bodyEl = document.getElementById('modalBody');
            if (scrollEl && bodyEl) bodyEl.style.minHeight = scrollEl.scrollHeight + 'px';
            _pmFrontmatterDraft = null;
            renderSceneFrontmatter(p);
            mountProseView(p);
            if (bodyEl) bodyEl.style.minHeight = '';
            _holdSceneReadingAnchor(anchor);
            return true;
        }

        window.addEventListener('beforeunload', function(event) {
            if (!_pmEditMode || !_pmDirty) return;
            event.preventDefault();
            event.returnValue = '';
        });

        var _hlTooltip = null;
        var _hlTooltipTimeout = null;

        function getHlTooltip() {
            if (!_hlTooltip) {
                _hlTooltip = document.createElement('div');
                _hlTooltip.className = 'hl-custom-tooltip';
                _hlTooltip.style.opacity = '0';
                document.body.appendChild(_hlTooltip);
            }
            return _hlTooltip;
        }

        document.addEventListener('mouseover', function(e) {
            var target = e.target;
            // Ignore prose view widgets and other things that aren't highlight spans
            if (target && target.classList && target.classList.contains('ProseMirror-widget')) return;
            
            var isHl = false;
            if (target && target.classList) {
                for (var i = 0; i < target.classList.length; i++) {
                    if (target.classList[i].startsWith('hl-')) {
                        isHl = true;
                        break;
                    }
                }
            }

            if (!isHl) {
                if (_hlTooltip && _hlTooltip.style.opacity !== '0') {
                    clearTimeout(_hlTooltipTimeout);
                    _hlTooltipTimeout = setTimeout(function() { _hlTooltip.style.opacity = '0'; }, 100);
                }
                return;
            }

            clearTimeout(_hlTooltipTimeout);
            var title = target.getAttribute('data-hl-title');
            var desc = target.getAttribute('data-hl-desc');
            if (!title) return;

            var tt = getHlTooltip();
            tt.innerHTML = '<div class="hl-title">' + title + '</div>' + 
                           (desc ? '<div class="hl-desc">' + desc + '</div>' : '') +
                           '<div class="hl-disable">To disable this highlight, go to the Analysis tab.</div>';
            
            tt.style.display = 'block';
            var rect = target.getBoundingClientRect();
            
            requestAnimationFrame(function() {
                var ttRect = tt.getBoundingClientRect();
                var top = rect.top - ttRect.height - 8;
                if (top < 0) top = rect.bottom + 8;
                var left = rect.left + (rect.width / 2) - (ttRect.width / 2);
                if (left < 10) left = 10;
                if (left + ttRect.width > window.innerWidth - 10) left = window.innerWidth - ttRect.width - 10;
                
                tt.style.top = top + window.scrollY + 'px';
                tt.style.left = left + window.scrollX + 'px';
                tt.style.opacity = '1';
            });
        });

        window.toggleFormat = function(markName) {
            if (!_pmView || !window._PM) return;
            var PM = window._PM;
            var markType = _pmView.state.schema.marks[markName];
            if (markType) {
                PM.toggleMark(markType)(_pmView.state, _pmView.dispatch);
                _pmView.focus();
            }
        };

        window.toggleList = function(listType) {
            if (!_pmView || !window._PM) return;
            var PM = window._PM;
            var state = _pmView.state;
            var dispatch = _pmView.dispatch.bind(_pmView);
            var nodeType = state.schema.nodes[listType];
            var itemType = state.schema.nodes.list_item;
            if (!nodeType || !itemType) return;
            
            // The innermost list around the selection decides what happens:
            // the same kind is taken away, the other kind is switched in
            // place, and only text in no list is wrapped in one. Switching by
            // lifting the items out and wrapping them again nested the lists,
            // or threw inside ProseMirror when the selection spanned items.
            var listTypes = [state.schema.nodes.bullet_list, state.schema.nodes.ordered_list];
            var $from = state.selection.$from;
            var listDepth = 0;
            for (var i = $from.depth; i > 0; i--) {
                if (listTypes.indexOf($from.node(i).type) >= 0) {
                    listDepth = i;
                    break;
                }
            }

            if (listDepth && $from.node(listDepth).type === nodeType) {
                if (PM.liftListItem && PM.liftListItem(itemType)(state)) {
                    PM.liftListItem(itemType)(state, dispatch);
                }
            } else if (listDepth) {
                var list = $from.node(listDepth);
                var attrs = {};
                Object.keys(nodeType.spec.attrs || {}).forEach(function(name) {
                    if (name in list.attrs) attrs[name] = list.attrs[name];
                });
                dispatch(state.tr.setNodeMarkup($from.before(listDepth), nodeType, attrs));
            } else if (PM.wrapInList && PM.wrapInList(nodeType, { tight: true })(state)) {
                PM.wrapInList(nodeType, { tight: true })(state, dispatch);
            }
            _pmView.focus();
        };

        window.toggleBlockquote = function() {
            if (!_pmView || !window._PM) return;
            var PM = window._PM;
            var state = _pmView.state;
            var nodeType = state.schema.nodes.blockquote;
            if (!nodeType) return;
            
            var dispatch = _pmView.dispatch.bind(_pmView);
            
            var isActive = false;
            var $from = state.selection.$from;
            for (var i = $from.depth; i > 0; i--) {
                if ($from.node(i).type === nodeType) {
                    isActive = true;
                    break;
                }
            }

            if (isActive) {
                if (PM.lift && PM.lift(state)) {
                    PM.lift(state, dispatch);
                }
            } else {
                if (PM.wrapIn && PM.wrapIn(nodeType)(state)) {
                    PM.wrapIn(nodeType)(state, dispatch);
                }
            }
            _pmView.focus();
        };

        (function() {
            var editBar = document.getElementById('sceneEditBar');
            var dragHandle = document.querySelector('.scene-edit-status');
            if (!editBar || !dragHandle) return;
            
            var originalParent = editBar.parentNode;
            var originalNextSibling = editBar.nextSibling;
            
            var isDragging = false;
            var startX = 0, startY = 0;
            
            dragHandle.style.cursor = 'grab';
            
            dragHandle.addEventListener('mousedown', function(e) {
                isDragging = true;
                dragHandle.style.cursor = 'grabbing';
                
                if (editBar.parentNode !== document.body) {
                    var rect = editBar.getBoundingClientRect();
                    document.body.appendChild(editBar);
                    editBar.style.position = 'fixed';
                    editBar.style.margin = '0';
                    editBar.style.bottom = 'auto';
                    editBar.style.right = 'auto';
                    editBar.style.left = rect.left + 'px';
                    editBar.style.top = rect.top + 'px';
                    editBar.style.transform = 'none';
                    editBar.style.zIndex = '3000';
                    startX = e.clientX - rect.left;
                    startY = e.clientY - rect.top;
                } else {
                    startX = e.clientX - parseFloat(editBar.style.left || 0);
                    startY = e.clientY - parseFloat(editBar.style.top || 0);
                }
                e.preventDefault();
            });
            
            document.addEventListener('mousemove', function(e) {
                if (!isDragging) return;
                var left = e.clientX - startX;
                var top = e.clientY - startY;
                editBar.style.left = left + 'px';
                editBar.style.top = top + 'px';
            });
            
            document.addEventListener('mouseup', function() {
                if (isDragging) {
                    isDragging = false;
                    dragHandle.style.cursor = 'grab';
                }
            });
            
            window._resetEditBarPosition = function() {
                if (editBar.parentNode !== originalParent) {
                    originalParent.insertBefore(editBar, originalNextSibling);
                    editBar.style.position = '';
                    editBar.style.margin = '';
                    editBar.style.bottom = '';
                    editBar.style.right = '';
                    editBar.style.left = '';
                    editBar.style.top = '';
                    editBar.style.transform = '';
                    editBar.style.zIndex = '';
                }
            };
        })();
