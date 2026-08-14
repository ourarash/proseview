        // ── AI proposal bridge ─────────────────────────────────────────────
        var _aiClientId = null;
        var _aiActiveProposal = null;
        var _aiProposalRange = null;
        var _aiProposalPluginKey = null;
        var _aiSelectedOptionIndex = 0;
        var _aiPendingSavedProposals = Object.create(null);
        // After an Accept the panel transitions to a confirmation view with an
        // Undo button. Holds the snapshot needed to revert the replacement.
        var _aiAppliedProposal = null;

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
                headers: pvHeaders(),
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
            if (proposal.range && typeof proposal.range.start === 'number' && typeof proposal.range.end === 'number') {
                start = proposal.range.start;
                end = proposal.range.end;
            }
            if (start >= 0 && end > start && end <= map.posMap.length) {
                var from = null, to = null;
                for (var i = start; i < end; i++) {
                    if (map.posMap[i] !== null && from === null) from = map.posMap[i];
                    if (map.posMap[i] !== null) to = map.posMap[i] + 1;
                }
                if (from !== null && to !== null && to > from) {
                    var expected = aiNormalizedTextMap(proposal.resolved_quote || proposal.quote || '').text;
                    var candidate = aiNormalizedTextMap(_pmView.state.doc.textBetween(from, to, '\n')).text;
                    if (!expected || candidate === expected) return {from: from, to: to};
                }
            }
            var quoteRange = aiResolveQuoteRange(map, proposal.resolved_quote || proposal.quote);
            if (quoteRange) return quoteRange;
            return {error: 'Could not safely resolve this proposal in the current scene.'};
        }

        function aiCurrentDecoratedRange() {
            if (!_pmView || !_aiProposalPluginKey) return null;
            try {
                var set = _aiProposalPluginKey.getState(_pmView.state);
                var decorations = set ? set.find() : [];
                if (decorations.length !== 1) return null;
                return {from: decorations[0].from, to: decorations[0].to};
            } catch (e) { return null; }
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
            if (!range) aiForceClearProposalHighlightDom();
        }

        function aiForceClearProposalHighlightDom() {
            try {
                document.querySelectorAll('.pm-ai-proposal-highlight, [data-ai-proposal="active"]').forEach(function(el) {
                    el.classList.remove('pm-ai-proposal-highlight');
                    if (el.getAttribute('data-ai-proposal') === 'active') el.removeAttribute('data-ai-proposal');
                    if (el.getAttribute('style')) el.removeAttribute('style');
                });
            } catch (e) {}
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
            panel.setAttribute('role', 'dialog');
            panel.setAttribute('aria-modal', 'false');
            panel.setAttribute('aria-labelledby', 'aiProposalTitle');
            panel.tabIndex = -1;
            panel.hidden = true;
            document.body.appendChild(panel);
            return panel;
        }

        function aiPost(path, payload) {
            return fetch(path, {
                method: 'POST',
                headers: pvHeaders(),
                body: JSON.stringify(payload || {})
            }).then(function(r) { return r.json(); });
        }

        function aiSetManagedTaskStatus(proposal, status, selectedOption) {
            if (!proposal || !proposal.conversation_id || typeof discussApi !== 'function') return;
            if (proposal.refactor_task_id && proposal.finding_id) {
                var decision = ({
                    rejected: 'rejected', dismissed: 'dismissed', applied: 'applied',
                    ready: 'proposal', saved: 'resolved'
                })[status];
                if (!decision) return;
                discussApi(
                    '/api/discuss/conversations/' + encodeURIComponent(proposal.conversation_id)
                    + '/tasks/' + encodeURIComponent(proposal.refactor_task_id)
                    + '/findings/' + encodeURIComponent(proposal.finding_id) + '/decision',
                    {decision: decision}
                ).then(function() { if (typeof scheduleDiscussSnapshot === 'function') scheduleDiscussSnapshot(); })
                    .catch(function() {});
                return;
            }
            if (!proposal.task_id) return;
            var payload = {status: status};
            if (Number.isInteger(selectedOption)) payload.selected_option = selectedOption;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(proposal.conversation_id) + '/tasks/' + encodeURIComponent(proposal.task_id) + '/status', payload)
                .then(function() { if (typeof scheduleDiscussSnapshot === 'function') scheduleDiscussSnapshot(); })
                .catch(function() {});
        }

        function aiPatch(path, payload) {
            return fetch(path, {
                method: 'PATCH',
                headers: pvHeaders(),
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
            title.id = 'aiProposalTitle';
            title.textContent = needsClaim ? 'Proposal available for this scene' : (proposal.action_id ? selectionActionLabel(proposal.action_id) + ' selection' : 'AI proposal');
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
                requestAnimationFrame(function() { panel.focus({preventScroll: true}); });
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
                optionsLabel.textContent = 'PROPOSED · ' + (_aiSelectedOptionIndex + 1) + ' OF ' + (proposal.options || []).length;
                panel.appendChild(optionsLabel);
                (proposal.options || []).forEach(function(opt, idx) {
                    if (idx !== _aiSelectedOptionIndex) return;
                    var item = document.createElement('div');
                    item.className = 'ai-proposal-option is-selected';
                    var text = document.createElement('div');
                    text.className = 'ai-proposal-option-text';
                    text.textContent = opt.text || String(opt);
                    item.appendChild(text);
                    if (opt.rationale) item.appendChild(elementWith('ai-proposal-rationale', opt.rationale));
                    panel.appendChild(item);
                });
                if ((proposal.options || []).length > 1) {
                    var nav = document.createElement('div'); nav.className = 'ai-proposal-nav';
                    var previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '← Previous'; previous.disabled = _aiSelectedOptionIndex === 0;
                    previous.onclick = function() { _aiSelectedOptionIndex--; aiRenderPanel(proposal, range, error, needsClaim); };
                    var next = document.createElement('button'); next.type = 'button'; next.textContent = 'Next →'; next.disabled = _aiSelectedOptionIndex >= proposal.options.length - 1;
                    next.onclick = function() { _aiSelectedOptionIndex++; aiRenderPanel(proposal, range, error, needsClaim); };
                    nav.appendChild(previous); nav.appendChild(next); panel.appendChild(nav);
                }
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
            if (!error && proposal.origin === 'managed_selection_action') {
                var shortcuts = document.createElement('div'); shortcuts.className = 'ai-proposal-shortcuts';
                shortcuts.textContent = 'A / ⌘Enter use · R reject · ← → alternatives · Esc close';
                panel.appendChild(shortcuts);
            }
            if (!error && (proposal.options || []).length) {
                var accept = document.createElement('button');
                accept.className = 'ai-proposal-primary';
                accept.type = 'button';
                accept.textContent = 'Use this version';
                accept.onclick = function() { aiApplyProposal(proposal, _aiSelectedOptionIndex || 0); };
                actions.appendChild(accept);
            }
            var refine = document.createElement('button');
            refine.type = 'button';
            refine.textContent = 'Refine…';
            refine.onclick = function() {
                aiClearProposal();
                openDiscussForSelection(null, proposal.resolved_quote || proposal.quote, {actionId: proposal.action_id || 'rephrase'});
                setTimeout(function() { var input = document.getElementById('discussInput'); input.value = 'Refine the selected rewrite with this constraint: '; input.focus(); saveDiscussDraft(); }, 80);
            };
            var retry = document.createElement('button'); retry.type = 'button'; retry.textContent = 'Try again';
            retry.onclick = function() { aiClearProposal(); openDiscussForSelection(null, proposal.resolved_quote || proposal.quote, {actionId: proposal.action_id || 'rephrase', runImmediately: true}); };
            var copy = document.createElement('button'); copy.type = 'button'; copy.textContent = 'Copy';
            copy.onclick = function() {
                var opt = (proposal.options || [])[_aiSelectedOptionIndex || 0];
                if (opt && navigator.clipboard) navigator.clipboard.writeText(opt.text || '').then(function() { copy.textContent = 'Copied'; setTimeout(function() { copy.textContent = 'Copy'; }, 1200); });
            };
            var skip = document.createElement('button');
            skip.type = 'button';
            skip.textContent = 'Reject';
            skip.onclick = function() {
                aiPost('/ai/proposals/' + proposal.id + '/skip', {client_id: aiClientId()});
                aiSetManagedTaskStatus(proposal, 'rejected');
                aiClearProposal();
            };
            var dismiss = document.createElement('button');
            dismiss.type = 'button';
            dismiss.textContent = 'Dismiss';
            dismiss.onclick = function() { aiSetManagedTaskStatus(proposal, 'dismissed'); aiClearProposal(); };
            actions.appendChild(refine);
            actions.appendChild(retry);
            actions.appendChild(copy);
            actions.appendChild(skip);
            actions.appendChild(dismiss);
            panel.appendChild(actions);
            requestAnimationFrame(function() { panel.focus({preventScroll: true}); });
        }

        function aiClearProposal() {
            _aiActiveProposal = null;
            _aiProposalRange = null;
            _aiAppliedProposal = null;
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

        function aiBuildMarkdownParser(PM) {
            return new PM.MarkdownParser(
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
        }

        function aiReplaceRangeWithMarkdown(applyRange, markdownText) {
            var PM = window._PM;
            var parser = aiBuildMarkdownParser(PM);
            var parsed = parser.parse(String(markdownText || ''));
            var tr;
            var newRange;
            if (parsed.childCount === 1 && parsed.firstChild && parsed.firstChild.type.name === 'paragraph') {
                tr = _pmView.state.tr.replaceWith(
                    applyRange.from,
                    applyRange.to,
                    parsed.firstChild.content
                );
                newRange = {from: applyRange.from, to: applyRange.from + parsed.firstChild.content.size};
            } else {
                var blockRange = aiTopLevelRange(applyRange);
                tr = _pmView.state.tr.replaceWith(
                    blockRange.from,
                    blockRange.to,
                    parsed.content
                );
                newRange = {from: blockRange.from, to: blockRange.from + parsed.content.size};
            }
            var safeSelectionPos = Math.max(0, Math.min(tr.doc.content.size, newRange.to));
            try {
                tr = tr.setSelection(PM.TextSelection.create(tr.doc, safeSelectionPos, safeSelectionPos));
            } catch (e) {
                tr = tr.setSelection(PM.TextSelection.near(tr.doc.resolve(safeSelectionPos), 1));
            }
            if (_aiProposalPluginKey) {
                tr = tr.setMeta(_aiProposalPluginKey, PM.DecorationSet.empty);
            }
            _pmView.dispatch(tr);
            return newRange;
        }

        function aiReplaceRangeWithSlice(applyRange, slice) {
            var PM = window._PM;
            var tr = _pmView.state.tr.replaceRange(applyRange.from, applyRange.to, slice);
            var newRange = {from: applyRange.from, to: applyRange.from + slice.size};
            var safeSelectionPos = Math.max(0, Math.min(tr.doc.content.size, newRange.to));
            try { tr = tr.setSelection(PM.TextSelection.create(tr.doc, safeSelectionPos, safeSelectionPos)); }
            catch (e) { tr = tr.setSelection(PM.TextSelection.near(tr.doc.resolve(safeSelectionPos), 1)); }
            if (_aiProposalPluginKey) tr = tr.setMeta(_aiProposalPluginKey, PM.DecorationSet.empty);
            _pmView.dispatch(tr);
            return newRange;
        }

        function aiApplyProposal(proposal, optionIndex) {
            var panel = aiPanel();
            var primary = panel.querySelector('.ai-proposal-primary');
            if (primary) primary.disabled = true;
            aiPost('/ai/proposals/' + proposal.id + '/validate', {client_id: aiClientId()}).then(function(data) {
                if (!data.ok) throw new Error(data.error || 'The proposal target is stale.');
                aiApplyValidatedProposal(proposal, optionIndex);
            }).catch(function(error) {
                aiSetProposalHighlight(null);
                aiRenderPanel(proposal, null, error.message, false);
            });
        }

        function aiApplyValidatedProposal(proposal, optionIndex) {
            if (!_pmView || !_aiProposalRange) return;
            var opt = (proposal.options || [])[optionIndex];
            if (!opt) return;
            var liveRange = aiCurrentDecoratedRange() || aiResolveRange(proposal);
            if (!liveRange || liveRange.error) {
                aiSetProposalHighlight(null);
                aiRenderPanel(proposal, null, (liveRange && liveRange.error) || 'The selected passage could not be resolved.', false);
                return;
            }
            var expected = aiNormalizedTextMap(proposal.resolved_quote || proposal.quote || '').text;
            var liveText = aiNormalizedTextMap(_pmView.state.doc.textBetween(liveRange.from, liveRange.to, '\n')).text;
            if (expected && liveText !== expected) {
                aiSetProposalHighlight(null);
                aiRenderPanel(proposal, null, 'The selected passage changed locally. Reselect it and try again.', false);
                return;
            }
            _aiProposalRange = liveRange;
            var applyRange = {from: liveRange.from, to: liveRange.to};
            var originalText = _pmView.state.doc.textBetween(applyRange.from, applyRange.to, '\n');
            var originalSlice = _pmView.state.doc.slice(applyRange.from, applyRange.to);
            var hadDirtyBeforeApply = !!_pmDirty;
            aiSetProposalHighlight(null);
            aiClearNativeSelection();
            if (!_pmEditMode && typeof toggleSceneEdit === 'function') {
                toggleSceneEdit();
            }
            var newRange = aiReplaceRangeWithMarkdown(applyRange, String(opt.text || '').trim());
            aiForceClearProposalHighlightDom();
            aiClearNativeSelection();
            setTimeout(aiClearNativeSelection, 0);
            setTimeout(aiClearNativeSelection, 80);
            setPmDirty(true);
            aiPatch('/ai/proposals/' + proposal.id, {
                client_id: aiClientId(),
                status: 'accepted',
                selected_option: optionIndex
            });
            _aiAppliedProposal = {
                proposal: proposal,
                optionIndex: optionIndex,
                originalText: originalText,
                originalSlice: originalSlice,
                originalRange: applyRange,
                newRange: newRange,
                hadDirtyBeforeApply: hadDirtyBeforeApply
            };
            if (proposal.conversation_id && (proposal.task_id || proposal.refactor_task_id)) {
                _aiPendingSavedProposals[proposal.id] = proposal;
            }
            aiSetManagedTaskStatus(proposal, 'applied', optionIndex);
            _aiProposalRange = newRange;
            aiScrollRangeIntoView(newRange);
            aiSetProposalHighlight(newRange);
            aiRenderAppliedPanel();
        }

        function aiFinishApplied(save) {
            if (!_aiAppliedProposal) return;
            var applied = _aiAppliedProposal;
            _aiAppliedProposal = null;
            _aiActiveProposal = null;
            _aiProposalRange = null;
            aiSetProposalHighlight(null);
            var panel = document.getElementById('aiProposalPanel');
            if (panel) panel.hidden = true;
            if (save && !applied.hadDirtyBeforeApply && typeof saveSceneEdit === 'function') {
                setTimeout(function() {
                    if (_pmEditMode && _pmDirty) saveSceneEdit();
                }, 0);
            }
        }

        function aiUndoApply() {
            if (!_pmView || !_aiAppliedProposal) return;
            var applied = _aiAppliedProposal;
            var revertRange = applied.newRange;
            var restoredRange = aiReplaceRangeWithSlice(revertRange, applied.originalSlice);
            aiForceClearProposalHighlightDom();
            aiClearNativeSelection();
            if (!applied.hadDirtyBeforeApply) {
                setPmDirty(false);
            }
            // Undo is purely local. Don't PATCH the server back to 'focused'
            // here — that would echo through SSE and re-trigger aiFocusProposal,
            // causing the panel to flicker. The server's 'accepted' status is
            // fine as a record of what the user did.
            _aiAppliedProposal = null;
            _aiActiveProposal = applied.proposal;
            delete _aiPendingSavedProposals[applied.proposal.id];
            aiSetManagedTaskStatus(applied.proposal, 'ready');
            _aiProposalRange = restoredRange;
            aiScrollRangeIntoView(restoredRange);
            aiSetProposalHighlight(restoredRange);
            aiRenderPanel(applied.proposal, restoredRange, null, false);
        }

        function aiMarkAppliedProposalsSaved() {
            var saved = Object.keys(_aiPendingSavedProposals).map(function(id) { return _aiPendingSavedProposals[id]; });
            if (!saved.length) return;
            _aiPendingSavedProposals = Object.create(null);
            saved.forEach(function(proposal) { aiSetManagedTaskStatus(proposal, 'saved'); });
            if (_aiAppliedProposal) aiFinishApplied(false);
        }

        function aiDiscardAppliedProposals() {
            var discarded = Object.keys(_aiPendingSavedProposals).map(function(id) { return _aiPendingSavedProposals[id]; });
            _aiPendingSavedProposals = Object.create(null);
            discarded.forEach(function(proposal) { aiSetManagedTaskStatus(proposal, 'ready'); });
            if (discarded.length) aiClearProposal();
        }

        function aiRenderAppliedPanel() {
            if (!_aiAppliedProposal || !_pmView) return;
            var applied = _aiAppliedProposal;
            var newText = '';
            try {
                newText = _pmView.state.doc.textBetween(applied.newRange.from, applied.newRange.to, '\n');
            } catch (e) {
                newText = (applied.proposal.options[applied.optionIndex] || {}).text || '';
            }
            var panel = aiPanel();
            panel.hidden = false;
            panel.innerHTML = '';

            var title = document.createElement('div');
            title.className = 'ai-proposal-title';
            title.id = 'aiProposalTitle';
            title.textContent = 'Applied to draft · Not saved';
            panel.appendChild(title);

            var lineLabel = aiLineLabel(applied.proposal, applied.newRange);
            if (lineLabel) {
                var loc = document.createElement('div');
                loc.className = 'ai-proposal-location';
                loc.textContent = lineLabel;
                panel.appendChild(loc);
            }

            var newWrap = document.createElement('div');
            newWrap.className = 'ai-proposal-section';
            var newLabel = document.createElement('div');
            newLabel.className = 'ai-proposal-label';
            newLabel.textContent = 'NEW';
            var newBox = document.createElement('div');
            newBox.className = 'ai-proposal-original';
            newBox.textContent = newText;
            newWrap.appendChild(newLabel);
            newWrap.appendChild(newBox);
            panel.appendChild(newWrap);

            var prevWrap = document.createElement('div');
            prevWrap.className = 'ai-proposal-section';
            var prevLabel = document.createElement('div');
            prevLabel.className = 'ai-proposal-label';
            prevLabel.textContent = 'PREVIOUS';
            var prevBox = document.createElement('div');
            prevBox.className = 'ai-proposal-original';
            prevBox.textContent = applied.originalText;
            prevWrap.appendChild(prevLabel);
            prevWrap.appendChild(prevBox);
            panel.appendChild(prevWrap);

            var actions = document.createElement('div');
            actions.className = 'ai-proposal-actions';
            var undo = document.createElement('button');
            undo.type = 'button';
            undo.textContent = 'Undo';
            undo.onclick = aiUndoApply;
            var save = document.createElement('button');
            save.className = 'ai-proposal-primary';
            save.type = 'button';
            save.textContent = 'Save scene';
            save.onclick = function() { if (typeof saveSceneEdit === 'function') saveSceneEdit(); };
            var done = document.createElement('button');
            done.type = 'button';
            done.textContent = 'Close';
            done.onclick = function() { aiFinishApplied(false); };
            actions.appendChild(undo);
            actions.appendChild(save);
            actions.appendChild(done);
            panel.appendChild(actions);
            requestAnimationFrame(function() { panel.focus({preventScroll: true}); });
        }

        function handleAiProposalEvent(payload) {
            if (!payload || payload.type !== 'ai:proposal') return;
            var proposal = payload.proposal || {};
            if (proposal.needs_target && !proposal.client_id && currentScenePath() !== proposal.file) return;
            if (payload.action === 'skip') {
                if (_aiActiveProposal && _aiActiveProposal.id === proposal.id) aiClearProposal();
                return;
            }
            if (proposal.status === 'skipped' || proposal.status === 'accepted') {
                // Local accept already opened the applied/undo panel for this
                // proposal; don't tear it down when our own PATCH round-trips
                // back as an SSE event.
                if (_aiAppliedProposal && _aiAppliedProposal.proposal.id === proposal.id) return;
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

        document.addEventListener('keydown', function(event) {
            if (!_aiActiveProposal || _aiAppliedProposal) return;
            var panel = document.getElementById('aiProposalPanel');
            if (!panel || panel.hidden || event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
            var options = _aiActiveProposal.options || [];
            if (event.key === 'ArrowLeft' && _aiSelectedOptionIndex > 0) {
                event.preventDefault(); _aiSelectedOptionIndex--; aiRenderPanel(_aiActiveProposal, _aiProposalRange, null, false);
            } else if (event.key === 'ArrowRight' && _aiSelectedOptionIndex < options.length - 1) {
                event.preventDefault(); _aiSelectedOptionIndex++; aiRenderPanel(_aiActiveProposal, _aiProposalRange, null, false);
            } else if ((event.key === 'a' || event.key === 'A' || (event.key === 'Enter' && (event.metaKey || event.ctrlKey))) && options.length) {
                event.preventDefault(); aiApplyProposal(_aiActiveProposal, _aiSelectedOptionIndex || 0);
            } else if (event.key === 'r' || event.key === 'R') {
                event.preventDefault(); aiPost('/ai/proposals/' + _aiActiveProposal.id + '/skip', {client_id: aiClientId()}); aiSetManagedTaskStatus(_aiActiveProposal, 'rejected'); aiClearProposal();
            } else if (event.key === 'Escape') {
                event.preventDefault(); aiSetManagedTaskStatus(_aiActiveProposal, 'dismissed'); aiClearProposal();
            }
        });
