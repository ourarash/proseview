// Reading position follows a conversation, including across a page reload.
function groupTurnViewKey(turn, index) {
    return turn.role + ':' + (turn.step_id || turn.message_id || (turn.created_at || '') + ':' + index);
}
function groupScrollViewportTop(body) {
    var nav = body.querySelector('.group-conversation-navigation');
    return body.getBoundingClientRect().top + (nav ? nav.offsetHeight : 0);
}
function groupRememberScroll(body) {
    if (!body || !body.isConnected || !body.clientHeight || body._groupRestoring || body._groupFollowLatest || !body._groupScrollSession) return;
    var anchors = Array.from(body.querySelectorAll('[data-group-reading-anchor]')).filter(function(node) {
        return (node.classList.contains('is-message-collapsed') || !node.querySelector('[data-group-reading-anchor]')) && node.getClientRects().length;
    });
    if (!anchors.length) return; // Loading a conversation must not replace its saved position.
    var top = groupScrollViewportTop(body);
    var anchor = anchors.find(function(node) { return node.getBoundingClientRect().bottom > top; });
    var state = {top: body.scrollTop, atBottom: body.scrollHeight - body.scrollTop - body.clientHeight < 48,
        anchor: anchor ? anchor.dataset.groupReadingAnchor : '', offset: anchor ? anchor.getBoundingClientRect().top - top : 0};
    body._groupScrollState = state;
    groupConversationView(body._groupScrollSession).scroll = state;
    groupSaveConversationView(body._groupScrollSession);
}
function groupFollowLatest(session) {
    var body = document.getElementById('groupBody');
    if (body && body._groupScrollSession && body._groupScrollSession.id === session.id) body._groupFollowLatest = true;
    groupConversationView(session).scroll = {top: 0, atBottom: true};
    groupSaveConversationView(session);
}
function groupInstallScroll(body, session) {
    body._groupScrollSession = {id: session.id, scene: session.scene};
    var state = groupConversationView(session).scroll || {top: 0, atBottom: true};
    body._groupScrollState = state;
    body.querySelectorAll('[data-group-turn]').forEach(function(card) {
        var key = card.dataset.groupMessageKey;
        card.dataset.groupReadingAnchor = key;
        card.querySelectorAll('.group-turn-body h1, .group-turn-body h2, .group-turn-body h3, .group-turn-body p, .group-turn-body blockquote').forEach(function(node, index) {
            node.dataset.groupReadingAnchor = key + ':block:' + index;
        });
    });
    function restore() {
        if (!body.isConnected || !body.clientHeight) return;
        var saved = body._groupScrollState;
        body._groupRestoring = true;
        if (saved.atBottom) body.scrollTop = body.scrollHeight;
        else {
            var anchor = Array.from(body.querySelectorAll('[data-group-reading-anchor]')).find(function(node) { return node.dataset.groupReadingAnchor === saved.anchor; });
            if (anchor && anchor.getClientRects().length) body.scrollTop += anchor.getBoundingClientRect().top - groupScrollViewportTop(body) - saved.offset;
            else body.scrollTop = saved.top || 0;
        }
        requestAnimationFrame(function() {
            body._groupRestoring = false;
            // A focus/jump can scroll during restoration, when the scroll
            // event is deliberately ignored. Commit the position once settled.
            groupRememberScroll(body);
        });
    }
    body._groupRestoreScroll = restore;
    body.addEventListener('scroll', function() { groupRememberScroll(body); }, {passive: true});
    // Read synchronously before a background render or reload; scroll events
    // can still be queued when either happens.
    ['wheel', 'touchstart', 'pointerdown', 'keydown'].forEach(function(name) {
        body.addEventListener(name, function() { body._groupRestoring = false; }, {passive: true});
    });
    var observer = new ResizeObserver(function() {
        if (!body.isConnected) { observer.disconnect(); return; }
        restore();
    });
    observer.observe(body);
    Array.from(body.children).forEach(function(child) { observer.observe(child); });
    // The old observer belongs to the detached pane, not to the next chat.
    body._groupDisconnectScroll = function() { observer.disconnect(); };
    restore(); requestAnimationFrame(restore);
}
window.addEventListener('pagehide', function() { groupRememberScroll(document.getElementById('groupBody')); });
