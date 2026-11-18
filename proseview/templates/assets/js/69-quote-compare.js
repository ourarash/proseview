// Quote comparisons preview the current passage; they never write a file.
var _currentDiscussQuoteComparison = null;

function decorateDiscussQuoteActions(wrap, quote, ctx) {
    if (!quote.dataset.targetPath) return;
    var previous = ctx && ctx.lastCompareQuote;
    var lead = quote._discussCompareLead || '';
    if (previous && previous.dataset.targetPath === quote.dataset.targetPath
        && previous.dataset.targetLine === quote.dataset.targetLine
        && (/^(?:After\s*:|Replace\b|Insert\b)/i.test(lead) || previous.querySelector('em') && !quote.querySelector('em'))) {
        quote._discussCompareOriginal = previous._discussCompareOriginal || extractDiscussQuoteText(previous);
    }
    if (/Insert\s+(after|before)/i.test(lead)) quote._discussCompareKind = /Insert\s+before/i.test(lead) ? 'insert-before' : 'insert-after';
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
        line: Number(quote.dataset.targetLine) || null, end_line: Number(quote.dataset.targetEndLine) || null,
        live_document: discussLiveDocumentFor(target)},
        label: quote._discussCompareOriginal || !quote.querySelector('em') ? 'Suggested text' : 'Quoted text'};
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
