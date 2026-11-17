        // A file's frontmatter, shown above its prose as the YAML it is: keys
        // in one colour, values in another. In edit mode it is a text box,
        // saved exactly as typed once the server has checked it is YAML.

        function _fmSpan(className, text) {
            var span = document.createElement('span');
            span.className = className;
            span.textContent = text;
            return span;
        }

        function _fmValue(text) {
            // A trailing "# comment" after the value is a comment.
            var comment = /^([^"'#]*?)(\s+#.*)$/.exec(text);
            if (comment) {
                var both = document.createDocumentFragment();
                if (comment[1]) both.appendChild(_fmValue(comment[1]));
                both.appendChild(_fmSpan('fm-comment', comment[2]));
                return both;
            }
            var trimmed = text.trim();
            if (/^(-?\d+(\.\d+)?|true|false|null|yes|no)$/i.test(trimmed)) return _fmSpan('fm-number', text);
            return _fmSpan('fm-string', text);
        }

        function _fmUnquote(raw) {
            var m = /^(\s*)(["'])(.*)\2(\s*)$/.exec(raw);
            if (m) return { before: m[1] + m[2], name: m[3].trim(), after: m[2] + m[4] };
            var trimmed = raw.trim();
            var idx = raw.indexOf(trimmed);
            return {
                before: idx > 0 ? raw.slice(0, idx) : '',
                name: trimmed,
                after: idx >= 0 ? raw.slice(idx + trimmed.length) : ''
            };
        }

        function _fmCharButton(name, options) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'fm-char-link';
            btn.dataset.charName = name;
            btn.textContent = name;
            var metrics = options.charMentions && options.charMentions[name];
            btn.title = metrics
                ? 'Mentions: ' + metrics.dialogue + ' dialogue, ' + metrics.prose + ' prose \u00b7 Click to read bio'
                : 'Read bio';
            btn.addEventListener('click', function() { options.onCharacter(name); });
            return btn;
        }

        function _fmAppendCharToken(target, raw, options) {
            var parts = _fmUnquote(raw);
            if (!parts.name) {
                if (raw) target.appendChild(_fmSpan('fm-string', raw));
                return;
            }
            if (parts.before) target.appendChild(_fmSpan('fm-string', parts.before));
            target.appendChild(_fmCharButton(parts.name, options));
            if (parts.after) target.appendChild(_fmSpan('fm-string', parts.after));
        }

        function _fmAppendCharValue(target, text, options) {
            var comment = /^([^"'#]*?)(\s+#.*)$/.exec(text);
            if (comment) {
                if (comment[1]) _fmAppendCharValue(target, comment[1], options);
                target.appendChild(_fmSpan('fm-comment', comment[2]));
                return;
            }
            var bracketed = /^(\s*\[)([\s\S]*?)(\]\s*)$/.exec(text);
            if (bracketed) {
                target.appendChild(_fmSpan('fm-colon', bracketed[1]));
                bracketed[2].split(',').forEach(function(part, idx) {
                    if (idx) target.appendChild(_fmSpan('fm-colon', ','));
                    _fmAppendCharToken(target, part, options);
                });
                target.appendChild(_fmSpan('fm-colon', bracketed[3]));
                return;
            }
            if (text.indexOf(',') >= 0 && !/^\s*["']/.test(text)) {
                text.split(',').forEach(function(part, idx) {
                    if (idx) target.appendChild(_fmSpan('fm-colon', ','));
                    _fmAppendCharToken(target, part, options);
                });
                return;
            }
            _fmAppendCharToken(target, text, options);
        }

        function _fmAppendPovValue(target, text, options) {
            var comment = /^([^"'#]*?)(\s+#.*)$/.exec(text);
            var body = comment ? comment[1] : text;
            var parts = _fmUnquote(body);
            if (parts.name && (!options.canLinkCharacter || options.canLinkCharacter(parts.name))) {
                if (parts.before) target.appendChild(_fmSpan('fm-string', parts.before));
                target.appendChild(_fmCharButton(parts.name, options));
                if (parts.after) target.appendChild(_fmSpan('fm-string', parts.after));
                if (comment) target.appendChild(_fmSpan('fm-comment', comment[2]));
                return;
            }
            target.appendChild(_fmValue(text));
        }

        // Fill *pre* with *text* (the lines between the --- fences), coloured.
        // When *options* is given (scene reading mode), character names become
        // clickable bio links and frontmatter TODO list items get checkboxes.
        function fillFrontmatterHighlight(pre, text, options) {
            pre.replaceChildren();
            var activeKey = '';
            var activeIndent = -1;
            String(text || '').split('\n').forEach(function(line, index) {
                if (index) pre.appendChild(document.createTextNode('\n'));
                var comment = /^(\s*)(#.*)$/.exec(line);
                if (comment) {
                    pre.appendChild(document.createTextNode(comment[1]));
                    pre.appendChild(_fmSpan('fm-comment', comment[2]));
                    return;
                }
                if (!line.trim()) return;
                var field = /^(\s*)(-\s+)?([^\s:#][^:]*?)(:)(\s+(.*))?$/.exec(line);
                if (field && !/^\s*-\s+["']/.test(line)) {
                    if (!field[2]) {
                        activeKey = field[3].trim().toLowerCase();
                        activeIndent = field[1].length;
                    }
                    pre.appendChild(document.createTextNode(field[1] + (field[2] || '')));
                    pre.appendChild(_fmSpan('fm-key', field[3]));
                    pre.appendChild(_fmSpan('fm-colon', field[4]));
                    if (field[5] !== undefined) {
                        pre.appendChild(document.createTextNode(field[5].slice(0, field[5].length - field[6].length)));
                        if (!field[2] && options && options.onCharacter && activeKey === 'characters') {
                            _fmAppendCharValue(pre, field[6], options);
                        } else if (!field[2] && options && options.onCharacter && activeKey === 'pov') {
                            _fmAppendPovValue(pre, field[6], options);
                        } else {
                            pre.appendChild(_fmValue(field[6]));
                        }
                    }
                    return;
                }
                var item = /^(\s*)(-\s+)(.*)$/.exec(line);
                if (item) {
                    if (item[1].length < activeIndent) {
                        activeKey = '';
                        activeIndent = -1;
                    }
                    if (options && options.onTodoComplete && activeKey === 'todos') {
                        var todoParts = _fmUnquote(item[3]);
                        if (todoParts.name) {
                            var itemWrap = document.createElement('span');
                            itemWrap.className = 'fm-todo-item';
                            itemWrap.appendChild(document.createTextNode(item[1]));
                            var cb = document.createElement('input');
                            cb.type = 'checkbox';
                            cb.className = 'fm-todo-cb';
                            cb.setAttribute('aria-label', 'Complete TODO: ' + todoParts.name);
                            cb.title = 'Mark TODO complete and remove from frontmatter';
                            var textSpan = document.createElement('span');
                            textSpan.appendChild(_fmSpan('fm-dash', item[2]));
                            textSpan.appendChild(_fmValue(item[3]));
                            cb.addEventListener('change', function() {
                                options.onTodoComplete(cb, todoParts.name, itemWrap);
                            });
                            itemWrap.append(cb, textSpan);
                            pre.appendChild(itemWrap);
                            return;
                        }
                    }
                    pre.appendChild(document.createTextNode(item[1]));
                    pre.appendChild(_fmSpan('fm-dash', item[2]));
                    if (options && options.onCharacter && activeKey === 'characters') {
                        _fmAppendCharValue(pre, item[3], options);
                    } else {
                        pre.appendChild(_fmValue(item[3]));
                    }
                    return;
                }
                var indentMatch = /^(\s*)/.exec(line);
                if (indentMatch && indentMatch[1].length <= activeIndent) {
                    activeKey = '';
                    activeIndent = -1;
                }
                // A folded continuation line, or anything else, as written.
                pre.appendChild(_fmValue(line));
            });
        }

        var FRONTMATTER_COLLAPSED_KEY = 'proseview-frontmatter-collapsed';

        function _fmCollapsed() {
            // Until a choice is made, folded on a phone, where it would fill the screen.
            var stored = null;
            try { stored = localStorage.getItem(FRONTMATTER_COLLAPSED_KEY); } catch (e) {}
            if (stored === null) return window.innerWidth < 640;
            return stored === 'true';
        }

        function _fmFieldCount(text) {
            return String(text || '').split('\n').filter(function(line) { return /^[^\s#-][^:]*:/.test(line); }).length;
        }

        // A quiet line above the frontmatter that folds it away and back.
        // One choice for every file, remembered in this browser.
        function _fmFrame(text, content, actions, footer) {
            var frame = document.createElement('div');
            frame.className = 'fm';
            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'fm-toggle';
            var label = function() {
                var collapsed = frame.classList.contains('is-collapsed');
                var count = _fmFieldCount(typeof text === 'function' ? text() : text);
                toggle.textContent = (collapsed ? '▸ ' : '▾ ') + 'Frontmatter'
                    + (collapsed && count ? ' · ' + count + (count === 1 ? ' field' : ' fields') : '');
                toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            };
            frame.classList.toggle('is-collapsed', _fmCollapsed());
            toggle.addEventListener('click', function() {
                var collapsed = !frame.classList.contains('is-collapsed');
                frame.classList.toggle('is-collapsed', collapsed);
                try { localStorage.setItem(FRONTMATTER_COLLAPSED_KEY, collapsed ? 'true' : 'false'); } catch (e) {}
                label();
            });
            label();
            if (actions) {
                var head = document.createElement('div');
                head.className = 'fm-head';
                head.append(toggle, actions);
                frame.append(head, content);
            } else {
                frame.append(toggle, content);
            }
            if (footer) frame.appendChild(footer);
            return frame;
        }

        // The highlighted, foldable block for *text*.
        function renderFrontmatterBlock(text, actions, options) {
            var pre = document.createElement('pre');
            pre.className = 'fm-block';
            pre.setAttribute('aria-label', 'Frontmatter');
            fillFrontmatterHighlight(pre, text, options);
            return _fmFrame(text, pre, actions, options && options.footer);
        }

        // The edit box for *text*; *onInput* runs on every change. A text box
        // with clear text over the highlighted copy of what it holds, so the
        // colours stay while typing.
        function frontmatterEditor(text, onInput) {
            var wrap = document.createElement('div');
            wrap.className = 'fm-edit';
            var area = document.createElement('div');
            area.className = 'fm-edit-area';
            var under = document.createElement('pre');
            under.className = 'fm-block fm-under';
            under.setAttribute('aria-hidden', 'true');
            var box = document.createElement('textarea');
            box.className = 'fm-editor';
            box.value = String(text || '');
            box.spellcheck = false;
            box.setAttribute('aria-label', 'Frontmatter (YAML)');
            var paint = function() {
                // The trailing space keeps a last empty line its height.
                fillFrontmatterHighlight(under, box.value + ' ');
            };
            box.addEventListener('input', function() { paint(); if (onInput) onInput(box.value); });
            box.addEventListener('scroll', function() { under.scrollTop = box.scrollTop; });
            paint();
            area.append(under, box);
            var error = document.createElement('p');
            error.className = 'fm-error';
            error.setAttribute('role', 'alert');
            error.hidden = true;
            wrap.append(_fmFrame(function() { return box.value; }, area), error);
            return wrap;
        }

        // For a file with no frontmatter: a button that asks for the box.
        function addFrontmatterButton(onClick) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'fm-add';
            button.textContent = '+ Add frontmatter';
            button.addEventListener('click', onClick);
            return button;
        }

        function showFrontmatterError(container, message) {
            var error = container && container.querySelector('.fm-error');
            if (!error) return false;
            error.textContent = message;
            error.hidden = !message;
            return true;
        }
