        // ── AI proposal bridge ─────────────────────────────────────────────
        var _aiClientId = null;
        var _aiActiveProposal = null;
        var _aiProposalRange = null;
        var _aiProposalPluginKey = null;
        var _aiSelectedOptionIndex = 0;

        function aiClientId() {
            if (_aiClientId) return _aiClientId;
            try {
                _aiClientId = sessionStorage.getItem('proseview-ai-client-id');
                if (!_aiClientId) {
                    _aiClientId = 'pv-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
                    sessionStorage.setItem('proseview-ai-client-id', _aiClientId);
                }
            } catch (e) {
                _aiClientId = 'pv-' + Math.random().toString(36).slice(2);
            }
            return _aiClientId;
        }

        function currentScenePath() {
            return (document.documentElement.dataset.view === 'scene' && curIdx >= 0) ? paths[curIdx] : null;
        }

        function aiHeartbeat() {
            fetch('/ai/clients/heartbeat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({client_id: aiClientId(), active_scene: currentScenePath()})
            }).catch(function() {});
        }

        function buildAiProposalPlugin(PM) {
            if (!_aiProposalPluginKey) _aiProposalPluginKey = new PM.PluginKey('aiProposal');
            return new PM.Plugin({
                key: _aiProposalPluginKey,
                state: {
                    init: function() { return PM.DecorationSet.empty; },
                    apply: function(tr, set) {
                        var next = tr.getMeta(_aiProposalPluginKey);
                        if (next !== undefined) return next;
                        return set.map(tr.mapping, tr.doc);
                    }
                },
                props: {
                    decorations: function(state) { return _aiProposalPluginKey.getState(state); }
                }
            });
        }

        function aiDocTextMap(doc) {
            var text = '';
            var posMap = [];
            doc.descendants(function(node, pos) {
                if (node.isText) {
                    for (var i = 0; i < node.text.length; i++) {
                        text += node.text.charAt(i);
                        posMap.push(pos + i);
                    }
                } else if (node.isBlock && text && text.charAt(text.length - 1) !== '\n') {
                    text += '\n';
                    posMap.push(null);
                }
            });
            return {text: text, posMap: posMap};
        }

        function aiNormalizedTextMap(text) {
            var normalized = '';
            var offsets = [];
            var inSpace = false;
            for (var i = 0; i < text.length; i++) {
                var ch = text.charAt(i);
                if (/\s/.test(ch)) {
                    if (!inSpace) {
                        normalized += ' ';
                        offsets.push(i);
                        inSpace = true;
                    }
                } else {
                    normalized += ch;
                    offsets.push(i);
                    inSpace = false;
                }
            }
            var start = 0, end = normalized.length;
            while (start < end && /\s/.test(normalized.charAt(start))) start++;
            while (end > start && /\s/.test(normalized.charAt(end - 1))) end--;
            return {text: normalized.slice(start, end), offsets: offsets.slice(start, end)};
        }

        function aiResolveQuoteRange(map, quote) {
            quote = String(quote || '').trim();
            if (!quote) return null;
            var normDoc = aiNormalizedTextMap(map.text);
            var normQuote = aiNormalizedTextMap(quote);
            if (!normQuote.text) return null;
            var start = normDoc.text.indexOf(normQuote.text);
            if (start < 0) return null;
            if (normDoc.text.indexOf(normQuote.text, start + normQuote.text.length) >= 0) {
                return {error: 'The proposal quote appears more than once. Ask Codex to target a longer quote.'};
            }
            var end = start + normQuote.text.length;
            var from = null, to = null;
            for (var i = start; i < end; i++) {
                var textOffset = normDoc.offsets[i];
                if (textOffset === undefined) continue;
                if (map.posMap[textOffset] !== null && from === null) from = map.posMap[textOffset];
                if (map.posMap[textOffset] !== null) to = map.posMap[textOffset] + 1;
            }
            if (from === null || to === null || to <= from) return null;
            return {from: from, to: to};
        }

        function aiResolveRange(proposal) {
            if (!_pmView) return {error: 'No scene editor is mounted.'};
            var map = aiDocTextMap(_pmView.state.doc);
            var start = -1, end = -1;
            var quoteRange = aiResolveQuoteRange(map, proposal.resolved_quote || proposal.quote);
            if (quoteRange && quoteRange.error) return quoteRange;
            if (quoteRange) return quoteRange;
            if (proposal.range && typeof proposal.range.start === 'number' && typeof proposal.range.end === 'number') {
                start = proposal.range.start;
                end = proposal.range.end;
            } else {
                return {error: 'Could not find the proposal quote in this scene.'};
            }
            if (start < 0 || end <= start || end > map.posMap.length) {
                var fallback = aiResolveQuoteRange(map, proposal.resolved_quote || proposal.quote);
                if (fallback) return fallback;
                return {error: 'Proposal range is outside the current scene.'};
            }
            var from = null, to = null;
            for (var i = start; i < end; i++) {
                if (map.posMap[i] !== null && from === null) from = map.posMap[i];
                if (map.posMap[i] !== null) to = map.posMap[i] + 1;
            }
            if (from === null || to === null || to <= from) {
                var quoteFallback = aiResolveQuoteRange(map, proposal.resolved_quote || proposal.quote);
                if (quoteFallback) return quoteFallback;
                return {error: 'Could not map proposal range into the editor.'};
            }
            return {from: from, to: to};
        }

        function aiSetProposalHighlight(range) {
            if (!_pmView || !window._PM || !_aiProposalPluginKey) return;
            var PM = window._PM;
            var decos = range
                ? [PM.Decoration.inline(range.from, range.to, {
                    class: 'pm-ai-proposal-highlight',
                    'data-ai-proposal': 'active',
                    style: 'background-color: rgba(14, 165, 233, 0.38); box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.55); outline: 1px solid rgba(14, 165, 233, 0.75); border-radius: 3px;'
                })]
                : [];
            var set = PM.DecorationSet.create(_pmView.state.doc, decos);
            _pmView.dispatch(_pmView.state.tr.setMeta(_aiProposalPluginKey, set));
        }

        function aiMaybeRefocusActiveProposal(scenePath) {
            if (!_aiActiveProposal || _aiActiveProposal.file !== scenePath) return;
            aiFocusProposal(_aiActiveProposal, true);
        }

        function aiPanel() {
            var panel = document.getElementById('aiProposalPanel');
            if (panel) return panel;
            panel = document.createElement('div');
            panel.id = 'aiProposalPanel';
            panel.className = 'ai-proposal-panel';
            panel.hidden = true;
            document.body.appendChild(panel);
            return panel;
        }

        function aiPost(path, payload) {
            return fetch(path, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload || {})
            }).then(function(r) { return r.json(); });
        }

        function aiPatch(path, payload) {
            return fetch(path, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload || {})
            }).then(function(r) { return r.json(); });
        }

        function aiOriginalText(proposal, range) {
            if (!_pmView || !range) return proposal.resolved_quote || proposal.quote || '';
            try {
                return _pmView.state.doc.textBetween(range.from, range.to, '\n');
            } catch (e) {
                return proposal.resolved_quote || proposal.quote || '';
            }
        }

        function aiLineLabel(proposal, range) {
            var p = proposal.file;
            if (!p || !contents[p] || !range) return '';
            var original = aiOriginalText(proposal, range).trim();
            if (!original) return '';
            var needle = original.slice(0, 80);
            var idx = contents[p].indexOf(needle);
            if (idx < 0 && proposal.quote) idx = contents[p].indexOf(String(proposal.quote).trim().slice(0, 80));
            if (idx < 0) return '';
            var base = (meta[p] && meta[p].txt_line_offset) || 0;
            return 'Line ' + (base + contents[p].slice(0, idx).split('\n').length);
        }

        function aiTopLevelRange(range) {
            var result = {from: range.from, to: range.to};
            if (!_pmView || !range) return result;
            _pmView.state.doc.forEach(function(node, offset) {
                var start = offset;
                var end = offset + node.nodeSize;
                if (range.from >= start && range.from < end) result.from = start;
                if (range.to > start && range.to <= end) result.to = end;
            });
            return result;
        }

        function aiClearNativeSelection() {
            try {
                if (typeof clearSceneSelectionMemory === 'function') clearSceneSelectionMemory();
                else if (typeof clearPinnedSelectionHighlight === 'function') clearPinnedSelectionHighlight();
            } catch (e) {}
            try {
                var sel = window.getSelection && window.getSelection();
                if (sel) sel.removeAllRanges();
            } catch (e) {}
            try {
                if (_pmView && _pmView.dom) _pmView.dom.blur();
            } catch (e) {}
        }

        function aiScrollRangeIntoView(range) {
            if (!_pmView || !range) return;
            try {
                var coords = _pmView.coordsAtPos(range.from);
                var container = document.querySelector('#sceneModal .modal-content');
                if (!container) return;
                var cr = container.getBoundingClientRect();
                var delta = coords.top - cr.top - Math.max(80, cr.height * 0.25);
                container.scrollTop += delta;
            } catch (e) {}
        }

        function aiRenderPanel(proposal, range, error, needsClaim) {
            var panel = aiPanel();
            panel.hidden = false;
            panel.innerHTML = '';
            var title = document.createElement('div');
            title.className = 'ai-proposal-title';
            title.textContent = needsClaim ? 'Proposal available for this scene' : 'AI proposal';
            panel.appendChild(title);

            if (needsClaim) {
                var claimMsg = document.createElement('div');
                claimMsg.className = 'ai-proposal-message';
                claimMsg.textContent = proposal.message || 'Review this suggested edit.';
                panel.appendChild(claimMsg);
                var claim = document.createElement('button');
                claim.className = 'ai-proposal-primary';
                claim.type = 'button';
                claim.textContent = 'Review here';
                claim.onclick = function() {
                    proposal.client_id = aiClientId();
                    aiPatch('/ai/proposals/' + proposal.id, {client_id: aiClientId(), status: 'focused'});
                    aiFocusProposal(proposal, true);
                };
                panel.appendChild(claim);
                return;
            }

            var line = aiLineLabel(proposal, range);
            if (line) {
                var loc = document.createElement('div');
                loc.className = 'ai-proposal-location';
                loc.textContent = line;
                panel.appendChild(loc);
            }

            if (range && !error) {
                var originalWrap = document.createElement('div');
                originalWrap.className = 'ai-proposal-section';
                var originalLabel = document.createElement('div');
                originalLabel.className = 'ai-proposal-label';
                originalLabel.textContent = 'ORIGINAL';
                var originalText = document.createElement('div');
                originalText.className = 'ai-proposal-original';
                originalText.textContent = aiOriginalText(proposal, range);
                originalWrap.appendChild(originalLabel);
                originalWrap.appendChild(originalText);
                panel.appendChild(originalWrap);
            }

            var issueWrap = document.createElement('div');
            issueWrap.className = 'ai-proposal-section';
            var issueLabel = document.createElement('div');
            issueLabel.className = 'ai-proposal-label ai-proposal-label-issue';
            issueLabel.textContent = error ? 'ERROR' : 'ISSUE';
            var msg = document.createElement('div');
            msg.className = error ? 'ai-proposal-error' : 'ai-proposal-message';
            msg.textContent = error || proposal.message || 'Review this suggested edit.';
            issueWrap.appendChild(issueLabel);
            issueWrap.appendChild(msg);
            panel.appendChild(issueWrap);

            if (!error) {
                _aiSelectedOptionIndex = Math.min(_aiSelectedOptionIndex || 0, Math.max(0, (proposal.options || []).length - 1));
                var optionsLabel = document.createElement('div');
                optionsLabel.className = 'ai-proposal-label';
                optionsLabel.textContent = 'SUGGESTIONS';
                panel.appendChild(optionsLabel);
                (proposal.options || []).forEach(function(opt, idx) {
                    var item = document.createElement('div');
                    item.className = 'ai-proposal-option' + (idx === _aiSelectedOptionIndex ? ' is-selected' : '');
                    item.setAttribute('role', 'button');
                    item.tabIndex = 0;
                    item.onclick = function() {
                        _aiSelectedOptionIndex = idx;
                        aiRenderPanel(proposal, range, error, needsClaim);
                    };
                    var text = document.createElement('div');
                    text.className = 'ai-proposal-option-text';
                    text.textContent = opt.text || String(opt);
                    var choice = document.createElement('div');
                    choice.className = 'ai-proposal-choice';
                    choice.textContent = idx === _aiSelectedOptionIndex ? 'Selected' : 'Select';
                    item.appendChild(text);
                    item.appendChild(choice);
                    panel.appendChild(item);
                });
            } else {
                var useSelection = document.createElement('button');
                useSelection.className = 'ai-proposal-primary';
                useSelection.type = 'button';
                useSelection.textContent = 'Use current selection';
                useSelection.onclick = function() {
                    var selected = window.getSelection ? window.getSelection().toString().trim() : '';
                    if (!selected && typeof currentSelectionText !== 'undefined') {
                        selected = String(currentSelectionText || '').trim();
                    }
                    if (!selected) {
                        alert('Select the intended text in the scene first.');
                        return;
                    }
                    proposal.quote = selected;
                    proposal.status = 'updated';
                    proposal.error = null;
                    aiPatch('/ai/proposals/' + proposal.id, {
                        client_id: aiClientId(),
                        status: 'updated',
                        quote: selected,
                        error: null
                    });
                    aiFocusProposal(proposal, true);
                };
                panel.appendChild(useSelection);
            }

            var actions = document.createElement('div');
            actions.className = 'ai-proposal-actions';
            if (!error && (proposal.options || []).length) {
                var accept = document.createElement('button');
                accept.className = 'ai-proposal-primary';
                accept.type = 'button';
                accept.textContent = 'Accept selected';
                accept.onclick = function() { aiApplyProposal(proposal, _aiSelectedOptionIndex || 0); };
                actions.appendChild(accept);
            }
            var refine = document.createElement('button');
            refine.type = 'button';
            refine.textContent = 'Refine in terminal';
            refine.onclick = function() {
                if (typeof openCodexTerminal === 'function') {
                    openCodexTerminal(
                        'Refine proposal ' + proposal.id + ' for @' + proposal.file +
                        '. Update it with `proseview proposal update ' + proposal.id +
                        ' --option "..."` when ready.',
                        null,
                        false,
                        proposal.file
                    );
                }
            };
            var skip = document.createElement('button');
            skip.type = 'button';
            skip.textContent = 'Skip';
            skip.onclick = function() {
                aiPost('/ai/proposals/' + proposal.id + '/skip', {client_id: aiClientId()});
                aiClearProposal();
            };
            var dismiss = document.createElement('button');
            dismiss.type = 'button';
            dismiss.textContent = 'Dismiss';
            dismiss.onclick = aiClearProposal;
            actions.appendChild(refine);
            actions.appendChild(skip);
            actions.appendChild(dismiss);
            panel.appendChild(actions);
        }

        function aiClearProposal() {
            _aiActiveProposal = null;
            _aiProposalRange = null;
            aiSetProposalHighlight(null);
            var panel = document.getElementById('aiProposalPanel');
            if (panel) panel.hidden = true;
        }

        function aiFocusProposal(proposal, forceClaim) {
            if (!proposal || !proposal.file) return;
            var active = currentScenePath();
            if (active !== proposal.file) {
                openSceneModal(proposal.file);
                setTimeout(function() { aiFocusProposal(proposal, forceClaim); }, 120);
                return;
            }
            var belongsHere = !proposal.client_id || proposal.client_id === aiClientId();
            var needsClaim = (!!proposal.needs_target && !proposal.client_id) || (!belongsHere && !forceClaim);
            _aiActiveProposal = proposal;
            if (proposal.status === 'failed' && proposal.error && !forceClaim) {
                _aiProposalRange = null;
                aiSetProposalHighlight(null);
                aiRenderPanel(proposal, null, proposal.error, false);
                return;
            }
            var range = needsClaim ? null : aiResolveRange(proposal);
            if (range && range.error) {
                _aiProposalRange = null;
                aiSetProposalHighlight(null);
                if (proposal.status !== 'failed' || proposal.error !== range.error) {
                    aiPatch('/ai/proposals/' + proposal.id, {
                        client_id: aiClientId(),
                        status: 'failed',
                        error: range.error
                    });
                }
                aiRenderPanel(proposal, null, range.error, false);
                return;
            }
            _aiProposalRange = range;
            if (range && _pmView) {
                aiScrollRangeIntoView(range);
                aiClearNativeSelection();
            }
            aiSetProposalHighlight(range);
            aiRenderPanel(proposal, range, null, needsClaim);
        }

        function aiApplyProposal(proposal, optionIndex) {
            if (!_pmView || !_aiProposalRange) return;
            var opt = (proposal.options || [])[optionIndex];
            if (!opt) return;
            if (!_pmEditMode && typeof toggleSceneEdit === 'function') {
                toggleSceneEdit();
            }
            var PM = window._PM;
            var parser = new PM.MarkdownParser(
                PM.mySchema,
                PM.defaultMarkdownParser.tokenizer,
                Object.assign({}, PM.defaultMarkdownParser.tokens, {
                    html_block: {
                        node: 'annotation',
                        getAttrs: function(tok) { return { raw: tok.content.trim() }; }
                    },
                    html_inline: { ignore: true }
                })
            );
            var parsed = parser.parse(String(opt.text || '').trim());
            var tr;
            var selectionPos = _aiProposalRange.from;
            if (parsed.childCount === 1 && parsed.firstChild && parsed.firstChild.type.name === 'paragraph') {
                tr = _pmView.state.tr.replaceWith(
                    _aiProposalRange.from,
                    _aiProposalRange.to,
                    parsed.firstChild.content
                );
                selectionPos = _aiProposalRange.from + parsed.firstChild.content.size;
            } else {
                var blockRange = aiTopLevelRange(_aiProposalRange);
                tr = _pmView.state.tr.replaceWith(
                    blockRange.from,
                    blockRange.to,
                    parsed.content
                );
                selectionPos = blockRange.from + parsed.content.size;
            }
            tr = tr.setSelection(PM.TextSelection.near(tr.doc.resolve(Math.min(tr.doc.content.size, selectionPos)), 1));
            if (_aiProposalPluginKey) {
                tr = tr.setMeta(_aiProposalPluginKey, PM.DecorationSet.empty);
            }
            _pmView.dispatch(tr);
            aiSetProposalHighlight(null);
            aiClearNativeSelection();
            setTimeout(aiClearNativeSelection, 0);
            setTimeout(aiClearNativeSelection, 80);
            setPmDirty(true);
            aiPatch('/ai/proposals/' + proposal.id, {
                client_id: aiClientId(),
                status: 'accepted',
                selected_option: optionIndex
            });
            aiClearProposal();
        }

        function handleAiProposalEvent(payload) {
            if (!payload || payload.type !== 'ai:proposal') return;
            var proposal = payload.proposal || {};
            if (proposal.needs_target && !proposal.client_id && currentScenePath() !== proposal.file) return;
            if (payload.action === 'skip') {
                if (_aiActiveProposal && _aiActiveProposal.id === proposal.id) aiClearProposal();
                return;
            }
            if (proposal.status === 'skipped') {
                if (_aiActiveProposal && _aiActiveProposal.id === proposal.id) aiClearProposal();
                return;
            }
            if (proposal.client_id && proposal.client_id !== aiClientId()) return;
            if (payload.action === 'apply') {
                aiFocusProposal(proposal, true);
                setTimeout(function() {
                    aiApplyProposal(proposal, proposal.selected_option || 0);
                }, 150);
                return;
            }
            if (payload.action === 'created' || payload.action === 'updated' || payload.action === 'focus') {
                aiFocusProposal(proposal, false);
            }
        }

        aiClientId();
        aiHeartbeat();
        setInterval(aiHeartbeat, 5000);
