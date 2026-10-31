        // ── Highlight suggestion card ───────────────────────────────────
        //
        // A click on a highlight mark while reading opens a small card under
        // its line: what the check found, and ways to answer it. Suggest with
        // Codex or Claude asks that agent once, outside the chat, for rewrites
        // shown in the card itself; both can be asked, at the same time, and
        // each keeps its own answers. Use puts one in the scene the way an
        // applied agent edit does (one undoable change, then saved). Discuss in
        // chat hands the passage to the agent tab with an unsent starter.
        //
        // Nothing here scrolls. The card follows its line as the reader
        // scrolls, and every focus it takes is preventScroll.
        var _hlCard = null;
        var HL_AGENTS = [{id: 'codex', label: 'Codex'}, {id: 'claude', label: 'Claude'}];
        // Which agents can run, from the same check the dock makes. Until it
        // answers, both are offered.
        var _hlAvailable = null;
        // Suggestions asked for, by scene, check, passage and agent, for as
        // long as the page is open. Clicking the mark again shows them, and a
        // request still running when the card closes carries on and lands here.
        var _hlAsked = Object.create(null);
        // Finished ones also go to sessionStorage, so a reload in the same tab
        // keeps them. Storage is a convenience: without it they last the page.
        var HL_ASKED_STORAGE_KEY = 'proseview-hl-suggestions-2';
        var HL_ASKED_KEEP = 100;
        try {
            var _hlStored = JSON.parse(sessionStorage.getItem(HL_ASKED_STORAGE_KEY) || '{}');
            Object.keys(_hlStored || {}).forEach(function(k) {
                var row = _hlStored[k];
                if (row && Array.isArray(row.options)) _hlAsked[k] = Object.assign({status: 'results'}, row);
            });
        } catch (e) {}

        function _hlSaveAsked() {
            var rows = Object.keys(_hlAsked).filter(function(k) { return _hlAsked[k].status === 'results'; })
                .sort(function(a, b) { return (_hlAsked[b].at || 0) - (_hlAsked[a].at || 0); })
                .slice(0, HL_ASKED_KEEP);
            var out = {};
            rows.forEach(function(k) {
                var a = _hlAsked[k];
                out[k] = {options: a.options, originalGlue: a.originalGlue, label: a.label, at: a.at, took: a.took,
                          model: a.model, effort: a.effort};
            });
            try { sessionStorage.setItem(HL_ASKED_STORAGE_KEY, JSON.stringify(out)); } catch (e) {}
        }

        // Suggestions put in the scene, so they can be taken back later: the
        // new text keeps a faint underline, and clicking it shows what it
        // replaced. Kept like the answers, for the page and in sessionStorage.
        var HL_APPLIED_STORAGE_KEY = 'proseview-hl-applied';
        var _hlApplied = [];
        var _hlAppliedRanges = Object.create(null);
        try {
            var _hlAppliedStored = JSON.parse(sessionStorage.getItem(HL_APPLIED_STORAGE_KEY) || '[]');
            if (Array.isArray(_hlAppliedStored)) _hlApplied = _hlAppliedStored.filter(function(r) { return r && r.id && r.text; });
        } catch (e) {}

        function _hlSaveApplied() {
            try { sessionStorage.setItem(HL_APPLIED_STORAGE_KEY, JSON.stringify(_hlApplied.slice(-50))); } catch (e) {}
        }

        function _hlForgetApplied(id) {
            _hlApplied = _hlApplied.filter(function(r) { return r.id !== id; });
            delete _hlAppliedRanges[id];
            _hlSaveApplied();
        }

        // Called while the scene's decorations are built. Text that is no
        // longer there was edited by hand, and its record goes.
        function hlAppliedDecorations(PM, path, lower, posAt, decorations) {
            var gone = [];
            _hlApplied.forEach(function(rec) {
                if (rec.path !== path) return;
                var needle = rec.text.toLowerCase();
                var at = needle ? _hlFindText(lower, needle, 0) : -1;
                if (at < 0 || at + needle.length > posAt.length) { gone.push(rec.id); return; }
                var from = posAt[at], to = posAt[at + needle.length - 1] + 1;
                _hlAppliedRanges[rec.id] = {from: from, to: to};
                decorations.push(PM.Decoration.inline(from, to, {
                    class: 'hl-applied', 'data-hl-applied': rec.id
                }));
            });
            gone.forEach(_hlForgetApplied);
        }

        function _hlAgo(at) {
            var minutes = Math.floor((Date.now() - at) / 60000);
            if (minutes < 1) return 'just now';
            if (minutes < 60) return minutes + ' min ago';
            var hours = Math.floor(minutes / 60);
            return hours === 1 ? '1 hour ago' : hours + ' hours ago';
        }

        function _hlAskKey(card, agent) {
            return card.path + '\u0000' + card.name + '\u0000' + card.text + '\u0000' + agent;
        }

        function _hlAsk(card, agent) {
            return _hlAsked[_hlAskKey(card, agent)] || null;
        }

        function _hlAgentsShown() {
            return HL_AGENTS.filter(function(a) { return !_hlAvailable || _hlAvailable[a.id] !== false; });
        }

        function _hlLoadAvailability() {
            if (_hlAvailable) return;
            _hlAvailable = {};
            fetch('/api/discuss/agents', {method: 'POST', headers: pvHeaders(), body: '{}'})
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    (data.agents || []).forEach(function(row) { _hlAvailable[row.id] = !!row.available; });
                    if (_hlCard) _renderHighlightCard();
                }).catch(function() {});
        }

        function _hlCardEl() {
            var el = document.getElementById('hlSuggestCard');
            if (el) return el;
            el = document.createElement('div');
            el.id = 'hlSuggestCard';
            el.className = 'hl-card';
            el.setAttribute('role', 'dialog');
            el.setAttribute('aria-label', 'Highlight');
            el.hidden = true;
            el.addEventListener('mousedown', function(e) { e.stopPropagation(); });
            document.body.appendChild(el);
            return el;
        }

        // The whole mark, which a second mark overlapping it splits into
        // several spans, as editor positions.
        function _hlMarkRange(key) {
            var host = document.getElementById('sceneProseHost');
            if (!host || !_pmView) return null;
            var spans = host.querySelectorAll('[data-hl-key="' + key + '"]');
            if (!spans.length) return null;
            var last = spans[spans.length - 1];
            try {
                return {from: _pmView.posAtDOM(spans[0], 0), to: _pmView.posAtDOM(last, last.childNodes.length)};
            } catch (e) { return null; }
        }

        // What Suggest rewrites. A sticky sentence is already a sentence; a
        // 6+ untagged lines mark sits on one word, but what wants a tag is its
        // whole paragraph; any other mark is a word or two, which cannot be
        // rewritten on its own, so the sentence around it is.
        var _HL_SENTENCE_END = /[.!?…]+["'”’)\]]*(?:\s+|$)/g;

        function _hlTargetRange(name, range) {
            var $from = _pmView.state.doc.resolve(range.from);
            var start = $from.start(), end = $from.end();
            if (name === 'sticky_sentences') return range;
            if (name === 'dialogue_tags' && _hlCard && /lines in a row/.test(_hlCard.note)) return {from: start, to: end};
            // One character per position, so offsets map straight back.
            var text = _pmView.state.doc.textBetween(start, end, '\n', '￼');
            var at = range.from - start, upto = range.to - start;
            var from = 0, to = text.length, m;
            _HL_SENTENCE_END.lastIndex = 0;
            while ((m = _HL_SENTENCE_END.exec(text))) {
                if (!m[0]) { _HL_SENTENCE_END.lastIndex++; continue; }
                var next = text.charAt(m.index + m[0].length);
                // '"Wait!" she said' is one sentence, as it is for the passes.
                if (next && next !== next.toUpperCase()) continue;
                var stop = m.index + m[0].replace(/\s+$/, '').length;
                if (stop <= at) from = m.index + m[0].length;
                else if (stop >= upto) { to = stop; break; }
            }
            return {from: start + from, to: start + to};
        }

        function _hlText(range) {
            return _pmView.state.doc.textBetween(range.from, range.to, '\n');
        }

        function openHighlightCard(span) {
            var key = span.getAttribute('data-hl-key') || '';
            var name = key.split(':')[0];
            var index = Number(key.split(':')[1]);
            var path = paths[curIdx];
            var hits = (((highlightsByPath[path] || {}).highlights || {})[name]) || [];
            var range = _hlMarkRange(key);
            // Dialogue is a tint, not a finding: there is nothing to suggest.
            if (!range || !PASS_LABELS[name] || name === 'dialogue') return;
            closeHighlightCard();
            _hlLoadAvailability();
            var note = String((hits[index] || {}).note || '');
            // An echo's note starts with its id; the card shows its words.
            if (name === 'echoes') note = note.split(' \u00b7 ').slice(1).join(' \u00b7 ');
            // A repeat's note is its counts; the card says them in words, with
            // the paragraph's count the mark's number leaves out.
            if (name === 'repeats') {
                var word = _hlRepeatGroup(hits[index] || {});
                var same = hits.filter(function(h) { return _hlRepeatGroup(h) === word; });
                var inPara = same.filter(function(h) { return h.paragraph_index === (hits[index] || {}).paragraph_index; }).length;
                note = (same.indexOf(hits[index]) + 1) + ' of ' + same.length + ' in this scene \u00b7 '
                    + inPara + ' in this paragraph';
            }
            _hlCard = {
                key: key, name: name, path: path, note: note,
                markRange: range, errors: {}, applied: null, tickers: [], error: ''
            };
            _hlCard.range = _hlTargetRange(name, range);
            _hlCard.text = _hlText(_hlCard.range);
            _hlCard.flagged = _hlText(range);
            _hlCard.returnFocus = document.activeElement;
            _renderHighlightCard();
            var first = _hlCardEl().querySelector('button.hl-card-primary, .hl-card-use');
            if (first) first.focus({preventScroll: true});
        }

        function _hlStopTickers(card) {
            (card.tickers || []).forEach(clearInterval);
            card.tickers = [];
        }

        function closeHighlightCard() {
            if (!_hlCard) return;
            _hlStopTickers(_hlCard);
            var back = _hlCard.returnFocus;
            _hlCard = null;
            var el = document.getElementById('hlSuggestCard');
            if (el) { el.hidden = true; el.replaceChildren(); }
            if (back && back.isConnected && typeof back.focus === 'function') back.focus({preventScroll: true});
        }

        function _hlButton(label, onClick, cls) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'hl-card-btn' + (cls ? ' ' + cls : '');
            b.textContent = label;
            b.onclick = function(e) { e.stopPropagation(); onClick(); };
            return b;
        }

        function _hlEl(tag, cls, text) {
            var el = document.createElement(tag);
            if (cls) el.className = cls;
            if (text !== undefined) el.textContent = text;
            return el;
        }

        // One agent's part of the card: its spinner while it works, then its
        // answers under a quiet line saying who and how long.
        function _hlGroup(card, agent) {
            var ask = _hlAsk(card, agent.id);
            var error = card.errors[agent.id];
            if (!ask && !error) return null;
            var group = _hlEl('div', 'hl-card-group');
            group.dataset.agent = agent.id;
            if (ask && ask.status === 'loading') {
                // A reply takes most of a minute, so the card shows the agent is
                // still at it: a spinner, and the time so far as the AI dock
                // counts it ("0:12").
                var wait = _hlEl('p', 'hl-card-wait');
                wait.setAttribute('role', 'status');
                var spinner = _hlEl('span', 'hl-card-spinner');
                spinner.setAttribute('aria-hidden', 'true');
                var clock = _hlEl('span', 'hl-card-elapsed');
                clock.setAttribute('aria-hidden', 'true');
                var tick = function() { clock.textContent = discussFormatDuration(Date.now() - ask.askedAt); };
                tick();
                card.tickers.push(setInterval(tick, 1000));
                var cancel = _hlButton('Cancel', function() { _hlCancel(agent.id); }, 'hl-card-link');
                wait.append(spinner, _hlEl('span', '', 'Asking ' + agent.label + '…'), clock, cancel);
                group.appendChild(wait);
                return group;
            }
            if (error) {
                var err = _hlEl('p', 'hl-card-error', agent.label + ': ' + error);
                err.setAttribute('role', 'alert');
                group.appendChild(err);
            }
            if (!ask || ask.status !== 'results') return group;
            var head = _hlEl('div', 'hl-card-group-head');
            var by = _hlEl('p', 'hl-card-by', 'Suggested by ' + agent.label
                + (ask.took ? ' in ' + discussFormatDuration(ask.took) : '') + ' · ' + _hlAgo(ask.at));
            if (ask.model) by.title = ask.model + (ask.effort ? ' · ' + ask.effort + ' effort' : '');
            head.appendChild(by);
            if (!card.applied) head.appendChild(_hlButton('Try again', function() { _hlSuggest(agent.id); }, 'hl-card-link hl-card-again'));
            group.appendChild(head);
            var list = _hlEl('ol', 'hl-card-options');
            ask.options.forEach(function(opt, i) {
                var on = card.applied && card.applied.agent === agent.id && card.applied.index === i;
                var li = _hlEl('li', 'hl-card-option' + (on ? ' is-applied' : ''));
                li.append(
                    _hlEl('p', 'hl-card-option-text', opt.text),
                    _hlEl('p', 'hl-card-option-why', opt.rationale
                        + (opt.glue_pct !== undefined ? ' · ' + opt.glue_pct + '% glue words' : ''))
                );
                if (!card.applied) li.appendChild(_hlButton('Use', function() { _hlUse(agent.id, i); }, 'hl-card-use'));
                list.appendChild(li);
            });
            group.appendChild(list);
            return group;
        }

        function _renderHighlightCard() {
            var card = _hlCard;
            var el = _hlCardEl();
            el.replaceChildren();
            if (!card) { el.hidden = true; return; }
            _hlStopTickers(card);
            if (card.record) { _renderAppliedCard(card, el); return; }

            var head = _hlEl('div', 'hl-card-head');
            // One row: the check, what it found, and the close button.
            var title = _hlEl('span', 'hl-card-title');
            title.appendChild(_hlEl('strong', '', PASS_LABELS[card.name] || card.name));
            if (card.note) title.appendChild(_hlEl('span', 'hl-card-note', ' · ' + card.note));
            var gear = _hlButton('⚙', function() { closeHighlightCard(); openSuggestionSettings(); }, 'hl-card-close hl-card-gear');
            gear.setAttribute('aria-label', 'Suggestion settings');
            gear.title = 'Suggestion settings';
            var close = _hlButton('×', closeHighlightCard, 'hl-card-close');
            close.setAttribute('aria-label', 'Close');
            head.append(title, gear, close);
            el.appendChild(head);

            var agents = _hlAgentsShown();
            var groups = agents.map(function(agent) { return _hlGroup(card, agent); }).filter(Boolean);
            if (!groups.length || card.error) el.appendChild(_hlEl('p', 'hl-card-why', PASS_NOTES[card.name] || ''));
            if (card.error) {
                var err = _hlEl('p', 'hl-card-error', card.error);
                err.setAttribute('role', 'alert');
                el.appendChild(err);
            }
            groups.forEach(function(g) { el.appendChild(g); });
            if (card.applied) {
                var done = _hlEl('p', 'hl-card-applied');
                done.setAttribute('role', 'status');
                done.append(card.applied.saved ? 'Applied' : 'Applied, not saved yet', ' · ');
                done.appendChild(_hlButton('Undo', _hlUndo, 'hl-card-link'));
                el.appendChild(done);
            } else {
                var actions = _hlEl('div', 'hl-card-actions');
                // An agent with nothing asked yet can still be asked.
                agents.forEach(function(agent) {
                    if (_hlAsk(card, agent.id)) return;
                    var b = _hlButton('Suggest with ' + agent.label, function() { _hlSuggest(agent.id); }, 'hl-card-primary');
                    b.dataset.agent = agent.id;
                    actions.appendChild(b);
                });
                // × closes the card, so no separate "Keep as is".
                actions.appendChild(_hlButton('Discuss in chat', _hlDiscuss));
                el.appendChild(actions);
            }
            el.hidden = false;
            positionHighlightCard();
        }

        // Under the line the mark ends on, or above the mark when there is no
        // room below. Fixed to the viewport and recomputed as the reader
        // scrolls, so the card moves with its text and never moves the text.
        function positionHighlightCard() {
            var el = document.getElementById('hlSuggestCard');
            if (!_hlCard || !el || el.hidden || !_pmView) return;
            var start, end;
            try {
                start = _pmView.coordsAtPos(_hlCard.markRange.from);
                end = _pmView.coordsAtPos(_hlCard.markRange.to, -1);
            } catch (e) { return; }
            var width = el.offsetWidth, height = el.offsetHeight;
            var left = Math.max(12, Math.min(start.left, window.innerWidth - width - 12));
            var top = end.bottom + 6;
            if (top + height > window.innerHeight - 8 && start.top - height - 6 > 8) top = start.top - height - 6;
            el.style.left = left + 'px';
            el.style.top = top + 'px';
        }

        function _hlCancel(agentId) {
            var card = _hlCard;
            if (!card) return;
            var key = _hlAskKey(card, agentId);
            var ask = _hlAsked[key];
            if (ask && ask.status === 'loading') {
                ask.controller.abort();
                if (ask.previous) _hlAsked[key] = ask.previous;
                else delete _hlAsked[key];
            }
            _renderHighlightCard();
        }

        function _hlSuggest(agentId) {
            var card = _hlCard;
            if (!card) return;
            var agent = HL_AGENTS.find(function(a) { return a.id === agentId; }) || HL_AGENTS[0];
            var key = _hlAskKey(card, agent.id);
            var hits = (((highlightsByPath[card.path] || {}).highlights || {})[card.name]) || [];
            var hit = hits[Number(card.key.split(':')[1])] || {};
            var paragraphs = (highlightsByPath[card.path] || {}).paragraphs || [];
            // "Same as chat": what the agent tab has picked, when it is this agent's.
            var chat = typeof discussModelSelection === 'function' && _discussAgent === agent.id
                ? discussModelSelection() : {model: '', effort: ''};
            var previous = _hlAsked[key] && _hlAsked[key].status === 'results' ? _hlAsked[key] : null;
            var ask = {status: 'loading', askedAt: Date.now(), label: agent.label,
                       controller: new AbortController(), previous: previous};
            _hlAsked[key] = ask;
            delete card.errors[agent.id];
            card.error = '';
            _renderHighlightCard();
            // Whichever card shows this passage now, if any, takes the answer.
            function shown() {
                return _hlCard && _hlAskKey(_hlCard, agent.id) === key ? _hlCard : null;
            }
            fetch('/api/discuss/highlight-suggest', {
                method: 'POST',
                headers: pvHeaders(),
                signal: ask.controller.signal,
                body: JSON.stringify({
                    agent: agent.id,
                    pass: card.name,
                    label: PASS_LABELS[card.name] || card.name,
                    explanation: PASS_NOTES[card.name] || '',
                    note: card.note,
                    flagged: card.flagged !== card.text ? card.flagged : '',
                    text: card.text,
                    paragraph: paragraphs[hit.paragraph_index] || card.text,
                    scene: card.path,
                    chat_model: chat.model,
                    chat_effort: chat.effort
                })
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (!data.ok) throw new Error(data.error || 'No suggestions came back.');
                ask.status = 'results';
                ask.options = data.alternatives || [];
                ask.originalGlue = data.original_glue_pct;
                ask.at = Date.now();
                ask.took = ask.at - ask.askedAt;
                ask.model = (data.used || {}).model || '';
                ask.effort = (data.used || {}).effort || '';
                ask.previous = null;
                _hlSaveAsked();
                if (shown()) _renderHighlightCard();
            }).catch(function(error) {
                if (error && error.name === 'AbortError') return;
                // A failed retry keeps the suggestions it was meant to replace.
                if (_hlAsked[key] === ask) {
                    if (ask.previous) _hlAsked[key] = ask.previous;
                    else delete _hlAsked[key];
                }
                var now = shown();
                if (!now) return;
                now.errors[agent.id] = (error && error.message) || 'No suggestions came back.';
                _renderHighlightCard();
            });
        }

        // Puts an agent's option i in place of the passage as one editor
        // change, then saves -- unless the scene already had unsaved edits,
        // which are the writer's to save.
        function _hlUse(agentId, i) {
            var card = _hlCard;
            var ask = card && _hlAsk(card, agentId);
            var opt = ask && ask.options && ask.options[i];
            if (!opt || !_pmView) return;
            if (_hlText(card.range).replace(/\s+/g, ' ').trim() !== card.text.replace(/\s+/g, ' ').trim()) {
                card.error = 'The passage changed since you asked. Close this and click the mark again.';
                _renderHighlightCard();
                return;
            }
            var wasReading = !_pmEditMode;
            if (wasReading) toggleSceneEdit();
            var hadDirty = !!_pmDirty;
            var originalSlice = _pmView.state.doc.slice(card.range.from, card.range.to);
            var newRange = aiReplaceRangeWithMarkdown(card.range, String(opt.text || '').trim());
            setPmDirty(true);
            card.applied = {agent: agentId, index: i, originalSlice: originalSlice, range: newRange,
                            text: _hlText(newRange), wasReading: wasReading, saved: false};
            card.applied.recordId = _hlRecordApplied(card, agentId, originalSlice, card.applied.text);
            card.markRange = newRange;
            _renderHighlightCard();
            _hlSave(card, hadDirty, wasReading, {check: PASS_LABELS[card.name] || card.name, agent: agentId});
            updatePMHighlightDecorations();
        }

        function _hlSave(card, hadDirty, wasReading, suggestion) {
            if (hadDirty || typeof saveSceneEdit !== 'function') return;
            _hlSaveScene(wasReading, suggestion, function() {
                if (_hlCard !== card || !card.applied) return;
                card.applied.saved = true;
                _renderHighlightCard();
            });
        }

        // Saves the scene, naming the save in History. The name rides on the
        // request saveSceneEdit builds at once, so it is cleared right after.
        function _hlSaveScene(wasReading, suggestion, onSaved) {
            window._pmNextSaveSuggestion = suggestion || null;
            try {
                saveSceneEdit(function() {
                    updatePMHighlightDecorations();
                    if (onSaved) onSaved();
                }, wasReading);
            } finally {
                window._pmNextSaveSuggestion = null;
            }
        }

        function _hlRecordApplied(card, agentId, originalSlice, text) {
            var options = [];
            HL_AGENTS.forEach(function(agent) {
                var ask = _hlAsk(card, agent.id);
                (ask && ask.status === 'results' ? ask.options : []).forEach(function(opt) {
                    options.push({agent: agent.id, agentLabel: agent.label, text: opt.text,
                                  rationale: opt.rationale, glue_pct: opt.glue_pct});
                });
            });
            var rec = {
                id: 'a' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
                path: card.path, name: card.name, label: PASS_LABELS[card.name] || card.name,
                agent: agentId, original: originalSlice.toJSON(), originalText: card.text,
                text: text, options: options, at: Date.now()
            };
            _hlApplied.push(rec);
            _hlSaveApplied();
            return rec.id;
        }

        function _hlUndo() {
            var card = _hlCard;
            var applied = card && card.applied;
            if (!applied || !_pmView) return;
            var wasReading = !_pmEditMode;
            if (wasReading) toggleSceneEdit();
            if (_hlText(applied.range) !== applied.text) {
                card.error = 'The text changed after it was applied, so it can’t be undone here. Use Undo in the editor.';
                card.applied = null;
                _renderHighlightCard();
                return;
            }
            var hadDirty = !!_pmDirty && !applied.saved;
            var restored = aiReplaceRangeWithSlice(applied.range, applied.originalSlice);
            setPmDirty(true);
            if (applied.recordId) _hlForgetApplied(applied.recordId);
            card.applied = null;
            card.range = restored;
            card.markRange = restored;
            _renderHighlightCard();
            _hlSave(card, hadDirty, wasReading, {check: PASS_LABELS[card.name] || card.name, undone: true});
            updatePMHighlightDecorations();
        }

        function _hlDiscuss() {
            var card = _hlCard;
            if (!card || typeof openDiscussForSelection !== 'function') return;
            var label = PASS_LABELS[card.name] || card.name;
            var starter = 'Prosview marked this with ' + label + (card.note ? ' (' + card.note + ')' : '') + '. ';
            var suggested = [];
            HL_AGENTS.forEach(function(agent) {
                var ask = _hlAsk(card, agent.id);
                if (!ask || ask.status !== 'results') return;
                ask.options.forEach(function(opt) {
                    suggested.push((suggested.length + 1) + '. ' + opt.text + ' (' + agent.label + ': ' + opt.rationale + ')');
                });
            });
            if (suggested.length) {
                starter += 'Suggested rewrites:\n' + suggested.join('\n')
                    + '\nWhich of these, if any, fits the scene, or what would you change?';
            } else {
                starter += 'Is it worth changing here, and how?';
            }
            var map = aiDocTextMap(_pmView.state.doc);
            var start = -1, end = -1;
            for (var i = 0; i < map.posMap.length; i++) {
                var pos = map.posMap[i];
                if (pos === null || pos < card.range.from || pos >= card.range.to) continue;
                if (start < 0) start = i;
                end = i + 1;
            }
            var revision = meta[card.path] && meta[card.path].revision;
            var flat = start >= 0 && typeof revision === 'string'
                ? {range: {start: start, end: end}, snapshot: {editor_text: map.text, source_revision: revision}}
                : null;
            var trigger = document.getElementById('sceneProseHost');
            closeHighlightCard();
            openDiscussForSelection(trigger, card.text.trim(), {
                selectionRange: flat ? flat.range : null,
                selectionSnapshot: flat ? flat.snapshot : null,
                liveDocument: typeof currentSceneLiveDocumentSnapshot === 'function' ? currentSceneLiveDocumentSnapshot() : null,
                prefill: starter
            });
        }

        // ── A suggestion already in the scene ──
        function openAppliedCard(id) {
            var rec = _hlApplied.find(function(r) { return r.id === id; });
            var range = _hlAppliedRanges[id];
            if (!rec || !range) return;
            closeHighlightCard();
            _hlCard = {record: rec, markRange: range, tickers: [], errors: {}, error: ''};
            _hlCard.returnFocus = document.activeElement;
            _renderHighlightCard();
            var first = _hlCardEl().querySelector('button.hl-card-primary');
            if (first) first.focus({preventScroll: true});
        }

        function _renderAppliedCard(card, el) {
            var rec = card.record;
            var head = _hlEl('div', 'hl-card-head');
            var title = _hlEl('span', 'hl-card-title');
            title.appendChild(_hlEl('strong', '', 'Suggestion applied'));
            title.appendChild(_hlEl('span', 'hl-card-note', ' \u00b7 ' + rec.label));
            var close = _hlButton('\u00d7', closeHighlightCard, 'hl-card-close');
            close.setAttribute('aria-label', 'Close');
            head.append(title, close);
            el.appendChild(head);
            var was = _hlEl('p', 'hl-card-was');
            was.append(_hlEl('span', 'hl-card-was-label', 'Was: '), _hlEl('span', 'hl-card-option-text', rec.originalText));
            el.appendChild(was);
            if (card.error) {
                var err = _hlEl('p', 'hl-card-error', card.error);
                err.setAttribute('role', 'alert');
                el.appendChild(err);
            }
            var others = rec.options.filter(function(opt) { return opt.text.trim() !== rec.text.trim(); });
            if (others.length) {
                el.appendChild(_hlEl('p', 'hl-card-by', 'The other suggestions'));
                var list = _hlEl('ol', 'hl-card-options');
                others.forEach(function(opt) {
                    var li = _hlEl('li', 'hl-card-option');
                    li.append(
                        _hlEl('p', 'hl-card-option-text', opt.text),
                        _hlEl('p', 'hl-card-option-why', opt.agentLabel + ': ' + opt.rationale
                            + (opt.glue_pct !== undefined ? ' \u00b7 ' + opt.glue_pct + '% glue words' : ''))
                    );
                    li.appendChild(_hlButton('Use instead', function() { _hlSwitchApplied(rec, opt); }, 'hl-card-use'));
                    list.appendChild(li);
                });
                el.appendChild(list);
            }
            var actions = _hlEl('div', 'hl-card-actions');
            actions.appendChild(_hlButton('Restore original', function() {
                if (_hlRestoreApplied(rec)) closeHighlightCard();
                else { card.error = 'The text changed, so it can\u2019t be restored here.'; _renderHighlightCard(); }
            }, 'hl-card-primary'));
            var done = _hlButton('Done', function() { _hlForgetApplied(rec.id); closeHighlightCard(); updatePMHighlightDecorations(); });
            done.title = 'Keep it, and stop marking it as a suggestion';
            actions.appendChild(done);
            el.appendChild(actions);
            el.hidden = false;
            positionHighlightCard();
        }

        // Puts back what the suggestion replaced, formatting included, and
        // saves. False when the text is no longer what was applied.
        function _hlRestoreApplied(rec) {
            var range = _hlAppliedRanges[rec.id];
            if (!range || !_pmView || _hlText(range) !== rec.text) return false;
            var wasReading = !_pmEditMode;
            if (wasReading) toggleSceneEdit();
            var hadDirty = !!_pmDirty;
            var Slice = _pmView.state.doc.slice(0, 0).constructor;
            aiReplaceRangeWithSlice(range, Slice.fromJSON(_pmView.state.schema, rec.original));
            setPmDirty(true);
            _hlForgetApplied(rec.id);
            if (!hadDirty) _hlSaveScene(wasReading, {check: rec.label, undone: true});
            updatePMHighlightDecorations();
            return true;
        }

        function _hlSwitchApplied(rec, opt) {
            var range = _hlAppliedRanges[rec.id];
            if (!range || !_pmView || _hlText(range) !== rec.text) {
                _hlCard.error = 'The text changed, so it can\u2019t be swapped here.';
                _renderHighlightCard();
                return;
            }
            var wasReading = !_pmEditMode;
            if (wasReading) toggleSceneEdit();
            var hadDirty = !!_pmDirty;
            var newRange = aiReplaceRangeWithMarkdown(range, String(opt.text || '').trim());
            setPmDirty(true);
            rec.text = _hlText(newRange);
            rec.agent = opt.agent;
            rec.at = Date.now();
            _hlSaveApplied();
            _hlAppliedRanges[rec.id] = newRange;
            _hlCard.markRange = newRange;
            _renderHighlightCard();
            if (!hadDirty) _hlSaveScene(wasReading, {check: rec.label, agent: opt.agent});
            updatePMHighlightDecorations();
        }

        // Cmd/Ctrl+Z while reading takes back the last suggestion applied in
        // this scene. While editing, it is the editor's own undo.
        document.addEventListener('keydown', function(e) {
            if (_pmEditMode || !(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey || e.key.toLowerCase() !== 'z') return;
            var target = e.target;
            if (target && (target.closest && target.closest('input, textarea, select, [contenteditable="true"]'))) return;
            var path = typeof paths !== 'undefined' ? paths[curIdx] : null;
            var mine = _hlApplied.filter(function(r) { return r.path === path; });
            if (!path || !mine.length || !_pmView) return;
            var rec = mine.reduce(function(a, b) { return b.at > a.at ? b : a; });
            e.preventDefault();
            closeHighlightCard();
            var ok = _hlRestoreApplied(rec);
            if (typeof sidebarShowToast === 'function') {
                sidebarShowToast(ok ? 'Undone: ' + rec.label + ' suggestion' : 'That text has changed, so the suggestion can\u2019t be undone.');
            }
        });

        // A plain click on a mark while reading. A drag that selects text is
        // the selection menu's, and editing keeps clicks for the caret.
        document.addEventListener('click', function(e) {
            var applied = e.target && e.target.closest && e.target.closest('#sceneProseHost [data-hl-applied]');
            if (applied && !_pmEditMode && e.button === 0 && !(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) {
                var selection = window.getSelection();
                if (!selection || selection.isCollapsed) { openAppliedCard(applied.getAttribute('data-hl-applied')); return; }
            }
            var span = e.target && e.target.closest && e.target.closest('#sceneProseHost [data-hl-key]');
            if (!span) {
                if (_hlCard && !(e.target.closest && e.target.closest('#hlSuggestCard'))) closeHighlightCard();
                return;
            }
            if (_pmEditMode || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            var sel = window.getSelection();
            if (sel && !sel.isCollapsed) return;
            openHighlightCard(span);
        });

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && _hlCard) {
                e.stopPropagation();
                closeHighlightCard();
            }
        }, true);

        window.addEventListener('scroll', function() {
            if (_hlCard) requestAnimationFrame(positionHighlightCard);
        }, true);
        window.addEventListener('resize', function() {
            if (_hlCard) requestAnimationFrame(positionHighlightCard);
        });
