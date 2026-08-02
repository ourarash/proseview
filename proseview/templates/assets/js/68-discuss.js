        // ── Document-aware Discuss with Codex ─────────────────────────────
        var _discussConversationId = null;
        var _discussSnapshot = null;
        var _discussDocumentKey = '';
        var _discussEventSource = null;
        var _discussAttachments = [];
        var _discussSelection = '';
        var _discussReturnFocus = null;
        var _discussRefreshTimer = null;
        var _discussLastApproval = '';

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
            return fetch(path, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Proseview-Session': discussSessionToken},
                body: JSON.stringify(body || {})
            }).then(function(response) {
                return response.json().catch(function() { return {}; }).then(function(data) {
                    if (!response.ok) throw new Error(data.error || ('Request failed (' + response.status + ')'));
                    return data;
                });
            });
        }

        function setDiscussConnection(state, reason) {
            var node = document.getElementById('discussConnection');
            node.textContent = state + (reason ? ' — ' + reason : '');
            node.dataset.state = state;
        }

        function openDiscuss(trigger) {
            var doc = discussDocument();
            if (!doc) {
                alert('Open a scene or supported text file before starting a discussion.');
                return;
            }
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            clearTimeout(_discussRefreshTimer);
            _discussReturnFocus = trigger || document.activeElement;
            _discussSelection = captureDiscussSelection();
            _discussAttachments = [];
            var panel = document.getElementById('discussPanel');
            panel.hidden = false;
            document.body.classList.add('discuss-open');
            if (typeof _termDock !== 'undefined' && _termDock === 'right') {
                var terminal = document.getElementById('terminalPanel');
                if (terminal && !terminal.hidden) terminal.hidden = true;
                document.body.classList.remove('terminal-right-open');
            }
            renderDiscussContext();
            setDiscussConnection('Restoring conversation', '');
            var key = discussDocumentKey(doc);
            _discussDocumentKey = key;
            discussApi('/api/discuss/conversations/open', doc).then(function(data) {
                if (_discussDocumentKey !== key) return;
                _discussConversationId = data.conversation_id;
                _discussSnapshot = data.snapshot;
                renderDiscussSnapshot();
                connectDiscussEvents();
                document.getElementById('discussInput').focus();
            }).catch(function(error) {
                setDiscussConnection('Unavailable', error.message);
                renderDiscussError(error.message);
            });
        }

        function closeDiscuss() {
            var panel = document.getElementById('discussPanel');
            panel.hidden = true;
            document.body.classList.remove('discuss-open');
            if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
            clearTimeout(_discussRefreshTimer);
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
            if (!_discussConversationId) return;
            var cid = _discussConversationId;
            var source = new EventSource('/api/discuss/conversations/' + encodeURIComponent(cid) + '/events');
            _discussEventSource = source;
            source.onopen = function() {
                if (_discussConversationId === cid && (!_discussSnapshot || _discussSnapshot.connection !== 'Unavailable')) {
                    setDiscussConnection('Live', '');
                }
            };
            source.onerror = function() {
                if (_discussConversationId === cid && source.readyState !== EventSource.CLOSED) setDiscussConnection('Reconnecting', '');
            };
            source.addEventListener('snapshot', function(event) {
                setDiscussConnection('Restoring conversation', '');
                _discussSnapshot = JSON.parse(event.data);
                renderDiscussSnapshot();
            });
            ['connection', 'conversation.reset', 'turn.queued', 'turn.started', 'turn.completed', 'response.completed', 'progress.delta',
             'plan.updated', 'activity.updated', 'approval.requested', 'approval.resolved', 'approval.expired', 'warning', 'error'].forEach(function(type) {
                source.addEventListener(type, function(event) {
                    if (type === 'connection') {
                        var detail = JSON.parse(event.data);
                        setDiscussConnection(detail.state, detail.reason || '');
                    }
                    if (type === 'approval.requested') {
                        var request = JSON.parse(event.data);
                        _discussLastApproval = request.request_id || '';
                    }
                    scheduleDiscussSnapshot();
                });
            });
            source.addEventListener('response.delta', function(event) {
                var detail = JSON.parse(event.data);
                appendDiscussStreamDelta(detail.text || '');
            });
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

        function safeDiscussUrl(value) {
            try {
                var parsed = new URL(value, location.href);
                return ['http:', 'https:', 'mailto:'].indexOf(parsed.protocol) >= 0 ? value : null;
            } catch(e) { return null; }
        }

        function appendMarkdownTokens(parent, tokens) {
            (tokens || []).forEach(function(token) {
                var node;
                if (token.type === 'space') return;
                if (token.type === 'text' || token.type === 'escape') {
                    if (token.tokens) appendMarkdownTokens(parent, token.tokens);
                    else parent.appendChild(document.createTextNode(token.text || token.raw || ''));
                    return;
                }
                if (token.type === 'html') { parent.appendChild(document.createTextNode(token.raw || token.text || '')); return; }
                if (token.type === 'paragraph') node = document.createElement('p');
                else if (token.type === 'heading') node = document.createElement('h' + Math.min(6, Math.max(1, token.depth || 3)));
                else if (token.type === 'strong') node = document.createElement('strong');
                else if (token.type === 'em') node = document.createElement('em');
                else if (token.type === 'codespan') { node = document.createElement('code'); node.textContent = token.text || ''; }
                else if (token.type === 'code') { node = document.createElement('pre'); var code = document.createElement('code'); code.textContent = token.text || ''; node.appendChild(code); }
                else if (token.type === 'blockquote') node = document.createElement('blockquote');
                else if (token.type === 'list') node = document.createElement(token.ordered ? 'ol' : 'ul');
                else if (token.type === 'list_item') node = document.createElement('li');
                else if (token.type === 'link') {
                    var href = safeDiscussUrl(token.href || '');
                    node = href ? document.createElement('a') : document.createElement('span');
                    if (href) { node.href = href; node.rel = 'noopener noreferrer'; if (node.protocol !== 'mailto:') node.target = '_blank'; }
                } else if (token.type === 'br') node = document.createElement('br');
                else { parent.appendChild(document.createTextNode(token.raw || token.text || '')); return; }
                if (token.type === 'list') {
                    (token.items || []).forEach(function(item) { appendMarkdownTokens(node, [item]); });
                } else if (token.type !== 'code' && token.type !== 'codespan' && token.type !== 'br') {
                    if (token.tokens) appendMarkdownTokens(node, token.tokens);
                    else if (token.text) node.textContent = token.text;
                }
                parent.appendChild(node);
            });
        }

        function renderDiscussMarkdown(parent, text) {
            try { appendMarkdownTokens(parent, marked.lexer(String(text || ''), {gfm: true})); }
            catch(e) { parent.textContent = String(text || ''); }
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
            if (!(snapshot.messages || []).length && !(snapshot.progress || []).length) {
                var empty = elementWith('discuss-empty');
                var title = document.createElement('strong'); title.textContent = 'Ask about what you are reading';
                empty.appendChild(title); empty.appendChild(document.createTextNode('Codex receives this document plus only the context you explicitly attach.'));
                log.appendChild(empty);
            }
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
            if ((snapshot.queue || []).length) log.appendChild(elementWith('discuss-queue', snapshot.queue.length + ' question' + (snapshot.queue.length === 1 ? '' : 's') + ' queued'));
            document.getElementById('discussStop').hidden = !snapshot.active_turn_id;
            var pendingApproval = (snapshot.approvals || []).some(function(approval) { return approval.status === 'pending'; });
            document.getElementById('discussNewConversation').disabled = !!snapshot.active_turn_id || !!(snapshot.queue || []).length || pendingApproval;
            log.setAttribute('aria-busy', snapshot.active_turn_id ? 'true' : 'false');
            discussAfterActivity(atBottom);
            if (_discussLastApproval) {
                var target = log.querySelector('[data-approval-id="' + CSS.escape(_discussLastApproval) + '"] button');
                if (target) { target.focus(); document.getElementById('discussAnnouncement').textContent = 'Codex is requesting approval'; }
                _discussLastApproval = '';
            }
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

        function renderDiscussError(message) {
            var log = document.getElementById('discussLog');
            var node = elementWith('discuss-error', message); log.appendChild(node); node.scrollIntoView({block: 'nearest'});
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
            if (doc) context.appendChild(elementWith('discuss-chip', doc.path));
            _discussAttachments.forEach(function(attachment, index) {
                var chip = elementWith('discuss-chip', attachment.path);
                var remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Remove ' + attachment.path);
                remove.onclick = function() { _discussAttachments.splice(index, 1); renderDiscussContext(); }; chip.appendChild(remove); context.appendChild(chip);
            });
            var selection = document.getElementById('discussSelectionChip');
            selection.hidden = !_discussSelection;
            selection.textContent = _discussSelection ? 'Selected text: ' + _discussSelection.slice(0, 80) : '';
        }

        function openDiscussContextPicker() {
            var tree = document.getElementById('discussPickerTree'); tree.replaceChildren();
            function visit(nodes, depth) {
                (nodes || []).forEach(function(node) {
                    if (!node.path) return;
                    var label = document.createElement('label'); label.style.paddingLeft = (depth * 16 + 2) + 'px';
                    var box = document.createElement('input'); box.type = 'checkbox'; box.value = node.path; box.dataset.kind = node.is_file ? 'file' : 'folder';
                    if (node.is_file && (!node.is_text || node.too_large)) {
                        box.disabled = true;
                        label.title = 'Only supported text files within the context limits can be attached';
                    }
                    if (_discussAttachments.some(function(item) { return item.path === node.path && item.kind === box.dataset.kind; })) box.checked = true;
                    label.appendChild(box); label.appendChild(document.createTextNode(' ' + (node.is_file ? '📄 ' : '📁 ') + (node.name || node.path))); tree.appendChild(label);
                    if (!node.is_file) visit(node.children, depth + 1);
                });
            }
            visit(repoTree, 0);
            document.getElementById('discussContextPicker').showModal();
        }

        function openNewDiscussConversationDialog() {
            var button = document.getElementById('discussNewConversation');
            if (!_discussConversationId || button.disabled) return;
            var dialog = document.getElementById('discussNewConversationDialog');
            var error = document.getElementById('discussNewConversationError');
            error.hidden = true; error.textContent = '';
            dialog.showModal();
            document.getElementById('discussNewConversationCancel').focus();
        }

        function confirmNewDiscussConversation(event) {
            event.preventDefault();
            if (!_discussConversationId) return;
            var dialog = document.getElementById('discussNewConversationDialog');
            var confirm = document.getElementById('discussNewConversationConfirm');
            var error = document.getElementById('discussNewConversationError');
            confirm.disabled = true;
            error.hidden = true; error.textContent = '';
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/new', {})
                .then(function(data) {
                    _discussSnapshot = data.snapshot;
                    _discussSelection = '';
                    _discussAttachments = [];
                    renderDiscussContext();
                    renderDiscussSnapshot();
                    dialog.close('confirmed');
                    document.getElementById('discussAnnouncement').textContent = 'New conversation started';
                    document.getElementById('discussInput').focus();
                })
                .catch(function(requestError) {
                    error.textContent = requestError.message;
                    error.hidden = false;
                    confirm.focus();
                })
                .finally(function() { confirm.disabled = false; });
        }

        document.getElementById('discussNewConversationDialog').addEventListener('close', function() {
            if (this.returnValue !== 'confirmed') document.getElementById('discussNewConversation').focus();
        });

        function applyDiscussContext(event) {
            event.preventDefault();
            _discussAttachments = Array.from(document.querySelectorAll('#discussPickerTree input:checked')).map(function(input) {
                return {kind: input.dataset.kind, path: input.value};
            });
            document.getElementById('discussContextPicker').close(); renderDiscussContext(); document.getElementById('discussInput').focus();
        }

        function sendDiscussQuestion() {
            var input = document.getElementById('discussInput');
            var question = input.value.trim();
            var button = document.getElementById('discussSend');
            if (!question || !_discussConversationId || button.disabled) return;
            var requestId = (crypto.randomUUID ? crypto.randomUUID() : 'pv-' + Date.now() + '-' + Math.random().toString(36).slice(2));
            button.disabled = true;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/questions', {
                client_request_id: requestId, question: question, selection: _discussSelection, attachments: _discussAttachments
            }).then(function() {
                input.value = ''; _discussSelection = ''; renderDiscussContext(); scheduleDiscussSnapshot();
                document.getElementById('discussAnnouncement').textContent = 'Question queued';
            }).catch(function(error) { renderDiscussError(error.message); }).finally(function() { button.disabled = false; input.focus(); });
        }

        function stopDiscussTurn() {
            if (!_discussSnapshot || !_discussSnapshot.active_turn_id) return;
            discussApi('/api/discuss/conversations/' + encodeURIComponent(_discussConversationId) + '/turns/' + encodeURIComponent(_discussSnapshot.active_turn_id) + '/stop', {})
                .then(scheduleDiscussSnapshot).catch(function(error) { renderDiscussError(error.message); });
        }

        document.getElementById('discussInput').addEventListener('keydown', function(event) {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendDiscussQuestion(); }
        });
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                var picker = document.getElementById('discussContextPicker');
                var resetDialog = document.getElementById('discussNewConversationDialog');
                if ((picker && picker.open) || (resetDialog && resetDialog.open)) return;
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
