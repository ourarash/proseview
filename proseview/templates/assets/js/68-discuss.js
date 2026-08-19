        // ── Document-aware Discuss with Codex ─────────────────────────────
        var _discussConversationId = null;
        var _discussSnapshot = null;
        var _discussDocumentKey = '';
        var _discussEventSource = null;
        var _discussAttachments = [];
        var _discussSelection = '';
        var _discussSelectionRange = null;
        var _discussLiveDocument = null;
        var _discussIncludeCurrentDocument = true;
        var _discussContextChoices = [];
        var _discussContextActiveIndex = 0;
        var _discussMentionRange = null;
        var _discussContextCandidateCache = null;
        var _discussReturnFocus = null;
        var _discussRefreshTimer = null;
        var _discussLastApproval = '';
        var _discussPendingAction = null;
        var _discussRepositoryAction = null;
        var _discussRetryOfTaskId = null;
        var _discussSelectedSkill = null;
        var _discussSkills = [];
        var _discussAutoRun = false;
        var _discussPreservedDraft = '';
        var _discussAutoReviewedTasks = Object.create(null);
        var _discussAutoReviewRequests = Object.create(null);
        var _prosviewRepositoryRootCache = null;
        var _discussRequestTimeoutMs = 15000;
        var _discussOpenFailed = false;
        var _discussLocalError = '';
        var _discussLocalErrorKind = '';
        // ── Agents ──────────────────────────────────────────────────────────
        // Codex and Claude are separate conversations that run at the same
        // time on the server. They are tabs, so only one is on screen; the
        // other keeps working and its state is restored from its snapshot when
        // you come back. Only the things a snapshot cannot carry -- the draft
        // you were typing, what you had attached -- are held here per agent.
        const DISCUSS_AGENTS = ['codex', 'claude'];
        const DISCUSS_AGENT_KEY = 'proseview-discuss-agent';
        var _discussAgent = _readDiscussAgent();
        var _discussAgentAvailability = {};
        var _discussAgentLocal = {codex: null, claude: null};
        var _discussAgentPollTimer = null;

        function _readDiscussAgent() {
            var saved = null;
            try { saved = localStorage.getItem(DISCUSS_AGENT_KEY); } catch (e) {}
            if (DISCUSS_AGENTS.indexOf(saved) >= 0) return saved;
            var fallback = (typeof discussDefaultAgent !== 'undefined') ? discussDefaultAgent : 'codex';
            return DISCUSS_AGENTS.indexOf(fallback) >= 0 ? fallback : 'codex';
        }

        function discussAgentLabel(agent) {
            return (agent || _discussAgent) === 'claude' ? 'Claude' : 'Codex';
        }

        function _saveDiscussAgentLocal() {
            var input = document.getElementById('discussInput');
            var previous = _discussAgentLocal[_discussAgent] || {};
            _discussAgentLocal[_discussAgent] = {
                draft: input ? input.value : '',
                attachments: _discussAttachments.slice(),
                includeCurrentDocument: _discussIncludeCurrentDocument,
                selectedSkill: _discussSelectedSkill,
                conversationId: _discussConversationId || previous.conversationId || null
            };
        }

        function _restoreDiscussAgentLocal() {
            var bag = _discussAgentLocal[_discussAgent] || {};
            _discussAttachments = (bag.attachments || []).slice();
            _discussIncludeCurrentDocument = bag.includeCurrentDocument !== false;
            _discussSelectedSkill = bag.selectedSkill || null;
            return bag.draft || '';
        }

        // Rename every piece of chrome that used to say "Codex" unconditionally.
        function _applyDiscussAgentLabels() {
            var label = discussAgentLabel();
            var title = document.getElementById('discussTitle');
            if (title) title.textContent = label;
            var close = document.getElementById('discussClose');
            if (close) close.setAttribute('aria-label', 'Close the ' + label + ' panel');
            var stop = document.getElementById('discussStop');
            if (stop) stop.textContent = 'Stop ' + label;
            var inputLabel = document.getElementById('discussInputLabel');
            if (inputLabel) inputLabel.textContent = 'Ask ' + label + ' about this document';
        }

        function showDiscussAgentTab(agent, trigger) {
            agent = DISCUSS_AGENTS.indexOf(agent) >= 0 ? agent : 'codex';
            var panel = document.getElementById('discussPanel');
            var log = document.getElementById('discussLog');
            // Only skip reopening when this agent's conversation is already the
            // thing on screen. The dock being open on Scene or Analysis is not
            // the same as Codex being live in it, and treating it as such left
            // the tab showing an empty log that never connected.
            var live = panel && !panel.hidden && log && !log.hidden && _discussConversationId;
            if (live && agent === _discussAgent) { _showDiscussBody(); return; }
            if (panel && !panel.hidden) _saveDiscussAgentLocal();
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            _discussAgent = agent;
            try { localStorage.setItem(DISCUSS_AGENT_KEY, agent); } catch (e) {}
            _applyDiscussAgentLabels();
            openDiscuss(trigger || _discussReturnFocus);
        }

        // The other agent may finish while you are reading this one. A dot on
        // its tab is the only way to know without switching.
        function _pollInactiveDiscussAgent() {
            clearTimeout(_discussAgentPollTimer);
            _discussAgentPollTimer = setTimeout(function() {
                var panel = document.getElementById('discussPanel');
                if (!panel || panel.hidden) return;
                var other = _discussAgent === 'codex' ? 'claude' : 'codex';
                // Only look at an agent the writer has actually opened. Opening
                // a conversation to poll it would start that agent -- visiting
                // the Codex tab would boot Claude, and every four seconds keep
                // it alive, for someone who never asked for it.
                var known = (_discussAgentLocal[other] || {}).conversationId;
                if (!known) { _pollInactiveDiscussAgent(); return; }
                fetch('/api/discuss/conversations/' + encodeURIComponent(known) + '/snapshot',
                      {cache: 'no-store'})
                    .then(function(response) { return response.ok ? response.json() : null; })
                    .then(function(data) {
                        var snapshot = (data || {}).snapshot || {};
                        var busy = !!snapshot.active_turn_id || (snapshot.queue || []).length > 0;
                        var pending = (snapshot.approvals || []).some(function(row) {
                            return row.status === 'pending';
                        });
                        _markDiscussAgentTab(other, busy || pending);
                    })
                    .catch(function() {})
                    .then(function() { _pollInactiveDiscussAgent(); });
            }, 4000);
        }

        function _markDiscussAgentTab(agent, active) {
            (UTILITY_TAB_IDS[agent] || []).forEach(function(id) {
                var el = document.getElementById(id);
                if (el) el.classList.toggle('utility-tab-busy', !!active);
            });
        }

        function loadDiscussAgentAvailability() {
            return discussApi('/api/discuss/agents', {}).then(function(data) {
                (data.agents || []).forEach(function(row) {
                    _discussAgentAvailability[row.id] = row;
                    (UTILITY_TAB_IDS[row.id] || []).forEach(function(id) {
                        var el = document.getElementById(id);
                        if (!el) return;
                        el.classList.toggle('utility-tab-unavailable', !row.available);
                        if (!row.available && row.reason) el.title = row.label + ' is unavailable — ' + row.reason;
                    });
                });
            }).catch(function() {});
        }
        var _discussLocalErrorReload = false;
        var _discussReconnectTimer = null;

        // Per agent as well as per document: the two tabs are separate
        // conversations, so a draft typed in one must not appear in the other.
        function discussDraftKey(doc, agent) {
            return 'proseview-draft:' + (agent || _discussAgent) + ':' + discussDocumentKey(doc);
        }

        function saveDiscussDraft() {
            var input = document.getElementById('discussInput');
            if (!_discussDocumentKey || !input) return;
            var key = 'proseview-draft:' + _discussAgent + ':' + _discussDocumentKey;
            try {
                if (input.value) sessionStorage.setItem(key, input.value);
                else sessionStorage.removeItem(key);
            } catch(e) {}
        }

        function restoreDiscussDraft(doc, agent) {
            try { return sessionStorage.getItem(discussDraftKey(doc, agent)) || ''; }
            catch(e) { return ''; }
        }

        function discussDocument() {
            var view = document.documentElement.dataset.view;
            if (view === 'scene' && curIdx >= 0 && paths[curIdx]) return {kind: 'scene', path: paths[curIdx]};
            if (view === 'file') {
                var title = document.getElementById('filePreviewTitle');
                var path = title ? title.textContent.trim() : '';
                var node = repoFileByPath[path];
                if (path && node && node.is_text && !node.too_large) return {kind: 'file', path: path};
            }
            return null;
        }

        function discussDocumentKey(doc) { return doc ? doc.kind + ':' + doc.path : ''; }

        function captureDiscussSelection() {
            var selection = window.getSelection ? window.getSelection() : null;
            if (!selection || selection.isCollapsed || !selection.anchorNode) return '';
            var anchor = selection.anchorNode.nodeType === 1 ? selection.anchorNode : selection.anchorNode.parentElement;
            if (!anchor || (!anchor.closest('#modalBody') && !anchor.closest('#filePreviewBody'))) return '';
            return selection.toString().slice(0, 65536);
        }

        function discussApi(path, body) {
            var controller = typeof AbortController === 'function' ? new AbortController() : null;
            var timedOut = false;
            var timeoutMs = Math.max(1, Number(_discussRequestTimeoutMs) || 15000);
            var timeout = controller ? setTimeout(function() {
                timedOut = true;
                controller.abort();
            }, timeoutMs) : null;
            return fetch(path, {
                method: 'POST',
                headers: pvHeaders(),
                body: JSON.stringify(body || {}),
                signal: controller ? controller.signal : undefined
            }).then(function(response) {
                return response.json().catch(function() { return {}; }).then(function(data) {
                    if (!response.ok) throw new Error(data.error || ('Request failed (' + response.status + ')'));
                    return data;
                });
            }).catch(function(error) {
                if (timedOut || (error && error.name === 'AbortError')) {
                    throw new Error('Request timed out. Check the connection and try again.');
                }
                if (error && (error.name === 'TypeError' || /failed to fetch|network error/i.test(error.message || ''))) {
                    var networkError = new Error('Proseview server is not responding. It will keep trying to reconnect.');
                    networkError.name = 'NetworkError';
                    throw networkError;
                }
                throw error;
            }).finally(function() {
                if (timeout !== null) clearTimeout(timeout);
            });
        }

        function setDiscussConnection(state, reason) {
            var node = document.getElementById('discussConnection');
            node.textContent = state + (reason ? ' — ' + reason : '');
            node.dataset.state = state;
        }

        // Where focus lands when the dock closes. A trigger inside the dock --
        // one of the tabs -- is no use: closing hides the subtree it lives in,
        // so focusing it silently fails and focus falls to the document. Prefer
        // the toolbar button that owns the panel, then the back button.
        function _returnFocusTarget(trigger) {
            const outside = trigger
                && trigger.getClientRects && trigger.getClientRects().length
                && !trigger.closest('#discussPanel, #terminalPanel');
            if (outside) return trigger;
            const modal = document.querySelector('#sceneModal .discuss-open-btn');
            const preview = document.querySelector('#file-preview-panel .discuss-open-btn');
            const visible = function(el) {
                return el && el.getClientRects && el.getClientRects().length ? el : null;
            };
            return visible(modal) || visible(preview)
                || document.querySelector('#sceneModal .scene-back-btn');
        }

        function openDiscuss(trigger, options) {
            options = options || {};
            var doc = discussDocument();
            if (!doc) {
                alert('Open a scene or supported text file before starting a discussion.');
                return;
            }
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            clearTimeout(_discussRefreshTimer);
            clearTimeout(_discussReconnectTimer);
            saveDiscussDraft();
            _discussReturnFocus = _returnFocusTarget(trigger);
            _discussSelection = options.selection !== undefined ? String(options.selection || '') : captureDiscussSelection();
            _discussSelectionRange = options.selectionRange && typeof options.selectionRange.start === 'number'
                ? {start: options.selectionRange.start, end: options.selectionRange.end}
                : null;
            _discussLiveDocument = options.liveDocument || null;
            _discussAttachments = [];
            _discussIncludeCurrentDocument = true;
            _discussPendingAction = options.actionId || null;
            _discussRepositoryAction = null;
            _discussRetryOfTaskId = null;
            _discussSelectedSkill = null;
            _discussAutoRun = !!options.runImmediately;
            var requestedAutoRun = _discussAutoRun;
            var requestedAction = _discussPendingAction;
            var requestedSelection = _discussSelection;
            var requestedSelectionRange = _discussSelectionRange;
            var requestedLiveDocument = _discussLiveDocument;
            closeDiscussContextPicker();
            clearDiscussError();
            var panel = document.getElementById('discussPanel');
            panel.hidden = false;
            // Whatever the dock was showing, it is showing Codex now. Doing
            // this here rather than in showDiscussTab keeps every route in --
            // the tab, a selection action, a keyboard shortcut -- agreeing.
            _showDiscussBody();
            document.getElementById('discussSend').disabled = true;
            _discussOpenFailed = false;
            _discussConversationId = null;
            document.body.classList.add('discuss-open');
            try { sessionStorage.setItem('proseview-panel-open', 'true'); } catch(e) {}
            if (typeof _termDock !== 'undefined' && _termDock === 'right') {
                var terminal = document.getElementById('terminalPanel');
                if (terminal && !terminal.hidden) terminal.hidden = true;
                document.body.classList.remove('terminal-right-open');
            }
            renderDiscussContext();
            renderDiscussTaskMode();
            setDiscussConnection('Restoring conversation', '');
            var key = discussDocumentKey(doc);
            _discussDocumentKey = key;
            var input = document.getElementById('discussInput');
            var bag = _discussAgentLocal[_discussAgent];
            var carriedDraft = _restoreDiscussAgentLocal();
            _discussPreservedDraft = bag ? carriedDraft : restoreDiscussDraft(doc, _discussAgent);
            input.value = requestedAutoRun ? '' : _discussPreservedDraft;
            var openBody = {kind: doc.kind, path: doc.path, agent: _discussAgent};
            discussApi('/api/discuss/conversations/open', openBody).then(function(data) {
                if (_discussDocumentKey !== key) return;
                _discussConversationId = data.conversation_id;
                _discussSnapshot = data.snapshot;
                renderDiscussSnapshot();
                connectDiscussEvents();
                renderDiscussTaskMode();
                document.getElementById('discussSend').disabled = false;
                _markDiscussAgentTab(_discussAgent, false);
                loadDiscussAgentAvailability();
                _pollInactiveDiscussAgent();
                if (options.showSkills) loadDiscussSkills();
                else if (requestedAutoRun && requestedAction) {
                    runDiscussSelectionAction(requestedAction, requestedSelection, requestedSelectionRange, requestedLiveDocument);
                }
                else input.focus();
            }).catch(function(error) {
                _discussOpenFailed = true;
                
                var msg = error.message || '';
                var label = discussAgentLabel();
                if (msg.includes('Codex') || msg.includes('API key') || msg.includes('app-server')
                    || msg.includes('claude-agent-sdk') || msg.includes('Claude Code')) {
                    setDiscussConnection('Not connected', '');
                    // Built as nodes, not markup: the reason is an error string
                    // and must never be interpolated into innerHTML.
                    var empty = document.createElement('div');
                    empty.className = 'discuss-empty-state';
                    var icon = document.createElement('div');
                    icon.className = 'discuss-empty-icon';
                    icon.textContent = '🤖';
                    var heading = document.createElement('h3');
                    heading.textContent = label + ' is not connected';
                    var blurb = document.createElement('p');
                    blurb.className = 'discuss-empty-blurb';
                    blurb.textContent = 'Proseview runs entirely locally, but you can connect an AI agent '
                        + 'to discuss your manuscript, fix continuity errors, and review pacing.';
                    var reason = document.createElement('p');
                    reason.className = 'discuss-empty-reason';
                    var em = document.createElement('em');
                    em.textContent = msg;
                    reason.appendChild(em);
                    [icon, heading, blurb, reason].forEach(function(node) { empty.appendChild(node); });
                    var log = document.getElementById('discussLog');
                    log.textContent = '';
                    log.appendChild(empty);
                    document.getElementById('discussComposerArea').hidden = true;
                    document.getElementById('discussAnnouncement').textContent = label + ' is not connected.';
                    return;
                }

                setDiscussConnection('Unavailable', error.message);
                renderDiscussError(error.message, {kind: error.name === 'NetworkError' ? 'transport' : 'request'});
                var button = document.getElementById('discussSend');
                button.textContent = 'Try again';
                button.disabled = false;
                document.getElementById('discussAnnouncement').textContent = 'Discuss could not open. ' + error.message;
            });
        }

        function openDiscussForSelection(trigger, selection, options) {
            options = options || {};
            options.selection = String(selection || '');
            var panel = document.getElementById('discussPanel');
            var doc = discussDocument();
            if (panel && !panel.hidden && doc && _discussConversationId && _discussDocumentKey === discussDocumentKey(doc)) {
                _discussReturnFocus = (trigger && trigger.getClientRects && trigger.getClientRects().length)
                    ? trigger : document.querySelector('#sceneModal .scene-back-btn');
                _discussSelection = options.selection;
                _discussSelectionRange = options.selectionRange || null;
                _discussLiveDocument = options.liveDocument || null;
                _discussPendingAction = options.actionId || null;
                _discussRepositoryAction = null;
                _discussRetryOfTaskId = null;
                _discussSelectedSkill = null;
                _discussAutoRun = !!options.runImmediately;
                renderDiscussContext(); renderDiscussTaskMode();
                if (options.showSkills) loadDiscussSkills();
                else if (_discussAutoRun && _discussPendingAction) {
                    runDiscussSelectionAction(
                        _discussPendingAction, _discussSelection, _discussSelectionRange, _discussLiveDocument
                    );
                } else document.getElementById('discussInput').focus();
                return;
            }
            openDiscuss(trigger, options);
        }

        function closeDiscuss() {
            saveDiscussDraft();
            closeDiscussContextPicker();
            var panel = document.getElementById('discussPanel');
            panel.hidden = true;
            document.body.classList.remove('discuss-open');
            try { sessionStorage.setItem('proseview-panel-open', 'false'); } catch(e) {}
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            clearTimeout(_discussRefreshTimer);
            clearTimeout(_discussReconnectTimer);
            var focus = _discussReturnFocus;
            _discussReturnFocus = null;
            if (focus && focus.isConnected && typeof focus.focus === 'function') focus.focus();
        }

        function hideDiscussForTerminal() {
            var panel = document.getElementById('discussPanel');
            if (panel && !panel.hidden) {
                panel.hidden = true;
                document.body.classList.remove('discuss-open');
            }
        }

        // ── Scene panel tabs ────────────────────────────────────────────
        //
        // Four tabs in one dock, ordered by how much they can surprise you.
        // Scene and Analysis are deterministic -- frontmatter, counts, and the
        // highlight passes, all derived from the file on disk. Codex is the
        // only surface that calls a model. Terminal is a shell. Keeping that
        // boundary legible is the point of the split.
        const SCENE_PANEL_TABS = ['scene', 'analysis', 'history', 'codex', 'claude', 'terminal'];
        const SCENE_PANEL_TAB_KEY = 'proseview-scene-panel-tab';

        function _readScenePanelTab() {
            var saved = null;
            try { saved = localStorage.getItem(SCENE_PANEL_TAB_KEY); } catch (e) {}
            // "details" was this tab's name before it split into Scene and
            // Analysis; a stored value from then must not leave the dock blank.
            if (saved === 'details') saved = 'scene';
            // "discuss" was the single agent tab before Codex and Claude got
            // one each. Send those readers to whichever agent they last used
            // rather than dropping them on Scene.
            if (saved === 'discuss') saved = _discussAgent;
            return SCENE_PANEL_TABS.indexOf(saved) >= 0 ? saved : 'scene';
        }

        // Both copies of the tab row -- the panel's and the terminal's -- are
        // driven from here, so whichever one you are looking at agrees with
        // what the dock is actually showing.
        const UTILITY_TAB_IDS = {
            scene: ['utilityTabScene', 'termUtilityTabScene'],
            analysis: ['utilityTabAnalysis', 'termUtilityTabAnalysis'],
            history: ['utilityTabHistory', 'termUtilityTabHistory'],
            codex: ['utilityTabCodex', 'termUtilityTabCodex'],
            claude: ['utilityTabClaude', 'termUtilityTabClaude'],
            terminal: ['utilityTabTerminal', 'termUtilityTabTerminal']
        };

        function _setUtilityTab(name) {
            SCENE_PANEL_TABS.forEach(function(tab) {
                UTILITY_TAB_IDS[tab].forEach(function(id) {
                    const el = document.getElementById(id);
                    if (!el) return;
                    const on = tab === name;
                    el.classList.toggle('active', on);
                    el.setAttribute('aria-selected', on ? 'true' : 'false');
                });
            });
            // Terminal is a destination, not a scene view: reopening the panel
            // on it would show a shell where the reader expected their scene.
            if (name === 'terminal') return;
            try { localStorage.setItem(SCENE_PANEL_TAB_KEY, name); } catch (e) {}
        }

        function _setDockHeading(text, showConnection) {
            const title = document.getElementById('discussTitle');
            const conn = document.getElementById('discussConnection');
            const heading = document.querySelector('.discuss-heading');
            if (title && text !== null) {
                if (!title.dataset.discussLabel) title.dataset.discussLabel = title.textContent;
                title.textContent = text;
            } else if (title && title.dataset.discussLabel) {
                title.textContent = title.dataset.discussLabel;
            }
            if (conn) conn.hidden = !showConnection;
            // The scene tabs are already named by the tab that is lit. Repeating
            // the name underneath is the duplication that made the old header
            // read as two competing sets of controls. Codex keeps its heading
            // because the connection state hangs off it.
            if (heading) heading.hidden = !showConnection;
        }

        // Everything a scene pane has to cover, and -- separately -- the parts
        // that come back when Codex returns. "New activity" is not in the
        // second list: it earns its visibility from the log, so restoring it
        // blind would announce activity that had already been read.
        function _discussBodyEls() {
            return ['discussContext', 'discussLog', 'discussComposerArea', 'discussNewActivity']
                .map(function(id) { return document.getElementById(id); }).filter(Boolean);
        }

        function _discussVisibleEls() {
            return ['discussContext', 'discussLog', 'discussComposerArea']
                .map(function(id) { return document.getElementById(id); }).filter(Boolean);
        }

        const SCENE_PANEL_PANES = {
            scene: {id: 'sceneDetailsPane', heading: 'Scene', render: renderSceneDetailsPane},
            analysis: {id: 'sceneAnalysisPane', heading: 'Analysis', render: renderSceneAnalysisPane},
            history: {id: 'sceneHistoryPane', heading: 'History', render: function() { if(paths[curIdx]) loadSceneHistory(paths[curIdx]); }}
        };

        function showScenePanelTab(name) { console.trace('showScenePanelTab called with:', name);
            const spec = SCENE_PANEL_PANES[name];
            const panel = document.getElementById('discussPanel');
            if (!spec || !panel) return;
            const pane = document.getElementById(spec.id);
            if (!pane) return;
            hideRightTerminalForPanel();
            panel.hidden = false;
            document.body.classList.add('discuss-open');
            try { sessionStorage.setItem('proseview-panel-open', 'true'); } catch(e) {}
            _discussBodyEls().forEach(function(el) { el.hidden = true; });
            Object.keys(SCENE_PANEL_PANES).forEach(function(key) {
                const other = document.getElementById(SCENE_PANEL_PANES[key].id);
                if (other) other.hidden = key !== name;
            });
            // "Codex / Live" names the Discuss connection; it has no business
            // sitting above a pane of counts and frontmatter.
            _setDockHeading(spec.heading, false);
            spec.render();
            _setUtilityTab(name);
        }

        // Kept as a named seam: it is the entry point the scene modal and the
        // tests reach for, and it now means "the deterministic scene tab".
        function showSceneDetailsTab() { showScenePanelTab('scene'); }
        function showSceneAnalysisTab() { showScenePanelTab('analysis'); }

        function _showDiscussBody() {
            Object.keys(SCENE_PANEL_PANES).forEach(function(key) {
                const pane = document.getElementById(SCENE_PANEL_PANES[key].id);
                if (pane) pane.hidden = true;
            });
            _discussVisibleEls().forEach(function(el) { el.hidden = false; });
            _setDockHeading(null, true);
            _applyDiscussAgentLabels();
            _setUtilityTab(_discussAgent);
        }

        function showDiscussTab(trigger) { showDiscussAgentTab(_discussAgent, trigger); }

        function hideRightTerminalForPanel() {
            const term = document.getElementById('terminalPanel');
            if (term && typeof _termDock !== 'undefined' && _termDock === 'right') term.hidden = true;
        }

        // ── Dock scope ──────────────────────────────────────────────────────
        // Leaving a scene closes the dock. Three of the four tabs describe the
        // document that just closed -- Scene and Analysis directly, and Codex
        // refuses to start without one, see the guard at the top of
        // openDiscuss. Only Terminal stands alone, and switching to it would
        // drop the reader into a shell they never asked for, spawning a fresh
        // one when none was running: a process created as a side effect of
        // clicking "Dashboard".
        //
        // Closing costs nothing. closeScenePanel only hides the terminal, so a
        // live session keeps running and comes back intact when the dock is
        // reopened; _termSessions is never touched.
        const SCENE_SCOPED_TABS = ['scene', 'analysis', 'history', 'codex', 'claude'];

        function _terminalIsAvailable() {
            return typeof terminalAvailable === 'undefined' || !!terminalAvailable;
        }

        function _sceneScopedViewIsOpen() {
            const view = document.documentElement.dataset.view;
            return view === 'scene' || view === 'file';
        }

        function syncScenePanelScope() {
            const scoped = _sceneScopedViewIsOpen();
            SCENE_SCOPED_TABS.forEach(function(tab) {
                UTILITY_TAB_IDS[tab].forEach(function(id) {
                    const el = document.getElementById(id);
                    if (el) el.hidden = !scoped;
                });
            });
            // Terminal is all the dashboard dock can offer, so without one the
            // button would open an empty panel.
            const dashBtn = document.getElementById('dashboardPanelBtn');
            if (dashBtn) dashBtn.hidden = !_terminalIsAvailable();

            if (!scoped) {
                closeScenePanel();
            } else {
                var shouldBeOpen = false;
                try { shouldBeOpen = sessionStorage.getItem('proseview-panel-open') === 'true'; } catch(e) {}
                var panel = document.getElementById('discussPanel');
                if (shouldBeOpen && panel && panel.hidden) {
                    var tab = _readScenePanelTab();
                    if (DISCUSS_AGENTS.indexOf(tab) >= 0) showDiscussAgentTab(tab);
                    else showScenePanelTab(tab);
                }
            }
        }

        // Observed rather than called from each transition: `data-view` is set
        // and cleared in seven places across three files, and the dock being
        // left on a stale scene is exactly what happens when one is missed.
        new MutationObserver(syncScenePanelScope).observe(
            document.documentElement,
            {attributes: true, attributeFilter: ['data-view']}
        );
        document.addEventListener('DOMContentLoaded', syncScenePanelScope);

        function toggleScenePanel(trigger) {
            const panel = document.getElementById('discussPanel');
            const term = document.getElementById('terminalPanel');
            const termInDock = term && !term.hidden
                && typeof _termDock !== 'undefined' && _termDock === 'right';
            if ((panel && !panel.hidden) || termInDock) { closeScenePanel(); return; }
            const tab = _readScenePanelTab();
            // On the dashboard the Terminal is the only tab with anything to
            // show. Opening it here is fine where falling into it on navigation
            // was not: this is a button the reader pressed. `_setUtilityTab`
            // never stores 'terminal', so their preferred tab survives.
            if (!_sceneScopedViewIsOpen() && SCENE_SCOPED_TABS.indexOf(tab) >= 0) {
                if (_terminalIsAvailable()) showRightTerminal();
                return;
            }
            // One call, not two: openDiscuss opens a conversation on the
            // server, and doing it twice queued a second thread/read behind the
            // first for every reader whose last tab was an agent.
            if (DISCUSS_AGENTS.indexOf(tab) >= 0) showDiscussAgentTab(tab, trigger);
            else showScenePanelTab(tab);
        }

        // The Panel button owns the whole dock, so closing has to cover the
        // right-docked terminal too -- otherwise pressing it while a shell was
        // showing did nothing visible.
        function closeScenePanel() {
            const term = document.getElementById('terminalPanel');
            var termInDock = term && typeof _termDock !== 'undefined' && _termDock === 'right';
            const panel = document.getElementById('discussPanel');
            var wasOpen = (panel && !panel.hidden) || (term && !term.hidden && termInDock);

            if (termInDock) term.hidden = true;
            if (panel && !panel.hidden) closeDiscuss();
            
            if (wasOpen) {
                try { sessionStorage.setItem('proseview-panel-open', 'false'); } catch(e) {}
            }
        }

        function renderSceneDetailsPane() {
            const pane = document.getElementById('sceneDetailsPane');
            if (!pane) return;
            pane.replaceChildren();
            // The context body starts life detached, built by the scene
            // renderer. It carries frontmatter, story fields, characters,
            // related documents and tasks.
            const body = window._sceneContextBody;
            if (body) { body.hidden = false; pane.appendChild(body); }
            else pane.appendChild(_scenePanelEmpty('Open a scene to see its frontmatter, links and tasks.'));
        }

        function _scenePanelEmpty(text) {
            const p = document.createElement('p');
            p.className = 'scene-panel-empty';
            p.textContent = text;
            return p;
        }

        function renderSceneAnalysisPane() {
            const pane = document.getElementById('sceneAnalysisPane');
            if (!pane) return;
            pane.replaceChildren();
            // Cache the stat grid on first sight. replaceChildren() detaches
            // it, so a second render could not find it through getElementById
            // and the pane silently lost its numbers.
            if (!window._sceneDetailsNodes) {
                window._sceneDetailsNodes = {stats: document.getElementById('modalStats')};
            }
            const stats = window._sceneDetailsNodes.stats;
            const path = (typeof paths !== 'undefined' && typeof curIdx !== 'undefined')
                ? paths[curIdx] : null;
            if (!path) {
                pane.appendChild(_scenePanelEmpty('Open a scene to see its measures and highlight passes.'));
                return;
            }
            pane.appendChild(_scenePanelHeading('Measures'));
            if (stats) { stats.hidden = false; pane.appendChild(stats); }
            const passHeading = _scenePanelHeading('Highlight passes');
            const allBtn = document.createElement('button');
            allBtn.type = 'button';
            allBtn.id = 'scenePassAllBtn';
            allBtn.className = 'scene-pass-all';
            allBtn.textContent = 'All';
            allBtn.setAttribute('aria-pressed', 'false');
            allBtn.title = 'Turn every pass on, or clear them all';
            allBtn.onclick = toggleAllHighlights;
            passHeading.appendChild(allBtn);
            pane.appendChild(passHeading);
            pane.appendChild(_scenePassList(path));
            syncAllBtn();

            const m = (typeof meta !== 'undefined' && meta[path]) || {};
            const dlg = (m.top_dlg && m.top_dlg.length) ? m.top_dlg.join(', ') : null;
            if (dlg) {
                const note = document.createElement('p');
                note.className = 'scene-panel-note';
                note.append('Top dialogue keywords: ');
                const strong = document.createElement('strong');
                strong.textContent = dlg;
                note.appendChild(strong);
                pane.appendChild(note);
            }
        }

        function _scenePanelHeading(text) {
            const h = document.createElement('p');
            h.className = 'scene-panel-heading';
            h.textContent = text;
            return h;
        }

        // One row per pass: a switch, the name, its examples, and how many
        // matches this scene actually has. The count is the reason the list is
        // ordered by it -- a pass with nothing to show should not sit above one
        // with thirty hits, and a zero row says "nothing here" without being
        // clicked.
        function _scenePassList(path) {
            const list = document.createElement('div');
            list.className = 'scene-pass-list';
            list.id = 'scenePassList';
            const byPass = ((typeof highlightsByPath !== 'undefined' && highlightsByPath[path])
                || {}).highlights || {};
            PASS_ORDER.map(function(name) {
                const hits = byPass[name];
                return {name: name, count: Array.isArray(hits) ? hits.length : 0};
            }).sort(function(a, b) {
                return b.count - a.count || PASS_ORDER.indexOf(a.name) - PASS_ORDER.indexOf(b.name);
            }).forEach(function(entry) {
                list.appendChild(_scenePassRow(entry.name, entry.count));
            });
            return list;
        }

        function _scenePassRow(name, count) {
            const on = !!hls[name];
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'scene-pass-row' + (on ? ' is-on' : '') + (count ? '' : ' is-empty');
            row.id = 'pass-row-' + name;
            row.dataset.pass = name;
            row.setAttribute('aria-pressed', on ? 'true' : 'false');
            // The examples are always visible; the note is the hover and
            // keyboard-focus layer, never something you must reach to read the row.
            if (PASS_NOTES[name]) row.title = PASS_NOTES[name];
            row.onclick = function() { toggleHighlight(name); };

            const sw = document.createElement('span');
            sw.className = 'scene-pass-switch';
            sw.setAttribute('aria-hidden', 'true');

            const label = document.createElement('span');
            label.className = 'scene-pass-label';
            const title = document.createElement('span');
            title.className = 'scene-pass-name';
            title.textContent = PASS_LABELS[name] || name;
            const example = document.createElement('span');
            example.className = 'scene-pass-example';
            example.textContent = PASS_EXAMPLES[name] || '';
            label.append(title, example);

            const n = document.createElement('span');
            n.className = 'scene-pass-count';
            n.textContent = String(count);
            n.title = count === 1 ? '1 match in this scene' : count + ' matches in this scene';

            row.append(sw, label, n);
            return row;
        }

        // Called whenever a pass is toggled from anywhere, so the list agrees
        // with the prose without being rebuilt.
        function syncScenePassRows() {
            document.querySelectorAll('#scenePassList .scene-pass-row').forEach(function(row) {
                const on = !!hls[row.dataset.pass];
                row.classList.toggle('is-on', on);
                row.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
        }

        function showRightTerminal() {
            hideDiscussForTerminal();
            if (typeof _termDock !== 'undefined') _termDock = 'right';
            try { localStorage.setItem('proseview-terminal-dock', 'right'); } catch(e) {}
            _setUtilityTab('terminal');
            var panel = document.getElementById('terminalPanel');
            if (typeof _termSessions !== 'undefined' && _termSessions.length) {
                panel.hidden = false;
                _applyTerminalDock();
            } else {
                openShellTerminal();
            }
        }

        function discussFollowActiveDocument() {
            var panel = document.getElementById('discussPanel');
            if (!panel || panel.hidden) return;
            var doc = discussDocument();
            var key = discussDocumentKey(doc);
            if (doc && key !== _discussDocumentKey) openDiscuss(_discussReturnFocus);
        }

        function connectDiscussEvents() {
            if (_discussEventSource) _discussEventSource.close();
            clearTimeout(_discussReconnectTimer);
            if (!_discussConversationId) return;
            var cid = _discussConversationId;
            var source = new EventSource(pvEventSourceUrl(
                '/api/discuss/conversations/' + encodeURIComponent(cid) + '/events'
            ));
            _discussEventSource = source;
            source.onopen = function() {
                if (_discussConversationId === cid && (!_discussSnapshot || _discussSnapshot.connection !== 'Unavailable')) {
                    clearDiscussTransportError();
                    setDiscussConnection('Live', '');
                }
            };
            source.onerror = function() {
                if (_discussConversationId !== cid || _discussEventSource !== source) return;
                if (source.readyState === EventSource.CLOSED) {
                    showDiscussReloadRequired(source);
                    return;
                }
                setDiscussConnection('Reconnecting', 'Proseview server unavailable');
                scheduleDiscussReconnectProbe(cid, source);
            };
            source.addEventListener('snapshot', function(event) {
                setDiscussConnection('Restoring conversation', '');
                _discussSnapshot = JSON.parse(event.data);
                renderDiscussSnapshot();
            });
            ['connection', 'conversation.reset', 'turn.queued', 'turn.cancelled', 'turn.preparing', 'turn.started', 'turn.completed', 'turn.idle', 'response.completed', 'progress.delta',
             'plan.updated', 'activity.updated', 'approval.requested', 'approval.resolved', 'approval.expired', 'task.ready', 'task.failed',
             'task.updated', 'tasks.cleared', 'notice.dismissed', 'warning', 'error'].forEach(function(type) {
                source.addEventListener(type, function(event) {
                    if (type === 'connection') {
                        var detail = JSON.parse(event.data);
                        setDiscussConnection(detail.state, detail.reason || '');
                    }
                    if (type === 'approval.requested') {
                        var request = JSON.parse(event.data);
                        _discussLastApproval = request.request_id || '';
                    }
                    if (type === 'task.ready' || type === 'task.failed') {
                        var completedTask = JSON.parse(event.data);
                        var requestId = String(completedTask.client_request_id || '');
                        var submittedHere = !!_discussAutoReviewRequests[requestId];
                        if (submittedHere) delete _discussAutoReviewRequests[requestId];
                        if (type === 'task.ready' && completedTask.kind === 'alternatives' && submittedHere) {
                            autoReviewDiscussTask(completedTask.task_id);
                        }
                    }
                    scheduleDiscussSnapshot();
                });
            });
            source.addEventListener('skills.changed', function() { if (!document.getElementById('discussSkillsPicker').hidden) loadDiscussSkills(true); });
            source.addEventListener('response.delta', function(event) {
                var detail = JSON.parse(event.data);
                appendDiscussStreamDelta(detail.text || '');
            });
        }

        function scheduleDiscussReconnectProbe(cid, source) {
            clearTimeout(_discussReconnectTimer);
            _discussReconnectTimer = setTimeout(function() {
                var panel = document.getElementById('discussPanel');
                if (!panel || panel.hidden || _discussConversationId !== cid || _discussEventSource !== source) return;
                fetch('/api/discuss/conversations/' + encodeURIComponent(cid) + '/snapshot', {cache: 'no-store'})
                    .then(function(response) {
                        if (response.status === 404) {
                            showDiscussReloadRequired(source);
                            return null;
                        }
                        if (!response.ok) throw new Error('Request failed (' + response.status + ')');
                        return response.json();
                    })
                    .then(function(data) {
                        if (!data || !data.snapshot || _discussConversationId !== cid) return;
                        _discussSnapshot = data.snapshot;
                        clearDiscussTransportError();
                        renderDiscussSnapshot();
                        if (source.readyState === EventSource.CLOSED) connectDiscussEvents();
                    })
                    .catch(function() {
                        if (_discussConversationId !== cid) return;
                        renderDiscussError(
                            'Proseview server is not responding. It will keep trying to reconnect.',
                            {kind: 'transport'}
                        );
                    });
            }, 900);
        }

        function showDiscussReloadRequired(source) {
            clearTimeout(_discussReconnectTimer);
            if (source) source.close();
            if (_discussEventSource === source) _discussEventSource = null;
            saveDiscussDraft();
            setDiscussConnection('Reload required', 'Proseview server restarted');
            renderDiscussError(
                'Proseview restarted. Reload this page to reconnect.',
                {kind: 'transport', reload: true}
            );
            var button = document.getElementById('discussSend');
            button.disabled = true;
            button.textContent = 'Reload';
            document.getElementById('discussAnnouncement').textContent = 'Proseview restarted. Reload the page to reconnect; your question draft is saved.';
        }

        function scheduleDiscussSnapshot() {
            clearTimeout(_discussRefreshTimer);
            _discussRefreshTimer = setTimeout(function() {
                if (!_discussConversationId) return;
                fetch('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/snapshot', {cache: 'no-store'})
                    .then(function(response) { return response.json(); })
                    .then(function(data) { if (data.snapshot) { _discussSnapshot = data.snapshot; renderDiscussSnapshot(); } })
                    .catch(function() {
                        var panel = document.getElementById('discussPanel');
                        if (panel && !panel.hidden) setDiscussConnection('Reconnecting', '');
                    });
            }, 35);
        }

        function appendDiscussStreamDelta(text) {
            var log = document.getElementById('discussLog');
            var draft = log.querySelector('.discuss-stream-draft');
            var atBottom = discussIsAtBottom(log);
            if (!draft) {
                draft = document.createElement('div');
                draft.className = 'discuss-message assistant discuss-stream-draft';
                draft.dataset.text = '';
                log.appendChild(draft);
            }
            draft.dataset.text += text;
            draft.textContent = draft.dataset.text;
            discussAfterActivity(atBottom);
        }

        function normalizeProsviewRepositoryPath(value) {
            var parts = String(value || '').replace(/\\/g, '/').split('/');
            var clean = [];
            for (var i = 0; i < parts.length; i++) {
                var part = parts[i];
                if (!part || part === '.') continue;
                if (part === '..') {
                    if (!clean.length) return null;
                    clean.pop();
                } else clean.push(part);
            }
            return clean.join('/');
        }

        function prosviewRepositoryRoot() {
            if (_prosviewRepositoryRootCache !== null) return _prosviewRepositoryRootCache;
            var keys = Object.keys(typeof repositoryFileByPath === 'undefined' ? {} : repositoryFileByPath);
            for (var i = 0; i < keys.length; i++) {
                var node = repositoryFileByPath[keys[i]];
                if (!node || !node.is_scene || !node.scene_path || !meta[node.scene_path]) continue;
                var absolute = String(meta[node.scene_path].abs_path || '').replace(/\\/g, '/');
                var suffix = '/' + String(node.path || '').replace(/\\/g, '/');
                if (absolute.endsWith(suffix)) {
                    _prosviewRepositoryRootCache = absolute.slice(0, -suffix.length);
                    return _prosviewRepositoryRootCache;
                }
            }
            _prosviewRepositoryRootCache = '';
            return _prosviewRepositoryRootCache;
        }

        function prosviewTargetForRepositoryPath(path, line) {
            var clean = normalizeProsviewRepositoryPath(path);
            if (!clean) return null;
            if (paths.indexOf(clean) >= 0) return {kind: 'scene', path: clean, line: line};
            var node = (typeof repositoryFileByPath !== 'undefined' && repositoryFileByPath[clean])
                || (typeof repoFileByPath !== 'undefined' && repoFileByPath[clean]);
            if (!node) return null;
            if (node.is_scene && node.scene_path && paths.indexOf(node.scene_path) >= 0) {
                return {kind: 'scene', path: node.scene_path, line: line};
            }
            return {kind: 'file', path: node.path, line: line};
        }

        function currentProsviewRepositoryPath() {
            if (document.documentElement.dataset.view === 'file') {
                var title = document.getElementById('filePreviewTitle');
                return title ? String(title.textContent || '') : '';
            }
            if (document.documentElement.dataset.view !== 'scene' || curIdx < 0 || !paths[curIdx]) return '';
            var scenePath = paths[curIdx];
            var keys = Object.keys(typeof repositoryFileByPath === 'undefined' ? {} : repositoryFileByPath);
            for (var i = 0; i < keys.length; i++) {
                var node = repositoryFileByPath[keys[i]];
                if (node && node.is_scene && node.scene_path === scenePath) return node.path;
            }
            return scenePath;
        }

        function resolveProsviewFileReference(value) {
            var raw = String(value || '').trim();
            if (!raw) return null;
            try { raw = decodeURIComponent(raw); } catch(e) {}
            if (/^file:\/\//i.test(raw)) {
                try {
                    var fileUrl = new URL(raw);
                    if (fileUrl.protocol !== 'file:' || (fileUrl.host && fileUrl.host !== 'localhost')) return null;
                    raw = fileUrl.pathname;
                } catch(e) { return null; }
            } else if (/^[a-z][a-z0-9+.-]*:/i.test(raw)) {
                return null;
            }

            var line = null;
            var hashLine = raw.match(/#L(\d+)(?:C\d+)?$/i);
            if (hashLine) {
                line = parseInt(hashLine[1], 10);
                raw = raw.slice(0, hashLine.index);
            } else {
                var suffixLine = raw.match(/:(\d+)(?::\d+)?$/);
                if (suffixLine) {
                    line = parseInt(suffixLine[1], 10);
                    raw = raw.slice(0, suffixLine.index);
                }
            }
            if (!Number.isInteger(line) || line < 1) line = null;
            raw = raw.replace(/\\/g, '/');

            if (raw.charAt(0) === '/') {
                var sceneKeys = Object.keys(meta || {});
                for (var i = 0; i < sceneKeys.length; i++) {
                    var scenePath = sceneKeys[i];
                    if (String((meta[scenePath] || {}).abs_path || '').replace(/\\/g, '/') === raw) {
                        return {kind: 'scene', path: scenePath, line: line};
                    }
                }
                var fileKeys = Object.keys(typeof repoFileByPath === 'undefined' ? {} : repoFileByPath);
                for (var j = 0; j < fileKeys.length; j++) {
                    var fileNode = repoFileByPath[fileKeys[j]];
                    if (String((fileNode || {}).abs_path || '').replace(/\\/g, '/') === raw) {
                        return prosviewTargetForRepositoryPath(fileNode.path, line);
                    }
                }
                var root = prosviewRepositoryRoot();
                if (!root || (raw !== root && !raw.startsWith(root + '/'))) return null;
                return prosviewTargetForRepositoryPath(raw.slice(root.length + 1), line);
            }

            var direct = prosviewTargetForRepositoryPath(raw, line);
            if (direct) return direct;
            var current = currentProsviewRepositoryPath();
            if (!current) return null;
            var slash = current.lastIndexOf('/');
            var relative = (slash >= 0 ? current.slice(0, slash + 1) : '') + raw;
            return prosviewTargetForRepositoryPath(relative, line);
        }

        function focusProsviewSourceLine(line) {
            if (!Number.isInteger(line) || line < 1) return;
            var blocks = Array.prototype.slice.call(document.querySelectorAll('#sceneProseHost .ProseMirror > [data-line]'));
            if (!blocks.length) return;
            var target = null;
            for (var i = 0; i < blocks.length; i++) {
                var blockLine = parseInt(blocks[i].getAttribute('data-line') || '', 10);
                if (!Number.isInteger(blockLine)) continue;
                if (blockLine === line) { target = blocks[i]; break; }
                if (blockLine < line) target = blocks[i];
                else if (!target) { target = blocks[i]; break; }
            }
            if (target && typeof _flashAndScrollTo === 'function') _flashAndScrollTo(target);
        }

        function openProsviewFileReference(target) {
            if (!target) return;
            var currentScene = document.documentElement.dataset.view === 'scene' && curIdx >= 0 ? paths[curIdx] : '';
            var sameScene = target.kind === 'scene' && target.path === currentScene;
            if (_pmEditMode && _pmDirty && !sameScene) {
                var warning = 'Save or cancel your scene edits before opening another file.';
                document.getElementById('discussAnnouncement').textContent = warning;
                renderDiscussError(warning);
                return;
            }
            if (target.kind === 'scene') {
                if (!sameScene && typeof openSceneModal === 'function') openSceneModal(target.path);
                window.setTimeout(function() { focusProsviewSourceLine(target.line); }, 0);
                document.getElementById('discussAnnouncement').textContent = 'Opened ' + target.path + (target.line ? ' at line ' + target.line : '');
                return;
            }
            if (typeof closeSceneModal === 'function' && document.documentElement.dataset.view === 'scene') closeSceneModal();
            if (typeof previewRepoFile === 'function') previewRepoFile(target.path, {focus: true});
            document.getElementById('discussAnnouncement').textContent = 'Opened ' + target.path + ' in Prosview';
        }

        function safeDiscussUrl(value) {
            try {
                if (!/^(?:https?:\/\/|mailto:)/i.test(String(value || '').trim())) return null;
                var parsed = new URL(value);
                return ['http:', 'https:', 'mailto:'].indexOf(parsed.protocol) >= 0 ? value : null;
            } catch(e) { return null; }
        }

        // ── Images ──────────────────────────────────────────────────────────
        //
        // `imagesConfig.mode` is 'all' | 'local' | 'off'. Remote images inside
        // agent output are gated separately: in Discuss the model chooses the
        // URL, so loading it would report the reader's IP and the fact that the
        // document was opened to a host neither of us picked.

        function repoAssetUrl(src, basePath) {
            // Resolve a Markdown src against the document that referenced it and
            // return a /repo-asset/ URL, or null if it escapes the repository.
            var raw = String(src || '').trim();
            if (!raw) return null;
            var parts = [];
            if (raw.charAt(0) !== '/') {
                var baseDir = String(basePath || '').split('/');
                baseDir.pop();
                parts = baseDir;
            }
            // A `..` with nothing left to pop is an escape attempt, not a
            // no-op. Array.pop() on an empty array returns undefined silently,
            // which would quietly rewrite ../../../../etc/passwd into a
            // different in-repo path instead of refusing it.
            var escaped = false;
            raw.split('/').forEach(function(segment) {
                if (!segment || segment === '.') return;
                if (segment === '..') {
                    if (!parts.length) escaped = true;
                    else parts.pop();
                    return;
                }
                parts.push(segment);
            });
            if (escaped || !parts.length) return null;
            return '/repo-asset/' + parts.map(encodeURIComponent).join('/');
        }

        function resolveImageSrc(src, ctx) {
            var mode = (typeof imagesConfig === 'object' && imagesConfig ? imagesConfig.mode : 'all');
            if (mode === 'off') return null;
            var raw = String(src || '').trim();

            if (/^data:image\//i.test(raw)) return raw;   // inline bytes reach nobody
            if (/^(?:https?:)?\/\//i.test(raw)) {
                if (mode !== 'all') return null;
                if (ctx && ctx.agentOutput
                    && !(imagesConfig && imagesConfig.remoteInAgentOutput)) return null;
                return safeDiscussUrl(raw);
            }
            return repoAssetUrl(raw, ctx && ctx.basePath);
        }

        function imageNode(src, alt, title, ctx) {
            var resolved = resolveImageSrc(src, ctx);
            if (!resolved) {
                var placeholder = document.createElement('span');
                placeholder.className = 'md-image-placeholder';
                placeholder.textContent = decodeMarkdownText(alt || title || 'image');
                placeholder.title = 'Image not shown: ' + String(src || '');
                return placeholder;
            }
            var img = document.createElement('img');
            img.className = 'md-image';
            img.src = resolved;
            img.alt = decodeMarkdownText(alt || '');
            if (title) img.title = decodeMarkdownText(title);
            img.loading = 'lazy';
            // A referrer would leak the local URL, and the page it came from, to
            // any remote host.
            img.referrerPolicy = 'no-referrer';
            return img;
        }

        //: Attributes copied off a raw <img> tag. Everything else -- onerror and
        //: friends especially -- is dropped, so the tag cannot carry script.
        var IMG_ATTR_ALLOWLIST = ['src', 'alt', 'title', 'width', 'height'];

        function rawImgNode(html, ctx) {
            // Parse a literal <img> tag out of an `html` token without ever
            // handing the markup to innerHTML.
            if (ctx && ctx.allowRawImages === false) return null;
            var match = /^\s*<img\b([^>]*)>\s*$/i.exec(String(html || ''));
            if (!match) return null;
            var attrs = {};
            var pattern = /([a-zA-Z-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/g;
            var found;
            while ((found = pattern.exec(match[1])) !== null) {
                var name = found[1].toLowerCase();
                if (IMG_ATTR_ALLOWLIST.indexOf(name) < 0) continue;
                attrs[name] = found[3] !== undefined ? found[3]
                    : found[4] !== undefined ? found[4] : found[5];
            }
            if (!attrs.src) return null;
            var node = imageNode(attrs.src, attrs.alt, attrs.title, ctx);
            if (node.tagName === 'IMG') {
                if (attrs.width && /^\d+$/.test(attrs.width)) node.width = parseInt(attrs.width, 10);
                if (attrs.height && /^\d+$/.test(attrs.height)) node.height = parseInt(attrs.height, 10);
            }
            return node;
        }

        function decodeMarkdownText(value) {
            var named = {amp: '&', lt: '<', gt: '>', quot: '"', apos: "'"};
            var decoded = String(value || '');
            // Marked escapes text tokens for HTML output. This renderer uses
            // text nodes instead, so reverse that one encoding layer.
            for (var pass = 0; pass < 1; pass += 1) {
                var next = decoded.replace(/&(?:#(\d+)|#x([0-9a-f]+)|(amp|lt|gt|quot|apos));/gi, function(match, decimal, hex, name) {
                    var code = decimal ? Number(decimal) : (hex ? parseInt(hex, 16) : null);
                    if (code !== null) {
                        if (!Number.isInteger(code) || code < 1 || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return '\ufffd';
                        return String.fromCodePoint(code);
                    }
                    return named[String(name || '').toLowerCase()] || match;
                });
                if (next === decoded) break;
                decoded = next;
            }
            return decoded;
        }

        function appendMarkdownTokens(parent, tokens, ctx) {
            (tokens || []).forEach(function(token) {
                var node;
                if (token.type === 'space') return;
                if (token.type === 'text' || token.type === 'escape') {
                    if (token.tokens) appendMarkdownTokens(parent, token.tokens, ctx);
                    else parent.appendChild(document.createTextNode(decodeMarkdownText(token.text || token.raw || '')));
                    return;
                }
                if (token.type === 'html') {
                    var rawImg = rawImgNode(token.raw || token.text || '', ctx);
                    if (rawImg) { parent.appendChild(rawImg); return; }
                    parent.appendChild(document.createTextNode(token.raw || token.text || ''));
                    return;
                }
                if (token.type === 'paragraph') node = document.createElement('p');
                else if (token.type === 'heading') node = document.createElement('h' + Math.min(6, Math.max(1, token.depth || 3)));
                else if (token.type === 'strong') node = document.createElement('strong');
                else if (token.type === 'em') node = document.createElement('em');
                else if (token.type === 'codespan') { node = document.createElement('code'); node.textContent = decodeMarkdownText(token.text || ''); }
                else if (token.type === 'code') { node = document.createElement('pre'); var code = document.createElement('code'); code.textContent = decodeMarkdownText(token.text || ''); node.appendChild(code); }
                else if (token.type === 'blockquote') node = document.createElement('blockquote');
                else if (token.type === 'list') node = document.createElement(token.ordered ? 'ol' : 'ul');
                else if (token.type === 'list_item') node = document.createElement('li');
                else if (token.type === 'link') {
                    let localTarget = resolveProsviewFileReference(token.href || '');
                    var href = localTarget ? null : safeDiscussUrl(token.href || '');
                    node = (localTarget || href) ? document.createElement('a') : document.createElement('span');
                    if (localTarget) {
                        node.href = '#/' + localTarget.kind + '/' + encodeURIComponent(localTarget.path);
                        node.dataset.prosviewKind = localTarget.kind;
                        node.dataset.prosviewPath = localTarget.path;
                        if (localTarget.line) node.dataset.prosviewLine = String(localTarget.line);
                        var titleLine = localTarget.kind === 'scene' ? localTarget.line : null;
                        node.title = 'Open in Prosview' + (titleLine ? ' at line ' + titleLine : '');
                        node.onclick = function(event) {
                            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                            event.preventDefault();
                            openProsviewFileReference(localTarget);
                        };
                    } else if (href) {
                        node.href = href;
                        node.rel = 'noopener noreferrer';
                        if (node.protocol !== 'mailto:') node.target = '_blank';
                    }
                } else if (token.type === 'br') node = document.createElement('br');
                else if (token.type === 'hr') node = document.createElement('hr');
                else if (token.type === 'image') {
                    parent.appendChild(imageNode(token.href, token.text, token.title, ctx));
                    return;
                }
                else if (token.type === 'del') node = document.createElement('del');
                else if (token.type === 'table') {
                    // Built cell by cell rather than via innerHTML: this same
                    // renderer draws agent output in Discuss, so every node here
                    // has to be safe for untrusted text.
                    node = document.createElement('table');
                    var align = token.align || [];
                    var thead = document.createElement('thead');
                    var headRow = document.createElement('tr');
                    (token.header || []).forEach(function(cell, i) {
                        var th = document.createElement('th');
                        if (align[i]) th.style.textAlign = align[i];
                        appendMarkdownTokens(th, cell.tokens || [], ctx);
                        headRow.appendChild(th);
                    });
                    thead.appendChild(headRow);
                    node.appendChild(thead);
                    var tbody = document.createElement('tbody');
                    (token.rows || []).forEach(function(row) {
                        var tr = document.createElement('tr');
                        (row || []).forEach(function(cell, i) {
                            var td = document.createElement('td');
                            if (align[i]) td.style.textAlign = align[i];
                            appendMarkdownTokens(td, cell.tokens || [], ctx);
                            tr.appendChild(td);
                        });
                        tbody.appendChild(tr);
                    });
                    node.appendChild(tbody);
                    // Wrap so a wide table scrolls itself instead of the page.
                    var scroller = document.createElement('div');
                    scroller.className = 'md-table-scroll';
                    scroller.appendChild(node);
                    parent.appendChild(scroller);
                    return;
                }
                else { parent.appendChild(document.createTextNode(token.raw || token.text || '')); return; }
                if (token.type === 'list') {
                    (token.items || []).forEach(function(item) { appendMarkdownTokens(node, [item], ctx); });
                } else if (token.type !== 'code' && token.type !== 'codespan'
                           && token.type !== 'br' && token.type !== 'hr') {
                    if (token.tokens) appendMarkdownTokens(node, token.tokens, ctx);
                    else if (token.text) node.textContent = decodeMarkdownText(token.text);
                }
                parent.appendChild(node);
            });
        }

        function renderSafeMarkdown(parent, text, ctx) {
            try { appendMarkdownTokens(parent, marked.lexer(String(text || ''), {gfm: true}), ctx || {}); }
            catch(e) { parent.textContent = String(text || ''); }
        }

        function renderDiscussMarkdown(parent, text) {
            // Agent output: relative paths have no document to resolve against,
            // and remote ones obey images.remote_in_agent_output.
            renderSafeMarkdown(parent, text, {agentOutput: true});
        }

        function elementWith(className, text) {
            var node = document.createElement('div');
            node.className = className;
            if (text !== undefined) node.textContent = text;
            return node;
        }

        function discussIsAtBottom(log) {
            return log.scrollHeight - log.scrollTop - log.clientHeight <= 1;
        }

        function captureDiscussScroll(log) {
            return {atBottom: discussIsAtBottom(log), scrollTop: log.scrollTop};
        }

        function restoreDiscussScroll(log, state) {
            var previousBehavior = log.style.scrollBehavior;
            log.style.scrollBehavior = 'auto';
            log.scrollTop = state.atBottom ? log.scrollHeight : state.scrollTop;
            requestAnimationFrame(function() { log.style.scrollBehavior = previousBehavior; });
            document.getElementById('discussNewActivity').hidden = state.atBottom;
        }

        function renderDiscussNotice(notice) {
            var node = elementWith('discuss-notice ' + (notice.kind === 'error' ? 'error' : 'warning'));
            if (notice.id) node.dataset.noticeId = notice.id;
            node.appendChild(elementWith('discuss-notice-message', notice.message || ''));
            if (notice.id) {
                var dismiss = document.createElement('button');
                dismiss.type = 'button';
                dismiss.className = 'discuss-notice-dismiss';
                dismiss.textContent = '×';
                dismiss.title = 'Dismiss';
                dismiss.setAttribute('aria-label', 'Dismiss notice');
                dismiss.onclick = function() {
                    dismiss.disabled = true;
                    discussApi(
                        '/api/discuss/conversations/' + encodeURIComponent(_discussConversationId)
                        + '/notices/' + encodeURIComponent(notice.id) + '/dismiss',
                        {}
                    ).then(function() {
                        if (_discussSnapshot) {
                            _discussSnapshot.notices = (_discussSnapshot.notices || []).filter(function(candidate) {
                                return candidate.id !== notice.id;
                            });
                        }
                        renderDiscussSnapshot();
                        document.getElementById('discussLog').focus();
                        document.getElementById('discussAnnouncement').textContent = 'Notice dismissed';
                    }).catch(function(error) {
                        dismiss.disabled = false;
                        renderDiscussError(error.message);
                    });
                };
                node.appendChild(dismiss);
            }
            return node;
        }

        function renderDiscussSnapshot() {
            var snapshot = _discussSnapshot;
            if (!snapshot) return;
            setDiscussConnection(snapshot.connection || 'Live', snapshot.unavailable_reason || '');
            var log = document.getElementById('discussLog');
            var scrollState = captureDiscussScroll(log);
            log.replaceChildren();
            var notices = snapshot.notices || [];
            var renderedNotices = Object.create(null);
            function appendNoticesForRequest(requestId) {
                if (!requestId) return;
                notices.forEach(function(notice, index) {
                    if (!renderedNotices[index] && notice.client_request_id === requestId) {
                        log.appendChild(renderDiscussNotice(notice));
                        renderedNotices[index] = true;
                    }
                });
            }
            function appendUnassociatedNotices() {
                notices.forEach(function(notice, index) {
                    if (!renderedNotices[index] && !notice.client_request_id) {
                        log.appendChild(renderDiscussNotice(notice));
                        renderedNotices[index] = true;
                    }
                });
            }
            var hasNoDiscussActivity = !(snapshot.messages || []).length
                && !(snapshot.progress || []).length
                && !(snapshot.tasks || []).length;
            if (hasNoDiscussActivity) {
                var empty = elementWith('discuss-empty');
                var title = document.createElement('strong');
                if (_discussRepositoryAction) {
                    var scanStarting = document.getElementById('discussSend').disabled;
                    if (scanStarting) {
                        title.textContent = _discussRepositoryAction === 'scene_continuity'
                            ? 'Starting continuity scan…'
                            : 'Starting canon scan…';
                        empty.appendChild(title);
                        empty.appendChild(document.createTextNode('Gathering the configured story evidence. This can take a moment.'));
                    } else if (_discussRepositoryAction === 'scene_continuity') {
                        title.textContent = 'Ready to scan this scene';
                        empty.appendChild(title);
                        empty.appendChild(document.createTextNode('Add an optional focus below, or scan the active scene as-is.'));
                        var readyActions = elementWith('discuss-story-actions');
                        var scanNow = document.createElement('button'); scanNow.type = 'button'; scanNow.className = 'discuss-primary'; scanNow.textContent = 'Scan scene now';
                        scanNow.onclick = function() { runDiscussRepositoryAction(); };
                        readyActions.appendChild(scanNow); empty.appendChild(readyActions);
                    } else {
                        title.textContent = 'Ready to trace a canon change';
                        empty.appendChild(title);
                        empty.appendChild(document.createTextNode('Describe the old and new fact below, then scan for consequences.'));
                    }
                } else {
                    title.textContent = 'What do you want to examine?';
                    empty.appendChild(title); empty.appendChild(document.createTextNode('Ask about what you are reading, or start with a story-aware action.'));
                    var actions = elementWith('discuss-story-actions');
                    var canon = document.createElement('button'); canon.type = 'button'; canon.className = 'discuss-story-action';
                    canon.appendChild(elementWith('discuss-story-action-title', 'Trace a canon change'));
                    canon.appendChild(elementWith('discuss-story-action-copy', 'Find consequences across the configured story folders.'));
                    canon.onclick = function() { startDiscussRepositoryAction('canon_refactor'); };
                    actions.appendChild(canon);
                    var continuity = document.createElement('button'); continuity.type = 'button'; continuity.className = 'discuss-story-action';
                    continuity.appendChild(elementWith('discuss-story-action-title', "Check this scene's continuity"));
                    continuity.appendChild(elementWith('discuss-story-action-copy', 'Compare this document with the rest of the story evidence.'));
                    continuity.onclick = function() { startDiscussRepositoryAction('scene_continuity'); };
                    actions.appendChild(continuity); empty.appendChild(actions);
                }
                log.appendChild(empty);
            }
            appendUnassociatedNotices();
            groupDiscussTasks(snapshot.tasks || []).forEach(function(group) {
                log.appendChild(renderDiscussTask(group.latest, group.previous));
                appendNoticesForRequest(group.latest.client_request_id);
            });
            (snapshot.messages || []).forEach(function(message) {
                var wrap = elementWith('discuss-message ' + (message.role === 'user' ? 'user' : 'assistant'));
                var label = elementWith('discuss-message-label', message.role === 'user' ? 'You' : discussAgentLabel());
                wrap.appendChild(label);
                if (message.role === 'assistant') renderDiscussMarkdown(wrap, message.text);
                else wrap.appendChild(document.createTextNode(message.text || ''));
                log.appendChild(wrap);
                if (message.role === 'user') appendNoticesForRequest(message.client_request_id);
            });
            if ((snapshot.progress || []).length) {
                var progress = document.createElement('details'); progress.className = 'discuss-progress';
                var progressSummary = document.createElement('summary'); progressSummary.textContent = 'What ' + discussAgentLabel() + ' is doing'; progress.appendChild(progressSummary);
                progress.appendChild(document.createTextNode((snapshot.progress || []).join(''))); log.appendChild(progress);
            }
            if ((snapshot.plan || []).length) {
                var plan = document.createElement('details'); plan.className = 'discuss-plan'; plan.open = true;
                var planSummary = document.createElement('summary'); planSummary.textContent = 'Plan'; plan.appendChild(planSummary);
                var list = document.createElement('ol');
                snapshot.plan.forEach(function(row) { var item = document.createElement('li'); item.className = row.status || ''; item.textContent = row.step || ''; list.appendChild(item); });
                plan.appendChild(list); log.appendChild(plan);
            }
            (snapshot.activities || []).forEach(function(activity) {
                var details = document.createElement('details'); details.className = 'discuss-activity';
                var summary = document.createElement('summary'); summary.textContent = (activity.kind || 'Activity') + ' · ' + (activity.status || ''); details.appendChild(summary);
                details.appendChild(document.createTextNode(activity.command || activity.query || activity.tool || '')); log.appendChild(details);
            });
            (snapshot.approvals || []).forEach(function(approval) { log.appendChild(renderDiscussApproval(approval)); });
            notices.forEach(function(notice, index) {
                if (!renderedNotices[index]) log.appendChild(renderDiscussNotice(notice));
            });
            appendDiscussLocalError(log);
            if ((snapshot.queue || []).length) {
                var queueCard = elementWith('discuss-queue');
                var queueTitle = document.createElement('strong'); queueTitle.textContent = snapshot.queue.length + ' item' + (snapshot.queue.length === 1 ? '' : 's') + ' queued'; queueCard.appendChild(queueTitle);
                snapshot.queue.forEach(function(item) {
                    var row = elementWith('discuss-queue-item', item.label || 'Question');
                    var remove = document.createElement('button');
                    remove.type = 'button'; remove.className = 'discuss-queue-remove';
                    remove.textContent = 'Remove';
                    remove.setAttribute('aria-label', 'Remove ' + (item.label || 'question') + ' from queue');
                    remove.onclick = function() {
                        remove.disabled = true;
                        discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/queue/' + encodeURIComponent(item.client_request_id) + '/cancel', {})
                            .then(function() {
                                document.getElementById('discussAnnouncement').textContent = (item.label || 'Question') + ' removed from queue';
                                scheduleDiscussSnapshot();
                            })
                            .catch(function(error) { remove.disabled = false; renderDiscussError(error.message); });
                    };
                    row.appendChild(remove); queueCard.appendChild(row);
                });
                log.appendChild(queueCard);
            }
            var stopButton = document.getElementById('discussStop');
            stopButton.hidden = !snapshot.active_turn_id;
            if (!snapshot.active_turn_id) {
                stopButton.disabled = false;
                stopButton.textContent = 'Stop ' + discussAgentLabel();
            }
            var clearResults = document.getElementById('discussHistoryClear');
            var hasClearableResults = (snapshot.tasks || []).some(function(task) {
                return task.status !== 'queued' && task.status !== 'running';
            });
            clearResults.hidden = !hasClearableResults;
            clearResults.disabled = !!(
                snapshot.active_turn_id
                || snapshot.active_request_id
                || (snapshot.queue || []).length
                || (snapshot.tasks || []).some(function(task) {
                    return task.status === 'queued' || task.status === 'running';
                })
            );
            clearResults.title = clearResults.disabled
                ? 'Wait for assistance to finish before clearing results'
                : 'Clear assistance results from this conversation';
            var pendingApproval = (snapshot.approvals || []).some(function(approval) { return approval.status === 'pending'; });
            var newConversation = document.getElementById('discussNewConversation');
            var newConversationHint = document.getElementById('discussNewConversationHint');
            var unavailableReason = '';
            if (snapshot.active_turn_id) unavailableReason = 'Stop ' + discussAgentLabel() + ' before starting a new conversation.';
            else if (snapshot.active_request_id) unavailableReason = 'Wait for ' + discussAgentLabel() + ' to start this question before starting a new conversation.';
            else if ((snapshot.queue || []).length) unavailableReason = 'Remove or wait for queued items before starting a new conversation.';
            else if (pendingApproval) unavailableReason = 'Resolve the ' + discussAgentLabel() + ' approval request before starting a new conversation.';
            newConversation.disabled = !!unavailableReason;
            newConversation.title = unavailableReason;
            if (newConversationHint.textContent !== unavailableReason) newConversationHint.textContent = unavailableReason;
            newConversationHint.hidden = !unavailableReason;
            log.setAttribute('aria-busy', snapshot.active_turn_id ? 'true' : 'false');
            restoreDiscussScroll(log, scrollState);
            if (_discussLastApproval) {
                var target = log.querySelector('[data-approval-id="' + CSS.escape(_discussLastApproval) + '"] button');
                if (target) { target.focus(); document.getElementById('discussAnnouncement').textContent = discussAgentLabel() + ' is requesting approval'; }
                _discussLastApproval = '';
            }
        }

        function groupDiscussTasks(tasks) {
            var groups = [];
            var byRoot = Object.create(null);
            tasks.forEach(function(task) {
                var rootId = task.retry_root_id || task.id;
                var group = byRoot[rootId];
                if (!group) {
                    group = {attempts: []};
                    byRoot[rootId] = group;
                    groups.push(group);
                }
                group.attempts.push(task);
            });
            groups.forEach(function(group) {
                group.attempts.sort(function(left, right) {
                    var attemptDelta = Number(left.attempt || 1) - Number(right.attempt || 1);
                    return attemptDelta || Number(left.created_at || 0) - Number(right.created_at || 0);
                });
                group.latest = group.attempts[group.attempts.length - 1];
                group.previous = group.attempts.slice(0, -1);
            });
            return groups;
        }

        function discussTaskStatusLabel(status) {
            if (status === 'applied' || status === 'staged') return 'Applied · Not saved';
            if (status === 'saved') return 'Saved';
            if (status === 'reviewing') return 'Reviewing';
            if (status === 'ready') return 'Ready';
            var label = String(status || 'Unknown').replace(/_/g, ' ');
            return label.charAt(0).toUpperCase() + label.slice(1);
        }

        function renderDiscussAlternatives(task, result) {
            var fragment = document.createDocumentFragment();
            if (task.instruction) {
                fragment.appendChild(elementWith('discuss-task-instruction', 'Instruction · ' + task.instruction));
            }
            var alternatives = result.alternatives || [];
            var selected = Number.isInteger(task.selected_option) ? task.selected_option : -1;
            if (selected >= 0 && selected < alternatives.length) {
                var used = elementWith('discuss-task-used');
                used.appendChild(elementWith('discuss-task-used-label', 'Used suggestion ' + String(selected + 1)));
                used.appendChild(elementWith('discuss-alternative-text', alternatives[selected].text || ''));
                fragment.appendChild(used);
            }
            var details = document.createElement('details'); details.className = 'discuss-alternatives';
            var summary = document.createElement('summary');
            summary.textContent = 'View ' + alternatives.length + ' suggestion' + (alternatives.length === 1 ? '' : 's');
            details.appendChild(summary);
            alternatives.forEach(function(alternative, index) {
                var row = elementWith('discuss-alternative');
                var label = 'Suggestion ' + String(index + 1);
                if (index === selected) label += ' · Used';
                row.appendChild(elementWith('discuss-alternative-label', label));
                row.appendChild(elementWith('discuss-alternative-text', alternative.text || ''));
                if (alternative.rationale) row.appendChild(elementWith('discuss-alternative-rationale', alternative.rationale));
                details.appendChild(row);
            });
            fragment.appendChild(details);
            return fragment;
        }

        function discussAlternativesStateSummary(task, result) {
            var count = (result.alternatives || []).length;
            var prefix = count + ' suggestion' + (count === 1 ? '' : 's');
            if (task.status === 'applied' || task.status === 'staged') return prefix + ' · applied to draft, not saved';
            if (task.status === 'saved') return prefix + ' · saved to manuscript';
            return prefix + ' · manuscript unchanged';
        }

        function openContinuityFinding(finding) {
            var target = resolveProsviewFileReference(finding.file + '#L' + String(finding.line || 1));
            if (!target) {
                renderDiscussError('This scanned file is not available in the current Proseview sidebar.');
                return;
            }
            openProsviewFileReference(target);
        }

        function setContinuityFindingDecision(task, finding, decision, button) {
            if (button) button.disabled = true;
            discussApi(
                '/api/discuss/conversations/' + encodeURIComponent(_discussConversationId)
                + '/tasks/' + encodeURIComponent(task.id) + '/findings/' + encodeURIComponent(finding.id) + '/decision',
                {decision: decision}
            ).then(function() {
                finding.decision = decision;
                renderDiscussSnapshot();
                document.getElementById('discussAnnouncement').textContent = decision === 'intentional'
                    ? 'Reference marked intentional' : 'Continuity decision updated';
                scheduleDiscussSnapshot();
            }).catch(function(error) { if (button) button.disabled = false; renderDiscussError(error.message); });
        }

        function reviewContinuityFinding(task, finding, button) {
            if (button) button.disabled = true;
            discussApi(
                '/api/discuss/conversations/' + encodeURIComponent(_discussConversationId)
                + '/tasks/' + encodeURIComponent(task.id) + '/findings/' + encodeURIComponent(finding.id) + '/proposal',
                {client_id: (typeof aiClientId === 'function' ? aiClientId() : null)}
            ).then(function(data) {
                if (data.proposal && typeof aiFocusProposal === 'function') aiFocusProposal(data.proposal, true);
                document.getElementById('discussAnnouncement').textContent = 'Proposed edit opened for review. The manuscript is unchanged.';
                scheduleDiscussSnapshot();
            }).catch(function(error) { if (button) button.disabled = false; renderDiscussError(error.message); });
        }

        function renderContinuityReport(task, result) {
            var fragment = document.createDocumentFragment();
            fragment.appendChild(elementWith('discuss-task-summary', result.summary || 'Continuity scan complete.'));
            var scope = task.scope || {};
            var scopeCopy = String(scope.files_scanned || 0) + ' files · ' + Math.ceil(Number(scope.bytes_scanned || 0) / 1024) + ' KB';
            fragment.appendChild(elementWith('discuss-refactor-scope', '✓ Read-only scan complete · ' + scopeCopy + ' · no manuscript files changed'));
            if (Number(scope.files_omitted || 0) > 0) {
                fragment.appendChild(elementWith(
                    'discuss-queue',
                    discussAgentLabel() + ' input limit · scanned ' + String(scope.files_scanned || 0)
                    + ' of ' + String(scope.files_available || 0) + ' configured files; '
                    + String(scope.files_omitted) + ' files were omitted. Narrow repo_tab.folders for a complete scan.'
                ));
            }
            var scopeDetails = document.createElement('details'); scopeDetails.className = 'discuss-refactor-scope-details';
            var scopeSummary = document.createElement('summary'); scopeSummary.textContent = Number(scope.files_omitted || 0) > 0 ? 'Configured folders' : 'Scanned folders'; scopeDetails.appendChild(scopeSummary);
            var scopeList = document.createElement('ul');
            (scope.roots || []).forEach(function(root) { var item = document.createElement('li'); item.textContent = root; scopeList.appendChild(item); });
            scopeDetails.appendChild(scopeList); fragment.appendChild(scopeDetails);
            var groups = [
                ['direct', 'Direct contradictions'],
                ['judgment', 'Needs your judgment'],
                ['intentional', 'Likely intentional']
            ];
            var findings = result.findings || [];
            if (!findings.length) {
                fragment.appendChild(elementWith('discuss-refactor-clear', task.verify_of
                    ? 'No unexplained continuity findings remain in the scanned scope.'
                    : 'No supported continuity findings were found in the scanned scope.'));
            }
            groups.forEach(function(group) {
                var rows = findings.filter(function(finding) { return finding.category === group[0]; });
                if (!rows.length) return;
                var section = document.createElement('section'); section.className = 'discuss-refactor-group';
                var heading = document.createElement('h4'); heading.textContent = group[1] + ' · ' + String(rows.length); section.appendChild(heading);
                rows.forEach(function(finding) {
                    var row = elementWith('discuss-refactor-finding'); row.dataset.decision = finding.decision || 'open';
                    var source = document.createElement('button'); source.type = 'button'; source.className = 'discuss-refactor-source';
                    source.textContent = finding.file + '#L' + finding.line; source.onclick = function() { openContinuityFinding(finding); };
                    row.appendChild(source);
                    var quote = document.createElement('q'); quote.textContent = finding.quote || ''; row.appendChild(quote);
                    row.appendChild(elementWith('discuss-finding-detail', finding.explanation || ''));
                    if (finding.decision && finding.decision !== 'open') {
                        row.appendChild(elementWith('discuss-refactor-decision', 'Decision · ' + String(finding.decision).replace(/_/g, ' ')));
                    }
                    var actions = elementWith('discuss-refactor-finding-actions');
                    if (finding.replacement && finding.proposal_eligible && finding.category !== 'intentional') {
                        var review = document.createElement('button'); review.type = 'button'; review.className = 'discuss-primary'; review.textContent = 'Review proposed edit';
                        review.onclick = function() { reviewContinuityFinding(task, finding, review); }; actions.appendChild(review);
                    }
                    var intentional = document.createElement('button'); intentional.type = 'button'; intentional.className = 'discuss-secondary';
                    intentional.textContent = finding.decision === 'intentional' ? 'Mark unresolved' : 'Mark intentional';
                    intentional.onclick = function() {
                        setContinuityFindingDecision(task, finding, finding.decision === 'intentional' ? 'open' : 'intentional', intentional);
                    };
                    actions.appendChild(intentional); row.appendChild(actions); section.appendChild(row);
                });
                fragment.appendChild(section);
            });
            if (findings.length >= Number(scope.finding_limit || 50)) {
                fragment.appendChild(elementWith('discuss-error', 'The finding limit was reached; this report may not include every consequence.'));
            }
            if (task.action_id !== 'verify_refactor') {
                var verify = document.createElement('button'); verify.type = 'button'; verify.className = 'discuss-secondary discuss-refactor-verify';
                verify.textContent = 'Verify after edits'; verify.onclick = function() { runDiscussRepositoryAction('verify_refactor', task.id); };
                fragment.appendChild(verify);
            }
            return fragment;
        }

        function renderDiscussTask(task, previousAttempts) {
            var card = elementWith('discuss-task'); card.dataset.taskId = task.id;
            var heading = document.createElement('div'); heading.className = 'discuss-task-heading';
            var title = document.createElement('strong'); title.textContent = task.label || selectionActionLabel(task.action_id);
            var status = document.createElement('span'); status.className = 'discuss-task-status status-' + task.status; status.textContent = discussTaskStatusLabel(task.status);
            heading.appendChild(title); heading.appendChild(status); card.appendChild(heading);
            var target = task.target || {};
            if (task.kind === 'continuity_report') {
                card.appendChild(elementWith('discuss-task-selection', task.change_request || task.instruction || 'Repository continuity scan'));
            } else {
                var preview = elementWith('discuss-task-selection', '“' + String(target.selection || '').slice(0, 120) + (String(target.selection || '').length > 120 ? '…' : '') + '”');
                card.appendChild(preview);
            }
            previousAttempts = previousAttempts || [];
            if (previousAttempts.length) {
                card.appendChild(elementWith('discuss-task-meta', 'Attempt ' + String(task.attempt || previousAttempts.length + 1)));
            }
            if (task.restored) {
                var restoredLabel = task.status === 'restored'
                    ? 'Historical result · reselect the passage to use it safely'
                    : 'Restored from ' + discussAgentLabel() + ' history';
                card.appendChild(elementWith('discuss-task-meta', restoredLabel));
            }
            if (task.skill && task.skill.name) card.appendChild(elementWith('discuss-task-meta', 'Skill · ' + task.skill.name));
            if (task.error) card.appendChild(elementWith('discuss-error', task.error));
            if (previousAttempts.length) {
                var attempts = document.createElement('details'); attempts.className = 'discuss-attempts';
                var attemptsSummary = document.createElement('summary');
                attemptsSummary.textContent = previousAttempts.length + ' previous attempt' + (previousAttempts.length === 1 ? '' : 's');
                attempts.appendChild(attemptsSummary);
                var attemptsList = document.createElement('ul');
                previousAttempts.forEach(function(previous) {
                    var attempt = document.createElement('li');
                    attempt.textContent = 'Attempt ' + String(previous.attempt || 1) + ' · ' + String(previous.status || 'unknown');
                    attemptsList.appendChild(attempt);
                });
                attempts.appendChild(attemptsList); card.appendChild(attempts);
            }
            var result = task.result || {};
            if (result.kind === 'continuity_report') {
                card.appendChild(renderContinuityReport(task, result));
            } else if (result.kind === 'critique') {
                var list = document.createElement('ol'); list.className = 'discuss-findings';
                (result.findings || []).forEach(function(finding) {
                    var item = document.createElement('li');
                    var observation = document.createElement('strong'); observation.textContent = finding.observation; item.appendChild(observation);
                    var evidence = document.createElement('q'); evidence.textContent = finding.evidence; item.appendChild(evidence);
                    item.appendChild(elementWith('discuss-finding-detail', finding.why_it_matters));
                    item.appendChild(elementWith('discuss-finding-next', 'Next: ' + finding.next_step));
                    list.appendChild(item);
                });
                card.appendChild(list);
                var propose = document.createElement('button'); propose.type = 'button'; propose.className = 'discuss-secondary'; propose.textContent = 'Propose a revision';
                propose.onclick = function() {
                    _discussSelection = target.selection || '';
                    _discussSelectionRange = target.range || null;
                    _discussLiveDocument = typeof currentSceneLiveDocumentSnapshot === 'function' ? currentSceneLiveDocumentSnapshot() : null;
                    _discussPendingAction = 'rephrase';
                    _discussRetryOfTaskId = null;
                    var input = document.getElementById('discussInput'); input.value = 'Address the critique while preserving the passage’s facts, point of view, and tense.';
                    renderDiscussContext(); renderDiscussTaskMode(); saveDiscussDraft(); input.focus();
                };
                card.appendChild(propose);
            } else if (result.kind === 'alternatives') {
                card.appendChild(elementWith('discuss-task-summary', result.summary || 'Rewrite alternatives are ready.'));
                card.appendChild(elementWith('discuss-task-meta', discussAlternativesStateSummary(task, result)));
                card.appendChild(renderDiscussAlternatives(task, result));
                if ((task.status === 'ready' || task.status === 'reviewing') && task.reviewable !== false) {
                    var review = document.createElement('button'); review.type = 'button'; review.className = 'discuss-primary'; review.textContent = 'Review changes';
                    review.onclick = function() { reviewDiscussTask(task, review); }; card.appendChild(review);
                }
            }
            if (task.status === 'failed' || task.status === 'cancelled' || task.status === 'stale') {
                var retry = document.createElement('button'); retry.type = 'button'; retry.className = 'discuss-secondary'; retry.textContent = 'Try again';
                retry.onclick = function() {
                    _discussSelection = target.selection || '';
                    _discussSelectionRange = target.range || null;
                    _discussLiveDocument = typeof currentSceneLiveDocumentSnapshot === 'function' ? currentSceneLiveDocumentSnapshot() : null;
                    _discussPendingAction = task.action_id;
                    _discussRetryOfTaskId = task.id;
                    var input = document.getElementById('discussInput');
                    input.value = task.instruction || '';
                    renderDiscussContext(); renderDiscussTaskMode(); saveDiscussDraft();
                    if (task.action_id === 'custom_rewrite' || task.instruction) {
                        input.focus();
                        document.getElementById('discussAnnouncement').textContent = 'Review the restored instruction, then run the action again';
                    } else runDiscussSelectionAction(task.action_id, target.selection || '', target.range || null, _discussLiveDocument, 0, task.id);
                };
                card.appendChild(retry);
            }
            return card;
        }

        function reviewDiscussTask(task, button) {
            if (button) button.disabled = true;
            var opened = false;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/tasks/' + encodeURIComponent(task.id) + '/proposal', {
                client_id: (typeof aiClientId === 'function' ? aiClientId() : null)
            }).then(function(data) {
                opened = true;
                if (data.proposal && typeof aiFocusProposal === 'function') aiFocusProposal(data.proposal, true);
                document.getElementById('discussAnnouncement').textContent = 'Rewrite ready for review. The manuscript is unchanged.';
                scheduleDiscussSnapshot();
            }).catch(function(error) {
                renderDiscussError(error.message);
                scheduleDiscussSnapshot();
            }).finally(function() { if (!opened && button) button.disabled = false; });
        }

        function autoReviewDiscussTask(taskId) {
            var key = String(_discussConversationId || '') + ':' + String(taskId || '');
            if (!taskId || _discussAutoReviewedTasks[key]) return;
            _discussAutoReviewedTasks[key] = true;
            reviewDiscussTask({id: taskId}, null);
        }

        function downloadDiscussHistory(data, title) {
            data.exported_at = new Date().toISOString();
            var blob = new Blob([JSON.stringify(data, null, 2) + '\n'], {type: 'application/json'});
            var url = URL.createObjectURL(blob); var link = document.createElement('a'); link.href = url;
            var slug = String(title || 'conversation').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
            link.download = 'prosview-' + (slug || 'conversation') + '.json'; link.click();
            setTimeout(function() { URL.revokeObjectURL(url); }, 0);
            document.getElementById('discussAnnouncement').textContent = 'Conversation exported locally';
        }

        function historyActionButton(label, handler) {
            var button = document.createElement('button');
            button.type = 'button'; button.textContent = label; button.onclick = handler;
            return button;
        }

        function renderDiscussHistoryRows(rows) {
            var list = document.getElementById('discussHistoryList');
            var status = document.getElementById('discussHistoryStatus');
            list.replaceChildren();
            if (!rows.length) {
                status.textContent = 'No saved conversations for this document yet.'; status.hidden = false;
                return;
            }
            status.hidden = true;
            rows.forEach(function(item) {
                var row = elementWith('discuss-history-row');
                var copy = elementWith('discuss-history-copy');
                var title = document.createElement('strong'); title.textContent = item.title || 'Previous conversation'; copy.appendChild(title);
                if (item.preview) { var preview = document.createElement('span'); preview.textContent = item.preview; copy.appendChild(preview); }
                var meta = document.createElement('span');
                var stamp = item.updated_at ? new Date(item.updated_at * 1000).toLocaleString() : '';
                meta.textContent = (item.current ? 'Current conversation' : 'Saved conversation') + (stamp ? ' · ' + stamp : ''); copy.appendChild(meta);
                row.appendChild(copy);

                var actions = elementWith('discuss-history-actions');
                var openButton = historyActionButton(item.current ? 'Current' : 'Open', function() {
                    openButton.disabled = true;
                    discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/history/' + encodeURIComponent(item.thread_id) + '/open', {})
                        .then(function(data) {
                            _discussSnapshot = data.snapshot; renderDiscussSnapshot();
                            document.getElementById('discussHistoryDialog').close('opened');
                            document.getElementById('discussAnnouncement').textContent = 'Conversation opened';
                            document.getElementById('discussInput').focus();
                        })
                        .catch(function(error) { openButton.disabled = false; status.textContent = error.message; status.hidden = false; });
                });
                var workInProgress = !!(_discussSnapshot && (
                    _discussSnapshot.active_request_id || _discussSnapshot.active_turn_id || (_discussSnapshot.queue || []).length
                ));
                openButton.disabled = !!item.current || workInProgress; actions.appendChild(openButton);
                var more = document.createElement('details');
                var summary = document.createElement('summary'); summary.textContent = 'More'; more.appendChild(summary);
                var menu = elementWith('discuss-history-menu');
                var renameForm = elementWith('discuss-history-rename'); renameForm.hidden = true;
                var renameLabel = document.createElement('label'); renameLabel.className = 'sr-only'; renameLabel.textContent = 'Conversation title';
                var renameInput = document.createElement('input'); renameInput.type = 'text'; renameInput.maxLength = 200; renameInput.value = item.title || '';
                renameLabel.appendChild(renameInput); renameForm.appendChild(renameLabel);
                menu.appendChild(historyActionButton('Rename', function() { more.open = false; renameForm.hidden = false; renameInput.focus(); renameInput.select(); }));
                menu.appendChild(historyActionButton('Export JSON', function() {
                    discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/history/' + encodeURIComponent(item.thread_id) + '/export', {})
                        .then(function(data) { downloadDiscussHistory(data.export, item.title); })
                        .catch(function(error) { status.textContent = error.message; status.hidden = false; });
                }));
                var removeButton = historyActionButton('Remove from history', function() {
                    if (!window.confirm('Remove this conversation from Prosview history? It will remain in Codex history.')) return;
                    removeButton.disabled = true;
                    discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/history/' + encodeURIComponent(item.thread_id) + '/remove', {})
                        .then(loadDiscussHistory)
                        .then(function() { document.getElementById('discussAnnouncement').textContent = 'Conversation removed from Prosview history'; })
                        .catch(function(error) { removeButton.disabled = false; status.textContent = error.message; status.hidden = false; });
                });
                removeButton.disabled = !!item.current; menu.appendChild(removeButton);
                more.appendChild(menu); actions.appendChild(more); row.appendChild(actions);
                renameForm.appendChild(historyActionButton('Save', function() {
                    var clean = renameInput.value.trim(); if (!clean) { renameInput.focus(); return; }
                    discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/history/' + encodeURIComponent(item.thread_id) + '/rename', {title: clean})
                        .then(loadDiscussHistory)
                        .catch(function(error) { status.textContent = error.message; status.hidden = false; });
                }));
                renameForm.appendChild(historyActionButton('Cancel', function() { renameForm.hidden = true; summary.focus(); }));
                row.appendChild(renameForm); list.appendChild(row);
            });
        }

        function loadDiscussHistory() {
            var status = document.getElementById('discussHistoryStatus');
            status.textContent = 'Loading conversations…'; status.hidden = false;
            return discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/history/list', {})
                .then(function(data) { renderDiscussHistoryRows(data.conversations || []); })
                .catch(function(error) { status.textContent = error.message; status.hidden = false; });
        }

        function openDiscussHistoryDialog() {
            if (!_discussConversationId) return;
            var dialog = document.getElementById('discussHistoryDialog');
            document.getElementById('discussHistoryList').replaceChildren();
            dialog.showModal(); loadDiscussHistory(); document.getElementById('discussHistoryClose').focus();
        }

        function clearDiscussHistory() {
            if (!_discussConversationId) return;
            if (!window.confirm('Clear assistance results for this document? This cannot be undone.')) return;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/tasks/clear', {})
                .then(function() { scheduleDiscussSnapshot(); document.getElementById('discussAnnouncement').textContent = 'Assistance results cleared'; })
                .catch(function(error) { renderDiscussError(error.message); });
        }

        function renderDiscussApproval(approval) {
            var card = elementWith('discuss-approval'); card.dataset.approvalId = approval.request_id;
            var title = document.createElement('h3'); title.textContent = approval.status === 'pending' ? 'Approval required' : 'Approval ' + approval.status; card.appendChild(title);
            card.appendChild(document.createTextNode(approval.reason || approval.kind || 'Codex requested an action.'));
            if (approval.command) { var code = document.createElement('code'); code.textContent = approval.command; card.appendChild(code); }
            if (approval.grant_root) { var root = document.createElement('code'); root.textContent = 'Write access: ' + approval.grant_root; card.appendChild(root); }
            if (approval.network) { var network = document.createElement('code'); network.textContent = 'Network: ' + JSON.stringify(approval.network); card.appendChild(network); }
            if (approval.permissions) { var permissions = document.createElement('code'); permissions.textContent = 'Permissions: ' + JSON.stringify(approval.permissions); card.appendChild(permissions); }
            if (approval.status === 'pending') {
                var actions = elementWith('discuss-approval-actions');
                var options = [
                    ['accept', 'Accept once'], ['accept_for_session', 'Accept for session ⚠'], ['decline', 'Decline'], ['cancel', 'Cancel']
                ];
                options.forEach(function(option) {
                    var wire = option[0] === 'accept_for_session' ? 'acceptForSession' : option[0];
                    if ((approval.available_decisions || []).indexOf(wire) < 0) return;
                    var button = document.createElement('button'); button.type = 'button'; button.textContent = option[1];
                    if (option[0] === 'accept_for_session') button.title = 'Allows matching requests until this Codex session ends';
                    button.onclick = function() { resolveDiscussApproval(approval.request_id, option[0], button, approval.permissions); };
                    actions.appendChild(button);
                });
                card.appendChild(actions);
            }
            return card;
        }

        function resolveDiscussApproval(requestId, decision, button, permissions) {
            button.disabled = true;
            var payload = {decision: decision};
            if (permissions && (decision === 'accept' || decision === 'accept_for_session')) payload.permissions = permissions;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/approvals/' + encodeURIComponent(requestId), payload)
                .then(function() { document.getElementById('discussAnnouncement').textContent = 'Approval ' + decision.replace('_', ' '); scheduleDiscussSnapshot(); })
                .catch(function(error) { renderDiscussError(error.message); scheduleDiscussSnapshot(); })
                .finally(function() { document.getElementById('discussInput').focus(); });
        }

        function appendDiscussLocalError(log) {
            if (!_discussLocalError) return;
            var node = elementWith('discuss-error discuss-local-error');
            node.appendChild(elementWith('discuss-local-error-message', _discussLocalError));
            if (_discussLocalErrorReload) {
                var reload = document.createElement('button');
                reload.type = 'button'; reload.className = 'discuss-secondary'; reload.textContent = 'Reload page';
                reload.onclick = function() { saveDiscussDraft(); location.reload(); };
                node.appendChild(reload);
            }
            log.appendChild(node);
            return node;
        }

        function renderDiscussError(message, options) {
            options = options || {};
            _discussLocalError = String(message || 'Something went wrong');
            _discussLocalErrorKind = String(options.kind || (
                _discussLocalError.indexOf('Proseview server is not responding.') === 0 ? 'transport' : 'request'
            ));
            _discussLocalErrorReload = !!options.reload;
            var log = document.getElementById('discussLog');
            var existing = log.querySelector('.discuss-local-error');
            if (existing) existing.remove();
            var node = appendDiscussLocalError(log);
            if (node) node.scrollIntoView({block: 'nearest'});
        }

        function clearDiscussError() {
            _discussLocalError = '';
            _discussLocalErrorKind = '';
            _discussLocalErrorReload = false;
            var existing = document.querySelector('#discussLog .discuss-local-error');
            if (existing) existing.remove();
        }

        function clearDiscussTransportError() {
            if (_discussLocalErrorKind === 'transport') clearDiscussError();
        }

        function discussAfterActivity(wasAtBottom) {
            var log = document.getElementById('discussLog');
            if (wasAtBottom) requestAnimationFrame(function() { log.scrollTop = log.scrollHeight; });
            else document.getElementById('discussNewActivity').hidden = false;
        }

        function discussScrollToEnd() {
            var log = document.getElementById('discussLog'); log.scrollTop = log.scrollHeight;
            document.getElementById('discussNewActivity').hidden = true;
        }

        function renderDiscussContext() {
            var context = document.getElementById('discussContext'); context.replaceChildren();
            var doc = discussDocument();
            if (doc && _discussIncludeCurrentDocument) {
                var current = elementWith('discuss-chip discuss-chip-current', doc.path);
                current.title = 'Current document';
                var removeCurrent = document.createElement('button');
                removeCurrent.type = 'button'; removeCurrent.textContent = '×';
                removeCurrent.setAttribute('aria-label', 'Remove current document ' + doc.path);
                removeCurrent.onclick = function() {
                    _discussIncludeCurrentDocument = false;
                    renderDiscussContext();
                    document.getElementById('discussAnnouncement').textContent = 'Current document removed from context';
                };
                current.appendChild(removeCurrent); context.appendChild(current);
            }
            _discussAttachments.forEach(function(attachment, index) {
                var chip = elementWith('discuss-chip', attachment.path);
                var remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Remove ' + attachment.path);
                remove.onclick = function() { _discussAttachments.splice(index, 1); renderDiscussContext(); }; chip.appendChild(remove); context.appendChild(chip);
            });
            var selection = document.getElementById('discussSelectionChip');
            selection.hidden = !_discussSelection;
            selection.replaceChildren();
            if (_discussSelection) {
                var words = _discussSelection.trim().split(/\s+/).filter(Boolean).length;
                selection.appendChild(document.createTextNode('Selection · ' + words + ' words · “' + _discussSelection.slice(0, 72) + (_discussSelection.length > 72 ? '…' : '') + '”'));
                var removeSelection = document.createElement('button');
                removeSelection.type = 'button'; removeSelection.textContent = '×';
                removeSelection.setAttribute('aria-label', 'Remove selected text from Codex context');
                removeSelection.onclick = function() {
                    _discussSelection = ''; _discussSelectionRange = null; _discussLiveDocument = null; _discussPendingAction = null; _discussRetryOfTaskId = null; renderDiscussContext(); renderDiscussTaskMode();
                    document.getElementById('discussAnnouncement').textContent = 'Selection removed from context';
                };
                selection.appendChild(removeSelection);
            }
        }

        function selectionActionLabel(actionId) {
            return ({
                rephrase: 'Rephrase', tighten: 'Tighten', clarify: 'Clarify', sensory_detail: 'Add sensory detail',
                show_moment: 'Show the moment', custom_rewrite: 'Custom rewrite', quick_critique: 'Quick critique', voice_character: 'Voice and character',
                pacing_tension: 'Pacing and tension', clarity_flow: 'Clarity and flow', continuity: 'Continuity check',
                canon_refactor: 'Trace a canon change', scene_continuity: "Check this scene's continuity",
                verify_refactor: 'Verify a canon change'
            })[actionId] || 'Selection action';
        }

        function normalizedDiscussInstructions(rows, limit) {
            if (!Array.isArray(rows)) return [];
            var normalized = [];
            rows.forEach(function(row) {
                if (typeof row !== 'string') return;
                var value = row.trim();
                if (value.length > 32768) return;
                if (value && normalized.indexOf(value) < 0) normalized.push(value);
            });
            return normalized.slice(0, limit);
        }

        function recentDiscussInstructions() {
            try { return normalizedDiscussInstructions(JSON.parse(localStorage.getItem('proseview-codex-recent-instructions') || '[]'), 8); }
            catch(e) { return []; }
        }

        function rememberDiscussInstruction(value) {
            value = String(value || '').trim();
            if (!value) return;
            var rows = recentDiscussInstructions().filter(function(row) { return row !== value; });
            rows.unshift(value);
            try { localStorage.setItem('proseview-codex-recent-instructions', JSON.stringify(rows.slice(0, 8))); } catch(e) {}
        }

        function favoriteDiscussInstructions() {
            try { return normalizedDiscussInstructions(JSON.parse(localStorage.getItem('proseview-codex-favorite-instructions') || '[]'), 12); }
            catch(e) { return []; }
        }

        function configuredDiscussInstructions() {
            return normalizedDiscussInstructions(
                typeof discussSelectionPresets === 'undefined' ? [] : discussSelectionPresets,
                12
            );
        }

        function presetDiscussInstructions() {
            return normalizedDiscussInstructions(
                favoriteDiscussInstructions().concat(configuredDiscussInstructions()),
                24
            );
        }

        function toggleDiscussInstructionFavorite(value, reopenMenu) {
            var rows = favoriteDiscussInstructions(); var index = rows.indexOf(value);
            if (index >= 0) rows.splice(index, 1); else rows.unshift(value);
            try { localStorage.setItem('proseview-codex-favorite-instructions', JSON.stringify(rows.slice(0, 12))); } catch(e) {}
            renderDiscussTaskMode();
            if (reopenMenu) {
                var details = document.querySelector('#discussTaskMode .discuss-presets-more');
                if (details) {
                    details.open = true;
                    var label = (index >= 0 ? 'Add to favorites: ' : 'Remove from favorites: ') + value;
                    Array.prototype.some.call(details.querySelectorAll('.discuss-favorite'), function(button) {
                        if (button.getAttribute('aria-label') !== label) return false;
                        button.focus();
                        return true;
                    });
                }
            }
        }

        function chooseDiscussInstruction(value, details) {
            document.getElementById('discussInput').value = value;
            saveDiscussDraft();
            if (details) details.open = false;
            document.getElementById('discussInput').focus();
        }

        function appendDiscussPresetMenuRow(node, value, favorite, details) {
            var wrap = elementWith('discuss-preset-menu-row');
            var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-preset-menu-choice'; button.textContent = value;
            button.title = value;
            button.onclick = function() { chooseDiscussInstruction(value, details); };
            var star = document.createElement('button'); star.type = 'button'; star.className = 'discuss-favorite'; star.textContent = favorite ? '★' : '☆';
            star.setAttribute('aria-label', (favorite ? 'Remove from favorites: ' : 'Add to favorites: ') + value);
            star.onclick = function() { toggleDiscussInstructionFavorite(value, true); };
            wrap.appendChild(button); wrap.appendChild(star); node.appendChild(wrap);
        }

        function appendDiscussPresetsMenu(node, presets, recents) {
            var details = document.createElement('details'); details.className = 'discuss-presets-more';
            var summary = document.createElement('summary'); summary.textContent = presets.length ? 'More…' : 'Add from recent…';
            summary.setAttribute('role', 'button');
            summary.setAttribute('aria-label', 'More presets and recent instructions');
            details.appendChild(summary);
            var popover = elementWith('discuss-presets-popover'); popover.id = 'discussPresetsPopover';
            var favorites = favoriteDiscussInstructions();
            if (presets.length) {
                var presetHeading = document.createElement('strong'); presetHeading.textContent = 'Presets'; popover.appendChild(presetHeading);
                presets.forEach(function(value) {
                    appendDiscussPresetMenuRow(popover, value, favorites.indexOf(value) >= 0, details);
                });
            }
            if (recents.length) {
                var recentHeading = document.createElement('strong'); recentHeading.textContent = 'Recent'; popover.appendChild(recentHeading);
                recents.forEach(function(value) { appendDiscussPresetMenuRow(popover, value, false, details); });
            }
            details.appendChild(popover); node.appendChild(details);
        }

        function renderDiscussTaskMode() {
            var node = document.getElementById('discussTaskMode');
            if (!node) return;
            node.replaceChildren();
            if (_discussRepositoryAction) {
                node.hidden = false;
                var repositoryTitle = document.createElement('strong');
                repositoryTitle.textContent = selectionActionLabel(_discussRepositoryAction); node.appendChild(repositoryTitle);
                var repositoryHelp = document.createElement('span');
                repositoryHelp.textContent = 'Read-only scan · configured manuscript and repository folders'; node.appendChild(repositoryHelp);
                var changeAction = document.createElement('button');
                changeAction.type = 'button'; changeAction.className = 'discuss-secondary'; changeAction.textContent = 'Change action';
                changeAction.onclick = cancelDiscussRepositoryAction; node.appendChild(changeAction);
                document.getElementById('discussInput').placeholder = _discussRepositoryAction === 'canon_refactor'
                    ? 'Describe the canon change, including the old and new fact…'
                    : 'Optional: name the continuity concern to focus on…';
                document.getElementById('discussSend').textContent = 'Scan';
                return;
            }
            if (_discussPendingAction) {
                node.hidden = false;
                var title = document.createElement('strong'); title.textContent = selectionActionLabel(_discussPendingAction) + ' selection'; node.appendChild(title);
                var help = document.createElement('span'); help.textContent = 'Optional constraint'; node.appendChild(help);
                document.getElementById('discussInput').placeholder = 'Add a constraint, or run as shown…';
                document.getElementById('discussSend').textContent = 'Run';
                return;
            }
            document.getElementById('discussSend').textContent = 'Send';
            var presets = presetDiscussInstructions();
            var recents = recentDiscussInstructions().filter(function(value) { return presets.indexOf(value) < 0; });
            document.getElementById('discussInput').placeholder = _discussSelection
                ? 'Ask anything about this selection…'
                : 'Ask about this document…';
            node.hidden = !(_discussSelection && (presets.length || recents.length));
            if (!node.hidden) {
                var label = document.createElement('strong'); label.textContent = 'Presets'; node.appendChild(label);
                var inline = elementWith('discuss-presets-inline');
                presets.slice(0, 3).forEach(function(value) {
                    var button = document.createElement('button');
                    button.type = 'button'; button.className = 'discuss-preset-inline'; button.textContent = value; button.title = value;
                    button.onclick = function() { chooseDiscussInstruction(value); };
                    inline.appendChild(button);
                });
                if (presets.length) node.appendChild(inline);
                if (presets.length > 3 || recents.length || favoriteDiscussInstructions().length) {
                    appendDiscussPresetsMenu(node, presets, recents);
                }
            }
        }

        function loadDiscussSkills(forceReload) {
            var picker = document.getElementById('discussSkillsPicker');
            picker.hidden = false; picker.textContent = 'Loading Codex skills…';
            discussApi('/api/discuss/skills', {force_reload: !!forceReload}).then(function(data) {
                _discussSkills = data.skills || []; renderDiscussSkills();
            }).catch(function(error) { picker.textContent = 'Skills unavailable: ' + error.message; });
        }

        function renderDiscussSkills() {
            var picker = document.getElementById('discussSkillsPicker'); picker.replaceChildren(); picker.hidden = false;
            var title = document.createElement('strong'); title.textContent = 'Run a skill'; picker.appendChild(title);
            var search = document.createElement('input'); search.type = 'search'; search.className = 'discuss-skill-search'; search.placeholder = 'Search skills'; search.setAttribute('aria-label', 'Search Codex skills'); picker.appendChild(search);
            var results = elementWith('discuss-skill-results'); picker.appendChild(results);
            function showSkills() {
                var query = search.value.trim().toLowerCase(); results.replaceChildren();
                var matches = _discussSkills.filter(function(skill) { return !query || (skill.name + ' ' + skill.display_name + ' ' + skill.description).toLowerCase().includes(query); });
                if (!matches.length) results.appendChild(document.createTextNode(_discussSkills.length ? 'No matching skills.' : 'No enabled Codex skills were found.'));
                matches.forEach(function(skill) {
                    var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-skill';
                    var name = document.createElement('strong'); name.textContent = skill.display_name || skill.name;
                    var description = document.createElement('span'); description.textContent = skill.description || 'Codex skill';
                    var metadata = document.createElement('small'); metadata.textContent = 'Conversation / unknown output · ' + (skill.scope || 'Codex');
                    button.appendChild(name); button.appendChild(description); button.appendChild(metadata);
                    if (skill.dependencies && Object.keys(skill.dependencies).length) {
                        var dependency = document.createElement('small'); dependency.textContent = 'Dependencies: ' + JSON.stringify(skill.dependencies); button.appendChild(dependency);
                    }
                    button.onclick = function() {
                        _discussSelectedSkill = {name: skill.name, path: skill.path};
                        picker.hidden = true;
                        var input = document.getElementById('discussInput');
                        input.placeholder = 'Tell ' + (skill.display_name || skill.name) + ' what to do with this selection…'; input.focus();
                        document.getElementById('discussAnnouncement').textContent = (skill.display_name || skill.name) + ' selected';
                    };
                    results.appendChild(button);
                });
            }
            search.oninput = showSkills; showSkills();
            var cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'discuss-secondary'; cancel.textContent = 'Cancel';
            cancel.onclick = function() { picker.hidden = true; document.getElementById('discussInput').focus(); };
            picker.appendChild(cancel); search.focus();
        }

        function discussMentionAtCaret() {
            var input = document.getElementById('discussInput');
            if (input.selectionStart !== input.selectionEnd) return null;
            var before = input.value.slice(0, input.selectionStart);
            var match = before.match(/(^|\s)@([^\s@]*)$/);
            if (!match) return null;
            return {start: before.length - match[2].length - 1, end: input.selectionStart, query: match[2]};
        }

        function discussContextCandidates() {
            if (_discussContextCandidateCache) return _discussContextCandidateCache;
            var candidates = [];
            function visit(nodes) {
                (nodes || []).forEach(function(node) {
                    if (!node.path) return;
                    var kind = node.is_file ? 'file' : 'folder';
                    if ((!node.is_file && node.attachable) || (node.is_file && node.attachable)) {
                        candidates.push({kind: kind, path: node.path, name: node.name || node.path});
                    }
                    if (!node.is_file) visit(node.children);
                });
            }
            visit(repositoryTree);
            _discussContextCandidateCache = candidates;
            return _discussContextCandidateCache;
        }

        function setDiscussContextExpanded(expanded) {
            document.getElementById('discussContextButton').setAttribute('aria-expanded', String(expanded));
            document.getElementById('discussInput').setAttribute('aria-expanded', String(expanded));
        }

        function positionDiscussContextPicker() {
            var picker = document.getElementById('discussContextPicker');
            if (!picker || picker.hidden) return;
            var composer = document.getElementById('discussComposerArea');
            var options = document.getElementById('discussContextOptions');
            var zoom = parseFloat(getComputedStyle(document.body).zoom) || 1;
            var availableRenderedHeight = Math.max(96, composer.getBoundingClientRect().top - 8);
            var maxLogicalHeight = Math.min(330, availableRenderedHeight / zoom);
            picker.style.maxHeight = maxLogicalHeight + 'px';
            options.style.maxHeight = Math.max(70, maxLogicalHeight - 42) + 'px';
        }

        function closeDiscussContextPicker() {
            var picker = document.getElementById('discussContextPicker');
            if (!picker) return;
            picker.hidden = true;
            _discussContextChoices = [];
            _discussContextActiveIndex = 0;
            _discussMentionRange = null;
            var input = document.getElementById('discussInput');
            input.removeAttribute('aria-activedescendant');
            setDiscussContextExpanded(false);
        }

        function renderDiscussContextOptions() {
            var mention = discussMentionAtCaret();
            if (!mention) { closeDiscussContextPicker(); return; }
            _discussMentionRange = mention;
            var query = mention.query.toLowerCase();
            _discussContextChoices = discussContextCandidates().filter(function(candidate) {
                if (_discussAttachments.some(function(item) { return item.kind === candidate.kind && item.path === candidate.path; })) return false;
                return !query || candidate.path.toLowerCase().includes(query) || candidate.name.toLowerCase().includes(query);
            }).slice(0, 12);
            _discussContextActiveIndex = Math.min(_discussContextActiveIndex, Math.max(0, _discussContextChoices.length - 1));
            var options = document.getElementById('discussContextOptions'); options.replaceChildren();
            if (!_discussContextChoices.length) {
                options.appendChild(elementWith('discuss-context-empty', query ? 'No matching files or folders' : 'Type to search files and folders'));
            }
            _discussContextChoices.forEach(function(choice, index) {
                var option = document.createElement('button');
                option.type = 'button'; option.className = 'discuss-context-option'; option.id = 'discussContextOption' + index;
                option.setAttribute('role', 'option'); option.setAttribute('aria-selected', String(index === _discussContextActiveIndex));
                option.dataset.path = choice.path; option.dataset.kind = choice.kind;
                var icon = elementWith('discuss-context-option-icon', choice.kind === 'file' ? '▤' : '▸'); icon.setAttribute('aria-hidden', 'true');
                option.appendChild(icon); option.appendChild(elementWith('discuss-context-option-path', choice.path));
                option.onmousedown = function(event) { event.preventDefault(); };
                option.onclick = function() { selectDiscussContextOption(index); };
                options.appendChild(option);
            });
            var picker = document.getElementById('discussContextPicker'); picker.hidden = false;
            positionDiscussContextPicker();
            setDiscussContextExpanded(true);
            updateDiscussContextActiveOption();
        }

        function updateDiscussContextActiveOption() {
            var input = document.getElementById('discussInput');
            document.querySelectorAll('#discussContextOptions [role="option"]').forEach(function(option, index) {
                option.setAttribute('aria-selected', String(index === _discussContextActiveIndex));
            });
            if (_discussContextChoices.length) {
                var active = document.getElementById('discussContextOption' + _discussContextActiveIndex);
                input.setAttribute('aria-activedescendant', active.id);
                active.scrollIntoView({block: 'nearest'});
            } else input.removeAttribute('aria-activedescendant');
        }

        function selectDiscussContextOption(index) {
            var choice = _discussContextChoices[index];
            var input = document.getElementById('discussInput');
            var mention = _discussMentionRange;
            if (!choice || !mention) return;
            if (!_discussAttachments.some(function(item) { return item.kind === choice.kind && item.path === choice.path; })) {
                _discussAttachments.push({kind: choice.kind, path: choice.path});
            }
            input.value = input.value.slice(0, mention.start) + input.value.slice(mention.end);
            input.setSelectionRange(mention.start, mention.start);
            closeDiscussContextPicker();
            renderDiscussContext();
            document.getElementById('discussAnnouncement').textContent = 'Attached ' + choice.path;
            input.focus();
        }

        function openDiscussContextPicker() {
            var input = document.getElementById('discussInput');
            input.focus();
            var mention = discussMentionAtCaret();
            if (!mention) {
                var start = input.selectionStart;
                var prefix = start > 0 && !/\s/.test(input.value.charAt(start - 1)) ? ' @' : '@';
                input.setRangeText(prefix, start, input.selectionEnd, 'end');
            }
            _discussContextActiveIndex = 0;
            renderDiscussContextOptions();
        }

        function openNewDiscussConversationDialog() {
            var button = document.getElementById('discussNewConversation');
            if (!_discussConversationId || button.disabled) return;
            var dialog = document.getElementById('discussNewConversationDialog');
            var error = document.getElementById('discussNewConversationError');
            var status = document.getElementById('discussNewConversationStatus');
            var confirm = document.getElementById('discussNewConversationConfirm');
            var cancel = document.getElementById('discussNewConversationCancel');
            error.hidden = true; error.textContent = '';
            status.hidden = true; status.textContent = '';
            dialog.setAttribute('aria-busy', 'false');
            confirm.disabled = false; confirm.textContent = 'Start new conversation';
            cancel.disabled = false;
            dialog.showModal();
            cancel.focus();
        }

        function confirmNewDiscussConversation(event) {
            event.preventDefault();
            if (!_discussConversationId) return;
            var dialog = document.getElementById('discussNewConversationDialog');
            var confirm = document.getElementById('discussNewConversationConfirm');
            var cancel = document.getElementById('discussNewConversationCancel');
            var status = document.getElementById('discussNewConversationStatus');
            var error = document.getElementById('discussNewConversationError');
            confirm.disabled = true; confirm.textContent = 'Starting…';
            cancel.disabled = true;
            dialog.setAttribute('aria-busy', 'true');
            status.hidden = true; status.textContent = '';
            error.hidden = true; error.textContent = '';
            document.getElementById('discussAnnouncement').textContent = 'Starting a new conversation';
            var slowTimer = setTimeout(function() {
                status.textContent = 'Still starting… Prosview is waiting for the local conversation reset to finish.';
                status.hidden = false;
            }, 1200);
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/new', {})
                .then(function(data) {
                    _discussSnapshot = data.snapshot;
                    _discussSelection = '';
                    _discussSelectionRange = null;
                    _discussLiveDocument = null;
                    _discussPendingAction = null;
                    _discussRepositoryAction = null;
                    _discussRetryOfTaskId = null;
                    _discussSelectedSkill = null;
                    _discussAutoRun = false;
                    _discussAttachments = [];
                    _discussIncludeCurrentDocument = true;
                    closeDiscussContextPicker();
                    renderDiscussContext();
                    renderDiscussTaskMode();
                    renderDiscussSnapshot();
                    dialog.close('confirmed');
                    document.getElementById('discussAnnouncement').textContent = 'New conversation started';
                    document.getElementById('discussInput').focus();
                })
                .catch(function(requestError) {
                    status.hidden = true; status.textContent = '';
                    error.textContent = requestError.message;
                    error.hidden = false;
                    confirm.textContent = 'Try again';
                    document.getElementById('discussAnnouncement').textContent = 'New conversation failed. ' + requestError.message;
                })
                .finally(function() {
                    clearTimeout(slowTimer);
                    dialog.setAttribute('aria-busy', 'false');
                    confirm.disabled = false;
                    cancel.disabled = false;
                    if (!error.hidden) confirm.focus();
                });
        }

        document.getElementById('discussNewConversationDialog').addEventListener('close', function() {
            if (this.returnValue !== 'confirmed') document.getElementById('discussNewConversation').focus();
        });
        document.getElementById('discussNewConversationDialog').addEventListener('cancel', function(event) {
            if (this.getAttribute('aria-busy') !== 'true') return;
            event.preventDefault();
            document.getElementById('discussAnnouncement').textContent = 'Wait for the conversation reset to finish';
        });
        document.getElementById('discussHistoryDialog').addEventListener('close', function() {
            if (this.returnValue !== 'opened') document.getElementById('discussHistory').focus();
        });

        function sendDiscussQuestion() {
            var input = document.getElementById('discussInput');
            var question = input.value.trim();
            var button = document.getElementById('discussSend');
            if (_discussOpenFailed) { openDiscuss(_discussReturnFocus); return; }
            if (_discussPendingAction) { runDiscussSelectionAction(); return; }
            if (_discussRepositoryAction) { runDiscussRepositoryAction(); return; }
            if (!question || !_discussConversationId || button.disabled) return;
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            button.disabled = true;
            button.textContent = 'Sending…';
            document.getElementById('discussAnnouncement').textContent = 'Sending question…';
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: question,
                selection: _discussSelection,
                selection_range: _discussSelectionRange,
                live_document: _discussLiveDocument,
                attachments: _discussAttachments,
                include_current_document: _discussIncludeCurrentDocument,
                skill: _discussSelectedSkill
            }).then(function() {
                rememberDiscussInstruction(question); input.value = ''; saveDiscussDraft(); _discussSelectedSkill = null;
                closeDiscussContextPicker(); renderDiscussContext(); renderDiscussTaskMode(); scheduleDiscussSnapshot();
                document.getElementById('discussAnnouncement').textContent = _discussSelection
                    ? 'Question queued. Selection remains attached for follow-up questions.'
                    : 'Question queued';
            }).catch(function(error) {
                renderDiscussError(error.message, {kind: error.name === 'NetworkError' ? 'transport' : 'request'});
                document.getElementById('discussAnnouncement').textContent = 'Question was not confirmed. ' + error.message;
            }).finally(function() {
                button.disabled = false;
                renderDiscussTaskMode();
                var active = document.activeElement;
                if (active === input || active === button || active === document.body) input.focus();
            });
        }

        function startDiscussRepositoryAction(actionId) {
            _discussRepositoryAction = actionId;
            _discussPendingAction = null;
            _discussSelectedSkill = null;
            renderDiscussTaskMode();
            renderDiscussSnapshot();
            var input = document.getElementById('discussInput');
            input.focus();
            document.getElementById('discussAnnouncement').textContent = selectionActionLabel(actionId) + ' selected';
        }

        function cancelDiscussRepositoryAction() {
            if (!_discussRepositoryAction) return;
            _discussRepositoryAction = null;
            renderDiscussTaskMode();
            renderDiscussSnapshot();
            document.getElementById('discussInput').focus();
            document.getElementById('discussAnnouncement').textContent = 'Choose a story-aware action';
        }

        function runDiscussRepositoryAction(actionOverride, verifyOfTaskId) {
            var actionId = actionOverride || _discussRepositoryAction;
            var input = document.getElementById('discussInput');
            var question = input.value.trim();
            var button = document.getElementById('discussSend');
            if (!actionId || !_discussConversationId || button.disabled) return;
            if (actionId === 'canon_refactor' && !question) {
                input.focus();
                document.getElementById('discussAnnouncement').textContent = 'Describe the old and new canon fact first';
                return;
            }
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            button.disabled = true;
            button.textContent = 'Starting…';
            document.getElementById('discussAnnouncement').textContent = 'Starting ' + selectionActionLabel(actionId).toLowerCase();
            renderDiscussSnapshot();
            document.getElementById('discussLog').setAttribute('aria-busy', 'true');
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: question,
                action_id: actionId,
                verify_of_task_id: verifyOfTaskId || ''
            }).then(function() {
                if (question) rememberDiscussInstruction(question);
                input.value = '';
                _discussRepositoryAction = null;
                saveDiscussDraft(); renderDiscussTaskMode(); scheduleDiscussSnapshot();
                document.getElementById('discussAnnouncement').textContent = selectionActionLabel(actionId) + ' queued. This scan cannot change manuscript files.';
            }).catch(function(error) {
                button.disabled = false;
                renderDiscussTaskMode();
                renderDiscussSnapshot();
                renderDiscussError(error.message);
            }).finally(function() {
                button.disabled = false;
                document.getElementById('discussLog').setAttribute('aria-busy', 'false');
                renderDiscussTaskMode();
                input.focus();
            });
        }

        function runDiscussSelectionAction(actionOverride, selectionOverride, rangeOverride, liveDocumentOverride, retryCount, retryOfOverride) {
            var input = document.getElementById('discussInput');
            var button = document.getElementById('discussSend');
            var actionId = actionOverride || _discussPendingAction;
            var selection = selectionOverride || _discussSelection;
            var selectionRange = rangeOverride || _discussSelectionRange;
            var liveDocument = liveDocumentOverride || _discussLiveDocument;
            var retryOfTaskId = retryOfOverride || _discussRetryOfTaskId;
            if (!actionId || !selection || !_discussConversationId) return;
            if (button.disabled) {
                retryCount = Number(retryCount || 0);
                if (retryCount < 100) {
                    setTimeout(function() {
                        runDiscussSelectionAction(actionId, selection, selectionRange, liveDocument, retryCount + 1, retryOfTaskId);
                    }, 50);
                }
                return;
            }
            var custom = input.value.trim();
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            _discussAutoReviewRequests[requestId] = true;
            button.disabled = true;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: '',
                selection: selection,
                selection_range: selectionRange,
                live_document: liveDocument,
                attachments: _discussAttachments,
                include_current_document: _discussIncludeCurrentDocument,
                action_id: actionId,
                custom_instruction: custom,
                skill: _discussSelectedSkill,
                retry_of_task_id: retryOfTaskId
            }).then(function() {
                if (custom) rememberDiscussInstruction(custom);
                input.value = _discussAutoRun ? _discussPreservedDraft : '';
                _discussPendingAction = null; _discussRetryOfTaskId = null; _discussSelectedSkill = null; _discussAutoRun = false; saveDiscussDraft();
                _discussSelection = ''; _discussSelectionRange = null; _discussLiveDocument = null; closeDiscussContextPicker(); renderDiscussContext(); renderDiscussTaskMode(); scheduleDiscussSnapshot();
                document.getElementById('discussAnnouncement').textContent = selectionActionLabel(actionId) + ' queued. The manuscript will not change.';
            }).catch(function(error) {
                delete _discussAutoReviewRequests[requestId];
                renderDiscussError(error.message);
            }).finally(function() {
                button.disabled = false;
                var proposalPanel = document.getElementById('aiProposalPanel');
                if (proposalPanel && !proposalPanel.hidden) proposalPanel.focus({preventScroll: true});
                else input.focus();
            });
        }

        function stopDiscussTurn() {
            if (!_discussSnapshot || !_discussSnapshot.active_turn_id) return;
            var button = document.getElementById('discussStop');
            if (button.disabled) return;
            button.disabled = true;
            button.textContent = 'Stopping…';
            document.getElementById('discussAnnouncement').textContent = 'Stopping ' + discussAgentLabel();
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/turns/' + encodeURIComponent(_discussSnapshot.active_turn_id) + '/stop', {})
                .then(scheduleDiscussSnapshot).catch(function(error) {
                    button.disabled = false;
                    button.textContent = 'Stop Codex';
                    renderDiscussError(error.message);
                });
        }

        document.getElementById('discussInput').addEventListener('keydown', function(event) {
            var pickerOpen = !document.getElementById('discussContextPicker').hidden;
            if (pickerOpen && event.key === 'ArrowDown') {
                event.preventDefault();
                if (_discussContextChoices.length) _discussContextActiveIndex = (_discussContextActiveIndex + 1) % _discussContextChoices.length;
                updateDiscussContextActiveOption();
            } else if (pickerOpen && event.key === 'ArrowUp') {
                event.preventDefault();
                if (_discussContextChoices.length) _discussContextActiveIndex = (_discussContextActiveIndex + _discussContextChoices.length - 1) % _discussContextChoices.length;
                updateDiscussContextActiveOption();
            } else if (pickerOpen && (event.key === 'Enter' || event.key === 'Tab') && !event.isComposing) {
                event.preventDefault(); selectDiscussContextOption(_discussContextActiveIndex);
            } else if (pickerOpen && event.key === 'Escape') {
                event.preventDefault(); event.stopPropagation(); closeDiscussContextPicker();
            } else if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendDiscussQuestion(); }
        });
        document.getElementById('discussInput').addEventListener('input', function() { saveDiscussDraft(); renderDiscussContextOptions(); });
        document.addEventListener('mousedown', function(event) {
            var picker = document.getElementById('discussContextPicker');
            if (picker.hidden || picker.contains(event.target) || event.target === document.getElementById('discussContextButton') || event.target === document.getElementById('discussInput')) return;
            closeDiscussContextPicker();
        });
        window.addEventListener('resize', positionDiscussContextPicker);
        if (window.visualViewport) window.visualViewport.addEventListener('resize', positionDiscussContextPicker);
        // Escape deliberately does not close the dock: it belongs to whatever
        // the writer is inside -- the composer's context picker handles its own,
        // and the dialogs are <dialog> elements that close natively. Taking it
        // for the panel stole the key from the editor underneath.
        document.getElementById('discussLog').addEventListener('scroll', function() {
            if (discussIsAtBottom(this)) document.getElementById('discussNewActivity').hidden = true;
        });
        (function initDiscussResize() {
            var handle = document.getElementById('discussResizeHandle'); var dragging = false; var startX = 0; var startWidth = 0;
            function setWidth(width) {
                var bounds = workspaceDockWidthBounds(340);
                width = Math.max(bounds.min, Math.min(bounds.max, width));
                var zoomed = document.documentElement.dataset.cssZoom === 'true';
                document.documentElement.style.setProperty(zoomed ? '--css-zoom-dock-width' : '--utility-dock-w', width + 'px');
                var zoom = workspaceZoomFactor();
                updateSeparatorValue(handle, width * zoom, bounds.min * zoom, bounds.max * zoom);
            }
            function currentWidth() {
                var rendered = document.getElementById('discussPanel').getBoundingClientRect().width;
                if (rendered > 0) return rendered / workspaceZoomFactor();
                return parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--utility-dock-w')) || 504;
            }
            handle.addEventListener('mousedown', function(event) { dragging = true; startX = event.clientX; startWidth = currentWidth(); handle.classList.add('is-dragging'); document.body.style.userSelect = 'none'; event.preventDefault(); });
            document.addEventListener('mousemove', function(event) { if (!dragging) return; setWidth(startWidth + (startX - event.clientX) / workspaceZoomFactor()); });
            document.addEventListener('mouseup', function() { if (!dragging) return; dragging = false; handle.classList.remove('is-dragging'); document.body.style.userSelect = ''; });
            handle.addEventListener('keydown', function(event) {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                var bounds = workspaceDockWidthBounds(340);
                var current = currentWidth();
                var next = current;
                if (event.key === 'Home') next = bounds.min;
                else if (event.key === 'End') next = bounds.max;
                else next += (event.key === 'ArrowRight' ? 1 : -1) * (event.shiftKey ? 50 : 20);
                setWidth(next);
                event.preventDefault();
            });
            var initialBounds = workspaceDockWidthBounds(340);
            var initialWidth = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--utility-dock-w')) || 504;
            setWidth(Math.min(initialBounds.max, Math.max(initialBounds.min, initialWidth)));
            window.addEventListener('resize', function() { setWidth(currentWidth()); });
            window.addEventListener('proseview:workspace-metrics', function() { setWidth(currentWidth()); });
        })();
