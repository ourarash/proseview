// Shared model controls and the Room composer. Agent identity and conversation
// state remain separate; the rendered model options are common to both chats.
function renderChatModelOptions(config) {
    var catalog = config.catalog, selection = config.selection, list = config.list, efforts = config.efforts;
    if (!catalog || !list) return;
    // Choosing anything rebuilds both rows, which would drop a keyboard
    // user back to the document. Remember where they were standing.
    var active = list.parentElement.contains(document.activeElement) ? document.activeElement : null;
    var restore = active && active.dataset && (active.dataset.discussModel !== undefined
        ? {kind: 'model', id: active.dataset.discussModel}
        : (active.dataset.discussEffort ? {kind: 'effort', id: active.dataset.discussEffort} : null));
    list.replaceChildren();
    var rows = [{
        id: '',
        label: config.inheritLabel || 'Follow ' + config.agentLabel + ' settings',
        description: config.inheritDescription || (catalog.default.label
            ? (catalog.default.label + (catalog.default.effort ? ' · ' + catalog.default.effort : '')
               + ', from ' + (catalog.default.source || 'your own configuration'))
            : (catalog.default.source || 'Whatever this agent is configured to use')),
        badge: 'Default'
    }].concat(catalog.models || []);
    rows.forEach(function(row) {
        var option = document.createElement('button');
        option.type = 'button';
        option.className = 'discuss-model-option';
        option.setAttribute('role', 'radio');
        var checked = (row.id || '') === selection.model;
        option.setAttribute('aria-checked', checked ? 'true' : 'false');
        option.appendChild(elementWith('discuss-model-option-tick', checked ? '●' : ''));
        var body = document.createElement('span');
        body.style.minWidth = '0';
        var name = document.createElement('strong');
        name.textContent = row.label || row.id;
        body.appendChild(name);
        body.appendChild(elementWith('', row.description || ''));
        option.appendChild(body);
        if (row.badge) option.appendChild(elementWith('discuss-model-badge', row.badge));
        else if (row.retiring) option.appendChild(elementWith('discuss-model-badge retiring', 'Retiring'));
        else option.appendChild(document.createElement('span'));
        option.dataset.discussModel = row.id || '';
        option.onclick = function() { config.chooseModel(row.id || ''); };
        list.appendChild(option);
    });
    var ladder = selection.model ? discussModelEfforts(catalog, selection.model) : [];
    var describedBy = null;
    efforts.replaceChildren();
    // Always the full union, with this model's missing rungs greyed
    // out: a row that silently loses its top entries hides the reason
    // a cheaper model cannot think as hard.
    discussModelEffortUnion(catalog).forEach(function(entry) {
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'discuss-model-effort-option';
        button.textContent = entry.id;
        var supported = !ladder.length ? false : ladder.some(function(row) { return row.id === entry.id; });
        button.disabled = !supported;
        var active = supported && selection.effort === entry.id;
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
        if (active) describedBy = entry.description || '';
        if (entry.description) button.title = entry.description;
        button.dataset.discussEffort = entry.id;
        button.onclick = function() { config.chooseEffort(entry.id); };
        efforts.appendChild(button);
    });
    if (restore) {
        var again = restore.kind === 'model'
            ? list.querySelector('[data-discuss-model="' + CSS.escape(restore.id) + '"]')
            : efforts.querySelector('[data-discuss-effort="' + CSS.escape(restore.id) + '"]:not(:disabled)');
        if (again) again.focus();
    }
    config.description.textContent = selection.model
        ? (describedBy || 'Model default')
        : config.inheritEffortDescription || 'Set by your ' + config.agentLabel + ' configuration';
    var foot = config.foot;
    if (config.note) {
        foot.textContent = config.note;
        foot.dataset.kind = 'warning';
    } else {
        foot.dataset.kind = 'info';
        foot.textContent = config.footNote || (selection.model
            ? 'Pinned to this conversation, from your next message on.'
            : 'Prosview sends no model, so ' + config.agentLabel + ' uses its own configuration.');
    }

}

var _roomDraftScene = '';
var _roomSkillCatalogs = Object.create(null);
var _roomSkillRequests = Object.create(null);
var _roomModelCatalogs = Object.create(null);
var _roomModelRequests = Object.create(null);

function roomDraftKey(path) {
    return 'proseview-room-draft:' + (((typeof meta !== 'undefined' && meta[path]) || {}).abs_path || path);
}
function _roomSaveDraft(path) {
    if (!path) return;
    var session = _roomSessionsByScene[path];
    var input = document.getElementById('roomInput');
    try {
        var previous = JSON.parse(sessionStorage.getItem(roomDraftKey(path)) || '{}'), current = path === _roomDraftScene;
        sessionStorage.setItem(roomDraftKey(path), JSON.stringify({text: current ? _roomDraftInput : previous.text || '',
            selection: current ? _roomPendingSelection : previous.selection || '', target: current ? _roomTargetChoice : previous.target || 'both',
            roomId: session && session.id || '', participants: session && session.participants,
            pending: session && session.managed ? [] : session && session.pendingMessages || [], outbox: session && session.outbox || [], height: current && input ? input.style.height : previous.height || ''}));
    } catch (error) { /* An unavailable draft store must not prevent sending. */ }
}
function _roomLoadDraft(path) {
    if (_roomDraftScene === path) return;
    _roomDraftScene = path;
    var saved = {};
    try { saved = JSON.parse(sessionStorage.getItem(roomDraftKey(path)) || '{}'); } catch (error) {}
    _roomDraftInput = saved.text || ''; _roomPendingSelection = saved.selection || '';
    _roomTargetChoice = ['both', 'critic1', 'critic2'].includes(saved.target) ? saved.target : 'both';
    var session = _roomSessionFor(path);
    if (!session.turns.length && !session.participants && Array.isArray(saved.participants) && saved.participants.length === 2
            && saved.participants.every(function(p) { return _roomSettings.library.profiles.some(function(available) { return available.id === p.id; }); })) {
        session.participants = _roomProfiles(saved.participants.map(function(p) { return p.id; }));
        session.participants.forEach(function(p, index) { p.model = saved.participants[index].model || ''; p.effort = saved.participants[index].effort || ''; });
        session.participantsChosen = true;
    }
    if (!session.pendingMessages && Array.isArray(saved.pending)) { session.pendingMessages = saved.pending; session.queuePaused = !!saved.pending.length; }
    session.composerHeight = saved.height || '';
    if (!session.outbox && Array.isArray(saved.outbox)) session.outbox = saved.outbox;
    if (!session.id) session.id = session.outbox && session.outbox.length ? session.outbox[0].room_id : saved.roomId || '';
}
function roomRequestedSeats(text) {
    var mentioned = _roomMentionRecipients(text);
    return mentioned.length ? mentioned : _roomTargetChoice === 'critic1' ? [1] : _roomTargetChoice === 'critic2' ? [2] : [1, 2];
}
function submitRoomComposerMessage() { return submitManagedRoomMessage(); }
function roomLoadSkills(agent) {
    if (_roomSkillCatalogs[agent]) return Promise.resolve(_roomSkillCatalogs[agent]);
    if (!_roomSkillRequests[agent]) _roomSkillRequests[agent] = discussApi('/api/discuss/skills', {agent: agent})
        .then(function(data) { _roomSkillCatalogs[agent] = data.skills || []; return _roomSkillCatalogs[agent]; })
        .finally(function() { delete _roomSkillRequests[agent]; });
    return _roomSkillRequests[agent];
}
function roomSkillForInvitation(participant, text) {
    if (!/(?:^|\s)\$/.test(text)) return Promise.resolve(null);
    return roomLoadSkills(participant.agent).then(function(skills) {
        var match = skills.find(function(skill) {
            return new RegExp('(?:^|\\s)\\$' + skill.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=$|[\\s.,;:!?])').test(text);
        });
        return match ? {name: match.name, path: match.path} : null;
    });
}
function roomLoadModelCatalog(agent) {
    var existing = _roomModelCatalogs[agent] || ((_roomSettings || {}).catalogs || {})[agent];
    if (existing && !existing.unavailable) return Promise.resolve(existing);
    if (!_roomModelRequests[agent]) _roomModelRequests[agent] = discussApi('/api/discuss/models', {agent: agent})
        .then(function(data) { _roomModelCatalogs[agent] = data.catalog; return data.catalog; })
        .finally(function() { delete _roomModelRequests[agent]; });
    return _roomModelRequests[agent];
}
function roomInsertContext(trigger) {
    var input = document.getElementById('roomInput');
    if (!input) return;
    input.focus();
    var start = input.selectionStart;
    input.setRangeText((start && !/\s/.test(input.value.charAt(start - 1)) ? ' ' : '') + trigger, start, input.selectionEnd, 'end');
    input.dispatchEvent(new Event('input', {bubbles: true}));
}
function createRoomModelControl(session, profile) {
    var wrap = elementWith('room-model-control');
    var chip = document.createElement('button'); chip.type = 'button'; chip.className = 'discuss-model-chip';
    chip.setAttribute('aria-haspopup', 'dialog'); chip.setAttribute('aria-expanded', 'false');
    chip.disabled = session.busy || !!(session.outbox && session.outbox.length);
    var panel = elementWith('discuss-model-picker room-model-picker'); panel.hidden = true;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Choose model for ' + profile.name);
    var head = elementWith('discuss-model-picker-head', profile.name + ' · ' + _roomAgentDisplay(profile.agent));
    var close = document.createElement('button'); close.type = 'button'; close.className = 'room-header-btn'; close.textContent = 'Close';
    close.setAttribute('aria-label', 'Close model picker');
    close.onclick = function() { panel.hidden = true; chip.setAttribute('aria-expanded', 'false'); chip.focus(); };
    head.appendChild(close);
    var list = elementWith('discuss-model-list'); list.setAttribute('role', 'radiogroup'); list.setAttribute('aria-label', 'Model');
    var desc = elementWith('discuss-model-effort-head');
    var effortLabel = document.createElement('strong'); effortLabel.textContent = 'Reasoning effort';
    var explanation = document.createElement('span'); desc.append(effortLabel, explanation);
    var efforts = elementWith('discuss-model-efforts'); efforts.setAttribute('role', 'group'); efforts.setAttribute('aria-label', 'Reasoning effort');
    var foot = elementWith('discuss-model-foot'); panel.append(head, list, desc, efforts, foot); wrap.append(chip, panel);
    var catalog = null, note = '';
    function inherited() { return ((_roomSettings || {}).chat_models || {})[profile.agent] || {}; }
    function paintChip() {
        var selection = inherited(), id = profile.model || selection.model || '', row = discussModelRow(catalog, id);
        var name = row && row.label || id || (catalog && catalog.default && (catalog.default.label || catalog.default.model)) || 'Same as chat';
        var effort = profile.effort || selection.effort || (row && row.default_effort) || (catalog && catalog.default && catalog.default.effort) || '';
        chip.textContent = profile.name + ' · ' + name + (effort ? ' · ' + effort : '') + ' ▾';
        chip.setAttribute('aria-label', 'Model for ' + profile.name + ': ' + name + (effort ? ', effort ' + effort : ''));
        chip.title = profile.name + ' · ' + _roomAgentDisplay(profile.agent) + '. Applies to the next message in this Room.';
        chip.dataset.inherited = !profile.model && !profile.effort ? 'true' : 'false';
    }
    function save(model, effort) {
        profile.model = model; profile.effort = effort;
        _roomSaveDraft(session.scene); _saveRoomSession(session); paintChip(); paintOptions();
    }
    function chooseModel(id) {
        if (!id) { note = ''; save('', ''); return; }
        var ladder = discussModelEfforts(catalog, id), requested = profile.effort || inherited().effort || (catalog.default || {}).effort || '';
        var supported = ladder.some(function(e) { return e.id === requested; });
        var effort = !requested || supported ? requested : ladder.length ? ladder[ladder.length - 1].id : '';
        note = requested && !supported ? requested + ' is not available on this model' + (effort ? '; using ' + effort + '.' : '.') : '';
        save(id, effort);
    }
    function paintOptions() {
        if (!catalog) return;
        renderChatModelOptions({catalog: catalog, selection: {model: profile.model || '', effort: profile.effort || ''},
            agentLabel: _roomAgentDisplay(profile.agent), inheritLabel: 'Same as individual chat',
            inheritDescription: 'Follow the current ' + _roomAgentDisplay(profile.agent) + ' chat model and effort.',
            inheritEffortDescription: 'Inherited from the individual ' + _roomAgentDisplay(profile.agent) + ' chat',
            footNote: 'Applies to ' + profile.name + ' in this Room, from the next message. The reusable profile stays unchanged.',
            list: list, efforts: efforts, description: explanation, foot: foot, note: note,
            chooseModel: chooseModel, chooseEffort: function(value) { note = ''; save(profile.model, value); }});
    }
    chip.onclick = function() {
        var opening = panel.hidden;
        document.querySelectorAll('.room-model-picker').forEach(function(picker) { picker.hidden = true; });
        document.querySelectorAll('.room-model-control > button').forEach(function(button) { button.setAttribute('aria-expanded', 'false'); });
        panel.hidden = !opening; chip.setAttribute('aria-expanded', String(opening));
        if (!opening) return;
        if (catalog) { paintOptions(); list.querySelector('[aria-checked="true"]').focus(); }
        else { list.textContent = 'Loading models…'; loadCatalog(); }
    };
    paintChip();
    function loadCatalog() {
        return roomLoadModelCatalog(profile.agent).then(function(value) {
            if (!value) throw new Error('No model catalogue was returned.');
            catalog = value; if (chip.isConnected) { paintChip(); paintOptions(); }
        }).catch(function(error) { list.textContent = 'Models unavailable: ' + error.message + ' Close and reopen to retry.'; });
    }
    loadCatalog();
    return wrap;
}
function renderRoomQuickSend(node, session) {
    var hasDraft = !!_roomDraftInput.trim();
    var presets = presetDiscussInstructions().filter(function(value) { return _roomPendingSelection || !discussInstructionNeedsSelection(value); });
    var recents = recentDiscussInstructions().filter(function(value) { return presets.indexOf(value) < 0 && (_roomPendingSelection || !discussInstructionNeedsSelection(value)); });
    node.replaceChildren(); node.hidden = !presets.length && !recents.length;
    node.appendChild(elementWith('discuss-presets-label', 'Quick send:'));
    var controls = {choose: function(value, details) {
        if (hasDraft) return;
        if (details) details.open = false;
        var field = document.getElementById('roomInput'); field.value = value; _roomDraftInput = value;
        submitRoomComposerMessage();
    }, refresh: function() {
        renderRoomQuickSend(node, session);
        var details = node.querySelector('details'); if (details) { details.open = true; details.querySelector('summary').focus(); }
    }};
    var inline = elementWith('discuss-presets-inline');
    presets.slice(0, 3).forEach(function(value) {
        var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-preset-inline'; button.textContent = value;
        button.onclick = function() { controls.choose(value); }; inline.appendChild(button);
    });
    node.appendChild(inline);
    if (presets.length > 3 || recents.length || favoriteDiscussInstructions().length) appendDiscussPresetsMenu(node, presets, recents, controls);
    node.querySelectorAll('.discuss-preset-inline, .discuss-preset-menu-choice').forEach(function(button) { button.disabled = hasDraft; });
}
function createRoomComposer(session) {
    var composer = elementWith('room-composer'); composer.id = 'roomComposer';
    var targetRow = elementWith('room-composer-bar'), targetLeft = elementWith('room-composer-target');
    targetLeft.appendChild(elementWith('room-apply-label', 'To:'));
    var target = document.createElement('select'); target.id = 'roomTargetSelect'; target.className = 'room-target-select'; target.setAttribute('aria-label', 'Room message recipient');
    [{value: 'both', name: 'Room (Both editors)'}, {value: 'critic1', name: _roomSeatName(1) + ' only'}, {value: 'critic2', name: _roomSeatName(2) + ' only'}].forEach(function(item) {
        var option = document.createElement('option'); option.value = item.value; option.textContent = item.name; target.appendChild(option);
    });
    target.value = _roomTargetChoice; target.onchange = function() { _roomTargetChoice = target.value; _roomSaveDraft(session.scene); };
    targetLeft.appendChild(target); targetRow.appendChild(targetLeft); composer.appendChild(targetRow);
    if (_roomPendingSelection) {
        var selection = elementWith('discuss-selection-chip room-selection-chip'); selection.id = 'roomSelectionChip';
        var words = _roomPendingSelection.trim().split(/\s+/).length;
        var excerpt = elementWith('discuss-selection-chip-text', 'Selection · ' + words + ' words · “' + _roomPendingSelection.replace(/\s+/g, ' ').slice(0, 72) + '”'); excerpt.title = _roomPendingSelection;
        var remove = document.createElement('button'); remove.type = 'button'; remove.className = 'room-selection-clear'; remove.setAttribute('aria-label', 'Remove selection'); remove.textContent = '×';
        remove.onclick = function() { _roomPendingSelection = ''; _roomSaveDraft(session.scene); renderSceneRoomPane(); };
        selection.append(excerpt, remove); composer.appendChild(selection);
    }
    var quick = elementWith('room-quick-send'); quick.id = 'roomQuickSend'; composer.appendChild(quick);
    var label = document.createElement('label'); label.className = 'sr-only'; label.htmlFor = 'roomInput'; label.textContent = 'Message the room'; composer.appendChild(label);
    var inputWrap = elementWith('room-input-wrap'), mirror = elementWith('room-input-mirror'); mirror.setAttribute('aria-hidden', 'true');
    var input = document.createElement('textarea'); input.id = 'roomInput'; input.className = 'room-input'; input.rows = 2; input.maxLength = 32768;
    input.setAttribute('aria-describedby', 'roomMentionHint'); input.placeholder = _roomPendingSelection ? 'Ask about this selection…' : 'Message the room…';
    input.title = 'Enter to send · Shift+Enter for a new line';
    input.value = _roomDraftInput; if (session.composerHeight) input.style.height = session.composerHeight;
    inputWrap.append(mirror, input); composer.appendChild(inputWrap);
    var toolbar = elementWith('discuss-send-row room-send-row'), actions = elementWith('discuss-composer-action-group room-composer-actions');
    var plus = document.createElement('button'); plus.type = 'button'; plus.className = 'discuss-context-button'; plus.id = 'roomContextButton'; plus.textContent = '+';
    plus.setAttribute('aria-label', 'Add people, files and folders'); plus.setAttribute('aria-haspopup', 'listbox'); plus.onclick = function() { roomInsertContext('@'); };
    actions.appendChild(plus); (session.participants || []).forEach(function(profile) { actions.appendChild(createRoomModelControl(session, profile)); });
    var sees = elementWith('discuss-sees-slot'), current = elementWith('discuss-sees', session.scene); current.title = 'Current scene shared with the Room: ' + session.scene; sees.appendChild(current); targetRow.appendChild(sees);
    var send = document.createElement('button'); send.type = 'button'; send.id = 'roomSendBtn'; send.className = 'room-send-btn'; send.textContent = session.busy ? 'Queue' : 'Send';
    send.disabled = !_roomDraftInput.trim(); send.title = 'Send (Enter) · Shift+Enter for a new line'; send.onclick = sendRoomComposerMessage;
    toolbar.append(actions, send); composer.appendChild(toolbar);
    var menu = elementWith('room-mention-menu'); menu.id = 'roomMentionMenu'; menu.setAttribute('role', 'listbox'); menu.setAttribute('aria-label', 'Mention an editor or project file'); menu.hidden = true;
    var connection = elementWith('room-connection-status'); connection.id = 'roomConnectionStatus'; connection.setAttribute('role', 'status'); composer.appendChild(connection);
    var hint = elementWith('sr-only'); hint.id = 'roomMentionHint'; hint.setAttribute('aria-live', 'polite'); composer.append(menu, hint);
    input.oninput = function() {
        _roomDraftInput = input.value; send.disabled = !_roomDraftInput.trim(); _roomSaveDraft(session.scene);
        paintRoomMentions(input, mirror); renderRoomQuickSend(quick, session);
    };
    input.addEventListener('scroll', function() { paintRoomMentions(input, mirror); });
    wireChatMentionReplacement(input, _roomMentionOptions); _wireRoomMentions(input, menu, target, hint);
    paintRoomMentions(input, mirror); renderRoomQuickSend(quick, session);
    return composer;
}

document.addEventListener('mousedown', function(event) {
    if (event.target.closest && event.target.closest('.room-model-control')) return;
    document.querySelectorAll('.room-model-picker').forEach(function(panel) { panel.hidden = true; });
    document.querySelectorAll('.room-model-control > button').forEach(function(chip) { chip.setAttribute('aria-expanded', 'false'); });
});
document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape') return;
    var panel = document.querySelector('.room-model-picker:not([hidden])');
    if (!panel) return;
    event.preventDefault(); event.stopPropagation(); panel.hidden = true;
    var chip = panel.parentElement.querySelector('button'); chip.setAttribute('aria-expanded', 'false'); chip.focus();
}, true);

function roomClearEditedSelection(scenePath, files) {
    if (!files.some(function(file) { var target = prosviewTargetForRepositoryPath(file); return target && target.kind === 'scene' && target.path === scenePath; })) return;
    if (_roomDraftScene === scenePath) _roomPendingSelection = '';
    else {
        try { var draft = JSON.parse(sessionStorage.getItem(roomDraftKey(scenePath)) || '{}'); draft.selection = ''; sessionStorage.setItem(roomDraftKey(scenePath), JSON.stringify(draft)); } catch (error) {}
    }
}

function roomSkillMentionRanges(text) {
    var names = [];
    _roomMentionOptions().forEach(function(profile) {
        (_roomSkillCatalogs[profile.agent] || []).forEach(function(skill) { if (!names.includes(skill.name)) names.push(skill.name); });
    });
    names.sort(function(a, b) { return b.length - a.length; });
    var ranges = [], pattern = /(^|\s)\$/g, match;
    while ((match = pattern.exec(text))) {
        var start = match.index + match[0].length - 1, rest = text.slice(start + 1);
        var name = names.find(function(value) { return rest.startsWith(value) && (!rest.charAt(value.length) || /[\s.,;:!?)]/.test(rest.charAt(value.length))); });
        if (name) ranges.push({start: start, end: start + name.length + 1, kind: 'skill', name: name});
    }
    return ranges;
}
