        // ── /btw ephemeral side questions ───────────────────────────────
        var _btwTabsByConversation = Object.create(null);
        var _btwBufferedEvents = Object.create(null);
        var _btwSplitWasOpen = false;
        var BTW_STORAGE_PREFIX = 'proseview-btw-tabs:';
        var BTW_LAYOUT_STORAGE_KEY = 'proseview-btw-layout';
        var BTW_MAX_STORED_TABS = 20;
        var BTW_MAX_STORED_EXCHANGES = 20;
        var _btwSaveTimers = Object.create(null);
        var _btwIgnoreScrollTop = null;

        function _btwStorageKey(cid) {
            return cid ? (BTW_STORAGE_PREFIX + cid) : '';
        }

        function _normalizeBtwAgent(raw) {
            return (raw === 'claude' || raw === 'agy') ? raw : 'codex';
        }

        function _btwAgentLabel(agent) {
            return agent === 'claude' ? 'Claude' : (agent === 'agy' ? 'Agy' : 'Codex');
        }

        function _serializeBtwExchange(ex) {
            return {
                id: String(ex.id || ''),
                sideQuestionId: String(ex.sideQuestionId || ''),
                clientRequestId: String(ex.clientRequestId || ''),
                agent: _normalizeBtwAgent(ex.agent),
                question: String(ex.question || ''),
                status: String(ex.status || 'idle'),
                mode: String(ex.mode || ''),
                fallbackReason: String(ex.fallbackReason || ''),
                answerText: String(ex.answerText || ''),
                progressText: String(ex.progressText || ''),
                activities: ex.activities && typeof ex.activities === 'object' ? Object.assign({}, ex.activities) : {},
                durationMs: typeof ex.durationMs === 'number' ? ex.durationMs : null,
                error: String(ex.error || ''),
                document: ex.document && typeof ex.document === 'object'
                    ? {kind: String(ex.document.kind || ''), path: String(ex.document.path || '')}
                    : null
            };
        }

        function _restoreBtwExchange(raw) {
            if (!raw || typeof raw !== 'object') return null;
            var status = String(raw.status || 'idle');
            var error = String(raw.error || '');
            // An in-flight stream across a page reload cannot receive SSE
            // events anymore; expose Retry instead of leaving the tab wedged.
            if (status === 'running') {
                status = 'error';
                if (!error) error = 'Page reloaded before the reply arrived.';
            }
            var activities = Object.create(null);
            if (raw.activities && typeof raw.activities === 'object') {
                Object.keys(raw.activities).forEach(function(k) {
                    activities[k] = String(raw.activities[k] || '');
                });
            }
            return {
                id: String(raw.id || ''),
                sideQuestionId: String(raw.sideQuestionId || ''),
                clientRequestId: String(raw.clientRequestId || raw.id || ''),
                agent: _normalizeBtwAgent(raw.agent),
                question: String(raw.question || ''),
                status: status,
                mode: String(raw.mode || ''),
                fallbackReason: String(raw.fallbackReason || ''),
                answerText: String(raw.answerText || ''),
                progressText: String(raw.progressText || ''),
                activities: activities,
                durationMs: typeof raw.durationMs === 'number' ? raw.durationMs : null,
                error: error,
                document: raw.document && typeof raw.document === 'object'
                    ? {kind: String(raw.document.kind || ''), path: String(raw.document.path || '')}
                    : null,
                selection: '',
                liveDocument: null,
                attachments: [],
                skill: null
            };
        }

        function _loadBtwState(cid) {
            var empty = {tabs: [], activeId: ''};
            var key = _btwStorageKey(cid);
            if (!key) return empty;
            try {
                var parsed = JSON.parse(localStorage.getItem(key) || 'null');
                if (!parsed || !Array.isArray(parsed.tabs)) return empty;
                var tabs = [];
                parsed.tabs.slice(-BTW_MAX_STORED_TABS).forEach(function(rawTab) {
                    if (!rawTab || typeof rawTab !== 'object' || !rawTab.id) return;
                    var exchanges = Array.isArray(rawTab.exchanges)
                        ? rawTab.exchanges.slice(-BTW_MAX_STORED_EXCHANGES).map(_restoreBtwExchange).filter(Boolean)
                        : [];
                    var tab = {
                        id: String(rawTab.id),
                        title: String(rawTab.title || 'New question'),
                        agent: _normalizeBtwAgent(rawTab.agent),
                        status: 'idle',
                        draft: String(rawTab.draft || ''),
                        atBottom: rawTab.atBottom !== false,
                        scrollTop: Math.max(0, Number(rawTab.scrollTop) || 0),
                        exchanges: exchanges
                    };
                    tab.status = _btwTabStatus(tab);
                    tabs.push(tab);
                });
                var activeId = String(parsed.activeId || '');
                if (!tabs.some(function(t) { return t.id === activeId; })) {
                    activeId = tabs.length ? tabs[0].id : '';
                }
                return {tabs: tabs, activeId: activeId};
            } catch (e) {
                return empty;
            }
        }

        function _saveBtwState(cid) {
            if (!cid) return;
            var key = _btwStorageKey(cid);
            var st = _btwTabsByConversation[cid];
            if (!key || !st) return;
            try {
                if (!st.tabs.length) {
                    localStorage.removeItem(key);
                    return;
                }
                var payload = {
                    activeId: String(st.activeId || ''),
                    tabs: st.tabs.slice(-BTW_MAX_STORED_TABS).map(function(tab) {
                        return {
                            id: String(tab.id || ''),
                            title: String(tab.title || 'New question'),
                            agent: _normalizeBtwAgent(tab.agent),
                            status: _btwTabStatus(tab),
                            draft: String(tab.draft || ''),
                            atBottom: tab.atBottom !== false,
                            scrollTop: tab.atBottom !== false ? 0 : Math.max(0, Math.round(Number(tab.scrollTop) || 0)),
                            exchanges: (tab.exchanges || []).slice(-BTW_MAX_STORED_EXCHANGES).map(_serializeBtwExchange)
                        };
                    })
                };
                localStorage.setItem(key, JSON.stringify(payload));
            } catch (e) {}
        }

        function _scheduleBtwSave(cid) {
            if (!cid) return;
            clearTimeout(_btwSaveTimers[cid]);
            _btwSaveTimers[cid] = setTimeout(function() {
                delete _btwSaveTimers[cid];
                _saveBtwState(cid);
            }, 180);
        }

        function _flushBtwDraft() {
            var cid = _discussConversationId;
            if (!cid) return;
            clearTimeout(_btwSaveTimers[cid]);
            delete _btwSaveTimers[cid];
            var st = _btwTabsByConversation[cid];
            if (!st) return;
            var cur = st.tabs.find(function(item) { return item.id === st.activeId; });
            var btwInput = document.getElementById('btwInput');
            if (cur && btwInput && !btwInput.closest('[hidden]')) {
                cur.draft = btwInput.value;
            }
            var btwPanel = document.getElementById('btwTabPanel');
            if (cur && btwPanel && !btwPanel.closest('[hidden]')) {
                _captureBtwScroll(btwPanel, cur);
            }
            _saveBtwState(cid);
        }

        function _loadBtwLayout() {
            try {
                var parsed = JSON.parse(localStorage.getItem(BTW_LAYOUT_STORAGE_KEY) || 'null');
                if (!parsed || typeof parsed !== 'object') return null;
                var mainW = Number(parsed.mainW);
                var splitW = Number(parsed.splitW);
                if (!(mainW > 0) && !(splitW > 0)) return null;
                return {mainW: mainW > 0 ? mainW : 0, splitW: splitW > 0 ? splitW : 0};
            } catch (e) {
                return null;
            }
        }

        function _saveBtwLayout() {
            try {
                var mainW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-main-w')) || 0;
                var splitW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-split-w')) || 0;
                if (mainW > 0 && splitW > 0) {
                    localStorage.setItem(BTW_LAYOUT_STORAGE_KEY, JSON.stringify({
                        mainW: Math.round(mainW),
                        splitW: Math.round(splitW)
                    }));
                }
            } catch (e) {}
        }

        function _btwState(cid) {
            if (!cid) return null;
            if (!_btwTabsByConversation[cid]) {
                _btwTabsByConversation[cid] = _loadBtwState(cid);
            }
            return _btwTabsByConversation[cid];
        }

        function _findBtwExchange(cid, sideId, clientReqId) {
            var state = _btwState(cid);
            if (!state) return null;
            for (var i = 0; i < state.tabs.length; i++) {
                var tab = state.tabs[i];
                for (var j = 0; j < tab.exchanges.length; j++) {
                    var ex = tab.exchanges[j];
                    if (sideId && ex.sideQuestionId === sideId) return {tab: tab, exchange: ex};
                    if (clientReqId && ex.clientRequestId === clientReqId) return {tab: tab, exchange: ex};
                }
            }
            return null;
        }

        function _btwTabStatus(tab) {
            if (!tab || !tab.exchanges.length) return 'idle';
            return tab.exchanges[tab.exchanges.length - 1].status;
        }

        function _applyBtwEventToExchange(tab, ex, type, detail) {
            if (type === 'side_question.started') {
                if (detail.side_question_id) ex.sideQuestionId = detail.side_question_id;
                ex.mode = detail.mode || ex.mode;
                ex.fallbackReason = detail.fallback_reason || '';
                if (ex.mode === 'seeded') {
                    ex.answerText = '';
                    ex.progressText = '';
                }
            } else if (type === 'side_question.delta') {
                var chunk = String(detail.text || '');
                if (detail.kind === 'answer') ex.answerText += chunk;
                else if (detail.kind === 'progress' || detail.kind === 'thought') ex.progressText = (ex.progressText + chunk).slice(-800);
            } else if (type === 'side_question.activity') {
                var act = detail.activity || {};
                if (act.id) {
                    var label = act.title || act.command || act.query || [act.tool, act.path || act.pattern].filter(Boolean).join(' ');
                    if (label) ex.activities[act.id] = label;
                }
            } else if (type === 'side_question.completed') {
                ex.status = 'completed';
                ex.answerText = String(detail.text || ex.answerText || '');
                ex.mode = detail.mode || ex.mode;
                ex.fallbackReason = detail.fallback_reason || ex.fallbackReason || '';
                ex.durationMs = detail.duration_ms != null ? detail.duration_ms : null;
            } else if (type === 'side_question.failed') {
                ex.status = 'error';
                ex.error = String(detail.error || 'Side question failed.');
            } else if (type === 'side_question.cancelled') {
                ex.status = 'cancelled';
            }
            tab.status = _btwTabStatus(tab);
            tab._rev = (tab._rev || 0) + 1;
        }

        function handleBtwEvent(cid, type, detail) {
            if (!cid || !detail) return;
            var sid = String(detail.side_question_id || '');
            var reqId = String(detail.client_request_id || '');
            var hit = _findBtwExchange(cid, sid, reqId);
            if (!hit) {
                var bufKey = cid + ':' + (sid || reqId);
                if (!_btwBufferedEvents[bufKey]) _btwBufferedEvents[bufKey] = [];
                _btwBufferedEvents[bufKey].push({type: type, detail: detail});
                return;
            }
            _applyBtwEventToExchange(hit.tab, hit.exchange, type, detail);
            if (type === 'side_question.delta') _scheduleBtwSave(cid);
            else _saveBtwState(cid);
            if (cid === _discussConversationId) {
                var st = _btwState(cid);
                renderBtwSplitTabs(st);
                if (st && st.activeId === hit.tab.id) renderBtwActivePanel(hit.tab);
                syncBtwComposerState();
            }
        }

        function _createBtwExchange(questionText, turnDocument) {
            var reqId = (crypto.randomUUID ? crypto.randomUUID() : 'btw-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            return {
                id: reqId,
                sideQuestionId: '',
                clientRequestId: reqId,
                agent: _discussAgent,
                question: questionText,
                status: 'running',
                mode: '',
                fallbackReason: '',
                answerText: '',
                progressText: '',
                activities: Object.create(null),
                durationMs: null,
                error: '',
                document: turnDocument,
                selection: _discussSelection || '',
                liveDocument: _discussLiveDocument || discussLiveDocumentFor(turnDocument),
                attachments: discussMentionsIn(questionText).concat(_discussAttachments.filter(function(item) {
                    return questionText.indexOf('@' + item.path) < 0;
                })),
                skill: _discussSelectedSkill || (function() {
                    var named = discussSkillsIn(questionText)[0];
                    return named ? {name: named.name, path: named.path} : null;
                })()
            };
        }

        function sendDiscussSideQuestion(questionText, options) {
            var input = document.getElementById('discussInput');
            var cid = _discussConversationId;
            if (!cid || DISCUSS_AGENTS.indexOf(_discussAgent) < 0) return;
            var cleaned = String(questionText || '').replace(/^\s*\/btw(?:\s+|$)/i, '').trim();
            if (!cleaned) return;
            var turnDocument = discussTurnDocument();
            if (!turnDocument) return;

            var st = _btwState(cid);
            var targetTab = options && options.targetTab ? options.targetTab : null;
            var reuseExchange = options && options.reuseExchange ? options.reuseExchange : null;
            var priorTurns = [];
            var ex;
            var tab;
            if (reuseExchange && targetTab) {
                tab = targetTab;
                var idx = tab.exchanges.indexOf(reuseExchange);
                priorTurns = tab.exchanges.slice(0, Math.max(0, idx)).filter(function(item) {
                    return item.status === 'completed' && item.answerText;
                }).map(function(item) { return {question: item.question, answer: item.answerText}; });
                ex = _createBtwExchange(cleaned, turnDocument);
                tab.exchanges.splice(idx, 1, ex);
            } else if (targetTab) {
                tab = targetTab;
                if (_btwTabStatus(tab) === 'running') return;
                priorTurns = tab.exchanges.filter(function(item) {
                    return item.status === 'completed' && item.answerText;
                }).map(function(item) { return {question: item.question, answer: item.answerText}; });
                ex = _createBtwExchange(cleaned, turnDocument);
                tab.exchanges.push(ex);
                if (!tab.title || tab.title === 'New question') tab.title = cleaned;
            } else {
                ex = _createBtwExchange(cleaned, turnDocument);
                tab = {
                    id: ex.id,
                    title: cleaned,
                    agent: _discussAgent,
                    status: 'running',
                    draft: '',
                    atBottom: true,
                    scrollTop: 0,
                    exchanges: [ex]
                };
                st.tabs.push(tab);
            }
            tab.status = _btwTabStatus(tab);
            tab._rev = (tab._rev || 0) + 1;
            tab.atBottom = true;
            tab.scrollTop = 0;
            st.activeId = tab.id;
            if (!(options && options.fromBtwInput) && !reuseExchange && input) {
                // Deliberately skip recordChatMessageHistory and rememberDiscussInstruction:
                // /btw side questions stay out of Up/Down history and main draft memory.
                if (_discussSelection && typeof clearDiscussSelection === 'function') {
                    clearDiscussSelection();
                    _discussIncludeCurrentDocument = false;
                    if (!_discussPendingAction && !_discussRepositoryAction) _discussDraftDocument = null;
                }
                input.value = '';
                saveDiscussDraft();
                closeDiscussContextPicker();
                renderDiscussContext();
                renderDiscussTaskMode();
            }
            renderBtwSplit();
            _saveBtwState(cid);
            document.getElementById('discussAnnouncement').textContent = 'Running side question in split pane.';

            discussApi('/api/discuss/conversations/' + encodeURIComponent(cid) + '/side-questions', {
                client_request_id: ex.clientRequestId,
                question: cleaned,
                prior_turns: priorTurns,
                document: ex.document,
                selection: ex.selection,
                live_document: ex.liveDocument,
                attachments: ex.attachments,
                skill: ex.skill
            }).then(function(data) {
                if (data && data.side_question_id) {
                    ex.sideQuestionId = data.side_question_id;
                    [cid + ':' + ex.sideQuestionId, cid + ':' + ex.clientRequestId].forEach(function(bufKey) {
                        var queued = _btwBufferedEvents[bufKey];
                        if (queued && queued.length) {
                            delete _btwBufferedEvents[bufKey];
                            queued.forEach(function(item) { _applyBtwEventToExchange(tab, ex, item.type, item.detail); });
                        }
                    });
                    _saveBtwState(cid);
                    if (cid === _discussConversationId) renderBtwSplit();
                }
            }).catch(function(error) {
                ex.status = 'error';
                ex.error = error.message || 'Side question failed.';
                tab.status = _btwTabStatus(tab);
                tab._rev = (tab._rev || 0) + 1;
                _saveBtwState(cid);
                if (cid === _discussConversationId) renderBtwSplit();
            });
        }

        function newBtwTab() {
            var cid = _discussConversationId;
            if (!cid || DISCUSS_AGENTS.indexOf(_discussAgent) < 0) return;
            var st = _btwState(cid);
            var cur = st.tabs.find(function(item) { return item.id === st.activeId; });
            var btwInput = document.getElementById('btwInput');
            if (cur && btwInput) cur.draft = btwInput.value;
            var btwPanel = document.getElementById('btwTabPanel');
            if (cur && btwPanel) _captureBtwScroll(btwPanel, cur);
            var blank = {
                id: (crypto.randomUUID ? crypto.randomUUID() : 'btw-tab-' + Date.now() + '-' + Math.random().toString(36).slice(2)),
                title: 'New question',
                agent: _discussAgent,
                status: 'idle',
                draft: '',
                atBottom: true,
                scrollTop: 0,
                exchanges: []
            };
            st.tabs.push(blank);
            st.activeId = blank.id;
            renderBtwSplit();
            _saveBtwState(cid);
            if (btwInput) { btwInput.value = ''; btwInput.focus(); syncBtwComposerState(); }
        }

        function openBtwPane() {
            var cid = _discussConversationId;
            if (!cid || DISCUSS_AGENTS.indexOf(_discussAgent) < 0) return;
            var st = _btwState(cid);
            var activeTab = st.tabs.find(function(item) { return item.id === st.activeId; });
            if (activeTab && !activeTab.exchanges.length && !activeTab.draft) {
                renderBtwSplit();
                var btwInput = document.getElementById('btwInput');
                if (btwInput) { btwInput.focus(); syncBtwComposerState(); }
                return;
            }
            newBtwTab();
        }

        function sendBtwInput() {
            var btwInput = document.getElementById('btwInput');
            var cid = _discussConversationId;
            if (!btwInput || !cid) return;
            var text = btwInput.value.trim();
            if (!text) return;
            var st = _btwState(cid);
            var activeTab = st.tabs.find(function(item) { return item.id === st.activeId; }) || null;
            if (activeTab && _btwTabStatus(activeTab) === 'running') return;
            if (activeTab) activeTab.draft = '';
            btwInput.value = '';
            sendDiscussSideQuestion(text, {targetTab: activeTab, fromBtwInput: true});
            btwInput.focus();
            syncBtwComposerState();
        }

        function syncBtwComposerState() {
            var btwInput = document.getElementById('btwInput');
            var sendBtn = document.getElementById('btwSendBtn');
            var hintEl = document.getElementById('btwComposerHint');
            if (!btwInput || !sendBtn) return;
            var st = _btwState(_discussConversationId);
            var activeTab = st ? st.tabs.find(function(item) { return item.id === st.activeId; }) : null;
            var busy = !!(activeTab && _btwTabStatus(activeTab) === 'running');
            var hasExchanges = !!(activeTab && activeTab.exchanges.length);
            btwInput.placeholder = hasExchanges
                ? 'Follow up in this tab… (Enter to ask · + New for separate tab)'
                : 'Ask an off-the-record side question… (Enter to ask)';
            if (hintEl) hintEl.textContent = busy ? 'Waiting for reply…' : 'Off the record · Can edit files';
            sendBtn.disabled = busy || !btwInput.value.trim();
            sendBtn.textContent = busy ? 'Asking…' : 'Ask';
        }

        function selectBtwTab(tabId) {
            var st = _btwState(_discussConversationId);
            if (!st) return;
            var prev = st.tabs.find(function(item) { return item.id === st.activeId; });
            var btwInput = document.getElementById('btwInput');
            if (prev && btwInput) prev.draft = btwInput.value;
            var btwPanel = document.getElementById('btwTabPanel');
            if (prev && btwPanel) _captureBtwScroll(btwPanel, prev);
            st.activeId = tabId;
            renderBtwSplit();
            _saveBtwState(_discussConversationId);
        }

        function _cancelBtwTabBackend(cid, tab) {
            if (!cid || !tab) return;
            (tab.exchanges || []).forEach(function(ex) {
                if (ex.status !== 'running' || !ex.sideQuestionId) return;
                fetch('/api/discuss/conversations/' + encodeURIComponent(cid) + '/side-questions/' + encodeURIComponent(ex.sideQuestionId) + '/stop', {
                    method: 'POST',
                    headers: pvHeaders(),
                    body: '{}'
                }).catch(function() {});
            });
        }

        function closeBtwTab(tabId) {
            var cid = _discussConversationId;
            var st = _btwState(cid);
            if (!st) return;
            var idx = -1;
            for (var i = 0; i < st.tabs.length; i++) {
                if (st.tabs[i].id === tabId) { idx = i; break; }
            }
            if (idx < 0) return;
            var removed = st.tabs.splice(idx, 1)[0];
            _cancelBtwTabBackend(cid, removed);
            if (st.activeId === tabId) {
                var fallback = st.tabs[Math.min(idx, st.tabs.length - 1)];
                st.activeId = fallback ? fallback.id : '';
            }
            renderBtwSplit();
            _saveBtwState(cid);
            var input = document.getElementById('discussInput');
            if (input) input.focus();
        }

        function closeActiveBtwTab() {
            var st = _btwState(_discussConversationId);
            if (!st || !st.activeId) return false;
            closeBtwTab(st.activeId);
            return true;
        }

        function _clearBtwTabs(cid) {
            var st = _btwState(cid);
            if (!st) return;
            st.tabs.forEach(function(tab) { _cancelBtwTabBackend(cid, tab); });
            st.tabs = [];
            st.activeId = '';
            _saveBtwState(cid);
            if (cid === _discussConversationId) renderBtwSplit();
        }

        function closeAllBtwTabs() {
            _clearBtwTabs(_discussConversationId);
            var input = document.getElementById('discussInput');
            if (input) input.focus();
        }

        function retryBtwExchange(tabId, exId) {
            var st = _btwState(_discussConversationId);
            if (!st) return;
            var tab = st.tabs.find(function(item) { return item.id === tabId; });
            if (!tab) return;
            var ex = tab.exchanges.find(function(item) { return item.id === exId; });
            if (ex) sendDiscussSideQuestion(ex.question, {targetTab: tab, reuseExchange: ex});
        }

        function renderBtwSplitTabs(st) {
            var bar = document.getElementById('btwTabsBar');
            if (!bar || !st) return;
            bar.replaceChildren();
            st.tabs.forEach(function(tab, index) {
                var active = tab.id === st.activeId;
                var wrap = document.createElement('div');
                wrap.className = 'btw-tab' + (active ? ' active' : '');
                wrap.dataset.btwTabId = tab.id;
                wrap.dataset.status = _btwTabStatus(tab);
                var select = document.createElement('button');
                select.type = 'button';
                select.className = 'btw-tab-select';
                select.setAttribute('role', 'tab');
                select.setAttribute('aria-selected', active ? 'true' : 'false');
                select.title = tab.title || 'New question';
                select.onclick = function() { selectBtwTab(tab.id); };
                var dot = elementWith('btw-tab-dot');
                var rawTitle = tab.title || ('Question ' + (index + 1));
                var shortLabel = rawTitle.length > 24 ? rawTitle.slice(0, 23) + '…' : rawTitle;
                var label = elementWith('btw-tab-label', shortLabel);
                select.append(dot, label);
                var close = document.createElement('button');
                close.type = 'button';
                close.className = 'btw-tab-close';
                close.innerHTML = '&times;';
                close.setAttribute('aria-label', 'Close side question ' + (rawTitle || ''));
                close.title = 'Close (Esc)';
                close.onclick = function() { closeBtwTab(tab.id); };
                wrap.append(select, close);
                bar.appendChild(wrap);
            });
        }

        function _btwPanelAtBottom(body) {
            return body.scrollHeight - body.scrollTop - body.clientHeight <= 24;
        }

        function _captureBtwScroll(body, tab) {
            if (!body || !tab || body.dataset.renderedTabId !== tab.id || !body.clientHeight) return;
            tab.atBottom = _btwPanelAtBottom(body);
            tab.scrollTop = tab.atBottom ? 0 : Math.max(0, Math.round(body.scrollTop));
        }

        function _restoreBtwScroll(body, tab) {
            if (!body || !tab) return;
            var apply = function() {
                if (body.dataset.renderedTabId !== tab.id) return;
                var targetTop = tab.atBottom !== false ? body.scrollHeight : Math.max(0, Number(tab.scrollTop) || 0);
                var previousBehavior = body.style.scrollBehavior;
                body.style.scrollBehavior = 'auto';
                _btwIgnoreScrollTop = targetTop;
                body.scrollTop = targetTop;
                if (Math.abs(body.scrollTop - targetTop) > 1) _btwIgnoreScrollTop = body.scrollTop;
                body.style.scrollBehavior = previousBehavior;
            };
            apply();
            requestAnimationFrame(apply);
        }

        function renderBtwActivePanel(tab) {
            var body = document.getElementById('btwTabPanel');
            if (!body || !tab) return;
            var rev = String(tab._rev || 0);
            if (body.dataset.renderedTabId === tab.id && body.dataset.renderedRev === rev) {
                return;
            }
            _captureBtwScroll(body, tab);
            body.replaceChildren();
            body.dataset.renderedTabId = tab.id;
            body.dataset.renderedRev = rev;
            if (!tab.exchanges.length) {
                body.appendChild(elementWith('btw-empty-hint', 'Ask a side question or request edits below without crowding your main chat.'));
                _restoreBtwScroll(body, tab);
                return;
            }
            tab.exchanges.forEach(function(ex) {
                var block = elementWith('btw-exchange');
                var qBox = elementWith('btw-question-box');
                var kicker = elementWith('btw-question-kicker');
                var agentName = _btwAgentLabel(ex.agent);
                kicker.appendChild(elementWith('', agentName + ' · Off the record'));
                qBox.append(kicker, elementWith('btw-question-text', ex.question));
                block.appendChild(qBox);

                var card = elementWith('btw-answer-card' + (ex.status === 'error' ? ' is-error' : ''));
                if (ex.status === 'running') {
                    var statusLine = elementWith('btw-status-line');
                    statusLine.appendChild(elementWith('btw-tab-dot'));
                    var actKeys = Object.keys(ex.activities || {});
                    var latestAct = actKeys.length ? ex.activities[actKeys[actKeys.length - 1]] : '';
                    statusLine.appendChild(elementWith('', latestAct || (ex.mode === 'seeded' ? 'Thinking from seeded chat context…' : 'Thinking on forked branch…')));
                    card.appendChild(statusLine);
                    if (ex.answerText) {
                        var streamWrap = elementWith('discuss-message assistant');
                        renderDiscussMarkdown(streamWrap, ex.answerText);
                        card.appendChild(streamWrap);
                    } else if (ex.progressText) {
                        card.appendChild(elementWith('', ex.progressText));
                    }
                } else if (ex.status === 'error') {
                    card.appendChild(elementWith('', ex.error || 'Side question failed.'));
                    var errActions = elementWith('btw-error-actions');
                    var retryBtn = document.createElement('button');
                    retryBtn.type = 'button'; retryBtn.className = 'btw-split-close-all'; retryBtn.textContent = 'Retry';
                    retryBtn.onclick = function() { retryBtwExchange(tab.id, ex.id); };
                    var dismissBtn = document.createElement('button');
                    dismissBtn.type = 'button'; dismissBtn.className = 'btw-split-close-all'; dismissBtn.textContent = 'Dismiss';
                    dismissBtn.onclick = function() { closeBtwTab(tab.id); };
                    errActions.append(retryBtn, dismissBtn);
                    card.appendChild(errActions);
                } else {
                    var answerWrap = elementWith('discuss-message assistant');
                    renderDiscussMarkdown(answerWrap, ex.answerText || 'No response returned.');
                    card.appendChild(answerWrap);
                    addCopyButton(card, function() { return ex.answerText || ''; }, 'Copy side answer');
                }
                block.appendChild(card);

                var foot = elementWith('btw-meta-foot');
                var provText = ex.mode === 'seeded'
                    ? 'Seeded side session (last messages)'
                    : (ex.mode === 'fork' ? 'Forked side branch · Off main chat' : 'Side branch · Off main chat');
                if (ex.fallbackReason && ex.mode === 'seeded') {
                    foot.title = ex.fallbackReason;
                }
                foot.appendChild(elementWith('', provText));
                if (ex.durationMs != null) {
                    foot.appendChild(elementWith('', (ex.durationMs / 1000).toFixed(1) + 's'));
                } else if (ex.status === 'running') {
                    foot.appendChild(elementWith('', 'Parallel'));
                }
                block.appendChild(foot);
                body.appendChild(block);
            });
            _restoreBtwScroll(body, tab);
        }

        function _btwTotalBudget() {
            var vw = workspaceLogicalViewportWidth();
            var zoomed = document.documentElement.dataset.cssZoom === 'true';
            var overlay = document.documentElement.dataset.utilityOverlay === 'true';
            if (zoomed || overlay || vw <= 780) return {stacked: true, maxCombined: vw};
            var sidebar = document.getElementById('repoSidebar');
            var sidebarReserved = (vw > 1120 && document.documentElement.dataset.sidebar !== 'closed' && sidebar)
                ? (sidebar.getBoundingClientRect().width / workspaceZoomFactor() + 10)
                : 0;
            // Always reserve comfortable manuscript reading width (~32% / up to 440px).
            var minProse = Math.min(440, Math.max(320, Math.floor(vw * 0.32)));
            var available = Math.floor(vw - sidebarReserved - minProse);
            return {stacked: available < 468, maxCombined: Math.max(468, available)};
        }

        function _applyBtwSplitDimensions(mainW, splitW) {
            var budget = _btwTotalBudget();
            var panel = document.getElementById('discussPanel');
            document.body.classList.toggle('btw-split-stacked', budget.stacked);
            if (panel) panel.classList.toggle('is-stacked', budget.stacked);
            if (budget.stacked) return;
            var root = document.documentElement.style;
            var usable = Math.max(460, budget.maxCombined - 8);
            var clampedSplit = Math.max(220, Math.min(Math.min(420, usable - 240), Math.round(splitW)));
            var clampedMain = Math.max(240, Math.min(usable - clampedSplit, Math.round(mainW)));
            root.setProperty('--btw-main-w', clampedMain + 'px');
            root.setProperty('--btw-split-w', clampedSplit + 'px');
            var handle = document.getElementById('btwResizeHandle');
            var zoom = workspaceZoomFactor();
            updateSeparatorValue(handle, clampedSplit * zoom, 220 * zoom, Math.max(220, usable - 240) * zoom);
        }

        function _syncBtwSplitOnOpen() {
            var budget = _btwTotalBudget();
            var panel = document.getElementById('discussPanel');
            document.body.classList.toggle('btw-split-stacked', budget.stacked);
            if (panel) panel.classList.toggle('is-stacked', budget.stacked);
            if (budget.stacked) return;
            var vw = workspaceLogicalViewportWidth();
            var usable = Math.max(460, budget.maxCombined - 8);
            var idleMain = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--utility-dock-w')) || 420;
            var defaultBtw = Math.min(300, Math.max(230, Math.round(vw * 0.21)));
            // Keep main chat comfortable (~56% of split budget max) so opening /btw
            // never crushes the manuscript editor even if idle chat was wide.
            var defaultMain = Math.min(idleMain, Math.max(280, Math.floor(usable * 0.56)));
            if (defaultMain + defaultBtw > usable) {
                defaultBtw = Math.max(220, Math.min(defaultBtw, usable - 260));
                defaultMain = Math.max(240, usable - defaultBtw);
            }
            var savedLayout = _loadBtwLayout();
            if (savedLayout) {
                if (savedLayout.splitW > 0) defaultBtw = savedLayout.splitW;
                if (savedLayout.mainW > 0) defaultMain = savedLayout.mainW;
            }
            _applyBtwSplitDimensions(defaultMain, defaultBtw);
        }

        function renderBtwSplit() {
            var panel = document.getElementById('discussPanel');
            var handle = document.getElementById('btwResizeHandle');
            var split = document.getElementById('btwSplitPane');
            if (!panel || !handle || !split) return;
            var isSingleAgent = DISCUSS_AGENTS.indexOf(_discussAgent) >= 0;
            var inSceneTab = !!panel.dataset.sceneTab;
            var st = (_discussConversationId && isSingleAgent) ? _btwState(_discussConversationId) : null;
            var visible = !!(panel && !panel.hidden && !inSceneTab && isSingleAgent && st && st.tabs.length);
            document.body.classList.toggle('btw-split-open', visible);
            panel.classList.toggle('has-btw-split', visible);
            handle.hidden = !visible;
            split.hidden = !visible;
            if (!visible) {
                _btwSplitWasOpen = false;
                var hiddenPanel = document.getElementById('btwTabPanel');
                if (hiddenPanel) {
                    delete hiddenPanel.dataset.renderedTabId;
                    delete hiddenPanel.dataset.renderedRev;
                }
                document.body.classList.remove('btw-split-stacked');
                panel.classList.remove('is-stacked');
                document.documentElement.style.removeProperty('--btw-main-w');
                return;
            }
            if (!_btwSplitWasOpen) {
                _btwSplitWasOpen = true;
                _syncBtwSplitOnOpen();
            } else {
                var curMain = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-main-w'))
                    || parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--utility-dock-w')) || 360;
                var curSplit = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-split-w')) || 280;
                _applyBtwSplitDimensions(curMain, curSplit);
            }
            if (!st.activeId || !st.tabs.some(function(t) { return t.id === st.activeId; })) {
                st.activeId = st.tabs[0].id;
            }
            renderBtwSplitTabs(st);
            var activeTab = st.tabs.find(function(t) { return t.id === st.activeId; }) || st.tabs[0];
            if (activeTab) {
                renderBtwActivePanel(activeTab);
                var btwInput = document.getElementById('btwInput');
                if (btwInput && document.activeElement !== btwInput) btwInput.value = activeTab.draft || '';
            }
            syncBtwComposerState();
        }

        (function initBtwSplitBehavior() {
            var panel = document.getElementById('discussPanel');
            if (panel) {
                panel.addEventListener('keydown', function(event) {
                    if (event.key !== 'Escape') return;
                    var split = document.getElementById('btwSplitPane');
                    if (!split || split.hidden) return;
                    if (!document.getElementById('discussContextPicker').hidden) return;
                    if (!document.getElementById('discussModelPicker').hidden) return;
                    if (!document.getElementById('discussSkillsPicker').hidden) return;
                    if (document.querySelector('dialog[open]')) return;
                    event.preventDefault();
                    event.stopPropagation();
                    closeActiveBtwTab();
                });
            }
            var btwPanel = document.getElementById('btwTabPanel');
            if (btwPanel) {
                btwPanel.addEventListener('scroll', function() {
                    if (_btwIgnoreScrollTop !== null && Math.abs(btwPanel.scrollTop - _btwIgnoreScrollTop) <= 1) {
                        _btwIgnoreScrollTop = null;
                        return;
                    }
                    _btwIgnoreScrollTop = null;
                    var st = _btwTabsByConversation[_discussConversationId];
                    var activeTab = st ? st.tabs.find(function(item) { return item.id === st.activeId; }) : null;
                    if (!activeTab || btwPanel.dataset.renderedTabId !== activeTab.id || !btwPanel.clientHeight) return;
                    activeTab.atBottom = _btwPanelAtBottom(btwPanel);
                    activeTab.scrollTop = activeTab.atBottom ? 0 : Math.max(0, Math.round(btwPanel.scrollTop));
                    _scheduleBtwSave(_discussConversationId);
                });
            }
            var btwInput = document.getElementById('btwInput');
            if (btwInput) {
                btwInput.addEventListener('input', function() {
                    var st = _btwState(_discussConversationId);
                    var activeTab = st ? st.tabs.find(function(item) { return item.id === st.activeId; }) : null;
                    if (activeTab) {
                        activeTab.draft = btwInput.value;
                        _scheduleBtwSave(_discussConversationId);
                    }
                    syncBtwComposerState();
                });
                btwInput.addEventListener('keydown', function(event) {
                    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                        event.preventDefault();
                        sendBtwInput();
                    }
                });
            }
            function flushAllBtwState() {
                Object.keys(_btwSaveTimers).forEach(function(key) {
                    clearTimeout(_btwSaveTimers[key]);
                    delete _btwSaveTimers[key];
                });
                _flushBtwDraft();
                Object.keys(_btwTabsByConversation).forEach(function(cid) {
                    _saveBtwState(cid);
                });
            }
            window.addEventListener('pagehide', flushAllBtwState);
            window.addEventListener('beforeunload', flushAllBtwState);

            var handle = document.getElementById('btwResizeHandle');
            var split = document.getElementById('btwSplitPane');
            if (!handle || !split) return;
            var dragging = false;
            var startX = 0;
            var startSplit = 290;
            var startMain = 380;
            function currentMainWidth() {
                var shell = document.querySelector('#discussPanel .discuss-shell');
                var rendered = shell ? shell.getBoundingClientRect().width : 0;
                if (rendered > 0) return rendered / workspaceZoomFactor();
                return parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-main-w')) || 380;
            }
            function currentBtwWidth() {
                var rendered = split.getBoundingClientRect().width;
                if (rendered > 0) return rendered / workspaceZoomFactor();
                return parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-split-w')) || 290;
            }
            function dragMiddleTo(nextSplit) {
                var budget = _btwTotalBudget();
                if (budget.stacked) return;
                var usable = Math.max(460, budget.maxCombined - 8);
                var maxSplit = Math.max(220, Math.min(520, usable - 240));
                var clampedSplit = Math.max(220, Math.min(maxSplit, Math.round(nextSplit)));
                // Grow/shrink /btw pane against spare room first, or borrow cleanly
                // from main chat when at the combined manuscript-protection cap.
                var nextMain = Math.min(startMain, usable - clampedSplit);
                nextMain = Math.max(240, nextMain);
                _applyBtwSplitDimensions(nextMain, clampedSplit);
            }
            handle.addEventListener('mousedown', function(event) {
                dragging = true;
                startX = event.clientX;
                startSplit = currentBtwWidth();
                startMain = currentMainWidth();
                handle.classList.add('is-dragging');
                document.body.style.userSelect = 'none';
                event.preventDefault();
            });
            document.addEventListener('mousemove', function(event) {
                if (!dragging) return;
                dragMiddleTo(startSplit + (startX - event.clientX) / workspaceZoomFactor());
            });
            document.addEventListener('mouseup', function() {
                if (!dragging) return;
                dragging = false;
                handle.classList.remove('is-dragging');
                document.body.style.userSelect = '';
                _saveBtwLayout();
            });
            handle.addEventListener('keydown', function(event) {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                startSplit = currentBtwWidth();
                startMain = currentMainWidth();
                var budget = _btwTotalBudget();
                var maxSplit = Math.max(220, Math.min(520, budget.maxCombined - 248));
                var next = startSplit;
                if (event.key === 'Home') next = 220;
                else if (event.key === 'End') next = maxSplit;
                else next += (event.key === 'ArrowLeft' ? 1 : -1) * (event.shiftKey ? 40 : 16);
                dragMiddleTo(next);
                _saveBtwLayout();
                event.preventDefault();
            });
        })();
