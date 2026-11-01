        // Callouts: > [!type] Title boxes, GitHub's and Obsidian's syntax.
        //
        // A quotation whose first line is exactly [!type], optionally with
        // - or + (Obsidian's folding: kept, never acted on) and a title, is
        // a callout: book text in a box, unlike TODOs and notes, which are
        // comments. The same rule as proseview/callouts.py, which the
        // exports use; tests/test_callout_editor.py runs both on one set of
        // cases. The type is kept as written ("NOTE") so a save writes it
        // back unchanged; CSS and colours match it lower-cased.

        var CALLOUT_MARKER_RE = /^\[!([A-Za-z][A-Za-z0-9-]*)\]([+-]?)(?:[ \t]+(.*?))?[ \t]*$/;
        var CALLOUT_TYPE_RE = /^[A-Za-z][A-Za-z0-9-]*$/;
        // The types GitHub draws; a book's own (letter, sms) come from the config.
        var CALLOUT_GITHUB_TYPES = ['note', 'tip', 'important', 'warning', 'caution'];

        // {type, fold, title} for a callout's first line, else null.
        function parseCalloutMarker(line) {
            var match = CALLOUT_MARKER_RE.exec(line);
            if (!match) return null;
            return {type: match[1], fold: match[2], title: (match[3] || '').trim()};
        }

        // Adds the callout rule to a markdown-it instance, once.
        function calloutPlugin(md) {
            if (md.__proseviewCallouts) return md;
            md.__proseviewCallouts = true;
            md.core.ruler.after('block', 'callouts', calloutRule);
            return md;
        }

        function calloutRule(state) {
            var tokens = state.tokens;
            for (var i = 0; i < tokens.length; i++) {
                var token = tokens[i];
                if (token.type !== 'blockquote_open' || i + 2 >= tokens.length) continue;
                var para = tokens[i + 1], inline = tokens[i + 2];
                if (para.type !== 'paragraph_open' || inline.type !== 'inline') continue;
                var newline = inline.content.indexOf('\n');
                var first = newline < 0 ? inline.content : inline.content.slice(0, newline);
                var rest = newline < 0 ? '' : inline.content.slice(newline + 1);
                var marker = parseCalloutMarker(first);
                if (!marker) continue;
                var close = calloutMatchingClose(tokens, i);
                var kind = marker.type.toLowerCase();
                token.type = 'callout_open';
                token.tag = 'div';
                token.attrs = [['class', 'callout callout-' + kind], ['data-callout', kind]];
                token.meta = {type: kind, raw: marker.type, fold: marker.fold, title: marker.title};
                tokens[close].type = 'callout_close';
                tokens[close].tag = 'div';
                var titleTokens = [];
                if (marker.title) {
                    var opener = new state.Token('callout_title_open', 'p', 1);
                    opener.attrs = [['class', 'callout-title']];
                    opener.map = inline.map;
                    opener.level = token.level + 1;
                    opener.block = true;
                    var text = new state.Token('inline', '', 0);
                    text.content = marker.title;
                    text.map = inline.map;
                    text.level = token.level + 2;
                    text.children = [];
                    var closer = new state.Token('callout_title_close', 'p', -1);
                    closer.level = token.level + 1;
                    closer.block = true;
                    titleTokens = [opener, text, closer];
                }
                if (rest.trim()) {
                    inline.content = rest;
                    tokens.splice.apply(tokens, [i + 1, 0].concat(titleTokens));
                } else {
                    // The marker was the whole paragraph: drop it.
                    tokens.splice.apply(tokens, [i + 1, 3].concat(titleTokens));
                }
            }
        }

        function calloutMatchingClose(tokens, start) {
            var depth = 0;
            for (var j = start; j < tokens.length; j++) {
                if (tokens[j].type === 'blockquote_open') depth++;
                else if (tokens[j].type === 'blockquote_close' && --depth === 0) return j;
            }
            throw new Error('unbalanced blockquote tokens');
        }

        // ProseMirror: a callout holds its title line (empty when it has
        // none) and then blocks, as a quotation does.
        var calloutNodeSpec = {
            attrs: {type: {default: 'note'}, fold: {default: ''}},
            content: 'callout_title block+',
            group: 'block',
            defining: true,
            parseDOM: [{tag: 'div.pv-callout', getAttrs: function(dom) {
                return {type: dom.getAttribute('data-callout-type') || 'note', fold: dom.getAttribute('data-callout-fold') || ''};
            }}],
            toDOM: function(node) {
                return ['div', {
                    'class': 'pv-callout',
                    'data-callout': String(node.attrs.type).toLowerCase(),
                    'data-callout-type': node.attrs.type,
                    'data-callout-fold': node.attrs.fold
                }, 0];
            }
        };

        var calloutTitleNodeSpec = {
            content: 'inline*',
            defining: true,
            parseDOM: [{tag: 'p.pv-callout-title', priority: 60}],
            toDOM: function() { return ['p', {'class': 'pv-callout-title'}, 0]; }
        };

        // MarkdownParser token handlers; a callout with no title gets an
        // empty title line from ProseMirror's createAndFill.
        var calloutParserTokens = {
            callout: {block: 'callout', getAttrs: function(tok) { return {type: tok.meta.raw, fold: tok.meta.fold}; }},
            callout_title: {block: 'callout_title'}
        };

        // MarkdownSerializer node writers: "> [!type]- Title" on the first
        // line, the body on the lines after it, every line behind "> ".
        var calloutSerializerNodes = {
            callout: function(state, node) {
                state.wrapBlock('> ', null, node, function() { state.renderContent(node); });
            },
            callout_title: function(state, node, parent) {
                state.write('[!' + parent.attrs.type + ']' + parent.attrs.fold);
                if (node.content.size) {
                    state.write(' ');
                    state.renderInline(node, false);
                }
                // No blank line before the body: GitHub's own layout.
                state.ensureNewLine();
            }
        };

        // A box for the callout's type, shown above the text while editing;
        // the text is ProseMirror's to edit as usual.
        function CalloutNodeView(node, view, getPos) {
            var self = this;
            this.node = node;
            this.dom = document.createElement('div');
            this.dom.className = 'pv-callout';
            var head = document.createElement('div');
            head.className = 'pv-callout-type';
            head.contentEditable = 'false';
            var label = document.createElement('label');
            label.textContent = 'Callout';
            var input = document.createElement('input');
            input.type = 'text';
            input.spellcheck = false;
            input.setAttribute('aria-label', 'Callout type');
            input.setAttribute('list', 'calloutTypeOptions');
            label.appendChild(input);
            head.appendChild(label);
            this.head = head;
            this.input = input;
            this.contentDOM = document.createElement('div');
            this.contentDOM.className = 'pv-callout-body';
            this.dom.appendChild(head);
            this.dom.appendChild(this.contentDOM);
            function commit() {
                var value = input.value.trim();
                var pos = getPos();
                input.placeholder = '';
                if (!CALLOUT_TYPE_RE.test(value) || typeof pos !== 'number') {
                    input.value = self.node.attrs.type;
                    input.setCustomValidity('');
                    return;
                }
                if (value === self.node.attrs.type) return;
                var attrs = Object.assign({}, self.node.attrs, {type: value});
                view.dispatch(view.state.tr.setNodeMarkup(pos, null, attrs));
            }
            input.addEventListener('input', function() {
                input.setCustomValidity(CALLOUT_TYPE_RE.test(input.value.trim()) ? '' : 'Letters, digits and -, starting with a letter');
            });
            // The browser lists only the types that match what the field
            // holds, so it is emptied on focus (the type shows as its
            // placeholder) and every type is offered; leaving it empty keeps
            // the type it had.
            input.addEventListener('focus', function() {
                input.placeholder = self.node.attrs.type;
                input.value = '';
            });
            input.addEventListener('change', commit);
            input.addEventListener('blur', commit);
            input.addEventListener('keydown', function(event) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    commit();
                    view.focus();
                } else if (event.key === 'Escape') {
                    input.value = '';
                    commit();
                    view.focus();
                }
            });
            this.render();
        }
        CalloutNodeView.prototype.render = function() {
            var type = String(this.node.attrs.type);
            this.dom.setAttribute('data-callout', type.toLowerCase());
            this.dom.setAttribute('data-callout-type', type);
            this.dom.setAttribute('data-callout-fold', this.node.attrs.fold);
            if (document.activeElement !== this.input) this.input.value = type;
        };
        CalloutNodeView.prototype.update = function(node) {
            if (node.type !== this.node.type) return false;
            this.node = node;
            this.render();
            return true;
        };
        CalloutNodeView.prototype.stopEvent = function(event) {
            return this.head.contains(event.target);
        };
        CalloutNodeView.prototype.ignoreMutation = function(mutation) {
            return this.head.contains(mutation.target);
        };

        function createCalloutNodeView(node, view, getPos) {
            return new CalloutNodeView(node, view, getPos);
        }

        // Marks a callout's empty title line so it can show a placeholder
        // while editing and take no room while reading.
        // Found once per change to the document, looking only through blocks
        // that hold blocks, so a long scene costs little per keystroke.
        function buildCalloutTitlePlugin(PM) {
            function find(doc) {
                var found = [];
                doc.descendants(function(node, pos) {
                    if (node.type.name === 'callout_title' && node.content.size === 0) {
                        found.push(PM.Decoration.node(pos, pos + node.nodeSize, {'class': 'is-empty'}));
                    }
                    return !node.isTextblock;
                });
                return found.length ? PM.DecorationSet.create(doc, found) : PM.DecorationSet.empty;
            }
            return new PM.Plugin({
                state: {
                    init: function(_config, state) { return find(state.doc); },
                    apply: function(tr, set) { return tr.docChanged ? find(tr.doc) : set; }
                },
                props: {
                    decorations: function(state) { return this.getState(state); }
                }
            });
        }

        // Wraps the selected blocks in a callout of *type*, or lifts the
        // blocks out of the callout the caret is in. The caret goes to the
        // title line, where a title can be typed.
        window.toggleCallout = function(type) {
            if (!_pmView || !window._PM) return;
            var PM = window._PM;
            var state = _pmView.state;
            var calloutType = state.schema.nodes.callout;
            if (!calloutType) return;
            var $from = state.selection.$from;
            for (var depth = $from.depth; depth > 0; depth--) {
                if ($from.node(depth).type === calloutType) {
                    unwrapCallout(PM, $from.before(depth));
                    _pmView.focus();
                    if (window.refreshSelectionPillAfterFormat) window.refreshSelectionPillAfterFormat();
                    return;
                }
            }
            var range = $from.blockRange(state.selection.$to);
            if (!range) return;
            var title = state.schema.nodes.callout_title.create();
            var content = state.doc.slice(range.start, range.end).content;
            var node = calloutType.createChecked({type: type || 'note', fold: ''}, PM.Fragment.from(title).append(content));
            var tr = state.tr.replaceWith(range.start, range.end, node);
            tr.setSelection(PM.TextSelection.create(tr.doc, range.start + 2));
            _pmView.dispatch(tr.scrollIntoView());
            _pmView.focus();
            if (window.refreshSelectionPillAfterFormat) window.refreshSelectionPillAfterFormat();
        };

        // Replaces the callout at *pos* with its blocks, its title (if any)
        // becoming the first paragraph.
        function unwrapCallout(PM, pos) {
            var state = _pmView.state;
            var node = state.doc.nodeAt(pos);
            var blocks = [];
            node.forEach(function(child) {
                if (child.type.name !== 'callout_title') blocks.push(child);
                else if (child.content.size) blocks.push(state.schema.nodes.paragraph.create(null, child.content));
            });
            var tr = state.tr.replaceWith(pos, pos + node.nodeSize, blocks);
            tr.setSelection(PM.TextSelection.near(tr.doc.resolve(Math.min(pos + 1, tr.doc.content.size))));
            _pmView.dispatch(tr.scrollIntoView());
        }
