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
        var _discussLocalErrorReload = false;
        var _discussReconnectTimer = null;

        function discussDraftKey(doc) {
            return 'proseview-codex-draft:' + discussDocumentKey(doc);
        }

        function saveDiscussDraft() {
            var input = document.getElementById('discussInput');
            if (!_discussDocumentKey || !input) return;
            var key = 'proseview-codex-draft:' + _discussDocumentKey;
            try {
                if (input.value) sessionStorage.setItem(key, input.value);
                else sessionStorage.removeItem(key);
            } catch(e) {}
        }

        function restoreDiscussDraft(doc) {
            try { return sessionStorage.getItem(discussDraftKey(doc)) || ''; }
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
            var sceneBack = document.querySelector('#sceneModal .scene-back-btn');
            _discussReturnFocus = (trigger && trigger.getClientRects && trigger.getClientRects().length) ? trigger : sceneBack;
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
            document.getElementById('discussSend').disabled = true;
            _discussOpenFailed = false;
            _discussConversationId = null;
            document.body.classList.add('discuss-open');
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
            _discussPreservedDraft = restoreDiscussDraft(doc);
            input.value = requestedAutoRun ? '' : _discussPreservedDraft;
            discussApi('/api/discuss/conversations/open', doc).then(function(data) {
                if (_discussDocumentKey !== key) return;
                _discussConversationId = data.conversation_id;
                _discussSnapshot = data.snapshot;
                renderDiscussSnapshot();
                connectDiscussEvents();
                renderDiscussTaskMode();
                document.getElementById('discussSend').disabled = false;
                if (options.showSkills) loadDiscussSkills();
                else if (requestedAutoRun && requestedAction) {
                    runDiscussSelectionAction(requestedAction, requestedSelection, requestedSelectionRange, requestedLiveDocument);
                }
                else input.focus();
            }).catch(function(error) {
                _discussOpenFailed = true;
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

        function showRightTerminal() {
            hideDiscussForTerminal();
            if (typeof _termDock !== 'undefined') _termDock = 'right';
            try { localStorage.setItem('proseview-terminal-dock', 'right'); } catch(e) {}
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
            var source = new EventSource('/api/discuss/conversations/' + encodeURIComponent(cid) + '/events');
            _discussEventSource = source;
            source.onopen = function() {
                if (_discussConversationId === cid && (!_discussSnapshot || _discussSnapshot.connection !== 'Unavailable')) {
                    clearDiscussTransportError();
                    setDiscussConnection('Live', '');
                }
            };
            source.onerror = function() {
                if (_discussConversationId !== cid || _discussEventSource !== source) return;
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
             'task.updated', 'tasks.cleared', 'warning', 'error'].forEach(function(type) {
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
            var atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
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

        function appendMarkdownTokens(parent, tokens) {
            (tokens || []).forEach(function(token) {
                var node;
                if (token.type === 'space') return;
                if (token.type === 'text' || token.type === 'escape') {
                    if (token.tokens) appendMarkdownTokens(parent, token.tokens);
                    else parent.appendChild(document.createTextNode(decodeMarkdownText(token.text || token.raw || '')));
                    return;
                }
                if (token.type === 'html') { parent.appendChild(document.createTextNode(token.raw || token.text || '')); return; }
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
                else { parent.appendChild(document.createTextNode(token.raw || token.text || '')); return; }
                if (token.type === 'list') {
                    (token.items || []).forEach(function(item) { appendMarkdownTokens(node, [item]); });
                } else if (token.type !== 'code' && token.type !== 'codespan' && token.type !== 'br') {
                    if (token.tokens) appendMarkdownTokens(node, token.tokens);
                    else if (token.text) node.textContent = decodeMarkdownText(token.text);
                }
                parent.appendChild(node);
            });
        }

        function renderSafeMarkdown(parent, text) {
            try { appendMarkdownTokens(parent, marked.lexer(String(text || ''), {gfm: true})); }
            catch(e) { parent.textContent = String(text || ''); }
        }

        function renderDiscussMarkdown(parent, text) {
            renderSafeMarkdown(parent, text);
        }

        function elementWith(className, text) {
            var node = document.createElement('div');
            node.className = className;
            if (text !== undefined) node.textContent = text;
            return node;
        }

        function renderDiscussSnapshot() {
            var snapshot = _discussSnapshot;
            if (!snapshot) return;
            setDiscussConnection(snapshot.connection || 'Live', snapshot.unavailable_reason || '');
            var log = document.getElementById('discussLog');
            var atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
            log.replaceChildren();
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
            groupDiscussTasks(snapshot.tasks || []).forEach(function(group) {
                log.appendChild(renderDiscussTask(group.latest, group.previous));
            });
            (snapshot.messages || []).forEach(function(message) {
                var wrap = elementWith('discuss-message ' + (message.role === 'user' ? 'user' : 'assistant'));
                var label = elementWith('discuss-message-label', message.role === 'user' ? 'You' : 'Codex');
                wrap.appendChild(label);
                if (message.role === 'assistant') renderDiscussMarkdown(wrap, message.text);
                else wrap.appendChild(document.createTextNode(message.text || ''));
                log.appendChild(wrap);
            });
            if ((snapshot.progress || []).length) {
                var progress = document.createElement('details'); progress.className = 'discuss-progress';
                var progressSummary = document.createElement('summary'); progressSummary.textContent = 'What Codex is doing'; progress.appendChild(progressSummary);
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
            (snapshot.notices || []).forEach(function(notice) {
                log.appendChild(elementWith(notice.kind === 'error' ? 'discuss-error' : 'discuss-queue', notice.message || ''));
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
                stopButton.textContent = 'Stop Codex';
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
            if (snapshot.active_turn_id) unavailableReason = 'Stop Codex before starting a new conversation.';
            else if (snapshot.active_request_id) unavailableReason = 'Wait for Codex to start this question before starting a new conversation.';
            else if ((snapshot.queue || []).length) unavailableReason = 'Remove or wait for queued items before starting a new conversation.';
            else if (pendingApproval) unavailableReason = 'Resolve the Codex approval request before starting a new conversation.';
            newConversation.disabled = !!unavailableReason;
            newConversation.title = unavailableReason;
            if (newConversationHint.textContent !== unavailableReason) newConversationHint.textContent = unavailableReason;
            newConversationHint.hidden = !unavailableReason;
            log.setAttribute('aria-busy', snapshot.active_turn_id ? 'true' : 'false');
            discussAfterActivity(atBottom);
            if (_discussLastApproval) {
                var target = log.querySelector('[data-approval-id="' + CSS.escape(_discussLastApproval) + '"] button');
                if (target) { target.focus(); document.getElementById('discussAnnouncement').textContent = 'Codex is requesting approval'; }
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
                    'Codex input limit · scanned ' + String(scope.files_scanned || 0)
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
                    : 'Restored from Codex history';
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

        function recentDiscussInstructions() {
            try { var rows = JSON.parse(localStorage.getItem('proseview-codex-recent-instructions') || '[]'); return Array.isArray(rows) ? rows.slice(0, 8) : []; }
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
            try { var rows = JSON.parse(localStorage.getItem('proseview-codex-favorite-instructions') || '[]'); return Array.isArray(rows) ? rows.slice(0, 12) : []; }
            catch(e) { return []; }
        }

        function toggleDiscussInstructionFavorite(value) {
            var rows = favoriteDiscussInstructions(); var index = rows.indexOf(value);
            if (index >= 0) rows.splice(index, 1); else rows.unshift(value);
            try { localStorage.setItem('proseview-codex-favorite-instructions', JSON.stringify(rows.slice(0, 12))); } catch(e) {}
            renderDiscussTaskMode();
        }

        function appendDiscussInstructionShortcut(node, value, favorite) {
            var wrap = elementWith('discuss-instruction-shortcut');
            var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-recent'; button.textContent = value;
            button.onclick = function() { document.getElementById('discussInput').value = value; saveDiscussDraft(); document.getElementById('discussInput').focus(); };
            var star = document.createElement('button'); star.type = 'button'; star.className = 'discuss-favorite'; star.textContent = favorite ? '★' : '☆';
            star.setAttribute('aria-label', (favorite ? 'Remove from favorites: ' : 'Add to favorites: ') + value);
            star.onclick = function() { toggleDiscussInstructionFavorite(value); };
            wrap.appendChild(button); wrap.appendChild(star); node.appendChild(wrap);
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
            var recents = recentDiscussInstructions();
            var favorites = favoriteDiscussInstructions();
            document.getElementById('discussInput').placeholder = _discussSelection
                ? 'Ask anything about this selection…'
                : 'Ask about this document…';
            node.hidden = !(_discussSelection && (recents.length || favorites.length));
            if (!node.hidden) {
                var label = document.createElement('span'); label.textContent = favorites.length ? 'Favorites and recent' : 'Recent instructions'; node.appendChild(label);
                favorites.slice(0, 3).forEach(function(value) { appendDiscussInstructionShortcut(node, value, true); });
                recents.filter(function(value) { return favorites.indexOf(value) < 0; }).slice(0, 3).forEach(function(value) { appendDiscussInstructionShortcut(node, value, false); });
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
            document.getElementById('discussAnnouncement').textContent = 'Stopping Codex';
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
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                var picker = document.getElementById('discussContextPicker');
                var resetDialog = document.getElementById('discussNewConversationDialog');
                var historyDialog = document.getElementById('discussHistoryDialog');
                if ((picker && !picker.hidden) || (resetDialog && resetDialog.open) || (historyDialog && historyDialog.open)) return;
                var panel = document.getElementById('discussPanel');
                if (panel && !panel.hidden) { event.preventDefault(); closeDiscuss(); }
            }
        });
        document.getElementById('discussLog').addEventListener('scroll', function() {
            if (this.scrollHeight - this.scrollTop - this.clientHeight < 70) document.getElementById('discussNewActivity').hidden = true;
        });
        (function initDiscussResize() {
            var handle = document.getElementById('discussResizeHandle'); var dragging = false; var startX = 0; var startWidth = 0;
            handle.addEventListener('mousedown', function(event) { dragging = true; startX = event.clientX; startWidth = document.getElementById('discussPanel').offsetWidth; handle.classList.add('is-dragging'); document.body.style.userSelect = 'none'; event.preventDefault(); });
            document.addEventListener('mousemove', function(event) { if (!dragging) return; var width = Math.max(340, Math.min(window.innerWidth - 180, startWidth + startX - event.clientX)); document.documentElement.style.setProperty('--utility-dock-w', width + 'px'); });
            document.addEventListener('mouseup', function() { if (!dragging) return; dragging = false; handle.classList.remove('is-dragging'); document.body.style.userSelect = ''; });
        })();
