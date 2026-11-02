        // ── Project conversations with document-aware turns ──────────────
        var _discussConversationId = null;
        var _discussSnapshot = null;
        // Where a login started from the expired-login notice has got to:
        // '' (not started), 'waiting' (Terminal is open) or 'done'. Kept out
        // here because the notice is redrawn with every snapshot.
        var _discussClaudeLogin = '';
        var _discussDocumentKey = '';
        var _discussDraftDocument = null;
        var _discussEventSource = null;
        var _discussAttachments = [];
        var _discussSelection = '';
        var _discussSelectionRange = null;
        var _discussSelectionSnapshot = null;
        var _discussSelectionSourceTaskId = null;
        var _discussLiveDocument = null;
        var _discussIncludeCurrentDocument = false;
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
        // Reading passes are ordinary questions: no schema, no card, and the
        // thing they read stays attached so a follow-up can refer to it.
        const DISCUSS_READING_ACTIONS = [
            'quick_critique', 'style_consistency', 'voice_character',
            'pacing_tension', 'clarity_flow', 'continuity', 'next_beats'
        ];
        function discussIsReadingAction(actionId) {
            return DISCUSS_READING_ACTIONS.indexOf(String(actionId || '')) >= 0;
        }
        // What a writer reaches for on an ordinary afternoon. The test for this
        // list is repetition: these get run on the same scene in draft two and
        // again in draft five.
        //
        // What each card *says* belongs to its skill file, which the writer
        // owns and can rewrite -- `description:` in the SKILL.md frontmatter,
        // served by /api/discuss/actions. The wording here is the last resort:
        // it stands in until that answer lands, and for a skill file whose
        // frontmatter has no description line at all.
        const DISCUSS_SCENE_PASSES = [
            {
                id: 'quick_critique',
                label: 'Quick critique',
                copy: 'What is working against this scene, each note quoting the line and suggesting a fix.'
            },
            {
                id: 'style_consistency',
                label: 'Style and consistency',
                copy: 'Proseview finds the passives, filter verbs and echoes. The agent says which ones hurt.'
            },
            {
                id: 'next_beats',
                label: 'Next beats',
                copy: 'Concrete possibilities for what happens next in this scene, without writing the prose for you.'
            }
        ];
        // The rarer, heavier work. Same cards, same skill files behind them.
        const DISCUSS_REPOSITORY_PASSES = [
            {
                id: 'canon_refactor',
                label: 'Trace a canon change',
                copy: 'Find consequences across the configured story folders.'
            },
            {
                id: 'scene_continuity',
                label: "Check this scene's continuity",
                copy: 'Compare this document with the rest of the story evidence.'
            }
        ];
        // id -> {label, description} as the skill files currently read.
        var _discussActionCopy = {};
        // How long a finished turn keeps its result on screen before the
        // strip stands down.
        const DISCUSS_TURN_DONE_MS = 6000;
        var _discussStreamText = '';
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
            var previous = _discussAgentLocal[_discussAgent] || {};
            _discussAgentLocal[_discussAgent] = {
                attachments: _discussAttachments.slice(),
                selectedSkill: _discussSelectedSkill,
                conversationId: _discussConversationId || previous.conversationId || null
            };
        }

        function _restoreDiscussAgentLocal() {
            var bag = _discussAgentLocal[_discussAgent] || {};
            _discussAttachments = (bag.attachments || []).slice();
            _discussSelectedSkill = bag.selectedSkill || null;
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
            if (inputLabel) inputLabel.textContent = 'Ask ' + label + ' about your project';
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
            if (panel && !panel.hidden) {
                saveDiscussDraft();
                _saveDiscussAgentLocal();
            }
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            if (_discussAgent !== agent) { _discussSkillsLoaded = false; _discussSkillsLoading = null; _discussSkills = []; }
            _discussAgent = agent;
            try { localStorage.setItem(DISCUSS_AGENT_KEY, agent); } catch (e) {}
            _applyDiscussAgentLabels();
            openDiscuss(trigger || _discussReturnFocus);
        }

        // An agent you are not looking at still finishes, still gets stuck on
        // an approval. The dock being closed is exactly when that matters most,
        // so the poll keeps running -- it just never opens a conversation that
        // was never started, which would boot an agent nobody asked for.
        function _pollInactiveDiscussAgent() {
            clearTimeout(_discussAgentPollTimer);
            _discussAgentPollTimer = setTimeout(function() {
                var panel = document.getElementById('discussPanel');
                var live = panel && !panel.hidden && _discussConversationId;
                var targets = DISCUSS_AGENTS.filter(function(agent) {
                    // The agent on screen reports itself through its own event
                    // stream; polling it as well would only race that.
                    if (live && agent === _discussAgent) return false;
                    return !!(_discussAgentLocal[agent] || {}).conversationId;
                });
                Promise.all(targets.map(function(agent) {
                    var known = (_discussAgentLocal[agent] || {}).conversationId;
                    return fetch('/api/discuss/conversations/' + encodeURIComponent(known) + '/snapshot',
                                 {cache: 'no-store'})
                        .then(function(response) { return response.ok ? response.json() : null; })
                        .then(function(data) {
                            var snapshot = (data || {}).snapshot || {};
                            var pending = (snapshot.approvals || []).some(function(row) {
                                return row.status === 'pending';
                            });
                            var busy = !!snapshot.active_turn_id
                                || !!snapshot.active_request_id
                                || (snapshot.queue || []).length > 0;
                            _discussAgentState[agent] = pending ? 'attention' : (busy ? 'busy' : '');
                        })
                        .catch(function() {});
                })).then(function() {
                    _syncDiscussAmbientSignals();
                    _pollInactiveDiscussAgent();
                });
            }, 4000);
        }

        // '' | 'busy' | 'attention'. Working and waiting-on-you are different
        // problems: one resolves itself, the other never will until you act.
        function _markDiscussAgentTab(agent, state) {
            (UTILITY_TAB_IDS[agent] || []).forEach(function(id) {
                var el = document.getElementById(id);
                if (!el) return;
                el.classList.toggle('utility-tab-busy', state === 'busy');
                el.classList.toggle('utility-tab-attention', state === 'attention');
            });
        }

        // Asked for on every open rather than once per page: the skills live
        // under .proseview, which the file watcher ignores, so a writer who has
        // just rewritten a description gets it back by reopening the panel.
        function loadDiscussScenePasses() {
            return discussApi('/api/discuss/actions', {}).then(function(data) {
                var next = {};
                (data.actions || []).forEach(function(row) {
                    if (!row || !row.id) return;
                    next[row.id] = {
                        label: String(row.label || ''),
                        description: String(row.description || '')
                    };
                });
                var changed = JSON.stringify(next) !== JSON.stringify(_discussActionCopy);
                _discussActionCopy = next;
                // The cards were painted from the fallbacks above before this
                // answer arrived. Repaint only if it actually says something
                // else, and only while they are the thing on screen.
                if (changed && document.querySelector('.discuss-story-action')) renderDiscussSnapshot();
            }).catch(function() {});
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

        // Drafts belong to the provider's project conversation. Their document
        // is stored separately so navigation cannot silently change context
        // underneath text the writer already composed.
        function discussDraftKey(doc, agent) {
            return 'proseview-draft:' + (agent || _discussAgent);
        }

        function legacyDiscussDraftKey(doc, agent) {
            return 'proseview-draft:' + (agent || _discussAgent) + ':' + discussDocumentKey(doc);
        }

        function discussDraftDocumentKey(agent) {
            return discussDraftKey(null, agent) + ':document';
        }

        function discussIncludeCurrentDocumentKey(agent) {
            return discussDraftKey(null, agent) + ':include-current-document';
        }

        function discussTurnDocument() {
            return _discussDraftDocument || discussDocument() || _discussDockDocument;
        }

        function discussTaskDocument(target) {
            var taskDocument = target && target.document;
            if (taskDocument && (taskDocument.kind === 'scene' || taskDocument.kind === 'file')
                && typeof taskDocument.path === 'string' && taskDocument.path) {
                return {kind: taskDocument.kind, path: taskDocument.path};
            }
            return null;
        }

        function discussLiveDocumentFor(targetDocument) {
            var current = discussDocument();
            if (!current || !targetDocument || current.kind !== targetDocument.kind
                || current.path !== targetDocument.path || targetDocument.kind !== 'scene') return null;
            return typeof currentSceneLiveDocumentSnapshot === 'function'
                ? currentSceneLiveDocumentSnapshot() : null;
        }

        function discussSelectionSnapshotFor(targetDocument) {
            return typeof currentSceneSelectionSnapshot === 'function'
                ? currentSceneSelectionSnapshot(targetDocument) : null;
        }

        function saveDiscussDraft() {
            var input = document.getElementById('discussInput');
            if (!input) return;
            var key = discussDraftKey(null, _discussAgent);
            if (input.value && !_discussDraftDocument) _discussDraftDocument = discussDocument();
            if (!input.value && !_discussSelection && !_discussPendingAction
                && !_discussRepositoryAction && !_discussIncludeCurrentDocument) {
                _discussDraftDocument = null;
            }
            try {
                if (input.value) sessionStorage.setItem(key, input.value);
                else sessionStorage.removeItem(key);
                if (_discussDraftDocument && (input.value || _discussIncludeCurrentDocument)) {
                    sessionStorage.setItem(discussDraftDocumentKey(_discussAgent), JSON.stringify(_discussDraftDocument));
                } else {
                    sessionStorage.removeItem(discussDraftDocumentKey(_discussAgent));
                }
                if (_discussIncludeCurrentDocument) {
                    sessionStorage.setItem(discussIncludeCurrentDocumentKey(_discussAgent), 'true');
                } else sessionStorage.removeItem(discussIncludeCurrentDocumentKey(_discussAgent));
            } catch(e) {}
        }

        function restoreDiscussDraft(doc, agent) {
            try {
                var key = discussDraftKey(doc, agent);
                var draft = sessionStorage.getItem(key) || '';
                var rawDocument = sessionStorage.getItem(discussDraftDocumentKey(agent));
                var savedDocument = rawDocument ? JSON.parse(rawDocument) : null;
                _discussIncludeCurrentDocument = sessionStorage.getItem(
                    discussIncludeCurrentDocumentKey(agent)
                ) === 'true';
                if (!draft && doc) {
                    var legacyKey = legacyDiscussDraftKey(doc, agent);
                    var legacyDraft = sessionStorage.getItem(legacyKey) || '';
                    if (legacyDraft) {
                        draft = legacyDraft;
                        savedDocument = Object.assign({}, doc);
                        sessionStorage.setItem(key, draft);
                        sessionStorage.setItem(discussDraftDocumentKey(agent), JSON.stringify(savedDocument));
                        sessionStorage.removeItem(legacyKey);
                    }
                }
                _discussDraftDocument = savedDocument && (savedDocument.kind === 'scene' || savedDocument.kind === 'file')
                    && typeof savedDocument.path === 'string' ? savedDocument : null;
                if (draft && !_discussDraftDocument && doc) _discussDraftDocument = Object.assign({}, doc);
                return draft;
            }
            catch(e) { _discussIncludeCurrentDocument = false; return ''; }
        }

        function hasLegacyDiscussDraft(doc, agent) {
            if (!doc) return false;
            try { return !!sessionStorage.getItem(legacyDiscussDraftKey(doc, agent)); }
            catch(e) { return false; }
        }

        function activateLegacyDiscussDraft(doc, agent) {
            var input = document.getElementById('discussInput');
            if (!input || input.value || _discussDraftDocument || _discussSelection
                || _discussPendingAction || _discussRepositoryAction || !doc) return false;
            var legacyKey = legacyDiscussDraftKey(doc, agent);
            try {
                var draft = sessionStorage.getItem(legacyKey) || '';
                if (!draft) return false;
                var savedDocument = {kind: doc.kind, path: doc.path};
                sessionStorage.setItem(discussDraftKey(doc, agent), draft);
                sessionStorage.setItem(discussDraftDocumentKey(agent), JSON.stringify(savedDocument));
                sessionStorage.removeItem(legacyKey);
                input.value = draft;
                _discussDraftDocument = savedDocument;
                _discussPreservedDraft = draft;
                _saveDiscussAgentLocal();
                renderDiscussContext();
                renderDiscussTaskMode();
                renderDiscussContextOptions();
                return true;
            } catch(e) { return false; }
        }

        // The document the dock was last on. The dock stays open over the
        // dashboard, and the conversation in it carries on about this one.
        var _discussDockDocument = null;

        function discussDocument() {
            var view = document.documentElement.dataset.view;
            var doc = null;
            if (view === 'scene' && curIdx >= 0 && paths[curIdx]) doc = {kind: 'scene', path: paths[curIdx]};
            if (view === 'file') {
                var title = document.getElementById('filePreviewTitle');
                var path = title ? title.textContent.trim() : '';
                var node = repoFileByPath[path];
                if (path && node && node.is_text && !node.too_large) doc = {kind: 'file', path: path};
            }
            if (doc) _discussDockDocument = doc;
            return doc;
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
                && !trigger.closest('#discussPanel');
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
            closeDiscussModelPicker();
            var doc = discussDocument() || _discussDockDocument;
            if (!doc) {
                alert('Open a scene or supported text file before starting a discussion.');
                return;
            }
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            clearTimeout(_discussRefreshTimer);
            clearTimeout(_discussReconnectTimer);
            _discussReturnFocus = _returnFocusTarget(trigger);
            _discussSelection = options.selection !== undefined ? String(options.selection || '') : captureDiscussSelection();
            _discussSelectionRange = options.selectionRange && typeof options.selectionRange.start === 'number'
                ? {start: options.selectionRange.start, end: options.selectionRange.end}
                : null;
            _discussSelectionSnapshot = options.selectionSnapshot || null;
            _discussSelectionSourceTaskId = options.selectionSourceTaskId || null;
            _discussLiveDocument = options.liveDocument || null;
            _discussDraftDocument = null;
            _discussAttachments = [];
            _discussIncludeCurrentDocument = false;
            _discussPendingAction = options.actionId || null;
            _discussRepositoryAction = null;
            _discussRetryOfTaskId = null;
            _discussSelectedSkill = null;
            _discussAutoRun = !!options.runImmediately;
            var requestedAutoRun = _discussAutoRun;
            var requestedAction = _discussPendingAction;
            var requestedSelection = _discussSelection;
            var requestedSelectionRange = _discussSelectionRange;
            var requestedSelectionSnapshot = _discussSelectionSnapshot;
            var requestedSelectionSourceTaskId = _discussSelectionSourceTaskId;
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
            renderDiscussContext();
            renderDiscussTaskMode();
            setDiscussConnection('Restoring conversation', '');
            var key = discussDocumentKey(doc);
            _discussDocumentKey = key;
            var input = document.getElementById('discussInput');
            _restoreDiscussAgentLocal();
            _discussPreservedDraft = restoreDiscussDraft(doc, _discussAgent);
            input.value = requestedAutoRun ? '' : (options.prefill || _discussPreservedDraft);
            if (requestedSelection || requestedAction) {
                _discussDraftDocument = Object.assign({}, doc);
                // A passage is judged in its scene: the whole file goes along
                // with it unless the writer removes it.
                _discussIncludeCurrentDocument = !!requestedSelection;
            } else if (input.value && !_discussDraftDocument) {
                _discussDraftDocument = Object.assign({}, doc);
            }
            renderDiscussContext();
            var openBody = {kind: doc.kind, path: doc.path, agent: _discussAgent};
            discussApi('/api/discuss/conversations/open', openBody).then(function(data) {
                if (_discussDocumentKey !== key) return;
                _discussConversationId = data.conversation_id;
                _discussSnapshot = data.snapshot;
                renderDiscussSnapshot();
                connectDiscussEvents();
                // The composer was rendered after its selection/draft state was
                // restored above. Rebuilding it here detaches an open presets
                // popover while the conversation request finishes.
                document.getElementById('discussSend').disabled = false;
                _markDiscussAgentTab(_discussAgent, false);
                loadDiscussModelCatalog(_discussAgent);
                loadDiscussAgentAvailability();
                loadDiscussScenePasses();
                loadDiscussSkillList();
                _pollInactiveDiscussAgent();
                if (options.showSkills) loadDiscussSkills();
                else if (requestedAutoRun && requestedAction) {
                    runDiscussSelectionAction(
                        requestedAction, requestedSelection, requestedSelectionRange, requestedLiveDocument,
                        0, null, requestedSelectionSnapshot, requestedSelectionSourceTaskId
                    );
                }
                else if (options.sendInstruction) chooseDiscussInstruction(options.sendInstruction);
                else input.focus();
            }).catch(function(error) {
                _discussOpenFailed = true;
                
                var msg = error.message || '';
                var label = discussAgentLabel();
                if (msg.includes('Codex') || msg.includes('API key') || msg.includes('app-server')
                    || msg.includes('claude-agent-sdk') || msg.includes('Claude Code')) {
                    setDiscussConnection('Not connected', '');
                    var log = document.getElementById('discussLog');
                    log.textContent = '';
                    log.appendChild(discussNotInstalledState(label, msg));
                    document.getElementById('discussComposerArea').hidden = true;
                    document.getElementById('discussAnnouncement').textContent = label + ' is not connected.';
                    return;
                }

                setDiscussConnection('Unavailable', error.message);
                renderDiscussError(error.message, {kind: error.name === 'NetworkError' ? 'transport' : 'request'});
                var button = document.getElementById('discussSend');
                button.textContent = 'Try again';
                button.disabled = false;
                syncDiscussSendEmpty();
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
                _discussDraftDocument = Object.assign({}, doc);
                _discussIncludeCurrentDocument = !!options.selection;
                _discussSelectionRange = options.selectionRange || null;
                _discussSelectionSnapshot = options.selectionSnapshot || null;
                _discussSelectionSourceTaskId = options.selectionSourceTaskId || null;
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
                        _discussPendingAction, _discussSelection, _discussSelectionRange, _discussLiveDocument,
                        0, null, _discussSelectionSnapshot, _discussSelectionSourceTaskId
                    );
                } else if (options.sendInstruction) chooseDiscussInstruction(options.sendInstruction);
                else {
                    // A starter is put in the box for the writer to edit, never sent.
                    if (options.prefill) {
                        document.getElementById('discussInput').value = options.prefill;
                        syncDiscussSendEmpty();
                    }
                    document.getElementById('discussInput').focus();
                }
                return;
            }
            openDiscuss(trigger, options);
        }

        function closeDiscuss() {
            saveDiscussDraft();
            _saveDiscussAgentLocal();
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
            _syncDiscussAmbientSignals();
        }

        // ── Scene panel tabs ────────────────────────────────────────────
        //
        // Five tabs in one dock, ordered by how much they can surprise you.
        // Scene, Analysis and History are deterministic -- frontmatter, counts,
        // the highlight passes and the version log, all derived from the file
        // on disk. Codex and Claude are the surfaces that call a model. Keeping
        // that boundary legible is the point of the split.
        const SCENE_PANEL_TABS = ['scene', 'analysis', 'history', 'codex', 'claude', 'room'];
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

        const UTILITY_TAB_IDS = {
            scene: ['utilityTabScene'],
            analysis: ['utilityTabAnalysis'],
            history: ['utilityTabHistory'],
            codex: ['utilityTabCodex'],
            claude: ['utilityTabClaude'],
            room: ['utilityTabRoom']
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
            return ['discussContext', 'discussLog', 'discussComposerArea', 'discussNewActivity', 'discussTurnStatus']
                .map(function(id) { return document.getElementById(id); }).filter(Boolean);
        }

        function _discussVisibleEls() {
            return ['discussContext', 'discussLog', 'discussComposerArea']
                .map(function(id) { return document.getElementById(id); }).filter(Boolean);
        }

        const SCENE_PANEL_PANES = {
            scene: {id: 'sceneDetailsPane', heading: 'Scene', render: renderSceneDetailsPane},
            analysis: {id: 'sceneAnalysisPane', heading: 'Analysis', render: renderSceneAnalysisPane},
            history: {id: 'sceneHistoryPane', heading: 'History', render: function() { if(paths[curIdx]) loadSceneHistory(paths[curIdx]); }},
            room: {id: 'sceneRoomPane', heading: 'Writers\u2019 Room', render: renderSceneRoomPane}
        };

        // What a scene tab says over the dashboard, where there is no scene.
        const SCENE_PANEL_AWAY = {
            scene: 'Open a scene to see its details.',
            analysis: 'Open a scene to see its analysis.',
            history: 'Open a scene to see its history.',
            room: 'Open a scene to run the Writers\u2019 Room.'
        };

        function _scenePanelAwayEl() {
            let away = document.getElementById('scenePanelAway');
            if (away) return away;
            const first = document.getElementById(SCENE_PANEL_PANES.scene.id);
            if (!first) return null;
            away = document.createElement('div');
            away.id = 'scenePanelAway';
            away.className = 'scene-details-pane';
            away.setAttribute('role', 'tabpanel');
            away.hidden = true;
            first.parentNode.insertBefore(away, first);
            return away;
        }

        // Over the dashboard a scene tab keeps its place in the strip and, if
        // it was the one open, stays selected -- it just has nothing to show.
        function _showScenePanelAway(name) {
            const away = _scenePanelAwayEl();
            if (!away) return;
            Object.keys(SCENE_PANEL_PANES).forEach(function(key) {
                const pane = document.getElementById(SCENE_PANEL_PANES[key].id);
                if (pane) pane.hidden = true;
            });
            away.replaceChildren(_scenePanelEmpty(SCENE_PANEL_AWAY[name]));
            away.dataset.tab = name;
            away.setAttribute('aria-labelledby', UTILITY_TAB_IDS[name][0]);
            away.hidden = false;
        }

        function _hideScenePanelAway() {
            const away = document.getElementById('scenePanelAway');
            const tab = away && !away.hidden ? away.dataset.tab : null;
            if (away) away.hidden = true;
            return tab;
        }

        function _syncSceneTabsEnabled(enabled) {
            Object.keys(SCENE_PANEL_PANES).forEach(function(key) {
                UTILITY_TAB_IDS[key].forEach(function(id) {
                    const el = document.getElementById(id);
                    if (!el) return;
                    el.disabled = !enabled;
                    if (enabled) el.removeAttribute('aria-disabled');
                    else el.setAttribute('aria-disabled', 'true');
                });
            });
        }

        function showScenePanelTab(name) {
            const spec = SCENE_PANEL_PANES[name];
            const panel = document.getElementById('discussPanel');
            if (!spec || !panel) return;
            const pane = document.getElementById(spec.id);
            if (!pane) return;
            const away = !_sceneScopedViewIsOpen();
            panel.hidden = false;
            // The chat keeps updating its own status and composer while
            // another tab is up; this keeps them out of that tab whatever they do.
            panel.dataset.sceneTab = name;
            document.body.classList.add('discuss-open');
            try { sessionStorage.setItem('proseview-panel-open', 'true'); } catch(e) {}
            _discussBodyEls().forEach(function(el) { el.hidden = true; });
            // "Codex / Live" names the Discuss connection; it has no business
            // sitting above a pane of counts and frontmatter.
            _setDockHeading(spec.heading, false);
            _setUtilityTab(name);
            if (away) { _showScenePanelAway(name); return; }
            _hideScenePanelAway();
            Object.keys(SCENE_PANEL_PANES).forEach(function(key) {
                const other = document.getElementById(SCENE_PANEL_PANES[key].id);
                if (other) other.hidden = key !== name;
            });
            spec.render();
        }

        // Kept as a named seam: it is the entry point the scene modal and the
        // tests reach for, and it now means "the deterministic scene tab".
        function showSceneDetailsTab() { showScenePanelTab('scene'); }
        function showSceneAnalysisTab() { showScenePanelTab('analysis'); }

        function _showDiscussBody() {
            var panel = document.getElementById('discussPanel');
            if (panel) delete panel.dataset.sceneTab;
            _hideScenePanelAway();
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

        // ── Dock scope ──────────────────────────────────────────────────────
        // Going back to the dashboard leaves the dock as it was: a panel you
        // opened stays open, on the same tab, until you close it. The scene
        // tabs grey out and say there is no scene; a conversation carries on
        // about the scene you left. Read the book is a reading mode and still
        // closes it.
        function _sceneScopedViewIsOpen() {
            const view = document.documentElement.dataset.view;
            return view === 'scene' || view === 'file';
        }

        function syncScenePanelScope() {
            const scoped = _sceneScopedViewIsOpen();
            var openPanel = document.getElementById('discussPanel');
            if (openPanel && !openPanel.hidden) renderDiscussContext();
            _syncSceneTabsEnabled(scoped);
            if (!scoped) {
                if (document.documentElement.dataset.view === 'book') closeScenePanel();
                else if (openPanel && !openPanel.hidden) {
                    var shown = Object.keys(SCENE_PANEL_PANES).filter(function(key) {
                        var pane = document.getElementById(SCENE_PANEL_PANES[key].id);
                        return pane && !pane.hidden;
                    })[0];
                    if (shown) _showScenePanelAway(shown);
                }
            } else {
                var awayTab = _hideScenePanelAway();
                var shouldBeOpen = false;
                try { shouldBeOpen = sessionStorage.getItem('proseview-panel-open') === 'true'; } catch(e) {}
                var panel = document.getElementById('discussPanel');
                if (shouldBeOpen && panel && panel.hidden) {
                    var tab = _readScenePanelTab();
                    if (DISCUSS_AGENTS.indexOf(tab) >= 0) showDiscussAgentTab(tab);
                    else showScenePanelTab(tab);
                } else if (awayTab && panel && !panel.hidden) showScenePanelTab(awayTab);
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
            if (panel && !panel.hidden) { closeScenePanel(); return; }
            // Every tab is scene-scoped, so there is nothing to open over the
            // dashboard.
            if (!_sceneScopedViewIsOpen()) return;
            const tab = _readScenePanelTab();
            // One call, not two: openDiscuss opens a conversation on the
            // server, and doing it twice queued a second thread/read behind the
            // first for every reader whose last tab was an agent.
            if (DISCUSS_AGENTS.indexOf(tab) >= 0) showDiscussAgentTab(tab, trigger);
            else showScenePanelTab(tab);
        }

        function closeScenePanel() {
            const panel = document.getElementById('discussPanel');
            var wasOpen = panel && !panel.hidden;

            if (wasOpen) closeDiscuss();
            
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

        // ── Writers' Room: shared chat and preset invitations ────────────
        var _roomSettings = null;
        var _roomSettingsLoading = null;

        // Seat identifiers stay canonical in the transcript and summary payloads.
        // Each conversation retains a snapshot of its selected profiles.
        function _roomSeatName(seat) {
            var session = _roomSessionsByScene[_roomCurrentScenePath()];
            var participant = ((session && session.participants) || (_roomSettings && _roomSettings.participants) || [])[Number(seat) - 1];
            if (participant) return participant.name;
            var key = seat === 2 ? 'critic2' : seat === 'moderator' ? 'moderator' : 'critic1';
            var fallback = {critic1: 'Story Editor', critic2: 'Voice Editor', moderator: 'Moderator'};
            return ((_roomSettings && _roomSettings.book) || {})[key + '_name'] || fallback[key];
        }

        function _roomSpeakerName(seat, agent) {
            return _roomSeatName(seat) + ' \u00b7 ' + _roomAgentDisplay(agent);
        }

        function _roomProposerName(value) {
            if (value === 'Critic 1') return _roomSeatName(1);
            if (value === 'Critic 2') return _roomSeatName(2);
            return value === 'Writer' ? 'Me' : value;
        }
        var _roomSessionsByScene = Object.create(null);
        var _roomDraftInput = '';
        var _roomTargetChoice = 'both';

        function _roomMentionOptions() {
            var session = _roomSessionsByScene[_roomCurrentScenePath()];
            return (session && session.participants) || (_roomSettings && _roomSettings.participants) || [];
        }

        function _roomProfiles(ids) {
            var library = (_roomSettings || {}).library;
            if (!library) return [];
            return _roomSnapshotPair(ids.map(function(id) { return library.profiles.find(function(profile) { return profile.id === id; }); }));
        }

        function _roomSnapshotPair(profiles) {
            var pair = JSON.parse(JSON.stringify(profiles));
            var handles = pair.map(function(profile, index) { return profile.name.replace(/[^\p{L}\p{N}_-]/gu, '') || 'Editor' + (index + 1); });
            if (handles[0].toLowerCase() === handles[1].toLowerCase()) handles = handles.map(function(handle, index) { return handle + (index + 1); });
            pair.forEach(function(profile, index) {
                profile.seat = index + 1;
                profile.handle = handles[index];
                profile.aliases = [profile.handle];
                if (pair.filter(function(p) { return p.agent === profile.agent; }).length === 1
                        && !handles.some(function(handle) { return handle.toLowerCase() === profile.agent; })) profile.aliases.push(profile.agent);
            });
            return pair;
        }

        function _roomEnsureParticipants(session) {
            if (!session.participants && _roomSettings && _roomSettings.library) {
                session.participants = _roomProfiles(_roomSettings.library.default_profiles);
            }
            return session.participants || [];
        }

        function _roomPairPicker(session, container, onChange) {
            var library = (_roomSettings || {}).library;
            if (!library) return;
            var pair = _roomEnsureParticipants(session);
            pair.forEach(function(profile, index) {
                var label = document.createElement('label');
                label.className = 'room-participant-choice';
                label.appendChild(document.createTextNode('Participant ' + (index + 1)));
                var select = document.createElement('select');
                select.className = 'room-target-select';
                select.setAttribute('aria-label', 'Room participant ' + (index + 1));
                library.profiles.forEach(function(option) {
                    var node = document.createElement('option');
                    node.value = option.id;
                    node.textContent = option.name + ' · ' + _roomAgentDisplay(option.agent);
                    node.disabled = pair[1 - index].id === option.id;
                    select.appendChild(node);
                });
                select.value = profile.id;
                select.disabled = !!session.turns.length || session.busy || session.managed || !!(session.outbox && session.outbox.length);
                select.onchange = function() {
                    var ids = pair.map(function(p) { return p.id; });
                    ids[index] = select.value;
                    session.participants = _roomProfiles(ids);
                    session.participantsChosen = true;
                    if (onChange) onChange(ids);
                    renderSceneRoomPane();
                };
                label.appendChild(select);
                container.appendChild(label);
            });
        }

        function _roomHasReview(session) {
            return !!session && session.turns.some(function(turn) { return turn.review_pending; });
        }

        function _roomFinishReview(session, turn) {
            if (session.managed) {
                return roomRuntimeControl(session, 'reviewed', {conversation_id: turn.tool_conversation_id}).then(function() {
                    try { sessionStorage.removeItem('proseview-room-review:' + turn.tool_conversation_id); } catch (error) {}
                }).catch(function() {});
                return;
            }
            turn.review_pending = false;
            _saveRoomSession(session);
            if (!_roomHasReview(session)) {
                session.busy = false;
                session.statusText = '';
                _processRoomQueue(session.scene, _roomRunToken);
            } else renderSceneRoomPane();
        }

        // Review state belongs to the Room turn, independently of the active
        // individual chat. Both surfaces use the same cards and expanded viewer.
        var _roomReviewContexts = new WeakMap();

        function _roomToolReview(session, turn) {
            var box = elementWith('room-tool-review');
            box.appendChild(elementWith('room-open-title', 'Review ' + _roomSpeakerName(turn.seat, turn.agent) + '’s changes'));
            var content = elementWith('room-tool-review-files');
            var notice = elementWith('room-error-text');
            notice.setAttribute('role', 'status');
            box.append(content, notice);
            var review = _roomReviewContexts.get(turn);
            if (!review) {
                review = {conversationId: turn.tool_conversation_id, agentLabel: _roomSpeakerName(turn.seat, turn.agent),
                    mode: 'side-by-side', files: [], unreviewable: [], keep: {}, loaded: false, applying: false, error: ''};
                var savedChoices = {};
                try { savedChoices = JSON.parse(sessionStorage.getItem('proseview-room-review:' + review.conversationId) || '{}'); } catch (error) {}
                review.keep = savedChoices.keep || {};
                review.mode = savedChoices.mode === 'inline' ? 'inline' : 'side-by-side';
                review.save = function() {
                    var fingerprints = Object.assign({}, review.fingerprints || savedChoices.fingerprints || {});
                    review.files.forEach(function(file) {
                        var chosen = review.keep[file.path] || {};
                        if (!Object.keys(chosen).some(function(id) { return chosen[id] === false; })) fingerprints[file.path] = file.fingerprint;
                    });
                    review.fingerprints = fingerprints;
                    try { sessionStorage.setItem('proseview-room-review:' + review.conversationId, JSON.stringify({keep: review.keep, mode: review.mode, fingerprints: fingerprints})); } catch (error) {}
                };
                review.onSettled = function() { return _roomFinishReview(session, turn); };
                _roomReviewContexts.set(turn, review);
                review.refresh = function() {
                    var token = review.loadToken = (review.loadToken || 0) + 1;
                    return discussApi('/api/discuss/conversations/' + encodeURIComponent(review.conversationId) + '/changes', {mode: review.mode})
                        .then(function(data) {
                            if (review.loadToken !== token) return;
                            review.files = data.files || []; review.unreviewable = data.unreviewable || [];
                            review.loaded = true; review.error = '';
                            Object.keys(review.keep).forEach(function(path) {
                                if (!review.files.some(function(file) { return file.path === path; })) delete review.keep[path];
                            });
                            review.render();
                        }).catch(function(error) {
                            if (review.loadToken !== token) return;
                            review.error = 'The original review is unavailable: ' + error.message + ' Use file history to inspect changes.';
                            review.render();
                        });
                };
            }
            review.render = function(focusPath) {
                review.save();
                if (!box.isConnected) return;
                content.replaceChildren();
                if (!review.loaded) content.textContent = review.error ? '' : 'Loading changes…';
                review.files.forEach(function(file) { content.appendChild(renderDiscussReviewCard(file, review)); });
                review.unreviewable.forEach(function(path) {
                    content.appendChild(elementWith('room-error-text', path + ': the agent changed this without a prior snapshot. Use file history to review it.'));
                });
                if (review.loaded && !review.files.length && !review.unreviewable.length) content.textContent = 'No outstanding changes.';
                notice.textContent = review.error;
                if (focusPath) {
                    var card = Array.from(content.querySelectorAll('[data-review-path]')).find(function(node) { return node.dataset.reviewPath === focusPath; });
                    if (card) card.querySelector('button').focus({preventScroll: true});
                    else document.getElementById('roomInput').focus({preventScroll: true});
                }
            };
            queueMicrotask(function() { review.render(); review.refresh(); });
            return box;
        }

        function chatMentionRanges(text, participants) {
            if (text.indexOf('@') < 0) return [];
            var ranges = discussMentionRanges(text);
            var pattern = /(?:^|[\s(])@([\p{L}\p{N}_-]+)(?=$|[\s.,!?:;)\]'’])/gu;
            var match;
            while ((match = pattern.exec(text))) {
                var start = match.index + match[0].indexOf('@');
                if (ranges.some(function(file) { return start >= file.start && start < file.end; })) continue;
                var handle = match[1].toLowerCase();
                var participant = (participants || []).find(function(p) {
                    return p.aliases.some(function(alias) { return alias.toLowerCase() === handle; });
                });
                if (participant) ranges.push({start: start, end: start + match[1].length + 1, kind: 'agent', participant: participant});
            }
            return ranges.sort(function(a, b) { return a.start - b.start; });
        }

        function highlightChatMentions(parent, participants) {
            var walker = document.createTreeWalker(parent, NodeFilter.SHOW_TEXT);
            var nodes = [], node;
            while ((node = walker.nextNode())) {
                if (!node.parentElement.closest('a, code, pre, .chat-mention')) nodes.push(node);
            }
            nodes.forEach(function(textNode) {
                var text = textNode.nodeValue, ranges = chatMentionRanges(text, participants);
                if (!ranges.length) return;
                var fragment = document.createDocumentFragment(), last = 0;
                ranges.forEach(function(range) {
                    if (range.start < last) return;
                    fragment.appendChild(document.createTextNode(text.slice(last, range.start)));
                    var chip = document.createElement('span'); chip.className = 'chat-mention';
                    chip.dataset.kind = range.kind;
                    chip.textContent = text.slice(range.start, range.end);
                    chip.title = range.participant ? range.participant.name + ' · ' + _roomAgentDisplay(range.participant.agent) : range.path;
                    fragment.appendChild(chip); last = range.end;
                });
                fragment.appendChild(document.createTextNode(text.slice(last)));
                textNode.replaceWith(fragment);
            });
        }

        function chatComposerMentionRanges(input, participants) {
            return chatMentionRanges(input.value, participants).concat(input.id === 'roomInput' ? roomSkillMentionRanges(input.value) : discussSkillRanges(input.value))
                .sort(function(a, b) { return a.start - b.start; });
        }

        function deleteChatMention(event, input, participants) {
            if (event.isComposing || event.ctrlKey || event.metaKey || event.altKey || !['Backspace', 'Delete'].includes(event.key)) return false;
            var start = input.selectionStart, end = input.selectionEnd;
            var ranges = chatComposerMentionRanges(input, participants);
            var hits = ranges.filter(function(range) {
                if (start !== end) return start < range.end && end > range.start;
                return event.key === 'Backspace' ? start > range.start && start <= range.end
                    || start === range.end + 1 && input.value.charAt(range.end) === ' '
                    : start >= range.start && start < range.end;
            });
            if (!hits.length) return false;
            event.preventDefault();
            hits.forEach(function(range) { start = Math.min(start, range.start); end = Math.max(end, range.end); });
            input.setRangeText('', start, end, 'end');
            input.dispatchEvent(new Event('input', {bubbles: true}));
            return true;
        }

        function wireChatMentionReplacement(input, participants) {
            input.addEventListener('beforeinput', function(event) {
                if (event.isComposing || !event.inputType.startsWith('insert')) return;
                var start = input.selectionStart, end = input.selectionEnd;
                chatComposerMentionRanges(input, participants()).forEach(function(range) {
                    if (start === end ? start > range.start && start < range.end : start < range.end && end > range.start) {
                        start = Math.min(start, range.start); end = Math.max(end, range.end);
                    }
                });
                input.setSelectionRange(start, end);
            });
        }

        function _roomMentionRecipients(text) {
            var seats = [];
            chatMentionRanges(text, _roomMentionOptions()).forEach(function(range) {
                if (range.participant && !seats.includes(range.participant.seat)) seats.push(range.participant.seat);
            });
            return seats;
        }

        function paintRoomMentions(input, mirror) {
            var text = input.value, last = 0;
            mirror.replaceChildren();
            chatMentionRanges(text, _roomMentionOptions()).concat(roomSkillMentionRanges(text)).sort(function(a, b) { return a.start - b.start; }).forEach(function(range) {
                if (range.start < last) return;
                mirror.appendChild(document.createTextNode(text.slice(last, range.start)));
                var mark = document.createElement('mark'); mark.className = 'discuss-mention';
                mark.textContent = text.slice(range.start, range.end); mirror.appendChild(mark); last = range.end;
            });
            mirror.appendChild(document.createTextNode(text.slice(last) + ' '));
            mirror.scrollTop = input.scrollTop; mirror.scrollLeft = input.scrollLeft;
        }

        function _wireRoomMentions(input, menu, target, hint) {
            var choices = [], active = 0, range = null;
            input.setAttribute('aria-autocomplete', 'list');
            input.setAttribute('aria-haspopup', 'listbox');
            input.setAttribute('aria-controls', menu.id);
            function close() {
                menu.hidden = true;
                choices = [];
                input.setAttribute('aria-expanded', 'false');
                input.removeAttribute('aria-activedescendant');
            }
            function updateRecipients() {
                var seats = _roomMentionRecipients(input.value);
                target.value = seats.length > 1 ? 'both' : seats.length ? 'critic' + seats[0] : _roomTargetChoice;
                target.disabled = seats.length > 0;
                hint.textContent = seats.length
                    ? 'Replies: ' + seats.map(_roomSeatName).join(', ')
                    : '';
            }
            function choose(option) {
                if (!range) return;
                var token = option.kind === 'skill' ? '$' + option.name : '@' + (option.kind === 'editor' ? option.handle : option.path + (option.kind === 'folder' ? '/' : ''));
                if (option.kind === 'skill' && !_roomMentionRecipients(input.value).length && _roomTargetChoice === 'both') token = '@' + option.participant.handle + ' ' + token;
                input.setRangeText(token + ' ', range.start, range.end, 'end');
                close();
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.focus();
            }
            function paint() {
                menu.replaceChildren();
                var group = '';
                choices.forEach(function(option, index) {
                    var category = option.kind === 'skill' ? 'Skills · ' + option.participant.name + ' · ' + _roomAgentDisplay(option.participant.agent) : option.kind === 'editor' ? 'Editors' : 'Files and folders';
                    if (group !== category) {
                        var heading = elementWith('room-mention-group', category);
                        heading.setAttribute('role', 'presentation');
                        menu.appendChild(heading);
                        group = category;
                    }
                    var button = document.createElement('button');
                    button.type = 'button';
                    button.id = 'roomMentionOption-' + index;
                    button.className = 'room-mention-option';
                    button.setAttribute('role', 'option');
                    button.setAttribute('aria-selected', index === active ? 'true' : 'false');
                    button.append(
                        elementWith('room-mention-name', option.kind === 'skill' ? '$' + option.name : option.kind === 'editor' ? option.name + ' \u00b7 ' + _roomAgentDisplay(option.agent) : option.path),
                        elementWith('room-mention-handle', option.kind === 'skill' ? option.description || 'Skill' : option.kind === 'editor' ? '@' + option.handle : option.kind === 'folder' ? 'Folder' : 'File')
                    );
                    button.onpointerdown = function(event) { event.preventDefault(); };
                    button.onclick = function() { choose(option); };
                    menu.appendChild(button);
                });
                menu.hidden = false;
                input.setAttribute('aria-expanded', 'true');
                input.setAttribute('aria-activedescendant', 'roomMentionOption-' + active);
                menu.querySelector('[aria-selected="true"]').scrollIntoView({block: 'nearest'});
            }
            function render() {
                updateRecipients();
                var prefix = input.value.slice(0, input.selectionStart);
                var match = /(?:^|[\s(])([@$])([^\s@$]*)$/u.exec(prefix);
                if (!match || input.selectionStart !== input.selectionEnd) { close(); return; }
                var query = match[2].toLowerCase();
                if (match[1] === '$') {
                    range = {start: input.selectionStart - match[2].length - 1, end: input.selectionStart + /^[\p{L}\p{N}_-]*/u.exec(input.value.slice(input.selectionStart))[0].length};
                    var participants = _roomMentionOptions().filter(function(profile) { return roomRequestedSeats(input.value).includes(profile.seat); });
                    choices = []; var pending = false;
                    participants.forEach(function(profile) {
                        var skills = _roomSkillCatalogs[profile.agent];
                        if (!skills) {
                            pending = true;
                            roomLoadSkills(profile.agent).then(function() { if (input.isConnected && document.activeElement === input) render(); })
                                .catch(function(error) { if (input.isConnected && document.activeElement === input) { menu.textContent = 'Skills unavailable: ' + error.message; menu.hidden = false; } });
                            return;
                        }
                        skills.filter(function(skill) { return (skill.name + ' ' + (skill.display_name || '') + ' ' + (skill.description || '')).toLowerCase().includes(query); }).forEach(function(skill) { choices.push(Object.assign({kind: 'skill', participant: profile}, skill)); });
                    });
                    choices = choices.slice(0, 12); active = 0;
                    if (choices.length) paint();
                    else { menu.textContent = pending ? 'Loading skills…' : 'No matching skills for the selected participants.'; menu.hidden = false; input.setAttribute('aria-expanded', 'true'); }
                    return;
                }
                var editors = _roomMentionOptions().filter(function(option) {
                    return [option.name, option.agent].concat(option.aliases).some(function(value) {
                        return value.toLowerCase().indexOf(query) >= 0;
                    });
                }).map(function(option) { return Object.assign({kind: 'editor'}, option); });
                var files = discussContextCandidates().filter(function(option) {
                    return (option.name + ' ' + option.path).toLowerCase().indexOf(query) >= 0;
                }).slice(0, 12 - editors.length);
                choices = editors.concat(files);
                if (!choices.length) { close(); return; }
                var suffix = /^[\p{L}\p{N}_./-]*/u.exec(input.value.slice(input.selectionStart))[0];
                range = {start: input.selectionStart - match[2].length - 1, end: input.selectionStart + suffix.length};
                active = 0;
                paint();
            }
            input.addEventListener('input', render);
            input.addEventListener('click', render);
            input.addEventListener('keyup', function(event) {
                if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(event.key) >= 0) render();
            });
            input.addEventListener('blur', close);
            input.onkeydown = function(event) {
                if (event.isComposing) return;
                if (deleteChatMention(event, input, _roomMentionOptions())) return;
                if (!menu.hidden && !choices.length && ['Enter', 'Tab', 'Escape'].includes(event.key)) {
                    event.preventDefault(); if (event.key === 'Escape') { event.stopPropagation(); close(); } return;
                }
                if (!menu.hidden && choices.length) {
                    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                        event.preventDefault();
                        active = (active + (event.key === 'ArrowDown' ? 1 : -1) + choices.length) % choices.length;
                        paint();
                        return;
                    }
                    if ((event.key === 'Enter' || event.key === 'Tab') && !event.shiftKey) {
                        event.preventDefault(); choose(choices[active]); return;
                    }
                    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return; }
                }
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault(); sendRoomComposerMessage();
                }
            };
            updateRecipients();
            close();
        }
        var _roomApplyAgentChoice = '';
        var _roomRunToken = 0;
        // Saved debates, as the chats keep their threads: per scene, on this
        // computer. A scene's latest debate comes back when the Room opens.
        var _roomHistoryChecked = Object.create(null);
        var _roomHistoryList = Object.create(null);
        var _roomHistoryOpen = false;
        var _roomScrollByScene = Object.create(null);
        // A passage picked with Ask or Polish, sent with the next message.
        var _roomPendingSelection = '';

        function roomTabIsOpen() {
            var panel = document.getElementById('discussPanel');
            return !!(panel && !panel.hidden && panel.dataset.sceneTab === 'room' && _roomCurrentScenePath());
        }

        function attachSelectionToRoom(selection, instruction) {
            var session = _roomSessionFor(_roomCurrentScenePath());
            if (!session) return;
            // A debate is running: hold the passage and the request for the writer to send.
            if (instruction && session.busy && _roomPendingSelection) return;
            _roomPendingSelection = String(selection || '').trim();
            renderSceneRoomPane();
            var input = document.getElementById('roomInput');
            if (instruction && input) {
                input.value = instruction;
                _roomDraftInput = instruction;
            }
            if (instruction && !session.busy) { sendRoomComposerMessage(); return; }
            renderSceneRoomPane();
            input = document.getElementById('roomInput');
            if (input) input.focus();
        }

        function _roomWithSelection(text) {
            if (!_roomPendingSelection) return text;
            var quoted = _roomPendingSelection.split('\n').map(function(line) { return '> ' + line; }).join('\n');
            return text + '\n\nSelected passage:\n' + quoted;
        }

        function _roomCurrentScenePath() {
            return (typeof paths !== 'undefined' && typeof curIdx !== 'undefined' && paths[curIdx]) ? paths[curIdx] : null;
        }

        function _roomSessionFor(scenePath) {
            if (!scenePath) return null;
            if (!_roomSessionsByScene[scenePath]) {
                _roomSessionsByScene[scenePath] = {
                    scene: scenePath,
                    presetId: '',
                    topicLabel: '',
                    topicBadge: '',
                    question: '',
                    turns: [],
                    plan: [],
                    authorsCall: '',
                    open: [],
                    plans: [],
                    busy: false,
                    statusText: '',
                    error: '',
                    queue: []
                };
            }
            return _roomSessionsByScene[scenePath];
        }

        function _roomAgentDisplay(agentId) {
            return agentId === 'claude' ? 'Claude' : 'Codex';
        }

        function _roomHeaderSummaryText() {
            var session = _roomSessionsByScene[_roomCurrentScenePath()];
            var pair = (session && session.participants) || (_roomSettings && _roomSettings.participants) || [];
            return pair.length ? pair.map(function(p) { return p.name + ' · ' + _roomAgentDisplay(p.agent); }).join(' ↔ ') : 'Writers’ Room';
        }

        function syncRoomSettingsState(settings) {
            if (settings) {
                _roomSettings = settings;
                Object.keys(_roomSessionsByScene).forEach(function(path) {
                    var session = _roomSessionsByScene[path];
                    if (!session.managed && !session.turns.length && !session.pendingPreset && !session.busy) {
                        var selected = session.participantsChosen && session.participants && session.participants.map(function(p) { return p.id; });
                        var available = selected && selected.every(function(id) { return settings.library.profiles.some(function(p) { return p.id === id; }); });
                        session.participants = _roomProfiles(available ? selected : settings.library.default_profiles);
                    }
                });
            }
            var summaryEl = document.getElementById('roomHeaderSummary');
            if (summaryEl) summaryEl.textContent = _roomHeaderSummaryText();
            var pane = document.getElementById('sceneRoomPane');
            if (pane && !pane.hidden) renderSceneRoomPane();
        }

        function _ensureRoomSettingsLoaded() {
            if (_roomSettings) return Promise.resolve(_roomSettings);
            if (_roomSettingsLoading) return _roomSettingsLoading;
            _roomSettingsLoading = (typeof loadRoomSettings === 'function' ? loadRoomSettings() :
                fetch('/api/discuss/room-settings', {method: 'POST', headers: pvHeaders(), body: '{}'})
                    .then(function(r) { return r.json(); }).then(function(data) { return data.settings; }))
                .then(function(settings) {
                    if (!settings) throw new Error('Could not load Room profiles and presets. Reopen the Room to retry.');
                    _roomSettings = settings;
                    return settings;
                }).finally(function() { _roomSettingsLoading = null; });
            return _roomSettingsLoading;
        }

        function resetRoomSession() {
            var path = _roomCurrentScenePath();
            if (!path) return;
            _roomRunToken++;
            _roomDraftInput = ''; _roomPendingSelection = ''; _roomTargetChoice = 'both';
            var input = document.getElementById('roomInput'); if (input) input.value = '';
            try { sessionStorage.removeItem(roomDraftKey(path)); } catch (error) {}
            delete _roomSessionsByScene[path];
            _roomHistoryChecked[path] = true;
            _roomHistoryOpen = false;
            renderSceneRoomPane();
        }

        function _roomNewId() {
            return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
        }

        function _roomHistoryRequest(payload) {
            return fetch('/api/discuss/room-history', {
                method: 'POST',
                headers: pvHeaders(),
                body: JSON.stringify(payload)
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (!data || !data.ok) throw new Error((data && data.error) || 'Could not access Room history');
                return data;
            });
        }

        // A debate keeps every plan the moderator wrote, each placed in the
        // thread after the turns it sums up; the newest one is live.
        function _roomPlanItem(item, idx) {
            return {
                id: 'plan-' + Date.now() + '-' + idx,
                title: item.title || '',
                detail: item.detail || '',
                line: item.line || '',
                original: item.original || '',
                replacement: item.replacement || '',
                proposedBy: item.proposed_by || item.proposedBy || '',
                accepted: item.accepted === true,
                checked: (typeof item.checked === 'boolean' ? item.checked : item.accepted === true) && !item.applied,
                applied: item.applied || '',
                todoAdded: !!item.todoAdded
            };
        }

        function _roomLatestPlan(session) {
            return (session && session.plans && session.plans.length) ? session.plans[session.plans.length - 1] : null;
        }

        function _saveRoomSession(session) {
            if (session && session.managed) { saveManagedRoom(session); return; }
            if (!session || !session.turns.length) return;
            if (!session.id) session.id = _roomNewId();
            // One save at a time per debate, the last one carrying the latest
            // state, so an older save can never land after a newer one.
            if (session._saving) { session._saveAgain = true; return; }
            session._saving = true;
            _roomHistoryRequest({
                action: 'save',
                session: {
                    id: session.id,
                    scene: session.scene,
                    title: session.topicLabel || (session.question ? session.question.slice(0, 80) : ''),
                    badge: session.topicBadge || '',
                    preset_id: session.presetId || '',
                    question: session.question || '',
                    created_at: session.createdAt || 0,
                    participants: session.participants,
                    turns: session.turns,
                    plans: (session.plans || []).map(function(plan) {
                        return {
                            after_turn: plan.afterTurn,
                            agent: plan.agent || '',
                            items: plan.items.map(function(item) {
                                return {
                                    title: item.title, detail: item.detail, proposed_by: item.proposedBy || '',
                                    line: item.line || '', original: item.original || '', replacement: item.replacement || '',
                                    accepted: !!item.accepted, checked: !!item.checked, applied: item.applied || '',
                                    todoAdded: !!item.todoAdded
                                };
                            }),
                            open: plan.open || [],
                            authors_call: plan.authorsCall || ''
                        };
                    })
                }
            }).then(function() {
                delete _roomHistoryList[session.scene];
            }).catch(function(error) {
                session.error = 'Could not save this Room: ' + error.message;
                if (!session.busy && session.scene === _roomCurrentScenePath()) renderSceneRoomPane();
            }).then(function() {
                session._saving = false;
                if (session._saveAgain) {
                    session._saveAgain = false;
                    _saveRoomSession(session);
                }
            });
        }

        function _loadRoomHistoryList(scenePath) {
            if (_roomHistoryList[scenePath]) return Promise.resolve(_roomHistoryList[scenePath]);
            return _roomHistoryRequest({action: 'list', scene: scenePath}).then(function(data) {
                var rows = (data && data.ok && Array.isArray(data.sessions)) ? data.sessions : [];
                _roomHistoryList[scenePath] = rows;
                return rows;
            }).catch(function() { return []; });
        }

        function openRoomHistorySession(scenePath, sessionId) {
            return _ensureRoomSettingsLoaded().then(function() {
                return _roomHistoryRequest({action: 'get', id: sessionId});
            }).then(function(data) {
                if (!data || !data.ok || !data.session) return;
                var saved = data.session;
                var current = _roomSessionsByScene[scenePath];
                if (current && current.busy) return;
                var session = _roomSessionFor(scenePath);
                session.id = saved.id;
                session.createdAt = saved.created_at || 0;
                session.presetId = saved.preset_id || '';
                session.topicLabel = saved.title || '';
                session.topicBadge = saved.badge || '';
                session.question = saved.question || '';
                session.turns = saved.turns || [];
                session.participants = saved.participants || null;
                if (!session.participants && _roomSettings && _roomSettings.library) {
                    // Older debates used book-specific seat names and prompts.
                    var book = _roomSettings.book || {};
                    var app = _roomSettings.app || {};
                    var snapshots = [1, 2].map(function(seat) {
                        var previous = session.turns.find(function(t) { return t.role === 'critic' && t.seat === seat; });
                        var recordedName = previous && String(previous.label || '').replace(/\s*·\s*(?:Codex|Claude).*$/, '').trim();
                        if (/^Critic\s*[12]$/i.test(recordedName || '')) recordedName = '';
                        var config = app['critic' + seat] || {};
                        var agent = previous ? previous.agent : config.agent || (seat === 1 ? 'codex' : 'claude');
                        return {id: 'legacy-' + seat, name: recordedName || book['critic' + seat + '_name'] || (seat === 1 ? 'Story Editor' : 'Voice Editor'),
                            specialty: book['critic' + seat + '_prompt'] || '', style: '',
                            agent: agent, model: config.agent === agent ? config.model || '' : '', effort: config.agent === agent ? config.effort || '' : ''};
                    });
                    session.participants = _roomSnapshotPair(snapshots);
                }
                var savedPlans = Array.isArray(saved.plans) && saved.plans.length ? saved.plans
                    : ((saved.plan || []).length || (saved.open || []).length || saved.authors_call)
                        ? [{after_turn: session.turns.length, items: saved.plan || [], open: saved.open || [], authors_call: saved.authors_call || ''}]
                        : [];
                session.plans = savedPlans.map(function(plan, pIdx) {
                    return {
                        id: 'plan-' + pIdx,
                        afterTurn: plan.after_turn || session.turns.length,
                        agent: plan.agent || '',
                        items: (plan.items || []).map(_roomPlanItem),
                        open: plan.open || [],
                        authorsCall: plan.authors_call || '',
                        expanded: false
                    };
                });
                session.busy = false;
                session.statusText = '';
                session.error = '';
                session.queue = [];
                session.live = null;
                _roomHistoryOpen = false;
                return attachManagedRoom(session).then(function() { if (scenePath === _roomCurrentScenePath()) renderSceneRoomPane(); });
            }).catch(function(error) { var session = _roomSessionFor(scenePath); session.error = error.message; if (scenePath === _roomCurrentScenePath()) renderSceneRoomPane(); });
        }

        function deleteRoomHistorySession(scenePath, sessionId) {
            _roomHistoryRequest({action: 'delete', id: sessionId}).then(function() {
                delete _roomHistoryList[scenePath];
                var session = _roomSessionsByScene[scenePath];
                if (session && session.id === sessionId && !session.busy) {
                    delete _roomSessionsByScene[scenePath];
                }
                renderSceneRoomPane();
            }).catch(function() {});
        }

        function _restoreLatestRoomSession(scenePath) {
            if (_roomHistoryChecked[scenePath]) return;
            _roomHistoryChecked[scenePath] = true;
            var pending = _roomSessionsByScene[scenePath];
            if (pending && (pending.outbox || []).length) {
                var request = pending.outbox[0];
                roomRuntimeRequest(pending, {action: 'state', room_id: request.room_id, initial: request.initial})
                    .then(function() { drainRoomOutbox(pending); })
                    .catch(function(error) { pending.sendError = error.message; renderSceneRoomPane(); });
                return;
            }
            var draftAtStart = _roomDraftInput;
            _loadRoomHistoryList(scenePath).then(function(rows) {
                var session = _roomSessionsByScene[scenePath];
                if (!rows.length || (session && (session.turns.length || session.busy)) || (scenePath === _roomDraftScene && _roomDraftInput !== draftAtStart)) return;
                var selected = session && rows.find(function(row) { return row.id === session.id; });
                openRoomHistorySession(scenePath, (selected || rows[0]).id);
            });
        }

        function _formatRoomWhen(seconds) {
            if (!seconds) return '';
            var d = new Date(seconds * 1000);
            var today = new Date();
            if (d.toDateString() === today.toDateString()) {
                return d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
            }
            return d.toLocaleDateString([], {month: 'short', day: 'numeric'});
        }

        function _renderRoomHistoryMenu(body, scenePath, session) {
            var menu = elementWith('room-history-menu');
            menu.appendChild(elementWith('room-history-head', 'Previous debates on this scene'));
            var list = elementWith('room-history-list');
            list.appendChild(elementWith('room-history-empty', 'Loading\u2026'));
            menu.appendChild(list);
            body.appendChild(menu);
            _loadRoomHistoryList(scenePath).then(function(rows) {
                list.replaceChildren();
                if (!rows.length) {
                    list.appendChild(elementWith('room-history-empty', 'No saved debates yet.'));
                    return;
                }
                rows.forEach(function(row) {
                    var item = elementWith('room-history-item' + (row.id === session.id ? ' is-current' : ''));
                    var open = document.createElement('button');
                    open.type = 'button';
                    open.className = 'room-history-open';
                    open.append(
                        elementWith('room-history-title', row.title || 'Writers\u2019 Room'),
                        elementWith('room-history-meta', row.turns + (row.turns === 1 ? ' turn' : ' turns')
                            + (row.has_plan ? ' \u00b7 plan' : '') + ' \u00b7 ' + _formatRoomWhen(row.updated_at))
                    );
                    open.disabled = !!session.busy;
                    open.onclick = function() { openRoomHistorySession(scenePath, row.id); };
                    var del = document.createElement('button');
                    del.type = 'button';
                    del.className = 'room-history-delete';
                    del.textContent = '\u00d7';
                    del.setAttribute('aria-label', 'Delete this debate');
                    del.setAttribute('data-tip', 'Delete this debate');
                    del.onclick = function() { deleteRoomHistorySession(scenePath, row.id); };
                    item.append(open, del);
                    list.appendChild(item);
                });
            });
        }

        function stopRoomDebate() {
            var session = _roomSessionFor(_roomCurrentScenePath());
            if (session && session.managed) roomRuntimeControl(session, 'stop').catch(function() {});
        }

        function startRoomDebate(options) {
            options = options || {};
            var path = _roomCurrentScenePath();
            if (!path) return;
            var session = _roomSessionFor(path);
            if (session.busy) return;
            var library = (_roomSettings || {}).library;
            if (!library) return;
            if (!options.start) {
                var preset = library.presets.find(function(p) { return p.id === options.presetId; });
                if (!preset) return;
                session.pendingPreset = JSON.parse(JSON.stringify(preset));
                session.participants = _roomProfiles(preset.profiles);
                renderSceneRoomPane();
                return;
            }
            startManagedRoomPreset(session);
        }

        function _processRoomQueue(scenePath) {
            var session = _roomSessionFor(scenePath);
            if (session && session.managed) roomRuntimePoll(session);
        }

        // What the critic is doing while its turn runs, as the single chat
        // shows it: elapsed time, its progress notes and steps, and its reply
        // as it streams. Updated in place so the pane does not re-render.
        function _pollRoomProgress(session, runId, token) {
            var stopped = false;
            var timer = null;
            function tick() {
                if (stopped || _roomRunToken !== token) return;
                fetch('/api/discuss/room-progress', {
                    method: 'POST',
                    headers: pvHeaders(),
                    body: JSON.stringify({run_id: runId})
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (stopped || _roomRunToken !== token || !session.live) return;
                    if (data && data.ok && data.running) {
                        session.live.elapsed = data.elapsed || 0;
                        session.live.progress = data.progress || '';
                        session.live.steps = Array.isArray(data.steps) ? data.steps : [];
                        session.live.draft = data.draft || '';
                        session.live.conversationId = data.conversation_id || '';
                        session.live.approvals = data.approvals || [];
                        _renderRoomLive();
                    }
                }).catch(function() {}).then(function() {
                    if (!stopped) timer = setTimeout(tick, 800);
                });
            }
            timer = setTimeout(tick, 400);
            return function() {
                stopped = true;
                if (timer) clearTimeout(timer);
            };
        }

        // Critics cite "line 54" as plain text; this links it to the scene, the
        // way a Codex answer links its own citations, whichever agent wrote it.
        function _roomLinkLines(text, scenePath) {
            var abs = String(((typeof meta !== 'undefined' && meta[scenePath]) || {}).abs_path || '');
            if (!abs) return String(text || '');
            return String(text || '').split(/(\[[^\]]*\]\([^)]*\)|`[^`]*`)/).map(function(part, idx) {
                if (idx % 2 === 1) return part;
                return part.replace(/\b(lines?)\s+(\d+)(\s*[\u2013-]\s*\d+)?/gi, function(all, word, start) {
                    return '[' + all + '](<' + abs + ':' + start + '>)';
                });
            }).join('');
        }

        function _formatRoomElapsed(seconds) {
            var s = Math.max(0, Math.floor(seconds || 0));
            return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
        }

        function _renderRoomLive() {
            var session = _roomSessionFor(_roomCurrentScenePath());
            var live = session && session.live;
            var textEl = document.getElementById('roomLiveStatusText');
            var box = document.getElementById('roomLiveProgress');
            if (!live || !textEl || !box) return;
            textEl.textContent = (session.statusText || 'Thinking\u2026')
                + (live.elapsed ? ' \u00b7 ' + _formatRoomElapsed(live.elapsed) : '');
            box.textContent = '';
            if (live.steps.length) {
                var steps = elementWith('room-live-steps');
                live.steps.forEach(function(step) {
                    // Codex wraps every command in a login shell; the command is the step.
                    var shown = String(step).replace(/^\/bin\/(?:ba|z)?sh -lc\s+/, '').replace(/^(['"])([\s\S]*)\1$/, '$2');
                    steps.appendChild(elementWith('room-live-step', shown));
                });
                box.appendChild(steps);
            }
            var quietPass = live.draft && '[ROOM_PASS]'.startsWith(live.draft.trim().toUpperCase());
            if (live.draft && !quietPass) {
                var draft = elementWith('room-live-draft room-turn-body discuss-message assistant');
                renderDiscussMarkdown(draft, _roomLinkLines(live.draft, session.scene));
                box.appendChild(draft);
            } else if (live.progress) {
                var note = live.progress.length > 400 ? '\u2026' + live.progress.slice(-400) : live.progress;
                var noteEl = elementWith('room-live-note room-turn-body');
                renderDiscussMarkdown(noteEl, note);
                box.appendChild(noteEl);
            }
            box.hidden = !box.childNodes.length;
            var approvals = document.getElementById('roomLiveApprovals');
            if (approvals) {
                var key = JSON.stringify(live.approvals || []);
                if (approvals.dataset.state !== key) {
                    approvals.dataset.state = key;
                    approvals.replaceChildren();
                    (live.approvals || []).forEach(function(approval) {
                        approvals.appendChild(renderDiscussApproval(approval, function(requestId, decision, button, permissions) {
                            button.disabled = true;
                            var payload = {decision: decision};
                            if (permissions && (decision === 'accept' || decision === 'accept_for_session')) payload.permissions = permissions;
                            discussApi('/api/discuss/conversations/' + encodeURIComponent(live.conversationId) + '/approvals/' + encodeURIComponent(requestId), payload)
                                .then(function() { live.approvals = []; _renderRoomLive(); })
                                .catch(function(error) { button.disabled = false; approvals.appendChild(elementWith('room-error-text', error.message)); });
                        }));
                    });
                }
            }
        }

        function runRoomPlusOneTurn() {
            var session = _roomSessionFor(_roomCurrentScenePath());
            if (!session || session.busy) return;
            var last = session.turns.filter(function(turn) { return turn.role === 'critic'; }).slice(-1)[0];
            var seat = last && last.seat === 1 ? 2 : 1;
            roomRuntimeControl(session, 'submit', {message_id: _roomNewId(), text: '@' + session.participants[seat - 1].handle + ' continue the discussion.', seats: [seat]}).catch(function() {});
        }

        function sendRoomComposerMessage() { return submitRoomComposerMessage(); }

        function insertRoomPlanTodo(item) {
            var path = _roomCurrentScenePath();
            if (!path || !item || item.todoAdded) return;
            var todoText = (item.title
                + (item.replacement ? ' \u2014 replace with: \u201c' + item.replacement + '\u201d' : '')
                + (item.detail ? ' \u2014 ' + item.detail : '')).replace(/-->/g, '').trim();
            if (!todoText) return;

            // If ProseMirror editor is open in Edit mode, insert annotation directly.
            if (window._pmEditMode === true && typeof _proseEditorView !== 'undefined' && _proseEditorView && typeof PM !== 'undefined' && PM.mySchema && PM.mySchema.nodes.annotation) {
                try {
                    var state = _proseEditorView.state;
                    var node = PM.mySchema.nodes.annotation.create({raw: '<!-- TODO: ' + todoText + ' -->'});
                    var pos = state.selection.$to.after(1);
                    _proseEditorView.dispatch(state.tr.insert(pos, node));
                    item.todoAdded = true;
                    _saveRoomSession(_roomSessionFor(path));
                    renderSceneRoomPane();
                    if (typeof sidebarShowToast === 'function') sidebarShowToast('Added TODO to scene');
                    return;
                } catch (e) {}
            }

            var m = (typeof meta !== 'undefined' && meta[path]) || null;
            if (!m || !m.abs_path) return;
            var rawScene = (typeof contents !== 'undefined' && contents[path]) ? String(contents[path]) : '';
            var rawParas = rawScene.split(/\n\s*\n/).map(function(s) { return s.trim(); }).filter(function(s) {
                return s && !s.startsWith('#') && !s.startsWith('<!--');
            });
            var anchorText = '';
            if (item.original) {
                var originalNeedle = item.original.split('\n')[0].trim().slice(0, 120);
                if (originalNeedle && rawScene.indexOf(originalNeedle) >= 0) anchorText = originalNeedle;
            }
            var combined = (item.title + ' ' + item.detail);
            var quoteMatch = combined.match(/["\u201c\u2018']([^"\u201d\u2019']{6,80})["\u201d\u2019']/);
            if (!anchorText && quoteMatch && quoteMatch[1]) {
                var needle = quoteMatch[1].trim();
                if (rawScene.indexOf(needle) >= 0) anchorText = needle;
            }
            if (!anchorText && rawParas.length) {
                anchorText = rawParas[0];
            }
            if (!anchorText) return;

            fetch('/insert-todo', {
                method: 'POST',
                headers: pvHeaders(),
                body: JSON.stringify({
                    abs_path: m.abs_path,
                    selection_text: anchorText,
                    txt_line_offset: m.txt_line_offset || 0,
                    todo_text: todoText,
                    open_mtime: null
                })
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (data && data.ok) {
                    item.todoAdded = true;
                    _saveRoomSession(_roomSessionFor(path));
                    renderSceneRoomPane();
                    if (typeof sidebarShowToast === 'function') sidebarShowToast('Added TODO to scene');
                }
            }).catch(function() {});
        }

        function applyRoomPlanWithAgent(agent, plan) {
            var path = _roomCurrentScenePath();
            var session = _roomSessionFor(path);
            plan = plan || _roomLatestPlan(session);
            if (!session || !plan) return;
            var ticked = plan.items.filter(function(item) { return item.checked && !item.applied; });
            if (!ticked.length) return;
            var targetAgent = (agent === 'codex' || agent === 'claude') ? agent : 'claude';
            ticked.forEach(function(item) {
                item.applied = _roomAgentDisplay(targetAgent);
                item.checked = false;
            });
            _saveRoomSession(session);
            var lines = ticked.map(function(item, idx) {
                var where = item.line ? ' (line ' + item.line + ')' : '';
                var change = '';
                if (item.original && item.replacement) {
                    change = '\n   Replace: \u201c' + item.original + '\u201d\n   With: \u201c' + item.replacement + '\u201d';
                } else if (item.replacement) {
                    change = '\n   Insert: \u201c' + item.replacement + '\u201d';
                } else if (item.original) {
                    change = '\n   Cut: \u201c' + item.original + '\u201d';
                }
                return (idx + 1) + '. ' + item.title + where + (item.detail ? ': ' + item.detail : '') + change;
            });
            var instruction = 'Please revise this scene to apply the following Writers\u2019 Room revision plan:\n' + lines.join('\n');

            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            if (_discussAgent !== targetAgent) {
                _discussSkillsLoaded = false;
                _discussSkillsLoading = null;
                _discussSkills = [];
            }
            _discussAgent = targetAgent;
            try { localStorage.setItem(DISCUSS_AGENT_KEY, targetAgent); } catch (e) {}
            _applyDiscussAgentLabels();
            openDiscuss(null, {sendInstruction: instruction});
        }

        function _renderRoomPresetPreview(session, container) {
            var preset = session.pendingPreset;
            var preview = elementWith('room-preset-preview');
            preview.id = 'roomPresetPreview';
            var title = document.createElement('strong'); title.textContent = preset.name; preview.appendChild(title);
            if (preset.description) { var description = document.createElement('p'); description.textContent = preset.description; preview.appendChild(description); }
            var countLabel = document.createElement('label');
            countLabel.textContent = 'Invitations ';
            var count = document.createElement('select');
            count.className = 'room-target-select';
            count.setAttribute('aria-label', 'Preset invitations');
            for (var n = 2; n <= 12; n++) {
                var option = document.createElement('option'); option.value = String(n); option.textContent = String(n); count.appendChild(option);
            }
            count.value = String(preset.invitations.length);
            count.onchange = function() { _rmResizeInvitations(preset, Number(count.value)); renderSceneRoomPane(); };
            countLabel.appendChild(count); preview.appendChild(countLabel);
            var list = document.createElement('ol');
            preset.invitations.forEach(function(step) {
                var item = document.createElement('li');
                item.textContent = '@' + session.participants[step.seat - 1].handle + ', ' + step.prompt;
                list.appendChild(item);
            });
            preview.appendChild(list);
            var recapLabel = document.createElement('label'); recapLabel.textContent = 'Optional recap ';
            var recap = document.createElement('select'); recap.className = 'room-target-select'; recap.setAttribute('aria-label', 'Preset recap');
            [{value: 0, name: 'No recap'}].concat(session.participants.map(function(p) { return {value: p.seat, name: p.name + ' · ' + _roomAgentDisplay(p.agent)}; })).forEach(function(p) {
                var option = document.createElement('option'); option.value = String(p.value); option.textContent = p.name; recap.appendChild(option);
            });
            recap.value = String(preset.recap); recap.onchange = function() { preset.recap = Number(recap.value); };
            recapLabel.appendChild(recap); preview.appendChild(recapLabel);
            var actions = elementWith('room-preset-actions');
            var start = document.createElement('button'); start.type = 'button'; start.id = 'roomStartPresetBtn'; start.className = 'room-send-btn'; start.textContent = 'Start discussion';
            start.onclick = function() { startRoomDebate({start: true}); };
            var cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'room-header-btn'; cancel.textContent = 'Cancel';
            cancel.onclick = function() { session.pendingPreset = null; renderSceneRoomPane(); };
            actions.append(start, cancel); preview.appendChild(actions); container.appendChild(preview);
        }

        function renderSceneRoomPane() {
            const pane = document.getElementById('sceneRoomPane');
            if (!pane) return;
            const path = _roomCurrentScenePath();
            if (!path) {
                pane.replaceChildren(_scenePanelEmpty('Open a scene to run the Writers\u2019 Room.'));
                return;
            }
            if (!_roomSettings) {
                pane.replaceChildren(_scenePanelEmpty('Loading Room profiles…'));
                _ensureRoomSettingsLoaded().then(function() {
                    if (!pane.querySelector('#roomInput')) renderSceneRoomPane();
                }).catch(function(error) { pane.replaceChildren(_scenePanelEmpty(error.message)); });
                return;
            }

            var prevInput = document.getElementById('roomInput');
            var inputFocus = prevInput && document.activeElement === prevInput ? {start: prevInput.selectionStart, end: prevInput.selectionEnd} : null;
            if (prevInput) { _roomDraftInput = prevInput.value; _roomSaveDraft(_roomDraftScene); }
            _roomLoadDraft(path);

            // Every change redraws the pane, so keep the reader where they were:
            // following the debate if they were at the bottom, else in place.
            // Read from the last scroll, not the old pane: a pane hidden behind
            // another tab (after Apply opens the chat) reports a scroll of 0.
            var keepScroll = _roomScrollByScene[path] || null;
            pane.replaceChildren();
            var session = _roomSessionFor(path);
            _restoreLatestRoomSession(path);
            _roomEnsureParticipants(session);

            // 1. Header strip
            var header = elementWith('room-header-strip');
            var summary = elementWith('room-header-summary', _roomHeaderSummaryText());
            summary.id = 'roomHeaderSummary';
            var actions = elementWith('room-header-actions');
            if (session.turns.length > 0 || session.busy || session.error || session.managed) {
                var resetBtn = document.createElement('button');
                resetBtn.type = 'button';
                resetBtn.id = 'roomResetBtn';
                resetBtn.className = 'room-header-btn';
                resetBtn.textContent = '\u21ba New';
                resetBtn.setAttribute('data-tip', 'Clear this room session and return to the starter cards');
                resetBtn.onclick = resetRoomSession;
                resetBtn.disabled = session.busy;
                actions.appendChild(resetBtn);
            }
            var historyBtn = document.createElement('button');
            historyBtn.type = 'button';
            historyBtn.id = 'roomHistoryBtn';
            historyBtn.className = 'room-header-btn' + (_roomHistoryOpen ? ' is-active' : '');
            historyBtn.textContent = 'History';
            historyBtn.setAttribute('aria-expanded', _roomHistoryOpen ? 'true' : 'false');
            historyBtn.setAttribute('data-tip', 'Open a previous Writers\u2019 Room debate on this scene');
            historyBtn.onclick = function() {
                _roomHistoryOpen = !_roomHistoryOpen;
                renderSceneRoomPane();
            };
            actions.appendChild(historyBtn);
            var gearBtn = document.createElement('button');
            gearBtn.type = 'button';
            gearBtn.id = 'roomSettingsBtn';
            gearBtn.className = 'room-header-btn';
            gearBtn.textContent = '\u2699 Settings';
            gearBtn.setAttribute('data-tip', 'Choose reusable profiles and discussion presets in Settings → Writers’ Room');
            gearBtn.onclick = function() {
                if (typeof openRoomSettings === 'function') openRoomSettings();
            };
            actions.appendChild(gearBtn);
            header.append(summary, actions);
            pane.appendChild(header);

            // 2. Scrollable body
            var body = elementWith('room-body');
            body.id = 'roomBody';
            if (_roomHistoryOpen) _renderRoomHistoryMenu(body, path, session);

            if (session.turns.length === 0 && !session.busy && !session.error && !(session.outbox || []).length) {
                var empty = elementWith('discuss-empty room-empty');
                var title = document.createElement('strong');
                title.textContent = session.pendingPreset ? 'Preview discussion' : 'What should we discuss?';
                empty.appendChild(title);
                empty.appendChild(document.createTextNode(session.pendingPreset ? 'Review the participants and invitations before starting.' : 'Choose participants, then type a message or preview a discussion preset.'));
                var pairPicker = elementWith('room-participant-picker');
                _roomPairPicker(session, pairPicker, function(ids) { if (session.pendingPreset) session.pendingPreset.profiles = ids; });
                empty.appendChild(pairPicker);
                if (session.pendingPreset) {
                    _renderRoomPresetPreview(session, empty);
                } else {

                var presets = _roomSettings ? _roomSettings.presets : [];
                var groups = [];
                presets.forEach(function(card) {
                    var g = groups.find(function(item) { return item.name === card.group; });
                    if (!g) { g = {name: card.group, cards: []}; groups.push(g); }
                    g.cards.push(card);
                });
                groups.forEach(function(g) {
                    empty.appendChild(elementWith('discuss-story-group', g.name));
                    var list = elementWith('discuss-story-actions');
                    g.cards.forEach(function(card) {
                        var btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = 'discuss-story-action room-starter-card';
                        btn.dataset.preset = card.id;
                        var head = elementWith('room-starter-head');
                        head.append(
                            elementWith('discuss-story-action-title', card.label),
                            elementWith('room-starter-badge', card.badge)
                        );
                        btn.append(head, elementWith('discuss-story-action-copy', card.copy));
                        btn.onclick = function() {
                            startRoomDebate({presetId: card.id, label: card.label, badge: card.badge});
                        };
                        list.appendChild(btn);
                    });
                    empty.appendChild(list);
                });
                }
                body.appendChild(empty);
            } else {
                // Active session topic banner
                if (session.topicLabel || session.question) {
                    var banner = elementWith('room-topic-banner');
                    var bannerTop = elementWith('room-topic-top');
                    bannerTop.appendChild(elementWith('room-topic-title', session.topicLabel || 'Writers\u2019 Room'));
                    if (session.topicBadge) {
                        bannerTop.appendChild(elementWith('room-topic-badge', session.topicBadge));
                    }
                    banner.appendChild(bannerTop);
                    if (session.question && session.presetId) {
                        banner.appendChild(elementWith('room-topic-question', session.question));
                    } else if (session.question && !session.presetId) {
                        banner.appendChild(elementWith('room-topic-question', '\u201c' + session.question + '\u201d'));
                    }
                    body.appendChild(banner);
                }

                // Turns list
                var turnsWrap = elementWith('room-turns-list');
                var placedPlans = {};
                var appendPlansAfter = function(count) {
                    (session.plans || []).forEach(function(plan, pIdx) {
                        if (placedPlans[pIdx] || plan.afterTurn !== count) return;
                        placedPlans[pIdx] = true;
                        turnsWrap.appendChild(_buildRoomPlanCard(session, plan, pIdx === session.plans.length - 1, path));
                    });
                };
                session.turns.forEach(function(turn, turnIdx) {
                    if (turn.passed) {
                        if (turn.review_pending && turn.tool_conversation_id) turnsWrap.appendChild(_roomToolReview(session, turn));
                    if (turn.review_unavailable) turnsWrap.appendChild(elementWith('room-runtime-notice', 'An older review is unavailable after the restart. Your changes remain saved; use file history to inspect them.'));
                        appendPlansAfter(turnIdx + 1); return;
                    }
                    if (turn.role === 'invitation') {
                        var invitation = elementWith('room-preset-invitation');
                        invitation.append(elementWith('room-preset-label', turn.label || 'Preset'), elementWith('room-preset-text', turn.text));
                        highlightChatMentions(invitation, session.participants);
                        turnsWrap.appendChild(invitation);
                        appendPlansAfter(turnIdx + 1);
                        return;
                    }
                    if (turn.role === 'user') {
                        var uCard = elementWith('room-turn-card chat-message-card is-user');
                        var uHead = elementWith('room-turn-head chat-message-header');
                        uHead.appendChild(elementWith('chat-message-name', 'Me'));
                        uCard.appendChild(uHead);
                        var uBody = elementWith('room-turn-body discuss-message');
                        renderDiscussMarkdown(uBody, turn.text);
                        highlightChatMentions(uBody, session.participants);
                        uCard.appendChild(uBody);
                        addCopyButton(uCard, function() { return turn.text; }, 'Copy message');
                        turnsWrap.appendChild(uCard);
                        appendPlansAfter(turnIdx + 1);
                        return;
                    }
                    var seatCls = turn.seat === 2 ? 'is-critic-2' : 'is-critic-1';
                    var card = elementWith('room-turn-card chat-message-card ' + seatCls);
                    var head = elementWith('room-turn-head chat-message-header');
                    var left = elementWith('room-turn-head-left');
                    left.appendChild(elementWith('chat-message-name', _roomSpeakerName(turn.seat, turn.agent)));
                    if (turn.tag) left.appendChild(elementWith('room-turn-tag', turn.tag));
                    head.appendChild(left);
                    if (turn.model) head.appendChild(elementWith('room-turn-model', turn.model));
                    card.appendChild(head);
                    var textWrap = elementWith('room-turn-body discuss-message assistant');
                    renderDiscussMarkdown(textWrap, _roomLinkLines(turn.text, path));
                    highlightChatMentions(textWrap, session.participants);
                    card.appendChild(textWrap);
                    addCopyButton(card, function() { return turn.text; }, 'Copy message');
                    turnsWrap.appendChild(card);
                    if (turn.review_pending && turn.tool_conversation_id) turnsWrap.appendChild(_roomToolReview(session, turn));
                    if (turn.review_unavailable) turnsWrap.appendChild(elementWith('room-runtime-notice', 'An older review is unavailable after the restart. Your changes remain saved; use file history to inspect them.'));
                    appendPlansAfter(turnIdx + 1);
                });
                // A plan whose turns were cut short still shows, at the end.
                (session.plans || []).forEach(function(plan, pIdx) {
                    if (!placedPlans[pIdx]) {
                        turnsWrap.appendChild(_buildRoomPlanCard(session, plan, pIdx === session.plans.length - 1, path));
                    }
                });
                body.appendChild(turnsWrap);

                // Live status spinner
                if (session.busy) {
                    var statusRow = elementWith('room-live-status');
                    statusRow.setAttribute('role', 'status');
                    var spin = elementWith('hl-card-spinner');
                    var statusMsg = elementWith('room-live-status-text', session.statusText || 'Thinking\u2026');
                    statusMsg.id = 'roomLiveStatusText';
                    var stopBtn = document.createElement('button');
                    stopBtn.type = 'button';
                    stopBtn.className = 'room-stop-btn';
                    stopBtn.textContent = 'Stop';
                    stopBtn.onclick = stopRoomDebate;
                    statusRow.append(spin, statusMsg, stopBtn);
                    body.appendChild(statusRow);
                    var liveBox = elementWith('room-live-progress');
                    liveBox.id = 'roomLiveProgress';
                    liveBox.hidden = true;
                    body.appendChild(liveBox);
                    var approvalsBox = elementWith('room-live-approvals');
                    approvalsBox.id = 'roomLiveApprovals';
                    body.appendChild(approvalsBox);
                    if (session.live) setTimeout(_renderRoomLive, 0);
                }

                // Error banner
                if (session.error) {
                    var errBox = elementWith('room-error-banner');
                    errBox.appendChild(elementWith('room-error-text', session.error));
                    body.appendChild(errBox);
                }

            }
            renderManagedRoomQueue(session, body);
            pane.appendChild(body);
            body.dataset.scene = path;
            body.addEventListener('scroll', function() {
                if (!body.isConnected || !body.clientHeight) return;
                _roomScrollByScene[path] = {
                    top: body.scrollTop,
                    atBottom: body.scrollHeight - body.scrollTop - body.clientHeight < 40
                };
            });
            if (keepScroll) {
                var restoreScroll = function() {
                    body.scrollTop = keepScroll.atBottom ? body.scrollHeight : keepScroll.top;
                };
                restoreScroll();
                // Again once the composer below has taken its share of the height.
                requestAnimationFrame(restoreScroll);
                setTimeout(restoreScroll, 60);
            }
            if (_roomLatestPlan(session)) _syncRoomApplyButton(session);

            // The Room uses the same composer controls, with one model choice per participant.
            pane.appendChild(createRoomComposer(session));
            if (session.managed) roomRuntimePoll(session);
            if (inputFocus) {
                var restoredInput = document.getElementById('roomInput');
                restoredInput.focus({preventScroll: true});
                restoredInput.setSelectionRange(inputFocus.start, inputFocus.end);
            }
        }


        function _buildRoomPlanCard(session, plan, isLatest, path) {
            var planCard = elementWith('room-plan-card' + (isLatest ? ' is-latest' : ''));
            if (isLatest) planCard.id = 'roomPlanCard';
            var applied = plan.items.filter(function(item) { return item.applied; }).length;
            var planHead = elementWith('room-plan-head');
            planHead.append(
                elementWith('room-plan-title', 'Revision plan'),
                elementWith('room-plan-sub', isLatest
                    ? (plan.agent ? _roomSpeakerName('moderator', plan.agent) : _roomSeatName('moderator') + ' \u00b7 agent not recorded') + ' \u00b7 choose changes to apply or add as TODO'
                    : 'Earlier plan \u00b7 ' + plan.items.length + (plan.items.length === 1 ? ' item' : ' items')
                        + (applied ? ' \u00b7 ' + applied + ' applied' : ''))
            );
            planCard.appendChild(planHead);
            // Earlier plans fold to their heading; their line numbers may be
            // out of date once later changes are applied.
            if (!isLatest) {
                var toggle = document.createElement('button');
                toggle.type = 'button';
                toggle.className = 'room-plan-toggle';
                toggle.textContent = plan.expanded ? 'Hide' : 'Show';
                toggle.setAttribute('aria-expanded', plan.expanded ? 'true' : 'false');
                toggle.onclick = function() {
                    plan.expanded = !plan.expanded;
                    renderSceneRoomPane();
                };
                planHead.appendChild(toggle);
                if (!plan.expanded) return planCard;
            }

            var groups = {};
            ['agreed', 'suggested'].forEach(function(kind) {
                var section = document.createElement('section');
                section.className = 'room-plan-section';
                section.dataset.consensus = kind;
                var title = document.createElement('h3');
                title.className = 'room-plan-section-title';
                title.textContent = kind === 'agreed' ? 'Agreed changes' : 'Other suggestions';
                section.setAttribute('aria-label', title.textContent);
                section.appendChild(title);
                var list = elementWith('room-plan-list');
                section.appendChild(list);
                groups[kind] = {section: section, list: list};
            });
            plan.items.forEach(function(item) {
                var row = elementWith('room-plan-item' + (item.applied ? ' is-applied' : ''));
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.className = 'room-plan-check';
                cb.checked = !!item.checked || !!item.applied;
                cb.disabled = !!item.applied;
                cb.setAttribute('aria-label', item.title);
                var content = elementWith('room-plan-item-text');
                var b = document.createElement('strong');
                b.textContent = item.title;
                content.appendChild(b);
                if (item.original || item.replacement) {
                    // The change itself, the way the critics write it: the line,
                    // the scene's words in italics, the new words plain.
                    var md = [];
                    if (item.line) md.push('Line ' + item.line + (item.replacement ? (item.original ? '' : ', insert:') : ', cut:'));
                    if (item.original) md.push(item.original.split('\n').map(function(l) { return '> *' + l.trim() + '*'; }).join('\n>\n'));
                    if (item.replacement) md.push(item.replacement.split('\n').map(function(l) { return '> ' + l; }).join('\n'));
                    if (item.detail) md.push(item.detail);
                    var change = elementWith('room-plan-change discuss-message assistant');
                    renderDiscussMarkdown(change, _roomLinkLines(md.join('\n\n'), path));
                    content.appendChild(change);
                } else if (item.detail) {
                    content.appendChild(document.createTextNode(' \u2014 ' + item.detail));
                }
                if (item.proposedBy || item.applied) {
                    content.appendChild(elementWith('room-plan-by',
                        (item.applied ? '\u2713 Applied with ' + item.applied + (item.proposedBy ? ' \u00b7 ' : '') : '')
                        + (item.proposedBy ? _roomProposerName(item.proposedBy) + (item.accepted ? ' \u00b7 both agree' : ' \u00b7 not yet endorsed by both editors') : '')));
                }
                var todoBtn = document.createElement('button');
                todoBtn.type = 'button';
                todoBtn.className = 'room-todo-btn' + (item.todoAdded ? ' is-added' : '');
                todoBtn.textContent = item.todoAdded ? '\u2713 TODO' : '+ TODO';
                todoBtn.disabled = !!item.todoAdded || !!item.applied;
                todoBtn.setAttribute('data-tip', 'Insert an inline <!-- TODO: ... --> comment for this item into the scene');
                todoBtn.onclick = function() { insertRoomPlanTodo(item); };

                cb.onchange = function() {
                    item.checked = cb.checked;
                    if (isLatest) _syncRoomApplyButton(session);
                    _saveRoomSession(session);
                };
                row.append(cb, content, todoBtn);
                groups[item.accepted ? 'agreed' : 'suggested'].list.appendChild(row);
            });
            ['agreed', 'suggested'].forEach(function(kind) {
                if (groups[kind].list.childNodes.length) planCard.appendChild(groups[kind].section);
            });
            if (!plan.items.length && !(plan.open || []).length && !plan.authorsCall) {
                planCard.appendChild(elementWith('room-plan-empty', 'No new changes to suggest.'));
            }

            if (plan.open && plan.open.length) {
                var openBox = elementWith('room-open');
                openBox.appendChild(elementWith('room-open-title', 'Still open \u00b7 your call'));
                plan.open.forEach(function(item) {
                    var openItem = elementWith('room-open-item');
                    openItem.appendChild(elementWith('room-open-issue', item.issue || ''));
                    [['Critic 1', item.critic1], ['Critic 2', item.critic2]].forEach(function(pair) {
                        if (!pair[1]) return;
                        var line = elementWith('room-open-side');
                        var who = document.createElement('strong');
                        who.textContent = _roomProposerName(pair[0]) + ': ';
                        line.append(who, document.createTextNode(pair[1]));
                        openItem.appendChild(line);
                    });
                    openBox.appendChild(openItem);
                });
                planCard.appendChild(openBox);
            }

            if (plan.authorsCall) {
                var callBox = elementWith('room-authors-call');
                var callTitle = document.createElement('strong');
                callTitle.textContent = 'Author\u2019s Call (Unresolved trade-off): ';
                callBox.append(callTitle, document.createTextNode(plan.authorsCall));
                planCard.appendChild(callBox);
            }
            if (!isLatest || session.busy) return planCard;

            var app = (_roomSettings && _roomSettings.app) || {};
            _roomApplyAgentChoice = _roomApplyAgentChoice
                || ((app.critic2 || {}).agent)
                || ((app.critic1 || {}).agent)
                || 'claude';

            var actBar = elementWith('room-plan-actions');
            var applyLabel = elementWith('room-apply-label', 'Apply with:');
            var agentSelect = document.createElement('select');
            agentSelect.id = 'roomApplyAgentSelect';
            agentSelect.className = 'room-apply-select';
            agentSelect.setAttribute('aria-label', 'Agent to apply ticked revisions');
            [{id: 'claude', label: 'Claude'}, {id: 'codex', label: 'Codex'}].forEach(function(a) {
                var opt = document.createElement('option');
                opt.value = a.id;
                opt.textContent = a.label;
                agentSelect.appendChild(opt);
            });
            agentSelect.value = _roomApplyAgentChoice;
            agentSelect.onchange = function() {
                _roomApplyAgentChoice = agentSelect.value;
                _syncRoomApplyButton(session);
            };

            var applyBtn = document.createElement('button');
            applyBtn.type = 'button';
            applyBtn.id = 'roomApplyBtn';
            applyBtn.className = 'room-apply-btn';
            applyBtn.onclick = function() {
                applyRoomPlanWithAgent(_roomApplyAgentChoice, plan);
            };

            var moreBtn = document.createElement('button');
            moreBtn.type = 'button';
            moreBtn.id = 'roomMoreTurnBtn';
            moreBtn.className = 'room-more-turn-btn';
            moreBtn.textContent = '+1 Turn';
            moreBtn.setAttribute('data-tip', 'Ask the other critic to respond one more time, then update the plan');
            moreBtn.onclick = runRoomPlusOneTurn;

            actBar.append(applyLabel, agentSelect, applyBtn, moreBtn);
            planCard.appendChild(actBar);
            return planCard;
        }

        function _syncRoomApplyButton(session) {
            var btn = document.getElementById('roomApplyBtn');
            if (!btn || !session) return;
            var latest = _roomLatestPlan(session);
            var count = (latest ? latest.items : []).filter(function(item) { return item.checked && !item.applied; }).length;
            var agentLabel = _roomAgentDisplay(_roomApplyAgentChoice || 'claude');
            btn.disabled = count === 0;
            btn.textContent = count > 0
                ? ('Apply ' + count + ' ticked ' + (count === 1 ? 'item' : 'items') + ' with ' + agentLabel + ' \u2192')
                : 'Tick an item to apply';
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
            // Words and variety have no check to switch, so they are one
            // quiet line at the top; every other measure sits in its check's row.
            pane.appendChild(_sceneSummaryLine(path));
            // The sentence-length strip needs the scene's editor, which may
            // mount after this pane; refreshSceneRhythm fills it in then.
            pane.appendChild(_scenePanelHeading('Sentence length'));
            const rhythm = typeof sceneRhythmStrip === 'function' ? sceneRhythmStrip(path) : null;
            if (rhythm) pane.appendChild(rhythm);
            else {
                const slot = document.createElement('div');
                slot.className = 'rhythm';
                slot.id = 'sceneRhythm';
                pane.appendChild(slot);
            }
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

        // The passes, grouped by what they look at. A group with no passes
        // shows no heading. A pass missing from every group lands in the last.
        // In the order novelists reach for them, groups and rows alike; the
        // order is fixed, so a check is always where it was last time.
        const SCENE_PASS_GROUPS = [
            {heading: 'Words', passes: ['echoes', 'crutch_words', 'sensory', 'filter_verbs', 'repeats']},
            {heading: 'Dialogue', passes: ['dialogue_tags', 'dialogue']},
            {heading: 'Style', passes: ['passive_voice', 'sticky_sentences', 'first_person']},
            {heading: 'Rhythm', passes: ['sentence_starts']}
        ];
        // Word-list passes that flag every "like", "never" or colour word.
        // Folded away by default; they are off unless the reader turned them on.
        const SCENE_PASS_MORE = ['lyrical', 'hyperbole'];
        let scenePassMoreOpen = null;

        // One row per check: a switch, the name, its examples, its rate where
        // it has one, and how many matches this scene has. A zero row says
        // "nothing here" without being clicked.
        function _scenePassList(path) {
            const list = document.createElement('div');
            list.className = 'scene-pass-list';
            list.id = 'scenePassList';
            const loaded = typeof highlightsByPath !== 'undefined' && highlightsByPath[path];
            const byPass = (loaded || {}).highlights || {};
            // Until the scene's marks arrive, the counts the page carries.
            const counts = (typeof highlightCounts !== 'undefined' && highlightCounts[path]) || {};
            const known = SCENE_PASS_MORE.slice();
            SCENE_PASS_GROUPS.forEach(function(g) { known.push.apply(known, g.passes); });
            const groups = SCENE_PASS_GROUPS.map(function(g) {
                return {heading: g.heading, passes: g.passes.filter(function(p) { return PASS_ORDER.indexOf(p) !== -1; })};
            });
            PASS_ORDER.forEach(function(p) {
                if (known.indexOf(p) === -1) groups[groups.length - 1].passes.push(p);
            });
            function rows(names) {
                return names.map(function(name) {
                    const hits = byPass[name];
                    // An echo is a group of marks; its row counts the groups.
                    const n = !Array.isArray(hits) ? (loaded ? 0 : (counts[name] || 0))
                        : name === 'echoes' ? new Set(hits.map(function(h) { return String(h.note || '').split(' \u00b7 ')[0]; })).size
                        : hits.length;
                    return {name: name, count: n};
                }).reduce(function(out, entry) {
                    out.push(_scenePassRow(entry.name, entry.count, path, counts));
                    if (PASS_BREAKDOWNS[entry.name]) out.push(_scenePassBreakdown(entry.name, byPass[entry.name], (loaded || {}).stats));
                    return out;
                }, []);
            }
            let first = true;
            groups.forEach(function(g) {
                if (!g.passes.length) return;
                const h = document.createElement('p');
                h.className = 'scene-pass-group';
                h.textContent = g.heading;
                // Clear sits at the end of the first group's line, seen only
                // while some check is on; its place is kept so nothing moves.
                if (first) {
                    const clear = document.createElement('button');
                    clear.type = 'button';
                    clear.id = 'scenePassAllBtn';
                    clear.className = 'scene-pass-all';
                    clear.textContent = 'Clear';
                    clear.title = 'Turn every check off';
                    clear.onclick = function() { if (PASS_ORDER.some(function(k) { return hls[k]; })) toggleAllHighlights(); };
                    h.appendChild(clear);
                    first = false;
                }
                list.appendChild(h);
                list.append.apply(list, rows(g.passes));
            });

            const more = SCENE_PASS_MORE.filter(function(p) { return PASS_ORDER.indexOf(p) !== -1; });
            if (more.length) {
                const details = document.createElement('details');
                details.className = 'scene-pass-more';
                details.id = 'scenePassMore';
                // Open when the reader opened it, or when one of its passes is on,
                // so a switched-on pass is never hidden.
                if (scenePassMoreOpen === null) scenePassMoreOpen = more.some(function(p) { return !!hls[p]; });
                details.open = scenePassMoreOpen;
                details.addEventListener('toggle', function() { scenePassMoreOpen = details.open; });
                const summary = document.createElement('summary');
                summary.textContent = 'More checks, off by default (' + more.length + ')';
                const note = document.createElement('p');
                note.className = 'scene-pass-more-note';
                note.textContent = 'They flag every “like” and “never”, so most hits aren’t problems.';
                details.append(summary, note);
                details.append.apply(details, rows(more));
                list.appendChild(details);
            }
            return list;
        }

        // A check's rate in this scene, worked out from its own marks so the
        // two always agree, against the book's typical scene counted the same
        // way. Null for a check with no rate.
        const SCENE_RATED_PASSES = ['passive_voice', 'first_person', 'crutch_words', 'sensory'];

        function _scenePassMeasure(name, count, path, counts) {
            const m = (typeof meta !== 'undefined' && meta[path]) || {};
            const md = (typeof medians !== 'undefined' && medians) || {};
            const stats = ((typeof highlightsByPath !== 'undefined' && highlightsByPath[path]) || {}).stats
                || {told_in_first_person: !!(counts && counts._told_first)};
            let value, text, typical, typicalText;
            if (name === 'dialogue') {
                value = m.dlg_pct || 0;
                text = value.toFixed(1) + '% of words';
                typical = md.dlg_pct;
                typicalText = typical !== undefined ? typical.toFixed(0) + '%' : '';
            } else if (SCENE_RATED_PASSES.indexOf(name) !== -1) {
                if (name === 'first_person' && stats.told_in_first_person) {
                    return {text: 'Told in first person, so nothing is marked', warn: false, typical: ''};
                }
                if (!m.words) return null;
                value = count * 1000 / m.words;
                text = value.toFixed(1) + ' per 1,000 words';
                typical = (md.pass_rates || {})[name];
                typicalText = typical !== undefined ? typical.toFixed(1) : '';
            } else {
                return null;
            }
            // Nothing found says so, muted, rather than as a rate of 0.
            if (!value) return {text: 'none', warn: false, typical: '', none: true};
            const warn = !!(typical) && (value > typical * 1.5 || value < typical * 0.5);
            return {text: text, warn: warn, typical: warn && typicalText ? 'vs typical ' + typicalText : ''};
        }

        // Words and the two variety scores, with their typical ranges on hover.
        function _sceneSummaryLine(path) {
            const m = (typeof meta !== 'undefined' && meta[path]) || {};
            const md = (typeof medians !== 'undefined' && medians) || {};
            // The same typical ranges the dashboard judges by (a top-level
            // const, not a property of window).
            const bands = lexicalBands;  // named as Settings → Word variety names them
            const line = document.createElement('p');
            line.className = 'scene-summary';
            line.id = 'sceneSummary';
            const part = function(before, value, after, title, warn) {
                const span = document.createElement('span');
                span.className = 'scene-summary-part' + (warn ? ' is-warn' : '');
                span.title = title;
                const b = document.createElement('b');
                b.textContent = value;
                span.append(before, b, after);
                return span;
            };
            const words = m.words || 0;
            const wordsWarn = !!(words && md.words) && (words > md.words * 1.5 || words < md.words * 0.5);
            line.appendChild(part('', words.toLocaleString(), ' words',
                'Words of prose in this scene.' + (md.words ? ' Your typical scene: ' + Math.round(md.words).toLocaleString() + '.' : ''), wordsWarn));
            line.append(' \u00b7 ');
            line.appendChild(part('Variety ', m.mattr ? m.mattr.toFixed(2) : '\u2026', '',
                'Word variety nearby (MATTR): how many different words a passage of 100 uses. Typical: ' + bands.mattr[0] + '\u2013' + bands.mattr[1] + '.',
                !!m.mattr && (m.mattr < bands.mattr[0] || m.mattr > bands.mattr[1])));
            line.append(' \u00b7 ');
            line.appendChild(part('MTLD ', m.mtld ? m.mtld.toFixed(1) : '\u2026', '',
                'Word variety across the whole scene (MTLD). Typical: ' + bands.mtld[0] + '\u2013' + bands.mtld[1] + '.',
                !!m.mtld && (m.mtld < bands.mtld[0] || m.mtld > bands.mtld[1])));
            // What the two variety scores are, behind one ⓘ at the line's end.
            const about = wordVarietyAbout(m.mattr, true);
            line.append(' ');
            line.append.apply(line, _sceneInfo('sceneSummaryInfo', 'About these numbers', about));
            return line;
        }

        // What Variety (MATTR) and MTLD are, how they are worked out, and the
        // ranges in use: the one text behind the scene line's ⓘ and Settings'
        // Word variety ⓘ. A scene's own Variety, when given, is the example;
        // pointToSettings ends it with where to change the ranges.
        function wordVarietyAbout(mattr, pointToSettings) {
            const bands = lexicalBands;  // named as Settings → Word variety names them
            const about = document.createElement('span');
            const para = function(name, text) {
                const p = document.createElement('span');
                p.className = 'scene-summary-about';
                const b = document.createElement('b');
                b.textContent = name;
                p.append(b, ' ' + text);
                return p;
            };
            const per100 = mattr ? ' ' + mattr.toFixed(2) + ' means about ' + Math.round(mattr * 100) + ' different words in each 100.' : '';
            about.append(
                para('Variety (MATTR)', 'How many different words a run of 100 words in a row uses, averaged over every such run in the scene.'
                    + per100 + ' Higher means fewer words come back close together. Typical: ' + bands.mattr[0] + '\u2013' + bands.mattr[1]
                    + ' (' + bands.label + ').'),
                para('MTLD', 'How many words, on average, the scene runs before its words start repeating: the count restarts each time the share of new words falls to 72%, read forwards and backwards. Unlike a plain ratio, a long scene isn\u2019t marked down for its length. Higher means more varied words across the whole scene. Typical: '
                    + bands.mtld[0] + '\u2013' + bands.mtld[1] + ' (' + bands.label + ').'),
                para('Amber', 'means outside the typical range.' + (pointToSettings ? ' Change it in Settings \u2192 Word variety.' : '')));
            return about;
        }

        // The variety scores arrive after the pane is drawn; the line follows.
        function refreshSceneSummary() {
            const old = document.getElementById('sceneSummary');
            const path = typeof paths !== 'undefined' ? paths[curIdx] : null;
            if (old && path) old.replaceWith(_sceneSummaryLine(path));
        }

        function _scenePassRow(name, count, path, counts) {
            const on = !!hls[name];
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'scene-pass-row' + (on ? ' is-on' : '') + (count ? '' : ' is-empty');
            row.id = 'pass-row-' + name;
            row.dataset.pass = name;
            row.setAttribute('aria-pressed', on ? 'true' : 'false');
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
            const measure = path ? _scenePassMeasure(name, count, path, counts) : null;
            if (measure) {
                const rate = document.createElement('span');
                rate.className = 'scene-pass-measure' + (measure.warn ? ' is-warn' : '') + (measure.none ? ' is-none' : '');
                const value = document.createElement('span');
                value.className = 'scene-pass-rate';
                value.textContent = measure.text;
                rate.appendChild(value);
                if (measure.typical) rate.append(' \u00b7 ' + measure.typical);
                label.appendChild(rate);
            }

            const n = document.createElement('span');
            n.className = 'scene-pass-count';
            n.textContent = String(count);
            n.title = count === 1 ? '1 match in this scene' : count + ' matches in this scene';

            row.append(sw, label, n);
            const item = document.createElement('div');
            item.className = 'scene-pass-item';
            item.appendChild(row);
            if (PASS_NOTES[name]) item.append.apply(item, _sceneInfo('pass-info-' + name, 'About ' + (PASS_LABELS[name] || name), PASS_NOTES[name]));
            return item;
        }

        // An explanation behind an ⓘ: a check's, beside its row (not in it:
        // the row is a button), or the summary line's. Shown on hover, focus
        // or a click, and Esc puts it away. A check's words also open a mark's card.
        function _sceneInfo(id, label, content) {
            const info = document.createElement('button');
            info.type = 'button';
            info.className = 'scene-pass-info';
            info.textContent = '\u24d8';
            info.setAttribute('aria-label', label);
            info.setAttribute('aria-expanded', 'false');
            const pop = document.createElement('span');
            pop.className = 'scene-pass-info-pop';
            pop.id = id;
            pop.setAttribute('role', 'tooltip');
            pop.append(content);
            info.setAttribute('aria-describedby', pop.id);
            info.onclick = function() {
                const open = info.getAttribute('aria-expanded') !== 'true';
                document.querySelectorAll('.scene-pass-info[aria-expanded="true"]').forEach(function(b) {
                    b.setAttribute('aria-expanded', 'false');
                });
                info.setAttribute('aria-expanded', open ? 'true' : 'false');
            };
            info.addEventListener('keydown', function(e) {
                if (e.key === 'Escape' && info.getAttribute('aria-expanded') === 'true') {
                    // Not the dialog it may sit in: Esc puts away only this.
                    e.preventDefault();
                    e.stopPropagation();
                    info.setAttribute('aria-expanded', 'false');
                    info.blur();
                }
            });
            return [info, pop];
        }

        // The count of each kind of mark, shown under the row while the pass
        // is on. A kind with nothing to show is dimmed, not dropped.
        function _scenePassBreakdown(name, hits, stats) {
            const box = document.createElement('div');
            box.className = 'scene-pass-breakdown';
            box.id = 'pass-breakdown-' + name;
            box.dataset.pass = name;
            box.hidden = !hls[name];
            const counts = {};
            PASS_BREAKDOWNS[name].forEach(function(kind) {
                const matches = [].concat(kind.match);
                const n = (Array.isArray(hits) ? hits : []).filter(function(h) {
                    return matches.some(function(m) { return String(h.note || '').indexOf(m) !== -1; });
                }).length;
                counts[kind.label] = n;
                const item = document.createElement('span');
                item.className = 'scene-pass-breakdown-item' + (n ? '' : ' is-empty');
                const num = document.createElement('span');
                num.className = 'scene-pass-breakdown-n';
                num.textContent = String(n);
                item.append(kind.label + ' ', num);
                box.appendChild(item);
            });
            // How many of the scene's tags carry an adverb, against the line
            // ProWritingAid suggests (under about 12%); amber only above it.
            const total = name === 'dialogue_tags' && stats ? stats.dialogue_tags : 0;
            if (total) {
                const share = Math.round(counts['Adverb on a tag'] * 100 / total);
                const line = document.createElement('span');
                line.className = 'scene-pass-share' + (share > 12 ? ' is-high' : '');
                line.textContent = 'Adverbs on ' + counts['Adverb on a tag'] + ' of ' + total + ' tags (' + share + '%)';
                const hint = document.createElement('span');
                hint.className = 'scene-pass-share-hint';
                hint.textContent = ' \u00b7 ProWritingAid suggests under about 12%';
                line.appendChild(hint);
                box.appendChild(line);
            }
            return box;
        }

        // The scene's marks have arrived: the list is redrawn with them (the
        // counts were already right, so nothing moves) for the breakdowns.
        function refreshScenePassList(path) {
            const list = document.getElementById('scenePassList');
            if (!list || (typeof paths !== 'undefined' && paths[curIdx] !== path)) return;
            list.replaceWith(_scenePassList(path));
            if (typeof syncAllBtn === 'function') syncAllBtn();
        }

        // Called whenever a pass is toggled from anywhere, so the list agrees
        // with the prose without being rebuilt.
        function syncScenePassRows() {
            document.querySelectorAll('#scenePassList .scene-pass-row').forEach(function(row) {
                const on = !!hls[row.dataset.pass];
                row.classList.toggle('is-on', on);
                row.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
            document.querySelectorAll('#scenePassList .scene-pass-breakdown').forEach(function(box) {
                box.hidden = !hls[box.dataset.pass];
            });
        }

        function discussFollowActiveDocument() {
            var panel = document.getElementById('discussPanel');
            if (!panel || panel.hidden) return;
            var doc = discussDocument();
            var key = discussDocumentKey(doc);
            if (!doc || key === _discussDocumentKey) return;
            _discussDocumentKey = key;
            renderDiscussContext();
            renderDiscussTaskMode();
            var waitingLegacyDraft = hasLegacyDiscussDraft(doc, _discussAgent);
            if (!_discussDraftDocument && activateLegacyDiscussDraft(doc, _discussAgent)) {
                document.getElementById('discussAnnouncement').textContent =
                    'Conversation kept open. Restored the saved draft for ' + doc.path + '.';
            } else if (_discussDraftDocument && waitingLegacyDraft) {
                document.getElementById('discussAnnouncement').textContent =
                    'Conversation kept open. Your current draft is still here. A saved draft for this file '
                    + 'is waiting and will appear after you send or clear this draft.';
            } else {
                document.getElementById('discussAnnouncement').textContent = _discussIncludeCurrentDocument
                    ? 'Conversation kept open. ' + discussTurnDocument().path + ' remains attached.'
                    : _discussDraftDocument
                    ? 'Conversation kept open. Your draft is still here; no file is attached.'
                    : 'Conversation kept open. No file is attached.';
            }
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
             'task.updated', 'tasks.cleared', 'notice.dismissed', 'model.changed', 'warning', 'error'].forEach(function(type) {
                source.addEventListener(type, function(event) {
                    if (type === 'connection') {
                        var detail = JSON.parse(event.data);
                        setDiscussConnection(detail.state, detail.reason || '');
                    }
                    if (type === 'turn.started' || type === 'conversation.reset') _discussStreamText = '';
                    if (type === 'conversation.reset') { _discussReview = []; _discussReviewKeep = {}; }
                    // A new question accepts what the last turn changed: the edits are
                    // already saved, and the server has already let go of their review.
                    // Asked rather than cleared here, since this event can arrive after
                    // a quick turn has finished and put up its own card.
                    if (type === 'turn.preparing') refreshDiscussReview();
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
            source.addEventListener('skills.changed', function() {
                loadDiscussSkillList(true);
                if (!document.getElementById('discussSkillsPicker').hidden) loadDiscussSkills(true);
            });
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
            var atBottom = discussIsAtBottom(log);
            // The text lives outside the DOM so the next snapshot render can
            // put it back; the node alone did not survive replaceChildren().
            _discussStreamText += text;
            var draft = log.querySelector('.discuss-stream-draft');
            if (!draft) {
                draft = discussStreamDraft();
                log.appendChild(draft);
            }
            // Formatted as it arrives, as the finished answer will be. Redrawn
            // at most once a frame: deltas come far faster than that.
            if (!_discussStreamPaintQueued) {
                _discussStreamPaintQueued = true;
                requestAnimationFrame(function() {
                    _discussStreamPaintQueued = false;
                    var current = document.querySelector('#discussLog .discuss-stream-draft');
                    if (current) paintDiscussStreamDraft(current);
                    discussAfterActivity(atBottom);
                });
            }
        }

        var _discussStreamPaintQueued = false;

        function discussStreamDraft() {
            var draft = elementWith('discuss-message assistant chat-message-card discuss-stream-draft');
            draft.appendChild(elementWith('discuss-message-label chat-message-header chat-message-name', discussAgentLabel()));
            draft.appendChild(elementWith('discuss-stream-body'));
            paintDiscussStreamDraft(draft);
            return draft;
        }

        function paintDiscussStreamDraft(draft) {
            var body = draft.querySelector('.discuss-stream-body');
            if (!body) return;
            body.replaceChildren();
            renderDiscussMarkdown(body, _discussStreamText);
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
            // Already a /repo-asset/ URL (the scene view writes those): take
            // the path back out rather than prefixing it a second time.
            if (/^\/repo-asset\//.test(raw)) {
                try { raw = '/' + decodeURIComponent(raw.slice('/repo-asset/'.length)); }
                catch (error) { return null; }
            }
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
                else if (token.type === 'code') {
                    node = document.createElement('pre'); var code = document.createElement('code'); code.textContent = decodeMarkdownText(token.text || ''); node.appendChild(code);
                    if (ctx.agentOutput) {
                        var codeText = code.textContent;
                        parent.appendChild(withCopyButton(node, function() { return codeText; }));
                        return;
                    }
                }
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
                if (token.type === 'blockquote' && ctx.agentOutput) {
                    var quote = node;
                    parent.appendChild(withCopyButton(quote, function() { return quote.innerText.trim(); }));
                    return;
                }
                parent.appendChild(node);
            });
        }

        var CODE_COPY_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
        var CODE_COPIED_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>';

        // Code blocks and quotes in agent replies (shell commands, drafted
        // passages), and the writer's own messages, get a small copy button on
        // hover. It floats on the block's
        // top edge, outside the text, so it never covers a long line. getText
        // runs at click time.
        function withCopyButton(node, getText) {
            var wrap = document.createElement('div');
            wrap.appendChild(node);
            addCopyButton(wrap, getText, node.tagName === 'PRE' ? 'Copy code' : 'Copy quote');
            return wrap;
        }

        function addCopyButton(container, getText, label) {
            container.classList.add('md-copy-block');
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'md-copy-btn';
            button.title = 'Copy';
            button.setAttribute('aria-label', label);
            button.innerHTML = CODE_COPY_ICON;
            button.onclick = function() {
                sidebarWriteClipboard(getText()).then(function() {
                    button.innerHTML = CODE_COPIED_ICON;
                    button.title = 'Copied';
                    button.classList.add('is-copied');
                    setTimeout(function() {
                        button.innerHTML = CODE_COPY_ICON;
                        button.title = 'Copy';
                        button.classList.remove('is-copied');
                    }, 1500);
                }, function() { button.title = 'Could not copy'; });
            };
            container.appendChild(button);
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

        // One card. Its title and explanation come from the skill file when the
        // server has answered with them, and from the fallback row when it has
        // not. Both go in as text nodes: a description is writer-authored.
        function discussPassGroup(rows, run) {
            var group = elementWith('discuss-story-actions');
            rows.forEach(function(row) {
                var live = _discussActionCopy[row.id] || {};
                var card = document.createElement('button');
                card.type = 'button'; card.className = 'discuss-story-action';
                card.appendChild(elementWith('discuss-story-action-title', live.label || row.label));
                card.appendChild(elementWith('discuss-story-action-copy', live.description || row.copy));
                card.onclick = function() { run(row.id); };
                group.appendChild(card);
            });
            return group;
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

        // Ask Claude Code whether the login has gone through, until it has or
        // the writer has plainly given up on it.
        function watchClaudeLogin(deadline) {
            discussApi('/api/discuss/claude/login-status', {}).then(function(data) {
                if (data.logged_in) {
                    _discussClaudeLogin = 'done';
                    renderDiscussSnapshot();
                    document.getElementById('discussAnnouncement').textContent = 'Logged in to Claude';
                    return;
                }
                if (Date.now() < deadline) { setTimeout(function() { watchClaudeLogin(deadline); }, 2000); return; }
                _discussClaudeLogin = '';
                renderDiscussSnapshot();
            }).catch(function() {
                if (Date.now() < deadline) setTimeout(function() { watchClaudeLogin(deadline); }, 2000);
            });
        }

        // The expired-login notice once the login has gone through: say so,
        // and offer to send the question that failed.
        function renderClaudeLoggedInNotice(notice, node) {
            node.className = 'discuss-notice';
            var message = elementWith('discuss-notice-message', 'You’re logged in to Claude again.');
            var asked = ((_discussSnapshot && _discussSnapshot.messages) || []).filter(function(row) {
                return row.role === 'user' && notice.client_request_id && row.client_request_id === notice.client_request_id;
            })[0];
            if (asked && asked.text) {
                var fix = elementWith('discuss-notice-fix');
                var again = document.createElement('button');
                again.type = 'button';
                again.className = 'discuss-primary';
                again.textContent = 'Ask again';
                again.onclick = function() {
                    again.disabled = true;
                    _discussClaudeLogin = '';
                    document.getElementById('discussInput').value = String(asked.text);
                    discussApi(
                        '/api/discuss/conversations/' + encodeURIComponent(_discussConversationId)
                        + '/notices/' + encodeURIComponent(notice.id) + '/dismiss',
                        {}
                    ).catch(function() {}).then(function() {
                        if (_discussSnapshot) {
                            _discussSnapshot.notices = (_discussSnapshot.notices || []).filter(function(candidate) {
                                return candidate.id !== notice.id;
                            });
                        }
                        sendDiscussQuestion();
                    });
                };
                fix.appendChild(again);
                message.appendChild(fix);
            }
            node.appendChild(message);
            return node;
        }

        function renderDiscussNotice(notice) {
            var node = elementWith('discuss-notice ' + (notice.kind === 'error' ? 'error' : 'warning'));
            if (notice.id) node.dataset.noticeId = notice.id;
            var message = elementWith('discuss-notice-message', notice.message || '');
            if (notice.command) {
                // The one command that fixes this, ready to paste into Terminal.
                var fix = elementWith('discuss-notice-fix');
                var command = document.createElement('code');
                command.textContent = notice.command;
                fix.appendChild(command);
                var copy = document.createElement('button');
                copy.type = 'button';
                copy.className = 'discuss-secondary';
                copy.textContent = 'Copy';
                copy.setAttribute('aria-label', 'Copy ' + notice.command);
                copy.onclick = function() {
                    if (!navigator.clipboard || !navigator.clipboard.writeText) return;
                    navigator.clipboard.writeText(notice.command).then(function() {
                        copy.textContent = 'Copied';
                        document.getElementById('discussAnnouncement').textContent = 'Copied ' + notice.command;
                        setTimeout(function() { copy.textContent = 'Copy'; }, 1200);
                    });
                };
                fix.appendChild(copy);
                // On the writer's own Mac the server can open Terminal with
                // the login already running, and then watch for it to finish.
                if (notice.command === 'claude auth login' && typeof hostPlatform === 'string' && hostPlatform === 'darwin') {
                    if (_discussClaudeLogin === 'done') return renderClaudeLoggedInNotice(notice, node);
                    var login = document.createElement('button');
                    login.type = 'button';
                    login.className = 'discuss-primary';
                    login.textContent = _discussClaudeLogin === 'waiting' ? 'Waiting for login…' : 'Log in';
                    login.disabled = _discussClaudeLogin === 'waiting';
                    login.onclick = function() {
                        login.disabled = true;
                        discussApi('/api/discuss/claude/login', {}).then(function() {
                            _discussClaudeLogin = 'waiting';
                            login.textContent = 'Waiting for login…';
                            document.getElementById('discussAnnouncement').textContent =
                                'Terminal is open. Finish logging in there.';
                            watchClaudeLogin(Date.now() + 10 * 60 * 1000);
                        }).catch(function(error) {
                            login.disabled = false;
                            renderDiscussError(error.message);
                        });
                    };
                    fix.insertBefore(login, fix.firstChild);
                }
                message.appendChild(fix);
            }
            node.appendChild(message);
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

        // ---- Turn status -------------------------------------------------
        // One strip answers "is it still working?". Everything it says is
        // derived from the snapshot, so a reload or a reconnect cannot leave it
        // claiming work that already finished.
        var _discussTurnBase = {ms: null, at: 0};
        var _discussTurnTimer = null;
        var _discussTurnTrailOpen = false;
        var _discussTurnLastKind = '';
        var _discussTurnPhraseAt = 0;
        var _discussTurnPhrase = '';
        var _discussTurnDoneUntil = 0;
        var _discussAgentState = {};
        var _discussBaseTitle = '';

        function discussFormatDuration(ms) {
            var total = Math.max(0, Math.round((ms || 0) / 1000));
            return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
        }

        function discussSpokenDuration(ms) {
            var total = Math.max(0, Math.round((ms || 0) / 1000));
            var minutes = Math.floor(total / 60);
            var seconds = total % 60;
            var parts = [];
            if (minutes) parts.push(minutes + ' minute' + (minutes === 1 ? '' : 's'));
            if (seconds || !minutes) parts.push(seconds + ' second' + (seconds === 1 ? '' : 's'));
            return parts.join(' ');
        }

        function discussShortPath(value) {
            var parts = String(value || '').replace(/\\/g, '/').split('/').filter(Boolean);
            if (!parts.length) return '';
            return parts.slice(-2).join('/');
        }

        // Split a shell command into words, honouring quotes. Enough for the
        // commands agents run; not a shell.
        function discussShellWords(text) {
            var words = [], current = '', quote = '', any = false;
            for (var i = 0; i < text.length; i++) {
                var ch = text.charAt(i);
                if (quote) {
                    if (ch === quote) quote = '';
                    else if (ch === '\\' && quote === '"' && i + 1 < text.length) current += text.charAt(++i);
                    else current += ch;
                } else if (ch === '"' || ch === "'") { quote = ch; any = true; }
                else if (/\s/.test(ch)) { if (current || any) words.push(current); current = ''; any = false; }
                else if (ch === '\\' && i + 1 < text.length) current += text.charAt(++i);
                else current += ch;
            }
            if (current || any) words.push(current);
            return words;
        }

        // Fill *node* with *command*, coloured as a shell line: the program,
        // its flags, quoted strings, and the operators between commands.
        function fillShellHighlight(node, command) {
            node.replaceChildren();
            node.classList.add('shell-hl');
            var text = String(command || '');
            var pattern = /("(?:[^"\\]|\\.)*"?|'[^']*'?)|(&&|\|\||[|;<>]+|\$\()|(\s+)|(--?\w[\w-]*(?:=\S*)?)|([^\s"'|;&<>]+)/g;
            var expectCommand = true;
            var match;
            var add = function(className, value) {
                if (!className) { node.appendChild(document.createTextNode(value)); return; }
                var span = document.createElement('span');
                span.className = className;
                span.textContent = value;
                node.appendChild(span);
            };
            while ((match = pattern.exec(text))) {
                if (match[1] !== undefined) { add('sh-string', match[1]); expectCommand = false; }
                else if (match[2] !== undefined) { add('sh-op', match[2]); expectCommand = true; }
                else if (match[3] !== undefined) { add('', match[3]); }
                else if (match[4] !== undefined) { add('sh-flag', match[4]); }
                else if (expectCommand && !/=/.test(match[5])) { add('sh-cmd', match[5]); expectCommand = false; }
                else { add(/^\d+([,.]\d+)*p?$/.test(match[5]) ? 'sh-num' : '', match[5]); }
            }
            return node;
        }

        // Agents run everything as `bash -lc "…"`; the command is inside.
        function discussInnerCommand(command) {
            var words = discussShellWords(command);
            var shell = (words[0] || '').split('/').pop();
            if (/^(ba|z|da|k)?sh$/.test(shell)) {
                var flag = words.findIndex(function(word) { return /^-[a-z]*c$/.test(word); });
                if (flag >= 0 && words[flag + 1] !== undefined) return words[flag + 1];
            }
            return command;
        }

        function discussPathWords(words) {
            return words.slice(1).filter(function(word) {
                return word && word.charAt(0) !== '-' && !/^\d+(,\d+)?p?$/.test(word) && !/^['"]?\d/.test(word)
                    && word.indexOf('/dev/') !== 0;
            });
        }

        function discussListPhrase(paths) {
            var shown = paths.slice(0, 2).map(discussShortPath);
            return paths.length > 2
                ? shown.join(', ') + ' and ' + (paths.length - 2) + ' more'
                : shown.join(' and ');
        }

        // One part of a pipeline, said in writer language, or '' when it is
        // plumbing (cd, a pipe into head) not worth a step of its own.
        function discussSegmentPhrase(segment) {
            var words = discussShellWords(segment.trim());
            var name = (words[0] || '').split('/').pop();
            if (!name || name === 'cd' || name === 'echo' || name === 'printf' || name === 'true') return '';
            if (name === 'rg' || name === 'grep' || name === 'ugrep' || name === 'ag') {
                var args = words.slice(1);
                var pattern = '', rest = [];
                for (var k = 0; k < args.length; k++) {
                    var word = args[k];
                    if (word === '-e' || word === '--regexp') { pattern = args[++k] || pattern; continue; }
                    if (/^-(g|t|m|A|B|C|-glob|-type|-max-count)$/.test(word)) { k++; continue; }
                    if (word.charAt(0) === '-') continue;
                    if (!pattern) pattern = word; else rest.push(word);
                }
                if (!pattern) return 'Searching the project';
                return 'Searching for “' + pattern + '”' + (rest.length ? ' in ' + discussListPhrase(rest) : '');
            }
            if (/^(cat|head|tail|sed|nl|less|more|bat|awk)$/.test(name)) {
                var files = discussPathWords(words).filter(function(word) { return /[./]/.test(word) && !/^s\//.test(word); });
                return files.length ? 'Reading ' + discussListPhrase(files) : '';
            }
            if (name === 'wc') {
                var counted = discussPathWords(words);
                return counted.length ? 'Counting words in ' + discussListPhrase(counted) : 'Counting words';
            }
            if (/^(ls|find|fd|tree)$/.test(name)) {
                var where = discussPathWords(words).filter(function(word) { return word !== '.' && word.indexOf('*') < 0; })[0];
                return where ? 'Listing ' + discussShortPath(where) : 'Looking through the project';
            }
            if (name === 'git') {
                var at = 1;
                while (words[at] === '-C' || words[at] === '-c') at += 2;
                var sub = words[at] || '';
                if (sub === 'log' || sub === 'blame' || sub === 'show') return 'Checking the history';
                if (sub === 'diff' || sub === 'status') return 'Checking what changed';
                return 'Using git';
            }
            if (/^python\d?(\.\d+)?$/.test(name) || name === 'node') return 'Running a script';
            if (name === 'mkdir' || name === 'touch' || name === 'cp' || name === 'mv') return 'Arranging files';
            return 'Running ' + name;
        }

        // Protocol nouns are not writer language. "commandExecution · failed"
        // says nothing about what was tried, and a search that matched nothing
        // is an outcome rather than an error.
        function discussCommandPhrase(activity) {
            var command = discussInnerCommand(String(activity.command || '').trim());
            if (!command) return 'Running a command';
            var phrases = [];
            command.split(/\s*(?:&&|\|\||;|\|)\s*/).forEach(function(segment) {
                var phrase = discussSegmentPhrase(segment);
                if (phrase && phrases.indexOf(phrase) < 0) phrases.push(phrase);
            });
            if (!phrases.length) {
                // Only plumbing (an echo, a cd): name it rather than say nothing.
                var first = (discussShellWords(command)[0] || '').split('/').pop();
                return first ? 'Running ' + first : 'Running a command';
            }
            return phrases.slice(0, 2).join(', then ') + (phrases.length > 2 ? '…' : '');
        }

        function discussActivityPhrase(activity) {
            var kind = activity.kind || '';
            var tool = String(activity.tool || '');
            if (kind === 'commandExecution') return discussCommandPhrase(activity);
            if (kind === 'commentary') return String(activity.text || '');
            if (kind === 'fileChange') {
                var changes = activity.changes || [];
                var path = changes.length ? discussShortPath(changes[0].path) : '';
                return path ? 'Editing ' + path : 'Editing a file';
            }
            if (kind === 'webSearch') {
                return activity.query ? 'Searching the web for “' + activity.query + '”' : 'Searching the web';
            }
            if (tool === 'Read' || tool === 'NotebookRead') {
                return activity.path ? 'Reading ' + discussShortPath(activity.path) : 'Reading a file';
            }
            if (tool === 'Grep') {
                var term = activity.pattern || activity.query;
                if (!term) return 'Searching the project';
                return 'Searching for “' + term + '”' + (activity.path ? ' in ' + discussShortPath(activity.path) : '');
            }
            if (tool === 'Glob') {
                return activity.pattern ? 'Looking for ' + activity.pattern : 'Looking through files';
            }
            if (tool === 'LS') return activity.path ? 'Listing ' + discussShortPath(activity.path) : 'Looking through files';
            if (tool === 'TodoWrite') return 'Updating its plan';
            if (tool === 'Task' || tool === 'Agent') return 'Handing part of the work to a helper';
            if (tool) return 'Using ' + tool;
            if (kind === 'mcpToolCall') return 'Using a connected tool';
            return 'Working';
        }

        function discussApprovalPhrase(approval) {
            if (approval.tool === 'WebSearch') return 'Wants to search the web';
            if (approval.tool === 'WebFetch') return 'Wants to open a web page';
            if (approval.tool === 'Task' || approval.tool === 'Agent') return 'Wants to start a helper agent';
            if (approval.kind === 'command' || approval.kind === 'network') return 'Wants to run a shell command';
            if (approval.kind === 'stdin') return 'Wants to type into a running command';
            if (approval.kind === 'fileChange') return 'Wants to edit a file';
            if (approval.kind === 'permissions') return 'Wants wider permissions';
            return 'Wants your decision';
        }

        function discussSettledApprovalPhrase(approval) {
            var what = approval.kind === 'fileChange' ? 'an edit'
                : approval.kind === 'permissions' ? 'wider permissions'
                : approval.kind === 'stdin' ? 'input to a running command'
                : 'a command';
            if (approval.status === 'expired') return 'The request for ' + what + ' expired';
            if (approval.decision === 'decline' || approval.decision === 'cancel') return 'You declined ' + what;
            return 'You allowed ' + what;
        }

        function discussTurnActivities(snapshot, turnId) {
            var rows = (snapshot.activities || []);
            if (!turnId) return rows;
            var scoped = rows.filter(function(row) { return (row.turn_id || '') === turnId; });
            // An agent that never labels its activities with a turn is still
            // reporting this turn's work: the projection is cleared when the
            // next turn starts.
            return scoped.length ? scoped : rows;
        }

        function discussTurnTrailRows(snapshot, turnId, running) {
            var rows = discussTurnActivities(snapshot, turnId).map(function(activity) {
                var phrase = discussActivityPhrase(activity);
                var status = activity.status || '';
                if (activity.kind === 'commentary') return {text: phrase, state: 'note'};
                var command = String(activity.command || '');
                if (status === 'inProgress') return {text: phrase, state: running ? 'now' : 'settled', command: command};
                if (status === 'failed') {
                    return phrase.indexOf('Searching') === 0
                        ? {text: phrase + ' — no matches', state: 'empty', command: command}
                        : {text: phrase + ' — failed', state: 'failed', command: command};
                }
                return {text: phrase, state: 'done', command: String(activity.command || '')};
            });
            (snapshot.approvals || []).forEach(function(approval) {
                if (approval.status === 'pending' || approval.status === 'resolving') return;
                if (turnId && approval.turn_id && approval.turn_id !== turnId) return;
                rows.push({text: discussSettledApprovalPhrase(approval), state: 'settled'});
            });
            return rows;
        }

        // The last thing the agent said it was doing. Activities beat progress:
        // "Reading alice.md" is a fact, a reasoning summary is a paraphrase.
        function discussTurnDoingLine(snapshot) {
            var scoped = discussTurnActivities(snapshot, snapshot.active_turn_id);
            var running = scoped.filter(function(row) { return row.status === 'inProgress'; });
            if (running.length) return discussActivityPhrase(running[running.length - 1]);
            var tail = (snapshot.progress || []).join('').split('\n').filter(function(line) {
                return line.trim();
            }).pop();
            if (tail) return tail.trim().slice(0, 160);
            if (scoped.length) return discussActivityPhrase(scoped[scoped.length - 1]);
            return '';
        }

        function discussTurnModel(snapshot) {
            var label = discussAgentLabel();
            var pending = (snapshot.approvals || []).filter(function(row) { return row.status === 'pending'; });
            if (pending.length) {
                return {
                    kind: 'waiting',
                    state: label + ' needs your permission',
                    doing: discussApprovalPhrase(pending[0]),
                    action: {label: 'Review', run: function() { discussFocusApproval(pending[0].request_id); }}
                };
            }
            if (snapshot.active_turn_id) {
                var queued = (snapshot.queue || []).length;
                return {
                    kind: 'working',
                    state: label + ' is working' + (queued ? ' · ' + queued + ' queued' : ''),
                    doing: discussTurnDoingLine(snapshot)
                };
            }
            if (snapshot.active_request_id) {
                return {
                    kind: 'starting',
                    state: 'Starting ' + label + '…',
                    doing: 'Waiting for the local agent to accept the question'
                };
            }
            var last = snapshot.last_turn || {};
            if (last.status) {
                var duration = discussFormatDuration(last.duration_ms);
                if (last.status === 'completed') {
                    var steps = last.steps || 0;
                    return {
                        kind: 'done',
                        state: 'Answered in ' + duration,
                        doing: steps ? steps + ' step' + (steps === 1 ? '' : 's') : ''
                    };
                }
                if (last.status === 'interrupted' || last.status === 'cancelled') {
                    return {kind: 'failed', state: 'Stopped after ' + duration, doing: 'You stopped ' + label};
                }
                return {
                    kind: 'failed',
                    state: label + ' could not finish',
                    doing: last.error ? String(last.error).split('\n')[0].slice(0, 160) : 'The turn ended without an answer'
                };
            }
            return {kind: 'idle'};
        }

        // The decision, not merely the first control in the card. A file change
        // leads with its diff toolbar, so reaching for the first button landed
        // on "Expand view" and left the actual question -- accept or decline --
        // looking untouched, whether you got there by Review or by the focus
        // that follows a new request.
        function discussApprovalDecisionButton(card) {
            if (!card) return null;
            var actions = card.querySelector('.discuss-approval-actions');
            return (actions && actions.querySelector('button:not([disabled])'))
                || (actions && actions.querySelector('button'))
                || card.querySelector('button');
        }

        function discussFocusApproval(requestId) {
            var card = document.getElementById('discussLog')
                .querySelector('[data-approval-id="' + CSS.escape(String(requestId || '')) + '"]');
            if (!card) return;
            card.scrollIntoView({block: 'center'});
            var button = discussApprovalDecisionButton(card);
            if (button) button.focus();
        }

        var _discussOpenCommands = {};

        function toggleDiscussTurnTrail() {
            _discussTurnTrailOpen = !_discussTurnTrailOpen;
            if (_discussSnapshot) renderDiscussTurnStatus(_discussSnapshot);
        }

        function discussTurnElapsedMs() {
            if (_discussTurnBase.ms === null) return null;
            return _discussTurnBase.ms + (Date.now() - _discussTurnBase.at);
        }

        function updateDiscussTurnClock() {
            var elapsed = discussTurnElapsedMs();
            var clock = document.getElementById('discussTurnClock');
            if (elapsed === null) { clock.hidden = true; return; }
            clock.hidden = false;
            clock.textContent = discussFormatDuration(elapsed);
            // Silence is a fact worth reporting. A turn that has produced
            // nothing for a minute may be thinking or may be wedged, and
            // pretending it is fine is how a panel loses its writer's trust.
            if (_discussTurnLastKind === 'working' && Date.now() - _discussTurnPhraseAt > 60000) {
                var quiet = Math.floor((Date.now() - _discussTurnPhraseAt) / 60000);
                document.getElementById('discussTurnDoing').textContent =
                    'Still working — no output for ' + quiet + 'm';
            }
        }

        function _syncDiscussTurnTimer(running) {
            if (running && !_discussTurnTimer) {
                _discussTurnTimer = setInterval(updateDiscussTurnClock, 1000);
            } else if (!running && _discussTurnTimer) {
                clearInterval(_discussTurnTimer);
                _discussTurnTimer = null;
            }
        }

        function renderDiscussTurnStatus(snapshot) {
            var wrap = document.getElementById('discussTurnStatus');
            if (!wrap) return;
            var model = discussTurnModel(snapshot);
            var kind = model.kind;
            // A finished turn holds its result briefly, then gets out of the way.
            if (kind === 'done') {
                if (_discussTurnLastKind !== 'done') _discussTurnDoneUntil = Date.now() + DISCUSS_TURN_DONE_MS;
                if (Date.now() > _discussTurnDoneUntil) kind = 'idle';
            } else if (kind !== 'idle') {
                _discussTurnDoneUntil = 0;
            }
            if (kind !== _discussTurnLastKind) {
                if (kind === 'done' && (_discussTurnLastKind === 'working' || _discussTurnLastKind === 'starting')) {
                    document.getElementById('discussAnnouncement').textContent =
                        discussAgentLabel() + ' finished in ' + discussSpokenDuration((snapshot.last_turn || {}).duration_ms);
                    setTimeout(function() {
                        if (_discussSnapshot) renderDiscussTurnStatus(_discussSnapshot);
                    }, DISCUSS_TURN_DONE_MS + 200);
                }
                // Steps stay folded until the writer asks for them, and fold
                // again once the turn is over.
                if (kind === 'idle' || kind === 'done') _discussTurnTrailOpen = false;
                _discussTurnLastKind = kind;
            }

            _discussAgentState[_discussAgent] = kind === 'waiting' ? 'attention'
                : (kind === 'working' || kind === 'starting') ? 'busy' : '';
            _syncDiscussAmbientSignals();

            if (kind === 'idle') {
                wrap.hidden = true;
                wrap.dataset.state = 'idle';
                _syncDiscussTurnTimer(false);
                return;
            }
            wrap.hidden = false;
            wrap.dataset.state = kind;

            document.getElementById('discussTurnState').textContent = model.state || '';
            var doing = model.doing || '';
            if (doing !== _discussTurnPhrase) { _discussTurnPhrase = doing; _discussTurnPhraseAt = Date.now(); }
            document.getElementById('discussTurnDoing').textContent = doing;
            // The strip is one line, so a long phrase is cut; hovering reads it.
            document.getElementById('discussTurnDoing').title = doing;

            var running = kind === 'working' || kind === 'starting';
            _discussTurnBase = running
                ? {ms: snapshot.active_turn_elapsed_ms || 0, at: Date.now()}
                : {ms: null, at: 0};
            _syncDiscussTurnTimer(running);
            updateDiscussTurnClock();

            var action = document.getElementById('discussTurnAction');
            if (model.action) {
                action.hidden = false;
                action.textContent = model.action.label;
                action.onclick = model.action.run;
            } else {
                action.hidden = true;
                action.onclick = null;
            }

            var planHost = document.getElementById('discussTurnPlan');
            planHost.replaceChildren();
            planHost.hidden = !(snapshot.plan || []).length;
            if (!planHost.hidden) {
                var plan = document.createElement('details');
                plan.className = 'discuss-plan';
                plan.open = true;
                var planSummary = document.createElement('summary');
                planSummary.textContent = 'Plan';
                plan.appendChild(planSummary);
                var list = document.createElement('ol');
                snapshot.plan.forEach(function(row) {
                    var item = document.createElement('li');
                    item.className = row.status || '';
                    item.textContent = row.step || '';
                    list.appendChild(item);
                });
                plan.appendChild(list);
                planHost.appendChild(plan);
            }

            var rows = discussTurnTrailRows(
                snapshot, snapshot.active_turn_id || (snapshot.last_turn || {}).turn_id, running);
            var toggle = document.getElementById('discussTurnTrailToggle');
            var trail = document.getElementById('discussTurnTrail');
            toggle.hidden = !rows.length;
            // The label has to name the way back in. Relabelling the open
            // control to a bare count read as a statistic rather than a
            // button, so a closed trail looked like one you could not reopen.
            toggle.textContent = _discussTurnTrailOpen
                ? 'Hide steps'
                : 'Show ' + rows.length + ' step' + (rows.length === 1 ? '' : 's');
            toggle.setAttribute('aria-expanded', _discussTurnTrailOpen ? 'true' : 'false');
            trail.hidden = !(_discussTurnTrailOpen && rows.length);
            wrap.dataset.trail = trail.hidden ? 'closed' : 'open';
            trail.replaceChildren();
            rows.forEach(function(row) {
                var item = document.createElement('li');
                item.className = row.state;
                var text = document.createElement('span');
                text.textContent = row.text;
                item.appendChild(text);
                // The exact command, a click away: the phrase is a reading of
                // it, and a writer who wants to check can.
                var command = row.command ? discussInnerCommand(row.command) : '';
                if (command) {
                    item.title = command;
                    var code = document.createElement('code');
                    code.className = 'discuss-turn-command';
                    fillShellHighlight(code, command);
                    code.hidden = _discussOpenCommands[command] !== true;
                    item.classList.add('has-command');
                    item.tabIndex = 0;
                    item.setAttribute('role', 'button');
                    item.setAttribute('aria-expanded', code.hidden ? 'false' : 'true');
                    var flip = function() {
                        code.hidden = !code.hidden;
                        _discussOpenCommands[command] = !code.hidden;
                        item.setAttribute('aria-expanded', code.hidden ? 'false' : 'true');
                    };
                    item.onclick = flip;
                    item.onkeydown = function(event) {
                        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); flip(); }
                    };
                    item.appendChild(code);
                }
                trail.appendChild(item);
            });
        }

        // ---- Signals outside the panel ------------------------------------
        // You are usually reading, not watching the dock. The tab dot and the
        // document title are the only things that reach you from there.
        function _syncDiscussAmbientSignals() {
            DISCUSS_AGENTS.forEach(function(agent) {
                _markDiscussAgentTab(agent, _discussAgentState[agent] || '');
            });
            if (!_discussBaseTitle) _discussBaseTitle = privacyRealTitle();
            var panel = document.getElementById('discussPanel');
            var away = !panel || panel.hidden || !document.hasFocus();
            var waiting = DISCUSS_AGENTS.filter(function(a) { return _discussAgentState[a] === 'attention'; });
            var working = DISCUSS_AGENTS.filter(function(a) { return _discussAgentState[a] === 'busy'; });
            var prefix = '';
            if (away && waiting.length) prefix = '· ' + discussAgentLabel(waiting[0]) + ' needs you — ';
            else if (away && working.length) prefix = '· ' + discussAgentLabel(working[0]) + ' working — ';
            var next = prefix + _discussBaseTitle;
            if (document.title !== next) document.title = next;
        }

        var _discussReviewedTurn = '';

        // What a tab shows when its agent cannot run here: why, and the
        // commands that fix it. Built as nodes, not markup: the reason is an
        // error string and must never be interpolated into innerHTML.
        function discussNotInstalledState(label, reasonText) {
            var empty = elementWith('discuss-empty-state');
            empty.appendChild(elementWith('discuss-empty-icon', '🤖'));
            var heading = document.createElement('h3');
            heading.textContent = label + ' is not connected';
            empty.appendChild(heading);
            empty.appendChild(elementWith('discuss-empty-blurb',
                'Proseview drives the agent you have installed, under your own login. Everything else works without one.'));
            var reason = elementWith('discuss-empty-reason');
            var em = document.createElement('em');
            em.textContent = String(reasonText || '');
            reason.appendChild(em);
            empty.appendChild(reason);
            var text = String(reasonText || '');
            var how, steps;
            if (/claude-agent-sdk/.test(text)) {
                how = 'Run this in a terminal, then restart Proseview:';
                steps = ['pipx inject proseview claude-agent-sdk'];
            } else if (/Claude/.test(label)) {
                how = 'Install Claude Code from claude.com/claude-code, sign in once in a terminal, then reopen this tab:';
                steps = ['claude'];
            } else {
                how = 'Install Codex and sign in once in a terminal, then reopen this tab:';
                steps = ['npm install -g @openai/codex', 'codex'];
            }
            empty.appendChild(elementWith('discuss-empty-blurb', how));
            var code = document.createElement('pre');
            code.className = 'discuss-empty-steps';
            code.textContent = steps.join('\n');
            empty.appendChild(code);
            var more = document.createElement('a');
            more.href = 'https://github.com/ourarash/proseview/blob/main/docs/ai.md';
            more.target = '_blank';
            more.rel = 'noopener';
            more.textContent = 'How the AI features work';
            empty.appendChild(more);
            return empty;
        }

        function renderDiscussSnapshot() {
            var snapshot = _discussSnapshot;
            if (!snapshot) return;
            syncDiscussHistoryOpenButtons();
            // The agent has stopped, so the file has stopped moving: the first
            // moment there is something settled to review. Keyed on the turn
            // that finished so it is asked exactly once per turn.
            var finished = (snapshot.last_turn || {}).turn_id || '';
            if (!snapshot.active_turn_id && finished && finished !== _discussReviewedTurn) {
                _discussReviewedTurn = finished;
                refreshDiscussReview({dropEditedSelection: true});
            }
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
            // An agent that is not installed has nothing to offer but how to
            // install it; the passes and the composer would only fail.
            var notInstalled = snapshot.connection === 'Unavailable'
                && /not installed|not on PATH/i.test(snapshot.unavailable_reason || '');
            document.getElementById('discussComposerArea').hidden = notInstalled && hasNoDiscussActivity;
            if (notInstalled && hasNoDiscussActivity) {
                log.appendChild(discussNotInstalledState(discussAgentLabel(), snapshot.unavailable_reason));
            } else if (hasNoDiscussActivity) {
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
                    empty.appendChild(title);
                    empty.appendChild(document.createTextNode('Ask about what you are reading, or run a pass over it.'));
                    // The scene on screen comes first. The repository scans are
                    // the rarer, heavier work and no longer lead.
                    var emptyDocument = discussTurnDocument();
                    if (emptyDocument && emptyDocument.kind === 'scene') {
                        empty.appendChild(elementWith('discuss-story-group', 'Read this scene'));
                        empty.appendChild(discussPassGroup(DISCUSS_SCENE_PASSES, runDiscussScenePass));
                    }
                    empty.appendChild(elementWith('discuss-story-group', 'Across the story'));
                    empty.appendChild(discussPassGroup(DISCUSS_REPOSITORY_PASSES, startDiscussRepositoryAction));
                }
                log.appendChild(empty);
            }
            appendUnassociatedNotices();
            groupDiscussTasks(snapshot.tasks || []).forEach(function(group) {
                log.appendChild(renderDiscussTask(group.latest, group.previous));
                appendNoticesForRequest(group.latest.client_request_id);
            });
            (snapshot.messages || []).forEach(function(message) {
                var wrap = elementWith('discuss-message chat-message-card ' + (message.role === 'user' ? 'user' : 'assistant'));
                var label = elementWith('discuss-message-label chat-message-header chat-message-name', message.role === 'user' ? 'Me' : discussAgentLabel());
                wrap.appendChild(label);
                renderDiscussMarkdown(wrap, message.text);
                highlightChatMentions(wrap, []);
                var sent = String(message.text || '');
                addCopyButton(wrap, function() { return sent; }, 'Copy message');
                log.appendChild(wrap);
                if (message.role === 'user') appendNoticesForRequest(message.client_request_id);
            });
            // Words appearing are the strongest sign of life there is, and the
            // rebuild above would erase them 35ms after they arrived. Re-hang
            // the draft until the message it becomes has landed.
            if (_discussStreamText && snapshot.active_turn_id) {
                var landed = (snapshot.messages || []).some(function(message) {
                    return message.role === 'assistant'
                        && String(message.text || '').indexOf(_discussStreamText.slice(0, 200)) >= 0;
                });
                if (landed) _discussStreamText = '';
                else {
                    log.appendChild(discussStreamDraft());
                }
            }
            // Progress and activities now belong to the turn strip, in the
            // order they happened. Only an approval that still needs a decision
            // earns a card here; a settled one is a line in the turn's trail.
            //
            // Cards follow the order the edits happened, so an approved change
            // stays above the request that came after it. Listing every pending
            // approval first put the newest question above an older answer and
            // read as though the change you had just approved was still asking.
            var pendingApprovals = {};
            (snapshot.approvals || []).forEach(function(approval) {
                if (approval.status === 'pending' || approval.status === 'resolving') {
                    pendingApprovals[approval.item_id] = approval;
                }
            });

            // A file change is no longer answered here. What it did is
            // reviewed once, against the file as it stood before the turn,
            // from the card the turn's end puts up.
            var anchored = {};

            // Approvals with no file-change activity to sit beside -- a command,
            // a permission grant -- still need somewhere to go.
            Object.keys(pendingApprovals).forEach(function(itemId) {
                var approval = pendingApprovals[itemId];
                if (!anchored[approval.request_id]) log.appendChild(renderDiscussApproval(approval));
            });
            notices.forEach(function(notice, index) {
                if (!renderedNotices[index]) log.appendChild(renderDiscussNotice(notice));
            });
            (_discussReview || []).forEach(function(file) {
                log.appendChild(renderDiscussReviewCard(file));
            });
            // Said plainly rather than left out: a file changed with no warning
            // has no earlier version to offer, and silence would read as though
            // nothing had happened to it.
            if ((_discussReviewUnreviewable || []).length) {
                var note = elementWith('discuss-review-note');
                note.textContent = discussAgentLabel() + ' changed '
                    + _discussReviewUnreviewable.join(', ')
                    + ' without saying so first, so there is no earlier version to compare against here. '
                    + 'Scene history still holds what was there before your last save.';
                log.appendChild(note);
            }
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
            var unavailableReason = '';
            if (snapshot.active_turn_id) unavailableReason = 'Stop ' + discussAgentLabel() + ' before starting a new conversation.';
            else if (snapshot.active_request_id) unavailableReason = 'Wait for ' + discussAgentLabel() + ' to start this question before starting a new conversation.';
            else if ((snapshot.queue || []).length) unavailableReason = 'Remove or wait for queued items before starting a new conversation.';
            else if (pendingApproval) unavailableReason = 'Resolve the ' + discussAgentLabel() + ' approval request before starting a new conversation.';
            // Why it is unavailable is the button's tooltip, not a line in the
            // panel: aria-disabled rather than disabled, which would hide it.
            newConversation.setAttribute('aria-disabled', unavailableReason ? 'true' : 'false');
            newConversation.title = unavailableReason || 'New conversation';
            log.setAttribute('aria-busy', snapshot.active_turn_id ? 'true' : 'false');
            renderDiscussModelChip();
            renderDiscussTurnStatus(snapshot);
            restoreDiscussScroll(log, scrollState);
            if (_discussLastApproval) {
                var target = discussApprovalDecisionButton(
                    log.querySelector('[data-approval-id="' + CSS.escape(_discussLastApproval) + '"]'));
                // An earlier scheduled snapshot may race the approval SSE
                // event. Keep the id until a snapshot renders its controls.
                if (target) {
                    target.focus();
                    document.getElementById('discussAnnouncement').textContent = discussAgentLabel() + ' is requesting approval';
                    _discussLastApproval = '';
                }
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
                if (target.scope === 'scene') {
                    // Quoting the first 120 characters of a whole scene back at
                    // its writer says nothing about what the pass read.
                    var words = String(target.selection || '').split(/\s+/).filter(Boolean).length;
                    card.appendChild(elementWith('discuss-task-selection', 'This scene · ' + words.toLocaleString() + ' words'));
                } else {
                    var preview = elementWith('discuss-task-selection', '“' + String(target.selection || '').slice(0, 120) + (String(target.selection || '').length > 120 ? '…' : '') + '”');
                    card.appendChild(preview);
                }
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
            if (target && target.scope_note) card.appendChild(elementWith('discuss-task-meta', target.scope_note));
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
                if (discussTaskDocument(target)) {
                    var propose = document.createElement('button'); propose.type = 'button'; propose.className = 'discuss-secondary'; propose.textContent = 'Propose a revision';
                    propose.onclick = function() {
                        var taskDocument = discussTaskDocument(target);
                        _discussSelection = target.selection || '';
                        _discussSelectionRange = target.range || null;
                        _discussDraftDocument = taskDocument;
                        _discussSelectionSnapshot = discussSelectionSnapshotFor(taskDocument);
                        _discussSelectionSourceTaskId = task.id;
                        _discussLiveDocument = discussLiveDocumentFor(taskDocument);
                        _discussPendingAction = 'rephrase';
                        _discussRetryOfTaskId = null;
                        var input = document.getElementById('discussInput'); input.value = 'Address the critique while preserving the passage’s facts, point of view, and tense.';
                        renderDiscussContext(); renderDiscussTaskMode(); saveDiscussDraft(); input.focus();
                    };
                    card.appendChild(propose);
                }
            } else if (result.kind === 'alternatives') {
                card.appendChild(elementWith('discuss-task-summary', result.summary || 'Rewrite alternatives are ready.'));
                card.appendChild(elementWith('discuss-task-meta', discussAlternativesStateSummary(task, result)));
                card.appendChild(renderDiscussAlternatives(task, result));
                if ((task.status === 'ready' || task.status === 'reviewing') && task.reviewable !== false) {
                    var review = document.createElement('button'); review.type = 'button'; review.className = 'discuss-primary'; review.textContent = 'Review changes';
                    review.onclick = function() { reviewDiscussTask(task, review); }; card.appendChild(review);
                }
            }
            if ((task.status === 'failed' || task.status === 'cancelled' || task.status === 'stale')
                && discussTaskDocument(target)) {
                var retry = document.createElement('button'); retry.type = 'button'; retry.className = 'discuss-secondary'; retry.textContent = 'Try again';
                retry.onclick = function() {
                    var taskDocument = discussTaskDocument(target);
                    _discussSelection = target.selection || '';
                    _discussSelectionRange = target.range || null;
                    _discussDraftDocument = taskDocument;
                    _discussSelectionSnapshot = discussSelectionSnapshotFor(taskDocument);
                    _discussSelectionSourceTaskId = task.id;
                    _discussLiveDocument = discussLiveDocumentFor(taskDocument);
                    _discussPendingAction = task.action_id;
                    _discussRetryOfTaskId = task.id;
                    var input = document.getElementById('discussInput');
                    input.value = task.instruction || '';
                    renderDiscussContext(); renderDiscussTaskMode(); saveDiscussDraft();
                    if (task.action_id === 'custom_rewrite' || task.instruction) {
                        input.focus();
                        document.getElementById('discussAnnouncement').textContent = 'Review the restored instruction, then run the action again';
                    } else runDiscussSelectionAction(
                        task.action_id, target.selection || '', target.range || null, _discussLiveDocument,
                        0, task.id, _discussSelectionSnapshot, task.id
                    );
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

        function discussWorkInProgress() {
            return !!(_discussSnapshot && (
                _discussSnapshot.active_request_id || _discussSnapshot.active_turn_id || (_discussSnapshot.queue || []).length
            ));
        }

        // Opening another conversation waits for the running turn, and has to
        // be offered again the moment that turn ends -- not only the next time
        // the list happens to be drawn.
        function syncDiscussHistoryOpenButtons() {
            var dialog = document.getElementById('discussHistoryDialog');
            if (!dialog || !dialog.open) return;
            var busy = discussWorkInProgress();
            dialog.querySelectorAll('button[data-history-open="saved"]').forEach(function(button) {
                if (button.dataset.historyOpening) return;
                button.disabled = busy;
            });
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
                status.textContent = 'No saved conversations for this project yet.'; status.hidden = false;
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
                    openButton.disabled = true; openButton.dataset.historyOpening = 'true';
                    discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/history/' + encodeURIComponent(item.thread_id) + '/open', {})
                        .then(function(data) {
                            _discussSnapshot = data.snapshot; renderDiscussSnapshot();
                            document.getElementById('discussHistoryDialog').close('opened');
                            document.getElementById('discussAnnouncement').textContent = 'Conversation opened';
                            document.getElementById('discussInput').focus();
                        })
                        .catch(function(error) {
                            delete openButton.dataset.historyOpening; syncDiscussHistoryOpenButtons();
                            status.textContent = error.message; status.hidden = false;
                        });
                });
                openButton.dataset.historyOpen = item.current ? 'current' : 'saved';
                openButton.disabled = !!item.current || discussWorkInProgress(); actions.appendChild(openButton);
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
            if (!window.confirm('Clear assistance results for this conversation? This cannot be undone.')) return;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/tasks/clear', {})
                .then(function() { scheduleDiscussSnapshot(); document.getElementById('discussAnnouncement').textContent = 'Assistance results cleared'; })
                .catch(function(error) { renderDiscussError(error.message); });
        }

        function renderDiscussApproval(approval, resolve) {
            resolve = resolve || resolveDiscussApproval;
            var card = elementWith('discuss-approval'); card.dataset.approvalId = approval.request_id;
            var title = document.createElement('h3'); title.textContent = approval.status === 'pending' ? 'Approval required' : 'Approval ' + approval.status; card.appendChild(title);
            if (approval.kind === 'stdin') {
                // Input typed into a command already running, not a new command.
                card.appendChild(document.createTextNode(approval.reason || 'Codex wants to type into a command it is running.'));
                if (approval.input) { var input = document.createElement('code'); input.textContent = 'Input: ' + approval.input; card.appendChild(input); }
                if (approval.command) {
                    var running = document.createElement('code');
                    running.appendChild(document.createTextNode('Running: '));
                    running.appendChild(fillShellHighlight(document.createElement('span'), discussInnerCommand(approval.command)));
                    card.appendChild(running);
                }
            } else {
                card.appendChild(document.createTextNode(approval.reason || approval.kind || 'Codex requested an action.'));
                if (approval.command) {
                    var code = document.createElement('code');
                    // Only a shell line is coloured as one.
                    if (!approval.tool || approval.tool === 'Bash') fillShellHighlight(code, discussInnerCommand(approval.command));
                    else code.textContent = approval.command;
                    card.appendChild(code);
                }
            }
            if (approval.grant_root) { var root = document.createElement('code'); root.textContent = 'Write access: ' + approval.grant_root; card.appendChild(root); }
            if (approval.network) { var network = document.createElement('code'); network.textContent = 'Network: ' + JSON.stringify(approval.network); card.appendChild(network); }
            if (approval.permissions) { var permissions = document.createElement('code'); permissions.textContent = 'Permissions: ' + JSON.stringify(approval.permissions); card.appendChild(permissions); }
            // Only a command, a network call, or a permission grant reaches
            // here now, and none of those can be taken back afterwards -- so
            // the answer is the whole request, not part of it.
            if (approval.status === 'pending') {
                var actions = elementWith('discuss-approval-actions');
                [
                    ['accept', 'Accept once'], ['accept_for_session', 'Accept for session ⚠'], ['decline', 'Decline'], ['cancel', 'Cancel']
                ].forEach(function(option) {
                    var wire = option[0] === 'accept_for_session' ? 'acceptForSession' : option[0];
                    if ((approval.available_decisions || []).indexOf(wire) < 0) return;
                    var button = document.createElement('button'); button.type = 'button'; button.textContent = option[1];
                    if (option[0] === 'accept_for_session') button.title = 'Allows matching requests until this Codex session ends';
                    button.onclick = function() {
                        resolve(approval.request_id, option[0], button, approval.permissions);
                    };
                    actions.appendChild(button);
                });
                card.appendChild(actions);
            }
            return card;
        }

        


// A diff viewer for one file's patch. When `revert` is supplied the patch is
// laid out hunk by hunk, each with its own control, so the writer can keep some
// of an edit and take the rest back. Without it the patch renders as one table:
// that is the right shape for a change that has not been applied yet, or one
// that cannot be undone.
function createDiscussDiffViewer(diffString) {
    var wrapper = document.createElement('div');
    wrapper.className = 'discuss-diff';

    var header = elementWith('discuss-diff-toolbar');

    var expandBtn = document.createElement('button');
    expandBtn.type = 'button';
    expandBtn.className = 'discuss-chip discuss-chip-outline';
    expandBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px; vertical-align: text-bottom;"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg> Expand view';
    expandBtn.onclick = function(e) { e.preventDefault(); openDiscussDiffModal(diffString); };

    var toggleGroup = elementWith('discuss-diff-modes');
    var btnInline = document.createElement('button');
    btnInline.type = 'button';
    btnInline.textContent = 'Inline';
    var btnSplit = document.createElement('button');
    btnSplit.type = 'button';
    btnSplit.textContent = 'Split';
    toggleGroup.appendChild(btnInline);
    toggleGroup.appendChild(btnSplit);

    header.appendChild(expandBtn);
    header.appendChild(toggleGroup);

    var body = elementWith('discuss-diff-viewer');

    wrapper.appendChild(header);
    wrapper.appendChild(body);

    // Toggling Inline/Split twice quickly can land the replies out of order,
    // so only the newest request is allowed to paint.
    var pending = 0;
    function loadDiff(mode) {
        var token = ++pending;
        btnInline.className = mode === 'inline' ? 'discuss-chip' : 'discuss-chip discuss-chip-outline';
        btnSplit.className = mode === 'side-by-side' ? 'discuss-chip' : 'discuss-chip discuss-chip-outline';
        body.textContent = '';
        body.appendChild(elementWith('discuss-diff-status', 'Loading diff…'));
        discussApi('/api/discuss/format_patch', {patch: diffString, mode: mode})
            .then(function(res) {
                if (token !== pending) return;
                body.innerHTML = res.diff_html;
            })
            .catch(function(err) {
                if (token !== pending) return;
                body.textContent = '';
                body.appendChild(elementWith('discuss-diff-status', 'Could not render this diff: ' + err.message));
            });
    }

    btnInline.onclick = function(e) { e.preventDefault(); loadDiff('inline'); };
    btnSplit.onclick = function(e) { e.preventDefault(); loadDiff('side-by-side'); };

    loadDiff('side-by-side');

    return wrapper;
}

function updateDiscussDiffFontSize(size) {
    var contentDiv = document.getElementById('discussDiffModalContent');
    if (contentDiv) contentDiv.style.fontSize = size + 'px';
    var slider = document.getElementById('discussDiffFontSize');
    if (slider) slider.value = size;
}

// The expanded view of one reviewed file: the same blocks and the same ticks,
// with room to read them and the split view a long paragraph needs.
var _currentDiscussReviewPath = null;
var _currentDiscussDiffString = null;
var _currentDiscussDiffMode = 'side-by-side';
var _currentDiscussReviewContext = null;
var _discussDiffLoadToken = 0;

function openDiscussReviewModal(path, review) {
    _currentDiscussReviewContext = review || null;
    _currentDiscussReviewPath = path;
    _currentDiscussDiffString = null;
    document.getElementById('discussDiffModalTitle').textContent = path;
    document.getElementById('discussDiffModalNote').textContent =
        'Already saved in the file. Untick anything you want undone, then finish from the card.';
    var overlay = document.getElementById('discussDiffModalOverlay');
    overlay.hidden = false;
    _discussReturnFocus = document.activeElement;
    setDiscussDiffMode(review ? review.mode : _discussReviewMode);
    var initialSize = document.getElementById('discussDiffFontSize').value;
    updateDiscussDiffFontSize(initialSize);
}

function openDiscussDiffModal(diffString) {
    _currentDiscussReviewContext = null;
    _discussReturnFocus = document.activeElement;
    document.getElementById('discussDiffModalTitle').textContent = 'Review Changes';
    _currentDiscussReviewPath = null;
    _currentDiscussDiffString = diffString;
    document.getElementById('discussDiffModalNote').textContent = 'Review the changes the agent made.';
        document.getElementById("discussDiffModalOverlay").hidden = false;
    
    // Set initial mode UI
    setDiscussDiffMode(_currentDiscussDiffMode);
    
    // Initialize font size
    var initialSize = 18;
    try {
        var stored = localStorage.getItem(MODAL_FONT_SIZE_STORAGE_KEY);
        if (stored) initialSize = parseInt(stored, 10);
    } catch(e) {}
    updateDiscussDiffFontSize(initialSize);
}

function closeDiscussDiffModal() {
    var review = _currentDiscussReviewContext, path = _currentDiscussReviewPath;
    document.getElementById('discussDiffModalOverlay').hidden = true;
    _discussDiffLoadToken++;
    _currentDiscussDiffString = null;
    _currentDiscussReviewPath = null;
    _currentDiscussReviewContext = null;
    // Each surface reads back the same choices made in the expanded view.
    if (review) review.render(path);
    else {
        if (_discussSnapshot) renderDiscussSnapshot();
        if (_discussReturnFocus && _discussReturnFocus.focus) _discussReturnFocus.focus();
    }
}

function setDiscussDiffMode(mode) {
    _currentDiscussDiffMode = mode;
    
    var btnInline = document.getElementById('discussDiffToggleInline');
    var btnSplit = document.getElementById('discussDiffToggleSideBySide');
    if (btnInline && btnSplit) {
        if (mode === 'inline') {
            btnInline.classList.add('active');
            btnSplit.classList.remove('active');
        } else {
            btnSplit.classList.add('active');
            btnInline.classList.remove('active');
        }
    }
    loadDiscussDiffMode(mode);
}

function loadDiscussDiffMode(mode) {
    var contentDiv = document.getElementById('discussDiffModalContent');
    var token = ++_discussDiffLoadToken;
    if (_currentDiscussReviewPath) {
        var review = _currentDiscussReviewContext;
        if (review) { review.mode = mode; if (review.save) review.save(); } else _discussReviewMode = mode;
        var path = _currentDiscussReviewPath;
        var conversationId = review ? review.conversationId : _discussConversationId;
        var file = ((review ? review.files : _discussReview) || []).find(function(row) { return row.path === path; });
        contentDiv.replaceChildren();
        if (!file) {
            contentDiv.appendChild(elementWith('discuss-diff-status', 'This file has no changes left to review.'));
            return;
        }
        contentDiv.appendChild(elementWith('discuss-diff-status', 'Loading changes…'));
        discussApi('/api/discuss/conversations/' + encodeURIComponent(conversationId) + '/changes', {mode: mode})
            .then(function(res) {
                if (token !== _discussDiffLoadToken || _currentDiscussReviewPath !== path || _currentDiscussReviewContext !== review) return;
                if (!review && conversationId !== _discussConversationId) return;
                var files = res.files || [];
                if (review) review.files = files; else _discussReview = files;
                var fresh = files.find(function(row) { return row.path === path; });
                contentDiv.replaceChildren();
                if (!fresh) {
                    contentDiv.appendChild(elementWith('discuss-diff-status', 'This file has no changes left to review.'));
                    return;
                }
                (fresh.blocks || []).forEach(function(block) {
                    contentDiv.appendChild(renderDiscussReviewBlock(fresh, block, null, review).row);
                });
            }).catch(function(error) {
                if (token !== _discussDiffLoadToken) return;
                contentDiv.replaceChildren(elementWith('discuss-diff-status', 'Could not render this diff: ' + error.message));
            });
        return;
    }
    if (!_currentDiscussDiffString) return;
    discussApi('/api/discuss/format_patch', {patch: _currentDiscussDiffString, mode: mode})
        .then(function(res) { if (token === _discussDiffLoadToken) contentDiv.innerHTML = res.diff_html; })
        .catch(function(error) { if (token === _discussDiffLoadToken) contentDiv.textContent = 'Could not render this diff: ' + error.message; });
}


        // ── Reviewing what the turn changed ─────────────────────────────
        // The one place a file change is decided. It compares the file as it
        // stands against the copy taken before the turn touched it, so what is
        // offered is what actually happened -- not what the agent said it did.

        var _discussReview = null;
        var _discussReviewMode = 'side-by-side';
        var _discussReviewUnreviewable = [];
        var _discussReviewKeep = {};

        function discussReviewKeep(path, review) {
            if (review) { if (!review.keep[path]) review.keep[path] = {}; return review.keep[path]; }
            if (!_discussReviewKeep[path]) _discussReviewKeep[path] = {};
            return _discussReviewKeep[path];
        }

        function refreshDiscussReview(options) {
            if (!_discussConversationId) return;
            var conversationId = _discussConversationId;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(conversationId) + '/changes',
                       {mode: _discussReviewMode})
                .then(function(res) {
                    if (conversationId !== _discussConversationId) return;
                    _discussReview = res.files || [];
                    _discussReviewUnreviewable = res.unreviewable || [];
                    // Anything no longer on offer forgets its ticks, so a file
                    // reviewed twice does not inherit the last answer.
                    var live = {};
                    _discussReview.forEach(function(file) { live[file.path] = true; });
                    Object.keys(_discussReviewKeep).forEach(function(path) {
                        if (!live[path]) delete _discussReviewKeep[path];
                    });
                    if (options && options.dropEditedSelection) dropDiscussSelectionIfEdited(_discussReview);
                    renderDiscussSnapshot();
                })
                .catch(function() { /* Nothing to review is not an error worth showing. */ });
        }

        // A finished turn that changed the file the selection came from has
        // made the chip stale: its words and position may no longer be there.
        // It goes rather than being guessed at; a turn that left that file
        // alone keeps it for the follow-up question.
        function dropDiscussSelectionIfEdited(files) {
            var doc = _discussSelection && discussTurnDocument();
            if (!doc) return;
            var edited = (files || []).some(function(file) {
                var target = prosviewTargetForRepositoryPath(file.path);
                return target && target.kind === doc.kind && target.path === doc.path;
            });
            if (!edited) return;
            _discussSelection = ''; _discussSelectionRange = null; _discussSelectionSnapshot = null;
            _discussSelectionSourceTaskId = null; _discussLiveDocument = null;
            if (!document.getElementById('discussInput').value && !_discussIncludeCurrentDocument) _discussDraftDocument = null;
            showDiscussSelectionInText(false);
            saveDiscussDraft(); renderDiscussContext(); renderDiscussTaskMode();
        }

        // One row, used by the card and by the expanded view. Both write the
        // same ticked state, so a change made in either shows in the other.
        function renderDiscussReviewBlock(file, block, onChange, review) {
            var keep = discussReviewKeep(file.path, review);
            var row = elementWith('discuss-review-block');
            var label = document.createElement('label');
            label.className = 'discuss-review-choice';
            var box = document.createElement('input');
            box.type = 'checkbox';
            box.checked = keep[block.id] !== false;
            box.setAttribute('aria-label', 'Keep the change at ' + block.header);
            var where = elementWith('discuss-review-where', block.header);
            var state = elementWith('discuss-review-state', '');
            label.appendChild(box);
            label.appendChild(where);
            label.appendChild(state);
            row.appendChild(label);

            var table = elementWith('discuss-review-table');
            table.innerHTML = block.html;
            row.appendChild(table);

            function paint() {
                row.classList.toggle('discuss-review-block-off', !box.checked);
                state.textContent = box.checked ? 'Kept' : 'Will be undone';
            }
            box.onchange = function() {
                keep[block.id] = box.checked;
                if (review && review.save) {
                    if (!review.fingerprints) review.fingerprints = {};
                    review.fingerprints[file.path] = file.fingerprint;
                    review.save();
                }
                paint();
                if (onChange) onChange();
            };
            paint();
            return {row: row, box: box};
        }

        function renderDiscussReviewCard(file, review) {
            var card = elementWith('discuss-review');
            card.dataset.reviewPath = file.path;

            // A compact receipt: the diff itself opens in Expand view, so a
            // long edit never fills the chat.
            var head = elementWith('discuss-review-head');
            var name = document.createElement('code');
            name.className = 'discuss-review-path';
            name.textContent = file.path;
            head.appendChild(name);
            var count = elementWith('discuss-review-count');
            head.appendChild(count);
            card.appendChild(head);

            // The changes are already in the file. The card says so, and its
            // one decision is what, if anything, to undo. Ticks are made in
            // Expand view; the card reads them back.
            var keep = discussReviewKeep(file.path, review);
            var blocks = file.blocks || [];
            var kept = blocks.filter(function(block) { return keep[block.id] !== false; });
            var off = blocks.length - kept.length;
            var plural = function(n) { return n + (n === 1 ? ' change' : ' changes'); };
            count.textContent = off
                ? 'Undoing ' + off + ' of ' + blocks.length
                : (review ? review.agentLabel : discussAgentLabel()) + ' changed this file · ' + plural(blocks.length) + ' · saved';

            var actions = elementWith('discuss-review-actions');
            var expand = document.createElement('button');
            expand.type = 'button';
            expand.className = 'discuss-chip discuss-chip-outline';
            expand.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px; vertical-align: text-bottom;"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg> Expand view';
            expand.onclick = function(event) { event.preventDefault(); openDiscussReviewModal(file.path, review); };
            actions.appendChild(expand);
            actions.appendChild(elementWith('discuss-review-hint', 'Kept when you ask your next question.'));
            var undoAll = document.createElement('button');
            undoAll.type = 'button';
            undoAll.className = 'discuss-review-undo-all';
            undoAll.textContent = 'Undo all';
            undoAll.hidden = !kept.length;
            undoAll.onclick = function() { applyDiscussReview(file, [], undoAll, review); };
            actions.appendChild(undoAll);
            var apply = document.createElement('button');
            apply.type = 'button';
            apply.className = 'discuss-primary';
            apply.textContent = !off ? 'Looks good' : (kept.length ? 'Undo ' + plural(off) : 'Undo all');
            apply.onclick = function() {
                applyDiscussReview(file, kept.map(function(block) { return block.id; }), apply, review);
            };
            actions.appendChild(apply);
            card.appendChild(actions);
            if (review && review.applying) card.querySelectorAll('button').forEach(function(button) { button.disabled = true; });
            return card;
        }

        function applyDiscussReview(file, keep, button, review) {
            if (review && review.applying) return;
            button.disabled = true;
            if (review) { review.applying = true; review.error = ''; review.render(); }
            var conversationId = review ? review.conversationId : _discussConversationId;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(conversationId) + '/changes/apply', {
                path: file.path,
                keep: keep,
                fingerprint: file.fingerprint || ''
            })
                .then(function(res) {
                    if (review) {
                        delete review.keep[file.path]; review.applying = false;
                        return review.refresh().then(function() {
                            if (!review.files.length && !review.unreviewable.length && review.onSettled) return review.onSettled();
                        });
                    }
                    document.getElementById('discussAnnouncement').textContent = res.dropped
                        ? 'Undid ' + (res.total - res.kept.length) + ' of ' + res.total + ' changes in ' + file.path
                        : 'Kept every change in ' + file.path;
                    delete _discussReviewKeep[file.path];
                    refreshDiscussReview();
                    scheduleDiscussSnapshot();
                })
                .catch(function(error) {
                    if (review) {
                        review.applying = false;
                        return review.refresh().then(function() { review.error = error.message; review.render(); });
                    }
                    button.disabled = false;
                    renderDiscussError(error.message);
                    // The file moved underneath the writer; show them what it
                    // says now rather than leaving a stale offer on screen.
                    refreshDiscussReview();
                });
        }

        // Codex reports `kind` as a plain string on some items and as an object
        // on others, so anything that is not a word is simply not shown rather
        // than stringified into the card.
        function discussChangeKindLabel(change) {
            var kind = change.kind;
            if (typeof kind === 'string') return kind;
            if (kind && typeof kind === 'object') {
                var named = kind.type || kind.kind || kind.name;
                if (typeof named === 'string') return named;
                var keys = Object.keys(kind);
                if (keys.length === 1 && typeof keys[0] === 'string') return keys[0];
            }
            return '';
        }

        // Codex sends absolute paths; the dock speaks in repository-relative
        // ones everywhere else, so the root is trimmed off when it matches.
        function renderDiscussChangePath(change) {
            var path = elementWith('discuss-diff-path');
            var name = document.createElement('code');
            name.textContent = discussRepoRelativePath(change.path) || 'unknown file';
            name.title = change.path || '';
            path.appendChild(name);
            var kind = discussChangeKindLabel(change);
            if (kind) path.appendChild(elementWith('discuss-diff-kind', kind));
            return path;
        }

        function discussRepoRelativePath(value) {
            var raw = String(value || '');
            var root = (_discussSnapshot && _discussSnapshot.root) || '';
            if (root && raw.indexOf(root) === 0) {
                return raw.slice(root.length).replace(/^[\\/]+/, '');
            }
            return raw;
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
            var seesSlot = document.getElementById('discussSees'); seesSlot.replaceChildren();
            var doc = discussTurnDocument();
            if (doc && _discussPendingAction && _discussIncludeCurrentDocument) {
                // A selection action judges the passage in its scene, so the
                // whole file goes along with it unless the writer removes it.
                var current = elementWith('discuss-chip discuss-chip-current', doc.path);
                current.title = 'File sent with this action';
                var removeCurrent = document.createElement('button');
                removeCurrent.type = 'button'; removeCurrent.textContent = '×';
                removeCurrent.setAttribute('aria-label', 'Remove current document ' + doc.path);
                removeCurrent.onclick = function() {
                    _discussIncludeCurrentDocument = false;
                    saveDiscussDraft();
                    renderDiscussContext();
                    document.getElementById('discussAnnouncement').textContent = 'Document removed from context';
                };
                current.appendChild(removeCurrent); context.appendChild(current);
            } else if (doc && !_discussRepositoryAction) {
                // What an editor extension calls IDE context: the agent is told
                // which file is open and reads it from the project itself.
                // Over the dashboard nothing is open, so name the document the
                // conversation is still about rather than claim it is open.
                // It sits in the send row's spare space as just the path; the
                // sentence it stands for is still read out and kept in the text.
                var away = !_discussDraftDocument && !discussDocument();
                var sees = elementWith('discuss-sees');
                if (away) {
                    sees.textContent = (doc.kind === 'file' ? 'Last file: ' : 'Last scene: ') + doc.path;
                } else {
                    sees.appendChild(Object.assign(document.createElement('span'),
                        {className: 'sr-only', textContent: discussAgentLabel() + ' knows you are in '}));
                    sees.appendChild(document.createTextNode(doc.path));
                }
                sees.title = (away ? '' : discussAgentLabel() + ' knows you are in ' + doc.path + '. ')
                    + 'Each question says which file is open; ' + discussAgentLabel()
                    + ' reads it from the project when the question needs it. Type @ to mention other files.';
                seesSlot.appendChild(sees);
            }
            var selection = document.getElementById('discussSelectionChip');
            selection.hidden = !_discussSelection;
            selection.replaceChildren();
            if (_discussSelection) {
                var words = _discussSelection.trim().split(/\s+/).filter(Boolean).length;
                var selectionText = elementWith('discuss-selection-chip-text',
                    'Selection · ' + words + ' words · “' + _discussSelection.slice(0, 72) + (_discussSelection.length > 72 ? '…' : '') + '”');
                selectionText.title = _discussSelection.slice(0, 600);
                selection.appendChild(selectionText);
                // Pointing at the chip lights up the passage it stands for.
                selection.onmouseenter = function() { showDiscussSelectionInText(true); };
                selection.onmouseleave = function() {
                    if (!goToDiscussSelection.timer || Date.now() - (goToDiscussSelection.at || 0) > 2000) showDiscussSelectionInText(false);
                };
                // A click goes there: lit, and brought to the middle of the view.
                selectionText.setAttribute('role', 'button');
                selectionText.tabIndex = 0;
                selectionText.onclick = function() { goToDiscussSelection(); };
                selectionText.onkeydown = function(event) {
                    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); goToDiscussSelection(); }
                };
                var removeSelection = document.createElement('button');
                removeSelection.type = 'button'; removeSelection.textContent = '×';
                removeSelection.setAttribute('aria-label', 'Remove selected text from ' + discussAgentLabel() + ' context');
                removeSelection.onclick = function() {
                    _discussSelection = ''; _discussSelectionRange = null; _discussSelectionSnapshot = null;
                    _discussSelectionSourceTaskId = null; _discussLiveDocument = null;
                    _discussPendingAction = null; _discussRetryOfTaskId = null;
                    if (!document.getElementById('discussInput').value) _discussDraftDocument = null;
                    saveDiscussDraft(); renderDiscussContext(); renderDiscussTaskMode();
                    document.getElementById('discussAnnouncement').textContent = 'Selection removed from context';
                };
                selection.appendChild(removeSelection);
            }
        }

        var DISCUSS_SELECTION_HOVER_HL = 'proseview-selection-hover';

        // The DOM range of the attached selection in the scene or file on
        // screen: by its recorded offsets in a scene, else by its text.
        function discussSelectionDomRange() {
            if (!_discussSelection) return null;
            var view = document.documentElement.dataset.view;
            var doc = discussTurnDocument();
            var onScreen = discussDocument();
            if (!doc || !onScreen || doc.kind !== onScreen.kind || doc.path !== onScreen.path) return null;
            if (view === 'scene' && typeof _pmView !== 'undefined' && _pmView && _discussSelectionRange
                && typeof aiDocTextMap === 'function') {
                try {
                    var map = aiDocTextMap(_pmView.state.doc).posMap;
                    var from = null, to = null;
                    for (var i = _discussSelectionRange.start; i < _discussSelectionRange.end && from === null; i++) from = map[i];
                    for (var j = _discussSelectionRange.end - 1; j >= _discussSelectionRange.start && to === null; j--) to = map[j];
                    if (from !== null && to !== null) {
                        var start = _pmView.domAtPos(from), end = _pmView.domAtPos(to + 1);
                        var range = document.createRange();
                        range.setStart(start.node, start.offset);
                        range.setEnd(end.node, end.offset);
                        return range;
                    }
                } catch (e) { /* fall through to the text */ }
            }
            var root = view === 'scene' ? document.getElementById('sceneProseHost')
                : view === 'file' ? document.getElementById('filePreviewBody') : null;
            if (!root) return null;
            var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            var nodes = [], text = '', node;
            while ((node = walker.nextNode())) { nodes.push({node: node, at: text.length}); text += node.nodeValue; }
            var needle = _discussSelection.trim();
            var found = text.indexOf(needle);
            if (found < 0) return null;
            var locate = function(offset) {
                for (var k = nodes.length - 1; k >= 0; k--) {
                    if (nodes[k].at <= offset) return {node: nodes[k].node, offset: offset - nodes[k].at};
                }
                return null;
            };
            var a = locate(found), b = locate(found + needle.length);
            if (!a || !b) return null;
            var fallback = document.createRange();
            fallback.setStart(a.node, a.offset);
            fallback.setEnd(b.node, b.offset);
            return fallback;
        }

        function goToDiscussSelection() {
            goToDiscussSelection.at = Date.now();
            showDiscussSelectionInText(true);
            var range = discussSelectionDomRange();
            if (!range) return;
            var el = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
            if (el) el.scrollIntoView({block: 'center', behavior: 'smooth'});
            // Stays lit a moment after the pointer leaves, long enough to find.
            clearTimeout(goToDiscussSelection.timer);
            goToDiscussSelection.timer = setTimeout(function() {
                var chip = document.getElementById('discussSelectionChip');
                if (!chip || !chip.matches(':hover')) showDiscussSelectionInText(false);
            }, 2000);
        }

        function showDiscussSelectionInText(on) {
            if (typeof CSS === 'undefined' || !CSS.highlights || typeof Highlight === 'undefined') return;
            CSS.highlights.delete(DISCUSS_SELECTION_HOVER_HL);
            if (!on) return;
            var range = discussSelectionDomRange();
            if (!range) return;
            var highlight = new Highlight(range);
            highlight.priority = 1;  // over the quieter pinned selection
            // Only lit, never scrolled to: a hover must not move the page.
            CSS.highlights.set(DISCUSS_SELECTION_HOVER_HL, highlight);
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

        // Favorites the writer marked as being about selected text, such as
        // "Polish this". The rest are replies, such as "good, apply it", and
        // stay on offer with or without a selection.
        function selectionOnlyDiscussInstructions() {
            try { return normalizedDiscussInstructions(JSON.parse(localStorage.getItem('proseview-codex-selection-only-instructions') || '[]'), 12); }
            catch(e) { return []; }
        }

        // Presets from the book's settings are selection presets by name.
        function discussInstructionNeedsSelection(value) {
            return selectionOnlyDiscussInstructions().indexOf(value) >= 0
                || (configuredDiscussInstructions().indexOf(value) >= 0 && favoriteDiscussInstructions().indexOf(value) < 0);
        }

        function toggleDiscussInstructionSelectionOnly(value, refresh) {
            var rows = selectionOnlyDiscussInstructions(); var index = rows.indexOf(value);
            if (index >= 0) rows.splice(index, 1); else rows.unshift(value);
            try { localStorage.setItem('proseview-codex-selection-only-instructions', JSON.stringify(rows.slice(0, 12))); } catch(e) {}
            if (refresh) { refresh(); return; }
            renderDiscussTaskMode();
            var details = document.querySelector('#discussTaskMode .discuss-presets-more');
            if (!details) return;
            details.open = true;
            var label = 'Only with selected text: ' + value;
            Array.prototype.some.call(details.querySelectorAll('.discuss-selection-only'), function(button) {
                if (button.getAttribute('aria-label') !== label) return false;
                button.focus();
                return true;
            });
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

        // What Polish selection sends: the writer's own saved "Polish..."
        // instruction when there is one, so P matches the Quick send button.
        function polishDiscussInstruction() {
            var saved = presetDiscussInstructions().concat(recentDiscussInstructions())
                .filter(function(value) { return /^polish\b/i.test(value); });
            return saved[0] || 'Polish this';
        }

        function toggleDiscussInstructionFavorite(value, reopenMenu, refresh) {
            var rows = favoriteDiscussInstructions(); var index = rows.indexOf(value);
            if (index >= 0) rows.splice(index, 1); else rows.unshift(value);
            try { localStorage.setItem('proseview-codex-favorite-instructions', JSON.stringify(rows.slice(0, 12))); } catch(e) {}
            if (refresh) { refresh(); return; }
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
            var visibleDocument = discussDocument();
            if (visibleDocument && !_discussSelection && !_discussPendingAction && !_discussRepositoryAction) {
                _discussDraftDocument = Object.assign({}, visibleDocument);
                _discussIncludeCurrentDocument = true;
                renderDiscussContext();
            }
            saveDiscussDraft();
            if (details) details.open = false;
            document.getElementById('discussInput').focus();
            // A preset is a whole message: choosing it sends it. While a turn
            // is running Send is unavailable and the text waits in the box.
            syncDiscussSendEmpty();
            sendDiscussQuestion();
        }

        function appendDiscussPresetMenuRow(node, value, favorite, details, controls) {
            var wrap = elementWith('discuss-preset-menu-row');
            var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-preset-menu-choice'; button.textContent = value;
            button.title = value;
            button.onclick = function() { (controls ? controls.choose : chooseDiscussInstruction)(value, details); };
            var star = document.createElement('button'); star.type = 'button'; star.className = 'discuss-favorite'; star.textContent = favorite ? '★' : '☆';
            star.setAttribute('aria-label', (favorite ? 'Remove from favorites: ' : 'Add to favorites: ') + value);
            star.onclick = function() { toggleDiscussInstructionFavorite(value, true, controls && controls.refresh); };
            wrap.appendChild(button);
            if (favorite) {
                var only = selectionOnlyDiscussInstructions().indexOf(value) >= 0;
                var scope = document.createElement('button'); scope.type = 'button'; scope.className = 'discuss-selection-only';
                scope.textContent = 'Selection';
                scope.title = only ? 'Shown only while text is selected' : 'Shown always. Click to show only while text is selected';
                scope.setAttribute('aria-label', 'Only with selected text: ' + value);
                scope.setAttribute('aria-pressed', only ? 'true' : 'false');
                scope.onclick = function() { toggleDiscussInstructionSelectionOnly(value, controls && controls.refresh); };
                wrap.appendChild(scope);
            } else wrap.appendChild(document.createElement('span'));
            wrap.appendChild(star); node.appendChild(wrap);
        }

        function appendDiscussPresetsMenu(node, presets, recents, controls) {
            var details = document.createElement('details'); details.className = 'discuss-presets-more';
            var summary = document.createElement('summary'); summary.textContent = presets.length ? 'More…' : 'Add from recent…';
            summary.setAttribute('role', 'button');
            summary.setAttribute('aria-label', 'More presets and recent instructions');
            details.appendChild(summary);
            var popover = elementWith('discuss-presets-popover'); popover.id = controls ? 'roomPresetsPopover' : 'discussPresetsPopover';
            var favorites = favoriteDiscussInstructions();
            if (presets.length) {
                var presetHeading = document.createElement('strong'); presetHeading.textContent = 'Presets'; popover.appendChild(presetHeading);
                presets.forEach(function(value) {
                    appendDiscussPresetMenuRow(popover, value, favorites.indexOf(value) >= 0, details, controls);
                });
            }
            if (recents.length) {
                var recentHeading = document.createElement('strong'); recentHeading.textContent = 'Recent'; popover.appendChild(recentHeading);
                recents.forEach(function(value) { appendDiscussPresetMenuRow(popover, value, false, details, controls); });
            }
            details.appendChild(popover); node.appendChild(details);
        }

        // A menu: Escape or a click elsewhere puts it away. Escape is taken
        // before the page's own handlers, which would otherwise claim it.
        document.addEventListener('keydown', function(event) {
            if (event.key !== 'Escape') return;
            var menu = document.querySelector('.discuss-presets-more[open]');
            if (!menu) return;
            event.preventDefault();
            event.stopPropagation();
            menu.open = false;
            var summary = menu.querySelector('summary');
            if (summary) summary.focus();
        }, true);

        document.addEventListener('mousedown', function(event) {
            document.querySelectorAll('.discuss-presets-more[open]').forEach(function(menu) {
                if (!menu.contains(event.target)) menu.open = false;
            });
        });

        function discussTaskModeControlKey(element) {
            return element.className + '|' + (element.getAttribute('aria-label') || element.textContent);
        }

        // The strip is rebuilt whenever the dock learns something, and a
        // rebuild recreates the presets menu closed. A menu the writer opened
        // stays open, with focus on the control they were on.
        // Nothing to send, nothing to press: Send waits for text, unless what
        // it would send is an action that needs none (or it is "Try again").
        function syncDiscussSendEmpty() {
            var button = document.getElementById('discussSend');
            var input = document.getElementById('discussInput');
            if (!button || !input) return;
            var empty = !input.value.trim() && !_discussPendingAction && !_discussRepositoryAction && !_discussOpenFailed;
            button.dataset.empty = empty ? 'true' : 'false';
            button.setAttribute('aria-disabled', empty || button.disabled ? 'true' : 'false');
            // A preset sends itself; with a draft in the box it would replace
            // the draft, so it waits until the box is empty again.
            var draft = !!input.value.trim();
            document.querySelectorAll('#discussTaskMode .discuss-preset-inline, #discussTaskMode .discuss-preset-menu-choice').forEach(function(preset) {
                preset.disabled = draft;
                preset.title = draft ? 'Clear the question box to send this' : 'Send: ' + preset.textContent;
            });
        }

        function renderDiscussTaskMode() {
            syncDiscussSendEmpty();
            var node = document.getElementById('discussTaskMode');
            if (!node) return;
            var menu = node.querySelector('.discuss-presets-more');
            var menuOpen = !!(menu && menu.open);
            var focused = node.contains(document.activeElement) ? discussTaskModeControlKey(document.activeElement) : '';
            buildDiscussTaskMode(node);
            // Quick send sits inside the empty question box; every other mode
            // keeps its own row above it.
            var inputWrap = document.querySelector('#discussComposerArea .discuss-input-wrap');
            if (node.dataset.mode === 'presets') {
                if (node.parentNode !== inputWrap) inputWrap.appendChild(node);
            } else if (node.parentNode === inputWrap) {
                inputWrap.parentNode.insertBefore(node, document.getElementById('discussInputLabel'));
            }
            syncDiscussSendEmpty();
            var rebuilt = menuOpen && node.querySelector('.discuss-presets-more');
            if (rebuilt) rebuilt.open = true;
            if (focused) {
                Array.prototype.some.call(node.querySelectorAll('button, summary'), function(control) {
                    if (discussTaskModeControlKey(control) !== focused) return false;
                    control.focus();
                    return true;
                });
            }
        }

        function buildDiscussTaskMode(node) {
            node.replaceChildren();
            delete node.dataset.mode;
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
                : 'Ask anything about your story…';
            // Replies are on offer whenever there is something to answer;
            // selection presets only while there is selected text.
            var offered = _discussSelection ? presets : presets.filter(function(value) {
                return !discussInstructionNeedsSelection(value);
            });
            node.hidden = !(offered.length || (_discussSelection && recents.length));
            node.dataset.mode = 'presets';
            if (!node.hidden) {
                var label = elementWith('discuss-presets-label', 'Quick send:'); node.appendChild(label);
                var inline = elementWith('discuss-presets-inline');
                offered.slice(0, 3).forEach(function(value) {
                    var button = document.createElement('button');
                    button.type = 'button'; button.className = 'discuss-preset-inline'; button.textContent = value;
                    button.onclick = function() { chooseDiscussInstruction(value); };
                    inline.appendChild(button);
                });
                if (offered.length) node.appendChild(inline);
                if (offered.length > 3 || recents.length || favoriteDiscussInstructions().length) {
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


        // ---- Model picker --------------------------------------------------
        // What the next turn runs as, chosen where the turn is typed. The
        // choice belongs to this conversation: starting a new one goes back to
        // the agent's own default, so an expensive setting picked for one hard
        // question does not quietly become the standing cost of every later
        // one. Both agents apply it from the next turn, never to the running
        // one, and the chip says so rather than implying otherwise.
        var _discussModelCatalogs = {codex: null, claude: null};
        var _discussModelCatalogPending = {codex: false, claude: false};
        var _discussModelPickerOpen = false;
        var _discussModelBusy = false;

        function discussModelSelection() {
            var selection = (_discussSnapshot && _discussSnapshot.model) || {};
            return {model: selection.model || '', effort: selection.effort || ''};
        }

        function discussModelCatalog() {
            return _discussModelCatalogs[_discussAgent] || null;
        }

        function discussModelRow(catalog, modelId) {
            if (!catalog || !modelId) return null;
            var rows = catalog.models || [];
            for (var i = 0; i < rows.length; i++) {
                if (rows[i].id === modelId) return rows[i];
            }
            return null;
        }

        function discussModelEfforts(catalog, modelId) {
            var row = discussModelRow(catalog, modelId);
            return (row && row.efforts) || [];
        }

        function loadDiscussModelCatalog(agent) {
            agent = DISCUSS_AGENTS.indexOf(agent) >= 0 ? agent : _discussAgent;
            if (_discussModelCatalogs[agent] || _discussModelCatalogPending[agent]) return;
            _discussModelCatalogPending[agent] = true;
            discussApi('/api/discuss/models', {agent: agent}).then(function(data) {
                _discussModelCatalogs[agent] = data.catalog || null;
                if (agent === _discussAgent) renderDiscussModelChip();
            }).catch(function() {
                // A roster Prosview could not read is not a roster to invent.
                // The chip stays hidden and questions keep working on the
                // agent's own default.
                _discussModelCatalogs[agent] = null;
            }).finally(function() {
                _discussModelCatalogPending[agent] = false;
            });
        }

        function renderDiscussModelChip() {
            var chip = document.getElementById('discussModelChip');
            if (!chip) return;
            var catalog = discussModelCatalog();
            if (!catalog) {
                chip.hidden = true;
                closeDiscussModelPicker();
                return;
            }
            chip.hidden = false;
            var selection = discussModelSelection();
            var fallback = catalog.default || {};
            var inherited = !selection.model && !selection.effort;
            var row = discussModelRow(catalog, selection.model);
            var name = selection.model
                ? ((row && row.label) || selection.model)
                : (fallback.label || fallback.model || 'Default');
            var effort = selection.effort || (selection.model ? ((row && row.default_effort) || '') : (fallback.effort || ''));
            chip.dataset.inherited = inherited ? 'true' : 'false';
            document.getElementById('discussModelName').textContent = name;
            var effortNode = document.getElementById('discussModelEffort');
            effortNode.textContent = effort;
            effortNode.previousElementSibling.hidden = !effort;
            var snapshot = _discussSnapshot || {};
            var reason = '';
            if (snapshot.active_turn_id) reason = 'Wait for ' + discussAgentLabel() + ' to finish before changing model.';
            else if (snapshot.active_request_id) reason = 'Wait for this question to start before changing model.';
            _discussModelBusy = !!reason;
            chip.disabled = _discussModelBusy;
            chip.title = reason || (inherited
                ? 'Following ' + (catalog.default.source || 'the agent default') + '. Click to choose a model.'
                : 'Pinned to this conversation. Click to change.');
            chip.setAttribute('aria-label', 'Model: ' + name + (effort ? ', effort ' + effort : '') + '. Change model');
            if (_discussModelBusy) closeDiscussModelPicker();
            if (_discussModelPickerOpen) renderDiscussModelPicker();
        }

        function renderDiscussModelPicker() {
            var catalog = discussModelCatalog();
            if (!catalog) return;
            renderChatModelOptions({catalog: catalog, selection: discussModelSelection(), agentLabel: discussAgentLabel(),
                list: document.getElementById('discussModelList'), efforts: document.getElementById('discussModelEfforts'),
                description: document.getElementById('discussModelEffortDesc'), foot: document.getElementById('discussModelFoot'),
                chooseModel: chooseDiscussModel, chooseEffort: chooseDiscussEffort, note: _discussModelNote});
        }

        // Codex advertises a different ladder per model, so the row shows every
        // rung any model offers and greys out the ones this model does not.
        function discussModelEffortUnion(catalog) {
            var seen = Object.create(null);
            var union = [];
            (catalog.models || []).forEach(function(row) {
                (row.efforts || []).forEach(function(entry) {
                    if (seen[entry.id]) return;
                    seen[entry.id] = true;
                    union.push(entry);
                });
            });
            return union;
        }

        var _discussModelNote = '';

        function saveDiscussModel(selection, note) {
            if (!_discussConversationId) return;
            _discussModelNote = note || '';
            if (_discussSnapshot) _discussSnapshot.model = {model: selection.model, effort: selection.effort};
            renderDiscussModelChip();
            if (_discussModelPickerOpen) renderDiscussModelPicker();
            discussApi(
                '/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/model',
                {model: selection.model, effort: selection.effort}
            ).then(function(data) {
                if (_discussSnapshot) _discussSnapshot.model = data.model || {model: '', effort: ''};
                if (_roomSettings && _roomSettings.chat_models) _roomSettings.chat_models[_discussAgent] = data.model || {model: '', effort: ''};
                renderDiscussModelChip();
                document.getElementById('discussAnnouncement').textContent =
                    'Model set to ' + document.getElementById('discussModelName').textContent
                    + (selection.effort ? ' at ' + selection.effort + ' effort' : '');
            }).catch(function(error) {
                renderDiscussError(error.message);
                scheduleDiscussSnapshot();
            });
        }

        function chooseDiscussModel(modelId) {
            var catalog = discussModelCatalog();
            if (!catalog) return;
            var selection = discussModelSelection();
            if (!modelId) {
                saveDiscussModel({model: '', effort: ''}, '');
                return;
            }
            var ladder = discussModelEfforts(catalog, modelId);
            // Carry forward whatever the chip was showing, including an effort
            // that came from the agent's own configuration: picking a model
            // should not quietly change how hard it thinks, and leaving it
            // unpinned would leave the chip claiming an effort nobody sent.
            var effort = selection.effort || (catalog.default && catalog.default.effort) || '';
            var supported = ladder.some(function(entry) { return entry.id === effort; });
            var note = '';
            if (!effort) {
                effort = '';
            } else if (!supported) {
                // Keep the writer's intent -- they asked for the hardest
                // thinking this model has -- rather than silently dropping to
                // the model's own default.
                var wanted = effort;
                effort = ladder.length ? ladder[ladder.length - 1].id : '';
                var row = discussModelRow(catalog, modelId);
                note = wanted + ' is not available on ' + ((row && row.label) || modelId)
                    + (effort ? ' — using ' + effort + '.' : '.');
            }
            saveDiscussModel({model: modelId, effort: effort}, note);
        }

        function chooseDiscussEffort(effortId) {
            var selection = discussModelSelection();
            if (!selection.model) return;
            saveDiscussModel({model: selection.model, effort: effortId}, '');
        }

        function toggleDiscussModelPicker() {
            if (_discussModelPickerOpen) {
                closeDiscussModelPicker();
                return;
            }
            var catalog = discussModelCatalog();
            if (!catalog || _discussModelBusy) return;
            _discussModelNote = '';
            _discussModelPickerOpen = true;
            document.getElementById('discussModelPicker').hidden = false;
            document.getElementById('discussModelChip').setAttribute('aria-expanded', 'true');
            renderDiscussModelPicker();
            var first = document.querySelector('#discussModelList .discuss-model-option[aria-checked="true"]')
                || document.querySelector('#discussModelList .discuss-model-option');
            if (first) first.focus();
        }

        function closeDiscussModelPicker(options) {
            if (!_discussModelPickerOpen) return;
            _discussModelPickerOpen = false;
            _discussModelNote = '';
            var picker = document.getElementById('discussModelPicker');
            if (picker) picker.hidden = true;
            var chip = document.getElementById('discussModelChip');
            if (chip) {
                chip.setAttribute('aria-expanded', 'false');
                if (options && options.focus && !chip.hidden && !chip.disabled) chip.focus();
            }
        }

        // mousedown, not click: choosing an option rebuilds the list, so by the
        // time a click bubbles to the document its target is detached and no
        // longer answers closest() -- which dismissed the picker on every
        // selection made inside it.
        document.addEventListener('mousedown', function(event) {
            if (!_discussModelPickerOpen) return;
            if (event.target.closest && event.target.closest('.discuss-model-wrap')) return;
            closeDiscussModelPicker();
        });

        // Only while the picker is open: the dock otherwise leaves Escape to
        // whatever the writer is inside, and an always-on handler would steal
        // the key from the editor underneath.
        document.addEventListener('keydown', function(event) {
            if (!_discussModelPickerOpen || event.key !== 'Escape') return;
            event.preventDefault();
            event.stopPropagation();
            closeDiscussModelPicker({focus: true});
        });

        document.getElementById('discussModelPicker').addEventListener('keydown', function(event) {
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
            var options = Array.prototype.slice.call(
                this.querySelectorAll('.discuss-model-option, .discuss-model-effort-option:not(:disabled)')
            );
            var index = options.indexOf(document.activeElement);
            if (index < 0) return;
            event.preventDefault();
            var step = event.key === 'ArrowDown' ? 1 : options.length - 1;
            options[(index + step) % options.length].focus();
        });

        function discussMentionAtCaret() {
            var input = document.getElementById('discussInput');
            if (input.selectionStart !== input.selectionEnd) return null;
            var before = input.value.slice(0, input.selectionStart);
            // @ for a file or folder, $ for a skill, as in the extensions.
            var match = before.match(/(^|\s)([@$])([^\s@$]*)$/);
            if (!match) return null;
            return {
                start: before.length - match[3].length - 1, end: input.selectionStart,
                query: match[3], trigger: match[2],
            };
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
            var skills = mention.trigger === '$';
            var heading = document.getElementById('discussContextHeading');
            if (heading) heading.textContent = skills ? discussAgentLabel() + ' skills' : 'Files and folders';
            if (skills && !_discussSkillsLoaded) {
                loadDiscussSkillList().then(function() { if (discussMentionAtCaret()) renderDiscussContextOptions(); });
            }
            _discussContextChoices = skills
                ? _discussSkills.filter(function(skill) {
                    return !query || (skill.name + ' ' + (skill.display_name || '') + ' ' + (skill.description || '')).toLowerCase().includes(query);
                }).slice(0, 12).map(function(skill) {
                    return {kind: 'skill', path: skill.path, name: skill.name, description: skill.description || ''};
                })
                : discussContextCandidates().filter(function(candidate) {
                    if (_discussAttachments.some(function(item) { return item.kind === candidate.kind && item.path === candidate.path; })) return false;
                    return !query || candidate.path.toLowerCase().includes(query) || candidate.name.toLowerCase().includes(query);
                }).slice(0, 12);
            _discussContextActiveIndex = Math.min(_discussContextActiveIndex, Math.max(0, _discussContextChoices.length - 1));
            var options = document.getElementById('discussContextOptions'); options.replaceChildren();
            if (!_discussContextChoices.length) {
                options.appendChild(elementWith('discuss-context-empty', skills
                    ? (!_discussSkillsLoaded ? 'Loading skills…' : query ? 'No matching skills' : 'No skills in this project')
                    : (query ? 'No matching files or folders' : 'Type to search files and folders')));
            }
            _discussContextChoices.forEach(function(choice, index) {
                var option = document.createElement('button');
                option.type = 'button'; option.className = 'discuss-context-option'; option.id = 'discussContextOption' + index;
                option.setAttribute('role', 'option'); option.setAttribute('aria-selected', String(index === _discussContextActiveIndex));
                option.dataset.path = choice.path; option.dataset.kind = choice.kind;
                var icon = elementWith('discuss-context-option-icon', choice.kind === 'skill' ? '$' : choice.kind === 'file' ? '▤' : '▸'); icon.setAttribute('aria-hidden', 'true');
                option.appendChild(icon);
                if (choice.kind === 'skill') {
                    var label = elementWith('discuss-context-option-path', choice.name);
                    if (choice.description) {
                        var about = document.createElement('small');
                        about.className = 'discuss-context-option-about';
                        about.textContent = choice.description;
                        label.appendChild(about);
                    }
                    option.appendChild(label);
                } else {
                    option.appendChild(elementWith('discuss-context-option-path', choice.path));
                }
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
            // The mention stays in the question, as @path, the way the Codex
            // and Claude extensions write it; it is read back out on send.
            var token = (choice.kind === 'skill' ? '$' + choice.name : '@' + choice.path) + ' ';
            input.value = input.value.slice(0, mention.start) + token + input.value.slice(mention.end);
            paintDiscussMentions();
            input.setSelectionRange(mention.start + token.length, mention.start + token.length);
            closeDiscussContextPicker();
            saveDiscussDraft();
            document.getElementById('discussAnnouncement').textContent = (choice.kind === 'skill' ? 'Using skill ' + choice.name : 'Mentioned ' + choice.path);
            input.focus();
        }

        // Where the question @-mentions a file or folder, longest path first
        // so `@plans/book-plan.md` is not read as the folder `@plans`.
        function discussMentionRanges(text) {
            var candidates = discussContextCandidates().slice().sort(function(a, b) { return b.path.length - a.path.length; });
            var ranges = [];
            var pattern = /(^|\s)@/g;
            var match;
            while ((match = pattern.exec(text))) {
                var at = match.index + match[0].length;
                var rest = text.slice(at);
                var hit = candidates.filter(function(candidate) {
                    if (rest.indexOf(candidate.path) !== 0) return false;
                    var next = rest.charAt(candidate.path.length);
                    return !next || /[\s,.;:!?)\]'"]/.test(next) || (candidate.kind === 'folder' && next === '/');
                })[0];
                if (hit) ranges.push({start: at - 1, end: at + hit.path.length, kind: hit.kind, path: hit.path});
            }
            return ranges;
        }

        // `$skill` names a skill the agent offers for this project.
        function discussSkillRanges(text) {
            var names = _discussSkills.map(function(skill) { return skill.name; })
                .sort(function(a, b) { return b.length - a.length; });
            var ranges = [];
            var pattern = /(^|\s)\$/g;
            var match;
            while ((match = pattern.exec(text))) {
                var at = match.index + match[0].length;
                var rest = text.slice(at);
                var name = names.filter(function(candidate) {
                    if (rest.indexOf(candidate) !== 0) return false;
                    var next = rest.charAt(candidate.length);
                    return !next || /[\s,.;:!?)]/.test(next);
                })[0];
                if (name) ranges.push({start: at - 1, end: at + name.length, kind: 'skill', name: name});
            }
            return ranges;
        }

        function discussSkillsIn(text) {
            var seen = {};
            return discussSkillRanges(text).map(function(range) {
                return _discussSkills.filter(function(skill) { return skill.name === range.name; })[0];
            }).filter(function(skill) {
                if (!skill || seen[skill.name]) return false;
                seen[skill.name] = true;
                return true;
            });
        }

        var _discussSkillsLoaded = false;
        var _discussSkillsLoading = null;

        // The agent's skills for this project, fetched once per agent.
        function loadDiscussSkillList(force) {
            if (_discussSkillsLoading && !force) return _discussSkillsLoading;
            var agent = _discussAgent || 'codex';
            _discussSkillsLoading = discussApi('/api/discuss/skills', {force_reload: !!force, agent: agent})
                .then(function(data) {
                    _discussSkills = data.skills || [];
                    _discussSkillsLoaded = true;
                    paintDiscussMentions();
                })
                .catch(function() { _discussSkills = []; _discussSkillsLoaded = true; });
            return _discussSkillsLoading;
        }

        function discussMentionsIn(text) {
            var found = [];
            discussMentionRanges(text).forEach(function(range) {
                if (!found.some(function(item) { return item.path === range.path; })) {
                    found.push({kind: range.kind, path: range.path});
                }
            });
            return found;
        }

        // A textarea cannot style part of its text, so a copy of it sits
        // behind, with the mentions marked; the real text is drawn on top.
        function paintDiscussMentions() {
            var input = document.getElementById('discussInput');
            var mirror = document.getElementById('discussInputMirror');
            if (!input || !mirror) return;
            var text = input.value;
            mirror.replaceChildren();
            var last = 0;
            discussMentionRanges(text).concat(discussSkillRanges(text)).sort(function(a, b) {
                return a.start - b.start;
            }).forEach(function(range) {
                if (range.start < last) return;
                mirror.appendChild(document.createTextNode(text.slice(last, range.start)));
                var mark = document.createElement('mark');
                mark.className = 'discuss-mention';
                mark.textContent = text.slice(range.start, range.end);
                mirror.appendChild(mark);
                last = range.end;
            });
            // The trailing space keeps a last empty line its height.
            mirror.appendChild(document.createTextNode(text.slice(last) + ' '));
            mirror.scrollTop = input.scrollTop;
        }

        // Put `@path ` into the question, opening the panel first if needed:
        // the file browser's "Mention in chat" does this.
        function mentionInDiscuss(path) {
            if (roomTabIsOpen()) { roomInsertContext('@' + path + ' '); return; }
            var insert = function() {
                var input = document.getElementById('discussInput');
                if (!input) return;
                var start = input.selectionStart === undefined ? input.value.length : input.selectionStart;
                var before = input.value.slice(0, start);
                var token = (before && !/\s$/.test(before) ? ' ' : '') + '@' + path + ' ';
                input.setRangeText(token, start, input.selectionEnd, 'end');
                paintDiscussMentions();
                saveDiscussDraft();
                input.focus();
                document.getElementById('discussAnnouncement').textContent = 'Mentioned ' + path;
            };
            var input = document.getElementById('discussInput');
            if (_discussConversationId && input && input.getClientRects().length) { insert(); return; }
            if (discussDocument()) {
                var opened = _discussConversationId;
                showDiscussAgentTab(_discussAgent || 'codex');
                if (opened && input && input.getClientRects().length) { insert(); return; }
                var tries = 0;
                (function wait() {
                    if (_discussConversationId) insert();
                    else if (tries++ < 50) setTimeout(wait, 100);
                })();
                return;
            }
            if (typeof sidebarShowToast === 'function') sidebarShowToast('Open a scene or file first, then mention ' + path + ' in the chat.');
        }

        (function initDiscussMentionPaint() {
            var input = document.getElementById('discussInput');
            if (!input) return;
            // Every way the question changes repaints it, including code that
            // sets the value directly.
            var native = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
            Object.defineProperty(input, 'value', {
                configurable: true,
                get: function() { return native.get.call(this); },
                set: function(next) { native.set.call(this, next); paintDiscussMentions(); syncDiscussSendEmpty(); }
            });
            wireChatMentionReplacement(input, function() { return []; });
            input.addEventListener('keydown', function(event) {
                if (deleteChatMention(event, input, [])) event.stopImmediatePropagation();
            }, true);
            input.addEventListener('input', paintDiscussMentions);
            input.addEventListener('input', syncDiscussSendEmpty);
            syncDiscussSendEmpty();
            input.addEventListener('scroll', function() {
                var mirror = document.getElementById('discussInputMirror');
                if (mirror) mirror.scrollTop = input.scrollTop;
            });
        })();

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
            if (!_discussConversationId || button.getAttribute('aria-disabled') === 'true') return;
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
                    _discussReview = []; _discussReviewKeep = {};
                    _discussSnapshot = data.snapshot;
                    _discussSelection = '';
                    _discussSelectionRange = null;
                    _discussSelectionSnapshot = null;
                    _discussSelectionSourceTaskId = null;
                    _discussLiveDocument = null;
                    _discussPendingAction = null;
                    _discussRepositoryAction = null;
                    _discussRetryOfTaskId = null;
                    _discussSelectedSkill = null;
                    _discussAutoRun = false;
                    _discussAttachments = [];
                    _discussIncludeCurrentDocument = false;
                    if (!document.getElementById('discussInput').value) _discussDraftDocument = null;
                    saveDiscussDraft();
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
            var turnDocument = discussTurnDocument();
            if (!turnDocument) return;
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            button.disabled = true;
            button.textContent = 'Sending…';
            document.getElementById('discussAnnouncement').textContent = 'Sending question…';
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: question,
                document: turnDocument,
                selection: _discussSelection,
                selection_range: _discussSelectionRange,
                // Unsaved edits are not on disk for the agent to read.
                live_document: _discussLiveDocument || discussLiveDocumentFor(turnDocument),
                attachments: discussMentionsIn(question).concat(_discussAttachments.filter(function(item) {
                    return question.indexOf('@' + item.path) < 0;
                })),
                include_current_document: _discussIncludeCurrentDocument,
                // A $skill typed in the question is the skill the turn runs.
                skill: _discussSelectedSkill || (function() {
                    var named = discussSkillsIn(question)[0];
                    return named ? {name: named.name, path: named.path} : null;
                })()
            }).then(function() {
                _discussAttachments = [];
                rememberDiscussInstruction(question); input.value = '';
                if (!_discussSelection && !_discussIncludeCurrentDocument) _discussDraftDocument = null;
                saveDiscussDraft(); _discussSelectedSkill = null;
                var restoredLegacyDraft = activateLegacyDiscussDraft(discussDocument(), _discussAgent);
                closeDiscussContextPicker(); renderDiscussContext(); renderDiscussTaskMode(); scheduleDiscussSnapshot();
                document.getElementById('discussAnnouncement').textContent = restoredLegacyDraft
                    ? 'Question queued. Restored another saved draft for this file.'
                    : _discussSelection
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
            if (!_discussDraftDocument) _discussDraftDocument = discussDocument();
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
            if (!document.getElementById('discussInput').value && !_discussSelection) _discussDraftDocument = null;
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
            var turnDocument = discussTurnDocument();
            if (!turnDocument) return;
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
                document: turnDocument,
                action_id: actionId,
                verify_of_task_id: verifyOfTaskId || ''
            }).then(function() {
                if (question) rememberDiscussInstruction(question);
                input.value = '';
                _discussRepositoryAction = null;
                _discussDraftDocument = null;
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

        function runDiscussSelectionAction(
            actionOverride, selectionOverride, rangeOverride, liveDocumentOverride,
            retryCount, retryOfOverride, selectionSnapshotOverride, selectionSourceTaskOverride
        ) {
            var input = document.getElementById('discussInput');
            var button = document.getElementById('discussSend');
            var actionId = actionOverride || _discussPendingAction;
            var selection = selectionOverride || _discussSelection;
            var selectionRange = rangeOverride || _discussSelectionRange;
            var selectionSnapshot = selectionSnapshotOverride || _discussSelectionSnapshot;
            var selectionSourceTaskId = selectionSourceTaskOverride || _discussSelectionSourceTaskId;
            var liveDocument = liveDocumentOverride || _discussLiveDocument;
            var retryOfTaskId = retryOfOverride || _discussRetryOfTaskId;
            var turnDocument = discussTurnDocument();
            if (!actionId || !selection || !_discussConversationId) return;
            if (!turnDocument) return;
            if (button.disabled) {
                retryCount = Number(retryCount || 0);
                if (retryCount < 100) {
                    setTimeout(function() {
                        runDiscussSelectionAction(
                            actionId, selection, selectionRange, liveDocument, retryCount + 1,
                            retryOfTaskId, selectionSnapshot, selectionSourceTaskId
                        );
                    }, 50);
                }
                return;
            }
            var custom = input.value.trim();
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            // Only a rewrite has a proposal to open when it lands.
            if (!discussIsReadingAction(actionId)) _discussAutoReviewRequests[requestId] = true;
            button.disabled = true;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: '',
                document: turnDocument,
                selection: selection,
                selection_range: selectionRange,
                selection_snapshot: selectionSnapshot,
                selection_source_task_id: selectionSourceTaskId,
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
                // A reading pass leaves its subject attached: the obvious next
                // move is "say more about that", and it should not have to be
                // reselected to ask.
                if (!discussIsReadingAction(actionId)) {
                    _discussSelection = ''; _discussSelectionRange = null; _discussSelectionSnapshot = null;
                    _discussSelectionSourceTaskId = null; _discussLiveDocument = null;
                    _discussDraftDocument = null;
                }
                saveDiscussDraft(); closeDiscussContextPicker(); renderDiscussContext(); renderDiscussTaskMode(); scheduleDiscussSnapshot();
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

        // A scene pass takes no selection: the server reads the scene this
        // conversation is looking at. Nothing to highlight, nothing to type --
        // an action that needs a paragraph of setup first is not one anybody
        // reaches for.
        function runDiscussScenePass(actionId) {
            var button = document.getElementById('discussSend');
            var turnDocument = discussTurnDocument();
            if (!actionId || !_discussConversationId || button.disabled) return;
            if (!turnDocument || turnDocument.kind !== 'scene') {
                renderDiscussError('A scene pass reads a manuscript scene. Open one first.');
                return;
            }
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            button.disabled = true;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: '',
                document: turnDocument,
                action_id: actionId,
                action_scope: 'scene',
                attachments: [],
                include_current_document: false
            }).then(function() {
                document.getElementById('discussAnnouncement').textContent =
                    selectionActionLabel(actionId) + ' running on this scene. The manuscript will not change.';
                scheduleDiscussSnapshot();
            }).catch(function(error) {
                renderDiscussError(error.message);
            }).finally(function() {
                button.disabled = false;
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

        // A press on a composer control leaves focus where it was. The presets
        // show only while the writer is in the composer, and WebKit does not
        // focus a pressed button: the box would blur on mousedown, the presets
        // would vanish, and everything above them would shift under the click.
        document.getElementById('discussComposerArea').addEventListener('mousedown', function(event) {
            if (event.target.closest('button, summary')) event.preventDefault();
        });

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
        document.getElementById('discussInput').addEventListener('input', function() {
            var beforeDocument = discussDocumentKey(discussTurnDocument());
            saveDiscussDraft();
            if (activateLegacyDiscussDraft(discussDocument(), _discussAgent)) {
                document.getElementById('discussAnnouncement').textContent =
                    'Restored another saved draft for this file.';
            }
            if (discussDocumentKey(discussTurnDocument()) !== beforeDocument) renderDiscussContext();
            renderDiscussContextOptions();
        });
        document.addEventListener('mousedown', function(event) {
            var picker = document.getElementById('discussContextPicker');
            if (picker.hidden || picker.contains(event.target) || event.target === document.getElementById('discussContextButton') || event.target === document.getElementById('discussInput')) return;
            closeDiscussContextPicker();
        });
        window.addEventListener('resize', positionDiscussContextPicker);
        window.addEventListener('focus', _syncDiscussAmbientSignals);
        window.addEventListener('blur', _syncDiscussAmbientSignals);
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
