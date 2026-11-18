// Presentation only: recaps remain ordinary Markdown in the saved conversation.
var _groupConversationViews = Object.create(null);

function groupConversationView(session) {
    var key = session.id || session.scene;
    if (!_groupConversationViews[key]) {
        var saved = {};
        try { saved = JSON.parse(sessionStorage.getItem('proseview-group-view:' + key) || '{}'); } catch (error) {}
        _groupConversationViews[key] = {messages: saved.messages || {}, edits: saved.edits || {}, scroll: saved.scroll || null};
    }
    return _groupConversationViews[key];
}
function groupSaveConversationView(session) {
    try { sessionStorage.setItem('proseview-group-view:' + (session.id || session.scene), JSON.stringify(groupConversationView(session))); } catch (error) {}
}
function groupPreserveReadingPosition(anchor, change) {
    var body = document.getElementById('groupBody');
    var top = anchor && anchor.getBoundingClientRect().top;
    change();
    if (body && anchor && anchor.isConnected) body.scrollTop += anchor.getBoundingClientRect().top - top;
    groupRememberScroll(body);
}
function groupMessageDisclosure(card, head, session, turn, index) {
    var key = turn.step_id || turn.message_id || (turn.created_at || '') + ':' + index + ':' + turn.role;
    var view = groupConversationView(session);
    card.dataset.groupTurn = String(index);
    card.dataset.groupMessageKey = groupTurnViewKey(turn, index);
    var button = document.createElement('button');
    button.type = 'button'; button.className = 'group-message-toggle';
    var preview = document.createElement('p'); preview.className = 'group-message-preview';
    preview.textContent = (card.querySelector('.group-turn-body').textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160);
    card.insertBefore(preview, head.nextSibling);
    var speaker = head.querySelector('.chat-message-name').textContent;
    card._groupSetCollapsed = function(collapsed, save) {
        card.classList.toggle('is-message-collapsed', collapsed);
        button.textContent = collapsed ? '▸' : '▾';
        button.setAttribute('aria-expanded', String(!collapsed));
        button.setAttribute('aria-label', (collapsed ? 'Expand' : 'Collapse') + ' message from ' + speaker);
        view.messages[key] = collapsed;
        if (save !== false) groupSaveConversationView(session);
    };
    button.onclick = function() {
        groupPreserveReadingPosition(head, function() { card._groupSetCollapsed(!card.classList.contains('is-message-collapsed')); });
    };
    head.insertBefore(button, head.firstChild);
    head.addEventListener('click', function(event) {
        if (!event.target.closest('button, a, input, select') && !String(window.getSelection() || '')) button.click();
    });
    card._groupSetCollapsed(!!view.messages[key], false);
}
function groupConversationNavigation(session, turnsWrap) {
    var nav = document.createElement('nav'); nav.className = 'group-conversation-navigation';
    nav.setAttribute('aria-label', 'Conversation navigation');
    function add(label, action) {
        var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-chip discuss-chip-outline';
        button.textContent = label; button.onclick = action; nav.appendChild(button); return button;
    }
    function setMessages(collapse) {
        var cards = Array.from(turnsWrap.querySelectorAll('[data-group-turn]'));
        var body = document.getElementById('groupBody');
        var anchor = cards.find(function(card) { return card.getBoundingClientRect().bottom > body.getBoundingClientRect().top; });
        groupPreserveReadingPosition(anchor, function() {
            cards.forEach(function(card, index) { card._groupSetCollapsed(collapse && index < cards.length - 1, false); });
            groupSaveConversationView(session);
        });
    }
    add('Collapse earlier messages', function() { setMessages(true); });
    add('Expand all', function() { setMessages(false); });
    var latest = add('Latest recap', function() {
        var card = Array.from(turnsWrap.querySelectorAll('.group-recap-message')).pop();
        if (!card) return;
        card._groupSetCollapsed(false);
        (card.querySelector('.group-recap-section') || card).scrollIntoView({block: 'start'});
    });
    latest.disabled = !turnsWrap.querySelector('.group-recap-message');
    return nav;
}
function groupQuoteText(quote) {
    return extractDiscussQuoteText(quote);
}
function groupEditPairs(content) {
    var pairs = [], before = null, state = '', kind = 'replace';
    Array.from(content.children).forEach(function(node) {
        if (node.tagName === 'P' && /^Before\s*:/i.test(node.textContent.trim())) state = 'before';
        if (node.tagName === 'P' && /^After\s*:/i.test(node.textContent.trim())) {
            state = 'after'; kind = /Insert\s+(?:after|before)/i.test(node.textContent) ? 'insert' : 'replace';
        }
        var quote = node.tagName === 'BLOCKQUOTE' ? node : node.querySelector(':scope > blockquote');
        if (!quote) return;
        if (state === 'before' || (!state && quote.querySelector('em'))) { before = quote; state = ''; return; }
        if (before && (state === 'after' || !quote.querySelector('em'))) {
            var after = groupQuoteText(quote);
            quote._discussCompareOriginal = groupQuoteText(before);
            if (kind === 'insert') quote._discussCompareKind = quote._discussCompareKind || 'insert-after';
            pairs.push({before: groupQuoteText(before), after: /^\[Cut (?:this )?passage\]$/i.test(after) ? '' : after,
                kind: /^\[Cut (?:this )?passage\]$/i.test(after) ? 'cut' : kind,
                path: before.dataset.targetPath || quote.dataset.targetPath || ''});
            before = null; state = '';
        }
    });
    return pairs;
}
function groupRecapEditCard(heading, nodes, session, turnIndex, editIndex, outcome) {
    var content = document.createElement('div'); content.className = 'group-edit-content';
    nodes.forEach(function(node) { content.appendChild(node); });
    var edits = groupEditPairs(content);
    if (!edits.length) { var fallback = document.createDocumentFragment(); fallback.append(heading, content); return fallback; }
    var card = document.createElement('article'); card.className = 'group-edit-card';
    if (edits.length === 1) card.classList.add('is-single-edit');
    card._groupEdits = edits; card._groupTurnIndex = turnIndex;
    var head = document.createElement('div'); head.className = 'group-edit-heading';
    var status = document.createElement('span'); status.className = 'group-edit-status';
    status.textContent = outcome === 'choices' ? 'Your choice' : 'Agreed';
    card._groupStatus = status;
    head.append(heading, status); card.appendChild(head);
    var source = content.querySelector('a[data-prosview-path]');
    if (source) {
        var reference = source.cloneNode(true); reference.classList.add('group-edit-source');
        reference.textContent = source.dataset.prosviewPath + (source.dataset.prosviewLine ? ' · Line ' + source.dataset.prosviewLine
            + (source.dataset.prosviewEndLine && source.dataset.prosviewEndLine !== source.dataset.prosviewLine ? '–' + source.dataset.prosviewEndLine : '') : '');
        reference.onclick = function(event) { if (!event.metaKey && !event.ctrlKey) { event.preventDefault(); source.click(); } };
        card.appendChild(reference);
    }
    if (edits.length === 1) {
        Array.from(content.children).forEach(function(node) {
            if (node.tagName !== 'P') return;
            var text = node.textContent.trim();
            if (/^After\s*:/i.test(text)) {
                var label = document.createElement('strong');
                label.textContent = edits[0].kind === 'insert' ? 'After (insert):' : 'After:';
                node.replaceChildren(label);
            } else if (/^Why\s*:/i.test(text)) {
                node.classList.add('group-edit-reason'); content.appendChild(node);
            } else if (node.querySelectorAll('a').length === 1 && text.replace(/[()\s.]/g, '') === node.querySelector('a').textContent.replace(/[()\s.]/g, '')) {
                node.hidden = true;
            }
        });
    }
    card.appendChild(content);
    var actions = document.createElement('div'); actions.className = 'group-edit-actions';
    var expand = document.createElement('button'); expand.type = 'button'; expand.className = 'discuss-chip discuss-chip-outline';
    var key = turnIndex + ':edit:' + editIndex, view = groupConversationView(session);
    function setExpanded(expanded) {
        card.classList.toggle('is-edit-expanded', expanded); expand.textContent = expanded ? 'Show previews' : 'Expand full edit';
        expand.setAttribute('aria-expanded', String(expanded)); view.edits[key] = expanded;
    }
    expand.onclick = function() { groupPreserveReadingPosition(head, function() { setExpanded(!card.classList.contains('is-edit-expanded')); groupSaveConversationView(session); }); };
    setExpanded(!!view.edits[key]); actions.appendChild(expand);
    var replacements = edits.filter(function(edit) { return edit.kind !== 'cut'; }).map(function(edit) { return edit.after; });
    if (edits.length === 1 && replacements.length) {
        var copy = document.createElement('button'); copy.type = 'button'; copy.className = 'discuss-chip discuss-chip-outline'; copy.textContent = 'Copy replacement';
        copy.onclick = function() { sidebarWriteClipboard(replacements.join('\n\n')).then(function() { copy.textContent = 'Copied'; }, function() { copy.textContent = 'Could not copy'; }); };
        actions.appendChild(copy);
    }
    if (edits.length > 1) {
        var hint = document.createElement('span'); hint.className = 'settings-note';
        hint.textContent = 'Copy each replacement separately.'; actions.appendChild(hint);
    }
    card._groupActions = actions; card.appendChild(actions); return card;
}
function groupDecorateRecap(parent, session, turn, index) {
    var children = Array.from(parent.children), section = null, outcome = '', editIndex = 0;
    children.forEach(function(node, i) {
        if (/^H[12]$/.test(node.tagName)) {
            var label = node.textContent.trim();
            outcome = /^agreed(?:\s|$)/i.test(label) ? 'agreed' : /^(choices for you|your call|open choices|unresolved)/i.test(label) ? 'choices' : /^(withdrawn|skipped|rejected)/i.test(label) ? 'withdrawn' : '';
            section = null;
            if (outcome) {
                section = document.createElement(outcome === 'withdrawn' ? 'details' : 'section');
                section.className = 'group-recap-section is-' + outcome;
                parent.insertBefore(section, node);
                if (outcome === 'withdrawn') { var summary = document.createElement('summary'); summary.textContent = label; section.appendChild(summary); node.remove(); }
                else section.appendChild(node);
            }
            return;
        }
        if (!section || !node.parentNode || node.parentNode !== parent) return;
        if (node.tagName === 'H3' && outcome !== 'withdrawn') {
            var nodes = [];
            for (var j = i + 1; j < children.length && !/^H[123]$/.test(children[j].tagName); j++) nodes.push(children[j]);
            section.appendChild(groupRecapEditCard(node, nodes, session, index, editIndex++, outcome));
        } else section.appendChild(node);
    });
}
function groupNormalizedProse(text) {
    return String(text || '').split(/\r?\n\s*\r?\n/).map(function(part) { return part.replace(/\s+/g, ' ').trim(); }).join('\n\n').trim();
}
function groupUpdateAppliedEdits(session) {
    var pane = document.getElementById('sceneGroupPane');
    if (!pane) return;
    pane.querySelectorAll('.group-edit-card').forEach(function(card) {
        var matches = card._groupEdits.map(function(edit) {
            for (var i = session.turns.length - 1; i > card._groupTurnIndex; i--) {
                var turn = session.turns[i], review = _groupReviewContexts.get(turn);
                if (!review || !review.loaded || review.error) continue;
                var file = (review.historyFiles || review.files).find(function(file) {
                    var target = resolveProsviewFileReference(file.path);
                    if (!target || target.path !== edit.path) return false;
                    var before = groupNormalizedProse(file.before), after = groupNormalizedProse(file.after);
                    var original = groupNormalizedProse(edit.before), replacement = groupNormalizedProse(edit.after);
                    if (!original || before === after || !before.includes(original)) return false;
                    return edit.kind === 'insert' ? replacement && !before.includes(replacement) && after.includes(replacement)
                        : !after.includes(original) && (edit.kind === 'cut' || replacement && after.includes(replacement));
                });
                if (file) return {review: review, file: file};
            }
            return null;
        });
        var applied = matches.length && matches.every(Boolean);
        card._groupStatus.textContent = applied ? 'Applied' : card.closest('.is-choices') ? 'Your choice' : 'Agreed';
        card.classList.toggle('is-applied', !!applied);
        var button = card._groupActions.querySelector('.group-edit-view-changes');
        if (applied && !button) {
            button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-chip discuss-chip-outline group-edit-view-changes';
            button.textContent = 'View changes'; card._groupActions.appendChild(button);
        }
        if (button) {
            button.hidden = !applied;
            button.onclick = function() {
                var match = matches[0];
                if (match.file.diff) {
                    openDiscussDiffModal(match.file.diff);
                    document.getElementById('discussDiffModalTitle').textContent = match.file.path;
                } else openDiscussReviewModal(match.file.path, match.review);
            };
        }
    });
}
function groupHydrateRecapReviews(session) {
    var pane = document.getElementById('sceneGroupPane');
    if (!pane || !pane.querySelector('.group-edit-card')) return;
    var first = Number(pane.querySelector('.group-edit-card')._groupTurnIndex);
    session.turns.forEach(function(turn, index) {
        if (index > first && turn.tool_conversation_id && turn.changed_files && turn.changed_files.length && !_groupReviewContexts.has(turn)) _groupToolReview(session, turn);
    });
    groupUpdateAppliedEdits(session);
}
