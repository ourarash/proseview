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
        var _discussCraftState = {
            active: false,
            cardsOpen: false,
            modeId: 'craft_review',
            lensId: _readCraftLensPref(),
            scopeMode: 'this_scene',
            customScenes: [],
            openInfoId: null,
            focusMenuOpen: false,
            selectedLanes: Object.create(null),
            comedyStyles: [],
            comedyGoals: ['strengthen', 'explore'],
            instructions: '',
            chatDraft: '',
            contextScenePath: '',
            scenePath: '',
            includeFrontmatter: null,
            includeAdjacent: null,
            // Off unless the writer asks: notes go stale quietly, and a planned
            // beat they dropped should not lead every review.
            checkPlan: false,
            // How many revision priorities a custom review may give, remembered
            // across reloads. The cards' Run now always uses the default.
            maxFindings: _readReviewMaxFindingsPref(),
            // Whether a custom review lists moments to keep, remembered across
            // reloads. Run now leaves it off.
            includeKeep: _readReviewIncludeKeepPref(),
            storyContexts: Object.create(null),
            storyContextLoaded: Object.create(null),
            storyContextVersions: Object.create(null),
            storyContextTimers: Object.create(null),
            storyContextSaves: Object.create(null),
            storyContextStatuses: Object.create(null),
            storyContextOpen: null
        };
        var _discussContextDefaultsLoading = null;
        function _discussDefaultFlag(key) {
            var bag = window._discussContextDefaults;
            return bag && typeof bag[key] === 'boolean' ? bag[key] : true;
        }
        function effectiveDiscussFrontmatter() {
            return _discussCraftState.includeFrontmatter === null
                ? _discussDefaultFlag('includeFrontmatter')
                : !!_discussCraftState.includeFrontmatter;
        }
        function effectiveDiscussAdjacent() {
            return _discussCraftState.includeAdjacent === null
                ? _discussDefaultFlag('includeAdjacent')
                : !!_discussCraftState.includeAdjacent;
        }
        function _ensureDiscussContextDefaults() {
            if (window._discussContextDefaults) return Promise.resolve();
            if (_discussContextDefaultsLoading) return _discussContextDefaultsLoading;
            _discussContextDefaultsLoading = discussApi('/api/discuss/discuss-settings').then(function(data) {
                var book = (data && data.settings && data.settings.book) || {};
                window._discussContextDefaults = {
                    includeFrontmatter: book.include_frontmatter !== false,
                    includeAdjacent: book.include_adjacent_scenes !== false
                };
                if (_discussCraftState.active) {
                    renderDiscussTaskMode();
                    renderDiscussSnapshot();
                }
            }).finally(function() { _discussContextDefaultsLoading = null; });
            return _discussContextDefaultsLoading;
        }
        function openDiscussSettings() {
            var dlg = document.getElementById('settingsDialog');
            if (dlg && dlg.parentElement !== document.body) document.body.appendChild(dlg);
            if (typeof openSettings === 'function') openSettings();
            if (typeof selectSettingsTab === 'function') selectSettingsTab('discuss');
            var tab = document.getElementById('settingsTabDiscuss');
            if (tab) tab.focus({preventScroll: true});
        }
        function _readCraftLensPref() {
            try {
                var saved = localStorage.getItem('proseview-craft-lens');
                if (saved) return saved;
            } catch (e) {}
            return 'craft_mckee';
        }
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
        const DISCUSS_AGENTS = ['codex', 'claude', 'agy'];
        const DISCUSS_AGENT_LABELS = {codex: 'Codex', claude: 'Claude', agy: 'Agy'};
        // Reading passes are ordinary questions: no schema, no card, and the
        // thing they read stays attached so a follow-up can refer to it.
        const DISCUSS_READING_ACTIONS = [
            'quick_critique', 'deepen_and_layer', 'comedy_review', 'style_consistency', 'voice_character',
            'pacing_tension', 'clarity_flow', 'continuity', 'next_beats',
            'craft_mckee', 'craft_cron', 'craft_coyne', 'craft_snyder', 'craft_king', 'craft_lamott'
        ];
        function discussIsReadingAction(actionId) {
            return DISCUSS_READING_ACTIONS.indexOf(String(actionId || '')) >= 0;
        }
        // What a writer reaches for on an ordinary afternoon. The test for this
        // list is repetition: these get run on the same scene in draft two and
        // again in draft five.
        //
        // Card descriptions come from the effective skill, served by
        // /api/discuss/actions. Bundled copy stands in while that answer loads
        // or when a writer-owned skill has no description.
        const DISCUSS_SCENE_PASSES = [
            {
                id: 'quick_critique',
                label: 'Quick critique',
                copy: 'What is working against this scene, each note quoting the line and suggesting a fix.'
            },
            {
                id: 'deepen_and_layer',
                label: 'Deepen & layer',
                copy: 'Add unspoken tension, physical micro-business, and emotional resonance in 2–3 key beats.'
            },
            {
                id: 'craft_review',
                label: 'Craft review',
                copy: 'Apply a writing book’s principles, with specific feedback and small next steps.'
            },
            {
                id: 'comedy_review',
                label: 'Comedy review',
                copy: 'Review the comic idea, character, and timing.'
            }
        ];
        // The rarer, heavier work. Same cards, same skill files behind them.
        const DISCUSS_REPOSITORY_PASSES = [
            {
                id: 'canon_refactor',
                label: 'Trace a canon change',
                copy: 'After a story fact changes, find passages and consequences that may need updating.'
            },
            {
                id: 'scene_continuity',
                label: "Check this scene's continuity",
                copy: 'Check this scene’s dates, facts, and character knowledge against supplied story evidence.'
            }
        ];
        // id -> {label, description} as the skill files currently read.
        var _discussActionCopy = {};
        // How long a finished turn keeps its result on screen before the
        // strip stands down.
        const DISCUSS_TURN_DONE_MS = 6000;
        var _discussStreamText = '';
        var _discussSyncingFrontmatter = null;

        function isDiscussFrontmatterSyncRunning(scenePath) {
            return !!(_discussSyncingFrontmatter && _discussSyncingFrontmatter.path === scenePath);
        }

        function _clearDiscussFrontmatterSync() {
            if (!_discussSyncingFrontmatter) return;
            var syncedPath = _discussSyncingFrontmatter.path;
            _discussSyncingFrontmatter = null;
            if (typeof renderSceneFrontmatter === 'function' && document.documentElement.dataset.view === 'scene'
                && typeof curIdx === 'number' && paths[curIdx] === syncedPath) {
                renderSceneFrontmatter(syncedPath);
            }
        }

        function syncSceneFrontmatterFromDiscuss(trigger, scenePath) {
            if (typeof IS_STATIC_SNAPSHOT !== 'undefined' && IS_STATIC_SNAPSHOT) return;
            if (typeof _pmDirty !== 'undefined' && _pmDirty) {
                if (typeof sidebarShowToast === 'function') {
                    sidebarShowToast('Save or cancel unsaved scene edits before updating frontmatter.', true);
                }
                return;
            }
            var prevTurnId = (_discussSnapshot && _discussSnapshot.last_turn && _discussSnapshot.last_turn.turn_id) || '';
            _discussSyncingFrontmatter = {path: scenePath, prevTurnId: String(prevTurnId), seenActive: false};
            if (typeof renderSceneFrontmatter === 'function') renderSceneFrontmatter(scenePath);
            var panel = document.getElementById('discussPanel');
            var doc = typeof discussDocument === 'function' ? discussDocument() : null;
            if (panel && !panel.hidden && doc && _discussConversationId && _discussDocumentKey === discussDocumentKey(doc)) {
                _showDiscussBody();
                _discussRepositoryAction = null;
                leaveDiscussReviewSetup();
                renderDiscussTaskMode();
                runDiscussScenePass('update_frontmatter');
                var input = document.getElementById('discussInput');
                if (input) input.focus();
                return;
            }
            openDiscuss(trigger, {scenePassActionId: 'update_frontmatter'});
        }
        const DISCUSS_AGENT_KEY = 'proseview-discuss-agent';
        var _discussAgent = _readDiscussAgent();
        var _discussAgentAvailability = {};
        var _discussAgentLocal = {codex: null, claude: null, agy: null};
        var _discussAgentPollTimer = null;

        function _readDiscussAgent() {
            var saved = null;
            try { saved = localStorage.getItem(DISCUSS_AGENT_KEY); } catch (e) {}
            if (DISCUSS_AGENTS.indexOf(saved) >= 0) return saved;
            var fallback = (typeof discussDefaultAgent !== 'undefined') ? discussDefaultAgent : 'codex';
            return DISCUSS_AGENTS.indexOf(fallback) >= 0 ? fallback : 'codex';
        }

        function discussAgentLabel(agent) {
            var id = agent || _discussAgent;
            return DISCUSS_AGENT_LABELS[id] || 'Codex';
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
            resetChatHistoryCursor(_discussAgent);
            resetChatHistoryCursor(agent);
            if (panel && !panel.hidden) {
                saveDiscussDraft();
                _saveDiscussAgentLocal();
                if (typeof _flushBtwDraft === 'function') _flushBtwDraft();
            }
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            if (_discussAgent !== agent) {
                _discussSkillsLoaded = false;
                _discussSkillsLoading = null;
                _discussSkills = [];
                leaveDiscussReviewSetup();
            }
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

        // Drafts belong to the provider's project conversation and follow the
        // currently open document; only an attached selection or action pins
        // a separate document across navigation.
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
            // Review instructions have their own draft. Opening Customize must
            // not turn an unsent chat question into review instructions.
            if (_discussCraftState.active) _discussCraftState.instructions = input.value;
            var draft = _discussCraftState.active ? _discussCraftState.chatDraft : input.value;
            var key = discussDraftKey(null, _discussAgent);
            if (!_discussSelection && !_discussPendingAction
                && !_discussRepositoryAction && !_discussIncludeCurrentDocument) {
                _discussDraftDocument = null;
            }
            try {
                if (draft) sessionStorage.setItem(key, draft);
                else sessionStorage.removeItem(key);
                if (_discussDraftDocument) {
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
                // Selections, pending actions, and repository actions are not
                // persisted across reloads, so plain restored drafts always
                // follow the active document.
                _discussIncludeCurrentDocument = false;
                _discussDraftDocument = null;
                sessionStorage.removeItem(discussIncludeCurrentDocumentKey(agent));
                sessionStorage.removeItem(discussDraftDocumentKey(agent));
                if (!draft && doc) {
                    var legacyKey = legacyDiscussDraftKey(doc, agent);
                    var legacyDraft = sessionStorage.getItem(legacyKey) || '';
                    if (legacyDraft) {
                        draft = legacyDraft;
                        sessionStorage.setItem(key, draft);
                        sessionStorage.removeItem(legacyKey);
                    }
                }
                return draft;
            }
            catch(e) { _discussIncludeCurrentDocument = false; _discussDraftDocument = null; return ''; }
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
                sessionStorage.setItem(discussDraftKey(doc, agent), draft);
                sessionStorage.removeItem(legacyKey);
                input.value = draft;
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
            var doc = options.document || discussDocument() || _discussDockDocument;
            if (!doc) {
                if (trigger && typeof sidebarShowToast === 'function') {
                    sidebarShowToast('Open a scene or supported text file before starting a discussion.', true);
                }
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
            leaveDiscussReviewSetup();
            _discussCraftState.cardsOpen = false;
            _discussRetryOfTaskId = null;
            _discussSelectedSkill = null;
            _discussAutoRun = !!options.runImmediately;
            var requestedScenePass = String(options.scenePassActionId || '');
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
            _discussLastLogSignature = '';
            document.body.classList.add('discuss-open');
            try { sessionStorage.setItem('proseview-panel-open', 'true'); } catch(e) {}
            renderDiscussContext();
            renderDiscussTaskMode();
            setDiscussConnection('Restoring conversation', '');
            var key = discussDocumentKey(doc);
            _discussDocumentKey = key;
            var input = document.getElementById('discussInput');
            resetChatHistoryCursor(_discussAgent);
            _restoreDiscussAgentLocal();
            _discussPreservedDraft = restoreDiscussDraft(doc, _discussAgent);
            input.value = requestedAutoRun ? '' : (options.prefill || _discussPreservedDraft);
            if (requestedSelection || requestedAction) {
                _discussDraftDocument = Object.assign({}, doc);
                // A passage is judged in its scene: the whole file goes along
                // with it unless the writer removes it.
                _discussIncludeCurrentDocument = !!requestedSelection;
            }
            renderDiscussContext();
            var openBody = {kind: doc.kind, path: doc.path, agent: _discussAgent};
            discussApi('/api/discuss/conversations/open', openBody).then(function(data) {
                if (!options.threadId) return data;
                return discussApi('/api/discuss/conversations/' + encodeURIComponent(data.conversation_id) + '/history/' + encodeURIComponent(options.threadId) + '/open', {}).then(function(restored) {
                    if (!restored.ok) throw new Error(restored.error || 'Could not reopen the source conversation');
                    data.snapshot = restored.snapshot; return data;
                });
            }).then(function(data) {
                if (_discussDocumentKey !== key) return;
                _discussConversationId = data.conversation_id;
                _discussSnapshot = data.snapshot;
                renderDiscussSnapshot();
                renderBtwSplit();
                connectDiscussEvents();
                // The composer was rendered after its selection/draft state was
                // restored above. Rebuilding it here detaches an open presets
                // popover while the conversation request finishes.
                document.getElementById('discussSend').disabled = false;
                syncDiscussSendEmpty();
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
                else if (requestedScenePass) {
                    runDiscussScenePass(requestedScenePass);
                    input.focus();
                }
                else if (options.sendInstruction) chooseDiscussInstruction(options.sendInstruction);
                else input.focus();
            }).catch(function(error) {
                _discussOpenFailed = true;
                
                var msg = error.message || '';
                var label = discussAgentLabel();
                if (msg.includes('Codex') || msg.includes('API key') || msg.includes('app-server')
                    || msg.includes('claude-agent-sdk') || msg.includes('Claude Code')
                    || msg.includes('Agy')) {
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
                leaveDiscussReviewSetup();
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
                        resetChatHistoryCursor(_discussAgent);
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
            if (typeof _flushBtwDraft === 'function') _flushBtwDraft();
            closeDiscussContextPicker();
            var panel = document.getElementById('discussPanel');
            panel.hidden = true;
            document.body.classList.remove('discuss-open');
            renderBtwSplit();
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
        // Seven tabs in one dock: scene inspection & beat map (Analysis,
        // History, Beats) first, then AI collaborators (Codex, Claude, Agy, Group).
        const SCENE_PANEL_TABS = ['analysis', 'history', 'beats', 'codex', 'claude', 'agy', 'group'];
        const SCENE_PANEL_TAB_KEY = 'proseview-scene-panel-tab';

        function _readScenePanelTab() {
            var saved = null;
            try { saved = localStorage.getItem(SCENE_PANEL_TAB_KEY); } catch (e) {}
            // "details" and "scene" were retired when frontmatter became interactive
            // directly on the scene; send stored values to Analysis.
            if (saved === 'details' || saved === 'scene') saved = 'analysis';
            if (saved === 'room') saved = 'group';
            // "discuss" was the single agent tab before Codex and Claude got
            // one each. Send those readers to whichever agent they last used
            // rather than dropping them on Analysis.
            if (saved === 'discuss') saved = _discussAgent;
            return SCENE_PANEL_TABS.indexOf(saved) >= 0 ? saved : 'analysis';
        }

        const UTILITY_TAB_IDS = {
            analysis: ['utilityTabAnalysis'],
            history: ['utilityTabHistory'],
            beats: ['utilityTabBeats'],
            codex: ['utilityTabCodex'],
            claude: ['utilityTabClaude'],
            agy: ['utilityTabAgy'],
            group: ['utilityTabGroup']
        };

        function _setUtilityTab(name) {
            SCENE_PANEL_TABS.forEach(function(tab) {
                UTILITY_TAB_IDS[tab].forEach(function(id) {
                    const el = document.getElementById(id);
                    if (!el) return;
                    const on = tab === name;
                    el.classList.toggle('active', on);
                    el.setAttribute('aria-selected', on ? 'true' : 'false');
                    if (on && typeof el.scrollIntoView === 'function') {
                        try { el.scrollIntoView({ block: 'nearest', inline: 'nearest' }); } catch(e) {}
                    }
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
            analysis: {id: 'sceneAnalysisPane', heading: 'Analysis', render: renderSceneAnalysisPane},
            history: {id: 'sceneHistoryPane', heading: 'History', render: function() { if(paths[curIdx]) loadSceneHistory(paths[curIdx]); }},
            beats: {id: 'sceneBeatMapPane', heading: 'Beat Map', render: function() { if (typeof renderSceneBeatMapPane === 'function') renderSceneBeatMapPane(); }},
            group: {id: 'sceneGroupPane', heading: 'Group', render: renderSceneGroupPane}
        };

        // What a scene tab says over the dashboard, where there is no scene.
        const SCENE_PANEL_AWAY = {
            analysis: 'Open a scene to see its analysis.',
            history: 'Open a scene to see its history.',
            beats: 'Open a scene to see its beat map.',
            group: 'Open a scene to run the Group.'
        };

        function _scenePanelAwayEl() {
            let away = document.getElementById('scenePanelAway');
            if (away) return away;
            const first = document.querySelector('#discussPanel .scene-details-pane');
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
            renderBtwSplit();
            if (away) { _showScenePanelAway(name); return; }
            _hideScenePanelAway();
            Object.keys(SCENE_PANEL_PANES).forEach(function(key) {
                const other = document.getElementById(SCENE_PANEL_PANES[key].id);
                if (other) other.hidden = key !== name;
            });
            spec.render();
        }

        function showSceneBeatMapTab() { showScenePanelTab('beats'); }
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
            renderBtwSplit();
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
                    if (DISCUSS_AGENTS.indexOf(tab) >= 0) {
                        var doc = discussDocument() || _discussDockDocument;
                        if (doc) {
                            showDiscussAgentTab(tab);
                        } else {
                            _showScenePanelAway(tab);
                        }
                    } else {
                        showScenePanelTab(tab);
                    }
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

        function _scenePanelEmpty(text) {
            const p = document.createElement('p');
            p.className = 'scene-panel-empty';
            p.textContent = text;
            return p;
        }

        // ── Group: shared chat and preset invitations ────────────
        var _groupSettings = null;
        var _groupSettingsLoading = null;

        function _groupAgentDisplay(agentId) {
            if (!agentId) return '';
            var lower = String(agentId).toLowerCase();
            if (lower === 'claude') return 'Claude';
            if (lower === 'codex') return 'Codex';
            if (lower === 'agy') return 'Agy';
            if (lower === 'gemini') return 'Gemini';
            return lower.charAt(0).toUpperCase() + lower.slice(1);
        }
        window._groupAgentDisplay = _groupAgentDisplay;

        // Seat identifiers stay canonical in the transcript and summary payloads.
        // Each conversation retains a snapshot of its selected profiles.
        function _groupSeatName(seat) {
            var session = _groupSessionsByScene[_groupCurrentScenePath()];
            var participant = ((session && session.participants) || (_groupSettings && _groupSettings.participants) || [])[Number(seat) - 1];
            if (participant) return participant.name;
            var key = Number(seat) === 3 ? 'critic3' : Number(seat) === 2 ? 'critic2' : seat === 'moderator' ? 'moderator' : 'critic1';
            var fallback = {critic1: 'Story Editor', critic2: 'Voice Editor', critic3: 'Continuity Editor', moderator: 'Moderator'};
            return ((_groupSettings && _groupSettings.book) || {})[key + '_name'] || fallback[key];
        }

        function _groupSeatParticipant(seat, session) {
            var s = session || _groupSessionsByScene[_groupCurrentScenePath()];
            var list = (s && s.participants) || (_groupSettings && _groupSettings.participants) || [];
            if (Array.isArray(list)) {
                var byIndex = list[Number(seat) - 1];
                if (byIndex && (Number(byIndex.seat) === Number(seat) || !byIndex.seat)) return byIndex;
                for (var i = 0; i < list.length; i++) {
                    if (Number(list[i].seat) === Number(seat)) return list[i];
                }
            }
            return null;
        }

        function _groupSeatAgent(seat, session) {
            var p = _groupSeatParticipant(seat, session);
            if (p && p.agent) return p.agent;
            var book = (_groupSettings && _groupSettings.book) || {};
            var key = Number(seat) === 3 ? 'critic3_agent' : Number(seat) === 2 ? 'critic2_agent' : Number(seat) === 1 ? 'critic1_agent' : 'moderator_agent';
            return book[key] || (Number(seat) === 3 ? 'agy' : Number(seat) === 2 ? 'claude' : 'codex');
        }

        function _groupSeatLabel(seat, session) {
            var name = _groupSeatName(seat);
            var agent = _groupAgentDisplay(_groupSeatAgent(seat, session));
            if (agent && name.toLowerCase().indexOf(agent.toLowerCase()) < 0) {
                return name + ' (' + agent + ')';
            }
            return name;
        }
        window._groupSeatLabel = _groupSeatLabel;

        function _groupAllAgents(session) {
            var list = (session && session.participants) || (_groupSettings && _groupSettings.participants) || [];
            var seen = [];
            (list.length ? list : [{seat: 1}, {seat: 2}]).forEach(function(p, idx) {
                var label = _groupAgentDisplay(_groupSeatAgent(p.seat || (idx + 1), session));
                if (label && seen.indexOf(label) < 0) seen.push(label);
            });
            return seen.join(', ');
        }
        window._groupAllAgents = _groupAllAgents;
        window._groupBothAgents = _groupAllAgents;

        function _groupAllLabel(session) {
            var list = (session && session.participants) || (_groupSettings && _groupSettings.participants) || [];
            var count = list.length || 2;
            var agents = _groupAllAgents(session);
            var scope = count === 2 ? 'Both' : 'All ' + count;
            return agents ? 'Group (' + scope + ': ' + agents + ')' : 'Group (' + scope + ' editors)';
        }
        window._groupAllLabel = _groupAllLabel;
        window._groupBothLabel = _groupAllLabel;

        function _groupSpeakerName(seat, agent) {
            return _groupSeatName(seat) + ' \u00b7 ' + _groupAgentDisplay(agent);
        }

        function _groupProposerName(value) {
            if (value === 'Critic 1') return _groupSeatName(1);
            if (value === 'Critic 2') return _groupSeatName(2);
            if (value === 'Critic 3') return _groupSeatName(3);
            return value === 'Writer' ? 'Me' : value;
        }
        var _groupSessionsByScene = Object.create(null);
        var _groupActiveSession = null;
        var _groupDraftInput = '';
        var _groupTargetChoice = 'auto';

        function _groupLastCriticSeat(session) {
            if (!session || !session.turns || !session.turns.length) return null;
            var maxSeat = (session.participants && session.participants.length) || 3;
            for (var i = session.turns.length - 1; i >= 0; i--) {
                var turn = session.turns[i];
                if (turn.role === 'critic' && turn.seat >= 1 && turn.seat <= maxSeat) {
                    return turn.seat;
                }
            }
            return null;
        }
        window._groupLastCriticSeat = _groupLastCriticSeat;

        function _groupEffectiveTarget(session) {
            if (_groupTargetChoice && _groupTargetChoice !== 'auto') {
                return _groupTargetChoice === 'both' ? 'all' : _groupTargetChoice;
            }
            var lastSeat = _groupLastCriticSeat(session);
            return lastSeat ? 'critic' + lastSeat : 'all';
        }
        window._groupEffectiveTarget = _groupEffectiveTarget;

        function _groupMentionOptions() {
            var session = _groupSessionsByScene[_groupCurrentScenePath()];
            return (session && session.participants) || (_groupSettings && _groupSettings.participants) || [];
        }

        function _groupProfiles(ids) {
            var library = (_groupSettings || {}).library;
            if (!library) return [];
            var found = (ids || []).map(function(id) { return library.profiles.find(function(profile) { return profile.id === id; }); }).filter(Boolean);
            return _groupSnapshotRoster(found);
        }

        function _groupSnapshotRoster(profiles) {
            var roster = JSON.parse(JSON.stringify(profiles || []));
            var handles = roster.map(function(profile, index) { return profile.name.replace(/[^\p{L}\p{N}_-]/gu, '') || 'Editor' + (index + 1); });
            var counts = Object.create(null);
            handles.forEach(function(h) { var k = h.toLowerCase(); counts[k] = (counts[k] || 0) + 1; });
            handles = handles.map(function(h, index) { return counts[h.toLowerCase()] > 1 ? h + (index + 1) : h; });
            roster.forEach(function(profile, index) {
                profile.seat = index + 1;
                profile.handle = handles[index];
                profile.aliases = [profile.handle, profile.handle + '-' + _groupAgentDisplay(profile.agent), profile.handle + _groupAgentDisplay(profile.agent)];
                if (roster.filter(function(p) { return p.agent === profile.agent; }).length === 1
                        && !handles.some(function(handle) { return handle.toLowerCase() === profile.agent; })) profile.aliases.push(profile.agent);
            });
            return roster;
        }
        var _groupSnapshotPair = _groupSnapshotRoster;

        function _groupEnsureParticipants(session) {
            if ((!session.participants || session.participants.length < 2) && _groupSettings && _groupSettings.library) {
                session.participants = _groupProfiles(_groupSettings.library.default_profiles);
            }
            return session.participants || [];
        }

        function _groupPairPicker(session, container, onChange) {
            var library = (_groupSettings || {}).library;
            if (!library) return;
            var roster = _groupEnsureParticipants(session);
            var locked = !!session.turns.length || session.busy || session.managed || !!(session.outbox && session.outbox.length);

            if (library.profiles.length >= 2) {
                var sizeWrap = elementWith('group-participant-choice group-room-size-choice');
                sizeWrap.appendChild(document.createTextNode('Agents'));
                var sizeRow = elementWith('group-room-size-toggle');
                [2, 3].forEach(function(count) {
                    var btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'group-header-btn group-room-size-btn' + (roster.length === count ? ' is-active' : '');
                    btn.textContent = count + ' agents';
                    btn.setAttribute('aria-pressed', roster.length === count ? 'true' : 'false');
                    btn.disabled = locked || (count === 3 && library.profiles.length < 3);
                    btn.onclick = function() {
                        if (roster.length === count) return;
                        var nextRoster;
                        if (count === 2) {
                            nextRoster = roster.slice(0, 2);
                        } else {
                            var used = new Set(roster.map(function(p) { return p.id; }));
                            var thirdId = (library.default_profiles || []).find(function(id) { return !used.has(id); });
                            var extra = (thirdId && library.profiles.find(function(p) { return p.id === thirdId; }))
                                || library.profiles.find(function(p) { return !used.has(p.id); });
                            if (!extra) return;
                            nextRoster = roster.concat([JSON.parse(JSON.stringify(extra))]);
                        }
                        session.participants = _groupSnapshotRoster(nextRoster);
                        session.participantsChosen = true;
                        if (onChange) onChange(session.participants.map(function(p) { return p.id; }));
                        _groupSaveDraft(session.scene);
                        renderSceneGroupPane();
                    };
                    sizeRow.appendChild(btn);
                });
                sizeWrap.appendChild(sizeRow);
                container.appendChild(sizeWrap);
            }

            roster.forEach(function(profile, index) {
                var label = document.createElement('label');
                label.className = 'group-participant-choice';
                label.appendChild(document.createTextNode('Participant ' + (index + 1)));
                var row = elementWith('group-participant-selects');
                var select = document.createElement('select');
                select.className = 'group-target-select';
                select.setAttribute('aria-label', 'Group participant ' + (index + 1));
                library.profiles.forEach(function(option) {
                    var node = document.createElement('option');
                    node.value = option.id;
                    var existing = roster.find(function(p) { return p.id === option.id; });
                    var shownAgent = existing ? existing.agent : option.agent;
                    node.textContent = option.name + ' · ' + _groupAgentDisplay(shownAgent);
                    select.appendChild(node);
                });
                select.value = profile.id;
                select.disabled = locked;
                select.onchange = function() {
                    var nextRoster = roster.slice();
                    var existingIdx = roster.findIndex(function(p, pi) { return pi !== index && p.id === select.value; });
                    if (existingIdx >= 0) {
                        nextRoster[index] = roster[existingIdx];
                        nextRoster[existingIdx] = roster[index];
                    } else {
                        var chosen = library.profiles.find(function(p) { return p.id === select.value; });
                        if (!chosen) return;
                        nextRoster[index] = JSON.parse(JSON.stringify(chosen));
                    }
                    session.participants = _groupSnapshotRoster(nextRoster);
                    session.participantsChosen = true;
                    var ids = session.participants.map(function(p) { return p.id; });
                    if (onChange) onChange(ids);
                    _groupSaveDraft(session.scene);
                    renderSceneGroupPane();
                };
                var provider = document.createElement('select');
                provider.className = 'group-target-select group-provider-select';
                provider.setAttribute('aria-label', 'Group participant ' + (index + 1) + ' provider');
                DISCUSS_AGENTS.forEach(function(agentId) {
                    var node = document.createElement('option');
                    node.value = agentId;
                    node.textContent = _groupAgentDisplay(agentId);
                    provider.appendChild(node);
                });
                provider.value = profile.agent;
                provider.disabled = locked;
                provider.onchange = function() {
                    var nextRoster = JSON.parse(JSON.stringify(roster));
                    nextRoster[index].agent = provider.value;
                    nextRoster[index].model = '';
                    nextRoster[index].effort = '';
                    session.participants = _groupSnapshotRoster(nextRoster);
                    session.participantsChosen = true;
                    session.providerChosen = true;
                    if (onChange) onChange(session.participants.map(function(p) { return p.id; }));
                    _groupSaveDraft(session.scene);
                    renderSceneGroupPane();
                };
                row.append(select, provider);
                label.appendChild(row);
                container.appendChild(label);
            });
            var swapBtn = document.createElement('button');
            swapBtn.type = 'button';
            swapBtn.id = 'groupSwapAgentsBtn';
            swapBtn.className = 'group-header-btn group-swap-agents-btn';
            swapBtn.textContent = roster.length > 2 ? '\u21c4 Rotate agents' : '\u21c4 Swap agents';
            swapBtn.setAttribute('aria-label', 'Swap participant agents');
            swapBtn.setAttribute('data-tip', roster.length > 2 ? 'Rotate which agent plays each role' : 'Swap which agent plays each role');
            swapBtn.disabled = locked;
            swapBtn.onclick = function() {
                var nextRoster = JSON.parse(JSON.stringify(roster));
                var snapshot = nextRoster.map(function(p) { return {agent: p.agent, model: p.model, effort: p.effort}; });
                for (var i = 0; i < nextRoster.length; i++) {
                    var src = snapshot[(i + 1) % snapshot.length];
                    nextRoster[i].agent = src.agent;
                    nextRoster[i].model = src.model;
                    nextRoster[i].effort = src.effort;
                }
                session.participants = _groupSnapshotRoster(nextRoster);
                session.participantsChosen = true;
                session.providerChosen = true;
                if (onChange) onChange(session.participants.map(function(p) { return p.id; }));
                _groupSaveDraft(session.scene);
                renderSceneGroupPane();
            };
            container.appendChild(swapBtn);
        }

        function _groupHasReview(session) {
            return !!session && session.turns.some(function(turn) { return turn.review_pending; });
        }

        function _groupFinishReview(session, turn) {
            if (session.managed) {
                return groupRuntimeControl(session, 'reviewed', {conversation_id: turn.tool_conversation_id}).then(function() {
                    try { sessionStorage.removeItem('proseview-group-review:' + turn.tool_conversation_id); } catch (error) {}
                }).catch(function() {});
                return;
            }
            turn.review_pending = false;
            _saveGroupSession(session);
            if (!_groupHasReview(session)) {
                session.busy = false;
                session.statusText = '';
                _processGroupQueue(session.scene, _groupRunToken);
            } else renderSceneGroupPane();
        }

        // Review state belongs to the Group turn, independently of the active
        // individual chat. Both surfaces use the same cards and expanded viewer.
        var _groupReviewContexts = new WeakMap();

        function _groupToolReview(session, turn) {
            var box = elementWith('group-tool-review');
            box.appendChild(elementWith('group-open-title', 'Review ' + _groupSpeakerName(turn.seat, turn.agent) + '’s changes'));
            var content = elementWith('group-tool-review-files');
            var notice = elementWith('group-error-text');
            notice.setAttribute('role', 'status');
            box.append(content, notice);
            var review = _groupReviewContexts.get(turn);
            if (!review) {
                review = {conversationId: turn.tool_conversation_id, agentLabel: _groupSpeakerName(turn.seat, turn.agent),
                    mode: 'side-by-side', files: [], unreviewable: [], keep: {}, loaded: false, applying: false, error: ''};
                var savedChoices = {};
                try { savedChoices = JSON.parse(sessionStorage.getItem('proseview-group-review:' + review.conversationId) || '{}'); } catch (error) {}
                review.keep = savedChoices.keep || {};
                review.mode = savedChoices.mode === 'inline' ? 'inline' : 'side-by-side';
                review.save = function() {
                    var fingerprints = Object.assign({}, review.fingerprints || savedChoices.fingerprints || {});
                    review.files.forEach(function(file) {
                        var chosen = review.keep[file.path] || {};
                        if (!Object.keys(chosen).some(function(id) { return chosen[id] === false; })) fingerprints[file.path] = file.fingerprint;
                    });
                    review.fingerprints = fingerprints;
                    try { sessionStorage.setItem('proseview-group-review:' + review.conversationId, JSON.stringify({keep: review.keep, mode: review.mode, fingerprints: fingerprints})); } catch (error) {}
                };
                review.onSettled = function() { return _groupFinishReview(session, turn); };
                _groupReviewContexts.set(turn, review);
                review.refresh = function() {
                    var token = review.loadToken = (review.loadToken || 0) + 1;
                    return discussApi('/api/discuss/conversations/' + encodeURIComponent(review.conversationId) + '/changes', {mode: review.mode, include_text: true})
                        .then(function(data) {
                            if (review.loadToken !== token) return;
                            review.files = data.files || []; review.unreviewable = data.unreviewable || [];
                            review.historyFiles = data.history_files || review.files;
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
                if (typeof groupUpdateAppliedEdits === 'function') groupUpdateAppliedEdits(session);
                if (!box.isConnected) return;
                content.replaceChildren();
                if (!review.loaded) content.textContent = review.error ? '' : 'Loading changes…';
                review.files.forEach(function(file) { content.appendChild(renderDiscussReviewCard(file, review)); });
                review.unreviewable.forEach(function(path) {
                    content.appendChild(elementWith('group-error-text', path + ': the agent changed this without a prior snapshot. Use file history to review it.'));
                });
                if (review.loaded && !review.files.length && !review.unreviewable.length) content.textContent = 'No outstanding changes.';
                notice.textContent = review.error;
                if (focusPath) {
                    var card = Array.from(content.querySelectorAll('[data-review-path]')).find(function(node) { return node.dataset.reviewPath === focusPath; });
                    if (card) card.querySelector('button').focus({preventScroll: true});
                    else document.getElementById('groupInput').focus({preventScroll: true});
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
                if (handle === 'all' || handle === 'everyone') {
                    ranges.push({
                        start: start,
                        end: start + match[1].length + 1,
                        kind: 'agent',
                        isAll: true,
                        participant: {name: 'All editors', handle: handle, agent: 'all', seat: 'all'}
                    });
                    continue;
                }
                var participant = (participants || []).find(function(p) {
                    return p.aliases && p.aliases.some(function(alias) { return alias.toLowerCase() === handle; });
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
                    if (range.participant) {
                        chip.dataset.agent = range.participant.agent;
                        var mentionText = text.slice(range.start, range.end).toLowerCase();
                        if (range.isAll) {
                            var bothAgents = typeof _groupBothAgents === 'function' ? _groupBothAgents() : '';
                            if (bothAgents) chip.dataset.showAgent = bothAgents;
                        } else if (!mentionText.includes(range.participant.agent.toLowerCase())) {
                            chip.dataset.showAgent = _groupAgentDisplay(range.participant.agent);
                        }
                    }
                    chip.textContent = text.slice(range.start, range.end);
                    var bothTitle = typeof _groupBothAgents === 'function' ? _groupBothAgents() : '';
                    chip.title = range.isAll ? (bothTitle ? 'All editors (' + bothTitle + ')' : 'All editors in the group') : (range.participant ? range.participant.name + ' · ' + _groupAgentDisplay(range.participant.agent) : range.path);
                    fragment.appendChild(chip); last = range.end;
                });
                fragment.appendChild(document.createTextNode(text.slice(last)));
                textNode.replaceWith(fragment);
            });
        }

        var CHAT_HISTORY_LIMIT = 100;
        var _chatHistoryState = {
            codex: {index: -1, draft: '', justRecalled: false},
            claude: {index: -1, draft: '', justRecalled: false},
            agy: {index: -1, draft: '', justRecalled: false},
            group: {index: -1, draft: '', justRecalled: false}
        };
        var _chatCaretMirror = null;

        function chatHistoryStorageKey(group) {
            var root = typeof repoRoot !== 'undefined' ? String(repoRoot || '') : '';
            return 'proseview-chat-history:' + root + ':' + group;
        }

        function normalizedChatHistory(rows, limit) {
            if (!Array.isArray(rows)) return [];
            var seen = Object.create(null);
            var out = [];
            for (var i = rows.length - 1; i >= 0; i--) {
                if (typeof rows[i] !== 'string') continue;
                var value = rows[i].trim();
                if (!value || value.length > 32768 || seen[value]) continue;
                seen[value] = true;
                out.push(value);
                if (limit && out.length >= limit) break;
            }
            return out.reverse();
        }

        function _extractAuthoredChatText(text) {
            return String(text || '').split(/\n\nSelected passage(?:\s*\([^)\n]*\))?:\n/)[0].trim();
        }

        function chatConversationUserMessages(group) {
            if (DISCUSS_AGENTS.indexOf(group) >= 0) {
                if (group !== _discussAgent || !_discussSnapshot || !Array.isArray(_discussSnapshot.messages)) return [];
                return _discussSnapshot.messages
                    .filter(function(m) { return m && m.role === 'user'; })
                    .map(function(m) { return _extractAuthoredChatText(m.text); })
                    .filter(Boolean);
            }
            if (group === 'group') {
                var path = typeof _groupCurrentScenePath === 'function' ? _groupCurrentScenePath() : null;
                var session = path && typeof _groupSessionsByScene !== 'undefined' ? (_groupSessionsByScene[path] || _groupActiveSession) : _groupActiveSession;
                if (!session || !Array.isArray(session.turns)) return [];
                return session.turns
                    .filter(function(turn) { return turn && turn.role === 'user'; })
                    .map(function(turn) { return _extractAuthoredChatText(turn.authored || turn.text); })
                    .filter(Boolean);
            }
            return [];
        }

        function getChatMessageHistory(group) {
            var stored = [];
            try {
                stored = normalizedChatHistory(JSON.parse(localStorage.getItem(chatHistoryStorageKey(group)) || '[]'), CHAT_HISTORY_LIMIT);
            } catch (e) {}
            var conv = chatConversationUserMessages(group);
            if (!conv.length) return stored;
            var unseen = conv.filter(function(msg) { return stored.indexOf(msg) < 0; });
            return normalizedChatHistory(unseen.concat(stored), CHAT_HISTORY_LIMIT);
        }

        function resetChatHistoryCursor(group) {
            _chatHistoryState[group] = {index: -1, draft: '', justRecalled: false};
        }

        function recordChatMessageHistory(group, value) {
            value = String(value || '').trim();
            if (!value || value.length > 32768) return;
            var stored = [];
            try {
                stored = normalizedChatHistory(JSON.parse(localStorage.getItem(chatHistoryStorageKey(group)) || '[]'), CHAT_HISTORY_LIMIT);
            } catch (e) {}
            var next = normalizedChatHistory(stored.concat([value]), CHAT_HISTORY_LIMIT);
            try { localStorage.setItem(chatHistoryStorageKey(group), JSON.stringify(next)); } catch (e) {}
            resetChatHistoryCursor(group);
        }

        function _ensureChatCaretMirror() {
            if (_chatCaretMirror) return _chatCaretMirror;
            var el = document.createElement('div');
            el.setAttribute('aria-hidden', 'true');
            el.style.position = 'absolute';
            el.style.top = '0';
            el.style.left = '0';
            el.style.visibility = 'hidden';
            el.style.pointerEvents = 'none';
            el.style.height = 'auto';
            el.style.overflow = 'hidden';
            el.style.whiteSpace = 'pre-wrap';
            el.style.overflowWrap = 'break-word';
            el.style.wordBreak = 'break-word';
            el.style.borderStyle = 'solid';
            el.style.borderWidth = '0';
            el.style.margin = '0';
            _chatCaretMirror = el;
            return el;
        }

        function _setSingleCharRange(range, textNode, text, index) {
            var start = Math.max(0, Math.min(text.length - 1, index));
            var code = text.charCodeAt(start);
            if (code >= 0xDC00 && code <= 0xDFFF && start > 0) start -= 1;
            var next = text.charCodeAt(start);
            var end = (next >= 0xD800 && next <= 0xDBFF && start + 1 < text.length) ? start + 2 : start + 1;
            range.setStart(textNode, start);
            range.setEnd(textNode, end);
        }

        function _isCaretOnTextareaEdgeLine(input, edge) {
            if (!input || input.selectionStart !== input.selectionEnd) return false;
            var value = input.value;
            if (!value) return true;
            var pos = input.selectionStart;
            if (edge === 'first') {
                if (pos === 0) return true;
                if (value.slice(0, pos).indexOf('\n') >= 0) return false;
            } else {
                if (pos === value.length) return true;
                if (value.slice(pos).indexOf('\n') >= 0) return false;
            }
            var parent = input.parentElement;
            if (!parent || !input.clientWidth || typeof document.createRange !== 'function') return true;
            var cs = getComputedStyle(input);
            var mirror = _ensureChatCaretMirror();
            mirror.style.boxSizing = 'border-box';
            mirror.style.width = input.clientWidth + 'px';
            mirror.style.paddingTop = cs.paddingTop;
            mirror.style.paddingRight = cs.paddingRight;
            mirror.style.paddingBottom = cs.paddingBottom;
            mirror.style.paddingLeft = cs.paddingLeft;
            mirror.style.fontFamily = cs.fontFamily;
            mirror.style.fontSize = cs.fontSize;
            mirror.style.fontWeight = cs.fontWeight;
            mirror.style.fontStyle = cs.fontStyle;
            mirror.style.letterSpacing = cs.letterSpacing;
            mirror.style.wordSpacing = cs.wordSpacing;
            mirror.style.lineHeight = cs.lineHeight;
            mirror.style.textIndent = cs.textIndent;
            mirror.style.overflowWrap = cs.overflowWrap;
            mirror.style.wordBreak = cs.wordBreak;
            mirror.style.tabSize = cs.tabSize;
            mirror.textContent = value + ' ';
            parent.appendChild(mirror);
            try {
                var textNode = mirror.firstChild;
                if (!textNode) return true;
                var lineHeight = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) || 14) * 1.4;
                var refStart = edge === 'first' ? 0 : value.length - 1;
                var rRef = document.createRange();
                _setSingleCharRange(rRef, textNode, value, refStart);
                var refRect = rRef.getBoundingClientRect();
                var caretIdx = edge === 'first'
                    ? ((pos < value.length && value.charAt(pos) !== '\n') ? pos : pos - 1)
                    : pos;
                var rCaret = document.createRange();
                _setSingleCharRange(rCaret, textNode, value, caretIdx);
                var caretRect = rCaret.getBoundingClientRect();
                if (!refRect.height || !caretRect.height) return true;
                return Math.abs(caretRect.top - refRect.top) < lineHeight * 0.5;
            } finally {
                if (mirror.parentElement === parent) parent.removeChild(mirror);
            }
        }

        function _applyChatHistoryEntry(input, config, nextValue) {
            config.applyValue(nextValue);
            input.setSelectionRange(nextValue.length, nextValue.length);
            input.scrollTop = input.scrollHeight;
            input.dispatchEvent(new Event('scroll'));
        }

        function handleChatHistoryKeydown(event, input, config) {
            var group = typeof config.group === 'function' ? config.group() : config.group;
            var state = _chatHistoryState[group] || (_chatHistoryState[group] = {index: -1, draft: '', justRecalled: false});
            if (config.isMenuOpen && config.isMenuOpen()) return false;
            if (event.isComposing) return false;
            if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') {
                if (!['Shift', 'Control', 'Alt', 'Meta'].includes(event.key)) state.justRecalled = false;
                return false;
            }
            if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) {
                state.justRecalled = false;
                return false;
            }
            var history = getChatMessageHistory(group);
            if (event.key === 'ArrowUp') {
                if (!history.length) return false;
                if (!state.justRecalled && !_isCaretOnTextareaEdgeLine(input, 'first')) return false;
                if (state.index >= 0 && !state.justRecalled && input.value !== history[state.index]) {
                    state.index = -1;
                    state.draft = '';
                }
                event.preventDefault();
                if (state.index === -1) {
                    state.draft = input.value;
                    state.index = history.length - 1;
                } else if (state.index > 0) {
                    state.index -= 1;
                }
                state.justRecalled = true;
                _applyChatHistoryEntry(input, config, history[state.index]);
                return true;
            }
            if (state.index < 0) return false;
            if (!state.justRecalled && input.value !== history[state.index]) {
                state.index = -1;
                state.draft = '';
                return false;
            }
            if (!state.justRecalled && !_isCaretOnTextareaEdgeLine(input, 'last')) return false;
            event.preventDefault();
            if (state.index < history.length - 1) {
                state.index += 1;
                state.justRecalled = true;
                _applyChatHistoryEntry(input, config, history[state.index]);
            } else {
                var restored = state.draft;
                state.index = -1;
                state.draft = '';
                state.justRecalled = false;
                _applyChatHistoryEntry(input, config, restored);
            }
            return true;
        }

        function wireChatHistoryInput(input, group) {
            if (!input) return;
            input.addEventListener('mousedown', function() {
                var key = typeof group === 'function' ? group() : group;
                if (_chatHistoryState[key]) _chatHistoryState[key].justRecalled = false;
            });
            input.addEventListener('input', function() {
                var key = typeof group === 'function' ? group() : group;
                var state = _chatHistoryState[key];
                if (!state) return;
                state.justRecalled = false;
                if (state.index >= 0) {
                    var history = getChatMessageHistory(key);
                    if (input.value !== (history[state.index] || '')) {
                        state.index = -1;
                        state.draft = '';
                    }
                }
            });
        }

        function chatComposerMentionRanges(input, participants) {
            return chatMentionRanges(input.value, participants).concat(input.id === 'groupInput' ? groupSkillMentionRanges(input.value) : discussSkillRanges(input.value))
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

        function _groupMentionRecipients(text) {
            var seats = [];
            var hasAll = false;
            chatMentionRanges(text, _groupMentionOptions()).forEach(function(range) {
                if (range.isAll) {
                    hasAll = true;
                } else if (range.participant && typeof range.participant.seat === 'number' && !seats.includes(range.participant.seat)) {
                    seats.push(range.participant.seat);
                }
            });
            if (hasAll) {
                var opts = _groupMentionOptions();
                var allSeats = opts.map(function(p) { return p.seat; }).filter(function(s) { return typeof s === 'number'; });
                if (!allSeats.length) allSeats = [1, 2];
                return allSeats.sort();
            }
            return seats;
        }

        function paintGroupMentions(input, mirror) {
            var text = input.value, last = 0;
            mirror.replaceChildren();
            chatMentionRanges(text, _groupMentionOptions()).concat(groupSkillMentionRanges(text)).sort(function(a, b) { return a.start - b.start; }).forEach(function(range) {
                if (range.start < last) return;
                mirror.appendChild(document.createTextNode(text.slice(last, range.start)));
                var mark = document.createElement('mark'); mark.className = 'discuss-mention';
                mark.textContent = text.slice(range.start, range.end); mirror.appendChild(mark); last = range.end;
            });
            mirror.appendChild(document.createTextNode(text.slice(last) + ' '));
            mirror.scrollTop = input.scrollTop; mirror.scrollLeft = input.scrollLeft;
        }

        function _wireGroupMentions(input, menu, target, hint, onHistoryApply) {
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
                var seats = _groupMentionRecipients(input.value);
                var session = _groupSessionFor(_groupCurrentScenePath());
                var effective = _groupEffectiveTarget(session);
                target.value = seats.length > 1 ? 'all' : seats.length ? 'critic' + seats[0] : effective;
                target.disabled = seats.length > 0;
                hint.textContent = seats.length
                    ? 'Replies: ' + seats.map(function(s) { return _groupSeatLabel(s, session); }).join(', ')
                    : '';
            }
            function choose(option) {
                if (!range) return;
                var token = option.kind === 'skill' ? '$' + option.name : '@' + (option.kind === 'editor' ? option.handle : option.path + (option.kind === 'folder' ? '/' : ''));
                var session = _groupSessionFor(_groupCurrentScenePath());
                var effective = typeof _groupEffectiveTarget === 'function' ? _groupEffectiveTarget(session) : _groupTargetChoice;
                if (option.kind === 'skill' && !_groupMentionRecipients(input.value).length && (effective === 'all' || effective === 'both')) token = '@' + option.participant.handle + ' ' + token;
                input.setRangeText(token + ' ', range.start, range.end, 'end');
                close();
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.focus();
            }
            function paint() {
                menu.replaceChildren();
                var group = '';
                choices.forEach(function(option, index) {
                    var category = option.kind === 'skill' ? 'Skills · ' + option.participant.name + ' · ' + _groupAgentDisplay(option.participant.agent) : option.kind === 'editor' ? 'Editors' : 'Files and folders';
                    if (group !== category) {
                        var heading = elementWith('group-mention-group', category);
                        heading.setAttribute('role', 'presentation');
                        menu.appendChild(heading);
                        group = category;
                    }
                    var button = document.createElement('button');
                    button.type = 'button';
                    button.id = 'groupMentionOption-' + index;
                    button.className = 'group-mention-option';
                    button.setAttribute('role', 'option');
                    button.setAttribute('aria-selected', index === active ? 'true' : 'false');
                    var session = _groupSessionFor(_groupCurrentScenePath());
                    var both = typeof _groupBothAgents === 'function' ? _groupBothAgents(session) : '';
                    var labelText = option.kind === 'skill'
                        ? '$' + option.name
                        : option.kind === 'editor'
                            ? (option.isAll ? (both ? 'All editors \u00b7 ' + both : 'All editors') : (option.name + ' \u00b7 ' + _groupAgentDisplay(option.agent)))
                            : option.path;
                    var handleText = option.kind === 'skill'
                        ? (option.description || 'Skill')
                        : option.kind === 'editor'
                            ? (option.isAll ? '@all' : ('@' + option.handle + ((option.aliases || []).includes(option.agent) ? ' \u00b7 @' + _groupAgentDisplay(option.agent) : ' \u00b7 @' + option.handle + '-' + _groupAgentDisplay(option.agent))))
                            : (option.kind === 'folder' ? 'Folder' : 'File');
                    button.append(
                        elementWith('group-mention-name', labelText),
                        elementWith('group-mention-handle', handleText)
                    );
                    button.onpointerdown = function(event) { event.preventDefault(); };
                    button.onclick = function() { choose(option); };
                    menu.appendChild(button);
                });
                menu.hidden = false;
                input.setAttribute('aria-expanded', 'true');
                input.setAttribute('aria-activedescendant', 'groupMentionOption-' + active);
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
                    var participants = _groupMentionOptions().filter(function(profile) { return groupRequestedSeats(input.value).includes(profile.seat); });
                    choices = []; var pending = false;
                    participants.forEach(function(profile) {
                        var skills = _groupSkillCatalogs[profile.agent];
                        if (!skills) {
                            pending = true;
                            groupLoadSkills(profile.agent).then(function() { if (input.isConnected && document.activeElement === input) render(); })
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
                var session = _groupSessionFor(_groupCurrentScenePath());
                var both = _groupBothAgents(session);
                var allOption = {kind: 'editor', name: both ? 'All editors (' + both + ')' : 'All editors', handle: 'all', agent: 'all', isAll: true, aliases: ['all', 'everyone']};
                var editorOptions = [];
                var rawParticipants = _groupMentionOptions();
                rawParticipants.forEach(function(profile) {
                    var seatLabel = _groupSeatLabel(profile.seat, session);
                    var agentDisplay = _groupAgentDisplay(profile.agent);
                    editorOptions.push(Object.assign({}, profile, {
                        kind: 'editor',
                        displayName: seatLabel,
                        handle: profile.handle,
                        secondaryHandle: agentDisplay ? '@' + agentDisplay : ''
                    }));
                });
                editorOptions.push(allOption);
                var editors = editorOptions.filter(function(option) {
                    return [option.name || '', option.displayName || '', option.agent || '', option.handle || ''].concat(option.aliases || []).some(function(value) {
                        return typeof value === 'string' && value.toLowerCase().indexOf(query) >= 0;
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
                if (deleteChatMention(event, input, _groupMentionOptions())) return;
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
                if (handleChatHistoryKeydown(event, input, {
                    group: 'group',
                    isMenuOpen: function() { return !menu.hidden; },
                    applyValue: function(nextValue) {
                        if (onHistoryApply) onHistoryApply(nextValue);
                        else input.value = nextValue;
                        close();
                        updateRecipients();
                    }
                })) return;
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    var groupSendNow = document.getElementById('groupSendNowBtn');
                    if ((event.metaKey || event.ctrlKey) && groupSendNow && !groupSendNow.hidden) {
                        sendGroupComposerMessage({mode: 'now'});
                    } else {
                        sendGroupComposerMessage();
                    }
                }
            };
            wireChatHistoryInput(input, 'group');
            updateRecipients();
            close();
        }
        var _groupApplyAgentChoice = '';
        var _groupRunToken = 0;
        // The active Group follows scene navigation. History is shared across
        // this book; each message freezes its own scene context when sent.
        var _groupHistoryChecked = Object.create(null);
        var _groupHistoryList = Object.create(null);
        var _groupHistoryOpen = false;
        // A passage picked with Ask or Polish, sent with the next message.
        var _groupPendingSelection = '';
        var _groupPendingSelectionScene = '';

        function groupTabIsOpen() {
            var panel = document.getElementById('discussPanel');
            return !!(panel && !panel.hidden && panel.dataset.sceneTab === 'group' && _groupCurrentScenePath());
        }

        function attachSelectionToGroup(selection, instruction) {
            var session = _groupSessionFor(_groupCurrentScenePath());
            if (!session) return;
            // A debate is running: hold the passage and the request for the writer to send.
            if (instruction && session.busy && _groupPendingSelection) return;
            _groupPendingSelection = String(selection || '').trim();
            _groupPendingSelectionScene = _groupCurrentScenePath();
            renderSceneGroupPane();
            var input = document.getElementById('groupInput');
            if (instruction && input) {
                input.value = instruction;
                _groupDraftInput = instruction;
            }
            if (instruction && !session.busy) { sendGroupComposerMessage(); return; }
            renderSceneGroupPane();
            input = document.getElementById('groupInput');
            if (input) input.focus();
        }

        function getSelectionLineRange(text) {
            try {
                if (typeof window !== 'undefined' && window.getSelection) {
                    var sel = window.getSelection();
                    if (sel && sel.rangeCount > 0 && !sel.isCollapsed) {
                        var range = sel.getRangeAt(0);
                        var sNode = range.startContainer;
                        var eNode = range.endContainer;
                        var startEl = (sNode.nodeType === 1 ? sNode : sNode.parentElement);
                        var endEl = (eNode.nodeType === 1 ? eNode : eNode.parentElement);
                        startEl = startEl ? startEl.closest('#sceneProseHost [data-line]') : null;
                        endEl = endEl ? endEl.closest('#sceneProseHost [data-line]') : null;
                        if (startEl && endEl) {
                            var s = parseInt(startEl.getAttribute('data-line'), 10);
                            var e = parseInt(endEl.getAttribute('data-line'), 10);
                            if (s && e) {
                                return s === e ? 'line ' + s : 'lines ' + Math.min(s, e) + '–' + Math.max(s, e);
                            }
                        }
                    }
                }
            } catch (err) {}
            if (text && typeof document !== 'undefined') {
                var blocks = Array.prototype.slice.call(document.querySelectorAll('#sceneProseHost .ProseMirror > [data-line]'));
                if (blocks.length && typeof findBlocksByQuoteText === 'function') {
                    var matched = findBlocksByQuoteText(blocks, text);
                    if (matched.length) {
                        var sLine = parseInt(matched[0].getAttribute('data-line'), 10);
                        var eLine = parseInt(matched[matched.length - 1].getAttribute('data-line'), 10);
                        if (sLine && eLine) {
                            return sLine === eLine ? 'line ' + sLine : 'lines ' + sLine + '–' + eLine;
                        }
                    }
                }
            }
            return '';
        }

        function _groupWithSelection(text) {
            if (!_groupPendingSelection) return text;
            if (/\n\nSelected passage(?:\s*\([^)\n]*\))?:\n/.test(text)) return text;
            var clean = _groupPendingSelection.trim();
            if (!clean) return text;
            var quoted = clean.split('\n').map(function(line) { return '> ' + line; }).join('\n');
            var source = _groupPendingSelectionScene && _groupPendingSelectionScene !== _groupCurrentScenePath()
                ? '> From scene: ' + _groupPendingSelectionScene + '\n' : '';
            var rangeDesc = getSelectionLineRange(clean);
            var header = rangeDesc ? 'Selected passage (' + rangeDesc + '):' : 'Selected passage:';
            return text + '\n\n' + header + '\n' + source + quoted;
        }

        function _groupCurrentScenePath() {
            return (typeof paths !== 'undefined' && typeof curIdx !== 'undefined' && paths[curIdx]) ? paths[curIdx] : null;
        }

        function _groupSessionFor(scenePath) {
            if (!scenePath) return null;
            if (!_groupActiveSession) {
                _groupActiveSession = {
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
            _groupActiveSession.scene = scenePath;
            _groupSessionsByScene[scenePath] = _groupActiveSession;
            return _groupActiveSession;
        }

        function _groupHeaderSummaryText() {
            var session = _groupSessionsByScene[_groupCurrentScenePath()];
            var pair = (session && session.participants) || (_groupSettings && _groupSettings.participants) || [];
            return pair.length ? pair.map(function(p) { return p.name + ' · ' + _groupAgentDisplay(p.agent); }).join(' ↔ ') : 'Group';
        }

        function syncGroupSettingsState(settings) {
            if (settings) {
                _groupSettings = settings;
                Object.keys(_groupSessionsByScene).forEach(function(path) {
                    var session = _groupSessionsByScene[path];
                    if (!session.managed && !session.turns.length && !session.pendingPreset && !session.busy) {
                        var selected = session.participantsChosen && session.participants && session.participants.map(function(p) { return p.id; });
                        var available = selected && selected.every(function(id) { return settings.library.profiles.some(function(p) { return p.id === id; }); });
                        session.participants = _groupProfiles(available ? selected : settings.library.default_profiles);
                        session.providerChosen = false;
                    }
                });
            }
            var summaryEl = document.getElementById('groupHeaderSummary');
            if (summaryEl) summaryEl.textContent = _groupHeaderSummaryText();
            var pane = document.getElementById('sceneGroupPane');
            if (pane && !pane.hidden) renderSceneGroupPane();
        }

        function _ensureGroupSettingsLoaded() {
            if (_groupSettings) return Promise.resolve(_groupSettings);
            if (_groupSettingsLoading) return _groupSettingsLoading;
            _groupSettingsLoading = (typeof loadGroupSettings === 'function' ? loadGroupSettings() :
                fetch('/api/discuss/group-settings', {method: 'POST', headers: pvHeaders(), body: '{}'})
                    .then(function(r) { return r.json(); }).then(function(data) { return data.settings; }))
                .then(function(settings) {
                    if (!settings) throw new Error('Could not load Group profiles and presets. Reopen the Group to retry.');
                    _groupSettings = settings;
                    return settings;
                }).finally(function() { _groupSettingsLoading = null; });
            return _groupSettingsLoading;
        }

        function resetGroupSession() {
            var path = _groupCurrentScenePath();
            if (!path) return;
            _groupRunToken++;
            _groupDraftInput = ''; _groupPendingSelection = ''; _groupPendingSelectionScene = ''; _groupTargetChoice = 'auto';
            var input = document.getElementById('groupInput'); if (input) input.value = '';
            resetChatHistoryCursor('group');
            try { sessionStorage.removeItem(groupDraftKey(path)); } catch (error) {}
            Object.keys(_groupSessionsByScene).forEach(function(key) { if (_groupSessionsByScene[key] === _groupActiveSession) delete _groupSessionsByScene[key]; });
            _groupActiveSession = null;
            _groupHistoryChecked.book = true;
            _groupHistoryOpen = false;
            renderSceneGroupPane();
        }

        function _groupNewId() {
            return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
        }

        function _groupHistoryRequest(payload) {
            return fetch('/api/discuss/group-history', {
                method: 'POST',
                headers: pvHeaders(),
                body: JSON.stringify(payload)
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (!data || !data.ok) throw new Error((data && data.error) || 'Could not access Group history');
                return data;
            });
        }

        // A debate keeps every plan the moderator wrote, each placed in the
        // thread after the turns it sums up; the newest one is live.
        function _groupPlanItem(item, idx) {
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

        function _groupLatestPlan(session) {
            return (session && session.plans && session.plans.length) ? session.plans[session.plans.length - 1] : null;
        }

        function _saveGroupSession(session) {
            if (session && session.managed) { saveManagedGroup(session); return; }
            if (!session || !session.turns.length) return;
            if (!session.id) session.id = _groupNewId();
            // One save at a time per debate, the last one carrying the latest
            // state, so an older save can never land after a newer one.
            if (session._saving) { session._saveAgain = true; return; }
            session._saving = true;
            _groupHistoryRequest({
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
                delete _groupHistoryList.book;
            }).catch(function(error) {
                session.error = 'Could not save this Group: ' + error.message;
                if (!session.busy && session.scene === _groupCurrentScenePath()) renderSceneGroupPane();
            }).then(function() {
                session._saving = false;
                if (session._saveAgain) {
                    session._saveAgain = false;
                    _saveGroupSession(session);
                }
            });
        }

        function _loadGroupHistoryList(scenePath) {
            if (_groupHistoryList.book) return Promise.resolve(_groupHistoryList.book);
            return _groupHistoryRequest({action: 'list'}).then(function(data) {
                var rows = (data && data.ok && Array.isArray(data.sessions)) ? data.sessions : [];
                _groupHistoryList.book = rows;
                return rows;
            }).catch(function() { return []; });
        }

        function openGroupHistorySession(scenePath, sessionId) {
            return _ensureGroupSettingsLoaded().then(function() {
                return _groupHistoryRequest({action: 'get', id: sessionId});
            }).then(function(data) {
                if (!data || !data.ok || !data.session) return;
                var saved = data.session;
                var current = _groupSessionsByScene[scenePath];
                if (current && current.busy) return;
                var session = _groupSessionFor(_groupCurrentScenePath() || scenePath);
                session.id = saved.id;
                session.originScene = saved.scene;
                session.createdAt = saved.created_at || 0;
                session.presetId = saved.preset_id || '';
                session.topicLabel = saved.title || '';
                session.topicBadge = saved.badge || '';
                session.source = saved.source || null;
                session.handoffWarnings = saved.handoff_warnings || [];
                session.summaryMissing = !!saved.summary_missing;
                session.question = saved.question || '';
                session.turns = saved.turns || [];
                session.participants = saved.participants || null;
                if (!session.participants && _groupSettings && _groupSettings.library) {
                    // Older debates used book-specific seat names and prompts.
                    var book = _groupSettings.book || {};
                    var app = _groupSettings.app || {};
                    var snapshots = [1, 2].map(function(seat) {
                        var previous = session.turns.find(function(t) { return t.role === 'critic' && t.seat === seat; });
                        var recordedName = previous && String(previous.label || '').replace(/\s*·\s*(?:Codex|Claude|Agy).*$/, '').trim();
                        if (/^Critic\s*[12]$/i.test(recordedName || '')) recordedName = '';
                        var config = app['critic' + seat] || {};
                        var agent = previous ? previous.agent : config.agent || (seat === 1 ? 'codex' : 'claude');
                        return {id: 'legacy-' + seat, name: recordedName || book['critic' + seat + '_name'] || (seat === 1 ? 'Story Editor' : 'Voice Editor'),
                            specialty: book['critic' + seat + '_prompt'] || '', style: '',
                            agent: agent, model: config.agent === agent ? config.model || '' : '', effort: config.agent === agent ? config.effort || '' : ''};
                    });
                    session.participants = _groupSnapshotPair(snapshots);
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
                        items: (plan.items || []).map(_groupPlanItem),
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
                _groupHistoryOpen = false;
                return attachManagedGroup(session).then(function() { if (session.scene === _groupCurrentScenePath()) renderSceneGroupPane(); });
            }).catch(function(error) { var session = _groupSessionFor(scenePath); session.error = error.message; if (scenePath === _groupCurrentScenePath()) renderSceneGroupPane(); });
        }

        function deleteGroupHistorySession(scenePath, sessionId) {
            _groupHistoryRequest({action: 'delete', id: sessionId}).then(function() {
                delete _groupHistoryList.book;
                var session = _groupSessionsByScene[scenePath];
                if (session && session.id === sessionId && !session.busy) {
                    Object.keys(_groupSessionsByScene).forEach(function(key) { if (_groupSessionsByScene[key] === session) delete _groupSessionsByScene[key]; });
                    _groupActiveSession = null;
                }
                renderSceneGroupPane();
            }).catch(function() {});
        }

        function _restoreLatestGroupSession(scenePath) {
            if (_groupHistoryChecked.book) return;
            _groupHistoryChecked.book = true;
            var pending = _groupSessionsByScene[scenePath];
            if (pending && (pending.outbox || []).length) {
                var request = pending.outbox[0];
                groupRuntimeRequest(pending, {action: 'state', group_id: request.group_id, initial: request.initial})
                    .then(function() { drainGroupOutbox(pending); })
                    .catch(function(error) { pending.sendError = error.message; renderSceneGroupPane(); });
                return;
            }
            var draftAtStart = _groupDraftInput;
            _loadGroupHistoryList(scenePath).then(function(rows) {
                var session = _groupSessionsByScene[scenePath];
                if (_groupActiveSession !== pending || !rows.length || (session && (session.turns.length || session.busy)) || _groupDraftInput !== draftAtStart) return;
                var selected = session && rows.find(function(row) { return row.id === session.id; });
                openGroupHistorySession(_groupCurrentScenePath(), (selected || rows[0]).id);
            });
        }

        function _formatGroupWhen(seconds) {
            if (!seconds) return '';
            var d = new Date(seconds * 1000);
            var today = new Date();
            if (d.toDateString() === today.toDateString()) {
                return d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
            }
            return d.toLocaleDateString([], {month: 'short', day: 'numeric'});
        }

        function _formatMessageTime(seconds) {
            if (!seconds) return '';
            var d = new Date(seconds > 1e11 ? seconds : seconds * 1000);
            if (isNaN(d.getTime())) return '';
            return d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
        }

        function _formatMessageDuration(ms) {
            if (!ms || ms < 0) return '';
            if (ms < 1000) return (ms / 1000).toFixed(1) + 's';
            if (ms < 60000) {
                var s = ms / 1000;
                return (s < 10 ? s.toFixed(1) : Math.round(s)) + 's';
            }
            var totalSec = Math.round(ms / 1000);
            var mins = Math.floor(totalSec / 60);
            var rem = totalSec % 60;
            return mins + 'm ' + (rem ? rem + 's' : '');
        }

        function _buildMessageMeta(createdAt, durationMs) {
            var timeStr = _formatMessageTime(createdAt);
            var durStr = _formatMessageDuration(durationMs);
            if (!timeStr && !durStr) return null;
            var meta = elementWith('chat-message-meta');
            if (timeStr) {
                var timeEl = elementWith('chat-message-time', timeStr);
                timeEl.title = 'Sent at ' + timeStr;
                meta.appendChild(timeEl);
            }
            if (durStr) {
                if (timeStr) meta.appendChild(elementWith('chat-message-meta-sep', '\u00b7'));
                var durEl = elementWith('chat-message-duration', durStr);
                durEl.title = 'Responded in ' + (durationMs >= 1000 ? (durationMs / 1000).toFixed(1) + 's' : durationMs + 'ms');
                meta.appendChild(durEl);
            }
            return meta;
        }

        function _renderGroupHistoryMenu(body, scenePath, session) {
            var menu = elementWith('group-history-menu');
            menu.appendChild(elementWith('group-history-head', 'Group conversations in this book'));
            var list = elementWith('group-history-list');
            list.appendChild(elementWith('group-history-empty', 'Loading\u2026'));
            menu.appendChild(list);
            body.appendChild(menu);
            _loadGroupHistoryList(scenePath).then(function(rows) {
                list.replaceChildren();
                if (!rows.length) {
                    list.appendChild(elementWith('group-history-empty', 'No saved debates yet.'));
                    return;
                }
                rows.forEach(function(row) {
                    var item = elementWith('group-history-item' + (row.id === session.id ? ' is-current' : ''));
                    var open = document.createElement('button');
                    open.type = 'button';
                    open.className = 'group-history-open';
                    open.append(
                        elementWith('group-history-title', row.title || 'Group'),
                        elementWith('group-history-meta', (row.scene ? row.scene + ' · ' : '') + row.turns + (row.turns === 1 ? ' reply' : ' replies')
                            + (row.has_plan ? ' \u00b7 plan' : '') + ' \u00b7 ' + _formatGroupWhen(row.updated_at))
                    );
                    open.disabled = !!session.busy;
                    open.onclick = function() { openGroupHistorySession(scenePath, row.id); };
                    var del = document.createElement('button');
                    del.type = 'button';
                    del.className = 'group-history-delete';
                    del.textContent = '\u00d7';
                    del.setAttribute('aria-label', 'Delete this debate');
                    del.setAttribute('data-tip', 'Delete this debate');
                    del.onclick = function() { deleteGroupHistorySession(scenePath, row.id); };
                    item.append(open, del);
                    list.appendChild(item);
                });
            });
        }

        function stopGroupDebate() {
            var session = _groupSessionFor(_groupCurrentScenePath());
            if (session && session.managed) groupRuntimeControl(session, 'stop').catch(function() {});
        }

        function _groupAdaptPresetForRoster(preset, roster) {
            var copy = JSON.parse(JSON.stringify(preset));
            var originalCount = (preset.profiles && preset.profiles.length) || 2;
            var count = (roster && roster.length) || 2;
            copy.profiles = (roster || []).map(function(p) { return p.id; });
            if (count === 2) {
                var kept = (copy.invitations || []).filter(function(step) { return step.seat === 1 || step.seat === 2; });
                copy.invitations = kept.length >= 2
                    ? kept
                    : (copy.invitations || []).map(function(step) { return Object.assign({}, step, {seat: step.seat > 2 ? 2 : step.seat}); });
                if (copy.recap > 2) copy.recap = 2;
            } else if (count === 3 && originalCount < 3) {
                var hasSeat3 = (copy.invitations || []).some(function(step) { return step.seat === 3; });
                if (!hasSeat3 && (copy.invitations || []).length < 12) {
                    var at = (copy.id === 'second_opinion' && (copy.invitations || []).length === 2 && copy.invitations[0].seat === 2)
                        ? 1
                        : Math.min(2, (copy.invitations || []).length);
                    copy.invitations.splice(at, 0, {
                        seat: 3,
                        prompt: 'Audit the discussion and proposed edits from your own lens (continuity, scene logic, and concrete detail): '
                            + 'challenge weak assumptions, flag at most 1 crucial missed issue with italic/plain blockquotes, or pass.'
                    });
                }
            }
            return copy;
        }

        function startGroupDebate(options) {
            options = options || {};
            var path = _groupCurrentScenePath();
            if (!path) return;
            var session = _groupSessionFor(path);
            if (session.busy) return;
            var library = (_groupSettings || {}).library;
            if (!library) return;
            if (!options.start) {
                var preset = library.presets.find(function(p) { return p.id === options.presetId; });
                if (!preset) return;
                if (preset.kind === 'workflow') { session.pendingPreset = JSON.parse(JSON.stringify(preset)); openCurrentGroupWorkflow(session, preset); return; }
                var presetUsesDefaultRoster = JSON.stringify(preset.profiles) === JSON.stringify(library.default_profiles);
                if (!session.participantsChosen && !presetUsesDefaultRoster) {
                    session.participants = _groupProfiles(preset.profiles);
                } else {
                    _groupEnsureParticipants(session);
                }
                session.pendingPreset = _groupAdaptPresetForRoster(preset, session.participants);
                renderSceneGroupPane();
                return;
            }
            startManagedGroupPreset(session);
        }

        function _processGroupQueue(scenePath) {
            var session = _groupSessionFor(scenePath);
            if (session && session.managed) groupRuntimePoll(session);
        }

        // What the critic is doing while its turn runs, as the single chat
        // shows it: elapsed time, its progress notes and steps, and its reply
        // as it streams. Updated in place so the pane does not re-render.
        function _pollGroupProgress(session, runId, token) {
            var stopped = false;
            var timer = null;
            function tick() {
                if (stopped || _groupRunToken !== token) return;
                fetch('/api/discuss/group-progress', {
                    method: 'POST',
                    headers: pvHeaders(),
                    body: JSON.stringify({run_id: runId})
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (stopped || _groupRunToken !== token || !session.live) return;
                    if (data && data.ok && data.running) {
                        session.live.elapsed = data.elapsed || 0;
                        session.live.progress = data.progress || '';
                        session.live.steps = Array.isArray(data.steps) ? data.steps : [];
                        session.live.draft = data.draft || '';
                        session.live.conversationId = data.conversation_id || '';
                        session.live.approvals = data.approvals || [];
                        _renderGroupLive();
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

        function _discussCurrentScenePath() {
            if (typeof _discussSnapshot !== 'undefined' && _discussSnapshot && _discussSnapshot.document && _discussSnapshot.document.kind === 'scene' && _discussSnapshot.document.path) {
                return _discussSnapshot.document.path;
            }
            if (typeof paths !== 'undefined' && typeof curIdx !== 'undefined' && curIdx >= 0 && paths[curIdx]) {
                return paths[curIdx];
            }
            return '';
        }

        // Critics cite "line 54" as plain text; this links it to the scene, the
        // way a Codex answer links its own citations, whichever agent wrote it.
        function _groupLinkLines(text, scenePath) {
            scenePath = scenePath || _discussCurrentScenePath();
            var activeSource = '';
            var namedSources = new Set();
            var namedTargets = [];
            (String(text || '').match(/[^\s`<>()\[\]#]+\.md/g) || []).forEach(function(source) {
                var target = resolveProsviewFileReference(source);
                var key = target ? target.kind + ':' + target.path : source;
                if (target && !namedSources.has(key)) namedTargets.push(target);
                namedSources.add(key);
            });
            var abs = String(((typeof meta !== 'undefined' && meta[scenePath]) || {}).abs_path || '');
            var docRef = abs ? ('<' + abs + ':') : (scenePath ? ('<' + scenePath + '#L') : '');
            function link(all, source, start, end) {
                var rangeSuffix = end ? ('-' + end) : '';
                if (source) {
                    // A named source must never fall back to the open scene.
                    activeSource = source;
                    var target = resolveProsviewFileReference(source);
                    if (!target) return all;
                    return '[' + all + '](<' + source + '#L' + start + rangeSuffix + '>)';
                }
                if (activeSource) return link(all, activeSource, start, end);
                if (namedSources.size) return all;
                return docRef ? '[' + all + '](' + docRef + start + rangeSuffix + '>)' : all;
            }
            var parts = String(text || '').split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|\[[^\]]*\]\([^)]*\)|`[^`]*`)/);
            return parts.map(function(part, idx) {
                if (idx % 2 === 1) {
                    var citation = part.match(/^`([^`\n]+\.md)\s*[·,:]\s*lines?\s+(\d+)(?:\s*(?:[\u2013\u2014-]|to)\s*(\d+))?`$/i);
                    var namedLink = part.match(/\]\(<?([^#\n]+?\.md)(?:#|:\d|>?\))/);
                    if (namedLink) activeSource = namedLink[1];
                    return citation ? link(part.slice(1, -1), citation[1], citation[2], citation[3]) : part;
                }
                var precedingPath = idx > 0 && parts[idx - 1].match(/^`([^`\n]+\.md)`$/);
                return part.split(/(\n)/).map(function(line, lineIndex) {
                    if (/^\s*#{1,6}\s/.test(line)) activeSource = '';
                    return line.replace(/(?:([^\s`<>\[\]()]+\.md)\s*[·,:]\s*)?\b(lines?)\s+(\d+)(?:\s*(?:[\u2013\u2014-]|to)\s*(\d+))?\b/gi, function(all, source, word, start, end, offset) {
                        if (!source && precedingPath && lineIndex === 0 && /^\s*[·,:]\s*$/.test(line.slice(0, offset))) source = precedingPath[1];
                        if (!source) {
                            var naturalSource = line.slice(0, offset).match(/\b(?:in|from)\s+(?:the\s+)?([^,\n]+),\s*$/i);
                            if (naturalSource) {
                                var name = naturalSource[1].trim().toLowerCase();
                                var matches = namedTargets.filter(function(target) {
                                    return target.path.split('/').pop().replace(/^\d+[-_]/, '').replace(/\.md$/i, '').replace(/[-_]/g, ' ').toLowerCase() === name;
                                });
                                if (matches.length !== 1) return all;
                                source = matches[0].path;
                            }
                        }
                        return link(all, source, start, end);
                    });
                }).join('');
            }).join('');
        }

        function _formatGroupElapsed(seconds) {
            var s = Math.max(0, Math.floor(seconds || 0));
            return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
        }

        function _renderGroupLive() {
            var session = _groupSessionFor(_groupCurrentScenePath());
            var live = session && session.live;
            var textEl = document.getElementById('groupLiveStatusText');
            var box = document.getElementById('groupLiveProgress');
            if (!live || !textEl || !box) return;
            var body = document.getElementById('groupBody');
            var wasAtBottom = body && (body.scrollHeight - body.scrollTop - body.clientHeight < 48);
            textEl.textContent = (session.statusText || 'Thinking\u2026')
                + (live.elapsed ? ' \u00b7 ' + _formatGroupElapsed(live.elapsed) : '');
            box.textContent = '';
            if (live.steps.length) {
                var steps = elementWith('group-live-steps');
                live.steps.forEach(function(step) {
                    // Codex wraps every command in a login shell; the command is the step.
                    var shown = String(step).replace(/^\/bin\/(?:ba|z)?sh -lc\s+/, '').replace(/^(['"])([\s\S]*)\1$/, '$2');
                    steps.appendChild(elementWith('group-live-step', shown));
                });
                box.appendChild(steps);
            }
            var quietPass = live.draft && '[GROUP_PASS]'.startsWith(live.draft.trim().toUpperCase());
            if (live.draft && !quietPass) {
                var draft = elementWith('group-live-draft group-turn-body discuss-message assistant');
                var active = session.runtime && session.runtime.steps.find(function(step) { return step.id === session.runtime.active_step; });
                renderDiscussMarkdown(draft, _groupLinkLines(groupVisibleReply(live.draft, true), active && active.scene || session.originScene || session.scene));
                box.appendChild(draft);
            } else if (live.progress) {
                var note = live.progress.length > 400 ? '\u2026' + live.progress.slice(-400) : live.progress;
                // Summary headings that arrived without a break between them.
                note = note.replace(/\*\*\*\*/g, '**\n\n**');
                var noteEl = elementWith('group-live-note group-turn-body');
                renderDiscussMarkdown(noteEl, note);
                box.appendChild(noteEl);
            }
            box.hidden = !box.childNodes.length;
            if (body && wasAtBottom) {
                body.scrollTop = body.scrollHeight;
                groupRememberScroll(body);
            }
            var approvals = document.getElementById('groupLiveApprovals');
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
                                .then(function() { live.approvals = []; _renderGroupLive(); })
                                .catch(function(error) { button.disabled = false; approvals.appendChild(elementWith('group-error-text', error.message)); });
                        }));
                    });
                }
            }
        }

        function runGroupPlusOneTurn() {
            var session = _groupSessionFor(_groupCurrentScenePath());
            if (!session || session.busy) return;
            var last = session.turns.filter(function(turn) { return turn.role === 'critic'; }).slice(-1)[0];
            var count = (session.participants && session.participants.length) || 2;
            var seat = last && last.seat ? ((last.seat % count) + 1) : 1;
            groupFollowLatest(session);
            groupRuntimeControl(session, 'submit', {message_id: _groupNewId(), text: '@' + session.participants[seat - 1].handle + ' continue the discussion.', seats: [seat]}).catch(function() {});
        }

        function sendGroupComposerMessage(options) { return submitGroupComposerMessage(options); }

        function insertGroupPlanTodo(item) {
            var path = _groupCurrentScenePath();
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
                    _saveGroupSession(_groupSessionFor(path));
                    renderSceneGroupPane();
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
                    _saveGroupSession(_groupSessionFor(path));
                    renderSceneGroupPane();
                    if (typeof sidebarShowToast === 'function') sidebarShowToast('Added TODO to scene');
                }
            }).catch(function() {});
        }

        function applyGroupPlanWithAgent(agent, plan) {
            var path = _groupCurrentScenePath();
            var session = _groupSessionFor(path);
            plan = plan || _groupLatestPlan(session);
            if (!session || !plan) return;
            var ticked = plan.items.filter(function(item) { return item.checked && !item.applied; });
            if (!ticked.length) return;
            var targetAgent = DISCUSS_AGENTS.indexOf(agent) >= 0 ? agent : 'claude';
            ticked.forEach(function(item) {
                item.applied = _groupAgentDisplay(targetAgent);
                item.checked = false;
            });
            _saveGroupSession(session);
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
            var instruction = 'Please revise this scene to apply the following Group revision plan:\n' + lines.join('\n');

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

        function _renderGroupPresetPreview(session, container) {
            var preset = session.pendingPreset;
            var preview = elementWith('group-preset-preview');
            preview.id = 'groupPresetPreview';
            var title = document.createElement('strong'); title.textContent = preset.name; preview.appendChild(title);
            if (preset.description) { var description = document.createElement('p'); description.textContent = preset.description; preview.appendChild(description); }
            var countLabel = document.createElement('label');
            countLabel.textContent = 'Invitations ';
            var count = document.createElement('select');
            count.className = 'group-target-select';
            count.setAttribute('aria-label', 'Preset invitations');
            for (var n = 2; n <= 12; n++) {
                var option = document.createElement('option'); option.value = String(n); option.textContent = String(n); count.appendChild(option);
            }
            count.value = String(preset.invitations.length);
            count.onchange = function() { _rmResizeInvitations(preset, Number(count.value)); renderSceneGroupPane(); };
            countLabel.appendChild(count); preview.appendChild(countLabel);
            var list = document.createElement('ol');
            preset.invitations.forEach(function(step) {
                var item = document.createElement('li');
                item.textContent = '@' + session.participants[step.seat - 1].handle + ', ' + step.prompt;
                list.appendChild(item);
            });
            preview.appendChild(list);
            var recapLabel = document.createElement('label'); recapLabel.textContent = 'Optional recap ';
            var recap = document.createElement('select'); recap.className = 'group-target-select'; recap.setAttribute('aria-label', 'Preset recap');
            [{value: 0, name: 'No recap'}].concat(session.participants.map(function(p) { return {value: p.seat, name: p.name + ' · ' + _groupAgentDisplay(p.agent)}; })).forEach(function(p) {
                var option = document.createElement('option'); option.value = String(p.value); option.textContent = p.name; recap.appendChild(option);
            });
            recap.value = String(preset.recap); recap.onchange = function() { preset.recap = Number(recap.value); };
            recapLabel.appendChild(recap); preview.appendChild(recapLabel);
            preview.appendChild(createGroupPositionsOption(preset, function(checked) {
                preset.positions_table = checked; groupSetPositions(preset.id, checked);
            }));
            var actions = elementWith('group-preset-actions');
            if (session.presetError) { var error = elementWith('group-error-text', session.presetError); error.setAttribute('role', 'alert'); preview.appendChild(error); }
            var start = document.createElement('button'); start.type = 'button'; start.id = 'groupStartPresetBtn'; start.className = 'group-send-btn'; start.textContent = 'Start discussion';
            start.disabled = !!session.startingPreset;
            if (session.startingPreset) start.textContent = 'Checking agents…';
            start.onclick = function() { startGroupDebate({start: true}); };
            var cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'group-header-btn'; cancel.textContent = 'Cancel';
            cancel.onclick = function() { session.pendingPreset = null; renderSceneGroupPane(); };
            actions.append(start, cancel); preview.appendChild(actions); container.appendChild(preview);
        }

        function renderSceneGroupPane() {
            const pane = document.getElementById('sceneGroupPane');
            if (!pane) return;
            const path = _groupCurrentScenePath();
            if (!path) {
                pane.replaceChildren(_scenePanelEmpty('Open a scene to run the Group.'));
                return;
            }
            if (!_groupSettings) {
                pane.replaceChildren(_scenePanelEmpty('Loading Group profiles…'));
                _ensureGroupSettingsLoaded().then(function() {
                    if (!pane.querySelector('#groupInput')) renderSceneGroupPane();
                }).catch(function(error) { pane.replaceChildren(_scenePanelEmpty(error.message)); });
                return;
            }

            var prevInput = document.getElementById('groupInput');
            var inputFocus = prevInput && document.activeElement === prevInput ? {start: prevInput.selectionStart, end: prevInput.selectionEnd} : null;
            if (prevInput) { _groupDraftInput = prevInput.value; _groupSaveDraft(_groupDraftScene); }
            _groupLoadDraft(path);

            var oldBody = document.getElementById('groupBody');
            groupRememberScroll(oldBody);
            if (oldBody && oldBody._groupDisconnectScroll) oldBody._groupDisconnectScroll();
            pane.replaceChildren();
            var session = _groupSessionFor(path);
            _restoreLatestGroupSession(path);
            _groupEnsureParticipants(session);

            // 1. Header strip
            var header = elementWith('group-header-strip');
            var summary = elementWith('group-header-summary', _groupHeaderSummaryText());
            summary.id = 'groupHeaderSummary';
            var actions = elementWith('group-header-actions');
            if (session.turns.length > 0 || session.busy || session.error || session.managed) {
                var resetBtn = document.createElement('button');
                resetBtn.type = 'button';
                resetBtn.id = 'groupResetBtn';
                resetBtn.className = 'group-header-btn';
                resetBtn.textContent = '\u21ba New';
                resetBtn.setAttribute('data-tip', 'Clear this group session and return to the starter cards');
                resetBtn.onclick = resetGroupSession;
                resetBtn.disabled = session.busy;
                actions.appendChild(resetBtn);
            }
            var historyBtn = document.createElement('button');
            historyBtn.type = 'button';
            historyBtn.id = 'groupHistoryBtn';
            historyBtn.className = 'group-header-btn' + (_groupHistoryOpen ? ' is-active' : '');
            historyBtn.textContent = 'History';
            historyBtn.setAttribute('aria-expanded', _groupHistoryOpen ? 'true' : 'false');
            historyBtn.setAttribute('data-tip', 'Open a previous Group debate on this scene');
            historyBtn.onclick = function() {
                _groupHistoryOpen = !_groupHistoryOpen;
                renderSceneGroupPane();
            };
            actions.appendChild(historyBtn);
            if (session.source) {
                var sourceBtn = document.createElement('button'); sourceBtn.type = 'button'; sourceBtn.className = 'group-header-btn'; sourceBtn.textContent = 'Source chat ↗';
                sourceBtn.onclick = function() { openGroupForkSource(session.source); }; actions.appendChild(sourceBtn);
            }
            var gearBtn = document.createElement('button');
            gearBtn.type = 'button';
            gearBtn.id = 'groupSettingsBtn';
            gearBtn.className = 'group-header-btn';
            gearBtn.textContent = '\u2699 Settings';
            gearBtn.setAttribute('data-tip', 'Choose reusable profiles and discussion presets in Settings → Group');
            gearBtn.onclick = function() {
                if (typeof openGroupSettings === 'function') openGroupSettings();
            };
            actions.appendChild(gearBtn);
            header.append(summary, actions);
            pane.appendChild(header);

            // 2. Scrollable body
            var body = elementWith('group-body');
            body.id = 'groupBody';
            if (_groupHistoryOpen) _renderGroupHistoryMenu(body, path, session);
            if (session.runtime && session.runtime.summary_missing || session.summaryMissing) {
                var missingSummary = (session.runtime && session.runtime.handoff_warnings || session.handoffWarnings || []).find(function(w) { return w.indexOf('Summary missing.') === 0; });
                var missingNotice = elementWith('group-runtime-notice group-summary-missing', missingSummary || 'Summary missing. This Group received recent exchanges and the current scene only.');
                missingNotice.setAttribute('role', 'status'); body.appendChild(missingNotice);
            }
            if (session.turns.length && !session.busy) renderGroupWorkflowPicker(session, body);

            if (session.turns.length === 0 && !session.busy && !session.error && !(session.outbox || []).length) {
                var empty = elementWith('discuss-empty group-empty');
                var title = document.createElement('strong');
                title.textContent = session.pendingPreset ? 'Preview discussion' : 'What should we discuss?';
                empty.appendChild(title);
                empty.appendChild(document.createTextNode(session.pendingPreset ? 'Review the participants and invitations before starting.' : 'Choose participants, then type a message or preview a discussion preset.'));
                var pairPicker = elementWith('group-participant-picker');
                _groupPairPicker(session, pairPicker, function(ids) {
                    if (session.pendingPreset) session.pendingPreset = _groupAdaptPresetForRoster(session.pendingPreset, session.participants);
                });
                empty.appendChild(pairPicker);
                if (session.pendingPreset) {
                    _renderGroupPresetPreview(session, empty);
                } else {

                var presets = _groupSettings ? _groupSettings.presets : [];
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
                        list.appendChild(createGroupPresetCard(card, session, function() {
                            startGroupDebate({presetId: card.id, label: card.label, badge: card.badge});
                        }));
                    });
                    empty.appendChild(list);
                });
                }
                body.appendChild(empty);
            } else {
                // Active session topic banner
                if (session.topicLabel || session.question) {
                    var banner = elementWith('group-topic-banner');
                    var bannerTop = elementWith('group-topic-top');
                    bannerTop.appendChild(elementWith('group-topic-title', session.topicLabel || 'Group'));
                    if (session.topicBadge) {
                        bannerTop.appendChild(elementWith('group-topic-badge', session.topicBadge));
                    }
                    banner.appendChild(bannerTop);
                    if (session.question && session.presetId) {
                        banner.appendChild(elementWith('group-topic-question', session.question));
                    } else if (session.question && !session.presetId) {
                        banner.appendChild(elementWith('group-topic-question', '\u201c' + session.question + '\u201d'));
                    }
                    body.appendChild(banner);
                }

                // Turns list
                var turnsWrap = elementWith('group-turns-list');
                var transferredContext = groupTransferredContextCard(session);
                if (transferredContext) turnsWrap.appendChild(transferredContext);
                var placedPlans = {};
                var appendPlansAfter = function(count) {
                    (session.plans || []).forEach(function(plan, pIdx) {
                        if (placedPlans[pIdx] || plan.afterTurn !== count) return;
                        placedPlans[pIdx] = true;
                        turnsWrap.appendChild(_buildGroupPlanCard(session, plan, pIdx === session.plans.length - 1, path));
                    });
                };
                session.turns.forEach(function(turn, turnIdx) {
                    if (turn.role === 'context') {
                        var summaryCard = elementWith('group-turn-card chat-message-card group-conversation-summary');
                        var summaryHead = elementWith('group-turn-head chat-message-header');
                        summaryHead.appendChild(elementWith('chat-message-name', 'Generated conversation summary'));
                        if (turn.model) summaryHead.appendChild(elementWith('group-turn-model', turn.model));
                        summaryCard.appendChild(summaryHead);
                        var summaryBody = elementWith('group-turn-body discuss-message assistant');
                        renderDiscussMarkdown(summaryBody, turn.text); summaryCard.appendChild(summaryBody);
                        addCopyButton(summaryCard, function() { return turn.text; }, 'Copy summary');
                        groupMessageDisclosure(summaryCard, summaryHead, session, turn, turnIdx);
                        turnsWrap.appendChild(summaryCard); appendPlansAfter(turnIdx + 1); return;
                    }
                    if (turn.passed) {
                        var runStart = turnIdx;
                        while (runStart > 0 && session.turns[runStart - 1].passed) runStart--;
                        var passSeats = [];
                        for (var pIdx = runStart; pIdx < session.turns.length && session.turns[pIdx].passed; pIdx++) {
                            if (passSeats.indexOf(session.turns[pIdx].seat) < 0) passSeats.push(session.turns[pIdx].seat);
                        }
                        var totalSeats = (session.participants && session.participants.length) || 2;
                        var allPassed = passSeats.length >= totalSeats;
                        if (!allPassed) {
                            turnsWrap.appendChild(elementWith('group-pass-note', _groupSpeakerName(turn.seat, turn.agent) + ' had no additions.'));
                        } else if (turnIdx === runStart) {
                            var msg = totalSeats === 2 ? 'Both editors had no additions.' : 'All ' + totalSeats + ' editors had no additions.';
                            turnsWrap.appendChild(elementWith('group-pass-note', msg));
                        }
                        if (turn.review_pending && turn.tool_conversation_id) turnsWrap.appendChild(_groupToolReview(session, turn));
                        if (turn.review_unavailable) turnsWrap.appendChild(elementWith('group-runtime-notice', 'An older review is unavailable after the restart. Your changes remain saved; use file history to inspect them.'));
                        appendPlansAfter(turnIdx + 1); return;
                    }
                    if (turn.role === 'invitation') {
                        var invitation = elementWith('group-preset-invitation');
                        invitation.append(elementWith('group-preset-label', turn.label || 'Preset'), elementWith('group-preset-text', turn.text));
                        highlightChatMentions(invitation, session.participants);
                        turnsWrap.appendChild(invitation);
                        appendPlansAfter(turnIdx + 1);
                        return;
                    }
                    if (turn.role === 'user') {
                        var uCard = elementWith('group-turn-card chat-message-card is-user');
                        var uHead = elementWith('group-turn-head chat-message-header');
                        uHead.appendChild(elementWith('chat-message-name', 'Me'));
                        var uTime = turn.created_at || (session.createdAt ? (session.createdAt + turnIdx * 60) : 0);
                        var uMeta = _buildMessageMeta(uTime, null);
                        if (uMeta) uHead.appendChild(uMeta);
                        uCard.appendChild(uHead);
                        var uBody = elementWith('group-turn-body discuss-message');
                        renderDiscussMarkdown(uBody, turn.text);
                        highlightChatMentions(uBody, session.participants);
                        uCard.appendChild(uBody);
                        addCopyButton(uCard, function() { return turn.text; }, 'Copy message');
                        groupMessageDisclosure(uCard, uHead, session, turn, turnIdx);
                        turnsWrap.appendChild(uCard);
                        appendPlansAfter(turnIdx + 1);
                        return;
                    }
                    var seatNum = turn.seat === 3 ? 3 : (turn.seat === 2 ? 2 : 1);
                    var seatCls = 'is-critic-' + seatNum;
                    var card = elementWith('group-turn-card chat-message-card ' + seatCls);
                    var head = elementWith('group-turn-head chat-message-header');
                    var left = elementWith('group-turn-head-left');
                    left.appendChild(elementWith('chat-message-name', _groupSpeakerName(turn.seat, turn.agent)));
                    if (turn.tag) left.appendChild(elementWith('group-turn-tag', turn.tag));
                    head.appendChild(left);
                    var cTime = turn.created_at || (session.createdAt ? (session.createdAt + turnIdx * 60) : 0);
                    var cMeta = _buildMessageMeta(cTime, turn.duration_ms);
                    if (cMeta) head.appendChild(cMeta);
                    if (turn.model) head.appendChild(elementWith('group-turn-model', turn.model));
                    if (turn.context_sent) {
                        var rCtxBtn = document.createElement('button');
                        rCtxBtn.type = 'button';
                        rCtxBtn.className = 'discuss-context-inspect-btn';
                        rCtxBtn.textContent = 'Context';
                        rCtxBtn.title = 'Inspect exact prompt, instructions, and frontmatter sent on this turn';
                        rCtxBtn.onclick = function() {
                            openDiscussContextSentDialog(turn.context_sent, _groupSpeakerName(turn.seat, turn.agent));
                        };
                        head.appendChild(rCtxBtn);
                    }
                    card.appendChild(head);
                    var textWrap = elementWith('group-turn-body discuss-message assistant');
                    renderDiscussMarkdown(textWrap, _groupLinkLines(groupVisibleReply(turn.text, false), turn.scene || session.originScene || path));
                    highlightChatMentions(textWrap, session.participants);
                    card.appendChild(textWrap);
                    if (turn.tag === 'Recap' || Array.from(textWrap.querySelectorAll('h1,h2')).some(function(node) { return /^Agreed edits\b/i.test(node.textContent); })) {
                        card.classList.add('group-recap-message');
                        groupDecorateRecap(textWrap, session, turn, turnIdx);
                    }
                    if (turn.inherited) card.classList.add('group-inherited-message');
                    if (turn.model_inferred) head.appendChild(elementWith('group-turn-model', 'model inferred'));
                    if (turn.tag === 'Recap' && (turn.preset_kind ? turn.preset_kind !== 'workflow' : session.presetId !== 'second_opinion')) card.insertBefore(elementWith('group-plan-title', 'Revision plan'), textWrap);
                    if (turn.positions) card.appendChild(groupPositionsCard(session, turn));
                    addCopyButton(card, function() { return groupVisibleReply(turn.text, false); }, 'Copy message');
                    groupMessageDisclosure(card, head, session, turn, turnIdx);
                    turnsWrap.appendChild(card);
                    if (turn.review_pending && turn.tool_conversation_id) turnsWrap.appendChild(_groupToolReview(session, turn));
                    if (turn.review_unavailable) turnsWrap.appendChild(elementWith('group-runtime-notice', 'An older review is unavailable after the restart. Your changes remain saved; use file history to inspect them.'));
                    appendPlansAfter(turnIdx + 1);
                });
                // A plan whose turns were cut short still shows, at the end.
                (session.plans || []).forEach(function(plan, pIdx) {
                    if (!placedPlans[pIdx]) {
                        turnsWrap.appendChild(_buildGroupPlanCard(session, plan, pIdx === session.plans.length - 1, path));
                    }
                });
                var doneInvitations = typeof groupPresetDebateInvitationCount === 'function' ? groupPresetDebateInvitationCount(session) : 0;
                if (!session.busy && !session.queuePaused && !(session.outbox || []).length && !(session.pendingMessages || []).length
                    && session.presetId && session.presetId !== 'second_opinion' && doneInvitations >= 2 && doneInvitations < 5) {
                    var contBar = elementWith('group-continue-bar');
                    var contBtn = document.createElement('button');
                    contBtn.type = 'button';
                    contBtn.id = 'groupContinueToFiveBtn';
                    contBtn.className = 'group-more-turn-btn';
                    contBtn.textContent = 'Continue to 5 turns';
                    contBtn.title = 'Run ' + (5 - doneInvitations) + ' more debate ' + (5 - doneInvitations === 1 ? 'turn' : 'turns') + ' to reach 5 turns';
                    contBtn.onclick = function() { continueManagedGroupToFive(session); };
                    contBar.appendChild(contBtn);
                    turnsWrap.appendChild(contBar);
                }
                body.appendChild(groupConversationNavigation(session, turnsWrap));
                body.appendChild(turnsWrap);

                // Live status spinner
                if (session.busy) {
                    var statusRow = elementWith('group-live-status');
                    statusRow.setAttribute('role', 'status');
                    var spin = elementWith('hl-card-spinner');
                    var statusMsg = elementWith('group-live-status-text', session.statusText || 'Thinking\u2026');
                    statusMsg.id = 'groupLiveStatusText';
                    var stopBtn = document.createElement('button');
                    stopBtn.type = 'button';
                    stopBtn.className = 'group-stop-btn';
                    stopBtn.textContent = 'Stop';
                    stopBtn.onclick = stopGroupDebate;
                    statusRow.append(spin, statusMsg, stopBtn);
                    body.appendChild(statusRow);
                    var liveBox = elementWith('group-live-progress');
                    liveBox.id = 'groupLiveProgress';
                    liveBox.hidden = true;
                    body.appendChild(liveBox);
                    var approvalsBox = elementWith('group-live-approvals');
                    approvalsBox.id = 'groupLiveApprovals';
                    body.appendChild(approvalsBox);
                    if (session.live) setTimeout(_renderGroupLive, 0);
                }

                // Error banner
                if (session.error) {
                    var errBox = elementWith('group-error-banner');
                    errBox.appendChild(elementWith('group-error-text', session.error));
                    body.appendChild(errBox);
                }

            }
            renderManagedGroupQueue(session, body);
            pane.appendChild(body);
            // Append the composer before restoring scroll so body already has its final flex height:
            pane.appendChild(createGroupComposer(session));
            queueMicrotask(function() { groupHydrateRecapReviews(session); });
            body.dataset.scene = path;
            groupInstallScroll(body, session);
            if (_groupLatestPlan(session)) _syncGroupApplyButton(session);
            if (session.managed) groupRuntimePoll(session);
            if (inputFocus) {
                var restoredInput = document.getElementById('groupInput');
                if (restoredInput) {
                    restoredInput.focus({preventScroll: true});
                    restoredInput.setSelectionRange(inputFocus.start, inputFocus.end);
                }
            }
        }


        function _buildGroupPlanCard(session, plan, isLatest, path) {
            var planCard = elementWith('group-plan-card' + (isLatest ? ' is-latest' : ''));
            if (isLatest) planCard.id = 'groupPlanCard';
            var applied = plan.items.filter(function(item) { return item.applied; }).length;
            var planHead = elementWith('group-plan-head');
            planHead.append(
                elementWith('group-plan-title', 'Revision plan'),
                elementWith('group-plan-sub', isLatest
                    ? (plan.agent ? _groupSpeakerName('moderator', plan.agent) : _groupSeatName('moderator') + ' \u00b7 agent not recorded') + ' \u00b7 choose changes to apply or add as TODO'
                    : 'Earlier plan \u00b7 ' + plan.items.length + (plan.items.length === 1 ? ' item' : ' items')
                        + (applied ? ' \u00b7 ' + applied + ' applied' : ''))
            );
            planCard.appendChild(planHead);
            // Earlier plans fold to their heading; their line numbers may be
            // out of date once later changes are applied.
            if (!isLatest) {
                var toggle = document.createElement('button');
                toggle.type = 'button';
                toggle.className = 'group-plan-toggle';
                toggle.textContent = plan.expanded ? 'Hide' : 'Show';
                toggle.setAttribute('aria-expanded', plan.expanded ? 'true' : 'false');
                toggle.onclick = function() {
                    plan.expanded = !plan.expanded;
                    renderSceneGroupPane();
                };
                planHead.appendChild(toggle);
                if (!plan.expanded) return planCard;
            }

            var groups = {};
            ['agreed', 'suggested'].forEach(function(kind) {
                var section = document.createElement('section');
                section.className = 'group-plan-section';
                section.dataset.consensus = kind;
                var title = document.createElement('h3');
                title.className = 'group-plan-section-title';
                title.textContent = kind === 'agreed' ? 'Agreed changes' : 'Other suggestions';
                section.setAttribute('aria-label', title.textContent);
                section.appendChild(title);
                var list = elementWith('group-plan-list');
                section.appendChild(list);
                groups[kind] = {section: section, list: list};
            });
            plan.items.forEach(function(item) {
                var row = elementWith('group-plan-item' + (item.applied ? ' is-applied' : ''));
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.className = 'group-plan-check';
                cb.checked = !!item.checked || !!item.applied;
                cb.disabled = !!item.applied;
                cb.setAttribute('aria-label', item.title);
                var content = elementWith('group-plan-item-text');
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
                    var change = elementWith('group-plan-change discuss-message assistant');
                    renderDiscussMarkdown(change, _groupLinkLines(md.join('\n\n'), path));
                    content.appendChild(change);
                } else if (item.detail) {
                    content.appendChild(document.createTextNode(' \u2014 ' + item.detail));
                }
                if (item.proposedBy || item.applied) {
                    var agreeCopy = (session.participants && session.participants.length > 2) ? ' \u00b7 all agree' : ' \u00b7 both agree';
                    var unendorsedCopy = (session.participants && session.participants.length > 2) ? ' \u00b7 not yet endorsed by all editors' : ' \u00b7 not yet endorsed by both editors';
                    content.appendChild(elementWith('group-plan-by',
                        (item.applied ? '\u2713 Applied with ' + item.applied + (item.proposedBy ? ' \u00b7 ' : '') : '')
                        + (item.proposedBy ? _groupProposerName(item.proposedBy) + (item.accepted ? agreeCopy : unendorsedCopy) : '')));
                }
                var todoBtn = document.createElement('button');
                todoBtn.type = 'button';
                todoBtn.className = 'group-todo-btn' + (item.todoAdded ? ' is-added' : '');
                todoBtn.textContent = item.todoAdded ? '\u2713 TODO' : '+ TODO';
                todoBtn.disabled = !!item.todoAdded || !!item.applied;
                todoBtn.setAttribute('data-tip', 'Insert an inline <!-- TODO: ... --> comment for this item into the scene');
                todoBtn.onclick = function() { insertGroupPlanTodo(item); };

                cb.onchange = function() {
                    item.checked = cb.checked;
                    if (isLatest) _syncGroupApplyButton(session);
                    _saveGroupSession(session);
                };
                row.append(cb, content, todoBtn);
                groups[item.accepted ? 'agreed' : 'suggested'].list.appendChild(row);
            });
            ['agreed', 'suggested'].forEach(function(kind) {
                if (groups[kind].list.childNodes.length) planCard.appendChild(groups[kind].section);
            });
            if (!plan.items.length && !(plan.open || []).length && !plan.authorsCall) {
                planCard.appendChild(elementWith('group-plan-empty', 'No new changes to suggest.'));
            }

            if (plan.open && plan.open.length) {
                var openBox = elementWith('group-open');
                openBox.appendChild(elementWith('group-open-title', 'Still open \u00b7 your call'));
                plan.open.forEach(function(item) {
                    var openItem = elementWith('group-open-item');
                    openItem.appendChild(elementWith('group-open-issue', item.issue || ''));
                    [['Critic 1', item.critic1], ['Critic 2', item.critic2], ['Critic 3', item.critic3]].forEach(function(pair) {
                        if (!pair[1]) return;
                        var line = elementWith('group-open-side');
                        var who = document.createElement('strong');
                        who.textContent = _groupProposerName(pair[0]) + ': ';
                        line.append(who, document.createTextNode(pair[1]));
                        openItem.appendChild(line);
                    });
                    openBox.appendChild(openItem);
                });
                planCard.appendChild(openBox);
            }

            if (plan.authorsCall) {
                var callBox = elementWith('group-authors-call');
                var callTitle = document.createElement('strong');
                callTitle.textContent = 'Author\u2019s Call (Unresolved trade-off): ';
                callBox.append(callTitle, document.createTextNode(plan.authorsCall));
                planCard.appendChild(callBox);
            }
            if (!isLatest || session.busy) return planCard;

            var app = (_groupSettings && _groupSettings.app) || {};
            _groupApplyAgentChoice = _groupApplyAgentChoice
                || ((app.critic2 || {}).agent)
                || ((app.critic1 || {}).agent)
                || 'claude';

            var actBar = elementWith('group-plan-actions');
            var applyLabel = elementWith('group-apply-label', 'Apply with:');
            var agentSelect = document.createElement('select');
            agentSelect.id = 'groupApplyAgentSelect';
            agentSelect.className = 'group-apply-select';
            agentSelect.setAttribute('aria-label', 'Agent to apply ticked revisions');
            DISCUSS_AGENTS.forEach(function(id) {
                var opt = document.createElement('option');
                opt.value = id;
                opt.textContent = _groupAgentDisplay(id);
                agentSelect.appendChild(opt);
            });
            agentSelect.value = _groupApplyAgentChoice;
            agentSelect.onchange = function() {
                _groupApplyAgentChoice = agentSelect.value;
                _syncGroupApplyButton(session);
            };

            var applyBtn = document.createElement('button');
            applyBtn.type = 'button';
            applyBtn.id = 'groupApplyBtn';
            applyBtn.className = 'group-apply-btn';
            applyBtn.onclick = function() {
                applyGroupPlanWithAgent(_groupApplyAgentChoice, plan);
            };

            var moreBtn = document.createElement('button');
            moreBtn.type = 'button';
            moreBtn.id = 'groupMoreTurnBtn';
            moreBtn.className = 'group-more-turn-btn';
            moreBtn.textContent = '+1 Turn';
            moreBtn.setAttribute('data-tip', 'Ask the other critic to respond one more time, then update the plan');
            moreBtn.onclick = runGroupPlusOneTurn;

            actBar.append(applyLabel, agentSelect, applyBtn, moreBtn);
            planCard.appendChild(actBar);
            return planCard;
        }

        function _syncGroupApplyButton(session) {
            var btn = document.getElementById('groupApplyBtn');
            if (!btn || !session) return;
            var latest = _groupLatestPlan(session);
            var count = (latest ? latest.items : []).filter(function(item) { return item.checked && !item.applied; }).length;
            var agentLabel = _groupAgentDisplay(_groupApplyAgentChoice || 'claude');
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

        function _normalizeChapterKey(ch, path) {
            const folder = (path && path.indexOf('/') !== -1) ? path.split('/')[0].trim() : '';
            const mFolder = folder ? folder.match(/^ch0*(\d+)$/i) : null;
            const chStr = ch != null ? String(ch).trim() : '';
            const mCh = chStr ? chStr.match(/^(?:chapter|ch)?\s*0*(\d+)$/i) : null;
            if (mFolder) return 'num:' + parseInt(mFolder[1], 10);
            if (mCh) return 'num:' + parseInt(mCh[1], 10);
            if (folder && folder.toLowerCase() !== 'manuscript') return 'folder:' + folder.toLowerCase();
            if (chStr && chStr.toLowerCase() !== 'manuscript') return 'ch:' + chStr.toLowerCase();
            return 'path:' + (path || '');
        }

        function _getSceneChapterWords(path) {
            if (!path || typeof meta !== 'object' || !meta) return 0;
            const currentMeta = meta[path] || {};
            const ch = (currentMeta.chapter != null ? String(currentMeta.chapter).trim() : '')
                || (currentMeta.fm && currentMeta.fm.chapter != null ? String(currentMeta.fm.chapter).trim() : '');
            const targetKey = _normalizeChapterKey(ch, path);

            let sum = 0;
            let counted = 0;
            for (const p in meta) {
                if (!meta[p] || typeof meta[p].words !== 'number') continue;
                const pCh = (meta[p].chapter != null ? String(meta[p].chapter).trim() : '')
                    || (meta[p].fm && meta[p].fm.chapter != null ? String(meta[p].fm.chapter).trim() : '');
                const pKey = _normalizeChapterKey(pCh, p);
                if (targetKey === pKey) {
                    sum += meta[p].words;
                    counted++;
                }
            }
            if (counted > 0) return sum;

            // Fallback: try storyModel.bands
            if (typeof storyModel === 'object' && storyModel && Array.isArray(storyModel.bands)) {
                const band = storyModel.bands.find(function(b) {
                    return b.chapter != null && _normalizeChapterKey(b.chapter, '') === targetKey;
                });
                if (band && typeof band.words === 'number' && band.words > 0) {
                    return band.words;
                }
            }

            return typeof currentMeta.words === 'number' ? currentMeta.words : 0;
        }

        function _getChapterLabel(path) {
            if (!path || typeof meta !== 'object' || !meta) return 'chapter';
            const currentMeta = meta[path] || {};
            const ch = (currentMeta.chapter != null ? String(currentMeta.chapter).trim() : '')
                || (currentMeta.fm && currentMeta.fm.chapter != null ? String(currentMeta.fm.chapter).trim() : '');
            const targetKey = _normalizeChapterKey(ch, path);

            // Look for a nicely formatted name among sibling scenes
            for (const p in meta) {
                if (!meta[p]) continue;
                const pCh = (meta[p].chapter != null ? String(meta[p].chapter).trim() : '')
                    || (meta[p].fm && meta[p].fm.chapter != null ? String(meta[p].fm.chapter).trim() : '');
                if (_normalizeChapterKey(pCh, p) === targetKey) {
                    if (pCh && pCh.toLowerCase() !== 'manuscript' && !/^ch0*\d+$/i.test(pCh)) {
                        return /^\d+$/.test(pCh) ? 'Chapter ' + pCh : pCh;
                    }
                }
            }

            if (targetKey.startsWith('num:')) {
                return 'Chapter ' + targetKey.slice(4);
            }
            if (ch && ch.toLowerCase() !== 'manuscript') {
                return /^\d+$/.test(ch) ? 'Chapter ' + ch : ch;
            }
            if (path.indexOf('/') !== -1) {
                const folder = path.split('/')[0];
                const match = folder.match(/^ch0*(\d+)$/i);
                if (match) return 'Chapter ' + parseInt(match[1], 10);
                return folder;
            }
            return 'chapter';
        }

        function _getBookTotalWords() {
            if (typeof window._getBookBaselineWords === 'function') {
                return window._getBookBaselineWords();
            }
            let sum = 0;
            if (typeof paths !== 'undefined' && Array.isArray(paths) && typeof meta === 'object' && meta) {
                let counted = 0;
                for (let i = 0; i < paths.length; i++) {
                    const sp = paths[i];
                    if (meta[sp] && typeof meta[sp].words === 'number') {
                        sum += meta[sp].words;
                        counted++;
                    }
                }
                if (counted > 0) return sum;
            }
            if (typeof storyModel === 'object' && storyModel && typeof storyModel.total_words === 'number' && storyModel.total_words > 0) {
                return storyModel.total_words;
            }
            if (typeof meta === 'object' && meta) {
                for (const k in meta) {
                    if (meta[k] && typeof meta[k].words === 'number') {
                        sum += meta[k].words;
                    }
                }
            }
            return sum;
        }

        function _formatWordsCompact(num) {
            if (typeof num !== 'number' || isNaN(num)) return '0';
            if (num >= 1000000) {
                return (num / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
            }
            if (num >= 1000) {
                return (num / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
            }
            return num.toLocaleString();
        }

        var WORD_COUNT_COMPACT_KEY = typeof WORD_COUNT_COMPACT_KEY !== 'undefined' ? WORD_COUNT_COMPACT_KEY : 'proseview-edit-word-compact';
        function _isWordCountCompact() {
            try {
                return localStorage.getItem(WORD_COUNT_COMPACT_KEY) === 'true';
            } catch (e) {
                return false;
            }
        }

        function _toggleWordCountCompact() {
            const next = !_isWordCountCompact();
            try {
                localStorage.setItem(WORD_COUNT_COMPACT_KEY, next ? 'true' : 'false');
            } catch (e) {}
            return next;
        }

        // Words (scene / chapter / total book) and the two variety scores, with typical ranges on hover.
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
            const chWords = _getSceneChapterWords(path);
            const bookWords = _getBookTotalWords();
            const wordsWarn = !!(words && md.words) && (words > md.words * 1.5 || words < md.words * 0.5);

            const isCompact = _isWordCountCompact();
            const sceneStr = (isCompact && words >= 10000) ? _formatWordsCompact(words) : words.toLocaleString();
            const chStr = isCompact ? _formatWordsCompact(chWords) : chWords.toLocaleString();
            const bookStr = isCompact ? _formatWordsCompact(bookWords) : bookWords.toLocaleString();

            const chLabel = _getChapterLabel(path);
            let tip = 'Words of prose in this scene. Excludes frontmatter, TODOs, comments, and notes. '
                + (md.words ? 'Your typical scene: ' + Math.round(md.words).toLocaleString() + '. ' : '')
                + '\n• ' + words.toLocaleString() + ' in scene'
                + (bookWords > 0 ? '\n• ' + chWords.toLocaleString() + ' in ' + chLabel : '')
                + (bookWords > 0 ? '\n• ' + bookWords.toLocaleString() + ' in manuscript' : '')
                + '\n\n(Click to toggle compact format)';

            const wordSpan = document.createElement('span');
            wordSpan.className = 'scene-summary-part scene-summary-words' + (wordsWarn ? ' is-warn' : '');
            wordSpan.title = tip;
            wordSpan.setAttribute('role', 'button');
            wordSpan.setAttribute('tabindex', '0');
            wordSpan.setAttribute('aria-label', 'Word count: ' + words + ' in scene' + (bookWords > 0 ? ', ' + chWords + ' in ' + chLabel + ', ' + bookWords + ' in book' : '') + '. Click to toggle format.');
            wordSpan.onclick = function(e) {
                if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
                _toggleWordCountCompact();
                refreshSceneSummary();
                if (typeof window._updateEditWordDelta === 'function') {
                    window._updateEditWordDelta();
                }
            };
            wordSpan.onkeydown = function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    wordSpan.click();
                }
            };

            const bScene = document.createElement('b');
            bScene.textContent = sceneStr;
            wordSpan.appendChild(bScene);

            if (bookWords > 0 && (bookWords !== words || chWords !== words)) {
                const uScene = document.createElement('span');
                uScene.className = 'scene-summary-unit';
                uScene.textContent = ' scene';
                wordSpan.appendChild(uScene);

                if (chWords > 0 && chWords !== bookWords) {
                    wordSpan.append(' / ');
                    const bCh = document.createElement('b');
                    bCh.textContent = chStr;
                    wordSpan.appendChild(bCh);

                    const uCh = document.createElement('span');
                    uCh.className = 'scene-summary-unit';
                    uCh.textContent = ' ch';
                    wordSpan.appendChild(uCh);
                }

                if (bookWords > 0 && bookWords !== words) {
                    wordSpan.append(' / ');
                    const bBook = document.createElement('b');
                    bBook.textContent = bookStr;
                    wordSpan.appendChild(bBook);

                    const uBook = document.createElement('span');
                    uBook.className = 'scene-summary-unit';
                    uBook.textContent = ' book';
                    wordSpan.appendChild(uBook);
                }
            } else {
                wordSpan.append(' words');
            }

            line.appendChild(wordSpan);

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
        window.refreshSceneSummary = refreshSceneSummary;

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
            var hasDraft = !!((document.getElementById('discussInput') || {}).value);
            var waitingLegacyDraft = hasLegacyDiscussDraft(doc, _discussAgent);
            if (!hasDraft && !_discussDraftDocument && activateLegacyDiscussDraft(doc, _discussAgent)) {
                document.getElementById('discussAnnouncement').textContent =
                    'Conversation kept open. Restored the saved draft for ' + doc.path + '.';
            } else if ((hasDraft || _discussDraftDocument) && waitingLegacyDraft) {
                document.getElementById('discussAnnouncement').textContent =
                    'Conversation kept open. Your current draft is still here. A saved draft for this file '
                    + 'is waiting and will appear after you send or clear this draft.';
            } else {
                document.getElementById('discussAnnouncement').textContent = _discussIncludeCurrentDocument
                    ? 'Conversation kept open. ' + discussTurnDocument().path + ' remains attached.'
                    : _discussDraftDocument
                    ? 'Conversation kept open. Your draft is still here; ' + discussTurnDocument().path + ' remains attached.'
                    : hasDraft
                    ? 'Conversation kept open. Your draft is still here; context follows ' + doc.path + '.'
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
            ['connection', 'conversation.reset', 'turn.queued', 'turn.steered', 'turn.cancelled', 'turn.preparing', 'turn.started', 'turn.completed', 'turn.idle', 'response.completed', 'progress.delta',
             'plan.updated', 'activity.updated', 'approval.requested', 'approval.resolved', 'approval.expired', 'task.ready', 'task.failed',
             'task.updated', 'tasks.cleared', 'notice.dismissed', 'model.changed', 'warning', 'error'].forEach(function(type) {
                source.addEventListener(type, function(event) {
                    if (type === 'connection') {
                        var detail = JSON.parse(event.data);
                        setDiscussConnection(detail.state, detail.reason || '');
                    }
                    if (type === 'turn.started' || type === 'conversation.reset') _discussStreamText = '';
                    if (type === 'conversation.reset') {
                        _discussReview = [];
                        _discussReviewKeep = {};
                        _clearBtwTabs(cid);
                    }
                    // A new question accepts what the last turn changed: the edits are
                    // already saved, and the server has already let go of their review.
                    // Asked rather than cleared here, since this event can arrive after
                    // a quick turn has finished and put up its own card.
                    if (type === 'turn.preparing') refreshDiscussReview();
                    if (type === 'turn.completed' || type === 'turn.failed' || type === 'turn.cancelled') {
                        _clearDiscussFrontmatterSync();
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
            source.addEventListener('skills.changed', function() {
                loadDiscussSkillList(true);
                if (!document.getElementById('discussSkillsPicker').hidden) loadDiscussSkills(true);
            });
            source.addEventListener('response.delta', function(event) {
                var detail = JSON.parse(event.data);
                appendDiscussStreamDelta(detail.text || '');
            });
            ['side_question.started', 'side_question.delta', 'side_question.activity',
             'side_question.completed', 'side_question.failed', 'side_question.cancelled'].forEach(function(type) {
                source.addEventListener(type, function(event) {
                    handleBtwEvent(cid, type, JSON.parse(event.data));
                });
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
            var head = elementWith('discuss-message-label chat-message-header');
            head.appendChild(elementWith('chat-message-name', discussAgentLabel()));
            var meta = elementWith('chat-message-meta');
            meta.appendChild(elementWith('chat-message-duration', 'Thinking\u2026'));
            head.appendChild(meta);
            draft.appendChild(head);
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

        function prosviewTargetForRepositoryPath(path, line, endLine) {
            var clean = normalizeProsviewRepositoryPath(path);
            if (!clean) return null;
            if (paths.indexOf(clean) >= 0) return {kind: 'scene', path: clean, line: line, endLine: endLine};
            var node = (typeof repositoryFileByPath !== 'undefined' && repositoryFileByPath[clean])
                || (typeof repoFileByPath !== 'undefined' && repoFileByPath[clean]);
            if (!node) return null;
            if (node.is_scene && node.scene_path && paths.indexOf(node.scene_path) >= 0) {
                return {kind: 'scene', path: node.scene_path, line: line, endLine: endLine};
            }
            return {kind: 'file', path: node.path, line: line, endLine: endLine};
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
            var raw = String(value || '').trim().replace(/^<|>$/g, '');
            if (!raw) return null;
            try { raw = decodeURIComponent(raw); } catch(e) {}
            if (/^file:\/\//i.test(raw)) {
                try {
                    var fileUrl = new URL(raw);
                    if (fileUrl.protocol !== 'file:' || (fileUrl.host && fileUrl.host !== 'localhost')) return null;
                    raw = fileUrl.pathname;
                } catch(e) { return null; }
            }

            var line = null;
            var endLine = null;
            var hashLine = raw.match(/#(?:L|lines?[-_]?)?(\d+)(?:C\d+)?(?:[-–—](?:L)?(\d+)(?:C\d+)?)?$/i);
            if (hashLine) {
                line = parseInt(hashLine[1], 10);
                if (hashLine[2]) endLine = parseInt(hashLine[2], 10);
                raw = raw.slice(0, hashLine.index);
            } else {
                var suffixLine = raw.match(/:(\d+)(?::\d+)?(?:[-–—](?:L)?(\d+)(?::\d+)?)?$/i);
                if (suffixLine) {
                    line = parseInt(suffixLine[1], 10);
                    if (suffixLine[2]) endLine = parseInt(suffixLine[2], 10);
                    raw = raw.slice(0, suffixLine.index);
                } else {
                    var bareLine = raw.match(/^#?(?:lines?[\s_]*)?(\d+)(?:\s*(?:[-–—]|to)\s*(\d+))?$/i);
                    if (bareLine) {
                        line = parseInt(bareLine[1], 10);
                        if (bareLine[2]) endLine = parseInt(bareLine[2], 10);
                        raw = '';
                    }
                }
            }
            if (!Number.isInteger(line) || line < 1) line = null;
            if (!Number.isInteger(endLine) || endLine < 1) endLine = null;
            if (line && endLine && endLine < line) {
                var tmp = line; line = endLine; endLine = tmp;
            }
            raw = raw.replace(/\\/g, '/');

            if (/^[a-z][a-z0-9+.-]*:/i.test(raw)) {
                return null;
            }

            if (!raw && (line || endLine)) {
                var currentPath = currentProsviewRepositoryPath() || (typeof _discussCurrentScenePath === 'function' ? _discussCurrentScenePath() : '');
                if (currentPath) return prosviewTargetForRepositoryPath(currentPath, line, endLine);
            }

            if (raw.charAt(0) === '/') {
                var sceneKeys = Object.keys(meta || {});
                for (var i = 0; i < sceneKeys.length; i++) {
                    var scenePath = sceneKeys[i];
                    if (String((meta[scenePath] || {}).abs_path || '').replace(/\\/g, '/') === raw) {
                        return {kind: 'scene', path: scenePath, line: line, endLine: endLine};
                    }
                }
                var fileKeys = Object.keys(typeof repoFileByPath === 'undefined' ? {} : repoFileByPath);
                for (var j = 0; j < fileKeys.length; j++) {
                    var fileNode = repoFileByPath[fileKeys[j]];
                    if (String((fileNode || {}).abs_path || '').replace(/\\/g, '/') === raw) {
                        return prosviewTargetForRepositoryPath(fileNode.path, line, endLine);
                    }
                }
                var root = prosviewRepositoryRoot();
                if (!root || (raw !== root && !raw.startsWith(root + '/'))) return null;
                return prosviewTargetForRepositoryPath(raw.slice(root.length + 1), line, endLine);
            }

            var direct = prosviewTargetForRepositoryPath(raw, line, endLine);
            if (direct) return direct;
            var current = currentProsviewRepositoryPath();
            if (!current) return null;
            var slash = current.lastIndexOf('/');
            var relative = (slash >= 0 ? current.slice(0, slash + 1) : '') + raw;
            return prosviewTargetForRepositoryPath(relative, line, endLine);
        }

        function flashElements(elements) {
            if (!elements) return;
            var prev = document.querySelectorAll('.para-flash');
            for (var k = 0; k < prev.length; k++) {
                if (prev[k]._paraFlashTimer) clearTimeout(prev[k]._paraFlashTimer);
                prev[k]._paraFlashTimer = null;
                prev[k].classList.remove('para-flash');
            }
            var list = Array.isArray(elements) ? elements : [elements];
            list.forEach(function(el) {
                if (!el || !el.classList) return;
                void el.offsetWidth;
                el.classList.add('para-flash');
                el._paraFlashTimer = setTimeout(function() {
                    el.classList.remove('para-flash');
                    el._paraFlashTimer = null;
                }, 2000);
            });
        }

        function focusProsviewSourceLine(line, endLine, attempt) {
            line = parseInt(line, 10);
            if (!Number.isInteger(line) || line < 1) return;
            endLine = (endLine !== undefined && endLine !== null && endLine !== '') ? parseInt(endLine, 10) : line;
            attempt = attempt || 0;
            var blocks = Array.prototype.slice.call(document.querySelectorAll('#sceneProseHost .ProseMirror > [data-line]'));
            if (!blocks.length) {
                if (attempt < 8) {
                    setTimeout(function() { focusProsviewSourceLine(line, endLine, attempt + 1); }, 60);
                }
                return;
            }

            var startLine = line;
            var stopLine = (Number.isInteger(endLine) && endLine >= line) ? endLine : line;

            var matchedBlocks = [];
            for (var i = 0; i < blocks.length; i++) {
                var bStart = parseInt(blocks[i].getAttribute('data-line') || '', 10);
                if (!Number.isInteger(bStart)) continue;
                var nextBlockLine = (i + 1 < blocks.length)
                    ? parseInt(blocks[i + 1].getAttribute('data-line') || '', 10)
                    : Infinity;
                var bEnd = (Number.isInteger(nextBlockLine) && nextBlockLine > bStart)
                    ? nextBlockLine - 1
                    : bStart;

                if (bStart <= stopLine && bEnd >= startLine) {
                    matchedBlocks.push(blocks[i]);
                }
            }

            if (!matchedBlocks.length) {
                var target = null;
                for (var j = 0; j < blocks.length; j++) {
                    var bl = parseInt(blocks[j].getAttribute('data-line') || '', 10);
                    if (!Number.isInteger(bl)) continue;
                    if (bl === line) { target = blocks[j]; break; }
                    if (bl < line) target = blocks[j];
                    else if (!target) { target = blocks[j]; break; }
                }
                if (target) matchedBlocks = [target];
            }

            if (!matchedBlocks.length) return;

            if (typeof matchedBlocks[0].scrollIntoView === 'function') {
                matchedBlocks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            flashElements(matchedBlocks);
            try {
                var range = document.createRange();
                range.setStartBefore(matchedBlocks[0]);
                range.setEndAfter(matchedBlocks[matchedBlocks.length - 1]);
                highlightQuoteRange(range);
            } catch (e) {}
        }

        var _discussQuoteHighlightTimer = null;
        var _discussQuoteSelectionFallback = false;

        function clearDiscussQuoteHighlight() {
            if (_discussQuoteHighlightTimer) {
                clearTimeout(_discussQuoteHighlightTimer);
                _discussQuoteHighlightTimer = null;
            }
            if (typeof CSS !== 'undefined' && CSS.highlights) {
                try {
                    CSS.highlights.delete('proseview-quote-jump');
                } catch (e) {}
            }
            if (_discussQuoteSelectionFallback) {
                _discussQuoteSelectionFallback = false;
                try {
                    var sel = window.getSelection ? window.getSelection() : null;
                    if (sel && sel.rangeCount) sel.removeAllRanges();
                } catch (e) {}
            }
        }

        function highlightQuoteRange(range) {
            if (!range) return;
            clearDiscussQuoteHighlight();

            if (typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined') {
                try {
                    var hl = new Highlight(range);
                    CSS.highlights.set('proseview-quote-jump', hl);
                } catch (e) {}
            } else {
                try {
                    var sel = window.getSelection ? window.getSelection() : null;
                    if (sel) {
                        sel.removeAllRanges();
                        sel.addRange(range);
                        _discussQuoteSelectionFallback = true;
                    }
                } catch (e) {}
            }

            _discussQuoteHighlightTimer = setTimeout(function() {
                clearDiscussQuoteHighlight();
            }, 2500);
        }

        function normalizeDiscussSearchText(str) {
            return String(str || '')
                .replace(/[\u2018\u2019\u201A\u201B]/g, "'")
                .replace(/[\u201C\u201D\u201E\u201F]/g, '"')
                .replace(/[\u2013\u2014]/g, '-')
                .replace(/[*_`~]/g, '')
                .replace(/\s+/g, ' ')
                .trim();
        }

        function getBlockCleanText(el) {
            if (!el) return '';
            var clone = el.cloneNode(true);
            var jumps = clone.querySelectorAll('.pm-line-jump, .pm-decoration');
            for (var i = 0; i < jumps.length; i++) jumps[i].remove();
            return (clone.textContent || '').replace(/\s+/g, ' ').trim();
        }

        function findBlocksByQuoteText(blocks, quoteText) {
            if (!blocks || !blocks.length || !quoteText) return [];
            var rawParas = String(quoteText).split(/\n[ \t]*\n+/).map(function(p) {
                return normalizeDiscussSearchText(p).replace(/^["'“”«»]+|["'“”«»]+$/g, '').trim();
            }).filter(Boolean);
            var normQuote = normalizeDiscussSearchText(quoteText);
            var trimmed = normQuote.replace(/^["'“”«»]+|["'“”«»]+$/g, '').trim();
            if (!trimmed || trimmed.length < 3) return [];

            for (var i = 0; i < blocks.length; i++) {
                var bText = normalizeDiscussSearchText(getBlockCleanText(blocks[i]));
                if (bText.indexOf(trimmed) >= 0) {
                    return [blocks[i]];
                }
            }

            if (rawParas.length > 1 && rawParas[0].length >= 3) {
                for (var p = 0; p < blocks.length; p++) {
                    var firstBlock = normalizeDiscussSearchText(getBlockCleanText(blocks[p]));
                    if (firstBlock.indexOf(rawParas[0]) >= 0 || (rawParas[0].length > 40 && firstBlock.indexOf(rawParas[0].slice(0, 40)) >= 0)) {
                        var seq = [blocks[p]];
                        var lastPara = rawParas[rawParas.length - 1];
                        var lastNeedle = lastPara.length > 35 ? lastPara.slice(-35).trim() : lastPara;
                        for (var q = p + 1; q < blocks.length && q < p + Math.max(8, rawParas.length + 2); q++) {
                            seq.push(blocks[q]);
                            var qText = normalizeDiscussSearchText(getBlockCleanText(blocks[q]));
                            if (lastNeedle && qText.indexOf(lastNeedle) >= 0) return seq;
                        }
                        if (seq.length > 1) return seq;
                    }
                }
            }

            var prefix = trimmed.length > 40 ? trimmed.slice(0, 40).trim() : trimmed;
            for (var j = 0; j < blocks.length; j++) {
                var blockText = normalizeDiscussSearchText(getBlockCleanText(blocks[j]));
                if (blockText.indexOf(prefix) >= 0) {
                    var matched = [blocks[j]];
                    if (trimmed.length <= 40) return matched;
                    var suffix = trimmed.slice(-35).trim();
                    if (suffix && blockText.indexOf(suffix) >= 0) return matched;
                    for (var k = j + 1; k < blocks.length && k < j + 8; k++) {
                        matched.push(blocks[k]);
                        var kText = normalizeDiscussSearchText(getBlockCleanText(blocks[k]));
                        if (kText.indexOf(suffix) >= 0) return matched;
                    }
                    return [blocks[j]];
                }
            }

            return [];
        }

        function mapNormIndexToRaw(rawText, targetNormIdx) {
            if (targetNormIdx <= 0) return 0;
            var currentNormIdx = 0;
            var inWhitespace = false;
            for (var r = 0; r < rawText.length; r++) {
                var ch = rawText[r];
                if (/[*_`~]/.test(ch)) continue;
                if (/\s/.test(ch)) {
                    if (!inWhitespace) {
                        inWhitespace = true;
                        currentNormIdx++;
                    }
                } else {
                    inWhitespace = false;
                    currentNormIdx++;
                }
                if (currentNormIdx >= targetNormIdx) {
                    return r + 1;
                }
            }
            return rawText.length;
        }

        function findDomRangeInBlocks(blocks, searchText) {
            if (!blocks || !blocks.length || !searchText) return null;
            var normSearch = normalizeDiscussSearchText(searchText);
            var trimmed = normSearch.replace(/^["'“”«»]+|["'“”«»]+$/g, '').trim();
            if (!trimmed || trimmed.length < 3) return null;

            var textNodes = [];
            var fullText = '';
            var nodeOffsets = [];

            for (var b = 0; b < blocks.length; b++) {
                var walker = document.createTreeWalker(blocks[b], NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
                    acceptNode: function(node) {
                        if (node.nodeType === 1) {
                            if (node.classList && node.classList.contains('pm-line-jump')) {
                                return NodeFilter.FILTER_REJECT;
                            }
                            if (node.tagName === 'BR') return NodeFilter.FILTER_ACCEPT;
                            return NodeFilter.FILTER_SKIP;
                        }
                        if (node.parentElement && node.parentElement.closest('.pm-line-jump')) {
                            return NodeFilter.FILTER_REJECT;
                        }
                        return NodeFilter.FILTER_ACCEPT;
                    }
                });
                var curr;
                while ((curr = walker.nextNode())) {
                    if (curr.nodeType === 1) {
                        fullText += ' ';
                        continue;
                    }
                    textNodes.push(curr);
                    nodeOffsets.push(fullText.length);
                    fullText += curr.nodeValue;
                }
                if (b < blocks.length - 1) {
                    fullText += ' ';
                }
            }

            if (!textNodes.length) return null;

            var normFull = fullText
                .replace(/[\u2018\u2019\u201A\u201B]/g, "'")
                .replace(/[\u201C\u201D\u201E\u201F]/g, '"')
                .replace(/[\u2013\u2014]/g, '-')
                .replace(/[*_`~]/g, '')
                .replace(/\s+/g, ' ');

            var foundIdx = normFull.indexOf(trimmed);
            var matchLen = trimmed.length;

            if (foundIdx === -1 && trimmed.length > 30) {
                var prefix = trimmed.slice(0, 30);
                foundIdx = normFull.indexOf(prefix);
                if (foundIdx !== -1) {
                    var suffix = trimmed.slice(-25);
                    var sIdx = normFull.indexOf(suffix, foundIdx);
                    if (sIdx !== -1) {
                        matchLen = (sIdx + suffix.length) - foundIdx;
                    } else {
                        matchLen = prefix.length;
                    }
                }
            }

            if (foundIdx === -1) return null;

            var rawStart = mapNormIndexToRaw(fullText, foundIdx);
            if (foundIdx > 0 && normFull.charAt(foundIdx) !== ' ') {
                while (rawStart < fullText.length && /[\s*_`~]/.test(fullText.charAt(rawStart))) {
                    rawStart++;
                }
            }
            var rawEnd = mapNormIndexToRaw(fullText, foundIdx + matchLen);

            var startNode = null, startOff = 0;
            var endNode = null, endOff = 0;

            for (var i = 0; i < textNodes.length; i++) {
                var nStart = nodeOffsets[i];
                var nLen = textNodes[i].nodeValue.length;
                var nEnd = nStart + nLen;

                if (!startNode && rawStart >= nStart && rawStart <= nEnd) {
                    startNode = textNodes[i];
                    startOff = Math.min(nLen, Math.max(0, rawStart - nStart));
                }
                if (rawEnd >= nStart && rawEnd <= nEnd) {
                    endNode = textNodes[i];
                    endOff = Math.min(nLen, Math.max(0, rawEnd - nStart));
                }
            }

            if (!startNode) { startNode = textNodes[0]; startOff = 0; }
            if (!endNode) {
                endNode = textNodes[textNodes.length - 1];
                endOff = endNode.nodeValue.length;
            }

            try {
                var range = document.createRange();
                range.setStart(startNode, startOff);
                range.setEnd(endNode, endOff);
                return range;
            } catch (e) {
                return null;
            }
        }

        function detectProsviewTargetInPrevEl(el, baseScenePath) {
            if (!el) return null;
            var linkEls = el.querySelectorAll ? el.querySelectorAll('a[data-prosview-path]') : [];
            var explicitTarget = null;
            var fallbackTarget = null;
            for (var i = 0; i < linkEls.length; i++) {
                var a = linkEls[i];
                var cand = {
                    kind: a.dataset.prosviewKind || 'scene',
                    path: a.dataset.prosviewPath,
                    line: parseInt(a.dataset.prosviewLine || '', 10) || null,
                    endLine: parseInt(a.dataset.prosviewEndLine || '', 10) || null
                };
                var isLineOnlyText = /^\s*(?:lines?|l)\s+\d+/i.test((a.textContent || '').trim());
                if (!isLineOnlyText || cand.kind === 'file' || (baseScenePath && cand.path !== baseScenePath)) {
                    if (!explicitTarget || (explicitTarget.kind === 'scene' && cand.kind === 'file') || (!explicitTarget.line && cand.line && cand.path === explicitTarget.path)) {
                        explicitTarget = cand;
                    }
                }
                fallbackTarget = cand;
            }
            var target = explicitTarget;
            if (!target) {
                var candidates = [];
                var codes = el.querySelectorAll ? el.querySelectorAll('code') : [];
                for (var c = 0; c < codes.length; c++) {
                    candidates.push((codes[c].textContent || '').trim());
                }
                var rawText = (el.textContent || '');
                var tokenRe = /(?:^|[\s(`"'\[])((?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_.-]+\.(?:md|markdown|txt|ya?ml|json|py|js|ts|css|html))\b/gi;
                var tm;
                while ((tm = tokenRe.exec(rawText)) !== null) {
                    candidates.push(tm[1]);
                }
                for (var t = 0; t < candidates.length; t++) {
                    var token = String(candidates[t] || '').replace(/[.,:;!?)'"`\]]+$/, '');
                    if (!token) continue;
                    var resolved = resolveProsviewFileReference(token);
                    if (resolved) { target = resolved; break; }
                }
            }
            if (!target) target = fallbackTarget;
            if (target && !target.line && el.textContent) {
                var m = el.textContent.match(/\b(?:lines?|l)\s*(\d+)\s*(?:[-–—]|to)\s*(?:l)?(\d+)\b/i);
                if (m) {
                    target.line = parseInt(m[1], 10) || null;
                    target.endLine = parseInt(m[2], 10) || null;
                } else {
                    var single = el.textContent.match(/\b(?:lines?|l)\s*(\d+)\b/i);
                    if (single) {
                        target.line = parseInt(single[1], 10) || null;
                        target.endLine = target.line;
                    }
                }
            }
            return target;
        }

        function findPreLineRange(pre, line, endLine) {
            if (!pre || !Number.isInteger(line) || line < 1) return null;
            var stopLine = (Number.isInteger(endLine) && endLine >= line) ? endLine : line;
            var curLine = 1;
            var startNode = null, startOff = 0;
            var endNode = null, endOff = 0;
            var lastTextNode = null;
            var walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
                acceptNode: function(node) {
                    if (node.nodeType === 1) {
                        return node.tagName === 'BR' ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
                    }
                    return NodeFilter.FILTER_ACCEPT;
                }
            });
            var node;
            while ((node = walker.nextNode())) {
                if (node.nodeType === 1) {
                    curLine++;
                    if (curLine > stopLine && endNode) break;
                    continue;
                }
                lastTextNode = node;
                var val = node.nodeValue || '';
                var idx = 0;
                while (idx <= val.length) {
                    var nl = val.indexOf('\n', idx);
                    var segEnd = nl >= 0 ? nl : val.length;
                    if (!startNode && curLine >= line) {
                        startNode = node;
                        startOff = idx;
                    }
                    if (curLine >= line && curLine <= stopLine) {
                        endNode = node;
                        endOff = segEnd;
                    }
                    if (nl < 0) break;
                    curLine++;
                    idx = nl + 1;
                    if (curLine > stopLine && endNode) break;
                }
                if (curLine > stopLine && endNode) break;
            }
            if (!startNode && lastTextNode) {
                startNode = lastTextNode;
                startOff = 0;
                endNode = lastTextNode;
                endOff = (lastTextNode.nodeValue || '').length;
            }
            if (!startNode) return null;
            if (!endNode) {
                endNode = startNode;
                endOff = (startNode.nodeValue || '').length;
            }
            try {
                var r = document.createRange();
                r.setStart(startNode, startOff);
                r.setEnd(endNode, endOff);
                return r;
            } catch (e) { return null; }
        }

        function focusRepoFilePreviewMatch(line, endLine, quoteText, sourceText) {
            var body = document.getElementById('filePreviewBody');
            if (!body) return false;
            var normText = normalizeDiscussSearchText(quoteText || '');
            var pre = body.querySelector('pre');
            var blocks = pre
                ? [pre]
                : Array.prototype.slice.call(body.querySelectorAll('p, li, blockquote, h1, h2, h3, h4, h5, h6, tr'));

            if (!normText && !pre && Number.isInteger(line) && line >= 1 && sourceText) {
                var srcLines = String(sourceText).split(/\r?\n/);
                var sIdx = Math.max(0, Math.min(line - 1, srcLines.length - 1));
                var eIdx = Math.max(sIdx, Math.min(((Number.isInteger(endLine) && endLine >= line) ? endLine : line) - 1, srcLines.length - 1));
                var snippet = '';
                for (var si = sIdx; si <= eIdx; si++) {
                    var stripped = srcLines[si].replace(/^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*)/, '').trim();
                    if (stripped && !/^[-*_]{3,}$/.test(stripped)) {
                        snippet += (snippet ? ' ' : '') + stripped;
                    }
                }
                normText = normalizeDiscussSearchText(snippet);
            }

            var matchedBlocks = [];
            if (normText.length >= 3 && blocks.length) {
                matchedBlocks = pre ? [pre] : findBlocksByQuoteText(blocks, normText);
            }

            var matchedRange = null;
            if (normText.length >= 3 && matchedBlocks.length) {
                matchedRange = findDomRangeInBlocks(matchedBlocks, normText);
            }

            if (!matchedRange && pre && Number.isInteger(line) && line >= 1) {
                matchedRange = findPreLineRange(pre, line, endLine);
            }

            if (matchedRange) {
                var targetEl = matchedBlocks[0] || pre;
                var rect = matchedRange.getBoundingClientRect ? matchedRange.getBoundingClientRect() : null;
                if (rect && (rect.height || rect.width) && typeof window !== 'undefined' && typeof window.scrollTo === 'function') {
                    window.scrollTo({
                        top: Math.max(0, (window.scrollY || window.pageYOffset || 0) + rect.top - ((window.innerHeight || 600) / 2) + (rect.height / 2)),
                        behavior: 'smooth'
                    });
                } else if (targetEl && typeof targetEl.scrollIntoView === 'function' && !pre) {
                    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                if (!pre && matchedBlocks.length) flashElements(matchedBlocks);
                highlightQuoteRange(matchedRange);
                return true;
            }
            if (!pre && matchedBlocks.length) {
                if (typeof matchedBlocks[0].scrollIntoView === 'function') {
                    matchedBlocks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                flashElements(matchedBlocks);
                return true;
            }
            return false;
        }

        function jumpAndHighlightDiscussQuote(targetPath, line, endLine, quoteText, targetKind, attempt) {
            var currentScene = document.documentElement.dataset.view === 'scene' && curIdx >= 0 ? paths[curIdx] : '';
            var resolved = targetPath ? (prosviewTargetForRepositoryPath(targetPath, line, endLine) || resolveProsviewFileReference(targetPath)) : null;
            if (!resolved && targetPath) {
                resolved = {kind: targetKind || 'scene', path: targetPath, line: line, endLine: endLine};
            }
            if (!resolved && currentScene) {
                resolved = {kind: 'scene', path: currentScene, line: line, endLine: endLine};
            }
            if (!resolved) return;

            var destKind = resolved.kind || targetKind || 'scene';
            var destPath = resolved.path;

            if (destKind === 'file') {
                if (document.documentElement.dataset.view === 'scene' && typeof closeSceneModal === 'function') {
                    if (!closeSceneModal({route: false})) return;
                }
                if (typeof previewRepoFile === 'function') {
                    var currentFile = document.documentElement.dataset.view === 'file'
                        ? String((document.getElementById('filePreviewTitle') || {}).textContent || '').trim()
                        : '';
                    var runHighlight = function(node) {
                        var bodyText = node && node.body ? node.body : '';
                        if (!bodyText && typeof repoFileByPath !== 'undefined' && repoFileByPath[destPath]) {
                            bodyText = repoFileByPath[destPath].body || '';
                        }
                        focusRepoFilePreviewMatch(line, endLine, quoteText, bodyText);
                        document.getElementById('discussAnnouncement').textContent = 'Opened ' + destPath + (line ? ' at line ' + line : '') + ' in Prosview';
                    };
                    if (currentFile === destPath) {
                        runHighlight(null);
                    } else {
                        previewRepoFile(destPath, {focus: false}).then(function(node) {
                            if (!node) return;
                            if (typeof requestAnimationFrame === 'function') requestAnimationFrame(function() { runHighlight(node); });
                            else setTimeout(function() { runHighlight(node); }, 0);
                        });
                    }
                }
                return;
            }

            var targetScene = destPath || currentScene;
            var sameScene = document.documentElement.dataset.view === 'scene' && targetScene === currentScene;

            if (_pmEditMode && _pmDirty && !sameScene) {
                var warning = 'Save or cancel your scene edits before opening another file.';
                document.getElementById('discussAnnouncement').textContent = warning;
                renderDiscussError(warning);
                return;
            }

            if (!sameScene && targetScene && typeof openSceneModal === 'function') {
                var opened = openSceneModal(targetScene);
                if (opened === false) return;
            }

            attempt = attempt || 0;
            var activeScene = (typeof curIdx !== 'undefined' && curIdx >= 0) ? paths[curIdx] : '';
            var blocks = Array.prototype.slice.call(document.querySelectorAll('#sceneProseHost .ProseMirror > [data-line]'));
            if (!blocks.length || (targetScene && activeScene !== targetScene)) {
                if (attempt < 10) {
                    setTimeout(function() {
                        jumpAndHighlightDiscussQuote(targetScene, line, endLine, quoteText, 'scene', attempt + 1);
                    }, 60);
                }
                return;
            }

            var matchedBlocks = [];
            var normText = normalizeDiscussSearchText(quoteText);

            if (normText.length >= 3) {
                matchedBlocks = findBlocksByQuoteText(blocks, normText);
            }

            if (!matchedBlocks.length && Number.isInteger(line) && line >= 1) {
                var startLine = line;
                var stopLine = (Number.isInteger(endLine) && endLine >= line) ? endLine : line;
                for (var i = 0; i < blocks.length; i++) {
                    var bStart = parseInt(blocks[i].getAttribute('data-line') || '', 10);
                    if (!Number.isInteger(bStart)) continue;
                    var nextBlockLine = (i + 1 < blocks.length)
                        ? parseInt(blocks[i + 1].getAttribute('data-line') || '', 10)
                        : Infinity;
                    var bEnd = (Number.isInteger(nextBlockLine) && nextBlockLine > bStart)
                        ? nextBlockLine - 1
                        : bStart;
                    if (bStart <= stopLine && bEnd >= startLine) {
                        matchedBlocks.push(blocks[i]);
                    }
                }
                if (!matchedBlocks.length) {
                    var targetBlock = null;
                    for (var j = 0; j < blocks.length; j++) {
                        var bl = parseInt(blocks[j].getAttribute('data-line') || '', 10);
                        if (!Number.isInteger(bl)) continue;
                        if (bl === line) { targetBlock = blocks[j]; break; }
                        if (bl < line) targetBlock = blocks[j];
                        else if (!targetBlock) { targetBlock = blocks[j]; break; }
                    }
                    if (targetBlock) matchedBlocks = [targetBlock];
                }
            }

            if (!matchedBlocks.length) return;

            if (typeof matchedBlocks[0].scrollIntoView === 'function') {
                matchedBlocks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            flashElements(matchedBlocks);

            var matchedRange = null;
            if (normText.length >= 3) {
                matchedRange = findDomRangeInBlocks(matchedBlocks, normText);
            }
            if (!matchedRange) {
                try {
                    var r = document.createRange();
                    r.setStartBefore(matchedBlocks[0]);
                    r.setEndAfter(matchedBlocks[matchedBlocks.length - 1]);
                    matchedRange = r;
                } catch (e) {}
            }

            if (matchedRange) {
                highlightQuoteRange(matchedRange);
            }

            var firstLine = matchedBlocks[0].getAttribute('data-line') || line;
            var lastLine = matchedBlocks[matchedBlocks.length - 1].getAttribute('data-line') || endLine || firstLine;
            var rangeDesc = firstLine ? (firstLine === lastLine ? ' at line ' + firstLine : ' at lines ' + firstLine + '–' + lastLine) : '';
            document.getElementById('discussAnnouncement').textContent = 'Jumped to quote' + rangeDesc + (targetScene ? ' in ' + targetScene : '');
        }

        function extractDiscussQuoteText(quoteEl) {
            if (!quoteEl) return '';
            var clone = quoteEl.cloneNode(true);
            var copyBtn = clone.querySelector('.md-copy-btn');
            if (copyBtn) copyBtn.remove();
            var header = clone.querySelector('.discuss-quote-header');
            if (header) header.remove();
            var brs = clone.querySelectorAll('br');
            for (var b = 0; b < brs.length; b++) {
                brs[b].replaceWith('\n');
            }
            var parts = [];
            var blockSel = 'p, li, pre, h1, h2, h3, h4, h5, h6, tr';
            var blocks = clone.querySelectorAll(blockSel);
            for (var i = 0; i < blocks.length; i++) {
                if (blocks[i].querySelector(blockSel)) continue;
                var t = (blocks[i].textContent || '').trim();
                if (t) parts.push(t);
            }
            var text = parts.length ? parts.join('\n\n') : (clone.textContent || '');
            return text.replace(/^From (?:scene|file):[^\r\n]*\r?\n?/m, '').trim();
        }

        function handleDiscussQuoteClick(event, quoteEl, ctx) {
            if (event) {
                if (event.button !== 0 && event.type === 'click') return;
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                if (event.target && (event.target.closest('a') || event.target.closest('.md-copy-btn'))) return;
                if (window.getSelection && !window.getSelection().isCollapsed) {
                    var sel = window.getSelection();
                    var selStr = (sel.toString() || '').trim();
                    if (selStr.length > 0 && ((sel.anchorNode && quoteEl.contains(sel.anchorNode)) || (sel.focusNode && quoteEl.contains(sel.focusNode)))) {
                        return;
                    }
                }
                event.preventDefault();
            }

            var cleanText = extractDiscussQuoteText(quoteEl);
            var targetKind = quoteEl.dataset.targetKind || '';
            var targetPath = quoteEl.dataset.targetPath || (ctx && ctx.scenePath) || _discussCurrentScenePath();
            var targetLine = parseInt(quoteEl.dataset.targetLine || '', 10) || null;
            var targetEndLine = parseInt(quoteEl.dataset.targetEndLine || '', 10) || null;

            var rawText = (quoteEl.innerText || quoteEl.textContent || '').trim();
            var sourceMatch = rawText.match(/^From (?:scene|file):\s*([^\r\n]+)/m);
            if (sourceMatch) {
                targetPath = sourceMatch[1].trim();
                var resolvedSource = prosviewTargetForRepositoryPath(targetPath) || resolveProsviewFileReference(targetPath);
                if (resolvedSource) {
                    targetKind = resolvedSource.kind;
                    targetPath = resolvedSource.path;
                }
            }

            jumpAndHighlightDiscussQuote(targetPath, targetLine, targetEndLine, cleanText, targetKind);
        }

        // Whether the paragraph above a quote names that quote's source: it is
        // just a citation, a short lead-in ("In ch08/02, line 149:"), or ends
        // with a citation and a colon. A long explanation ending in "Possibility:"
        // only mentions its links; the quote below is a rewrite of the passage
        // quoted before it.
        function _discussIntroducesQuote(prevEl, prevText) {
            if (/^[\s(\[]*(?:[^\s]+\.md\s*[·,:]\s*)?lines?\s+\d+(?:\s*[-–—]\s*\d+)?[\s)\].]*$/i.test(prevText)) return true;
            if (!/:$/.test(prevText)) return false;
            if (prevText.split(/\s+/).length <= 12) return true;
            var links = prevEl.querySelectorAll ? prevEl.querySelectorAll('a[data-prosview-path]') : [];
            var lastRef = links.length ? (links[links.length - 1].textContent || '') : '';
            var at = lastRef ? prevText.lastIndexOf(lastRef) : -1;
            if (at < 0) {
                var mentions = prevText.match(/\b(?:lines?|l)\s*\d+(?:\s*(?:[-–—]|to)\s*l?\d+)?/gi);
                lastRef = mentions ? mentions[mentions.length - 1] : '';
                at = lastRef ? prevText.lastIndexOf(lastRef) : -1;
            }
            if (at < 0) return false;
            var trailing = prevText.slice(at + lastRef.length).replace(/[:\s.,;)\]]+$/, '').trim();
            return !trailing || trailing.split(/\s+/).length <= 4;
        }

        function decorateDiscussBlockquote(quoteEl, ctx, prevEl, followingCitation) {
            if (!quoteEl) return;
            var baseScenePath = (ctx && ctx.scenePath) || _discussCurrentScenePath();
            quoteEl._discussCompareLead = prevEl ? prevEl.textContent.trim() : '';
            quoteEl.classList.add('discuss-clickable-quote');
            quoteEl.title = 'Click to jump to this passage in the scene';
            quoteEl.setAttribute('tabindex', '0');
            quoteEl.setAttribute('role', 'button');
            quoteEl.setAttribute('aria-label', 'Jump to quoted passage in Prosview');

            var rawInner = (quoteEl.innerText || quoteEl.textContent || '').trim();
            var sourceMatch = rawInner.match(/^From (?:scene|file):\s*([^\r\n]+)/m);
            if (sourceMatch) {
                var srcResolved = prosviewTargetForRepositoryPath(sourceMatch[1].trim()) || resolveProsviewFileReference(sourceMatch[1].trim());
                if (srcResolved) {
                    quoteEl.dataset.targetKind = srcResolved.kind;
                    quoteEl.dataset.targetPath = srcResolved.path;
                } else {
                    quoteEl.dataset.targetPath = sourceMatch[1].trim();
                }
            }

            var innerLink = quoteEl.querySelector('a[data-prosview-line], a[data-prosview-path]');
            if (innerLink) {
                if (innerLink.dataset.prosviewKind) quoteEl.dataset.targetKind = innerLink.dataset.prosviewKind;
                if (innerLink.dataset.prosviewPath) quoteEl.dataset.targetPath = innerLink.dataset.prosviewPath;
                if (innerLink.dataset.prosviewLine) quoteEl.dataset.targetLine = innerLink.dataset.prosviewLine;
                if (innerLink.dataset.prosviewEndLine) quoteEl.dataset.targetEndLine = innerLink.dataset.prosviewEndLine;
            }
            if (!innerLink && !sourceMatch && followingCitation) {
                quoteEl.dataset.targetKind = followingCitation.kind;
                quoteEl.dataset.targetPath = followingCitation.path;
                if (followingCitation.line) {
                    quoteEl.dataset.targetLine = String(followingCitation.line);
                    quoteEl.dataset.targetEndLine = String(followingCitation.endLine || followingCitation.line);
                }
            }

            if (!prevEl) {
                prevEl = quoteEl.previousElementSibling || (quoteEl.parentElement ? quoteEl.parentElement.previousElementSibling : null);
            }
            // The paragraph above names the quote's source only when it
            // introduces it ("In ch08/02, line 149:") or is just the citation.
            // A line it merely mentions in passing ("the lie at line 88") is a
            // hint, weaker than the quote's own text and than the passage a
            // rewrite replaces; it is applied below if nothing better turns up.
            var prevHint = null;
            if (prevEl) {
                var prevText = (prevEl.textContent || '').trim();
                var introduces = _discussIntroducesQuote(prevEl, prevText);
                var prevTarget = detectProsviewTargetInPrevEl(prevEl, baseScenePath);
                if (!prevTarget && !quoteEl.dataset.targetLine && prevText) {
                    var m = prevText.match(/\b(?:lines?|l)\s*(\d+)\s*(?:[-–—]|to)\s*(?:l)?(\d+)\b/i);
                    var single = m ? null : prevText.match(/\b(?:lines?|l)\s*(\d+)\b/i);
                    if (m) prevTarget = {line: parseInt(m[1], 10), endLine: parseInt(m[2], 10)};
                    else if (single) prevTarget = {line: parseInt(single[1], 10)};
                }
                if (prevTarget && introduces) {
                    if (!quoteEl.dataset.targetPath && prevTarget.path) {
                        quoteEl.dataset.targetKind = prevTarget.kind || 'scene';
                        quoteEl.dataset.targetPath = prevTarget.path;
                    }
                    if (!quoteEl.dataset.targetLine && prevTarget.line) {
                        quoteEl.dataset.targetLine = String(prevTarget.line);
                        quoteEl.dataset.targetEndLine = String(prevTarget.endLine || prevTarget.line);
                    }
                } else if (prevTarget) {
                    prevHint = prevTarget;
                }
            }

            var resolvedForMatch = quoteEl.dataset.targetPath
                ? (prosviewTargetForRepositoryPath(quoteEl.dataset.targetPath) || {kind: quoteEl.dataset.targetKind || 'scene', path: quoteEl.dataset.targetPath})
                : {kind: 'scene', path: baseScenePath};
            var targetsCurrentScene = !resolvedForMatch.path || (resolvedForMatch.kind === 'scene' && resolvedForMatch.path === ((typeof curIdx !== 'undefined' && curIdx >= 0) ? paths[curIdx] : baseScenePath));

            if (!quoteEl.dataset.targetLine && targetsCurrentScene && typeof document !== 'undefined') {
                var clean = extractDiscussQuoteText(quoteEl);
                if (clean && clean.length >= 6) {
                    var sceneBlocks = Array.prototype.slice.call(document.querySelectorAll('#sceneProseHost .ProseMirror > [data-line]'));
                    if (sceneBlocks.length && typeof findBlocksByQuoteText === 'function') {
                        var found = findBlocksByQuoteText(sceneBlocks, clean);
                        if (found.length) {
                            var s = found[0].getAttribute('data-line');
                            var e = found[found.length - 1].getAttribute('data-line') || s;
                            if (s) {
                                quoteEl.dataset.targetKind = 'scene';
                                quoteEl.dataset.targetPath = baseScenePath || ((typeof curIdx !== 'undefined' && curIdx >= 0) ? paths[curIdx] : '');
                                quoteEl.dataset.targetLine = s;
                                quoteEl.dataset.targetEndLine = e;
                            }
                        }
                    }
                }
            }

            if (!quoteEl.dataset.targetLine && prevHint && !(ctx && ctx.lastQuoteTarget)) {
                if (!quoteEl.dataset.targetPath && prevHint.path) {
                    quoteEl.dataset.targetKind = prevHint.kind || 'scene';
                    quoteEl.dataset.targetPath = prevHint.path;
                }
                if (prevHint.line) {
                    quoteEl.dataset.targetLine = String(prevHint.line);
                    quoteEl.dataset.targetEndLine = String(prevHint.endLine || prevHint.line);
                }
            }
            var cited = !!quoteEl.dataset.targetLine;
            if (cited && ctx && quoteEl.dataset.targetPath) {
                ctx.lastQuoteTarget = {
                    kind: quoteEl.dataset.targetKind || 'scene',
                    path: quoteEl.dataset.targetPath,
                    line: parseInt(quoteEl.dataset.targetLine || '', 10) || null,
                    endLine: parseInt(quoteEl.dataset.targetEndLine || '', 10) || null
                };
            }
            // A quote without a citation of its own is usually a suggested
            // rewrite of the passage quoted just before it. Point it there, not
            // at a scene the explanation in between happened to link.
            var inherited = ctx && (ctx.lastQuoteTarget || ctx.lastLocalTarget);
            if (!cited && inherited) {
                if (!quoteEl.dataset.targetPath && inherited.path) {
                    quoteEl.dataset.targetKind = inherited.kind || 'scene';
                    quoteEl.dataset.targetPath = inherited.path;
                }
                if (inherited.line) quoteEl.dataset.targetLine = String(inherited.line);
                if (inherited.endLine) quoteEl.dataset.targetEndLine = String(inherited.endLine);
            }

            if (!quoteEl.dataset.targetPath) {
                quoteEl.dataset.targetPath = baseScenePath;
            }
            if (!quoteEl.dataset.targetKind && quoteEl.dataset.targetPath) {
                var kTarget = prosviewTargetForRepositoryPath(quoteEl.dataset.targetPath);
                quoteEl.dataset.targetKind = (kTarget && kTarget.kind) ? kTarget.kind : 'scene';
            }

            var tLine = parseInt(quoteEl.dataset.targetLine || '', 10);
            var tEndLine = parseInt(quoteEl.dataset.targetEndLine || '', 10) || tLine;
            var tPath = quoteEl.dataset.targetPath || '';
            var tKind = quoteEl.dataset.targetKind || 'scene';
            var isOtherFile = !!(tPath && (tKind === 'file' || (baseScenePath && tPath !== baseScenePath)));
            var lineLabel = tLine ? ((tEndLine && tEndLine !== tLine) ? ('lines ' + tLine + '–' + tEndLine) : ('line ' + tLine)) : '';
            var tagParts = [];
            if (isOtherFile) tagParts.push(tPath);
            if (lineLabel) tagParts.push(lineLabel);

            if (tagParts.length && !quoteEl.querySelector('.discuss-quote-header')) {
                var header = document.createElement('div');
                header.className = 'discuss-quote-header';
                var tag = document.createElement('span');
                tag.className = 'discuss-quote-line-tag';
                tag.textContent = tagParts.join(' · ');
                header.appendChild(tag);
                quoteEl.insertBefore(header, quoteEl.firstChild);
                quoteEl.title = isOtherFile
                    ? ('Click to open ' + tPath + (lineLabel ? ' at ' + lineLabel : ''))
                    : ('Click to jump to ' + lineLabel + ' in the scene');
            }

            quoteEl.onclick = function(event) {
                if (event.target && event.target.closest && event.target.closest('.md-copy-btn')) return;
                try { quoteEl.blur(); } catch(e) {}
                handleDiscussQuoteClick(event, quoteEl, ctx);
            };
            quoteEl.onmouseup = function() {
                try { quoteEl.blur(); } catch(e) {}
            };
            quoteEl.onkeydown = function(event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    handleDiscussQuoteClick(event, quoteEl, ctx);
                }
            };
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
                focusProsviewSourceLine(target.line, target.endLine);
                var rangeLabel = target.line ? (target.line + (target.endLine && target.endLine !== target.line ? '–' + target.endLine : '')) : '';
                document.getElementById('discussAnnouncement').textContent = 'Opened ' + target.path + (rangeLabel ? ' at line ' + rangeLabel : '');
                return;
            }
            if (document.documentElement.dataset.view === 'scene' && typeof closeSceneModal === 'function') {
                if (!closeSceneModal({route: false})) return;
            }
            if (typeof previewRepoFile === 'function') {
                previewRepoFile(target.path, {focus: true, line: target.line, endLine: target.endLine}).then(function(node) {
                    if (!node || !target.line) return;
                    var focusFn = function() { focusRepoFilePreviewMatch(target.line, target.endLine, '', node.body || ''); };
                    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(focusFn);
                    else setTimeout(focusFn, 0);
                });
            }
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

        function renderDiscussBeatmapCard(lang, rawText, parent, ctx) {
            var payload;
            try {
                payload = JSON.parse(String(rawText || '').trim());
            } catch (e) {
                var pre = document.createElement('pre');
                var code = document.createElement('code');
                code.textContent = decodeMarkdownText(rawText || '');
                pre.appendChild(code);
                parent.appendChild(withCopyButton(pre, function() { return code.textContent; }));
                return;
            }

            var isPatch = (lang === 'proseview:beatmap-patch');
            var card = document.createElement('div');
            card.className = 'discuss-beatmap-card ' + (isPatch ? 'is-patch' : 'is-recreate');

            // Header
            var header = document.createElement('div');
            header.className = 'discuss-beatmap-header';

            var headerLeft = document.createElement('div');
            headerLeft.className = 'discuss-beatmap-header-left';

            var icon = document.createElement('span');
            icon.className = 'discuss-beatmap-icon';
            icon.innerHTML = isPatch
                ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>'
                : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>';
            headerLeft.appendChild(icon);

            var title = document.createElement('span');
            title.className = 'discuss-beatmap-title';
            title.textContent = isPatch ? 'BEAT MAP UPDATE PROPOSAL' : 'BEAT MAP RECREATION PROPOSAL';
            headerLeft.appendChild(title);
            header.appendChild(headerLeft);

            var badge = document.createElement('span');
            badge.className = 'discuss-beatmap-badge';
            badge.textContent = isPatch ? 'Targeted Patch' : 'Structural Re-creation';
            header.appendChild(badge);
            card.appendChild(header);

            // Bind proposal to originating scene and revision at render time (Bug 5)
            var boundScenePath = (payload && (payload.scene_path || payload.path)) || '';
            if (!boundScenePath && ctx) {
                if (ctx.scenePath) boundScenePath = ctx.scenePath;
                else if (ctx.document && ctx.document.path) boundScenePath = ctx.document.path;
            }
            if (!boundScenePath && typeof _discussSnapshot !== 'undefined' && _discussSnapshot && _discussSnapshot.document && _discussSnapshot.document.path) {
                boundScenePath = _discussSnapshot.document.path;
            }
            if (!boundScenePath && typeof discussTurnDocument === 'function' && discussTurnDocument() && discussTurnDocument().path) {
                boundScenePath = discussTurnDocument().path;
            }
            if (!boundScenePath && typeof paths !== 'undefined' && typeof curIdx !== 'undefined' && curIdx >= 0 && paths[curIdx]) {
                boundScenePath = paths[curIdx];
            }
            if (!boundScenePath && window.location.hash) {
                var locMatch = window.location.hash.match(/^#\/scene\/(.+)$/);
                if (locMatch) {
                    try { boundScenePath = decodeURIComponent(locMatch[1]); } catch (e) { boundScenePath = locMatch[1]; }
                }
            }
            if (!boundScenePath && typeof window.getBeatMapData === 'function' && window.getBeatMapData() && window.getBeatMapData().scene_path) {
                boundScenePath = window.getBeatMapData().scene_path;
            }

            var boundRevision = (payload && (payload.expected_revision || payload.target_revision || payload.analyzed_revision_hash || payload.revision)) || '';
            if (!boundRevision && typeof window.getBeatMapData === 'function' && window.getBeatMapData() && window.getBeatMapData().scene_path === boundScenePath) {
                boundRevision = window.getBeatMapData().analyzed_revision_hash || '';
            }
            var boundMapVersion = (payload && (payload.expected_map_version || payload.target_map_version || payload.map_version)) || '';
            if (!boundMapVersion && typeof window.getBeatMapData === 'function' && window.getBeatMapData() && window.getBeatMapData().scene_path === boundScenePath) {
                boundMapVersion = window.getBeatMapData().map_version || '';
            }

            if (boundScenePath) {
                var targetTag = document.createElement('div');
                targetTag.className = 'discuss-beatmap-target-scene';
                targetTag.style.cssText = 'font-size:10px; font-family:var(--font-mono); color:var(--text-muted); padding:3px 12px 6px;';
                var shortRev = boundRevision ? String(boundRevision).replace(/^sha256:/i, '').slice(0, 7) : '';
                targetTag.textContent = 'Scene: ' + boundScenePath + (shortRev ? ' (' + shortRev + ')' : '');
                card.appendChild(targetTag);
            }

            // Body
            var body = document.createElement('div');
            body.className = 'discuss-beatmap-body';

            if (isPatch) {
                var patches = (payload && Array.isArray(payload.beats)) ? payload.beats : [];
                if (!patches.length && payload && (payload.beat_order || payload.order)) {
                    var single = Object.assign({}, payload.patch || payload);
                    single.order = payload.beat_order || payload.order;
                    patches.push(single);
                }

                if (patches.length > 0) {
                    patches.forEach(function(p) {
                        var row = document.createElement('div');
                        row.className = 'discuss-beatmap-patch-row';
                        var order = p.order || p.beat_order || 1;

                        var beatTag = document.createElement('span');
                        beatTag.className = 'patch-beat-label';
                        beatTag.textContent = 'Beat ' + order;
                        row.appendChild(beatTag);

                        var detailsDiv = document.createElement('div');
                        detailsDiv.className = 'patch-details';

                        var items = [];
                        if (p.estimated_tension !== undefined) {
                            var tSpan = document.createElement('span');
                            tSpan.className = 'patch-tension';
                            tSpan.textContent = 'Tension: ' + p.estimated_tension + '%';
                            items.push(tSpan);
                        }
                        if (p.title) {
                            var tiSpan = document.createElement('span');
                            tiSpan.className = 'patch-title';
                            tiSpan.textContent = 'Title: "' + p.title + '"';
                            items.push(tiSpan);
                        }
                        if (p.is_turning_point !== undefined) {
                            var tpSpan = document.createElement('span');
                            tpSpan.className = 'patch-tp';
                            tpSpan.textContent = p.is_turning_point ? '⚡ Turning Point' : 'Normal Beat';
                            items.push(tpSpan);
                        }
                        if (p.summary) {
                            var smSpan = document.createElement('span');
                            smSpan.className = 'patch-summary';
                            smSpan.textContent = p.summary;
                            items.push(smSpan);
                        }

                        items.forEach(function(it, idx) {
                            if (idx > 0) {
                                var dot = document.createElement('span');
                                dot.className = 'patch-sep';
                                dot.textContent = ' • ';
                                detailsDiv.appendChild(dot);
                            }
                            detailsDiv.appendChild(it);
                        });

                        row.appendChild(detailsDiv);
                        body.appendChild(row);
                    });
                } else {
                    var rawPre = document.createElement('pre');
                    rawPre.className = 'discuss-beatmap-raw';
                    rawPre.textContent = JSON.stringify(payload, null, 2);
                    body.appendChild(rawPre);
                }
            } else {
                var guidanceText = (payload && payload.guidance) ? payload.guidance : 'Restructure scene beats';
                var guidanceWrap = document.createElement('div');
                guidanceWrap.className = 'discuss-beatmap-guidance';

                var gLabel = document.createElement('div');
                gLabel.className = 'guidance-label';
                gLabel.textContent = 'Author Guidance:';
                guidanceWrap.appendChild(gLabel);

                var gQuote = document.createElement('div');
                gQuote.className = 'guidance-quote';
                gQuote.textContent = '“' + guidanceText + '”';
                guidanceWrap.appendChild(gQuote);

                body.appendChild(guidanceWrap);
            }
            card.appendChild(body);

            // Footer
            var footer = document.createElement('div');
            footer.className = 'discuss-beatmap-footer';

            var progressPanel = document.createElement('div');
            progressPanel.className = 'discuss-beatmap-progress-panel';
            progressPanel.style.display = 'none';

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'discuss-beatmap-btn';
            var originalBtnText = isPatch ? 'Apply to Beat Map' : 'Recreate Beat Map';
            btn.textContent = originalBtnText;

            var statusSpan = document.createElement('span');
            statusSpan.className = 'discuss-beatmap-status';

            function getProposalStageInfo(elapsedSec, status, agent) {
                var agentName = (agent === 'codex' ? 'Codex CLI' : (agent === 'agy' ? 'Agy CLI' : 'Claude CLI'));
                var wordCount = (status && status.word_count) ? status.word_count : 0;
                var totalParas = (status && status.total_paragraphs) ? status.total_paragraphs : 0;
                var draftLen = (status && typeof status.draft_length === 'number') ? status.draft_length : 0;
                var tokensStarted = !!(status && status.tokens_started);

                var countText = '';
                if (wordCount > 0 && totalParas > 0) {
                    countText = wordCount.toLocaleString() + ' words • ' + totalParas + ' paragraphs';
                } else if (wordCount > 0) {
                    countText = wordCount.toLocaleString() + ' words';
                }

                if (tokensStarted || draftLen > 0) {
                    var streamProgress = Math.min(45, Math.floor(draftLen / 65));
                    var percent = Math.min(95, 50 + streamProgress);
                    var sub = draftLen > 0
                        ? draftLen.toLocaleString() + ' chars streamed' + (countText ? ' • ' + countText : '')
                        : (countText || 'Streaming beat structure');

                    return {
                        percent: percent,
                        stage: 'Extracting narrative beats & dialogue moments…',
                        subtext: sub
                    };
                }

                if (elapsedSec <= 4) {
                    var p = Math.min(20, Math.floor(5 + elapsedSec * 3.5));
                    return {
                        percent: p,
                        stage: 'Initializing ' + agentName + '…',
                        subtext: countText || 'Loading scene context'
                    };
                } else if (elapsedSec <= 15) {
                    var p2 = Math.min(38, Math.floor(20 + (elapsedSec - 4) * 1.6));
                    return {
                        percent: p2,
                        stage: agentName + ' reading scene & evaluating dramatic tension…',
                        subtext: countText ? 'Analyzing ' + countText : 'Analyzing scene narrative arc'
                    };
                } else if (elapsedSec <= 30) {
                    var p3 = Math.min(46, Math.floor(38 + (elapsedSec - 15) * 0.5));
                    return {
                        percent: p3,
                        stage: agentName + ' synthesizing beats, pacing & dialogue…',
                        subtext: countText ? 'Synthesizing ' + countText : 'Synthesizing beat progression'
                    };
                } else {
                    var p4 = Math.min(49, Math.floor(46 + (elapsedSec - 30) * 0.08));
                    var m = Math.floor(elapsedSec / 60);
                    var s = elapsedSec % 60;
                    var timeStr = m + ':' + (s < 10 ? '0' : '') + s;
                    return {
                        percent: p4,
                        stage: agentName + ' reasoning across narrative arc…',
                        subtext: 'Deep scene analysis in progress (' + timeStr + ' elapsed)'
                    };
                }
            }

            btn.onclick = function() {
                var targetPath = boundScenePath;
                if (!targetPath) {
                    btn.disabled = false;
                    btn.textContent = originalBtnText;
                    statusSpan.textContent = 'Error: Cannot resolve originating scene path for proposal';
                    statusSpan.classList.add('error');
                    return;
                }

                btn.disabled = true;
                statusSpan.textContent = '';
                statusSpan.className = 'discuss-beatmap-status';

                var startTime = Date.now();
                var generationStatus = null;
                var targetAgent = (payload && payload.agent) || 'claude';

                function formatClock(sec) {
                    var s = Math.max(0, Math.floor(sec || 0));
                    var m = Math.floor(s / 60);
                    var rem = s % 60;
                    return m + ':' + (rem < 10 ? '0' : '') + rem;
                }

                function formatDurationBadge(sec) {
                    var s = Math.max(1, Math.round(sec || 0));
                    if (s >= 60) {
                        return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
                    }
                    return s + 's';
                }

                function updateProgressView() {
                    var elapsedSec = Math.max(0, Math.floor((Date.now() - startTime) / 1000));
                    var clockStr = formatClock(elapsedSec);
                    var stageInfo = getProposalStageInfo(elapsedSec, generationStatus, targetAgent);

                    btn.innerHTML = '<span class="beatmap-spinner"></span> ' +
                        (isPatch ? 'Applying… ' : 'Generating… ') +
                        '<span class="discuss-beatmap-btn-timer">' + clockStr + '</span>';

                    progressPanel.innerHTML =
                        '<div class="beatmap-progress-bar-wrap" style="height:5px; margin-bottom:6px;">' +
                        '<div class="beatmap-progress-bar-fill" style="width:' + stageInfo.percent + '%;"></div>' +
                        '</div>' +
                        '<div class="beatmap-progress-label">' +
                        '<span class="discuss-beatmap-stage">' + stageInfo.stage + '</span>' +
                        '<span class="discuss-beatmap-clock">' + clockStr + '</span>' +
                        '</div>' +
                        '<div class="beatmap-progress-subtext">' +
                        '<span class="beatmap-pulse-dot"></span> <span class="discuss-beatmap-subtext-msg">' + stageInfo.subtext + '</span>' +
                        '</div>';
                }

                progressPanel.style.display = 'block';
                updateProgressView();

                var ticker = setInterval(updateProgressView, 1000);

                var poller = setInterval(function() {
                    fetch('/api/scene/beatmap/status?path=' + encodeURIComponent(targetPath))
                        .then(function(res) { return res.json(); })
                        .then(function(d) {
                            if (d && d.ok && d.status) {
                                generationStatus = d.status;
                                if (d.status.agent) targetAgent = d.status.agent;
                                updateProgressView();
                            }
                        })
                        .catch(function() {});
                }, 1500);

                window.dispatchEvent(new CustomEvent('beatmap-generating', {
                    detail: { scene_path: targetPath, agent: targetAgent }
                }));

                var url = (isPatch || (payload && payload.replace)) ? '/api/scene/beatmap/patch' : '/api/scene/beatmap/generate';
                var reqPayload = Object.assign({}, payload, {
                    path: targetPath,
                    scene_path: targetPath,
                });
                if (boundRevision && !reqPayload.expected_revision && !reqPayload.target_revision) {
                    reqPayload.expected_revision = boundRevision;
                }
                if (boundMapVersion && !reqPayload.expected_map_version && !reqPayload.target_map_version) {
                    reqPayload.expected_map_version = boundMapVersion;
                }

                fetch(url, {
                    method: 'POST',
                    headers: (typeof pvHeaders === 'function') ? pvHeaders() : { 'Content-Type': 'application/json' },
                    body: JSON.stringify(reqPayload),
                })
                .then(function(res) {
                    if (!res.ok) {
                        return res.json().then(function(errData) {
                            throw new Error(errData.error || ('HTTP ' + res.status));
                        }).catch(function(e) {
                            throw new Error(e.message || ('HTTP ' + res.status));
                        });
                    }
                    return res.json();
                })
                .then(function(data) {
                    clearInterval(ticker);
                    clearInterval(poller);
                    progressPanel.style.display = 'none';

                    if (!data.ok) {
                        throw new Error(data.error || 'Server error');
                    }
                    btn.style.display = 'none';
                    var totalSec = Math.max(1, Math.round((Date.now() - startTime) / 1000));
                    var durationText = formatDurationBadge(totalSec);
                    statusSpan.textContent = (isPatch ? '✓ Applied to Beat Map in ' : '✓ Beat Map Recreated in ') + durationText;
                    statusSpan.classList.add('success');

                    // Only update the active scene's beatmap view if the proposal was applied to the currently open scene
                    var currentScene = (typeof _beatMapCurrentScene !== 'undefined') ? _beatMapCurrentScene : (typeof paths !== 'undefined' && curIdx >= 0 ? paths[curIdx] : null);
                    if (currentScene === targetPath) {
                        if (typeof window.updateBeatMapState === 'function') {
                            window.updateBeatMapState(data.beatmap);
                        }
                    }
                    window.dispatchEvent(new CustomEvent('beatmap-updated', { detail: data }));
                })
                .catch(function(err) {
                    clearInterval(ticker);
                    clearInterval(poller);
                    progressPanel.style.display = 'none';

                    btn.disabled = false;
                    btn.textContent = originalBtnText;
                    statusSpan.textContent = 'Error: ' + (err.message || String(err));
                    statusSpan.classList.add('error');

                    window.dispatchEvent(new CustomEvent('beatmap-generation-failed', {
                        detail: { scene_path: targetPath, error: err.message || String(err) }
                    }));
                });
            };

            card.appendChild(progressPanel);
            footer.appendChild(btn);
            footer.appendChild(statusSpan);
            card.appendChild(footer);

            parent.appendChild(card);
        }

        function appendMarkdownTokens(parent, tokens, ctx) {
            (tokens || []).forEach(function(token, tokenIndex) {
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
                else if (token.type === 'heading') {
                    if (ctx) ctx.lastLocalTarget = ctx.lastQuoteTarget = ctx.lastCompareQuote = null;
                    node = document.createElement('h' + Math.min(6, Math.max(1, token.depth || 3)));
                }
                else if (token.type === 'strong') node = document.createElement('strong');
                else if (token.type === 'em') node = document.createElement('em');
                else if (token.type === 'codespan') { node = document.createElement('code'); node.textContent = decodeMarkdownText(token.text || ''); }
                else if (token.type === 'code') {
                    if (token.lang === 'proseview:beatmap-patch' || token.lang === 'proseview:beatmap-recreate') {
                        renderDiscussBeatmapCard(token.lang, token.text, parent, ctx);
                        return;
                    }
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
                    if (localTarget) {
                        var textClean = String(token.text || '').replace(/[*_`~]/g, '');
                        if (!localTarget.endLine) {
                            var labelRange = textClean.match(/\b(?:lines?|l)?\s*(\d+)\s*(?:[-–—]|to)\s*(?:l)?(\d+)\b/i);
                            if (labelRange) {
                                var rStart = parseInt(labelRange[1], 10);
                                var rEnd = parseInt(labelRange[2], 10);
                                if (Number.isInteger(rStart) && Number.isInteger(rEnd) && rEnd >= rStart) {
                                    if (!localTarget.line || localTarget.line === rStart) {
                                        localTarget.line = rStart;
                                        localTarget.endLine = rEnd;
                                    }
                                }
                            }
                        }
                        if (!localTarget.line) {
                            var singleMatch = textClean.match(/\b(?:lines?|l)\s*(\d+)\b/i);
                            if (singleMatch) {
                                var sLine = parseInt(singleMatch[1], 10);
                                if (Number.isInteger(sLine) && sLine >= 1) {
                                    localTarget.line = sLine;
                                }
                            }
                        }
                        if (ctx) ctx.lastLocalTarget = Object.assign({}, localTarget);
                    }
                    var href = localTarget ? null : safeDiscussUrl(token.href || '');
                    node = (localTarget || href) ? document.createElement('a') : document.createElement('span');
                    if (localTarget) {
                        node.href = '#/' + localTarget.kind + '/' + encodeURIComponent(localTarget.path);
                        node.dataset.prosviewKind = localTarget.kind;
                        node.dataset.prosviewPath = localTarget.path;
                        if (localTarget.line) {
                            node.dataset.prosviewLine = String(localTarget.line);
                            node.classList.add('discuss-line-ref');
                        }
                        if (localTarget.endLine) node.dataset.prosviewEndLine = String(localTarget.endLine);
                        var titleRange = localTarget.kind === 'scene' && localTarget.line
                            ? (localTarget.line + (localTarget.endLine && localTarget.endLine !== localTarget.line ? '–' + localTarget.endLine : ''))
                            : null;
                        node.title = 'Open in Prosview' + (titleRange ? (localTarget.endLine && localTarget.endLine !== localTarget.line ? ' at lines ' : ' at line ') + titleRange : '');
                        node.onclick = function(event) {
                            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                            event.preventDefault();
                            try { node.blur(); } catch(e) {}
                            openProsviewFileReference(localTarget);
                        };
                        node.onmouseup = function() {
                            try { node.blur(); } catch(e) {}
                        };
                    } else if (href) {
                        node.href = href;
                        node.rel = 'noopener noreferrer';
                        if (node.protocol !== 'mailto:') node.target = '_blank';
                    }
                } else if (token.type === 'br') node = document.createElement('br');
                else if (token.type === 'hr') {
                    if (ctx) ctx.lastLocalTarget = ctx.lastQuoteTarget = null;
                    node = document.createElement('hr');
                }
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
                if (token.type === 'blockquote') {
                    var prevSibling = parent.lastElementChild;
                    var next = (tokens || []).slice(tokenIndex + 1).find(function(item) { return item.type !== 'space'; });
                    var citationParts = next && next.type === 'paragraph' ? (next.tokens || []) : [];
                    var citationLinks = citationParts.filter(function(item) { return item.type === 'link'; });
                    var citationOnly = citationLinks.length === 1 && citationParts.every(function(item) {
                        return item.type === 'link' || (item.type === 'text' && /^[\s—–().-]*$/.test(item.text || ''));
                    });
                    // A Keep item puts its citation first in the reason below the
                    // quote: "[scene.md · Line 176](…). Nima states …".
                    var leading = citationParts.findIndex(function(item) {
                        return !(item.type === 'text' && /^[\s—–(]*$/.test(item.text || ''));
                    });
                    var afterLead = leading >= 0 ? citationParts[leading + 1] : null;
                    var leadingCitation = leading >= 0 && citationParts[leading].type === 'link'
                        && /#L\d+/i.test(citationParts[leading].href || '')
                        && (!afterLead || (afterLead.type === 'text' && /^\s*[.,;:)—–-]/.test(afterLead.text || '')));
                    var followingCitation = null;
                    if (citationOnly || leadingCitation) {
                        var citationNode = document.createElement('p');
                        appendMarkdownTokens(citationNode, citationOnly ? citationParts : [citationParts[leading]], Object.assign({}, ctx));
                        followingCitation = detectProsviewTargetInPrevEl(citationNode, ctx.scenePath);
                    }
                    decorateDiscussBlockquote(node, ctx, prevSibling, followingCitation);
                    if (ctx.agentOutput) {
                        var quote = node;
                        var quoteWrap = withCopyButton(quote, function() { return extractDiscussQuoteText(quote); });
                        decorateDiscussQuoteActions(quoteWrap, quote, ctx);
                        parent.appendChild(quoteWrap);
                        return;
                    }
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
            button.onclick = function(event) {
                if (event && event.stopPropagation) event.stopPropagation();
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
            button.onmousedown = function(event) {
                if (event && event.stopPropagation) event.stopPropagation();
            };
            container.appendChild(button);
        }

        function renderSafeMarkdown(parent, text, ctx) {
            try { appendMarkdownTokens(parent, marked.lexer(String(text || ''), {gfm: true}), ctx || {}); }
            catch(e) { parent.textContent = String(text || ''); }
        }

        function renderDiscussMarkdown(parent, text, scenePath) {
            // Agent output: relative paths have no document to resolve against,
            // and remote ones obey images.remote_in_agent_output.
            scenePath = scenePath || _discussCurrentScenePath();
            var linked = typeof _groupLinkLines === 'function' ? _groupLinkLines(text, scenePath) : text;
            // Review labels such as **Type:** and **Lane:** come on consecutive
            // lines; Markdown would join them into one run-on line.
            linked = String(linked || '').replace(/([^\n])\n(?=[ \t]*\*\*[A-Z][^*\n]{0,40}:)/g, '$1  \n');
            renderSafeMarkdown(parent, linked, {agentOutput: true, scenePath: scenePath});
        }

        function linkDiscussCraftLanes(parent, lens) {
            if (!lens) return;
            var names = lens.lanes.map(discussCraftLaneName);
            var pattern = new RegExp('\\b(' + names.map(function(name) {
                return name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            }).sort(function(a, b) { return b.length - a.length; }).join('|') + ')\\b', 'g');
            parent.querySelectorAll('p, li').forEach(function(paragraph) {
                if (!/^Lanes?:\s/.test(paragraph.textContent.trim())) return;
                var walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
                var nodes = [];
                while (walker.nextNode()) {
                    if (!walker.currentNode.parentElement.closest('a, button, code, pre')) nodes.push(walker.currentNode);
                }
                nodes.forEach(function(node) {
                    var text = node.textContent;
                    pattern.lastIndex = 0;
                    var matches = Array.from(text.matchAll(pattern));
                    if (!matches.length) return;
                    var fragment = document.createDocumentFragment();
                    var start = 0;
                    matches.forEach(function(match) {
                        fragment.appendChild(document.createTextNode(text.slice(start, match.index)));
                        var name = match[0];
                        var lane = lens.lanes[names.indexOf(name)];
                        var button = document.createElement('button');
                        button.type = 'button';
                        button.className = 'discuss-craft-lane-link';
                        button.textContent = name;
                        button.setAttribute('aria-label', 'Read about ' + name + ' in ' + lens.book);
                        button.onclick = function() { openDiscussCraftInfoDialog(lens.id, lane.id); };
                        fragment.appendChild(button);
                        start = match.index + name.length;
                    });
                    fragment.appendChild(document.createTextNode(text.slice(start)));
                    node.replaceWith(fragment);
                });
            });
        }

        function renderDiscussCraftRequest(parent, text, key, expanded) {
            var raw = String(text || '');
            var divider = '\n\nCraft review instructions:\n';
            var summaryLabel = 'Review instructions';
            if (raw.startsWith('Update frontmatter · ')) {
                divider = '\n\nUpdate instructions:\n';
                summaryLabel = 'Update instructions';
            } else if (raw.startsWith('Quick critique · ') || raw.startsWith('Deepen & layer · ') || raw.startsWith('Comedy review · ')) {
                divider = '\n\nScene review instructions:\n';
            } else if (!raw.startsWith('Craft review · ')) {
                return false;
            }
            var split = raw.lastIndexOf(divider);
            if (split < 0) return false;
            parent.classList.add('discuss-craft-request');
            var receipt = elementWith('discuss-craft-request-summary');
            renderDiscussMarkdown(receipt, raw.slice(0, split));
            var details = document.createElement('details');
            details.className = 'discuss-craft-prompt';
            details.dataset.messageKey = key;
            details.open = expanded;
            var summary = document.createElement('summary');
            summary.textContent = summaryLabel;
            var body = elementWith('discuss-craft-prompt-body');
            renderDiscussMarkdown(body, raw.slice(split + divider.length));
            details.append(summary, body);
            parent.append(receipt, details);
            return true;
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
                if (DISCUSS_REVIEW_MODES.some(function(mode) { return mode.id === row.id; })) {
                    group.appendChild(discussReviewCard(row, live));
                    return;
                }
                var card = document.createElement('button');
                card.type = 'button'; card.className = 'discuss-story-action';
                card.appendChild(elementWith('discuss-story-action-title', live.label || row.label));
                card.appendChild(elementWith('discuss-story-action-copy', live.description || row.copy));
                card.onclick = function() { run(row.id); };
                group.appendChild(card);
            });
            return group;
        }

        var _discussLastLogSignature = '';

        function _discussLogActivitySignature(snapshot) {
            if (!snapshot) return '';
            var msgs = snapshot.messages || [];
            var last = msgs.length ? msgs[msgs.length - 1] : null;
            return [
                msgs.length,
                last ? (String(last.text || '').length) : 0,
                Object.keys(snapshot.activities || {}).length,
                (snapshot.tasks || []).length,
                snapshot.active_turn_id || ''
            ].join(':');
        }

        function discussIsAtBottom(log) {
            return log.scrollHeight - log.scrollTop - log.clientHeight <= 1;
        }

        function captureDiscussScroll(log) {
            return {
                atBottom: discussIsAtBottom(log),
                scrollTop: log.scrollTop,
                signature: _discussLogActivitySignature(_discussSnapshot)
            };
        }

        function restoreDiscussScroll(log, state) {
            var previousBehavior = log.style.scrollBehavior;
            log.style.scrollBehavior = 'auto';
            log.scrollTop = state.atBottom ? log.scrollHeight : state.scrollTop;
            requestAnimationFrame(function() { log.style.scrollBehavior = previousBehavior; });
            var btn = document.getElementById('discussNewActivity');
            var currentSig = _discussLogActivitySignature(_discussSnapshot);
            var hasNewActivity = !!_discussLastLogSignature && currentSig !== _discussLastLogSignature;
            _discussLastLogSignature = currentSig;
            // Setting up Craft review or clicking UI chips/tabs while scrolled up
            // is not "New activity" — only reveal the pill when content grew
            // off-screen outside setup.
            if (state.atBottom || _discussCraftState.active) {
                btn.hidden = true;
            } else if (hasNewActivity) {
                btn.hidden = false;
            }
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
                    document.getElementById('discussInput').value = String(asked.text || '').split(/\n\nSelected passage(?:\s*\([^)\n]*\))?:\n/)[0];
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
            } else if (/Agy/.test(label)) {
                how = 'Install Antigravity CLI (agy) and sign in once in a terminal, then reopen this tab:';
                steps = ['agy'];
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
            syncDiscussGroupFork();
            // The agent has stopped, so the file has stopped moving: the first
            // moment there is something settled to review. Keyed on the turn
            // that finished so it is asked exactly once per turn.
            var finished = (snapshot.last_turn || {}).turn_id || '';
            if (snapshot.active_turn_id && _discussSyncingFrontmatter) {
                _discussSyncingFrontmatter.seenActive = true;
            }
            if (!snapshot.active_turn_id && finished && finished !== _discussReviewedTurn) {
                _discussReviewedTurn = finished;
                refreshDiscussReview({dropEditedSelection: true});
            }
            if (!snapshot.active_turn_id && _discussSyncingFrontmatter
                && (_discussSyncingFrontmatter.seenActive || (finished && finished !== _discussSyncingFrontmatter.prevTurnId))) {
                _clearDiscussFrontmatterSync();
            }
            setDiscussConnection(snapshot.connection || 'Live', snapshot.unavailable_reason || '');
            var log = document.getElementById('discussLog');
            var continuityTools = log.querySelector('.discuss-continuity-tools');
            var continuityToolsOpen = !!(continuityTools && continuityTools.open);
            var craftCustomEl = log.querySelector('.discuss-craft-custom-list');
            var craftCustomScroll = craftCustomEl ? craftCustomEl.scrollTop : 0;
            var craftContextEl = document.getElementById('discussCraftContext');
            var craftContextSelection = craftContextEl && document.activeElement === craftContextEl
                ? [craftContextEl.selectionStart, craftContextEl.selectionEnd, craftContextEl.scrollTop] : null;
            var craftFocusValue = (craftCustomEl && document.activeElement && craftCustomEl.contains(document.activeElement) && document.activeElement.type === 'checkbox')
                ? document.activeElement.value : '';
            var reviewFocusId = document.activeElement && document.activeElement.closest('.discuss-craft-setup, .discuss-review-card, .discuss-review-heading') ? document.activeElement.id : '';
            var scrollState = captureDiscussScroll(log);
            var expandedCraftPrompts = new Set(Array.from(log.querySelectorAll('.discuss-craft-prompt[open]')).map(function(el) {
                return el.dataset.messageKey;
            }));
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
            } else if (hasNoDiscussActivity && !_discussCraftState.active) {
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
                    // The scene on screen comes first. The repository scans are
                    // the rarer, heavier work and no longer lead.
                    var emptyDocument = discussTurnDocument();
                    if (emptyDocument && emptyDocument.kind === 'scene') {
                        empty.classList.add('discuss-review-landing');
                        appendDiscussReviewCards(empty);
                    } else {
                        title.textContent = 'What do you want to examine?';
                        empty.append(title, document.createTextNode('Ask about what you are reading, or run a pass over it.'));
                    }
                    var continuity = document.createElement('details');
                    continuity.className = 'discuss-continuity-tools';
                    continuity.open = continuityToolsOpen;
                    var continuitySummary = document.createElement('summary');
                    continuitySummary.textContent = 'Continuity tools';
                    continuity.appendChild(continuitySummary);
                    continuity.appendChild(elementWith('discuss-continuity-help',
                        'Check story facts, or find passages affected by a change.'));
                    continuity.appendChild(discussPassGroup(DISCUSS_REPOSITORY_PASSES, startDiscussRepositoryAction));
                    empty.appendChild(continuity);
                }
                log.appendChild(empty);
            }
            appendUnassociatedNotices();
            groupDiscussTasks(snapshot.tasks || []).forEach(function(group) {
                log.appendChild(renderDiscussTask(group.latest, group.previous));
                appendNoticesForRequest(group.latest.client_request_id);
            });
            var messages = snapshot.messages || [];
            var lastAssistantIndexByTurn = {};
            messages.forEach(function(m, idx) {
                if (m.role === 'assistant' && m.turn_id) {
                    lastAssistantIndexByTurn[m.turn_id] = idx;
                }
            });
            var resultCraftLens = null;
            messages.forEach(function(message, mIdx) {
                var isUser = message.role === 'user';
                if (isUser) {
                    var skillName = (message.context_sent || {}).skill_name;
                    resultCraftLens = DISCUSS_CRAFT_LENSES.concat(DISCUSS_REVIEW_GUIDES).find(function(lens) {
                        return lens.id === skillName || String(message.text || '').startsWith((lens.id.indexOf('craft_') === 0 ? 'Craft review · ' : '') + lens.label + ' ·');
                    }) || null;
                }
                var isThought = false;
                // A reply the agent's safeguards cut short is part of the answer,
                // even though a continuation follows it in the same turn.
                var wasStopped = !isUser && message.stopped === 'safeguards';
                if (!isUser && !wasStopped) {
                    if (message.phase === 'thought' || message.phase === 'commentary') {
                        isThought = true;
                    } else if (message.turn_id) {
                        var isLastInTurn = lastAssistantIndexByTurn[message.turn_id] === mIdx;
                        var isTurnActive = snapshot.active_turn_id && snapshot.active_turn_id === message.turn_id;
                        if (isTurnActive) {
                            var turnActivities = discussTurnActivities(snapshot, message.turn_id);
                            isThought = !isLastInTurn || turnActivities.length > 0;
                        } else {
                            isThought = !isLastInTurn;
                        }
                    }
                }
                var wrap = elementWith('discuss-message chat-message-card ' + (isUser ? 'user' : ('assistant' + (isThought ? ' is-thought' : ''))));
                var head = elementWith('discuss-message-label chat-message-header');
                var agentName = discussAgentLabel();
                var label = elementWith('chat-message-name', isUser ? 'Me' : (isThought ? (agentName + ' \u00b7 Thought') : agentName));
                head.appendChild(label);
                var mTime = message.created_at || (snapshot.conversation && snapshot.conversation.created_at ? (snapshot.conversation.created_at + mIdx * 60) : 0);
                var meta = _buildMessageMeta(mTime, message.duration_ms);
                if (meta) head.appendChild(meta);
                if (isUser && message.context_sent) {
                    var ctxBtn = document.createElement('button');
                    ctxBtn.type = 'button';
                    ctxBtn.className = 'discuss-context-inspect-btn';
                    ctxBtn.textContent = 'Context';
                    ctxBtn.title = 'Inspect exact prompt, instructions, and frontmatter sent on this turn';
                    ctxBtn.onclick = function() {
                        openDiscussContextSentDialog(message.context_sent, 'Discuss · ' + discussAgentLabel());
                    };
                    head.appendChild(ctxBtn);
                }
                wrap.appendChild(head);
                var messageKey = String(message.client_request_id || message.id || mIdx);
                if (!isUser || !renderDiscussCraftRequest(wrap, message.text, messageKey, expandedCraftPrompts.has(messageKey))) {
                    renderDiscussMarkdown(wrap, message.text);
                }
                if (wasStopped) {
                    wrap.classList.add('is-stopped');
                    var stoppedNote = elementWith('discuss-stopped-note',
                        agentName + '’s safeguards stopped this reply partway through. '
                        + 'The next reply continues without the withheld part.');
                    stoppedNote.setAttribute('role', 'note');
                    wrap.appendChild(stoppedNote);
                }
                if (!isUser && !isThought) linkDiscussCraftLanes(wrap, resultCraftLens);
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
            if (_discussCraftState.active) {
                var craftSetup = elementWith('discuss-empty discuss-review-container');
                renderDiscussCraftSetup(craftSetup);
                log.appendChild(craftSetup);
                if (craftContextSelection) {
                    var restoredContext = document.getElementById('discussCraftContext');
                    restoredContext.focus({preventScroll: true});
                    restoredContext.setSelectionRange(craftContextSelection[0], craftContextSelection[1]);
                    restoredContext.scrollTop = craftContextSelection[2];
                }
                var nextCustomEl = log.querySelector('.discuss-craft-custom-list');
                if (nextCustomEl) {
                    nextCustomEl.scrollTop = craftCustomScroll;
                    if (craftFocusValue) {
                        Array.prototype.some.call(nextCustomEl.querySelectorAll('input[type="checkbox"]'), function(cb) {
                            if (cb.value !== craftFocusValue) return false;
                            cb.focus({preventScroll: true});
                            return true;
                        });
                    }
                }
            } else if (_discussCraftState.cardsOpen && !hasNoDiscussActivity) {
                renderDiscussReviewCardPicker(log);
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
            syncDiscussSendEmpty();
            renderBtwSplit();
            restoreDiscussScroll(log, scrollState);
            if (reviewFocusId) {
                var reviewControl = document.getElementById(reviewFocusId);
                if (reviewControl) reviewControl.focus({preventScroll: true});
            }
            renderDiscussReviewFocusPopover();
            positionDiscussReviewInfo();
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
                            resetChatHistoryCursor(_discussAgent);
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
var _discussHideWrapOnly = false;

function applyDiscussDiffWrapVisibility() {
    var contentDiv = document.getElementById('discussDiffModalContent');
    var btn = document.getElementById('discussDiffHideWrapBtn');
    if (btn) {
        btn.setAttribute('aria-pressed', _discussHideWrapOnly ? 'true' : 'false');
        var countLabel = btn.dataset.wrapCount ? ' (' + btn.dataset.wrapCount + ')' : '';
        btn.textContent = (_discussHideWrapOnly ? 'Show formatting' : 'Hide formatting') + countLabel;
    }
    if (!contentDiv) return;
    var rows = contentDiv.querySelectorAll('.discuss-review-block');
    var wrapRows = 0;
    var visibleRows = 0;
    for (var i = 0; i < rows.length; i++) {
        var isWrap = rows[i].dataset.whitespaceOnly === 'true';
        if (isWrap) {
            wrapRows++;
            rows[i].hidden = _discussHideWrapOnly;
        } else {
            rows[i].hidden = false;
        }
        if (!rows[i].hidden) visibleRows++;
    }
    var emptyNote = document.getElementById('discussDiffAllWrapHiddenNote');
    if (_discussHideWrapOnly && wrapRows > 0 && visibleRows === 0) {
        if (!emptyNote) {
            emptyNote = document.createElement('div');
            emptyNote.id = 'discussDiffAllWrapHiddenNote';
            emptyNote.className = 'discuss-diff-wrap-empty';
            var msg = document.createElement('span');
            msg.textContent = 'All ' + wrapRows + (wrapRows === 1 ? ' change is' : ' changes are') + ' line wrapping or spacing only — words are unchanged.';
            var showBtn = document.createElement('button');
            showBtn.type = 'button';
            showBtn.className = 'discuss-wrap-show-btn';
            showBtn.textContent = 'Show formatting';
            showBtn.onclick = function() {
                if (_discussHideWrapOnly) toggleDiscussDiffHideWrapping();
            };
            emptyNote.appendChild(msg);
            emptyNote.appendChild(showBtn);
            contentDiv.appendChild(emptyNote);
        }
        emptyNote.hidden = false;
    } else if (emptyNote) {
        emptyNote.hidden = true;
    }
}

function syncDiscussDiffWrapToggle(blocks) {
    var btn = document.getElementById('discussDiffHideWrapBtn');
    if (!btn) return;
    var wrapCount = (blocks || []).filter(function(b) { return !!b.whitespace_only; }).length;
    if (wrapCount > 0) {
        btn.hidden = false;
        btn.dataset.wrapCount = String(wrapCount);
        btn.textContent = (_discussHideWrapOnly ? 'Show formatting' : 'Hide formatting') + ' (' + wrapCount + ')';
        btn.setAttribute('aria-pressed', _discussHideWrapOnly ? 'true' : 'false');
    } else {
        btn.hidden = true;
        delete btn.dataset.wrapCount;
    }
}

function toggleDiscussDiffHideWrapping() {
    _discussHideWrapOnly = !_discussHideWrapOnly;
    applyDiscussDiffWrapVisibility();
}

function openDiscussReviewModal(path, review) {
    _currentDiscussQuoteComparison = null;
    document.getElementById('discussDiffModalOverlay').classList.remove('is-quote-comparison');
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

function openDiscussDiffModal(diffString, options) {
    _currentDiscussQuoteComparison = options && options.comparison || null;
    document.getElementById('discussDiffModalOverlay').classList.toggle('is-quote-comparison', !!_currentDiscussQuoteComparison);
    _currentDiscussReviewContext = null;
    _discussReturnFocus = document.activeElement;
    document.getElementById('discussDiffModalTitle').textContent = _currentDiscussQuoteComparison ? 'Compare passage' : 'Review Changes';
    _currentDiscussReviewPath = null;
    _currentDiscussDiffString = diffString;
    syncDiscussDiffWrapToggle([]);
    document.getElementById('discussDiffModalNote').textContent = _currentDiscussQuoteComparison ? 'Preview · loading current passage…' : 'Review the changes the agent made.';
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
    var comparison = _currentDiscussQuoteComparison;
    var overlay = document.getElementById('discussDiffModalOverlay');
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    _discussDiffLoadToken++;
    _currentDiscussDiffString = null;
    _currentDiscussReviewPath = null;
    _currentDiscussReviewContext = null;
    _currentDiscussQuoteComparison = null;
    // Each surface reads back the same choices made in the expanded view.
    if (review) review.render(path);
    else if (!comparison && _discussSnapshot) renderDiscussSnapshot();
    if (_discussReturnFocus && _discussReturnFocus.focus && _discussReturnFocus.isConnected) {
        _discussReturnFocus.focus();
    }
}

document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        var overlay = document.getElementById('discussDiffModalOverlay');
        if (overlay && !overlay.hidden) {
            closeDiscussDiffModal();
            event.stopImmediatePropagation();
            event.preventDefault();
        }
    }
}, true);

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
    if (_currentDiscussQuoteComparison) { loadDiscussQuoteComparison(mode, token); return; }
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
                    syncDiscussDiffWrapToggle([]);
                    contentDiv.appendChild(elementWith('discuss-diff-status', 'This file has no changes left to review.'));
                    return;
                }
                syncDiscussDiffWrapToggle(fresh.blocks || []);
                (fresh.blocks || []).forEach(function(block) {
                    contentDiv.appendChild(renderDiscussReviewBlock(fresh, block, null, review).row);
                });
                applyDiscussDiffWrapVisibility();
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
                    if (document.documentElement.dataset.view === 'scene'
                        && typeof curIdx === 'number' && paths[curIdx]
                        && typeof refreshContent === 'function'
                        && !(_pmEditMode && _pmDirty)
                        && _discussReview.some(function(file) {
                            var target = prosviewTargetForRepositoryPath(file.path);
                            return target && target.kind === 'scene' && target.path === paths[curIdx];
                        })) {
                        refreshContent([paths[curIdx]]);
                    }
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
            if (!_discussPendingAction) _discussIncludeCurrentDocument = false;
            if (!_discussIncludeCurrentDocument && !_discussPendingAction && !_discussRepositoryAction) _discussDraftDocument = null;
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
            if (block.note) {
                var badge = elementWith('diff-block-badge' + (block.whitespace_only ? '' : ' is-reflow'), block.note);
                label.appendChild(badge);
            }
            label.appendChild(state);
            row.appendChild(label);

            var table = elementWith('discuss-review-table');
            table.innerHTML = block.html;

            if (block.whitespace_only) {
                row.dataset.whitespaceOnly = 'true';
                row.classList.add('discuss-review-block-wrap-only');
            }

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
            var blocks = file.blocks || [];
            var wrapBlocks = blocks.filter(function(block) { return !!block.whitespace_only; });
            if (wrapBlocks.length) {
                var allSpacesOnly = wrapBlocks.every(function(block) { return block.whitespace_kind === 'spaces'; });
                var wrapPillText = wrapBlocks.length === blocks.length
                    ? (allSpacesOnly ? 'Spaces only' : 'Wrapping only')
                    : (wrapBlocks.length + ' wrapping only');
                head.appendChild(elementWith('discuss-review-wrap-pill', wrapPillText));
            }
            var count = elementWith('discuss-review-count');
            head.appendChild(count);
            card.appendChild(head);

            // The changes are already in the file. The card says so, and its
            // one decision is what, if anything, to undo. Ticks are made in
            // Expand view; the card reads them back.
            var keep = discussReviewKeep(file.path, review);
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
                    var activeTarget = prosviewTargetForRepositoryPath(file.path);
                    if (activeTarget && activeTarget.kind === 'scene'
                        && document.documentElement.dataset.view === 'scene'
                        && typeof curIdx === 'number' && paths[curIdx] === activeTarget.path
                        && typeof refreshContent === 'function'
                        && !(_pmEditMode && _pmDirty)) {
                        refreshContent([activeTarget.path]);
                    }
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
                    _discussIncludeCurrentDocument = false;
                    if (!_discussRepositoryAction) _discussDraftDocument = null;
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
                rephrase: 'Rephrase', tighten: 'Tighten', clarify: 'Clarify', layer_subtext: 'Layer subtext', sensory_detail: 'Add sensory detail',
                show_moment: 'Show the moment', custom_rewrite: 'Custom rewrite', update_frontmatter: 'Update frontmatter',
                quick_critique: 'Quick critique', deepen_and_layer: 'Deepen & layer',
                voice_character: 'Voice and character', pacing_tension: 'Pacing and tension', clarity_flow: 'Clarity and flow', continuity: 'Continuity check',
                next_beats: 'Next beats', craft_mckee: 'McKee · Story', craft_cron: 'Cron · Story Genius',
                craft_coyne: 'Coyne · The Story Grid', craft_snyder: 'Snyder · Save the Cat!',
                craft_king: 'King · On Writing', craft_lamott: 'Lamott · Bird by Bird',
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

        var DEFAULT_DISCUSS_INSTRUCTIONS = [
            'good, apply it',
            'Make this more direct.',
            'Deepen the subtext.',
            'Is the grammar correct?',
            'Check the point of view.'
        ];
        var DEFAULT_DISCUSS_SELECTION_ONLY = [
            'Make this more direct.',
            'Is the grammar correct?',
            'Check the point of view.'
        ];

        // Presets from the book's settings are selection presets by name.
        function discussInstructionNeedsSelection(value) {
            if (selectionOnlyDiscussInstructions().indexOf(value) >= 0) return true;
            if (configuredDiscussInstructions().indexOf(value) >= 0 && favoriteDiscussInstructions().indexOf(value) < 0) return true;
            if (DEFAULT_DISCUSS_SELECTION_ONLY.indexOf(value) >= 0 && favoriteDiscussInstructions().indexOf(value) < 0) return true;
            return false;
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
            var favorites = favoriteDiscussInstructions();
            var configured = configuredDiscussInstructions();
            var merged = favorites.concat(configured);
            if (!merged.length) {
                merged = DEFAULT_DISCUSS_INSTRUCTIONS.slice();
            }
            return normalizedDiscussInstructions(
                merged,
                24
            );
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
            var popover = elementWith('discuss-presets-popover'); popover.id = controls ? 'groupPresetsPopover' : 'discussPresetsPopover';
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
        function parseDiscussBtwDraft(rawText) {
            var value = String(rawText || '');
            var match = value.match(/^\s*\/btw(?:\s+([\s\S]*))?$/i);
            if (!match) return null;
            return {question: String(match[1] || '').trim()};
        }

        function syncDiscussSendEmpty() {
            var button = document.getElementById('discussSend');
            var sendNow = document.getElementById('discussSendNow');
            var btwHint = document.getElementById('discussBtwHint');
            var input = document.getElementById('discussInput');
            if (!button || !input) return;
            var craftButton = document.getElementById('discussCraftButton');
            var doc = discussTurnDocument();
            if (craftButton) {
                craftButton.hidden = !doc || doc.kind !== 'scene' || _discussCraftState.active
                    || !(_discussSnapshot && (_discussSnapshot.messages || []).length);
                craftButton.setAttribute('aria-expanded', String(!!_discussCraftState.cardsOpen));
            }
            var ordinary = !_discussPendingAction && !_discussRepositoryAction && !_discussCraftState.active && !_discussOpenFailed;
            var busy = !!(_discussSnapshot && (_discussSnapshot.active_turn_id || _discussSnapshot.active_request_id));
            var btwDraft = ordinary ? parseDiscussBtwDraft(input.value) : null;
            if (btwHint) btwHint.hidden = !btwDraft;
            var craftNoScenes = _discussCraftState.active && !discussCraftSelectedScenes().length;
            var reviewNoLanes = _discussCraftState.active && !discussReviewSelectedLanes().length;
            var comedyNoGoals = _discussCraftState.active && _discussCraftState.modeId === 'comedy_review' && !_discussCraftState.comedyGoals.length;
            var empty = btwDraft ? false : ((craftNoScenes || reviewNoLanes || comedyNoGoals) ? true : (!input.value.trim() && ordinary));
            button.dataset.empty = empty ? 'true' : 'false';
            button.setAttribute('aria-disabled', empty || button.disabled ? 'true' : 'false');
            if (ordinary && !button.disabled) {
                button.textContent = btwDraft ? (btwDraft.question ? 'Ask /btw' : 'Open /btw') : (busy ? 'Queue' : 'Send');
            }
            if (sendNow) {
                sendNow.hidden = !(ordinary && busy && !btwDraft);
                sendNow.disabled = empty || button.disabled;
                sendNow.dataset.empty = empty ? 'true' : 'false';
                sendNow.setAttribute('aria-disabled', empty || button.disabled ? 'true' : 'false');
            }
            // A preset sends itself; with a draft in the box it would replace
            // the draft, so it waits until the box is empty again.
            var draft = !!input.value.trim();
            document.querySelectorAll('#discussLog .discuss-review-run, #discussLog .discuss-review-customize').forEach(function(control) {
                control.disabled = button.disabled;
            });
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
            document.getElementById('discussInput').removeAttribute('aria-labelledby');
            var baseInputLabel = document.getElementById('discussInputLabel');
            if (baseInputLabel) {
                baseInputLabel.setAttribute('for', 'discussInput');
                baseInputLabel.hidden = false;
            }
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
            if (_discussCraftState.active) {
                node.hidden = false;
                var craftLens = discussCraftLens();
                var craftScenes = discussCraftSelectedScenes();
                var craftTitle = document.createElement('strong');
                craftTitle.textContent = _discussCraftState.modeId === 'craft_review' ? 'Craft review · ' + craftLens.label : craftLens.label;
                node.appendChild(craftTitle);
                var fmOn = effectiveDiscussFrontmatter();
                var adjOn = craftScenes.length === 1 && effectiveDiscussAdjacent();
                var craftHelp = document.createElement('span');
                craftHelp.textContent = craftScenes.length + (craftScenes.length === 1 ? ' scene' : ' scenes')
                    + ' · Full prose · Frontmatter ' + (fmOn ? 'on' : 'off')
                    + (adjOn ? ' · ±1 excerpts' : '')
                    + (_discussCraftState.checkPlan ? ' · Plan check' : '')
                    + (craftLens.id === 'craft_lamott' ? '' : ' · Up to ' + _discussCraftState.maxFindings
                        + (craftLens.id === 'deepen_and_layer' ? ' opportunities' : ' priorities'))
                    + (_discussCraftState.includeKeep && discussReviewHasKeepChoice(craftLens.id) ? ' · Keep list' : '');
                node.appendChild(craftHelp);
                if (_discussCraftState.modeId === 'comedy_review') {
                    node.appendChild(elementWith('discuss-comedy-summary', discussComedySummary()));
                }
                var chosenLanes = discussReviewSelectedLanes();
                if (chosenLanes.length !== craftLens.lanes.length) {
                    var focusName = discussReviewLaneSummary();
                    var focusChip = document.createElement('button');
                    focusChip.type = 'button';
                    focusChip.className = 'discuss-secondary discuss-craft-focus';
                    focusChip.textContent = 'Focus: ' + focusName + ' ×';
                    focusChip.setAttribute('aria-label', 'Remove review focus: ' + focusName);
                    focusChip.title = focusName + ' — reset to all lanes';
                    focusChip.onclick = function() {
                        setDiscussReviewLanes(craftLens.lanes.map(function(lane) { return lane.id; }));
                        renderDiscussTaskMode();
                        renderDiscussSnapshot();
                    };
                    node.appendChild(focusChip);
                }
                if (baseInputLabel) {
                    baseInputLabel.removeAttribute('for');
                    baseInputLabel.hidden = true;
                }
                var instructionLabel = document.createElement('label');
                instructionLabel.htmlFor = 'discussInput';
                instructionLabel.id = 'discussCraftInstructionsLabel';
                instructionLabel.className = 'discuss-craft-instruction-label';
                instructionLabel.textContent = 'Instructions for this review (optional)';
                node.appendChild(instructionLabel);
                document.getElementById('discussInput').setAttribute('aria-labelledby', instructionLabel.id);
                document.getElementById('discussInput').placeholder = 'For example: preserve the quiet tone, or focus on the ending…';
                document.getElementById('discussSend').textContent = discussReviewMode().run;
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
                if (presets.length > offered.length || offered.length > 3 || recents.length || favoriteDiscussInstructions().length) {
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
        var _discussModelCatalogs = {codex: null, claude: null, agy: null};
        var _discussModelCatalogPending = {codex: false, claude: false, agy: false};
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
                if (_groupSettings && _groupSettings.chat_models) _groupSettings.chat_models[_discussAgent] = data.model || {model: '', effort: ''};
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
            if (groupTabIsOpen()) { groupInsertContext('@' + path + ' '); return; }
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
                    resetChatHistoryCursor(_discussAgent);
                    _discussReview = []; _discussReviewKeep = {};
                    _discussSnapshot = data.snapshot;
                    _discussSelection = '';
                    _discussSelectionRange = null;
                    _discussSelectionSnapshot = null;
                    _discussSelectionSourceTaskId = null;
                    _discussLiveDocument = null;
                    _discussPendingAction = null;
                    _discussRepositoryAction = null;
                    leaveDiscussReviewSetup();
                    _discussCraftState.cardsOpen = false;
                    _discussRetryOfTaskId = null;
                    _discussSelectedSkill = null;
                    _discussAutoRun = false;
                    _discussAttachments = [];
                    _discussIncludeCurrentDocument = false;
                    if (!_discussRepositoryAction) _discussDraftDocument = null;
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

        function _discussWithSelection(text) {
            if (!_discussSelection) return text;
            if (/\n\nSelected passage(?:\s*\([^)\n]*\))?:\n/.test(text)) return text;
            var clean = _discussSelection.trim();
            if (!clean) return text;
            var quoted = clean.split('\n').map(function(line) { return '> ' + line; }).join('\n');
            var doc = discussTurnDocument();
            var docPath = doc && doc.kind === 'scene' ? doc.path : '';
            var curScene = _discussCurrentScenePath();
            var source = docPath && curScene && docPath !== curScene
                ? '> From scene: ' + docPath + '\n' : '';
            var rangeDesc = typeof getSelectionLineRange === 'function' ? getSelectionLineRange(clean) : '';
            var header = rangeDesc ? 'Selected passage (' + rangeDesc + '):' : 'Selected passage:';
            return text + '\n\n' + header + '\n' + source + quoted;
        }

        function sendDiscussQuestion(options) {
            var input = document.getElementById('discussInput');
            var question = input.value.trim();
            var button = document.getElementById('discussSend');
            var sendNow = document.getElementById('discussSendNow');
            var immediate = !!(options && options.mode === 'now');
            if (_discussOpenFailed) { openDiscuss(_discussReturnFocus); return; }
            if (_discussPendingAction) { runDiscussSelectionAction(); return; }
            if (_discussRepositoryAction) { runDiscussRepositoryAction(); return; }
            if (_discussCraftState.active) { runDiscussCraftReview(); return; }
            var btwDraft = parseDiscussBtwDraft(input.value);
            if (btwDraft && _discussConversationId) {
                if (btwDraft.question) {
                    sendDiscussSideQuestion(btwDraft.question);
                } else {
                    input.value = '';
                    saveDiscussDraft();
                    closeDiscussContextPicker();
                    syncDiscussSendEmpty();
                    openBtwPane();
                }
                return;
            }
            if (!question || !_discussConversationId || button.disabled) return;
            var turnDocument = discussTurnDocument();
            if (!turnDocument) return;
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            button.disabled = true;
            if (sendNow) sendNow.disabled = true;
            if (immediate && sendNow) sendNow.textContent = 'Sending…';
            else button.textContent = 'Sending…';
            document.getElementById('discussAnnouncement').textContent = immediate ? 'Sending now…' : 'Sending question…';
            var authored = question;
            var fullQuestion = _discussWithSelection(authored);
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: fullQuestion,
                document: turnDocument,
                selection: _discussSelection,
                selection_range: _discussSelectionRange,
                // Unsaved edits are not on disk for the agent to read.
                live_document: _discussLiveDocument || discussLiveDocumentFor(turnDocument),
                attachments: discussMentionsIn(authored).concat(_discussAttachments.filter(function(item) {
                    return authored.indexOf('@' + item.path) < 0;
                })),
                include_current_document: _discussIncludeCurrentDocument,
                immediate: immediate,
                // A $skill typed in the question is the skill the turn runs.
                skill: _discussSelectedSkill || (function() {
                    var named = discussSkillsIn(authored)[0];
                    return named ? {name: named.name, path: named.path} : null;
                })()
            }).then(function(data) {
                _discussAttachments = [];
                rememberDiscussInstruction(authored);
                recordChatMessageHistory(_discussAgent, authored);
                input.value = '';
                if (!_discussSelection) {
                    _discussIncludeCurrentDocument = false;
                    _discussDraftDocument = null;
                }
                saveDiscussDraft(); _discussSelectedSkill = null;
                var restoredLegacyDraft = activateLegacyDiscussDraft(discussDocument(), _discussAgent);
                closeDiscussContextPicker(); renderDiscussContext(); renderDiscussTaskMode(); scheduleDiscussSnapshot();
                var verb = data && data.status === 'steered' ? 'Sent now.' : immediate ? 'Sending now.' : 'Question queued.';
                document.getElementById('discussAnnouncement').textContent = restoredLegacyDraft
                    ? verb + ' Restored another saved draft for this file.'
                    : _discussSelection
                    ? verb + ' Selection remains attached for follow-up questions.'
                    : verb;
            }).catch(function(error) {
                renderDiscussError(error.message, {kind: error.name === 'NetworkError' ? 'transport' : 'request'});
                document.getElementById('discussAnnouncement').textContent = 'Question was not confirmed. ' + error.message;
            }).finally(function() {
                button.disabled = false;
                if (sendNow) { sendNow.disabled = false; sendNow.textContent = 'Send now'; }
                renderDiscussTaskMode();
                var active = document.activeElement;
                if (active === input || active === button || active === sendNow || active === document.body) input.focus();
            });
        }


        function startDiscussRepositoryAction(actionId) {
            leaveDiscussReviewSetup();
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
            if (!_discussSelection && !_discussPendingAction) _discussDraftDocument = null;
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
                    _discussIncludeCurrentDocument = false;
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

        function discussCraftLens(id) {
            var targetId = id || (_discussCraftState.modeId === 'craft_review' ? _discussCraftState.lensId : _discussCraftState.modeId);
            return DISCUSS_CRAFT_LENSES.concat(DISCUSS_REVIEW_GUIDES).find(function(l) { return l.id === targetId; }) || DISCUSS_CRAFT_LENSES[0];
        }

        function discussCraftLaneName(lane) {
            return lane ? String(lane.tab || '').replace(/^\d+\.\s*/, '') : '';
        }

        function discussCraftFocus() {
            var lanes = discussReviewSelectedLanes();
            return lanes.length === 1 ? lanes[0] : null;
        }

        function discussCraftContextKey(scenePath) {
            scenePath = scenePath || _discussCraftState.contextScenePath || discussCraftActivePath();
            var sourcePath = (typeof meta !== 'undefined' && meta[scenePath] && meta[scenePath].abs_path) || scenePath;
            return 'proseview-craft-context:' + sourcePath;
        }

        function discussCraftContext(scenePath) {
            var key = discussCraftContextKey(scenePath);
            if (Object.prototype.hasOwnProperty.call(_discussCraftState.storyContexts, key)) {
                return _discussCraftState.storyContexts[key];
            }
            try { return sessionStorage.getItem(key) || ''; } catch (e) { return ''; }
        }

        function saveDiscussCraftContext(value, scenePath) {
            var path = scenePath || _discussCraftState.contextScenePath || discussCraftActivePath();
            var key = discussCraftContextKey(path);
            _discussCraftState.storyContexts[key] = value;
            _discussCraftState.storyContextVersions[key] = (_discussCraftState.storyContextVersions[key] || 0) + 1;
            try {
                sessionStorage.setItem(key, value);
                sessionStorage.setItem(key + ':pending', 'true');
            } catch (e) {}
            clearTimeout(_discussCraftState.storyContextTimers[key]);
            setDiscussCraftContextStatus(key, 'Saving with this scene…');
            _discussCraftState.storyContextTimers[key] = setTimeout(function() {
                persistDiscussCraftContext(key, path);
            }, 400);
        }

        function setDiscussCraftContextStatus(key, text) {
            _discussCraftState.storyContextStatuses[key] = text;
            var status = document.getElementById('discussCraftContextStatus');
            if (status && key === discussCraftContextKey()) status.textContent = text;
        }

        function persistDiscussCraftContext(key, path) {
            if (_discussCraftState.storyContextSaves[key]) return;
            var value = _discussCraftState.storyContexts[key] || '';
            _discussCraftState.storyContextSaves[key] = true;
            discussApi('/api/discuss/craft-context', {scene_path: path, context: value}).then(function() {
                _discussCraftState.storyContextSaves[key] = false;
                if ((_discussCraftState.storyContexts[key] || '') !== value) {
                    persistDiscussCraftContext(key, path);
                    return;
                }
                try { sessionStorage.removeItem(key + ':pending'); } catch (e) {}
                setDiscussCraftContextStatus(key, 'Saved with this scene · shared by Codex and Claude');
            }).catch(function() {
                _discussCraftState.storyContextSaves[key] = false;
                setDiscussCraftContextStatus(key, 'Could not save yet. These notes are still included in this review.');
            });
        }

        function loadDiscussCraftContext(scenePath) {
            var path = scenePath || _discussCraftState.contextScenePath || discussCraftActivePath();
            var key = discussCraftContextKey(path);
            if (_discussCraftState.storyContextLoaded[key]) return;
            _discussCraftState.storyContextLoaded[key] = true;
            var version = _discussCraftState.storyContextVersions[key] || 0;
            // Carry notes from the earlier provider-specific session cache forward.
            try {
                if (sessionStorage.getItem(key) === null) {
                    var previousKey = 'proseview-craft-context:' + _discussAgent + ':' + key.slice('proseview-craft-context:'.length);
                    var previous = sessionStorage.getItem(previousKey);
                    if (previous) {
                        sessionStorage.setItem(key, previous);
                        sessionStorage.setItem(key + ':pending', 'true');
                    }
                }
            } catch (e) {}
            discussApi('/api/discuss/craft-context', {scene_path: path}).then(function(data) {
                if ((_discussCraftState.storyContextVersions[key] || 0) !== version) return;
                var pending = false;
                var cached = '';
                try {
                    pending = sessionStorage.getItem(key + ':pending') === 'true';
                    cached = sessionStorage.getItem(key) || '';
                } catch (e) {}
                var value = pending ? cached : (data.context || '');
                var changed = (_discussCraftState.storyContexts[key] || '') !== value;
                _discussCraftState.storyContexts[key] = value;
                try { sessionStorage.setItem(key, value); } catch (e) {}
                if (pending) {
                    setDiscussCraftContextStatus(key, 'Saving with this scene…');
                    persistDiscussCraftContext(key, path);
                } else {
                    setDiscussCraftContextStatus(key, 'Saved with this scene · shared by Codex and Claude');
                }
                if (changed && key === discussCraftContextKey() && _discussCraftState.active) renderDiscussSnapshot();
            }).catch(function() {
                _discussCraftState.storyContextLoaded[key] = false;
                setDiscussCraftContextStatus(key, 'Could not load saved notes. You can still add context for this review.');
            });
        }

        function discussCraftActivePath() {
            var doc = discussTurnDocument();
            return (doc && doc.kind === 'scene' && doc.path) ? doc.path : '';
        }

        function discussCraftAllPaths() {
            return Array.isArray(paths) ? paths.slice() : [];
        }

        function discussCraftSelectedScenes() {
            var activePath = discussCraftActivePath();
            var all = discussCraftAllPaths();
            var mode = _discussCraftState.scopeMode;
            if (mode === 'this_scene') return activePath ? [activePath] : [];
            if (mode === 'adjacent') {
                var idx = all.indexOf(activePath);
                if (idx < 0) return activePath ? [activePath] : [];
                return [all[idx - 1], all[idx], all[idx + 1]].filter(Boolean);
            }
            if (mode === 'this_chapter') {
                var ch = activePath && typeof meta !== 'undefined' && meta[activePath] ? meta[activePath].chapter : '';
                if (!ch) return activePath ? [activePath] : [];
                var inChapter = all.filter(function(p) { return meta[p] && meta[p].chapter === ch; });
                return inChapter.length ? inChapter : (activePath ? [activePath] : []);
            }
            var chosen = (_discussCraftState.customScenes || []).filter(function(p) { return all.indexOf(p) >= 0; });
            chosen.sort(function(a, b) { return all.indexOf(a) - all.indexOf(b); });
            return chosen;
        }

        function startDiscussCraftReview(modeId) {
            var activePath = discussCraftActivePath();
            var input = document.getElementById('discussInput');
            if (!_discussCraftState.active) {
                _discussCraftState.chatDraft = input.value;
                input.value = _discussCraftState.instructions;
            }
            _discussCraftState.modeId = DISCUSS_REVIEW_MODES.some(function(mode) { return mode.id === modeId; }) ? modeId : 'craft_review';
            _ensureDiscussContextDefaults().catch(function() {});
            _discussRepositoryAction = null;
            _discussPendingAction = null;
            _discussSelectedSkill = null;
            _discussCraftState.active = true;
            _discussCraftState.cardsOpen = true;
            _discussCraftState.openInfoId = null;
            _discussCraftState.focusMenuOpen = false;
            if (_discussCraftState.scenePath !== activePath) {
                _discussCraftState.storyContextOpen = null;
                _discussCraftState.scopeMode = 'this_scene';
                _discussCraftState.customScenes = activePath ? [activePath] : [];
                _discussCraftState.contextScenePath = activePath;
                _discussCraftState.scenePath = activePath;
            }
            renderDiscussTaskMode();
            renderDiscussSnapshot();
            var setup = document.querySelector('.discuss-craft-setup');
            if (setup) setup.scrollIntoView({block: 'start'});
            document.getElementById('discussInput').focus();
            document.getElementById('discussAnnouncement').textContent = discussReviewMode().label + ' selected';
        }

        function cancelDiscussCraftReview() {
            if (!_discussCraftState.active) return;
            closeDiscussCraftInfoDialog();
            leaveDiscussReviewSetup();
            saveDiscussDraft();
            renderDiscussTaskMode();
            renderDiscussSnapshot();
            document.getElementById('discussInput').focus();
            document.getElementById('discussAnnouncement').textContent = 'Choose a story-aware action';
        }

        function leaveDiscussReviewSetup() {
            var input = document.getElementById('discussInput');
            if (_discussCraftState.active && input) {
                _discussCraftState.instructions = input.value;
                input.value = _discussCraftState.chatDraft;
            }
            _discussCraftState.active = false;
            _discussCraftState.openInfoId = null;
            _discussCraftState.focusMenuOpen = false;
        }

        function _syncDiscussCraftInfoButtons() {
            document.querySelectorAll('.discuss-craft-lens').forEach(function(card) {
                var btn = card.querySelector('.discuss-craft-info-btn');
                if (!btn) return;
                var open = _discussCraftState.openInfoId === card.dataset.lens;
                btn.classList.toggle('is-open', open);
                btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            });
        }

        function _selectDiscussCraftLensAndScope(infoLens) {
            var isBook = infoLens.id.indexOf('craft_') === 0;
            _discussCraftState.modeId = isBook ? 'craft_review' : infoLens.id;
            if (isBook) _discussCraftState.lensId = infoLens.id;
            _discussCraftState.focusMenuOpen = false;
            // Scope and background settings belong to this review, not the book.
            if (isBook) {
                try { localStorage.setItem('proseview-craft-lens', infoLens.id); } catch (e) {}
            }
        }

        function renderDiscussCraftInfoDialog(lensId, tabId) {
            var infoLens = discussCraftLens(lensId);
            var lanes = Array.isArray(infoLens.lanes) ? infoLens.lanes : [];
            var activeTabId = tabId && lanes.some(function(item) { return item.id === tabId; }) ? tabId : 'overview';
            _discussCraftState.openInfoId = infoLens.id;
            _syncDiscussCraftInfoButtons();

            var dialog = document.getElementById('discussCraftInfoDialog');
            var titleEl = document.getElementById('discussCraftInfoTitle');
            var subEl = document.getElementById('discussCraftInfoSubtitle');
            var tabsEl = document.getElementById('discussCraftInfoTabs');
            var bodyEl = document.getElementById('discussCraftInfoBody');
            var useBtn = document.getElementById('discussCraftInfoUseBtn');
            if (!dialog || !titleEl || !subEl || !tabsEl || !bodyEl || !useBtn) return;

            dialog.dataset.lens = infoLens.id;
            dialog.dataset.tab = activeTabId;
            titleEl.textContent = infoLens.book;
            subEl.textContent = (infoLens.author ? infoLens.author + ' · ' : '') + (infoLens.subtitle || infoLens.tagline);
            document.getElementById('discussCraftInfoNote').textContent = infoLens.author
                ? 'Selected book principles · Original examples · No file changes'
                : 'Selected feedback lanes · Original examples · No file changes';

            tabsEl.replaceChildren();
            var tabItems = [{ id: 'overview', tab: 'Overview' }].concat(lanes);
            tabItems.forEach(function(item, index) {
                var isActive = item.id === activeTabId;
                var tab = document.createElement('button');
                tab.type = 'button';
                tab.role = 'tab';
                tab.id = 'discussCraftTab-' + infoLens.id + '-' + item.id;
                tab.setAttribute('aria-controls', bodyEl.id);
                tab.dataset.tab = item.id;
                tab.tabIndex = isActive ? 0 : -1;
                tab.className = 'discuss-craft-dialog-tab' + (isActive ? ' is-active' : '');
                tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
                tab.textContent = item.tab;
                tab.onclick = function() {
                    renderDiscussCraftInfoDialog(infoLens.id, item.id);
                    document.getElementById(tab.id).focus({preventScroll: true});
                };
                tab.addEventListener('keydown', function(event) {
                    var targetIdx = null;
                    if (event.key === 'ArrowRight') targetIdx = (index + 1) % tabItems.length;
                    else if (event.key === 'ArrowLeft') targetIdx = (index - 1 + tabItems.length) % tabItems.length;
                    else if (event.key === 'Home') targetIdx = 0;
                    else if (event.key === 'End') targetIdx = tabItems.length - 1;
                    if (targetIdx === null) return;
                    event.preventDefault();
                    var nextId = tabItems[targetIdx].id;
                    renderDiscussCraftInfoDialog(infoLens.id, nextId);
                    var nextTab = tabsEl.querySelector('[data-tab="' + nextId + '"]');
                    if (nextTab) nextTab.focus();
                });
                tabsEl.appendChild(tab);
            });

            bodyEl.replaceChildren();
            bodyEl.scrollTop = 0;
            bodyEl.setAttribute('aria-labelledby', 'discussCraftTab-' + infoLens.id + '-' + activeTabId);
            if (activeTabId === 'overview') {
                infoLens.thesis.split(/\n\s*\n/).forEach(function(paragraph) {
                    var thesis = document.createElement('p');
                    thesis.className = 'discuss-craft-info-thesis';
                    thesis.textContent = paragraph;
                    bodyEl.appendChild(thesis);
                });

                var reviewNote = elementWith('discuss-craft-guide-note');
                var reviewLabel = document.createElement('strong');
                reviewLabel.textContent = 'What the review will do';
                reviewNote.append(reviewLabel, elementWith('discuss-craft-check-desc', infoLens.reviewNote));
                bodyEl.appendChild(reviewNote);

                var lanesLabel = elementWith('discuss-craft-dialog-section-label', 'Principles in this review (choose one for examples)');
                bodyEl.appendChild(lanesLabel);

                var laneGrid = elementWith('discuss-craft-lane-grid');
                lanes.forEach(function(lane) {
                    var card = document.createElement('button');
                    card.type = 'button';
                    card.className = 'discuss-craft-lane-card';
                    card.dataset.lane = lane.id;
                    var cTop = elementWith('discuss-craft-lane-top');
                    var cTitle = elementWith('discuss-craft-lane-name', lane.tab);
                    var cLink = elementWith('discuss-craft-lane-more', 'Examples →');
                    cTop.append(cTitle, cLink);
                    card.append(cTop, elementWith('discuss-craft-check-desc', lane.brief));
                    card.onclick = function() {
                        renderDiscussCraftInfoDialog(infoLens.id, lane.id);
                        document.getElementById('discussCraftTab-' + infoLens.id + '-' + lane.id).focus({preventScroll: true});
                    };
                    laneGrid.appendChild(card);
                });
                bodyEl.appendChild(laneGrid);

                var guidance = elementWith('discuss-craft-info-guidance');
                var best = elementWith('discuss-craft-info-best');
                var bestStrong = document.createElement('strong');
                bestStrong.textContent = 'Best when: ';
                best.append(bestStrong, document.createTextNode(infoLens.bestFor));
                guidance.appendChild(best);
                if (infoLens.skipWhen) {
                    var skipLine = elementWith('discuss-craft-info-skip');
                    var skipStrong = document.createElement('strong');
                    skipStrong.textContent = 'Try another lens when: ';
                    skipLine.append(skipStrong, document.createTextNode(infoLens.skipWhen));
                    guidance.appendChild(skipLine);
                }
                bodyEl.appendChild(guidance);
                if (infoLens.goals) {
                    var approach = elementWith('discuss-craft-guide-note');
                    var approachLabel = document.createElement('strong'); approachLabel.textContent = 'Choose what you want the review to do';
                    approach.appendChild(approachLabel);
                    infoLens.goals.forEach(function(goal) {
                        approach.appendChild(elementWith('discuss-craft-check-desc', goal.label + ': ' + goal.brief));
                    });
                    approach.appendChild(elementWith('discuss-craft-check-desc', 'Dark comedy, sarcasm, and dry delivery can be combined in setup. They change how selected lanes are read, and leave your scene selection and notes in place.'));
                    bodyEl.appendChild(approach);
                }
                appendDiscussReviewSources(bodyEl, infoLens);
                if (infoLens.sourceUrl) {
                    var source = document.createElement('a');
                    source.className = 'discuss-craft-source';
                    source.href = infoLens.sourceUrl;
                    source.target = '_blank';
                    source.rel = 'noopener noreferrer';
                    source.textContent = infoLens.sourceLabel + ' ↗';
                    bodyEl.appendChild(source);
                }
            } else {
                var lane = lanes.find(function(item) { return item.id === activeTabId; }) || lanes[0];
                if (lane) {
                    var laneHead = elementWith('discuss-craft-lane-detail-head');
                    var lTitle = document.createElement('h3');
                    lTitle.textContent = lane.title;
                    var focusBtn = document.createElement('button');
                    focusBtn.type = 'button';
                    focusBtn.className = 'discuss-craft-lane-focus-btn';
                    focusBtn.textContent = 'Focus review on this topic →';
                    focusBtn.onclick = function() {
                        _selectDiscussCraftLensAndScope(infoLens);
                        var input = document.getElementById('discussInput');
                        setDiscussReviewLanes([lane.id], infoLens);
                        closeDiscussCraftInfoDialog();
                        if (!_discussCraftState.active) startDiscussCraftReview(_discussCraftState.modeId);
                        renderDiscussTaskMode();
                        renderDiscussSnapshot();
                        if (input) input.focus();
                    };
                    laneHead.append(lTitle, focusBtn);
                    bodyEl.appendChild(laneHead);

                    var summaryEl = elementWith('discuss-craft-info-thesis', lane.summary);
                    bodyEl.appendChild(summaryEl);

                    var exWrap = elementWith('discuss-craft-example');
                    var exHead = elementWith('discuss-craft-example-head');
                    var exKicker = document.createElement('strong');
                    exKicker.textContent = 'One possible revision';
                    exHead.appendChild(exKicker);

                    var exGrid = elementWith('discuss-craft-example-grid');
                    var flatCard = elementWith('discuss-craft-example-card is-flat');
                    flatCard.appendChild(elementWith('discuss-craft-example-tag', 'Before'));
                    flatCard.appendChild(elementWith('discuss-craft-example-copy', lane.flat));

                    var winCard = elementWith('discuss-craft-example-card is-working');
                    winCard.appendChild(elementWith('discuss-craft-example-tag', 'A possible next version'));
                    winCard.appendChild(elementWith('discuss-craft-example-copy', lane.working));
                    exGrid.append(flatCard, winCard);

                    var whyEl = elementWith('discuss-craft-example-why');
                    var whyStrong = document.createElement('strong');
                    whyStrong.textContent = 'Why it works: ';
                    whyEl.append(whyStrong, document.createTextNode(lane.why));

                    exWrap.append(exHead, exGrid, whyEl);
                    bodyEl.appendChild(exWrap);

                    if (lane.anotherExample) {
                        var another = document.createElement('details');
                        another.className = 'discuss-craft-guide-note discuss-craft-another-example';
                        var anotherTitle = document.createElement('summary');
                        anotherTitle.textContent = 'Another example: ' + lane.anotherExample.title;
                        var anotherText = document.createElement('blockquote');
                        anotherText.textContent = lane.anotherExample.text;
                        another.append(anotherTitle, anotherText, elementWith('discuss-craft-check-desc', lane.anotherExample.why));
                        bodyEl.appendChild(another);
                    }
                    var aiGrid = elementWith('discuss-craft-ai-grid');
                    var spotBox = elementWith('discuss-craft-ai-box');
                    var spotStrong = document.createElement('strong');
                    spotStrong.textContent = 'What to look for';
                    spotBox.append(spotStrong, elementWith('discuss-craft-check-desc', lane.spot));
                    if (lane.fix) {
                        var fixBox = elementWith('discuss-craft-ai-box');
                        var fixStrong = document.createElement('strong');
                        fixStrong.textContent = 'Possible next step';
                        fixBox.append(fixStrong, elementWith('discuss-craft-check-desc', lane.fix));
                        aiGrid.appendChild(fixBox);
                    }
                    aiGrid.prepend(spotBox);
                    bodyEl.appendChild(aiGrid);

                    var practice = elementWith('discuss-craft-guide-note');
                    var practiceTitle = document.createElement('strong');
                    practiceTitle.textContent = 'Try it in your scene';
                    practice.append(practiceTitle, elementWith('discuss-craft-check-desc', lane.tryIt));
                    var judgment = elementWith('discuss-craft-guide-note');
                    var judgmentTitle = document.createElement('strong');
                    judgmentTitle.textContent = 'Use your judgment';
                    judgment.append(judgmentTitle, elementWith('discuss-craft-check-desc', lane.caution));
                    bodyEl.append(practice, judgment);
                    if (lane.sources) appendDiscussReviewSources(bodyEl, infoLens, lane.sources);
                }
            }

            var alreadyActive = _discussCraftState.active && discussCraftLens().id === infoLens.id;
            useBtn.textContent = alreadyActive ? 'Selected ✓' : 'Use ' + infoLens.book;
            useBtn.disabled = alreadyActive;
            useBtn.onclick = function() {
                _selectDiscussCraftLensAndScope(infoLens);
                closeDiscussCraftInfoDialog();
                if (!_discussCraftState.active) startDiscussCraftReview(_discussCraftState.modeId);
                renderDiscussTaskMode();
                renderDiscussSnapshot();
            };
        }

        var _discussCraftInfoOpener = null;
        function openDiscussCraftInfoDialog(lensId, tabId) {
            var dialog = document.getElementById('discussCraftInfoDialog');
            if (!dialog) return;
            if (!dialog.open) _discussCraftInfoOpener = document.activeElement;
            renderDiscussCraftInfoDialog(lensId, tabId || 'overview');
            if (!dialog.open) dialog.showModal();
            var closeBtn = document.getElementById('discussCraftInfoClose');
            if (closeBtn) closeBtn.focus();
        }

        function closeDiscussCraftInfoDialog() {
            var dialog = document.getElementById('discussCraftInfoDialog');
            var prevLensId = _discussCraftState.openInfoId;
            _discussCraftState.openInfoId = null;
            _syncDiscussCraftInfoButtons();
            if (dialog && dialog.open) dialog.close();
            if (_discussCraftInfoOpener && _discussCraftInfoOpener.isConnected) {
                _discussCraftInfoOpener.focus({preventScroll: true});
                _discussCraftInfoOpener = null;
                return;
            }
            var trigger = document.getElementById('discussReviewFocusTrigger');
            if (trigger) {
                trigger.focus({preventScroll: true});
                return;
            }
            if (prevLensId) {
                var btn = document.querySelector('.discuss-craft-lens[data-lens="' + prevLensId + '"] .discuss-craft-info-btn');
                if (btn) btn.focus({preventScroll: true});
            }
        }

        (function initDiscussCraftInfoDialog() {
            var dialog = document.getElementById('discussCraftInfoDialog');
            if (!dialog) return;
            dialog.addEventListener('click', function(event) {
                if (event.target === dialog) closeDiscussCraftInfoDialog();
            });
            dialog.addEventListener('close', function() {
                var prevLensId = _discussCraftState.openInfoId;
                _discussCraftState.openInfoId = null;
                _syncDiscussCraftInfoButtons();
                // Explicit closes already restored focus synchronously.
                if (!prevLensId) return;
                if (_discussCraftInfoOpener && _discussCraftInfoOpener.isConnected) {
                    _discussCraftInfoOpener.focus({preventScroll: true});
                    _discussCraftInfoOpener = null;
                    return;
                }
                var trigger = document.getElementById('discussReviewFocusTrigger');
                if (trigger) { trigger.focus({preventScroll: true}); return; }
                if (prevLensId) {
                    var btn = document.querySelector('.discuss-craft-lens[data-lens="' + prevLensId + '"] .discuss-craft-info-btn');
                    if (btn) btn.focus({preventScroll: true});
                }
            });
        })();

        function openDiscussContextSentDialog(ctx, titleLabel) {
            var dialog = document.getElementById('discussContextSentDialog');
            var subEl = document.getElementById('discussContextSentSubtitle');
            var bodyEl = document.getElementById('discussContextSentBody');
            if (!dialog || !subEl || !bodyEl || !ctx) return;

            var parts = [];
            if (titleLabel) parts.push(titleLabel);
            if (ctx.skill_name) parts.push('Skill: ' + ctx.skill_name);
            subEl.textContent = parts.join(' · ') || 'Turn context details';

            bodyEl.replaceChildren();

            var pills = elementWith('discuss-context-sent-pills');
            function addPill(label, on) {
                var pill = elementWith('discuss-context-sent-pill' + (on ? ' is-on' : ''), label);
                pills.appendChild(pill);
            }
            addPill('Frontmatter: ' + (ctx.include_frontmatter ? 'On' : 'Off'), !!ctx.include_frontmatter);
            addPill('±1 Excerpts: ' + (ctx.include_adjacent ? 'On' : 'Off'), !!ctx.include_adjacent);
            addPill('Beat Map: ' + (ctx.beatmap_included ? 'Included' : 'None'), !!ctx.beatmap_included);
            if (ctx.include_keep === true || ctx.include_keep === false) {
                addPill('Keep list: ' + (ctx.include_keep ? 'On' : 'Off'), ctx.include_keep);
            }
            if (ctx.check_plan === true || ctx.check_plan === false) {
                addPill('Plan check: ' + (ctx.check_plan ? 'On' : 'Off'), ctx.check_plan);
            }
            if (typeof ctx.max_findings === 'number') {
                addPill('Priorities: up to ' + ctx.max_findings, ctx.max_findings !== DISCUSS_DEFAULT_MAX_FINDINGS);
            }
            var instrList = Array.isArray(ctx.project_instructions) ? ctx.project_instructions : [];
            addPill('Repo rules: ' + (instrList.length ? instrList.join(', ') : 'none'), instrList.length > 0);
            bodyEl.appendChild(pills);

            if (Array.isArray(ctx.documents) && ctx.documents.length) {
                var docsSec = elementWith('discuss-context-sent-section');
                docsSec.appendChild(elementWith('discuss-craft-dialog-section-label', 'Attached documents'));
                docsSec.appendChild(elementWith('discuss-context-sent-docs', ctx.documents.join(', ')));
                bodyEl.appendChild(docsSec);
            }

            function addCollapsible(title, text, openByDefault) {
                if (!text) return;
                var det = document.createElement('details');
                det.className = 'discuss-context-sent-details';
                if (openByDefault) det.open = true;
                var sum = document.createElement('summary');
                sum.textContent = title;
                var pre = document.createElement('pre');
                pre.className = 'discuss-context-sent-pre';
                pre.textContent = text;
                det.append(sum, pre);
                bodyEl.appendChild(det);
            }

            var noteParts = [];
            if (ctx.include_frontmatter) noteParts.push('frontmatter');
            if (ctx.include_adjacent) noteParts.push('adjacent excerpts');
            var notesTitle = noteParts.length
                ? 'Background notes sent (' + noteParts.join(' & ') + ')'
                : 'Background notes sent';
            addCollapsible(notesTitle, ctx.notes, true);
            addCollapsible('Selected passage', ctx.selection, false);
            addCollapsible('Skill / action prompt', ctx.skill_prompt, false);
            addCollapsible('Developer instructions', ctx.developer_instructions, false);
            addCollapsible('Full raw prompt sent', ctx.full_prompt, false);

            if (!dialog.open) dialog.showModal();
            var closeBtn = document.getElementById('discussContextSentClose');
            if (closeBtn) closeBtn.focus();
        }

        function closeDiscussContextSentDialog() {
            var dialog = document.getElementById('discussContextSentDialog');
            if (dialog && dialog.open) dialog.close();
        }

        (function initDiscussContextSentDialog() {
            var dialog = document.getElementById('discussContextSentDialog');
            if (!dialog) return;
            dialog.addEventListener('click', function(event) {
                if (event.target === dialog) closeDiscussContextSentDialog();
            });
        })();

        function renderDiscussCraftSetup(container) {
            renderDiscussReviewSetup(container);
        }

        function discussCraftScenesCountHint(mode, activePath, allPaths) {
            if (mode === 'adjacent') {
                var idx = allPaths.indexOf(activePath);
                if (idx < 0) return '1 scene';
                var n = [allPaths[idx - 1], allPaths[idx], allPaths[idx + 1]].filter(Boolean).length;
                return n + (n === 1 ? ' scene' : ' scenes');
            }
            if (mode === 'this_chapter') {
                var ch = activePath && typeof meta !== 'undefined' && meta[activePath] ? meta[activePath].chapter : '';
                if (!ch) return '1 scene';
                var count = allPaths.filter(function(p) { return meta[p] && meta[p].chapter === ch; }).length || 1;
                return count + (count === 1 ? ' scene' : ' scenes');
            }
            return '';
        }

        function runDiscussCraftReview(options) {
            var defaults = !!(options && options.defaults);
            var modeId = defaults ? options.modeId : _discussCraftState.modeId;
            var button = document.getElementById('discussSend');
            var input = document.getElementById('discussInput');
            var turnDocument = defaults ? (discussDocument() || discussTurnDocument()) : discussTurnDocument();
            if (!_discussConversationId || button.disabled) return;
            if (!turnDocument || turnDocument.kind !== 'scene') {
                renderDiscussError('A review reads manuscript scenes. Open a scene first.');
                return;
            }
            var selectedScenes = defaults ? [turnDocument.path] : discussCraftSelectedScenes();
            if (!selectedScenes.length) {
                renderDiscussError('Select at least one scene to review.');
                return;
            }
            var lens = defaults ? discussReviewDefaultLens(modeId) : discussCraftLens();
            var lanes = defaults ? lens.lanes : discussReviewSelectedLanes(lens);
            if (!lanes.length) {
                renderDiscussError('Choose at least one lane to review.');
                return;
            }
            if (modeId === 'comedy_review' && !defaults && !_discussCraftState.comedyGoals.length) {
                renderDiscussError('Choose at least one comedy review goal.');
                return;
            }
            var contexts = {};
            selectedScenes.forEach(function(path) {
                var key = discussCraftContextKey(path);
                // Let the server read saved notes that have not loaded yet.
                // Include local edits immediately, even before their save finishes.
                if (Object.prototype.hasOwnProperty.call(_discussCraftState.storyContexts, key)) contexts[path] = discussCraftContext(path).trim();
                else {
                    try {
                        if (sessionStorage.getItem(key + ':pending') === 'true') contexts[path] = discussCraftContext(path).trim();
                    } catch (e) {}
                }
            });
            var custom = !defaults && input ? input.value.trim() : '';
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            clearDiscussError();
            button.disabled = true;
            button.textContent = 'Starting…';
            var endpoint = '/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions';
            // Capture a request without changing Customize's saved choices.
            var payload = {
                client_request_id: requestId,
                question: '',
                document: turnDocument,
                action_id: lens.id,
                action_scope: selectedScenes.length > 1 ? 'scenes' : 'scene',
                scenes: selectedScenes,
                custom_instruction: custom,
                craft_focus: defaults ? '' : (discussCraftFocus() || {}).id || '',
                craft_context: '',
                craft_check_plan: !defaults && !!_discussCraftState.checkPlan,
                review_max_findings: defaults ? DISCUSS_DEFAULT_MAX_FINDINGS : _discussCraftState.maxFindings,
                review_include_keep: !defaults && !!_discussCraftState.includeKeep,
                craft_lanes: lanes.map(discussCraftLaneName),
                review_lanes: lanes.map(function(lane) { return lane.id; }),
                review_contexts: contexts,
                ...(modeId === 'comedy_review' ? {
                    comedy_styles: defaults ? [] : _discussCraftState.comedyStyles.slice(),
                    comedy_goals: defaults ? ['strengthen', 'explore'] : _discussCraftState.comedyGoals.slice()
                } : {}),
                live_document: discussLiveDocumentFor(turnDocument),
                attachments: [],
                include_current_document: false,
                include_frontmatter: effectiveDiscussFrontmatter(),
                include_adjacent: selectedScenes.length === 1 && effectiveDiscussAdjacent()
            };
            syncDiscussSendEmpty();
            // The first quick run may happen before Settings has been opened.
            // Read the book defaults before sending rather than borrowing any
            // temporary frontmatter/neighbor choices from Customize.
            (defaults ? _ensureDiscussContextDefaults() : Promise.resolve()).then(function() {
                if (defaults) {
                    payload.include_frontmatter = _discussDefaultFlag('includeFrontmatter');
                    payload.include_adjacent = _discussDefaultFlag('includeAdjacent');
                }
                return discussApi(endpoint, payload);
            }).then(function() {
                if (!defaults) {
                    if (custom) rememberDiscussInstruction(custom);
                    leaveDiscussReviewSetup();
                    saveDiscussDraft();
                }
                _discussCraftState.cardsOpen = false;
                renderDiscussTaskMode();
                document.getElementById('discussAnnouncement').textContent =
                    lens.label + ' running across ' + selectedScenes.length + (selectedScenes.length === 1 ? ' scene' : ' scenes') + '. The manuscript will not change.';
                scheduleDiscussSnapshot();
            }).catch(function(error) {
                renderDiscussError(error.message);
            }).finally(function() {
                button.disabled = false;
                renderDiscussTaskMode();
            });
        }

        // The main card runs this scene with defaults. Customize is a separate
        // control; its scope, lanes, and instructions never enter a quick run.
        function runDiscussScenePass(actionId) {
            if (DISCUSS_REVIEW_MODES.some(function(mode) { return mode.id === actionId; })) {
                runDiscussCraftReview({defaults: true, modeId: actionId});
                return;
            }
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
            var isFrontmatterUpdate = actionId === 'update_frontmatter';
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId,
                question: '',
                document: turnDocument,
                action_id: actionId,
                action_scope: 'scene',
                attachments: [],
                include_current_document: false,
                include_frontmatter: isFrontmatterUpdate ? false : effectiveDiscussFrontmatter(),
                include_adjacent: isFrontmatterUpdate ? false : effectiveDiscussAdjacent()
            }).then(function() {
                document.getElementById('discussAnnouncement').textContent = isFrontmatterUpdate
                    ? 'Updating frontmatter from drafted prose. You can adjust any field or undo all afterwards.'
                    : selectionActionLabel(actionId) + ' running on this scene. The manuscript will not change.';
                scheduleDiscussSnapshot();
            }).catch(function(error) {
                if (isFrontmatterUpdate) _clearDiscussFrontmatterSync();
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
                    button.textContent = 'Stop ' + discussAgentLabel();
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
            } else if (handleChatHistoryKeydown(event, this, {
                group: function() { return _discussAgent; },
                isMenuOpen: function() { return !document.getElementById('discussContextPicker').hidden; },
                applyValue: function(nextValue) {
                    var box = document.getElementById('discussInput');
                    box.value = nextValue;
                    saveDiscussDraft();
                    syncDiscussSendEmpty();
                }
            })) {
                return;
            } else if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
                event.preventDefault();
                var sendNowBtn = document.getElementById('discussSendNow');
                if ((event.metaKey || event.ctrlKey) && sendNowBtn && !sendNowBtn.hidden && !sendNowBtn.disabled) {
                    sendDiscussQuestion({mode: 'now'});
                } else {
                    sendDiscussQuestion();
                }
            }
        });
        wireChatHistoryInput(document.getElementById('discussInput'), function() { return _discussAgent; });
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
            function splitSideBySide() {
                var panel = document.getElementById('discussPanel');
                return !!(panel && panel.classList.contains('has-btw-split') && !panel.classList.contains('is-stacked'));
            }
            function setWidth(width) {
                var zoom = workspaceZoomFactor();
                if (splitSideBySide() && typeof _btwTotalBudget === 'function') {
                    var budget = _btwTotalBudget();
                    if (budget.stacked) return;
                    var curSplit = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-split-w')) || 280;
                    var maxMain = Math.max(240, Math.floor(budget.maxCombined - curSplit - 8));
                    var clamped = Math.max(240, Math.min(maxMain, width));
                    document.documentElement.style.setProperty('--btw-main-w', Math.round(clamped) + 'px');
                    updateSeparatorValue(handle, clamped * zoom, 240 * zoom, maxMain * zoom);
                    return;
                }
                var bounds = workspaceDockWidthBounds(340);
                width = Math.max(bounds.min, Math.min(bounds.max, width));
                var zoomed = document.documentElement.dataset.cssZoom === 'true';
                document.documentElement.style.setProperty(zoomed ? '--css-zoom-dock-width' : '--utility-dock-w', width + 'px');
                updateSeparatorValue(handle, width * zoom, bounds.min * zoom, bounds.max * zoom);
            }
            function currentWidth() {
                // A split measures its main shell; the ordinary dock includes
                // its border so repeated layout updates preserve its width.
                var panel = document.getElementById('discussPanel');
                var target = splitSideBySide() ? panel.querySelector('.discuss-shell') : panel;
                var rendered = target ? target.getBoundingClientRect().width : 0;
                if (rendered > 0) return rendered / workspaceZoomFactor();
                return parseFloat(getComputedStyle(document.documentElement).getPropertyValue(
                    splitSideBySide() ? '--btw-main-w' : '--utility-dock-w'
                )) || 420;
            }
            handle.addEventListener('mousedown', function(event) { dragging = true; startX = event.clientX; startWidth = currentWidth(); handle.classList.add('is-dragging'); document.body.style.userSelect = 'none'; event.preventDefault(); });
            document.addEventListener('mousemove', function(event) { if (!dragging) return; setWidth(startWidth + (startX - event.clientX) / workspaceZoomFactor()); });
            document.addEventListener('mouseup', function() {
                if (!dragging) return;
                dragging = false;
                handle.classList.remove('is-dragging');
                document.body.style.userSelect = '';
                if (splitSideBySide() && typeof _saveBtwLayout === 'function') _saveBtwLayout();
            });
            handle.addEventListener('keydown', function(event) {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                var minW = splitSideBySide() ? 240 : workspaceDockWidthBounds(340).min;
                var maxW = (splitSideBySide() && typeof _btwTotalBudget === 'function')
                    ? Math.max(240, _btwTotalBudget().maxCombined - (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-split-w')) || 280) - 8)
                    : workspaceDockWidthBounds(340).max;
                var current = currentWidth();
                var next = current;
                if (event.key === 'Home') next = minW;
                else if (event.key === 'End') next = maxW;
                else next += (event.key === 'ArrowRight' ? 1 : -1) * (event.shiftKey ? 50 : 20);
                setWidth(next);
                if (splitSideBySide() && typeof _saveBtwLayout === 'function') _saveBtwLayout();
                event.preventDefault();
            });
            var initialBounds = workspaceDockWidthBounds(340);
            var initialWidth = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--utility-dock-w')) || 420;
            setWidth(Math.min(initialBounds.max, Math.max(initialBounds.min, initialWidth)));
            window.addEventListener('resize', function() {
                if (splitSideBySide() && typeof _applyBtwSplitDimensions === 'function') _applyBtwSplitDimensions(currentWidth(), parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-split-w')) || 280);
                else setWidth(currentWidth());
            });
            window.addEventListener('proseview:workspace-metrics', function() {
                if (splitSideBySide() && typeof _applyBtwSplitDimensions === 'function') _applyBtwSplitDimensions(currentWidth(), parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--btw-split-w')) || 280);
                else setWidth(currentWidth());
            });
        })();
