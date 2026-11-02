// The server owns accepted messages, invitations and replies. This file only
// projects saved Room state and submits idempotent user commands.
var _roomRuntimePolls = Object.create(null);

function roomRuntimeInitial(session) {
    return {id: session.id, scene: session.scene, participants: _roomEnsureParticipants(session),
        title: session.topicLabel || 'Conversation', badge: session.topicBadge || '', preset_id: session.presetId || '',
        created_at: session.createdAt || 0, question: session.question || '',
        turns: session.turns.map(function(turn) {
            var row = Object.assign({}, turn);
            if (row.role === 'user' || row.role === 'invitation') row.attachments = discussMentionsIn(row.text.split('\n\nSelected passage:\n')[0]);
            return row;
        }), plans: roomRuntimePlans(session)};
}
function roomRuntimePlans(session) {
    return (session.plans || []).map(function(plan) { return {
        after_turn: plan.afterTurn, agent: plan.agent || '', authors_call: plan.authorsCall || '', open: plan.open || [],
        items: plan.items.map(function(item) { return {title: item.title, detail: item.detail, line: item.line || '',
            original: item.original || '', replacement: item.replacement || '', proposed_by: item.proposedBy || '',
            accepted: !!item.accepted, checked: !!item.checked, applied: item.applied || '', todoAdded: !!item.todoAdded}; })
    }; });
}
function roomRuntimeEnvelope(session, action, payload) {
    if (!session.id) { session.id = _roomNewId(); session.createdAt = Date.now() / 1000; }
    var body = Object.assign({action: action, room_id: session.id, request_id: _roomNewId()}, payload || {});
    if (!session.managed) body.initial = roomRuntimeInitial(session);
    return JSON.parse(JSON.stringify(body));
}
function roomRuntimeRequest(session, body, options) {
    return discussApi('/api/discuss/room-run', body).then(function(data) {
        if (!data.ok || !data.room) throw new Error(data.error || 'Could not read the Room state');
        roomRuntimeApply(session, data.room, options);
        roomRuntimePoll(session);
        return data.room;
    });
}
function roomRuntimeApply(session, state, options) {
    options = options || {};
    var oldRevision = session.runtime && session.runtime.revision;
    session.managed = true;
    if (!state.unchanged) {
        var previous = session.turns;
        session.turns = state.turns.map(function(turn, index) {
            var old = previous.find(function(row) { return turn.step_id ? row.step_id === turn.step_id && row.role === turn.role
                : turn.message_id ? row.message_id === turn.message_id : previous[index] === row && row.role === turn.role && row.text === turn.text; });
            if (!old && session.runtime && turn.changed_files) roomClearEditedSelection(session.scene, turn.changed_files);
            return old ? Object.assign(old, turn) : turn;
        });
        if (!options.preserveModels) {
            session.participants = state.participants.map(function(profile, index) {
                var old = (session.participants || [])[index];
                return old && old.id === profile.id ? Object.assign(old, profile) : profile;
            });
        }
        session.runtimeModelsKey = JSON.stringify(state.participants.map(function(p) { return [p.model, p.effort]; }));
        session.runtime = state;
        session.topicLabel = state.title || session.topicLabel || 'Conversation';
        session.topicBadge = state.badge || ''; session.presetId = state.preset_id || '';
        session.createdAt = state.created_at || session.createdAt;
        session.id = state.id;
        session.queue = state.steps.filter(function(step) { return step.state === 'queued'; });
        var posted = new Set(state.turns.filter(function(turn) { return turn.message_id; }).map(function(turn) { return turn.message_id; }));
        var seen = new Set();
        session.pendingMessages = state.steps.filter(function(step) {
            if (step.kind !== 'message' || step.state !== 'queued' || posted.has(step.message_id) || seen.has(step.message_id)) return false;
            seen.add(step.message_id); return true;
        }).map(function(step) { return {id: step.message_id, text: step.text}; });
        var acknowledged = state.acknowledged_requests || [];
        var oldOutboxLength = (session.outbox || []).length;
        session.outbox = (session.outbox || []).filter(function(body) { return !acknowledged.includes(body.request_id); });
        if (oldOutboxLength > session.outbox.length) session.sendError = '';
        delete _roomHistoryList[session.scene];
    } else {
        Object.assign(session.runtime, {status: state.status, live: state.live, partial_reply: state.partial_reply});
    }
    var current = session.runtime;
    var active = current.steps && current.steps.find(function(step) { return step.id === current.active_step; });
    session.busy = ['running', 'recovering'].includes(current.status) || !!(active && active.state === 'interrupting') || current.status === 'idle' && current.steps.some(function(step) { return step.state === 'queued'; });
    session.error = current.error || '';
    session.queuePaused = ['paused', 'interrupted'].includes(current.status);
    session.runId = active && active.run_id || '';
    session.statusText = current.status === 'recovering' ? 'Recovering the interrupted invitation…' : active && active.state === 'interrupting'
        ? 'Stopping the current invitation…' : active ? _roomSpeakerName(active.seat, session.participants[active.seat - 1].agent) + (active.recap ? ' is recapping…' : ' is replying…') : '';
    var live = state.live;
    session.live = session.busy ? {statusText: session.statusText, elapsed: live && live.elapsed || 0,
        progress: live && live.progress || '', steps: live && live.steps || [], draft: live && live.draft || '',
        conversationId: live && live.conversation_id || '', approvals: live && live.approvals || []} : null;
    _roomSaveDraft(session.scene);
    if (options.render === false || session.scene !== _roomCurrentScenePath()) return;
    if (oldRevision !== current.revision || !document.getElementById('roomComposer')) renderSceneRoomPane();
    else if (session.live) _renderRoomLive();
}
function roomRuntimePoll(session) {
    if (_roomRuntimePolls[session.id]) return;
    var tick = function() {
        if (_roomSessionsByScene[session.scene] !== session || !roomTabIsOpen() || _roomCurrentScenePath() !== session.scene) {
            delete _roomRuntimePolls[session.id]; return;
        }
        _roomRuntimePolls[session.id] = true;
        discussApi('/api/discuss/room-run', {action: 'state', room_id: session.id, after_revision: session.runtime && session.runtime.revision})
            .then(function(data) { if (data.ok && data.room) { roomRuntimeApply(session, data.room); if (!session.sendError) drainRoomOutbox(session); } })
            .catch(function(error) {
                var hint = document.getElementById('roomConnectionStatus');
                if (hint) { hint.textContent = 'Connection interrupted. The server keeps accepted work; reconnecting…'; hint.title = error.message; }
            }).finally(function() { _roomRuntimePolls[session.id] = setTimeout(tick, 800); });
    };
    _roomRuntimePolls[session.id] = setTimeout(tick, 800);
}
function attachManagedRoom(session) {
    if (!session.id) return Promise.resolve();
    return roomRuntimeRequest(session, roomRuntimeEnvelope(session, 'state')).then(function() {
        drainRoomOutbox(session);
    });
}
function roomRuntimeControl(session, action, payload) {
    if (action === 'retry') payload = Object.assign({}, payload, {review_choices: roomReviewChoices(session)});
    return roomRuntimeRequest(session, roomRuntimeEnvelope(session, action, payload)).catch(function(error) {
        session.error = error.message; renderSceneRoomPane(); throw error;
    });
}
function roomReviewChoices(session) {
    var choices = [];
    session.turns.filter(function(turn) { return turn.review_pending; }).forEach(function(turn) {
        var review = _roomReviewContexts.get(turn), saved = {};
        if (!review) {
            try { saved = JSON.parse(sessionStorage.getItem('proseview-room-review:' + turn.tool_conversation_id) || '{}'); } catch (error) {}
        }
        var keep = review ? review.keep : saved.keep || {}, fingerprints = review ? review.fingerprints || {} : saved.fingerprints || {};
        Object.keys(keep).forEach(function(path) {
            var drop = Object.keys(keep[path]).filter(function(id) { return keep[path][id] === false; }).map(Number);
            if (drop.length) choices.push({conversation_id: turn.tool_conversation_id, path: path, drop: drop, fingerprint: fingerprints[path] || ''});
        });
    });
    return choices;
}
function drainRoomOutbox(session) {
    if (session.sendingOutbox || !session.outbox || !session.outbox.length) return;
    session.sendingOutbox = true;
    var body = session.outbox[0];
    roomRuntimeRequest(session, body).then(function() {
        session.outbox = session.outbox.filter(function(row) { return row.request_id !== body.request_id; });
        session.sendError = '';
    }).catch(function(error) {
        if (session.outbox.some(function(row) { return row.request_id === body.request_id; })) session.sendError = 'Message not confirmed: ' + error.message + ' Retry sending; an accepted message will not run twice.';
    }).finally(function() {
        session.sendingOutbox = false; _roomSaveDraft(session.scene); roomRuntimePoll(session);
        if (session.scene === _roomCurrentScenePath()) renderSceneRoomPane();
        if (!session.sendError) drainRoomOutbox(session);
    });
}
function submitManagedRoomMessage() {
    var scene = _roomCurrentScenePath(), session = _roomSessionFor(scene), input = document.getElementById('roomInput');
    var text = input ? input.value.trim() : _roomDraftInput.trim();
    if (!scene || !text) return;
    var body = roomRuntimeEnvelope(session, 'submit', {message_id: _roomNewId(), text: _roomWithSelection(text), authored: text,
        seats: roomRequestedSeats(text), attachments: discussMentionsIn(text), review_choices: roomReviewChoices(session), live_document: discussLiveDocumentFor({kind: 'scene', path: scene})});
    if (!session.outbox) session.outbox = [];
    session.outbox.push(body);
    rememberDiscussInstruction(text);
    _roomDraftInput = ''; if (input) input.value = '';
    session.busy = true; session.statusText = 'Sending message…';
    _roomSaveDraft(scene); renderSceneRoomPane(); drainRoomOutbox(session);
}
function startManagedRoomPreset(session) {
    var preset = session.pendingPreset;
    if (!preset) return;
    session.id = _roomNewId(); session.createdAt = Date.now() / 1000;
    session.topicLabel = preset.name; session.presetId = preset.id;
    session.topicBadge = preset.invitations.length + ' invitations' + (preset.recap ? ' + recap' : '');
    var invitations = preset.invitations.map(function(step) { return {seat: step.seat, prompt: step.prompt, attachments: discussMentionsIn(step.prompt)}; });
    if (preset.recap) invitations.push({seat: preset.recap, recap: true, prompt: 'Summarize where we landed and any agreed action items.'});
    var body = roomRuntimeEnvelope(session, 'preset', {invitations: invitations});
    session.pendingPreset = null; session.outbox = [body];
    session.busy = true; session.statusText = 'Starting discussion…';
    _roomSaveDraft(session.scene); renderSceneRoomPane(); drainRoomOutbox(session);
}
function saveManagedRoom(session) {
    if (!session.managed) { _roomSaveDraft(session.scene); return; }
    if (session._saving) { session._saveAgain = true; return; }
    session._saving = true;
    var models = JSON.stringify(session.participants.map(function(p) { return [p.model, p.effort]; }));
    var action = models !== session.runtimeModelsKey ? 'models' : 'preferences';
    var body = roomRuntimeEnvelope(session, action, action === 'models' ? {participants: session.participants} : {plans: roomRuntimePlans(session)});
    roomRuntimeRequest(session, body, {render: false, preserveModels: true}).catch(function(error) {
        session.error = error.message; renderSceneRoomPane();
        return roomRuntimeRequest(session, {action: 'state', room_id: session.id}).catch(function() {});
    }).finally(function() {
        session._saving = false;
        if (session._saveAgain) { session._saveAgain = false; saveManagedRoom(session); }
    });
}
function renderManagedRoomQueue(session, body) {
    var outbox = session.outbox || [], pending = session.pendingMessages || [];
    if (outbox.length || pending.length) {
        var box = elementWith('discuss-queue room-message-queue');
        var heading = document.createElement('strong'); heading.textContent = pending.length + outbox.length + ' message' + (pending.length + outbox.length === 1 ? '' : 's') + ' queued'; box.appendChild(heading);
        pending.forEach(function(message, index) {
            var row = elementWith('discuss-queue-item', message.text);
            var remove = document.createElement('button'); remove.type = 'button'; remove.className = 'discuss-queue-remove'; remove.textContent = 'Remove';
            remove.setAttribute('aria-label', 'Remove queued message ' + (index + 1));
            remove.onclick = function() { remove.disabled = true; roomRuntimeControl(session, 'remove', {message_id: message.id}).catch(function() {}); };
            row.appendChild(remove); box.appendChild(row);
        });
        outbox.forEach(function(request) { box.appendChild(elementWith('discuss-queue-item', request.text || 'Starting the discussion preset…')); });
        if (session.sendError) {
            box.appendChild(elementWith('room-error-text', session.sendError));
            var retry = document.createElement('button'); retry.type = 'button'; retry.className = 'room-header-btn'; retry.textContent = 'Retry sending';
            retry.onclick = function() { session.sendError = ''; drainRoomOutbox(session); }; box.appendChild(retry);
        }
        body.appendChild(box);
    }
    var state = session.runtime;
    if (!state) return;
    if (state.notice) body.appendChild(elementWith('room-runtime-notice', state.notice));
    if (state.status === 'interrupted' || state.status === 'paused') {
        var recovery = elementWith('room-runtime-recovery');
        var active = state.steps.find(function(step) { return step.id === state.active_step; });
        if (state.partial_reply) {
            var partial = elementWith('room-interrupted-reply discuss-message');
            partial.appendChild(elementWith('room-turn-tag', 'Partial reply · interrupted'));
            renderDiscussMarkdown(partial, state.partial_reply); recovery.appendChild(partial);
        }
        var interrupted = active && active.state === 'interrupted';
        (interrupted ? [{action:'retry', label:'Retry interrupted invitation'}, {action:'skip', label:'Skip interrupted invitation'}]
            : [{action:'resume', label:'Resume remaining invitations'}]).forEach(function(option) {
            var button = document.createElement('button'); button.type = 'button'; button.className = 'room-header-btn'; button.textContent = option.label;
            button.disabled = session.busy;
            button.onclick = function() { button.disabled = true; roomRuntimeControl(session, option.action).catch(function() {}); }; recovery.appendChild(button);
        });
        body.appendChild(recovery);
    }
}
