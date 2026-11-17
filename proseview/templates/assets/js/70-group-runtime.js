// The server owns accepted messages, invitations and replies. This file only
// projects saved Group state and submits idempotent user commands.
var _groupRuntimePolls = Object.create(null);

function groupRuntimeInitial(session) {
    return {id: session.id, scene: session.scene, participants: _groupEnsureParticipants(session),
        title: session.topicLabel || 'Conversation', badge: session.topicBadge || '', preset_id: session.presetId || '',
        created_at: session.createdAt || 0, question: session.question || '',
        turns: session.turns.map(function(turn) {
            var row = Object.assign({}, turn);
            if (row.role === 'user' || row.role === 'invitation') row.attachments = discussMentionsIn(String(row.text || '').split(/\n\nSelected passage(?:\s*\([^)\n]*\))?:\n/)[0]);
            return row;
        }), plans: groupRuntimePlans(session)};
}
function groupRuntimePlans(session) {
    return (session.plans || []).map(function(plan) { return {
        after_turn: plan.afterTurn, agent: plan.agent || '', authors_call: plan.authorsCall || '', open: plan.open || [],
        items: plan.items.map(function(item) { return {title: item.title, detail: item.detail, line: item.line || '',
            original: item.original || '', replacement: item.replacement || '', proposed_by: item.proposedBy || '',
            accepted: !!item.accepted, checked: !!item.checked, applied: item.applied || '', todoAdded: !!item.todoAdded}; })
    }; });
}
function groupRuntimeEnvelope(session, action, payload) {
    if (!session.id) { session.id = _groupNewId(); session.createdAt = Date.now() / 1000; }
    var body = Object.assign({action: action, group_id: session.id, request_id: _groupNewId()}, payload || {});
    if (!session.managed) body.initial = groupRuntimeInitial(session);
    return JSON.parse(JSON.stringify(body));
}
function groupRuntimeRequest(session, body, options) {
    return discussApi('/api/discuss/group-run', body).then(function(data) {
        if (!data.ok || !data.group) throw new Error(data.error || 'Could not read the Group state');
        if (body.group_id !== session.id) return data.group;
        groupRuntimeApply(session, data.group, options);
        groupRuntimePoll(session, true);
        return data.group;
    });
}
function groupRuntimeApply(session, state, options) {
    options = options || {};
    var oldRevision = session.runtime && session.runtime.revision;
    session.managed = true;
    if (!state.unchanged) {
        var previous = session.turns;
        session.turns = state.turns.map(function(turn, index) {
            var old = previous.find(function(row) { return turn.step_id ? row.step_id === turn.step_id && row.role === turn.role
                : turn.message_id ? row.message_id === turn.message_id : previous[index] === row && row.role === turn.role && row.text === turn.text; });
            if (!old && session.runtime && turn.changed_files) groupClearEditedSelection(session.scene, turn.changed_files);
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
        session.originScene = state.scene;
        delete _groupHistoryList.book;
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
        ? 'Stopping the current invitation…' : active ? _groupSpeakerName(active.seat, session.participants[active.seat - 1].agent) + (active.recap ? ' is recapping…' : ' is replying…') : '';
    var live = state.live;
    session.live = session.busy ? {statusText: session.statusText, elapsed: live && live.elapsed || 0,
        progress: live && live.progress || '', steps: live && live.steps || [], draft: live && live.draft || '',
        conversationId: live && live.conversation_id || '', approvals: live && live.approvals || []} : null;
    _groupSaveDraft(session.scene);
    if (options.render === false || session.scene !== _groupCurrentScenePath()) return;
    if (oldRevision !== current.revision || !document.getElementById('groupComposer')) renderSceneGroupPane();
    else if (session.live) _renderGroupLive();
}
function groupRuntimePoll(session, wake) {
    var key = session.id, existing = _groupRuntimePolls[key];
    if (existing && existing.session !== session) {
        clearTimeout(existing.timer); delete _groupRuntimePolls[key]; existing = null;
    }
    if (existing) {
        if (wake) {
            existing.idleDelay = 5000;
            if (existing.running) existing.wake = true;
            else { clearTimeout(existing.timer); existing.timer = setTimeout(existing.tick, 0); }
        }
        return;
    }
    var poll = {session: session, running: false, idleDelay: 5000, timer: null, wake: false};
    function visible() {
        return session.id === key && !document.hidden && _groupSessionsByScene[session.scene] === session
            && groupTabIsOpen() && _groupCurrentScenePath() === session.scene;
    }
    var tick = function() {
        if (_groupRuntimePolls[key] !== poll) return;
        if (!visible()) { delete _groupRuntimePolls[key]; return; }
        poll.running = true;
        var revision = session.runtime && session.runtime.revision;
        discussApi('/api/discuss/group-run', {action: 'state', group_id: session.id, after_revision: session.runtime && session.runtime.revision})
            .then(function(data) {
                if (_groupRuntimePolls[key] !== poll || !visible()) return;
                if (!data.ok || !data.group) throw new Error(data.error || 'Could not read the Group state');
                groupRuntimeApply(session, data.group);
                var hint = document.getElementById('groupConnectionStatus');
                if (hint) { hint.textContent = ''; hint.title = ''; }
                if (!session.sendError) drainGroupOutbox(session);
                poll.idleDelay = revision !== data.group.revision ? 5000 : Math.min(30000, poll.idleDelay * 2);
            })
            .catch(function(error) {
                if (_groupRuntimePolls[key] !== poll || !visible()) return;
                poll.idleDelay = Math.min(30000, poll.idleDelay * 2);
                var hint = document.getElementById('groupConnectionStatus');
                if (hint) { hint.textContent = 'Connection interrupted. The server keeps accepted work; reconnecting…'; hint.title = error.message; }
            }).finally(function() {
                poll.running = false;
                if (_groupRuntimePolls[key] !== poll) return;
                if (!visible()) { delete _groupRuntimePolls[key]; return; }
                var active = session.busy || session.sendingOutbox || (session.outbox || []).length;
                var delay = poll.wake ? 0 : active ? 800 : poll.idleDelay;
                poll.wake = false;
                poll.timer = setTimeout(tick, delay);
            });
    };
    poll.tick = tick;
    _groupRuntimePolls[key] = poll;
    poll.timer = setTimeout(tick, 0);
}
function wakeCurrentGroupPoll() {
    var session = _groupSessionsByScene[_groupCurrentScenePath()];
    if (session && session.managed && groupTabIsOpen() && !document.hidden) groupRuntimePoll(session, true);
}
document.addEventListener('visibilitychange', function() {
    if (!document.hidden) { wakeCurrentGroupPoll(); return; }
    Object.keys(_groupRuntimePolls).forEach(function(key) {
        clearTimeout(_groupRuntimePolls[key].timer); delete _groupRuntimePolls[key];
    });
});
window.addEventListener('focus', wakeCurrentGroupPoll);
function attachManagedGroup(session) {
    if (!session.id) return Promise.resolve();
    return groupRuntimeRequest(session, groupRuntimeEnvelope(session, 'state')).then(function() {
        drainGroupOutbox(session);
    });
}
function groupRuntimeControl(session, action, payload) {
    if (action === 'retry') payload = Object.assign({}, payload, {review_choices: groupReviewChoices(session)});
    return groupRuntimeRequest(session, groupRuntimeEnvelope(session, action, payload)).catch(function(error) {
        session.error = error.message; renderSceneGroupPane(); throw error;
    });
}
function groupReviewChoices(session) {
    var choices = [];
    session.turns.filter(function(turn) { return turn.review_pending; }).forEach(function(turn) {
        var review = _groupReviewContexts.get(turn), saved = {};
        if (!review) {
            try { saved = JSON.parse(sessionStorage.getItem('proseview-group-review:' + turn.tool_conversation_id) || '{}'); } catch (error) {}
        }
        var keep = review ? review.keep : saved.keep || {}, fingerprints = review ? review.fingerprints || {} : saved.fingerprints || {};
        Object.keys(keep).forEach(function(path) {
            var drop = Object.keys(keep[path]).filter(function(id) { return keep[path][id] === false; }).map(Number);
            if (drop.length) choices.push({conversation_id: turn.tool_conversation_id, path: path, drop: drop, fingerprint: fingerprints[path] || ''});
        });
    });
    return choices;
}
function drainGroupOutbox(session) {
    if (session.sendingOutbox || !session.outbox || !session.outbox.length) return;
    session.sendingOutbox = true;
    var body = session.outbox[0];
    groupRuntimeRequest(session, body).then(function() {
        session.outbox = session.outbox.filter(function(row) { return row.request_id !== body.request_id; });
        session.sendError = '';
    }).catch(function(error) {
        if (session.outbox.some(function(row) { return row.request_id === body.request_id; })) session.sendError = 'Message not confirmed: ' + error.message + ' Retry sending; an accepted message will not run twice.';
    }).finally(function() {
        session.sendingOutbox = false; _groupSaveDraft(session.scene); groupRuntimePoll(session);
        if (session.scene === _groupCurrentScenePath()) renderSceneGroupPane();
        if (!session.sendError) drainGroupOutbox(session);
    });
}
function submitManagedGroupMessage(options) {
    var scene = _groupCurrentScenePath(), session = _groupSessionFor(scene), input = document.getElementById('groupInput');
    var text = input ? input.value.trim() : _groupDraftInput.trim();
    if (!scene || !text) return;
    var immediate = !!(options && options.mode === 'now');
    var body = groupRuntimeEnvelope(session, 'submit', {message_id: _groupNewId(), scene: scene, text: _groupWithSelection(text), authored: text,
        created_at: Date.now() / 1000, immediate: immediate,
        seats: groupRequestedSeats(text, session), attachments: discussMentionsIn(text), review_choices: groupReviewChoices(session), live_document: discussLiveDocumentFor({kind: 'scene', path: scene})});
    if (!session.outbox) session.outbox = [];
    session.outbox.push(body);
    if (session.managed) groupRuntimePoll(session, true);
    rememberDiscussInstruction(text);
    if (typeof recordChatMessageHistory === 'function') recordChatMessageHistory('group', text);
    _groupDraftInput = ''; if (input) input.value = '';
    _groupTargetChoice = 'auto';
    session.busy = true; session.statusText = 'Sending message…';
    if (typeof _groupScrollByScene !== 'undefined') _groupScrollByScene[scene] = {top: 0, atBottom: true};
    _groupSaveDraft(scene); renderSceneGroupPane(); drainGroupOutbox(session);
}
function startManagedGroupPreset(session) {
    if (!session.pendingPreset || session.startingPreset) return;
    var preset = session.pendingPreset;
    session.startingPreset = true; session.presetError = ''; renderSceneGroupPane();
    return groupLoadProviderStatus(true).then(function(rows) {
        if (session.pendingPreset !== preset || _groupSessionsByScene[session.scene] !== session) return;
        var required = preset.invitations.map(function(step) { return step.seat; });
        if (preset.recap) required.push(preset.recap);
        var missing = session.participants.filter(function(profile) {
            return required.includes(profile.seat) && rows.some(function(row) { return row.id === profile.agent && !row.available; });
        });
        if (missing.length) throw new Error(missing.map(function(profile) {
            var row = rows.find(function(row) { return row.id === profile.agent; });
            return profile.name + ' · ' + _groupAgentDisplay(profile.agent) + ': ' + (row.reason || 'Agent unavailable');
        }).join('\n'));
        queueManagedGroupPreset(session);
    }).catch(function(error) { if (session.pendingPreset === preset) session.presetError = error.message; })
        .finally(function() { session.startingPreset = false; if (_groupSessionsByScene[session.scene] === session) renderSceneGroupPane(); });
}
function groupRecapPrompt(presetId) {
    if (presetId === 'pitch_next_beat') {
        return (
            'Deliver a self-contained, actionable recap of where we landed so the writer does not need to piece it together from earlier turns: ' +
            '1) The winning next-beat blueprint (opening disruption, mid-scene turn, and closing cliffhanger or pivot), ' +
            '2) Any strong alternative beat worth keeping as Option B, and ' +
            '3) The key character or pacing trap to avoid while drafting.'
        );
    }
    return (
        'Deliver a self-contained, actionable revision summary so the writer can apply the changes directly from this card without reading earlier turns. ' +
        'Do not include meta-disclaimers about writer approval. ' +
        'For every agreed or recommended edit:\n' +
        '1. Give a short bold heading and cite `Line N` (or `Setup — Line X` and `Payoff — Line Y` for a linked setup-and-payoff move).\n' +
        '2. Quote the complete, verbatim original passage from the scene as an italic blockquote (`> *...*`) — never abbreviate with `...`.\n' +
        '3. Provide the complete, ready-to-paste replacement as a plain blockquote (`> ...`), or `> [Cut this passage]` for a pure deletion (for a linked setup/payoff pair touching two lines, include the complete `> *...*` and `> ...` blockquotes for both lines; if two competing versions remain open, show Option A and Option B as separate plain blockquotes).\n' +
        '4. Add one sentence explaining why this edit improves the scene.'
    );
}
function groupPresetDebateInvitationCount(session) {
    return ((session && session.turns) || []).filter(function(turn) {
        return turn.role === 'invitation' && !turn.recap && turn.label !== 'Recovery';
    }).length;
}
function queueManagedGroupPreset(session) {
    var preset = session.pendingPreset;
    if (!preset) return;
    session.id = _groupNewId(); session.createdAt = Date.now() / 1000;
    session.topicLabel = preset.name; session.presetId = preset.id;
    session.topicBadge = preset.invitations.length + ' invitations' + (preset.recap ? ' + recap' : '');
    var invitations = preset.invitations.map(function(step) { return {seat: step.seat, prompt: step.prompt, attachments: discussMentionsIn(step.prompt)}; });
    if (preset.recap) invitations.push({seat: preset.recap, recap: true, prompt: groupRecapPrompt(preset.id)});
    var body = groupRuntimeEnvelope(session, 'preset', {invitations: invitations});
    session.pendingPreset = null; session.outbox = [body];
    session.busy = true; session.statusText = 'Starting discussion…';
    if (typeof _groupScrollByScene !== 'undefined') _groupScrollByScene[session.scene] = {top: 0, atBottom: true};
    _groupSaveDraft(session.scene); renderSceneGroupPane(); drainGroupOutbox(session);
}
function continueManagedGroupToFive(session) {
    if (!session || session.busy || !session.presetId) return;
    var doneCount = groupPresetDebateInvitationCount(session);
    if (doneCount < 2 || doneCount >= 5) return;
    var extra = [];
    for (var idx = doneCount; idx < 5; idx++) {
        var step = typeof window._rmPresetStepTemplate === 'function'
            ? window._rmPresetStepTemplate(session.presetId, idx)
            : {seat: idx % 2 + 1, prompt: 'Respond to the latest proposal. Agree, push back, or offer a concrete alternative.'};
        extra.push({seat: step.seat, prompt: step.prompt, attachments: discussMentionsIn(step.prompt)});
    }
    var lastRecap = (session.turns || []).slice().reverse().find(function(turn) {
        return turn.role === 'invitation' && turn.recap;
    });
    var presetDef = (((_groupSettings || {}).library || {}).presets || []).find(function(p) { return p.id === session.presetId; });
    var recapSeat = lastRecap ? lastRecap.seat : (presetDef && presetDef.recap ? presetDef.recap : 0);
    if (recapSeat) {
        extra.push({seat: recapSeat, recap: true, prompt: groupRecapPrompt(session.presetId)});
    }
    var body = groupRuntimeEnvelope(session, 'preset', {append: true, invitations: extra});
    if (!session.outbox) session.outbox = [];
    session.outbox.push(body);
    session.busy = true;
    session.statusText = 'Continuing discussion to 5 turns…';
    if (typeof _groupScrollByScene !== 'undefined') _groupScrollByScene[session.scene] = {top: 0, atBottom: true};
    _groupSaveDraft(session.scene); renderSceneGroupPane(); drainGroupOutbox(session);
}
function saveManagedGroup(session) {
    if (!session.managed) { _groupSaveDraft(session.scene); return; }
    if (session._saving) { session._saveAgain = true; return; }
    session._saving = true;
    var models = JSON.stringify(session.participants.map(function(p) { return [p.model, p.effort]; }));
    var action = models !== session.runtimeModelsKey ? 'models' : 'preferences';
    var body = groupRuntimeEnvelope(session, action, action === 'models' ? {participants: session.participants} : {plans: groupRuntimePlans(session)});
    groupRuntimeRequest(session, body, {render: false, preserveModels: true}).catch(function(error) {
        session.error = error.message; renderSceneGroupPane();
        return groupRuntimeRequest(session, {action: 'state', group_id: session.id}).catch(function() {});
    }).finally(function() {
        session._saving = false;
        if (session._saveAgain) { session._saveAgain = false; saveManagedGroup(session); }
    });
}
function renderManagedGroupQueue(session, body) {
    var outbox = session.outbox || [], pending = session.pendingMessages || [];
    if (outbox.length || pending.length) {
        var box = elementWith('discuss-queue group-message-queue');
        var heading = document.createElement('strong'); heading.textContent = pending.length + outbox.length + ' message' + (pending.length + outbox.length === 1 ? '' : 's') + ' queued'; box.appendChild(heading);
        pending.forEach(function(message, index) {
            var row = elementWith('discuss-queue-item', message.text);
            var remove = document.createElement('button'); remove.type = 'button'; remove.className = 'discuss-queue-remove'; remove.textContent = 'Remove';
            remove.setAttribute('aria-label', 'Remove queued message ' + (index + 1));
            remove.onclick = function() { remove.disabled = true; groupRuntimeControl(session, 'remove', {message_id: message.id}).catch(function() {}); };
            row.appendChild(remove); box.appendChild(row);
        });
        outbox.forEach(function(request) { box.appendChild(elementWith('discuss-queue-item', request.text || 'Starting the discussion preset…')); });
        if (session.sendError) {
            box.appendChild(elementWith('group-error-text', session.sendError));
            var retry = document.createElement('button'); retry.type = 'button'; retry.className = 'group-header-btn'; retry.textContent = 'Retry sending';
            retry.onclick = function() { session.sendError = ''; drainGroupOutbox(session); }; box.appendChild(retry);
        }
        body.appendChild(box);
    }
    var state = session.runtime;
    if (!state) return;
    if (state.notice) body.appendChild(elementWith('group-runtime-notice', state.notice));
    if (state.status === 'interrupted' || state.status === 'paused') {
        var recovery = elementWith('group-runtime-recovery');
        var active = state.steps.find(function(step) { return step.id === state.active_step; });
        if (state.partial_reply) {
            var partial = elementWith('group-interrupted-reply discuss-message');
            partial.appendChild(elementWith('group-turn-tag', 'Partial reply · interrupted'));
            renderDiscussMarkdown(partial, state.partial_reply); recovery.appendChild(partial);
        }
        var interrupted = active && active.state === 'interrupted';
        (interrupted ? [{action:'retry', label:'Retry interrupted invitation'}, {action:'skip', label:'Skip interrupted invitation'}]
            : [{action:'resume', label:'Resume remaining invitations'}]).forEach(function(option) {
            var button = document.createElement('button'); button.type = 'button'; button.className = 'group-header-btn'; button.textContent = option.label;
            button.disabled = session.busy;
            button.onclick = function() { button.disabled = true; groupRuntimeControl(session, option.action).catch(function() {}); }; recovery.appendChild(button);
        });
        body.appendChild(recovery);
    }
}
