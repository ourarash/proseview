function groupForkElement(tagOrClass, classOrText, text) {
    if (arguments.length < 3) return elementWith(tagOrClass, classOrText);
    var el = document.createElement(tagOrClass); el.className = classOrText || ''; el.textContent = text || ''; return el;
}
// Single-chat forks and the shared conversation workflow picker.
var _groupForkDialogState = null;
var _groupForkLinks = Object.create(null);

function groupTransferWarnings(session) {
    return Array.from(new Set((session.runtime && session.runtime.handoff_warnings || session.handoffWarnings || []).filter(Boolean)));
}
function groupRuntimeNotice(session) {
    var notice = session.runtime && session.runtime.notice || '';
    // Older Groups repeat their transfer notes in the runtime notice above
    // the composer. Keep recovery notices there, and transfer details in history.
    groupTransferWarnings(session).forEach(function(warning) { notice = notice.split(warning).join(''); });
    return notice.trim();
}
function groupTransferredContextCard(session) {
    var warnings = groupTransferWarnings(session);
    if (!session.source && !warnings.length) return null;
    var card = document.createElement('details'); card.className = 'group-transferred-context';
    card.appendChild(groupForkElement('summary', '', 'Context transferred'));
    var options = session.runtime && session.runtime.context_options || {};
    card.appendChild(groupForkElement('p', 'settings-note', options.mode === 'recent'
        ? 'The selected recent exchanges and current scene were transferred. Other files remain available by reference.'
        : 'Conversation messages, request instructions, structured results, and available tool history were transferred.'));
    if (options.mode === 'recent' && (session.turns || []).some(function(turn) { return turn.role === 'context'; })) {
        card.appendChild(groupForkElement('p', 'settings-note', 'A summary of the earlier conversation is also included.'));
    }
    if (warnings.some(function(warning) { return /fresh session|new session|could not be forked/i.test(warning); })) {
        card.appendChild(groupForkElement('p', 'settings-note', 'Started a new session with transferred context.'));
    }
    if (warnings.length) {
        var technical = document.createElement('details'); technical.className = 'group-transfer-technical';
        technical.appendChild(groupForkElement('summary', '', 'Technical details'));
        warnings.forEach(function(warning) { technical.appendChild(groupForkElement('p', 'settings-note', warning)); });
        card.appendChild(technical);
    }
    return card;
}

function groupVisibleReply(text, streaming) {
    var lines = String(text || '').split('\n');
    return lines.filter(function(line, index) {
        var clean = line.trimStart();
        return !clean.startsWith('STANCE') && !(streaming && index === lines.length - 1 && clean && 'STANCE'.startsWith(clean));
    }).join('\n').trimEnd();
}
function groupHasAnswer(session) {
    return (session.turns || []).some(function(t) { return t.role === 'critic' && !t.passed && t.text; });
}
function groupSetPositions(id, checked) {
    var preset = _groupSettings.library.presets.find(function(p) { return p.id === id; });
    if (!preset) return;
    preset.positions_table = checked;
    var card = (_groupSettings.presets || []).find(function(p) { return p.id === id; });
    if (card) card.positions_table = checked;
    discussApi('/api/discuss/group-settings', {save: true, library: _groupSettings.library}).then(function(data) {
        if (!data.ok) throw new Error(data.error || 'Could not save the shared workflow option');
    }).catch(function(error) { if (typeof sidebarShowToast === 'function') sidebarShowToast(error.message, true); });
}
function createGroupPositionsOption(preset, change) {
    var label = document.createElement('label'); label.className = 'group-positions-option';
    var option = document.createElement('input'); option.type = 'checkbox'; option.checked = !!preset.positions_table;
    var title = 'Include agent positions in Discussion';
    option.setAttribute('aria-label', title + ' for ' + preset.name);
    option.onchange = function() { change(option.checked); };
    var copy = document.createElement('span');
    copy.appendChild(groupForkElement('span', 'group-positions-title', title));
    copy.appendChild(groupForkElement('span', 'group-positions-help', 'Keep agent-by-agent positions in a collapsed Discussion section beneath the recap.'));
    label.append(option, copy);
    return label;
}
function createGroupPresetCard(preset, session, choose, selected) {
    var wrap = groupForkElement('group-preset-choice');
    var button = document.createElement('button'); button.type = 'button';
    button.className = 'discuss-story-action group-starter-card'; button.dataset.preset = preset.id;
    if (selected) { button.classList.add('is-selected'); button.setAttribute('aria-pressed', 'true'); }
    var head = groupForkElement('group-starter-head');
    head.appendChild(groupForkElement('discuss-story-action-title', preset.name || preset.label));
    if (preset.badge) head.appendChild(groupForkElement('group-starter-badge', preset.badge));
    button.append(head, groupForkElement('discuss-story-action-copy', preset.description || preset.copy || ''));
    button.disabled = !!session.startingPreset || !!session.busy || preset.kind === 'workflow' && !groupHasAnswer(session);
    if (preset.kind === 'workflow' && !groupHasAnswer(session)) button.title = 'Ask for an answer before starting a second opinion';
    button.onclick = choose;
    wrap.appendChild(button);
    if (preset.kind === 'workflow') {
        wrap.appendChild(createGroupPositionsOption(preset, function(checked) {
            preset.positions_table = checked; groupSetPositions(preset.id, checked);
        }));
    }
    return wrap;
}
function openCurrentGroupWorkflow(session, preset) {
    if (session.busy || !groupHasAnswer(session)) return;
    session.pendingPreset = JSON.parse(JSON.stringify(preset));
    session.pendingPreset.profiles = session.participants.map(function(p) { return p.id; });
    startManagedGroupPreset(session);
}
function renderGroupWorkflowPicker(session, body) {
    var details = document.createElement('details'); details.className = 'group-workflow-picker';
    details.open = !!session.startingPreset;
    details.appendChild(groupForkElement('summary', '', 'Conversation workflows'));
    if (session.startingPreset) details.appendChild(groupForkElement('p', 'settings-note', 'Checking agents…'));
    var list = groupForkElement('discuss-story-actions');
    ((_groupSettings || {}).library || {presets: []}).presets.filter(function(p) { return p.kind === 'workflow'; }).forEach(function(p) {
        list.appendChild(createGroupPresetCard(p, session, function() { openCurrentGroupWorkflow(session, p); }));
    });
    details.appendChild(list); body.appendChild(details);
}
function groupPositionsCard(session, turn) {
    var box = document.createElement('details'); box.className = 'group-positions-card';
    box.appendChild(groupForkElement('summary', '', 'Discussion · agent positions'));
    var scroll = groupForkElement('md-table-scroll'), table = document.createElement('table');
    table.setAttribute('aria-label', 'Recorded positions');
    var head = document.createElement('tr');
    ['Suggestion'].concat(session.participants.map(function(p) { return p.name; }), ['Evidence']).forEach(function(name) { head.appendChild(groupForkElement('th', '', name)); });
    var thead = document.createElement('thead'); thead.appendChild(head); table.appendChild(thead);
    var tbody = document.createElement('tbody');
    turn.positions.forEach(function(row) {
        var tr = document.createElement('tr'); tr.appendChild(groupForkElement('td', '', row.id + '. ' + row.suggestion));
        var evidence = [];
        session.participants.forEach(function(_, idx) {
            var seat = idx + 1;
            var position = row.agents[String(seat)];
            tr.appendChild(groupForkElement('td', position ? 'group-stance-' + position.stance : '', position ? position.stance : ''));
            if (position) evidence.push(session.participants[seat - 1].name + ': ' + position.evidence);
        });
        tr.appendChild(groupForkElement('td', '', evidence.join(' · '))); tbody.appendChild(tr);
    });
    table.appendChild(tbody); scroll.appendChild(table); box.appendChild(scroll);
    box.appendChild(groupForkElement('p', 'settings-note', 'Only explicit final positions are shown. A blank cell means no stance was recorded.'));
    return box;
}
function syncDiscussGroupFork() {
    var send = document.getElementById('discussSend');
    if (!send) return;
    var button = document.getElementById('discussGroupFork');
    if (!button) {
        button = document.createElement('button'); button.type = 'button'; button.id = 'discussGroupFork';
        button.className = 'discuss-secondary'; button.textContent = 'Send to Group'; button.onclick = openDiscussGroupFork;
        send.parentElement.insertBefore(button, send);
    }
    var s = _discussSnapshot || {}, active = _groupActiveSession;
    button.disabled = !_discussConversationId || !!s.active_request_id || !!s.active_turn_id || (s.queue || []).length > 0
        || (s.approvals || []).some(function(p) { return p.status === 'pending' || p.status === 'resolving'; })
        || !!(active && (active.busy || (active.outbox || []).length))
        || !(s.messages || []).some(function(m) { return m.role === 'assistant'; }) && !(s.tasks || []).some(function(t) { return t.result; });
    button.title = button.disabled ? 'Finish running work and approvals, and wait for an answer before forking' : 'Continue this conversation with two or three assistants';
    var key = _discussConversationId + ':' + (s.thread_id || '');
    if (_discussConversationId && !_groupForkLinks[key]) {
        _groupForkLinks[key] = [];
        discussApi('/api/discuss/group-fork', {action: 'links', conversation_id: _discussConversationId}).then(function(data) {
            _groupForkLinks[key] = data.groups || []; syncDiscussGroupForkLink(key);
        }).catch(function() {});
    }
    syncDiscussGroupForkLink(key);
}
function syncDiscussGroupForkLink(key) {
    var s = _discussSnapshot || {};
    if (key !== _discussConversationId + ':' + (s.thread_id || '')) return;
    var existing = document.getElementById('discussForkGroupLink'); if (existing) existing.remove();
    var rows = _groupForkLinks[key] || [], parent = document.getElementById('discussGroupFork');
    if (!rows.length || !parent) return;
    var button = document.createElement('button'); button.type = 'button'; button.id = 'discussForkGroupLink'; button.className = 'discuss-secondary'; button.textContent = 'Open Group ↗';
    button.onclick = function() { openGroupHistorySession(rows[0].scene, rows[0].id).then(function() { showScenePanelTab('group'); }); };
    parent.parentElement.insertBefore(button, parent);
}
function openGroupForkSource(source) {
    if (_discussEventSource) { _discussEventSource.close(); _discussEventSource = null; }
    _discussAgent = source.agent; _applyDiscussAgentLabels();
    openDiscuss(null, {document: source.document || {kind: 'scene', path: source.scene}, threadId: source.thread_id});
}
function groupForkPayload(state) {
    var scene = _groupCurrentScenePath();
    return {conversation_id: state.conversationId, scene: scene, participants: state.participants,
        workflow: state.workflow, context_options: state.contextOptions,
        positions_table: ((_groupSettings.library.presets.find(function(p) { return p.id === state.workflow; }) || {}).positions_table), live_document: discussLiveDocumentFor({kind: 'scene', path: scene})};
}
function openDiscussGroupFork() {
    if (!_discussConversationId || document.getElementById('discussGroupFork').disabled) return;
    var dialog = document.getElementById('discussGroupForkDialog');
    if (!dialog) {
        dialog = document.createElement('dialog'); dialog.id = 'discussGroupForkDialog'; dialog.className = 'group-fork-dialog';
        dialog.setAttribute('aria-labelledby', 'groupForkTitle'); document.body.appendChild(dialog);
        dialog.oncancel = function(event) { var s = _groupForkDialogState; if (s && s.creating) { event.preventDefault(); if (s.summarizing) cancelGroupForkSummary(s); } else _groupForkDialogState = null; };
    }
    var state = {conversationId: _discussConversationId, participants: [], workflow: '', loading: true, warnings: [], limits: [], error: '', contextOptions: groupForkContextPreferences(), counts: {}, attempt: 0};
    _groupForkDialogState = state;
    renderDiscussGroupFork(); dialog.showModal();
    _ensureGroupSettingsLoaded().then(function() {
        return discussApi('/api/discuss/group-fork', {conversation_id: state.conversationId, scene: _groupCurrentScenePath(),
            live_document: discussLiveDocumentFor({kind: 'scene', path: _groupCurrentScenePath()}), context_options: state.contextOptions});
    }).then(function(data) {
        if (_groupForkDialogState !== state) return;
        if (!data.ok) throw new Error(data.error || 'Could not prepare the Group');
        state.participants = data.participants; state.original = Object.assign({}, data.participants[0]);
        state.warnings = data.warnings || []; state.limits = data.limit_errors || []; state.counts = data.context_counts || {}; state.loading = false;
        renderDiscussGroupFork();
    }).catch(function(error) { state.loading = false; state.error = error.message; renderDiscussGroupFork(); });
}
function renderDiscussGroupFork() {
    var state = _groupForkDialogState, dialog = document.getElementById('discussGroupForkDialog'); if (!state || !dialog) return;
    var focused = document.activeElement && dialog.contains(document.activeElement) ? document.activeElement.id : '';
    dialog.replaceChildren();
    var head = groupForkElement('div', ''); head.className = 'group-fork-head';
    var title = groupForkElement('h2', '', 'Send to Group'); title.id = 'groupForkTitle';
    head.append(title, groupForkElement('p', 'settings-note', 'Fork this conversation through its latest completed turn.')); dialog.appendChild(head);
    var body = groupForkElement('div', ''); body.className = 'group-fork-body';
    if (state.summarizing) {
        var progress = groupForkElement('p', 'group-fork-summary-progress', 'Summarizing ' + (state.counts.older || 0) + ' earlier exchanges…'); progress.setAttribute('role', 'status');
        body.append(progress, groupForkElement('p', 'settings-note', 'Your recent exchanges stay in full. The source chat stays unchanged.')); dialog.appendChild(body);
        var progressFoot = groupForkElement('group-fork-footer'); var stop = document.createElement('button'); stop.type = 'button'; stop.id = 'groupForkCancelSummary'; stop.textContent = state.cancelRequested ? 'Stopping…' : 'Cancel'; stop.disabled = !!state.cancelRequested; stop.onclick = function() { cancelGroupForkSummary(state); }; progressFoot.appendChild(stop); dialog.appendChild(progressFoot); return;
    }
    if (state.loading) body.appendChild(groupForkElement('p', '', 'Preparing conversation context…'));
    if (state.participants.length >= 2) {
        var countBar = groupForkElement('div', 'group-room-size-toggle');
        countBar.style.marginBottom = '10px';
        countBar.appendChild(groupForkElement('span', 'group-apply-label', 'Participants:'));
        [2, 3].forEach(function(count) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'group-header-btn group-room-size-btn' + (state.participants.length === count ? ' is-active' : '');
            btn.textContent = count + ' agents';
            btn.setAttribute('aria-pressed', state.participants.length === count ? 'true' : 'false');
            btn.onclick = function() {
                if (state.participants.length === count) return;
                if (count === 2) {
                    state.removedThird = Object.assign({}, state.participants[2]);
                    state.participants = state.participants.slice(0, 2);
                } else {
                    var third = state.removedThird || (function() {
                        var used = new Set(state.participants.map(function(p) { return p.agent; }));
                        var agent = DISCUSS_AGENTS.find(function(a) { return !used.has(a); }) || 'agy';
                        return {id: 'fork-3', name: 'Third perspective', agent: agent, model: '', effort: '', specialty: '', style: ''};
                    })();
                    state.participants = state.participants.concat([third]);
                }
                state.limits = [];
                renderDiscussGroupFork();
                checkGroupForkContext(state);
            };
            countBar.appendChild(btn);
        });
        body.appendChild(countBar);
    }
    var grid = groupForkElement('div', ''); grid.className = 'group-fork-models';
    state.participants.forEach(function(profile, index) {
        var card = groupForkElement('group-fork-model'); card.appendChild(groupForkElement('strong', '', profile.name));
        var provider = document.createElement('select'); provider.setAttribute('aria-label', profile.name + ' provider');
        DISCUSS_AGENTS.forEach(function(p) { var option = document.createElement('option'); option.value = p; option.textContent = _groupAgentDisplay(p); provider.appendChild(option); });
        provider.value = profile.agent;
        provider.onchange = function() { profile.agent = provider.value; profile.model = ''; profile.effort = ''; profile.custom = false; state.limits = []; renderDiscussGroupFork(); checkGroupForkContext(state); };
        var pLabel = groupForkElement('label', '', 'Provider'); pLabel.appendChild(provider); card.appendChild(pLabel);
        var model = document.createElement('select'); model.setAttribute('aria-label', profile.name + ' model');
        var initial = document.createElement('option'); initial.value = ''; initial.textContent = 'Provider default'; model.appendChild(initial);
        var catalog = _groupModelCatalogs[profile.agent];
        (catalog && catalog.models || []).forEach(function(row) { var option = document.createElement('option'); option.value = row.id; option.textContent = row.label || row.id; model.appendChild(option); });
        if (profile.model && !Array.from(model.options).some(function(o) { return o.value === profile.model; })) { var custom = document.createElement('option'); custom.value = profile.model; custom.textContent = profile.model; model.appendChild(custom); }
        var customOption = document.createElement('option'); customOption.value = '__custom'; customOption.textContent = 'Custom model…'; model.appendChild(customOption);
        model.value = profile.custom ? '__custom' : profile.model;
        model.onchange = function() { if (model.value === '__custom') { profile.custom = true; profile.model = ''; profile.effort = ''; renderDiscussGroupFork(); } else { profile.model = model.value; profile.custom = false; profile.effort = ''; state.limits = []; renderDiscussGroupFork(); checkGroupForkContext(state); } };
        var mLabel = groupForkElement('label', '', 'Model'); mLabel.appendChild(model); card.appendChild(mLabel);
        if (profile.custom) { var input = document.createElement('input'); input.id = 'groupForkCustom' + index; input.setAttribute('aria-label', profile.name + ' custom model'); input.placeholder = 'Configured model ID'; input.value = profile.model; input.oninput = function() { profile.model = input.value.trim(); state.limits = []; checkGroupForkContext(state); }; card.appendChild(input); }
        var effort = document.createElement('select'); effort.setAttribute('aria-label', profile.name + ' reasoning effort');
        var effortDef = document.createElement('option'); effortDef.value = ''; effortDef.textContent = 'Provider default'; effort.appendChild(effortDef);
        var modelRow = catalog && (catalog.models || []).find(function(row) { return row.id === profile.model; });
        var supportedEfforts = modelRow && modelRow.supportedReasoningEfforts && modelRow.supportedReasoningEfforts.length
            ? modelRow.supportedReasoningEfforts.map(function(e) { return e.reasoningEffort || e; })
            : ['low', 'medium', 'high', 'xhigh', 'max'];
        if (profile.effort && !supportedEfforts.includes(profile.effort)) supportedEfforts = supportedEfforts.concat([profile.effort]);
        supportedEfforts.forEach(function(effId) { var option = document.createElement('option'); option.value = effId; option.textContent = effId; effort.appendChild(option); });
        effort.value = profile.effort || '';
        effort.onchange = function() { profile.effort = effort.value; };
        var eLabel = groupForkElement('label', '', 'Reasoning effort'); eLabel.appendChild(effort); card.appendChild(eLabel);
        grid.appendChild(card);
        if (!catalog && !state['loading-' + profile.agent]) {
            state['loading-' + profile.agent] = true;
            groupLoadModelCatalog(profile.agent).then(function() { if (_groupForkDialogState === state && dialog.open) renderDiscussGroupFork(); }).catch(function() {});
        }
    });
    body.appendChild(grid);
    if (state.original && (state.original.agent !== state.participants[0].agent || state.original.model !== state.participants[0].model)) {
        body.appendChild(groupForkElement('p', 'settings-note', 'Changing the Original assistant’s provider or model starts a fresh session with the transferred conversation context.'));
    }
    if (state.participants.length) {
        renderGroupForkContextChoices(state, body);
        body.appendChild(groupForkElement('h3', '', 'Conversation workflow'));
        var manual = document.createElement('button'); manual.type = 'button'; manual.className = 'discuss-story-action group-fork-manual';
        manual.classList.toggle('is-selected', !state.workflow); manual.textContent = 'None — I’ll direct it'; manual.setAttribute('aria-pressed', String(!state.workflow));
        manual.onclick = function() { state.workflow = ''; renderDiscussGroupFork(); }; body.appendChild(manual);
        _groupSettings.library.presets.filter(function(p) { return p.kind === 'workflow'; }).forEach(function(p) {
            body.appendChild(createGroupPresetCard(p, {turns: [{role: 'critic', text: 'Existing answer'}]}, function() { state.workflow = p.id; renderDiscussGroupFork(); }, state.workflow === p.id));
        });
        var note = document.createElement('details'); note.className = 'group-fork-context'; note.appendChild(groupForkElement('summary', '', 'What will the agents receive?'));
        note.appendChild(groupForkElement('p', '', state.contextOptions.mode === 'recent' ? 'Recent exchanges retain request instructions, structured results, and quotations. The current scene is included once with line numbers, using your unsaved draft. Other files remain available by reference. Pending approvals and apply actions stay in the source chat.' : 'Visible messages, request instructions, structured results, current scenes and files, and available tool history are transferred. The current scene has line numbers. Pending approvals and apply actions stay in the source chat.'));
        (state.warnings || []).forEach(function(w) { note.appendChild(groupForkElement('p', 'settings-note', w)); }); body.appendChild(note);
    }
    if (state.error) { var error = groupForkElement('p', 'group-error-text', state.error); error.setAttribute('role', 'alert'); body.appendChild(error); }
    (state.limits || []).forEach(function(message) { body.appendChild(groupForkElement('p', 'group-error-text', message)); });
    dialog.appendChild(body);
    var foot = groupForkElement('div', ''); foot.className = 'group-fork-footer';
    var cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel'; cancel.onclick = function() { dialog.close(); _groupForkDialogState = null; }; foot.appendChild(cancel);
    var confirm = document.createElement('button'); confirm.type = 'button'; confirm.id = 'groupForkConfirm'; confirm.className = 'group-send-btn'; confirm.textContent = state.creating ? 'Forking…' : state.workflow ? 'Fork & run' : 'Fork to Group';
    confirm.disabled = state.loading || state.creating || state.checking || !state.participants.length || state.participants.some(function(p) { return p.custom && !p.model; }) || !!((state.workflow || state.contextOptions.mode === 'recent') && state.limits.length);
    confirm.onclick = function() { runGroupFork(state); };
    foot.appendChild(confirm); dialog.appendChild(foot);
    if (state.creating) dialog.querySelectorAll('button,input,select').forEach(function(el) { el.disabled = true; });
    else if (focused && document.getElementById(focused)) document.getElementById(focused).focus({preventScroll: true});
}

function groupForkContextPreferences() {
    var value = {};
    try { value = JSON.parse(localStorage.getItem('proseview-group-fork-context') || '{}'); } catch (error) {}
    if (!value || typeof value !== 'object') value = {};
    return {mode: value.mode === 'recent' ? 'recent' : 'whole', exchanges: Math.max(1, Math.min(10, Math.round(Number(value.exchanges) || 3))), include_summary: value.include_summary !== false};
}
function renderGroupForkContextChoices(state, body) {
    body.appendChild(groupForkElement('h3', '', 'Conversation context'));
    [['whole', 'Whole conversation', 'All messages, request instructions, and available evidence.'], ['recent', 'Recent exchanges', 'Keep recent requests and replies in full. Optionally summarize the rest.']].forEach(function(choice) {
        var label = document.createElement('label'); label.className = 'group-fork-context-choice';
        label.classList.toggle('is-selected', state.contextOptions.mode === choice[0]);
        var radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'groupForkContextMode'; radio.value = choice[0]; radio.checked = state.contextOptions.mode === choice[0]; radio.setAttribute('aria-label', choice[1]);
        radio.onchange = function() { state.contextOptions.mode = choice[0]; state.limits = []; renderDiscussGroupFork(); checkGroupForkContext(state); };
        var copy = document.createElement('span'); copy.append(groupForkElement('strong', '', choice[1]), groupForkElement('span', 'settings-note', choice[2])); label.append(radio, copy); body.appendChild(label);
    });
    if (state.contextOptions.mode !== 'recent') return;
    var box = groupForkElement('group-fork-recent-options');
    var countLabel = document.createElement('label'); countLabel.className = 'group-fork-count'; countLabel.appendChild(document.createTextNode('Keep the last '));
    var count = document.createElement('input'); count.type = 'number'; count.min = '1'; count.max = '10'; count.step = '1'; count.value = state.contextOptions.exchanges; count.id = 'groupForkExchangeCount'; count.setAttribute('aria-label', 'Number of recent exchanges');
    count.oninput = function() { var n = Number(count.value); if (Number.isInteger(n) && n >= 1 && n <= 10) { state.contextOptions.exchanges = n; checkGroupForkContext(state); } };
    count.onchange = function() { state.contextOptions.exchanges = Math.max(1, Math.min(10, Math.round(Number(count.value) || 1))); count.value = state.contextOptions.exchanges; checkGroupForkContext(state); };
    countLabel.append(count, document.createTextNode(' exchanges')); box.appendChild(countLabel);
    box.appendChild(groupForkElement('p', 'settings-note', state.checking ? 'Checking the selected context…' : (state.counts.kept || 0) + ' of ' + (state.counts.total || 0) + ' exchanges kept in full. An exchange includes your request and its assistant replies.'));
    var summaryLabel = document.createElement('label'); summaryLabel.className = 'group-positions-option';
    var summary = document.createElement('input'); summary.type = 'checkbox'; summary.id = 'groupForkIncludeSummary'; summary.checked = state.contextOptions.include_summary;
    summary.onchange = function() { state.contextOptions.include_summary = summary.checked; renderDiscussGroupFork(); };
    var copy = document.createElement('span'); copy.append(groupForkElement('span', 'group-positions-title', 'Include a summary of earlier exchanges'), groupForkElement('span', 'group-positions-help', (state.counts.older || 0) + ' earlier exchanges. A selected summary is made when you fork.'));
    summaryLabel.append(summary, copy); box.appendChild(summaryLabel);
    box.appendChild(groupForkElement('p', 'group-fork-fresh-note', 'All participants start fresh sessions with this context.'));
    body.appendChild(box);
}
function checkGroupForkContext(state) {
    clearTimeout(state.checkTimer); state.checking = true; state.error = '';
    var version = state.checkVersion = (state.checkVersion || 0) + 1;
    var confirm = document.getElementById('groupForkConfirm'); if (confirm) confirm.disabled = true;
    state.checkTimer = setTimeout(function() {
        if (_groupForkDialogState !== state || state.creating) return;
        discussApi('/api/discuss/group-fork', groupForkPayload(state)).then(function(data) {
            if (_groupForkDialogState !== state || version !== state.checkVersion) return;
            if (!data.ok) throw new Error(data.error || 'Could not check context');
            state.counts = data.context_counts || {}; state.warnings = data.warnings || []; state.limits = data.limit_errors || []; state.checking = false; renderDiscussGroupFork();
        }).catch(function(error) { if (_groupForkDialogState === state && version === state.checkVersion) { state.checking = false; state.error = error.message; renderDiscussGroupFork(); } });
    }, 250);
}
async function cancelGroupForkSummary(state) {
    state.cancelRequested = true; renderDiscussGroupFork();
    if (!state.summaryId || state.cancelling) return;
    state.cancelling = true;
    try {
        var result = await discussApi('/api/discuss/group-fork', {action: 'cancel-summary', conversation_id: state.conversationId, summary_id: state.summaryId});
        if (!result.ok) throw new Error(result.error || 'Could not cancel summary');
        state.attempt++; state.creating = state.summarizing = state.cancelRequested = state.cancelling = false; state.summaryId = ''; renderDiscussGroupFork();
    } catch (error) { state.cancelling = false; state.cancelRequested = false; state.error = error.message; renderDiscussGroupFork(); }
}
async function runGroupFork(state) {
    var attempt = ++state.attempt; state.creating = true; state.error = ''; state.cancelRequested = false; renderDiscussGroupFork();
    var payload = groupForkPayload(state);
    try {
        var checked = await discussApi('/api/discuss/group-fork', payload);
        if (!checked.ok) throw new Error(checked.error || 'Could not check the handoff');
        state.counts = checked.context_counts || {}; state.limits = checked.limit_errors || [];
        if ((state.workflow || state.contextOptions.mode === 'recent') && state.limits.length) throw new Error(state.limits.join(' '));
        if (state.contextOptions.mode === 'recent' && state.contextOptions.include_summary && state.counts.older) {
            state.summarizing = true; renderDiscussGroupFork();
            var started = await discussApi('/api/discuss/group-fork', Object.assign({}, payload, {action: 'summarize'}));
            if (!started.ok) throw new Error(started.error || 'Could not prepare summary');
            state.summaryId = started.summary_id;
            while (true) {
                if (state.cancelRequested) { await cancelGroupForkSummary(state); return; }
                if (state.attempt !== attempt || _groupForkDialogState !== state) return;
                var job = await discussApi('/api/discuss/group-fork', {action: 'summary-state', conversation_id: state.conversationId, summary_id: state.summaryId});
                if (!job.ok) throw new Error(job.error || 'The summary is no longer available');
                if (state.cancelRequested || state.attempt !== attempt) continue;
                if (job.status === 'cancelled') { state.creating = state.summarizing = false; renderDiscussGroupFork(); return; }
                if (job.status === 'ready') break;
                await new Promise(function(resolve) { setTimeout(resolve, 300); });
            }
            payload.summary_id = state.summaryId; state.summarizing = false; renderDiscussGroupFork();
        }
        if (state.attempt !== attempt || state.cancelRequested) return;
        var data = await discussApi('/api/discuss/group-fork', Object.assign({}, payload, {action: 'create'}));
        if (!data.ok || !data.group) throw new Error(data.error || 'Could not fork the conversation');
        try { localStorage.setItem('proseview-group-fork-context', JSON.stringify(state.contextOptions)); } catch (error) {}
        var group = data.group, scene = group.scene;
        editSelectionTransferToGroup(group.id);
        if (_groupActiveSession) _saveGroupSession(_groupActiveSession);
        if (_groupSessionsByScene[scene] && _groupSessionsByScene[scene] !== _groupActiveSession) _saveGroupSession(_groupSessionsByScene[scene]);
        var session = {id: group.id, scene: scene, turns: [], plans: [], participants: group.participants, participantsChosen: true, providerChosen: true};
        _groupActiveSession = session; _groupSessionsByScene[scene] = session; _groupDraftScene = scene; _groupDraftInput = ''; _groupPendingSelection = ''; _groupHistoryChecked.book = true;
        groupRuntimeApply(session, group, {render: false});
        var key = state.conversationId + ':' + ((_discussSnapshot || {}).thread_id || '');
        _groupForkLinks[key] = [{id: group.id, scene: scene}].concat(_groupForkLinks[key] || []);
        document.getElementById('discussGroupForkDialog').close(); _groupForkDialogState = null; showScenePanelTab('group'); groupRuntimePoll(session, true);
    } catch (error) {
        if (state.attempt !== attempt) return;
        state.creating = state.summarizing = false; state.summaryId = ''; state.error = error.message; renderDiscussGroupFork();
    }
}
