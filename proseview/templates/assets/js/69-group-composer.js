// Shared model controls and the Group composer. Agent identity and conversation
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

var _groupDraftScene = '';
var _groupSkillCatalogs = Object.create(null);
var _groupSkillRequests = Object.create(null);
var _groupModelCatalogs = Object.create(null);
var _groupModelRequests = Object.create(null);
var _groupProviderStatus = null;
var _groupProviderStatusAt = 0;
var _groupProviderRequest = null;

function groupLoadProviderStatus(force) {
    if (!force && _groupProviderStatus && Date.now() - _groupProviderStatusAt < 30000) return Promise.resolve(_groupProviderStatus);
    if (!_groupProviderRequest) _groupProviderRequest = discussApi('/api/discuss/agents', {}).then(function(data) {
        if (!data.ok || !Array.isArray(data.agents)) throw new Error(data.error || 'Could not check agent availability');
        _groupProviderStatus = data.agents; _groupProviderStatusAt = Date.now();
        return data.agents;
    }).finally(function() { _groupProviderRequest = null; });
    return _groupProviderRequest;
}

function groupDraftKey(path) {
    return 'proseview-group-draft:book:' + repoRoot;
}
function _groupSaveDraft(path) {
    if (!path) return;
    var session = _groupSessionsByScene[path];
    var input = document.getElementById('groupInput');
    try {
        var previous = JSON.parse(sessionStorage.getItem(groupDraftKey(path)) || '{}'), current = path === _groupDraftScene;
        sessionStorage.setItem(groupDraftKey(path), JSON.stringify({text: current ? _groupDraftInput : previous.text || '',
            selection: current ? _groupPendingSelection : previous.selection || '', target: current ? _groupTargetChoice : previous.target || 'auto',
            selectionScene: current ? _groupPendingSelectionScene : previous.selectionScene || '',
            groupId: session && session.id || '', participants: session && session.participants,
            providerChosen: !!(session && session.providerChosen),
            pending: session && session.managed ? [] : session && session.pendingMessages || [], outbox: session && session.outbox || [], height: current && input ? input.style.height : previous.height || ''}));
    } catch (error) { /* An unavailable draft store must not prevent sending. */ }
}
function _groupLoadDraft(path) {
    if (_groupDraftScene === path) return;
    if (_groupDraftScene) { _groupDraftScene = path; _groupSessionFor(path); return; }
    _groupDraftScene = path;
    var saved = {};
    try {
        var legacyKey = 'proseview-group-draft:' + (((typeof meta !== 'undefined' && meta[path]) || {}).abs_path || path);
        saved = JSON.parse(sessionStorage.getItem(groupDraftKey(path)) || sessionStorage.getItem(legacyKey) || '{}');
    } catch (error) {}
    _groupDraftInput = saved.text || ''; _groupPendingSelection = saved.selection || '';
    _groupPendingSelectionScene = saved.selectionScene || path;
    _groupTargetChoice = ['critic1', 'critic2', 'both'].includes(saved.target) ? saved.target : 'auto';
    var session = _groupSessionFor(path);
    if (!session.turns.length && !session.participants && Array.isArray(saved.participants) && saved.participants.length === 2
            && saved.participants.every(function(p) { return _groupSettings.library.profiles.some(function(available) { return available.id === p.id; }); })) {
        session.participants = _groupProfiles(saved.participants.map(function(p) { return p.id; }));
        session.participants.forEach(function(p, index) {
            if (saved.providerChosen && DISCUSS_AGENTS.indexOf(saved.participants[index].agent) >= 0) {
                p.agent = saved.participants[index].agent;
            }
            p.model = saved.participants[index].model || '';
            p.effort = saved.participants[index].effort || '';
        });
        if (saved.providerChosen) session.participants = _groupSnapshotPair(session.participants);
        session.participantsChosen = true;
        session.providerChosen = !!saved.providerChosen;
    }
    if (!session.pendingMessages && Array.isArray(saved.pending)) { session.pendingMessages = saved.pending; session.queuePaused = !!saved.pending.length; }
    session.composerHeight = saved.height || '';
    if (!session.outbox && Array.isArray(saved.outbox)) session.outbox = saved.outbox;
    if (!session.id) session.id = session.outbox && session.outbox.length ? session.outbox[0].group_id : saved.groupId || '';
}
function groupRequestedSeats(text, session) {
    var mentioned = _groupMentionRecipients(text);
    if (mentioned.length) return mentioned;
    session = session || _groupSessionFor(_groupCurrentScenePath());
    var count = (session && session.participants && session.participants.length) || 2;
    var allSeats = Array.from({length: count}, function(_, i) { return i + 1; });
    var effective = typeof _groupEffectiveTarget === 'function' ? _groupEffectiveTarget(session) : 'all';
    if (/^critic(\d+)$/.test(effective)) {
        var seatNum = Number(RegExp.$1);
        if (seatNum >= 1 && seatNum <= count) return [seatNum];
    }
    return allSeats;
}
function submitGroupComposerMessage(options) { return submitManagedGroupMessage(options); }
function groupLoadSkills(agent) {
    if (_groupSkillCatalogs[agent]) return Promise.resolve(_groupSkillCatalogs[agent]);
    if (!_groupSkillRequests[agent]) _groupSkillRequests[agent] = discussApi('/api/discuss/skills', {agent: agent})
        .then(function(data) { _groupSkillCatalogs[agent] = data.skills || []; return _groupSkillCatalogs[agent]; })
        .finally(function() { delete _groupSkillRequests[agent]; });
    return _groupSkillRequests[agent];
}
function groupSkillForInvitation(participant, text) {
    if (!/(?:^|\s)\$/.test(text)) return Promise.resolve(null);
    return groupLoadSkills(participant.agent).then(function(skills) {
        var match = skills.find(function(skill) {
            return new RegExp('(?:^|\\s)\\$' + skill.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=$|[\\s.,;:!?])').test(text);
        });
        return match ? {name: match.name, path: match.path} : null;
    });
}
function groupLoadModelCatalog(agent) {
    var existing = _groupModelCatalogs[agent] || ((_groupSettings || {}).catalogs || {})[agent];
    if (existing && !existing.unavailable) return Promise.resolve(existing);
    if (!_groupModelRequests[agent]) _groupModelRequests[agent] = discussApi('/api/discuss/models', {agent: agent})
        .then(function(data) { _groupModelCatalogs[agent] = data.catalog; return data.catalog; })
        .finally(function() { delete _groupModelRequests[agent]; });
    return _groupModelRequests[agent];
}
function groupInsertContext(trigger) {
    var input = document.getElementById('groupInput');
    if (!input) return;
    input.focus();
    var start = input.selectionStart;
    input.setRangeText((start && !/\s/.test(input.value.charAt(start - 1)) ? ' ' : '') + trigger, start, input.selectionEnd, 'end');
    input.dispatchEvent(new Event('input', {bubbles: true}));
}
function createGroupModelControl(session, profile) {
    var wrap = elementWith('group-model-control');
    var chip = document.createElement('button'); chip.type = 'button'; chip.className = 'discuss-model-chip';
    chip.setAttribute('aria-haspopup', 'dialog'); chip.setAttribute('aria-expanded', 'false');
    chip.disabled = session.busy || !!(session.outbox && session.outbox.length);
    var panel = elementWith('discuss-model-picker group-model-picker'); panel.hidden = true;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Choose model for ' + profile.name);
    var head = elementWith('discuss-model-picker-head', profile.name + ' · ' + _groupAgentDisplay(profile.agent));
    var close = document.createElement('button'); close.type = 'button'; close.className = 'group-header-btn'; close.textContent = 'Close';
    close.setAttribute('aria-label', 'Close model picker');
    close.onclick = function() { panel.hidden = true; chip.setAttribute('aria-expanded', 'false'); chip.focus(); };
    head.appendChild(close);
    var list = elementWith('discuss-model-list'); list.setAttribute('role', 'radiogroup'); list.setAttribute('aria-label', 'Model');
    var desc = elementWith('discuss-model-effort-head');
    var effortLabel = document.createElement('strong'); effortLabel.textContent = 'Reasoning effort';
    var explanation = document.createElement('span'); desc.append(effortLabel, explanation);
    var efforts = elementWith('discuss-model-efforts'); efforts.setAttribute('role', 'group'); efforts.setAttribute('aria-label', 'Reasoning effort');
    var foot = elementWith('discuss-model-foot'); panel.append(head, list, desc, efforts, foot); wrap.append(chip, panel);
    var catalog = null, note = '', providerWarning = '', providerUnavailable = false, catalogWarning = '';
    function inherited() { return ((_groupSettings || {}).chat_models || {})[profile.agent] || {}; }
    function paintChip() {
        var selection = inherited(), id = profile.model || selection.model || '', row = discussModelRow(catalog, id);
        var name = row && row.label || id || (catalog && catalog.default && (catalog.default.label || catalog.default.model)) || 'Same as chat';
        var effort = profile.effort || selection.effort || (row && row.default_effort) || (catalog && catalog.default && catalog.default.effort) || '';
        var warning = providerWarning || catalogWarning;
        var label = providerUnavailable ? 'Agent unavailable' : providerWarning ? 'Availability unknown' : catalogWarning ? 'Models unavailable' : name + (effort ? ' · ' + effort : '');
        chip.textContent = (warning ? '⚠ ' : '') + profile.name + ' · ' + label + ' ▾';
        chip.dataset.warning = warning ? 'true' : 'false';
        chip.setAttribute('aria-label', 'Model for ' + profile.name + ': ' + (warning || name + (effort ? ', effort ' + effort : '')));
        chip.title = warning ? warning + ' Open the picker to retry.' : profile.name + ' · ' + _groupAgentDisplay(profile.agent) + ' · ' + name + (effort ? ' · ' + effort : '') + '. Applies to the next message in this Group.';
        chip.dataset.inherited = !profile.model && !profile.effort ? 'true' : 'false';
    }
    function save(model, effort) {
        profile.model = model; profile.effort = effort;
        _groupSaveDraft(session.scene); _saveGroupSession(session); paintChip(); paintOptions();
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
            agentLabel: _groupAgentDisplay(profile.agent), inheritLabel: 'Same as individual chat',
            inheritDescription: 'Follow the current ' + _groupAgentDisplay(profile.agent) + ' chat model and effort.',
            inheritEffortDescription: 'Inherited from the individual ' + _groupAgentDisplay(profile.agent) + ' chat',
            footNote: 'Applies to ' + profile.name + ' in this Group, from the next message. The reusable profile stays unchanged.',
            list: list, efforts: efforts, description: explanation, foot: foot, note: note,
            chooseModel: chooseModel, chooseEffort: function(value) { note = ''; save(profile.model, value); }});
    }
    chip.onclick = function() {
        var opening = panel.hidden;
        document.querySelectorAll('.group-model-picker').forEach(function(picker) { picker.hidden = true; });
        document.querySelectorAll('.group-model-control > button').forEach(function(button) { button.setAttribute('aria-expanded', 'false'); });
        panel.hidden = !opening; chip.setAttribute('aria-expanded', String(opening));
        if (!opening) return;
        if (catalog) { paintOptions(); list.querySelector('[aria-checked="true"]').focus(); }
        else list.textContent = 'Loading models…';
        loadCatalog(true);
    };
    paintChip();
    function loadCatalog(force) {
        groupLoadProviderStatus(force).then(function(rows) {
            var provider = rows.find(function(row) { return row.id === profile.agent; });
            providerUnavailable = !!(provider && !provider.available);
            providerWarning = provider && !provider.available ? _groupAgentDisplay(profile.agent) + ': ' + (provider.reason || 'Agent unavailable') : '';
        }).catch(function(error) { providerUnavailable = false; providerWarning = 'Availability unknown: ' + error.message; })
            .finally(function() { if (chip.isConnected) paintChip(); });
        return groupLoadModelCatalog(profile.agent).then(function(value) {
            if (!value) throw new Error('No model catalogue was returned.');
            catalog = value; catalogWarning = ''; if (chip.isConnected) { paintChip(); paintOptions(); }
        }).catch(function(error) {
            catalog = null; catalogWarning = 'Models unavailable: ' + error.message;
            list.textContent = catalogWarning + ' Close and reopen to retry.';
            if (chip.isConnected) paintChip();
        });
    }
    loadCatalog();
    return wrap;
}
function renderGroupQuickSend(node, session) {
    var hasDraft = !!_groupDraftInput.trim();
    var allPresets = presetDiscussInstructions();
    var presets = allPresets.filter(function(value) { return _groupPendingSelection || !discussInstructionNeedsSelection(value); });
    var recents = recentDiscussInstructions().filter(function(value) { return allPresets.indexOf(value) < 0 && (_groupPendingSelection || !discussInstructionNeedsSelection(value)); });
    node.replaceChildren(); node.hidden = !presets.length && !recents.length;
    node.appendChild(elementWith('discuss-presets-label', 'Quick send:'));
    var controls = {choose: function(value, details) {
        if (hasDraft) return;
        if (details) details.open = false;
        var field = document.getElementById('groupInput'); field.value = value; _groupDraftInput = value;
        submitGroupComposerMessage();
    }, refresh: function() {
        renderGroupQuickSend(node, session);
        var details = node.querySelector('details'); if (details) { details.open = true; details.querySelector('summary').focus(); }
    }};
    var inline = elementWith('discuss-presets-inline');
    presets.slice(0, 3).forEach(function(value) {
        var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-preset-inline'; button.textContent = value;
        button.onclick = function() { controls.choose(value); }; inline.appendChild(button);
    });
    node.appendChild(inline);
    if (allPresets.length > presets.length || presets.length > 3 || recents.length || favoriteDiscussInstructions().length) appendDiscussPresetsMenu(node, allPresets, recents, controls);
    node.querySelectorAll('.discuss-preset-inline, .discuss-preset-menu-choice').forEach(function(button) { button.disabled = hasDraft; });
}
function createGroupComposer(session) {
    var composer = elementWith('group-composer'); composer.id = 'groupComposer';
    var targetRow = elementWith('group-composer-bar'), targetLeft = elementWith('group-composer-target');
    targetLeft.appendChild(elementWith('group-apply-label', 'To:'));
    var target = document.createElement('select'); target.id = 'groupTargetSelect'; target.className = 'group-target-select'; target.setAttribute('aria-label', 'Group message recipient');
    var allLabel = typeof _groupAllLabel === 'function' ? _groupAllLabel(session)
        : (typeof _groupBothLabel === 'function' ? _groupBothLabel(session) : 'Group (All editors)');
    var items = [{value: 'all', name: allLabel}];
    var participants = (session && session.participants && session.participants.length) ? session.participants : [{seat: 1}, {seat: 2}];
    participants.forEach(function(p, idx) {
        var s = p.seat || (idx + 1);
        var seatLabel = (typeof _groupSeatLabel === 'function' ? _groupSeatLabel(s, session) : _groupSeatName(s)) + ' only';
        items.push({value: 'critic' + s, name: seatLabel});
    });
    items.forEach(function(item) {
        var option = document.createElement('option'); option.value = item.value; option.textContent = item.name; target.appendChild(option);
    });
    var effectiveTarget = typeof _groupEffectiveTarget === 'function' ? _groupEffectiveTarget(session) : 'all';
    if (effectiveTarget === 'both') effectiveTarget = 'all';
    target.value = effectiveTarget; target.onchange = function() { _groupTargetChoice = target.value; _groupSaveDraft(session.scene); };
    targetLeft.appendChild(target); targetRow.appendChild(targetLeft); composer.appendChild(targetRow);
    if (_groupPendingSelection) {
        var selection = elementWith('discuss-selection-chip group-selection-chip'); selection.id = 'groupSelectionChip';
        var words = _groupPendingSelection.trim().split(/\s+/).length;
        var excerpt = elementWith('discuss-selection-chip-text', 'Selection · ' + words + ' words · “' + _groupPendingSelection.replace(/\s+/g, ' ').slice(0, 72) + '”'); excerpt.title = _groupPendingSelection;
        var remove = document.createElement('button'); remove.type = 'button'; remove.className = 'group-selection-clear'; remove.setAttribute('aria-label', 'Remove selection'); remove.textContent = '×';
        remove.onclick = function() { _groupPendingSelection = ''; _groupPendingSelectionScene = ''; _groupSaveDraft(session.scene); renderSceneGroupPane(); };
        selection.append(excerpt, remove); composer.appendChild(selection);
    }
    var quick = elementWith('group-quick-send'); quick.id = 'groupQuickSend'; composer.appendChild(quick);
    var label = document.createElement('label'); label.className = 'sr-only'; label.htmlFor = 'groupInput'; label.textContent = 'Message the group'; composer.appendChild(label);
    var inputWrap = elementWith('group-input-wrap'), mirror = elementWith('group-input-mirror'); mirror.setAttribute('aria-hidden', 'true');
    var input = document.createElement('textarea'); input.id = 'groupInput'; input.className = 'group-input'; input.rows = 2; input.maxLength = 32768;
    input.setAttribute('aria-describedby', 'groupMentionHint'); input.placeholder = _groupPendingSelection ? 'Ask about this selection…' : 'Message the group…';
    input.title = 'Enter to send · Shift+Enter for a new line';
    input.value = _groupDraftInput; if (session.composerHeight) input.style.height = session.composerHeight;
    inputWrap.append(mirror, input); composer.appendChild(inputWrap);
    var toolbar = elementWith('discuss-send-row group-send-row'), actions = elementWith('discuss-composer-action-group group-composer-actions');
    var plus = document.createElement('button'); plus.type = 'button'; plus.className = 'discuss-context-button'; plus.id = 'groupContextButton'; plus.textContent = '+';
    plus.setAttribute('aria-label', 'Add people, files and folders'); plus.setAttribute('aria-haspopup', 'listbox'); plus.onclick = function() { groupInsertContext('@'); };
    actions.appendChild(plus); (session.participants || []).forEach(function(profile) { actions.appendChild(createGroupModelControl(session, profile)); });
    var sees = elementWith('discuss-sees-slot'), current = elementWith('discuss-sees', session.scene); current.title = 'Current scene shared with the Group: ' + session.scene; sees.appendChild(current); targetRow.appendChild(sees);
    var sendActions = elementWith('group-send-actions');
    var sendNow = document.createElement('button'); sendNow.type = 'button'; sendNow.id = 'groupSendNowBtn'; sendNow.className = 'group-send-now-btn'; sendNow.textContent = 'Send now';
    sendNow.hidden = !session.busy; sendNow.disabled = !_groupDraftInput.trim();
    sendNow.title = 'Send now (⌘/Ctrl+Enter) · Steer or run immediately';
    sendNow.onclick = function() { sendGroupComposerMessage({mode: 'now'}); };
    var send = document.createElement('button'); send.type = 'button'; send.id = 'groupSendBtn'; send.className = 'group-send-btn'; send.textContent = session.busy ? 'Queue' : 'Send';
    send.disabled = !_groupDraftInput.trim(); send.title = 'Send (Enter) · Shift+Enter for a new line'; send.onclick = function() { sendGroupComposerMessage(); };
    sendActions.append(sendNow, send);
    toolbar.append(actions, sendActions); composer.appendChild(toolbar);
    var menu = elementWith('group-mention-menu'); menu.id = 'groupMentionMenu'; menu.setAttribute('role', 'listbox'); menu.setAttribute('aria-label', 'Mention an editor or project file'); menu.hidden = true;
    var connection = elementWith('group-connection-status'); connection.id = 'groupConnectionStatus'; connection.setAttribute('role', 'status'); composer.appendChild(connection);
    var hint = elementWith('sr-only'); hint.id = 'groupMentionHint'; hint.setAttribute('aria-live', 'polite'); composer.append(menu, hint);
    function syncGroupInputState() {
        _groupDraftInput = input.value; send.disabled = !_groupDraftInput.trim(); sendNow.disabled = !_groupDraftInput.trim(); _groupSaveDraft(session.scene);
        paintGroupMentions(input, mirror); renderGroupQuickSend(quick, session);
    }
    input.oninput = syncGroupInputState;
    input.addEventListener('scroll', function() { paintGroupMentions(input, mirror); });
    wireChatMentionReplacement(input, _groupMentionOptions);
    _wireGroupMentions(input, menu, target, hint, function(nextValue) {
        input.value = nextValue;
        syncGroupInputState();
    });
    paintGroupMentions(input, mirror); renderGroupQuickSend(quick, session);
    editSelectionMount(editSelectionGroupScope(session), composer, input, quick, session);
    return composer;
}

document.addEventListener('mousedown', function(event) {
    if (event.target.closest && event.target.closest('.group-model-control')) return;
    document.querySelectorAll('.group-model-picker').forEach(function(panel) { panel.hidden = true; });
    document.querySelectorAll('.group-model-control > button').forEach(function(chip) { chip.setAttribute('aria-expanded', 'false'); });
});
document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape') return;
    var panel = document.querySelector('.group-model-picker:not([hidden])');
    if (!panel) return;
    event.preventDefault(); event.stopPropagation(); panel.hidden = true;
    var chip = panel.parentElement.querySelector('button'); chip.setAttribute('aria-expanded', 'false'); chip.focus();
}, true);

function groupClearEditedSelection(scenePath, files) {
    var selectedScene = _groupPendingSelectionScene || scenePath;
    if (!files.some(function(file) { var target = prosviewTargetForRepositoryPath(file); return target && target.kind === 'scene' && target.path === selectedScene; })) return;
    _groupPendingSelection = ''; _groupPendingSelectionScene = '';
    _groupSaveDraft(_groupDraftScene || scenePath);
}

function groupSkillMentionRanges(text) {
    var names = [];
    _groupMentionOptions().forEach(function(profile) {
        (_groupSkillCatalogs[profile.agent] || []).forEach(function(skill) { if (!names.includes(skill.name)) names.push(skill.name); });
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
