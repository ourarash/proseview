// Quote comparisons preview the current passage; they never write a file.
var _currentDiscussQuoteComparison = null;

function isDiscussItalicQuote(quote) {
    if (!quote) return false;
    var walker = document.createTreeWalker(quote, NodeFilter.SHOW_TEXT, null);
    var total = 0, italic = 0, node;
    while ((node = walker.nextNode())) {
        var el = node.parentElement;
        if (el && el.closest('.discuss-quote-header, .md-copy-btn')) continue;
        var count = (node.nodeValue || '').replace(/\s+/g, '').length;
        if (!count) continue;
        total += count;
        if (el && el.closest('em')) italic += count;
    }
    return total > 0 && (italic / total) >= 0.8;
}

function discussQuoteNormal(text) {
    return String(text || '')
        .replace(/[\u2018\u2019\u2032]/g, "'")
        .replace(/[\u201C\u201D\u2033]/g, '"')
        .replace(/[*_`]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

function discussQuoteDocumentText(quote) {
    var path = quote.dataset.targetPath || '', kind = quote.dataset.targetKind || 'scene';
    if (!path) return null;
    if (kind === 'scene') {
        var live = typeof discussLiveDocumentFor === 'function' ? discussLiveDocumentFor({kind: 'scene', path: path}) : null;
        if (live && typeof live.content === 'string') {
            return {body: live.content, offset: (typeof meta !== 'undefined' && meta[path] && meta[path].txt_line_offset) || 0};
        }
        if (typeof contents !== 'undefined' && typeof contents[path] === 'string') {
            return {body: contents[path], offset: (typeof meta !== 'undefined' && meta[path] && meta[path].txt_line_offset) || 0};
        }
    } else if (typeof repoFileByPath !== 'undefined' && repoFileByPath[path] && typeof repoFileByPath[path].body === 'string') {
        return {body: repoFileByPath[path].body, offset: 0};
    }
    return null;
}

function discussQuoteMatchesSource(quote) {
    var doc = discussQuoteDocumentText(quote);
    if (!doc) return false;
    var q = discussQuoteNormal(extractDiscussQuoteText(quote));
    if (!q) return false;
    var line = Number(quote.dataset.targetLine) || 0;
    if (line > 0) {
        var endLine = Number(quote.dataset.targetEndLine) || line;
        var lines = doc.body.split('\n');
        var start = line - doc.offset - 1, end = Math.max(start, endLine - doc.offset - 1);
        if (start < 0 || start >= lines.length) return false;
        var s = discussQuoteNormal(lines.slice(start, Math.min(lines.length, end + 1)).join('\n'));
        if (!s) return false;
        if (endLine > line) return q === s;
        return q === s || (q.length >= 12 && s.indexOf(q) >= 0);
    }
    var full = discussQuoteNormal(doc.body);
    return !!full && (q === full || (q.length >= 12 && full.indexOf(q) >= 0));
}

function decorateDiscussQuoteActions(wrap, quote, ctx) {
    if (!quote.dataset.targetPath) return;
    var previous = ctx && ctx.lastCompareQuote;
    var lead = quote._discussCompareLead || '';
    var italic = isDiscussItalicQuote(quote);
    if (previous && previous.dataset.targetPath === quote.dataset.targetPath
        && previous.dataset.targetLine === quote.dataset.targetLine
        && (/^(?:After\s*:|Replace\b|Insert\b)/i.test(lead) || isDiscussItalicQuote(previous) && !italic)) {
        quote._discussCompareOriginal = previous._discussCompareOriginal || extractDiscussQuoteText(previous);
    }
    if (/Insert\s+(after|before)/i.test(lead)) quote._discussCompareKind = /Insert\s+before/i.test(lead) ? 'insert-before' : 'insert-after';
    quote._discussExplicitEdit = /^(?:After\s*:|Replace\b|Insert\s+(?:after|before)\b)/i.test(lead);
    var namedSources = lead.match(/[^\s`<>()\[\]]+\.md\b/g) || [];
    var unknownSource = namedSources.some(function(path) { return !resolveProsviewFileReference(path); })
        && !(quote._discussCompareSourceKnown);
    if (unknownSource) quote._discussExplicitEdit = false;
    var quoteText = extractDiscussQuoteText(quote);
    var hasLine = Number(quote.dataset.targetLine) > 0;
    var plainQuote = !italic && !unknownSource && !!quoteText;
    var matchesSource = plainQuote && discussQuoteMatchesSource(quote);
    quote._discussPlainQuote = plainQuote;
    quote._discussMatchesSource = matchesSource;
    quote._discussProposedEdit = !!(
        quote._discussCompareOriginal
        || quote._discussExplicitEdit
        || (plainQuote && hasLine && !matchesSource)
    );
    quote._discussUnanchoredProposal = !quote._discussProposedEdit && plainQuote && !hasLine && !matchesSource;
    if (ctx) ctx.lastCompareQuote = quote;
    var header = quote.querySelector('.discuss-quote-header');
    if (!header) {
        header = document.createElement('div'); header.className = 'discuss-quote-header'; quote.prepend(header);
    }
    wrap.classList.add('has-quote-actions');
    var actions = document.createElement('div'); actions.className = 'discuss-quote-actions';
    var button = document.createElement('button'); button.type = 'button'; button.className = 'discuss-quote-compare';
    button.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M9 3v18M15 3v18M3 7h6M15 17h6M3 17h2M19 7h2"/></svg>Compare';
    button.title = 'Compare this quote with the current passage';
    button.onclick = function(event) { event.stopPropagation(); openDiscussQuoteComparison(quote, button); };
    actions.appendChild(button);
    var copy = wrap.querySelector(':scope > .md-copy-btn');
    if (copy) actions.appendChild(copy);
    wrap.appendChild(actions);
}

function openDiscussQuoteComparison(quote, button) {
    var target = {kind: quote.dataset.targetKind || 'scene', path: quote.dataset.targetPath};
    var replacement = extractDiscussQuoteText(quote);
    var comparison = {request: {document: target, quote: /^\[Cut (?:this )?passage\]$/i.test(replacement) ? '' : replacement,
        original: quote._discussCompareOriginal || '', kind: quote._discussCompareKind || 'replace',
        prefer_line: !!(quote._discussExplicitEdit || quote._discussProposedEdit) && !quote._discussCompareOriginal,
        line: Number(quote.dataset.targetLine) || null, end_line: Number(quote.dataset.targetEndLine) || null,
        live_document: discussLiveDocumentFor(target)},
        label: quote._discussCompareOriginal || !isDiscussItalicQuote(quote) ? 'Suggested text' : 'Quoted text'};
    openDiscussDiffModal('', {comparison: comparison});
    _discussReturnFocus = button;
    document.getElementById('discussDiffModalOverlay').querySelector('[aria-label="Close diff viewer"]').focus({preventScroll: true});
}

function loadDiscussQuoteComparison(mode, token) {
    var comparison = _currentDiscussQuoteComparison;
    var content = document.getElementById('discussDiffModalContent');
    content.replaceChildren(elementWith('discuss-diff-status', 'Loading passage…'));
    if (!comparison.pending) comparison.pending = discussApi('/api/discuss/compare-quote', comparison.request);
    comparison.pending.then(function(result) {
        if (token !== _discussDiffLoadToken || comparison !== _currentDiscussQuoteComparison) return;
        content.replaceChildren();
        document.getElementById('discussDiffModalNote').textContent = comparison.request.document.path + ' · Preview';
        if (result.unavailable) { content.appendChild(elementWith('discuss-diff-status', result.unavailable)); return; }
        var range = 'Line ' + result.line + (result.end_line !== result.line ? '–' + result.end_line : '');
        document.getElementById('discussDiffModalNote').textContent = result.path + ' · ' + range + ' · Preview' + (result.unsaved ? ' · unsaved edits' : '');
        if (result.matches) { content.appendChild(elementWith('discuss-diff-status', 'Matches the current ' + (result.kind === 'scene' ? 'scene' : 'file') + '.')); return; }
        var labels = elementWith('discuss-quote-comparison-labels');
        labels.append(elementWith('', 'Current ' + (result.kind === 'scene' ? 'scene' : 'file') + (result.unsaved ? ' · unsaved' : '')),
                      elementWith('', comparison.label));
        labels.classList.toggle('is-inline', mode === 'inline'); content.appendChild(labels);
        var diff = elementWith('discuss-quote-comparison-diff'); content.appendChild(diff);
        return discussApi('/api/discuss/format_patch', {patch: result.patch, mode: mode, hunks: true, hunk_headers: false}).then(function(data) {
            if (token !== _discussDiffLoadToken || comparison !== _currentDiscussQuoteComparison) return;
            diff.innerHTML = (data.hunks || []).map(function(hunk) { return hunk.html; }).join('');
        });
    }).catch(function(error) {
        if (token !== _discussDiffLoadToken || comparison !== _currentDiscussQuoteComparison) return;
        content.replaceChildren(elementWith('discuss-diff-status', 'Could not compare this passage: ' + error.message));
    });
}
