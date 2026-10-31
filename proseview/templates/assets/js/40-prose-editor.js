        // Keep the scene's editor state, history included, for its next mount.
        function stashSceneEditorState() {
            if (!_pmView || !_pmViewPath) return;
            delete _pmUndoStates[_pmViewPath];
            _pmUndoStates[_pmViewPath] = _pmView.state;
            var keys = Object.keys(_pmUndoStates);
            if (keys.length > 20) delete _pmUndoStates[keys[0]];
        }

        function mountProseView(p) {
            if (_pmView) { stashSceneEditorState(); _pmView.destroy(); _pmView = null; }
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
                Object.assign({}, PM.defaultMarkdownParser.tokens, calloutParserTokens, {
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
                buildCalloutTitlePlugin(PM),
                (typeof buildAiProposalPlugin === 'function' ? buildAiProposalPlugin(PM) : null),
                buildListInputRules(PM),
                PM.history(),
                PM.keymap({
                    'ArrowRight': caretIntoGap(PM, 'right'),
                    'ArrowDown': caretIntoGap(PM, 'down'),
                    'ArrowLeft': caretIntoGap(PM, 'left'),
                    'ArrowUp': caretIntoGap(PM, 'up')
                }),
                clickBetweenContainers(PM),
                // Lets the caret sit between two blocks that hold no text,
                // such as TODOs stacked one after another, so the writer can
                // type there.
                PM.gapCursor(),
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
                    'Mod-s': function() {
                        // Nothing changed: still leave edit mode, as a save
                        // would, and say so without writing the file.
                        if (!_pmDirty && !_pmSaveInFlight) {
                            if (cancelSceneEdit() !== false && typeof sidebarShowToast === 'function') {
                                sidebarShowToast(SCENE_UNCHANGED_TOAST);
                            }
                            return true;
                        }
                        saveSceneEdit();
                        return true;
                    }
                }))
            ].filter(Boolean);

            var state = null;
            var kept = _pmUndoStates[p];
            if (kept && kept.schema === PM.mySchema) {
                try {
                    // Same history, fresh plugins: undo reaches back past
                    // saves and past leaving edit mode.
                    state = kept.reconfigure({ plugins: plugins });
                    if (!state.doc.eq(doc)) {
                        // The file changed since -- Codex edited it, or edits
                        // were thrown away. The change is one more step, so
                        // undo can take it back too.
                        state = state.apply(state.tr.replaceWith(0, state.doc.content.size, doc.content));
                    }
                } catch (e) {
                    state = null;
                }
            }
            if (!state || !state.doc.eq(doc)) state = PM.EditorState.create({ doc: doc, plugins: plugins });
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
                    if (window._editBarFollowSelection) window._editBarFollowSelection();
                },
                nodeViews: {
                    annotation: PM.createAnnotationNodeView,
                    callout: createCalloutNodeView
                }
            });

            _pmViewPath = p;
            initAffordance(_pmView);
            updatePMHighlightDecorations();
            ensureSceneHighlights(p);
            if (typeof refreshSceneRhythm === 'function') refreshSceneRhythm();

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

        // Whether `needle` sits at `at` in `text` as whole words, so a
        // highlight for "route" never lands inside "routes".
        function _hlTextAt(text, needle, at) {
            if (text.substr(at, needle.length) !== needle) return false;
            var word = /[\p{L}\p{N}_]/u;
            return !(at > 0 && word.test(text[at - 1]) && word.test(needle[0]))
                && !(word.test(text[at + needle.length] || '') && word.test(needle[needle.length - 1]));
        }

        function _hlFindText(text, needle, from) {
            for (var at = text.indexOf(needle, from); at >= 0; at = text.indexOf(needle, at + 1)) {
                if (_hlTextAt(text, needle, at)) return at;
            }
            return -1;
        }

        // Whether the caret can stop at a top-level gap between these two
        // blocks: beside a TODO or note, or between two blocks that hold
        // their text inside them, such as two quotes in a row. The gap
        // cursor alone offers neither: text inside the blocks could already
        // take the caret, so it sees no need to stop between them.
        function isGapBetween(before, after) {
            if (!before || !after) return false;
            if (before.type.name === 'annotation' || after.type.name === 'annotation') return true;
            return !before.isTextblock && !before.isAtom && !after.isTextblock && !after.isAtom;
        }

        // An arrow key at the edge of text (a paragraph, the end of a quote)
        // next to such a gap stops in it, ready to type there.
        function caretIntoGap(PM, dir) {
            return function(state, dispatch, view) {
                var sel = state.selection;
                if (!(sel instanceof PM.TextSelection) || !sel.empty) return false;
                var $head = sel.$head;
                var forward = dir === 'right' || dir === 'down';
                if ($head.depth < 1 || !$head.parent.isTextblock) return false;
                if ($head.parentOffset !== (forward ? $head.parent.content.size : 0)) {
                    if (dir === 'left' || dir === 'right' || !view.endOfTextblock(dir)) return false;
                }
                // The caret must be at that edge of every block it is in.
                for (var d = $head.depth - 1; d >= 1; d--) {
                    var index = $head.index(d);
                    if (forward ? index !== $head.node(d).childCount - 1 : index !== 0) return false;
                }
                var pos = forward ? $head.after(1) : $head.before(1);
                var $pos = state.doc.resolve(pos);
                var beside = forward ? $pos.nodeAfter : $pos.nodeBefore;
                var own = $head.node(1);
                var isGap = beside && (beside.type.name === 'annotation' ||
                    isGapBetween(forward ? own : beside, forward ? beside : own));
                if (!isGap) return false;
                if (dispatch) dispatch(state.tr.setSelection(new PM.GapCursor($pos)).scrollIntoView());
                return true;
            };
        }

        // A click in the space between two such blocks puts the caret in
        // the gap. The browser would otherwise drop it into the nearer
        // block's text, leaving no way to type between two quotes.
        function clickBetweenContainers(PM) {
            return new PM.Plugin({
                props: {
                    handleClick: function(view, pos, event) {
                        if (event.target !== view.dom) return false;
                        var doc = view.state.doc, found = null, prev = null;
                        doc.forEach(function(node, offset) {
                            if (found !== null) return;
                            var dom = view.nodeDOM(offset);
                            if (!dom || !dom.getBoundingClientRect) { prev = null; return; }
                            var rect = dom.getBoundingClientRect();
                            if (prev && event.clientY >= prev.bottom && event.clientY <= rect.top &&
                                isGapBetween(prev.node, node)) found = offset;
                            prev = { node: node, bottom: rect.bottom };
                        });
                        if (found === null) return false;
                        view.dispatch(view.state.tr.setSelection(new PM.GapCursor(doc.resolve(found))));
                        return true;
                    }
                }
            });
        }

        // A scene's highlight marks are fetched when it opens, not carried in
        // the page: from the server, or (01-static-snapshot.js) from
        // highlights/<scene>.json beside a snapshot. Kept until the scene
        // changes, which drops them (see the refresh in 60-selection.js).
        var _hlLoading = Object.create(null);
        function ensureSceneHighlights(path) {
            if (!path || highlightsByPath[path]) return Promise.resolve(highlightsByPath[path] || null);
            if (_hlLoading[path]) return _hlLoading[path];
            var url = '/api/scene/highlights?path=' + encodeURIComponent(path);
            _hlLoading[path] = fetch(url).then(function(r) { return r.json(); }).then(function(data) {
                delete _hlLoading[path];
                if (!data || data.ok === false) return null;
                highlightsByPath[path] = {paragraphs: data.paragraphs || [], highlights: data.highlights || {},
                                          stats: data.stats || {}};
                if (typeof paths !== 'undefined' && paths[curIdx] === path) {
                    updatePMHighlightDecorations();
                    if (typeof refreshScenePassList === 'function') refreshScenePassList(path);
                }
                return highlightsByPath[path];
            }).catch(function() { delete _hlLoading[path]; return null; });
            return _hlLoading[path];
        }

        // The word a Repeats mark is, in all its forms ("block/blocks").
        function _hlRepeatGroup(inst) {
            return inst.group || String(inst.text || '').toLowerCase();
        }

        function updatePMHighlightDecorations() {
            if (!_pmView || !window._PM) return;
            var p = paths[curIdx];
            var PM = window._PM;
            // Whichever way the scene was drawn, its marks are fetched if
            // they have not been yet; this runs again once they arrive.
            if (!highlightsByPath[p]) ensureSceneHighlights(p);
            var sceneHls = highlightsByPath[p] || { paragraphs: [], highlights: {} };
            var hlData = sceneHls.highlights || {};
            var doc = _pmView.state.doc;

            // The scene's text as the editor holds it, with the document
            // position of every character, and where each top-level block's
            // text starts and ends in it. The server's paragraphs are those
            // blocks (a callout is one, title and body), but its offsets
            // count its own markdown-stripped text in code points, which
            // drifts after an emoji, an escape, an intraword underscore or a
            // line break. So each highlight goes on the matching word in its
            // block nearest to where the server put it.
            var lower = '', posAt = [], blocks = [];
            doc.forEach(function(top, topOffset) {
                var block = { start: lower.length };
                function addText(node, pos) {
                    lower += '\n';
                    posAt.push(pos);
                    node.forEach(function(child, offset) {
                        var start = pos + 1 + offset;
                        var t = child.isText ? child.text : '\uFFFC';
                        // Lowercase only where it keeps the length ("İ" does not).
                        if (t.toLowerCase().length === t.length) t = t.toLowerCase();
                        for (var i = 0; i < t.length; i++) posAt.push(start + i);
                        lower += t;
                    });
                }
                if (top.isTextblock) addText(top, topOffset);
                else top.descendants(function(node, pos) {
                    if (!node.isTextblock) return true;
                    addText(node, topOffset + 1 + pos);
                    return false;
                });
                block.end = lower.length;
                blocks.push(block);
            });

            var decorations = [];
            var seenEcho = {};
            var echoSizes = {};
            // Each word's place in its echo, in reading order: 1 of 3, 2 of 3.
            var echoPlace = [];
            (hlData.echoes || []).forEach(function(inst, i) {
                var g = (inst.note || '').split(' \u00b7 ')[0];
                echoSizes[g] = (echoSizes[g] || 0) + 1;
                echoPlace[i] = echoSizes[g];
            });
            // A repeated word's place among its uses in the scene, forms
            // counted together, numbered the same way.
            var repeatSizes = {};
            var repeatPlace = [];
            (hlData.repeats || []).forEach(function(inst, i) {
                var g = _hlRepeatGroup(inst);
                repeatSizes[g] = (repeatSizes[g] || 0) + 1;
                repeatPlace[i] = repeatSizes[g];
            });
            PASS_ORDER.forEach(function(name) {
                if (!hls[name]) return;
                // Starts already marked, so two of the server's matches never
                // share one word and stack a second badge on it.
                var taken = {};
                (hlData[name] || []).forEach(function(inst, instIndex) {
                    var block = blocks[inst.paragraph_index];
                    if (!block || !inst.char_offsets || !inst.text) return;
                    // A paragraph wrapped over several lines in the file reads as
                    // one line in the editor: its line breaks are spaces there.
                    var needle = inst.text.toLowerCase().replace(/[ \t]*\n[ \t]*/g, ' ');
                    // +1: the block's text starts with a separator.
                    var want = block.start + 1 + inst.char_offsets[0], at = -1;
                    for (var cand = _hlFindText(lower, needle, block.start); cand >= 0 && cand + needle.length <= block.end;
                         cand = _hlFindText(lower, needle, cand + 1)) {
                        if (!taken[cand] && (at < 0 || Math.abs(cand - want) < Math.abs(at - want))) at = cand;
                    }
                    if (at < 0) return;
                    taken[at] = true;
                    var from = posAt[at];
                    var to = posAt[at + needle.length - 1] + 1;
                    if (from >= to || to > doc.content.size) return;
                    var cls = PASS_CLASSES[name] || '';
                    var attrs = { class: cls };
                    if (name === 'echoes') {
                        // Which word of its echo this is and how many it has
                        // (2/3), after the word as Repeats shows its count; the
                        // first word of an echo is lighter,
                        // and the group lets pointing at one light its partners.
                        var group = (inst.note || '').split(' \u00b7 ')[0];
                        var size = (echoPlace[instIndex] || '?') + '/' + (echoSizes[group] || 0);
                        attrs['data-hl-group'] = 'echo-' + group;
                        if (!seenEcho[group]) { seenEcho[group] = true; attrs.class = cls + ' is-first'; }
                        decorations.push(PM.Decoration.widget(to, function() {
                            var badge = document.createElement('span');
                            badge.className = 'hl-echo-count';
                            badge.textContent = size;
                            return badge;
                        }, { side: -1, ignoreSelection: true, key: 'hl-echo-' + to + '-' + group + '-' + size }));
                    }
                    if (name === 'repeats') {
                        // Every form of the word, so pointing at one lights the rest.
                        if (inst.group) attrs['data-hl-repeat'] = inst.group;
                        // Which use of the word this is and how many the scene
                        // has (2/6), as an echo's words are numbered. It is its
                        // own widget after the word: another pass overlapping
                        // part of the word ("I" in "I'm") splits the inline
                        // span, and a badge on the span would then repeat
                        // after every piece.
                        var count = (repeatPlace[instIndex] || '?') + '/' + (repeatSizes[_hlRepeatGroup(inst)] || 0);
                        decorations.push(PM.Decoration.widget(to, function() {
                            var badge = document.createElement('span');
                            badge.className = 'hl-repeat-count';
                            badge.textContent = count;
                            return badge;
                        }, { side: -1, ignoreSelection: true, key: 'hl-count-' + to + '-' + count }));
                    }
                    
                    // Which mark this is, so a click can open its suggestion card.
                    attrs['data-hl-key'] = name + ':' + instIndex;
                    
                    decorations.push(PM.Decoration.inline(from, to, attrs));
                });
            });

            // Text a suggestion replaced, which stays clickable to undo it.
            if (typeof hlAppliedDecorations === 'function') hlAppliedDecorations(PM, p, lower, posAt, decorations);
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

        var SCENE_UNCHANGED_TOAST = 'No changes. Back to reading.';

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
            // Back to editing, the "No changes" note from the last Cmd+S
            // has nothing left to say.
            var toast = document.getElementById('sidebarFileToast');
            if (toast && !toast.hidden && toast.textContent === SCENE_UNCHANGED_TOAST) toast.hidden = true;
            var anchor = _sceneReadingAnchor();
            _pmEditMode = true;
            _pmView.setProps({ editable: function() { return true; } });
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) editBar.hidden = false;
            if (window._placeEditBar) window._placeEditBar();
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
            var nodes = Object.assign({}, PM.defaultMarkdownSerializer.nodes, calloutSerializerNodes, {
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
                    overwrite: !!overwrite,
                    // A save that applies or undoes a highlight suggestion is
                    // named so in History.
                    suggestion: window._pmNextSaveSuggestion || undefined
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

        // The edit bar can be dragged by any part of it. A press that moves
        // a few pixels becomes a drag; one that doesn't stays a click, so
        // the buttons work as before. Where it was left is remembered and
        // used the next time edit mode opens. While text is selected the
        // bar sits just above the selection, and goes back once it clears.
        (function() {
            var editBar = document.getElementById('sceneEditBar');
            if (!editBar) return;

            var STORE_KEY = 'proseview-edit-bar-pos';
            var DRAG_THRESHOLD = 4;
            var originalParent = editBar.parentNode;
            var originalNextSibling = editBar.nextSibling;

            var pressed = false, isDragging = false, justDragged = false;
            var atSelection = false, selectingWithMouse = false, followFrame = 0;
            var downX = 0, downY = 0, startX = 0, startY = 0;

            function clampInView(left, top) {
                var w = editBar.offsetWidth, h = editBar.offsetHeight;
                return {
                    left: Math.max(0, Math.min(left, window.innerWidth - w)),
                    top: Math.max(0, Math.min(top, window.innerHeight - h))
                };
            }

            function float(left, top) {
                if (editBar.parentNode !== document.body) document.body.appendChild(editBar);
                editBar.style.position = 'fixed';
                editBar.style.margin = '0';
                editBar.style.bottom = 'auto';
                editBar.style.right = 'auto';
                editBar.style.transform = 'none';
                editBar.style.zIndex = '3000';
                var p = clampInView(left, top);
                editBar.style.left = p.left + 'px';
                editBar.style.top = p.top + 'px';
            }

            editBar.addEventListener('mousedown', function(e) {
                if (e.button !== 0) return;
                pressed = true;
                downX = e.clientX;
                downY = e.clientY;
                var rect = editBar.getBoundingClientRect();
                startX = e.clientX - rect.left;
                startY = e.clientY - rect.top;
                // Keep the editor's caret and selection; buttons already do.
                if (!e.target.closest('button')) e.preventDefault();
            });

            document.addEventListener('mousemove', function(e) {
                if (!pressed) return;
                if (!isDragging) {
                    if (Math.abs(e.clientX - downX) < DRAG_THRESHOLD &&
                        Math.abs(e.clientY - downY) < DRAG_THRESHOLD) return;
                    isDragging = true;
                    editBar.classList.add('is-dragging');
                }
                float(e.clientX - startX, e.clientY - startY);
                e.preventDefault();
            });

            document.addEventListener('mouseup', function() {
                pressed = false;
                if (!isDragging) return;
                isDragging = false;
                justDragged = true;
                atSelection = false;
                editBar.classList.remove('is-dragging');
                try {
                    localStorage.setItem(STORE_KEY, JSON.stringify({
                        left: parseFloat(editBar.style.left), top: parseFloat(editBar.style.top)
                    }));
                } catch (err) {}
                setTimeout(function() { justDragged = false; }, 0);
            });

            // The click that ends a drag should not press the button under it.
            editBar.addEventListener('click', function(e) {
                if (!justDragged) return;
                justDragged = false;
                e.stopPropagation();
                e.preventDefault();
            }, true);

            // Called when edit mode opens: put the bar where it was left.
            window._placeEditBar = function() {
                atSelection = false;
                var saved = null;
                try { saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null'); } catch (err) {}
                if (saved && isFinite(saved.left) && isFinite(saved.top)) float(saved.left, saved.top);
                else if (window._resetEditBarPosition) window._resetEditBarPosition();
            };

            function followSelection() {
                followFrame = 0;
                if (!_pmView || !_pmEditMode || editBar.hidden || isDragging || selectingWithMouse) return;
                var sel = _pmView.state.selection;
                if (sel.empty) {
                    if (atSelection) window._placeEditBar();
                    return;
                }
                var start, end;
                try {
                    start = _pmView.coordsAtPos(sel.from);
                    end = _pmView.coordsAtPos(sel.to);
                } catch (err) { return; }
                var w = editBar.offsetWidth, h = editBar.offsetHeight;
                var oneLine = Math.abs(start.top - end.top) < 4;
                var x = oneLine ? (start.left + end.left) / 2 : start.left;
                var top = Math.min(start.top, end.top) - h - 22;
                if (top < 8) top = Math.max(start.bottom, end.bottom) + 22;
                float(x - w / 2, top);
                atSelection = true;
            }

            window._editBarFollowSelection = function() {
                if (!followFrame) followFrame = requestAnimationFrame(followSelection);
            };

            // Wait for a mouse selection to finish before moving the bar.
            document.addEventListener('mousedown', function(e) {
                if (e.button === 0 && e.target.closest && e.target.closest('#sceneProseHost')) selectingWithMouse = true;
            }, true);
            document.addEventListener('mouseup', function() {
                if (!selectingWithMouse) return;
                selectingWithMouse = false;
                window._editBarFollowSelection();
            }, true);
            document.addEventListener('scroll', function() {
                if (atSelection) window._editBarFollowSelection();
            }, true);

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

        // Pointing at an echo lights the other words in it, and pointing at a
        // repeated word lights its other uses.
        (function() {
            // An echo's words share data-hl-group; a repeated word's forms share
            // data-hl-repeat. A word marked by both lights both sets.
            var lit = null;
            function light(selector, on) {
                document.querySelectorAll(selector).forEach(function(el) {
                    el.classList.toggle('is-partner', on);
                });
            }
            document.addEventListener('mouseover', function(e) {
                var mark = e.target && e.target.closest
                    && e.target.closest('#sceneProseHost [data-hl-group], #sceneProseHost [data-hl-repeat]');
                var selector = mark ? ['data-hl-group', 'data-hl-repeat'].filter(function(attr) {
                    return mark.hasAttribute(attr);
                }).map(function(attr) {
                    return '#sceneProseHost [' + attr + '="' + CSS.escape(mark.getAttribute(attr)) + '"]';
                }).join(', ') : null;
                if (selector === lit) return;
                if (lit) light(lit, false);
                lit = selector;
                if (lit) light(lit, true);
            });
        })();
