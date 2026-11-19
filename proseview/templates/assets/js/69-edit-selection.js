// Selection is local review state. Refer to the review's own item numbers;
// include proposal text only when that review is absent from the recipient's history.
var _editSelectionStores = new Map();
var _editSelectionComposers = new Map();
var _editSelectionWidgets = new Set();
var _editSelectionSourceJobs = new Map();
var EDIT_SELECTION_START = '\n\n<!-- proseview:selected-edits -->\n';
var EDIT_SELECTION_END = '\n<!-- /proseview:selected-edits -->';

function editSelectionTag(tag, text) { var node = document.createElement(tag); node.textContent = text; return node; }

function editSelectionChatScope() {
    var snapshot = _discussSnapshot || {};
    return 'chat:' + _discussAgent + ':' + (snapshot.thread_id || _discussConversationId || '');
}
function editSelectionGroupScope(session) { return 'group:' + session.id; }
function editSelectionStorageKey(scope) { return 'proseview-selected-edits:v1:' + repoRoot + ':' + scope; }
function editSelectionStore(scope) {
    if (!_editSelectionStores.has(scope)) {
        var saved = {};
        try { saved = JSON.parse(localStorage.getItem(editSelectionStorageKey(scope)) || '{}'); } catch (error) {}
        _editSelectionStores.set(scope, {records: saved.records || {}, notes: saved.notes || {}, next: saved.next || 1,
            prepared: saved.prepared || null, pending: saved.pending || {}, open: false});
    }
    return _editSelectionStores.get(scope);
}
function editSelectionSave(scope) {
    var store = editSelectionStore(scope);
    try { localStorage.setItem(editSelectionStorageKey(scope), JSON.stringify({records: store.records, notes: store.notes, next: store.next,
        prepared: store.prepared, pending: store.pending}, function(key, value) { return key === 'verifying' ? undefined : value; })); } catch (error) {}
}
function editSelectionHash(text) {
    var a = 2166136261, b = 5381;
    for (var i = 0; i < text.length; i++) { a = Math.imul(a ^ text.charCodeAt(i), 16777619); b = Math.imul(b, 33) ^ text.charCodeAt(i); }
    return (a >>> 0).toString(36) + '-' + (b >>> 0).toString(36) + '-' + text.length;
}
function editSelectionRecords(scope) {
    var rows = Object.values(editSelectionStore(scope).records).filter(function(row) { return row.selected; });
    var reviews = new Map();
    rows.forEach(function(row) { reviews.set(row.source, Math.min(reviews.get(row.source) || Infinity, row.order || 0)); });
    return rows.sort(function(a, b) {
        if (a.source !== b.source) return reviews.get(a.source) - reviews.get(b.source);
        if (a.number != null && b.number != null && a.number !== b.number) return a.number - b.number;
        return (a.order || 0) - (b.order || 0);
    });
}
function editSelectionNormal(text) { return String(text || '').replace(/\s+/g, ' ').trim(); }
function editSelectionItemKey(row) {
    return JSON.stringify([row.reviewKey || row.source || '', row.number == null ? ['title', row.title || row.key] : ['number', row.number]]);
}
function editSelectionGroups(rows) {
    var groups = new Map();
    rows.forEach(function(row) {
        var key = editSelectionItemKey(row);
        if (!groups.has(key)) groups.set(key, {key: key, row: row, edits: []});
        groups.get(key).edits.push(row);
    });
    return Array.from(groups.values());
}
function editSelectionNote(scope, row) { return String(editSelectionStore(scope).notes[editSelectionItemKey(row)] || ''); }
function editSelectionNotesPending(scope) {
    var store = editSelectionStore(scope);
    if (!store.prepared) return false;
    return JSON.stringify(editSelectionNoteLines(scope, editSelectionRecords(scope))) !== JSON.stringify(store.prepared.noteValues || {});
}
function editSelectionConflicts(scope) {
    var rows = editSelectionRecords(scope), conflicts = new Set();
    rows.forEach(function(a, index) {
        rows.slice(index + 1).forEach(function(b) {
            if (a.path !== b.path || a.targetKind !== b.targetKind) return;
            if (editSelectionItemKey(a) === editSelectionItemKey(b)) return;
            if (a.kind === 'instruction' || b.kind === 'instruction') return;
            if (a.kind.indexOf('insert-') === 0 || b.kind.indexOf('insert-') === 0) return;
            var x = editSelectionNormal(a.before), y = editSelectionNormal(b.before);
            var overlap = x && y && (x.includes(y) || y.includes(x));
            for (var n = Math.min(x.length, y.length); !overlap && n >= 12; n--) {
                if (x.endsWith(y.slice(0, n)) || y.endsWith(x.slice(0, n))) overlap = true;
            }
            if (overlap) { conflicts.add(a.key); conflicts.add(b.key); }
        });
    });
    return conflicts;
}
function editSelectionItem(quote) {
    var section = quote.closest('.edit-selection-item');
    if (section && section._editSelectionItem) return section._editSelectionItem;
    var card = quote.closest('.group-edit-card');
    var message = quote.closest('.group-turn-body, .chat-message-card, .discuss-message') || quote.parentElement;
    var headings = Array.from(message.querySelectorAll('h1,h2,h3,h4,h5,h6,strong')).filter(function(node) {
        return !node.closest('blockquote') && node.compareDocumentPosition(quote) & Node.DOCUMENT_POSITION_FOLLOWING
            && !/^(?:Before|After|Why|Type|Lane)\s*(?::|$)/i.test(node.textContent.trim());
    });
    var numbered = /^(?:(?:edit|item|suggestion|finding)\s+)?(\d+)(?:[.):]\s*|\s+[—–-]\s*|$)(.*)$/i;
    var heading = card && card.querySelector('h3') || headings.filter(function(node) {
        if (!numbered.test(node.textContent.trim())) return false;
        var level = /^H\d$/.test(node.tagName) ? Number(node.tagName[1]) : 6;
        return !headings.some(function(later) {
            return /^H\d$/.test(later.tagName) && Number(later.tagName[1]) <= level
                && node.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING;
        });
    }).pop();
    var match = heading && heading.textContent.trim().match(numbered);
    if (match) return {number: Number(match[1]), title: match[2].trim() || 'Item ' + match[1], heading: heading};
    var item = quote.closest('li');
    while (item && item.parentElement.tagName !== 'OL') item = item.parentElement.closest('li');
    if (item) {
        var number = Number(item.parentElement.getAttribute('start') || 1);
        Array.from(item.parentElement.children).some(function(sibling) {
            if (sibling.tagName !== 'LI') return false;
            if (sibling.hasAttribute('value')) number = Number(sibling.getAttribute('value'));
            if (sibling === item) return true;
            number++;
        });
        var first = item.querySelector(':scope > p, :scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > h5, :scope > h6, :scope > strong') || item;
        return {number: number, title: first.textContent.trim().split('\n')[0].slice(0, 120), heading: first};
    }
    heading = heading || headings.filter(function(node) { return /^H\d$/.test(node.tagName); }).pop() || headings.pop();
    return {number: null, title: heading ? heading.textContent.trim() : extractDiscussQuoteText(quote).slice(0, 90), heading: heading};
}
function editSelectionItemName(row) { return row.number == null ? '“' + row.title + '”' : String(row.number); }
function editSelectionSetItem(row, item, context) {
    row.number = item.number; row.title = item.title; row.source = context.source || ''; row.speaker = context.speaker || ''; row.itemVersion = 2;
    row.reviewKey = context.reviewText ? editSelectionHash(context.reviewText) : row.reviewKey || row.source;
}
function editSelectionWrapItem(heading, item) {
    var existing = heading.closest('.edit-selection-item');
    if (existing) return existing;
    var card = heading.closest('.group-edit-card');
    var section = card || document.createElement('section');
    if (!card) {
        var level = /^H\d$/.test(heading.tagName) ? Number(heading.tagName[1]) : 6;
        heading.before(section);
        var node = heading;
        while (node) {
            var next = node.nextElementSibling;
            section.appendChild(node);
            if (!next || next.matches('.edit-selection-item') || /^H\d$/.test(next.tagName) && Number(next.tagName[1]) <= level) break;
            node = next;
        }
    }
    section.classList.add('edit-selection-item');
    section._editSelectionItem = item;
    section._editSelectionHeading = heading;
    return section;
}
function editSelectionPrepareItems(parent) {
    if (parent._editSelectionItemsPrepared) return;
    parent._editSelectionItemsPrepared = true;
    parent.querySelectorAll('.group-edit-card').forEach(function(card) {
        var heading = card.querySelector('h3');
        if (heading && !card.closest('.is-withdrawn')) editSelectionWrapItem(heading, editSelectionItem(card.querySelector('blockquote') || heading));
    });
    var numbered = /^(?:(?:edit|item|suggestion|finding)\s+)?(\d+)(?:[.):]\s*|\s+[—–-]\s*|$)(.*)$/i;
    var headings = Array.from(parent.querySelectorAll('h1,h2,h3,h4,h5,h6,p > strong:first-child')).map(function(node) {
        return node.tagName === 'STRONG' ? node.parentElement : node;
    }).filter(function(node) {
        return !node.closest('.edit-selection-item, blockquote, li, .is-withdrawn') && numbered.test(node.textContent.trim());
    });
    headings.reverse().forEach(function(heading) {
        var match = heading.textContent.trim().match(numbered);
        editSelectionWrapItem(heading, {number: Number(match[1]), title: match[2].trim() || 'Item ' + match[1], heading: heading});
    });
    parent.querySelectorAll('ol > li').forEach(function(item) {
        if (item.closest('.edit-selection-item, .is-withdrawn') || item.parentElement.closest('li')) return;
        var number = Number(item.parentElement.getAttribute('start') || 1);
        Array.from(item.parentElement.children).some(function(sibling) {
            if (sibling.tagName !== 'LI') return false;
            if (sibling.hasAttribute('value')) number = Number(sibling.getAttribute('value'));
            if (sibling === item) return true;
            number++;
        });
        var heading = item.querySelector(':scope > p, :scope > h3, :scope > strong') || item.firstElementChild;
        if (!heading || heading.matches('.md-copy-block, blockquote')) return;
        item.classList.add('edit-selection-item'); item._editSelectionHeading = heading;
        item._editSelectionItem = {number: number, title: heading.textContent.trim().split('\n')[0].slice(0, 120), heading: heading};
    });
    // Unnumbered suggestions with concrete edits keep their original title.
    parent.querySelectorAll('blockquote').forEach(function(quote) {
        if (quote.closest('.edit-selection-item, .is-withdrawn') || !quote.dataset.targetPath) return;
        if (!quote._discussCompareOriginal && !quote._discussExplicitEdit) return;
        var item = editSelectionItem(quote), heading = item.heading;
        if (!heading) {
            heading = editSelectionTag('h3', item.title);
            quote.parentElement.before(heading); item.heading = heading;
        }
        editSelectionWrapItem(heading, item);
    });
}
function editSelectionInstruction(section, item, reviewText) {
    var clone = section.cloneNode(true);
    if (/^(P|STRONG)$/.test(section._editSelectionHeading.tagName) && clone.firstElementChild) clone.firstElementChild.remove();
    clone.querySelectorAll('h1,h2,h3,h4,h5,h6,blockquote,.group-edit-heading,.discuss-quote-actions,.md-copy-btn,.group-edit-actions').forEach(function(node) { node.remove(); });
    var paragraphs = Array.from(clone.querySelectorAll('p,li,pre')).filter(function(node) { return !node.querySelector('p,li,pre'); });
    var instruction = paragraphs.map(function(node) {
        var text = node.textContent.trim(), links = Array.from(node.querySelectorAll('a'));
        if (links.length && links.map(function(link) { return link.textContent; }).join(' ').trim() === text) return '';
        return /^Before\s*:\s*$/i.test(text) ? '' : text;
    }).filter(Boolean).join('\n\n');
    var lines = String(reviewText || '').split('\n'), start = -1, level = 6, indent = 0, headingStyle = false;
    for (var i = 0; i < lines.length; i++) {
        var clean = lines[i].replace(/[*_`]/g, '').replace(/^\s*#{1,6}\s*/, '').trim();
        if (clean.includes(item.title) && (item.number == null || new RegExp('^(?:(?:edit|item|suggestion|finding)\\s+)?' + item.number + '[.):\\s]', 'i').test(clean))) {
            start = i; var heading = lines[i].match(/^\s*(#{1,6})\s/); level = heading ? heading[1].length : 6;
            headingStyle = !!heading;
            indent = (lines[i].match(/^\s*/) || [''])[0].length; break;
        }
    }
    var end = lines.length;
    for (var n = start + 1; start >= 0 && n < lines.length; n++) {
        var nextHeading = lines[n].match(/^\s*(#{1,6})\s/);
        var nextNumber = lines[n].replace(/[*_`]/g, '').match(/^(\s*)(?:(?:#{1,6}|edit|item|suggestion|finding)\s+)?\d+[.):]\s/i);
        if (nextHeading && nextHeading[1].length <= level || !headingStyle && nextNumber && nextNumber[1].length <= indent && (!nextHeading || nextHeading[1].length <= level)) { end = n; break; }
    }
    return {text: instruction, markdown: start >= 0 ? lines.slice(start, end).join('\n').trim() : ''};
}
function editSelectionRegisterMessage(parent, context) {
    editSelectionPrepareItems(parent);
    var store = editSelectionStore(context.scope), changed = false;
    var reviewKey = context.reviewText ? editSelectionHash(context.reviewText) : context.source;
    parent.querySelectorAll('.edit-selection-item').forEach(function(section) {
        if (section.closest('.is-withdrawn') || section._editSelectionWidget) return;
        var item = section._editSelectionItem, heading = section._editSelectionHeading;
        if (!item || !heading) return;
        var keys = [], quotes = [];
        function register(signature, values) {
            var key = editSelectionHash(signature), suffix = 1, baseKey = key;
            while (store.records[key] && store.records[key].signature !== signature) key = baseKey + '-' + suffix++;
            if (!store.records[key]) { store.records[key] = Object.assign({key: key, signature: signature, order: store.next++, selected: false, origins: []}, values); changed = true; }
            var row = store.records[key], previous = editSelectionItemKey(row);
            if (!row.order) row.order = row.number || store.next++;
            if (!row.selected || row.source === context.source || row.itemVersion !== 2) {
                if (row.number !== item.number || row.title !== item.title || row.reviewKey !== reviewKey) changed = true;
                editSelectionSetItem(row, item, context);
            }
            var next = editSelectionItemKey(row);
            if (previous !== next && store.notes[previous] != null) {
                if (store.notes[next] == null) store.notes[next] = store.notes[previous];
                delete store.notes[previous];
            }
            if (store.noteEditor && store.noteEditor.itemKey === previous) store.noteEditor.itemKey = next;
            keys.push(key); return row;
        }
        section.querySelectorAll('blockquote').forEach(function(quote) {
            if (quote.closest('.edit-selection-item') !== section || !quote.dataset.targetPath) return;
            var before = quote._discussCompareOriginal || '', after = extractDiscussQuoteText(quote);
            var standalone = !before && quote._discussExplicitEdit && Number(quote.dataset.targetLine) > 0;
            if (!before && !standalone) return;
            var kind = quote._discussCompareKind || 'replace';
            if (/^\[Cut (?:this )?passage\]$/i.test(after)) { after = ''; kind = 'cut'; }
            var path = quote.dataset.targetPath, targetKind = quote.dataset.targetKind || 'scene';
            var signature = JSON.stringify(standalone ? [targetKind, path, kind, before, after, quote.dataset.targetLine, quote.dataset.targetEndLine] : [targetKind, path, kind, before, after]);
            var row = register(signature, {path: path, targetKind: targetKind, line: Number(quote.dataset.targetLine) || null,
                endLine: Number(quote.dataset.targetEndLine) || null, before: before, after: after, kind: kind, sourceReady: !standalone});
            if (row.before) quote._discussCompareOriginal = row.before;
            quotes.push({quote: quote, key: row.key});
        });
        if (!keys.length) {
            var instruction = editSelectionInstruction(section, item, context.reviewText);
            if (!instruction.text) return;
            var evidence = section.querySelector('blockquote[data-target-path]'), link = section.querySelector('a[data-prosview-path]');
            var data = evidence && evidence.dataset || {}, target = link && link.dataset || {};
            register(JSON.stringify([reviewKey, item.number, item.title, 'instruction']), {
                kind: 'instruction', instructionText: instruction.text, instructionMarkdown: instruction.markdown,
                instructionRefs: Array.from(section.querySelectorAll('a[data-prosview-path]')).map(function(link) {
                    return {kind: link.dataset.prosviewKind || 'scene', path: link.dataset.prosviewPath, line: Number(link.dataset.prosviewLine) || null,
                        endLine: Number(link.dataset.prosviewEndLine) || null, label: link.textContent};
                }),
                before: evidence ? extractDiscussQuoteText(evidence) : '', after: '', sourceReady: true,
                path: data.targetPath || target.prosviewPath || '', targetKind: data.targetKind || target.prosviewKind || 'scene',
                line: Number(data.targetLine || target.prosviewLine) || null, endLine: Number(data.targetEndLine || target.prosviewEndLine) || null});
        }
        var selected = keys.some(function(key) { return store.records[key].selected; });
        keys.forEach(function(key) { if (store.records[key].selected !== selected) changed = true; store.records[key].selected = selected; });
        var head = heading.parentElement.matches('.group-edit-heading') ? heading.parentElement : elementWith('edit-selection-item-heading');
        if (head !== heading.parentElement) { heading.before(head); head.appendChild(heading); }
        head.classList.add('edit-selection-item-heading');
        var label = document.createElement('label'), input = document.createElement('input'); input.type = 'checkbox'; label.className = 'edit-selection-control';
        input.setAttribute('aria-label', 'Select item' + (item.number == null ? '' : ' ' + item.number) + ': ' + item.title);
        label.appendChild(input); head.prepend(label);
        var text = elementWith('edit-selection-item-state'); head.appendChild(text);
        var noteHost = elementWith('edit-selection-note-host'); head.after(noteHost);
        var noteButton = editSelectionButton('Add note', 'edit-selection-add-note', function(event) {
            event.stopPropagation(); editSelectionOpenNote(context.scope, store.records[keys[0]], noteHost, 'item');
        }); head.appendChild(noteButton);
        var widget = {scope: context.scope, key: keys[0], keys: keys, quote: section, anchor: heading, input: input, label: label, text: text, item: item, noteButton: noteButton, noteHost: noteHost, quotes: quotes};
        section._editSelectionWidget = widget; _editSelectionWidgets.add(widget);
        ['click', 'mousedown', 'keydown'].forEach(function(name) { label.addEventListener(name, function(event) { event.stopPropagation(); }); });
        input.onchange = function() {
            keys.forEach(function(key) {
                var row = store.records[key]; row.selected = input.checked;
                if (row.selected) { editSelectionSetItem(row, item, context); row.applied = false; if (row.sourceReady === false) editSelectionResolveSource(context.scope, row); }
            });
            if (!input.checked && store.noteEditor && store.noteEditor.itemKey === editSelectionItemKey(store.records[keys[0]])) store.noteEditor = null;
            editSelectionUpdateDraft(context.scope); editSelectionSave(context.scope); editSelectionPaint(context.scope);
        };
        keys.forEach(function(key) { if (store.records[key].selected && store.records[key].sourceReady === false) editSelectionResolveSource(context.scope, store.records[key]); });
        editSelectionPaintWidget(widget);
    });
    if (changed) editSelectionSave(context.scope);
}
function editSelectionPaintWidget(widget) {
    var store = editSelectionStore(widget.scope), rows = widget.keys.map(function(key) { return store.records[key]; }).filter(Boolean);
    if (!rows.length) return;
    var selected = rows.every(function(row) { return row.selected; }), applied = rows.every(function(row) { return row.applied; });
    widget.input.checked = selected; widget.input.hidden = applied;
    widget.text.textContent = applied ? '✓ Applied' : rows.some(function(row) { return row.requested; }) ? 'Requested' : '';
    var error = rows.find(function(row) { return row.sourceError; });
    if (selected && rows.some(function(row) { return row.sourceReady === false; })) widget.text.textContent = 'Reading source…';
    if (error) widget.text.textContent = 'Check source';
    widget.label.title = error ? error.sourceError : '';
    widget.label.classList.toggle('is-edit-applied', applied);
    widget.quote.classList.toggle('is-item-selected', selected);
    widget.quotes.forEach(function(entry) { entry.quote.classList.toggle('is-edit-selected', selected); });
    widget.noteButton.hidden = !selected || !!editSelectionNote(widget.scope, rows[0]).trim();
    editSelectionRenderNote(widget.scope, rows[0], widget.noteHost, 'item');
}
function editSelectionResolveSource(scope, row) {
    var jobKey = scope + ':' + row.key;
    if (_editSelectionSourceJobs.has(jobKey)) return _editSelectionSourceJobs.get(jobKey);
    row.sourceError = '';
    var target = {kind: row.targetKind, path: row.path};
    var job = discussApi('/api/discuss/compare-quote', {document: target, quote: row.after,
        line: row.line, end_line: row.endLine, kind: row.kind, prefer_line: true,
        live_document: discussLiveDocumentFor(target)}).then(function(result) {
        if (result.unavailable || !result.before) throw new Error(result.unavailable || 'Could not read the cited passage.');
        row.before = result.before; row.sourceReady = true;
        _editSelectionWidgets.forEach(function(widget) {
            if (widget.scope === scope) widget.quotes.forEach(function(entry) { if (entry.key === row.key) entry.quote._discussCompareOriginal = row.before; });
        });
    }).catch(function(error) {
        row.sourceError = error.message;
        var store = editSelectionStore(scope), itemKey = editSelectionItemKey(row);
        Object.values(store.records).forEach(function(record) { if (editSelectionItemKey(record) === itemKey) record.selected = false; });
    }).finally(function() {
        _editSelectionSourceJobs.delete(jobKey); editSelectionUpdateDraft(scope); editSelectionSave(scope); editSelectionPaint(scope);
    });
    _editSelectionSourceJobs.set(jobKey, job); return job;
}
function editSelectionReference(row) {
    return row.path ? row.path + (row.line ? ' · Line ' + row.line + (row.endLine && row.endLine !== row.line ? '–' + row.endLine : '') : '') : '';
}
function editSelectionJump(scope, row) {
    var widget = Array.from(_editSelectionWidgets).find(function(item) { return item.scope === scope && item.keys.includes(row.key) && item.quote.isConnected; });
    if (!widget) return;
    var message = widget.quote.closest('[data-group-turn]');
    if (message && message._groupSetCollapsed) message._groupSetCollapsed(false);
    var card = widget.quote.closest('.group-edit-card');
    if (card && !card.classList.contains('is-edit-expanded')) card.querySelector('.group-edit-actions button').click();
    editSelectionStore(scope).open = false; editSelectionPaint(scope);
    widget.anchor.scrollIntoView({block: 'start'}); widget.input.focus({preventScroll: true});
}
function editSelectionButton(label, className, action) {
    var button = document.createElement('button'); button.type = 'button'; button.className = className || ''; button.textContent = label; button.onclick = action; return button;
}
function editSelectionPaintNotes(scope) {
    _editSelectionWidgets.forEach(function(widget) {
        if (widget.scope === scope && widget.quote.isConnected) editSelectionPaintWidget(widget);
    });
    var component = _editSelectionComposers.get(scope);
    if (!component) return;
    component.root.querySelectorAll('.edit-selection-note-host').forEach(function(host) {
        var row = editSelectionStore(scope).records[host.dataset.selectionKey];
        if (row) editSelectionRenderNote(scope, row, host, 'review');
    });
    component.root.querySelectorAll('.edit-selection-ids [data-selection-key]').forEach(function(button) {
        var row = editSelectionStore(scope).records[button.dataset.selectionKey], note = row && editSelectionNote(scope, row).trim();
        button.classList.toggle('has-note', !!note);
        if (row) button.title = row.title + (note ? ' · Note: ' + note : '');
    });
    var status = component.root.querySelector('.edit-selection-note-status');
    if (status) status.textContent = editSelectionNotesPending(scope) ? 'Notes changed · Update request' : '';
}
function editSelectionOpenNote(scope, row, host, location) {
    var store = editSelectionStore(scope);
    store.noteEditor = {itemKey: editSelectionItemKey(row), location: location, host: host, focused: true};
    editSelectionPaintNotes(scope);
    var input = host.querySelector('textarea');
    if (input) { input.focus({preventScroll: true}); input.setSelectionRange(input.value.length, input.value.length); input.scrollIntoView({block: 'nearest'}); }
}
function editSelectionCloseNote(scope, host) {
    var store = editSelectionStore(scope);
    store.noteEditor = null;
    editSelectionPaintNotes(scope);
    var button = host.querySelector('button');
    if (!button) {
        var widget = Array.from(_editSelectionWidgets).find(function(item) { return item.noteHost === host; });
        button = widget && widget.noteButton;
    }
    if (button) button.focus({preventScroll: true});
}
function editSelectionRenderNote(scope, row, host, location) {
    var store = editSelectionStore(scope), key = editSelectionItemKey(row), note = editSelectionNote(scope, row);
    host.dataset.selectionKey = row.key;
    if (!host._editSelectionEvents) {
        ['click', 'mousedown', 'keydown'].forEach(function(name) { host.addEventListener(name, function(event) { event.stopPropagation(); }); });
        host._editSelectionEvents = true;
    }
    var editor = store.noteEditor;
    var editing = editor && editor.itemKey === key && editor.location === location
        && (editor.host === host || !editor.host || !editor.host.isConnected);
    host.hidden = !row.selected;
    if (!row.selected) { host.replaceChildren(); return; }
    if (editing) {
        editor.host = host;
        if (host.querySelector('textarea')) return;
        host.replaceChildren();
        var field = elementWith('edit-selection-note-editor');
        var id = 'edit-note-' + editSelectionHash(scope + key + location);
        var label = document.createElement('label'); label.htmlFor = id; label.textContent = 'Your instruction for item ' + editSelectionItemName(row);
        var input = document.createElement('textarea'); input.id = id; input.rows = 2; input.value = note;
        input.placeholder = 'Change wording, add a condition, or ask a question…';
        function rememberCaret() { editor.start = input.selectionStart; editor.end = input.selectionEnd; }
        input.onfocus = function() { editor.focused = true; rememberCaret(); };
        input.onblur = function() { editor.focused = false; };
        input.onselect = input.onkeyup = rememberCaret;
        input.oninput = function() {
            store.notes[key] = input.value; rememberCaret();
            editSelectionSave(scope); editSelectionPaintNotes(scope);
        };
        input.onkeydown = function(event) {
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); editSelectionCloseNote(scope, host); }
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') event.preventDefault();
        };
        var foot = elementWith('edit-selection-note-editor-footer');
        foot.appendChild(editSelectionTag('span', 'Saved automatically'));
        foot.appendChild(editSelectionButton('Remove note', '', function() {
            delete store.notes[key]; editSelectionSave(scope); editSelectionCloseNote(scope, host);
        }));
        foot.appendChild(editSelectionButton('Done', '', function() { editSelectionCloseNote(scope, host); }));
        field.append(label, input, foot); host.appendChild(field);
        if (editor.focused) queueMicrotask(function() {
            if (host.isConnected && store.noteEditor === editor) { input.focus({preventScroll: true}); input.setSelectionRange(editor.start == null ? note.length : editor.start, editor.end == null ? note.length : editor.end); }
        });
        return;
    }
    host.replaceChildren();
    if (note.trim()) {
        var preview = editSelectionButton('', 'edit-selection-note-preview', function() { editSelectionOpenNote(scope, row, host, location); });
        preview.setAttribute('aria-label', 'Change note for item ' + editSelectionItemName(row));
        preview.title = note.trim();
        preview.append(editSelectionTag('span', 'Your note'), editSelectionTag('span', note.trim())); host.appendChild(preview);
    } else if (location === 'review') {
        host.appendChild(editSelectionButton('Add note', 'edit-selection-add-note', function() { editSelectionOpenNote(scope, row, host, location); }));
    }
}
function editSelectionMount(scope, container, input, quick, session) {
    var old = _editSelectionComposers.get(scope);
    if (old && old.container === container && container.contains(old.root)) {
        if (editSelectionRecords(scope).every(function(row) { return row.itemVersion === 2; })) editSelectionUpdateDraft(scope);
        editSelectionPaint(scope); return;
    }
    var root = elementWith('edit-selection-composer');
    root.dataset.selectionScope = scope;
    var before = container.querySelector('label[for="' + input.id + '"]') || input.closest('.discuss-input-wrap, .group-input-wrap');
    container.insertBefore(root, quick && quick.parentNode === container ? quick : before);
    var component = {scope: scope, container: container, root: root, input: input, quick: quick, session: session || null};
    _editSelectionComposers.set(scope, component);
    if (input._editSelectionInputListener) input.removeEventListener('input', input._editSelectionInputListener);
    input._editSelectionInputListener = function() {
        var action = root.querySelector('.edit-selection-prepare');
        if (action) action.textContent = editSelectionConflicts(scope).size && !editSelectionHasCustomInstructions(scope, input.value)
            ? 'Choose wording' : editSelectionStore(scope).prepared ? 'Update request' : 'Prepare request';
    };
    input.addEventListener('input', input._editSelectionInputListener);
    // Wait for restored messages to migrate old item numbers before changing a
    // saved generated draft; changing it sooner can cancel history restoration.
    if (editSelectionRecords(scope).every(function(row) { return row.itemVersion === 2; })) editSelectionUpdateDraft(scope);
    if (editSelectionStore(scope).prepared) editSelectionSave(scope);
    editSelectionPaint(scope);
}
function editSelectionHasCustomInstructions(scope, text) {
    var prepared = editSelectionStore(scope).prepared;
    if (editSelectionRecords(scope).some(function(row) { return !!editSelectionNote(scope, row).trim(); })) return true;
    return !!String(text || '').trim() && (!prepared || !prepared.generated || String(text).trim() !== prepared.generated.trim());
}
function editSelectionMountChat() {
    if (!_discussSnapshot || !_discussConversationId) return;
    var container = document.getElementById('discussComposerArea');
    var input = document.getElementById('discussInput');
    var scope = editSelectionChatScope();
    container.querySelectorAll('.edit-selection-composer').forEach(function(node) { if (node.dataset.selectionScope !== scope) node.remove(); });
    editSelectionMount(scope, container, input, document.getElementById('discussTaskMode'));
}
function editSelectionPaint(scope) {
    _editSelectionWidgets.forEach(function(widget) {
        if (widget.scope === scope && widget.quote.isConnected) editSelectionPaintWidget(widget);
        else if (!widget.quote.isConnected) _editSelectionWidgets.delete(widget);
    });
    var component = _editSelectionComposers.get(scope);
    if (!component || component.painting) return;
    component.painting = true;
    var store = editSelectionStore(scope), rows = editSelectionRecords(scope), conflicts = editSelectionConflicts(scope);
    var groups = editSelectionGroups(rows), countText = groups.length + (groups.length === 1 ? ' item' : ' items');
    var root = component.root;
    var previousList = root.querySelector('.edit-selection-review-list'), scrollTop = previousList ? previousList.scrollTop : 0;
    root.replaceChildren(); root.hidden = !rows.length;
    if (component.quick) component.quick.classList.toggle('has-edit-selections', !!rows.length);
    if (!rows.length) { component.painting = false; return; }
    var panel = elementWith('edit-selection-review'); panel.hidden = !store.open; panel.id = 'selected-items-' + editSelectionHash(scope);
    var head = elementWith('edit-selection-review-head');
    var files = new Set(rows.map(function(row) { return row.path; }).filter(Boolean)).size;
    head.append(editSelectionTag('strong', 'Selected items'), editSelectionTag('span', countText
        + (rows.length === groups.length ? '' : ' · ' + rows.length + ' edits') + (files ? ' · ' + files + (files === 1 ? ' file' : ' files') : '')));
    var close = editSelectionButton('×', '', function() { store.open = false; editSelectionPaint(scope); component.root.querySelector('.edit-selection-count').focus(); });
    close.setAttribute('aria-label', 'Close selected items'); head.appendChild(close); panel.appendChild(head);
    if (conflicts.size) panel.appendChild(elementWith('edit-selection-conflict', 'Some selections change overlapping passages. Keep one wording for each passage.'));
    if (component.error) panel.appendChild(elementWith('edit-selection-conflict', component.error));
    var list = elementWith('edit-selection-review-list');
    groups.forEach(function(group) {
        var row = group.row;
        var item = elementWith('edit-selection-review-item'); item.classList.toggle('has-conflict', group.edits.some(function(edit) { return conflicts.has(edit.key); }));
        var title = elementWith('edit-selection-review-title');
        title.appendChild(editSelectionButton((row.number == null ? '' : row.number + '. ') + row.title, '', function() { editSelectionJump(scope, row); }));
        var remove = editSelectionButton('×', '', function() {
            group.edits.forEach(function(edit) { edit.selected = false; });
            if (store.noteEditor && store.noteEditor.itemKey === group.key) store.noteEditor = null;
            editSelectionUpdateDraft(scope); editSelectionSave(scope); editSelectionPaint(scope);
        });
        remove.setAttribute('aria-label', 'Remove item ' + editSelectionItemName(row)); title.appendChild(remove); item.appendChild(title);
        var noteHost = elementWith('edit-selection-note-host'); noteHost.dataset.selectionKey = row.key; item.appendChild(noteHost);
        group.edits.forEach(function(row) {
            var passage = elementWith('edit-selection-review-edit');
            var reference = document.createElement('a'); reference.href = '#'; reference.textContent = editSelectionReference(row);
            reference.onclick = function(event) { event.preventDefault(); openProsviewFileReference({kind: row.targetKind, path: row.path, line: row.line, endLine: row.endLine}); };
            if (row.path) passage.appendChild(reference);
            if (row.speaker) passage.appendChild(elementWith('edit-selection-speaker', row.speaker));
            if (row.kind === 'instruction') {
                if (row.before) {
                    var evidence = document.createElement('p'); evidence.append(editSelectionTag('b', 'Passage '), editSelectionTag('em', row.before)); passage.appendChild(evidence);
                }
                var action = document.createElement('p'); action.className = 'edit-selection-instruction';
                action.append(editSelectionTag('b', 'Suggested action '), document.createTextNode(row.instructionText)); passage.appendChild(action);
                var seen = new Set([JSON.stringify([row.path, row.line])]);
                (row.instructionRefs || []).forEach(function(ref) {
                    var key = JSON.stringify([ref.path, ref.line]); if (seen.has(key)) return; seen.add(key);
                    var link = document.createElement('a'); link.href = '#'; link.textContent = ref.label;
                    link.onclick = function(event) { event.preventDefault(); openProsviewFileReference(ref); }; passage.appendChild(link);
                });
                item.appendChild(passage); return;
            }
            var before = document.createElement('p'); before.append(editSelectionTag('b', row.kind.indexOf('insert-') === 0 ? 'Anchor ' : 'Before '), editSelectionTag('em', row.before || 'Reading the cited passage…'));
            var after = document.createElement('p'); after.append(editSelectionTag('b', 'After '), document.createTextNode(row.after || '[Cut this passage]'));
            passage.append(before, after);
            passage.appendChild(editSelectionButton('Compare passage', 'edit-selection-compare', function(event) {
                var quote = document.createElement('blockquote'); quote.dataset.targetKind = row.targetKind; quote.dataset.targetPath = row.path;
                if (row.line) quote.dataset.targetLine = row.line; if (row.endLine) quote.dataset.targetEndLine = row.endLine;
                quote._discussCompareOriginal = row.before; quote._discussCompareKind = row.kind;
                quote.appendChild(editSelectionTag('p', row.after || '[Cut this passage]'));
                openDiscussQuoteComparison(quote, event.currentTarget);
            })); item.appendChild(passage);
        });
        list.appendChild(item);
    });
    panel.appendChild(list); root.appendChild(panel);
    var tray = elementWith('edit-selection-tray');
    var count = editSelectionButton(countText + ' selected ' + (store.open ? '⌄' : '⌃'), 'edit-selection-count', function() { store.open = !store.open; editSelectionPaint(scope); });
    count.setAttribute('aria-expanded', String(store.open)); count.setAttribute('aria-controls', panel.id); tray.appendChild(count);
    var ids = elementWith('edit-selection-ids');
    groups.slice(0, 5).forEach(function(group) {
        var row = group.row, button = editSelectionButton(row.number == null ? row.title : String(row.number), '', function() { editSelectionJump(scope, row); });
        button.dataset.selectionKey = row.key; button.title = row.title; ids.appendChild(button);
    });
    if (groups.length > 5) {
        var more = editSelectionButton('+' + (groups.length - 5) + ' more', 'edit-selection-more', function() {
            store.open = true; editSelectionPaint(scope); component.root.querySelector('.edit-selection-review-head button').focus({preventScroll: true});
        });
        more.setAttribute('aria-controls', panel.id); more.setAttribute('aria-expanded', String(store.open)); ids.appendChild(more);
    }
    tray.appendChild(ids);
    tray.appendChild(editSelectionButton('Clear', 'edit-selection-clear', function() { rows.forEach(function(row) { row.selected = false; }); store.noteEditor = null; editSelectionUpdateDraft(scope); editSelectionSave(scope); editSelectionPaint(scope); }));
    var prepare = editSelectionButton(conflicts.size && !editSelectionHasCustomInstructions(scope, component.input.value) ? 'Choose wording' : store.prepared ? 'Update request' : 'Prepare request', 'edit-selection-prepare', function() { editSelectionPrepare(scope); });
    prepare.disabled = rows.some(function(row) { return row.sourceReady === false; }); tray.appendChild(prepare);
    root.appendChild(tray);
    if (store.prepared) {
        var included = elementWith('edit-selection-included');
        included.appendChild(editSelectionButton(countText + ' included · Review', '', function() { store.open = !store.open; editSelectionPaint(scope); }));
        var status = elementWith('edit-selection-note-status'); status.setAttribute('aria-live', 'polite'); included.appendChild(status);
        var detach = editSelectionButton('×', '', function() { editSelectionDetach(scope); editSelectionPaint(scope); });
        detach.setAttribute('aria-label', 'Remove included edits'); included.appendChild(detach); root.appendChild(included);
    }
    component.painting = false;
    list.scrollTop = scrollTop;
    editSelectionPaintNotes(scope);
}
function editSelectionSetInput(component, value) {
    component.input.value = value;
    component.input.dispatchEvent(new Event('input', {bubbles: true}));
}
function editSelectionDetach(scope) {
    var store = editSelectionStore(scope), component = _editSelectionComposers.get(scope);
    if (store.prepared && component) {
        var text = editSelectionReplaceBlock(component.input.value, store.prepared.generated, '');
        Object.values(store.prepared.notes || {}).forEach(function(line) { text = editSelectionReplaceBlock(text, line, ''); });
        editSelectionSetInput(component, text.trim());
    }
    store.prepared = null; editSelectionSave(scope);
}
function editSelectionItemReference(row, multipleReviews) {
    return editSelectionItemName(row) + (multipleReviews && row.number != null ? ' (“' + row.title + '”)' : '');
}
function editSelectionRequestLine(rows) {
    var groups = editSelectionGroups(rows);
    var multipleReviews = new Set(groups.map(function(group) { return group.row.reviewKey || group.row.source; })).size > 1;
    var names = Array.from(new Set(groups.map(function(group) {
        return editSelectionItemReference(group.row, multipleReviews);
    })));
    return 'Apply ' + (names.length === 1 ? 'item ' : 'items ') + names.join(', ') + '.';
}
function editSelectionNoteLines(scope, rows) {
    var groups = editSelectionGroups(rows), lines = {};
    var multipleReviews = new Set(groups.map(function(group) { return group.row.reviewKey || group.row.source; })).size > 1;
    groups.forEach(function(group) {
        var note = editSelectionNote(scope, group.row).trim();
        if (note) lines[group.key] = 'For item ' + editSelectionItemReference(group.row, multipleReviews) + ': ' + note;
    });
    return lines;
}
function editSelectionBlockIndex(text, block) {
    if (!block) return -1;
    var index = text.indexOf(block);
    while (index >= 0) {
        var end = index + block.length;
        if ((!index || text[index - 1] === '\n') && (end === text.length || text[end] === '\n')) return index;
        index = text.indexOf(block, index + 1);
    }
    return -1;
}
function editSelectionReplaceBlock(text, previous, next) {
    var index = editSelectionBlockIndex(text, previous);
    return index < 0 ? text : text.slice(0, index) + next + text.slice(index + previous.length);
}
function editSelectionPreparedValue(scope, text) {
    var store = editSelectionStore(scope), previous = store.prepared || {}, rows = editSelectionRecords(scope);
    var generated = editSelectionRequestLine(rows), automatic = !text.trim() || editSelectionBlockIndex(text, previous.generated) >= 0;
    var value = !text.trim() ? generated : editSelectionReplaceBlock(text, previous.generated, generated);
    var nextNotes = editSelectionNoteLines(scope, rows), managed = {};
    Object.entries(previous.notes || {}).forEach(function(entry) {
        var key = entry[0], line = entry[1];
        if (editSelectionBlockIndex(value, line) >= 0) value = editSelectionReplaceBlock(value, line, nextNotes[key] || '');
        // A note line edited directly in chat belongs to the writer. Preserve it.
        else if (nextNotes[key]) managed[key] = line;
    });
    Object.entries(nextNotes).forEach(function(entry) {
        if (managed[entry[0]]) return;
        if (editSelectionBlockIndex(value, entry[1]) < 0) value = value.trimEnd() + '\n\n' + entry[1];
        managed[entry[0]] = entry[1];
    });
    return {value: value.trim(), prepared: {generated: automatic ? generated : '', keys: rows.map(function(row) { return row.key; }), notes: managed, noteValues: nextNotes}};
}
function editSelectionPrepare(scope) {
    var store = editSelectionStore(scope), component = _editSelectionComposers.get(scope), rows = editSelectionRecords(scope);
    if (!component || !rows.length) return;
    if (rows.some(function(row) { return row.sourceReady === false; })) return;
    if (editSelectionConflicts(scope).size && !editSelectionHasCustomInstructions(scope, component.input.value)) { store.open = true; editSelectionPaint(scope); return; }
    var draft = editSelectionPreparedValue(scope, component.input.value);
    store.prepared = draft.prepared; store.open = false;
    if (component.session) {
        var target = component.container.querySelector('#groupTargetSelect');
        if (target && !/^critic\d+$/.test(target.value)) { target.value = 'critic1'; target.dispatchEvent(new Event('change')); }
    }
    editSelectionSetInput(component, draft.value); editSelectionSave(scope); editSelectionPaint(scope); component.input.focus({preventScroll: true});
}
function editSelectionUpdateDraft(scope) {
    var store = editSelectionStore(scope), component = _editSelectionComposers.get(scope);
    if (!store.prepared || !component) return;
    var rows = editSelectionRecords(scope);
    if (rows.some(function(row) { return row.sourceReady === false; })) return;
    if (!rows.length) { editSelectionDetach(scope); return; }
    var generated = editSelectionRequestLine(rows);
    var automatic = editSelectionBlockIndex(component.input.value, store.prepared.generated) >= 0;
    var value = editSelectionReplaceBlock(component.input.value, store.prepared.generated, generated);
    var selected = new Set(editSelectionGroups(rows).map(function(group) { return group.key; }));
    Object.keys(store.prepared.notes || {}).forEach(function(key) {
        if (!selected.has(key)) {
            value = editSelectionReplaceBlock(value, store.prepared.notes[key], '').trim();
            delete store.prepared.notes[key];
            if (store.prepared.noteValues) delete store.prepared.noteValues[key];
        }
    });
    store.prepared.generated = automatic ? generated : ''; store.prepared.keys = rows.map(function(row) { return row.key; });
    if (component.input.value !== value) editSelectionSetInput(component, value);
}
function editSelectionMarkdown(rows) {
    return rows.map(function(row) {
        var reference = editSelectionReference(row), path = row.path;
        if (row.targetKind === 'scene') {
            var files = typeof repositoryFileByPath !== 'undefined' ? repositoryFileByPath : {};
            var file = Object.values(files).find(function(node) { return node.is_scene && node.scene_path === row.path; });
            path = file ? file.path : (meta[row.path] || {}).abs_path || row.path;
        }
        var source = '[' + reference + '](<' + path + (row.line ? '#L' + row.line + (row.endLine && row.endLine !== row.line ? '-L' + row.endLine : '') : '') + '>)';
        if (row.kind === 'instruction') {
            var body = row.instructionMarkdown ? row.instructionMarkdown.split('\n').slice(1).join('\n').trim() :
                (row.before ? '> *' + row.before + '*\n\n' + source + '\n\n' : '') + row.instructionText;
            return '### Edit ' + (row.number == null ? '' : row.number + ': ') + row.title + '\n\n' + body;
        }
        return '### Edit ' + (row.number == null ? '' : row.number + ': ') + row.title + '\n\n' + (row.speaker ? 'Source: ' + row.speaker + '\n\n' : '')
            + '**Before:**\n\n' + row.before.split('\n').map(function(line) { return line ? '> *' + line + '*' : '>'; }).join('\n')
            + '\n\n' + source + '\n\n**After:** ' + (row.kind === 'insert-after' ? 'Insert after ' : row.kind === 'insert-before' ? 'Insert before ' : 'Replace ') + source
            + ':\n\n' + (row.after || '[Cut this passage]').split('\n').map(function(line) { return '> ' + line; }).join('\n');
    }).join('\n\n');
}
function editSelectionReviewText(text) {
    return editSelectionNormal(String(text || '').replace(/^\s*> ?/gm, '').replace(/[*_]/g, ''));
}
function editSelectionReviews(component) {
    if (component && component.session) return (component.session.turns || []).filter(function(turn) { return turn.role === 'critic'; });
    return ((_discussSnapshot || {}).messages || []).filter(function(message) {
        return message.role === 'assistant' && !/^(?:thought|commentary)$/.test(message.phase || '');
    });
}
function editSelectionReviewIndex(row, reviews) {
    var passage = editSelectionReviewText(row.after || row.before || row.instructionText);
    if (!passage) return -1;
    for (var i = reviews.length - 1; i >= 0; i--) {
        var text = editSelectionReviewText(reviews[i].text);
        if (row.instructionMarkdown && text.includes(editSelectionReviewText(row.instructionMarkdown))) return i;
        if (text.includes(passage) && text.includes(editSelectionReviewText(row.title))) return i;
    }
    return -1;
}
function editSelectionOutgoing(scope, text) {
    var store = editSelectionStore(scope), component = _editSelectionComposers.get(scope);
    var rows = editSelectionRecords(scope);
    if (!store.prepared && !rows.some(function(row) { return !!editSelectionNote(scope, row).trim(); })) return {text: text, authored: text, edits: []};
    if (rows.some(function(row) { return row.sourceReady === false; })) { store.open = true; editSelectionPaint(scope); return null; }
    if (editSelectionConflicts(scope).size && !editSelectionHasCustomInstructions(scope, text)) {
        store.open = true; editSelectionPaint(scope); return null;
    }
    if (component && component.session && groupRequestedSeats(text, component.session).length !== 1) {
        component.error = 'Choose one editor in To for this apply request.'; store.open = true; editSelectionPaint(scope); return null;
    }
    var reviews = editSelectionReviews(component);
    var missing = rows.filter(function(row) { return editSelectionReviewIndex(row, reviews) < 0; });
    var earlier = rows.filter(function(row) {
        var index = editSelectionReviewIndex(row, reviews);
        return index >= 0 && index < reviews.length - 1;
    });
    var draft = editSelectionPreparedValue(scope, text), full = draft.value;
    if (earlier.length) full += '\n\nSelected items from earlier reviews: ' + Array.from(new Set(earlier.map(function(row) {
        return (row.speaker ? row.speaker + ' · ' : '') + (row.number == null ? '' : 'item ' + row.number + ': ') + row.title;
    }))).join('; ') + '.';
    if (missing.length) full += EDIT_SELECTION_START + 'Selected proposals for reference:\n\n' + editSelectionMarkdown(missing) + EDIT_SELECTION_END;
    if (new TextEncoder().encode(full).length > 32768) {
        if (component) { component.error = 'These edits make the message too long. Send a smaller selection.'; store.open = true; editSelectionPaint(scope); }
        return null;
    }
    if (component) component.error = '';
    store.prepared = draft.prepared;
    if (component && component.input.value !== draft.value) editSelectionSetInput(component, draft.value);
    editSelectionSave(scope);
    return {text: full, authored: draft.value, edits: rows.map(function(row) { return row.key; })};
}
function editSelectionQueue(scope, requestId, keys) {
    if (!keys.length) return;
    editSelectionStore(scope).pending[requestId] = keys; editSelectionSave(scope);
}
function editSelectionAccepted(scope, requestId) {
    var store = editSelectionStore(scope), keys = store.pending[requestId];
    if (!keys) return;
    keys.forEach(function(key) {
        var row = store.records[key];
        if (!row) return;
        row.requested = Date.now(); row.selected = false;
        (row.origins || []).forEach(function(origin) {
            var previous = editSelectionStore(origin).records[key];
            if (previous) { previous.requested = row.requested; previous.selected = false; editSelectionSave(origin); }
        });
    });
    delete store.pending[requestId]; store.prepared = null; store.noteEditor = null; store.open = false; editSelectionSave(scope); editSelectionPaint(scope);
}
function editSelectionRenderReceipt(parent, text, scene) {
    var start = String(text || '').indexOf(EDIT_SELECTION_START);
    if (start < 0) return false;
    var end = text.indexOf(EDIT_SELECTION_END, start);
    if (end < 0) return false;
    renderDiscussMarkdown(parent, text.slice(0, start), scene);
    var markdown = text.slice(start + EDIT_SELECTION_START.length, end);
    var details = document.createElement('details'); details.className = 'edit-selection-receipt';
    var count = (markdown.match(/^### Edit /gm) || []).length;
    details.appendChild(editSelectionTag('summary', count + (count === 1 ? ' selected edit' : ' selected edits') + ' included'));
    var body = elementWith('discuss-message'); renderDiscussMarkdown(body, markdown, scene); details.appendChild(body); parent.appendChild(details);
    if (text.slice(end + EDIT_SELECTION_END.length).trim()) renderDiscussMarkdown(parent, text.slice(end + EDIT_SELECTION_END.length), scene);
    return true;
}
function editSelectionTransferToGroup(groupId) {
    var from = editSelectionChatScope(), source = editSelectionStore(from), scope = 'group:' + groupId, target = editSelectionStore(scope);
    Object.values(source.records).forEach(function(row) { target.records[row.key] = Object.assign({}, row, {origins: Array.from(new Set((row.origins || []).concat(from)))}); });
    target.notes = Object.assign({}, source.notes, target.notes);
    target.next = Math.max(target.next, source.next); editSelectionSave(scope);
}
function editSelectionVerify(scope, stamp) {
    var store = editSelectionStore(scope);
    if (store.verified === stamp) return;
    store.verified = stamp;
    Object.values(store.records).filter(function(row) { return row.requested && row.kind !== 'instruction'; }).forEach(function(row) {
        discussApi('/api/discuss/compare-quote', {document: {kind: row.targetKind, path: row.path}, quote: row.after,
            original: row.before, line: row.line, end_line: row.endLine, kind: row.kind === 'cut' ? 'replace' : row.kind}).then(function(result) {
            if (store.verified !== stamp) return;
            row.applied = !!result.matches && !result.unsaved;
            if (row.applied) row.selected = false;
            (row.origins || []).forEach(function(origin) { var previous = editSelectionStore(origin).records[row.key]; if (previous) { previous.applied = row.applied; if (row.applied) previous.selected = false; editSelectionSave(origin); } });
        }).catch(function() { if (store.verified === stamp) row.applied = false; }).finally(function() { editSelectionSave(scope); editSelectionPaint(scope); });
    });
}
function editSelectionReconcile(scope, requestIds) {
    (requestIds || []).forEach(function(id) { editSelectionAccepted(scope, id); });
}
document.addEventListener('keydown', function(event) {
    if (event.key !== 'Escape' || document.getElementById('discussDiffModalOverlay') && !document.getElementById('discussDiffModalOverlay').hidden) return;
    _editSelectionComposers.forEach(function(component, scope) {
        var store = editSelectionStore(scope);
        if (store.open && component.root.isConnected) { store.open = false; editSelectionPaint(scope); component.root.querySelector('.edit-selection-count').focus(); event.preventDefault(); }
    });
});
