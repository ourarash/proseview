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

        // Fill *pre* with *text* (the lines between the --- fences), coloured.
        function fillFrontmatterHighlight(pre, text) {
            pre.replaceChildren();
            String(text || '').split('\n').forEach(function(line, index) {
                if (index) pre.appendChild(document.createTextNode('\n'));
                var comment = /^(\s*)(#.*)$/.exec(line);
                if (comment) {
                    pre.appendChild(document.createTextNode(comment[1]));
                    pre.appendChild(_fmSpan('fm-comment', comment[2]));
                    return;
                }
                var field = /^(\s*)(-\s+)?([^\s:#][^:]*?)(:)(\s+(.*))?$/.exec(line);
                if (field && !/^\s*-\s+["']/.test(line)) {
                    pre.appendChild(document.createTextNode(field[1] + (field[2] || '')));
                    pre.appendChild(_fmSpan('fm-key', field[3]));
                    pre.appendChild(_fmSpan('fm-colon', field[4]));
                    if (field[5] !== undefined) {
                        pre.appendChild(document.createTextNode(field[5].slice(0, field[5].length - field[6].length)));
                        pre.appendChild(_fmValue(field[6]));
                    }
                    return;
                }
                var item = /^(\s*)(-\s+)(.*)$/.exec(line);
                if (item) {
                    pre.appendChild(document.createTextNode(item[1]));
                    pre.appendChild(_fmSpan('fm-dash', item[2]));
                    pre.appendChild(_fmValue(item[3]));
                    return;
                }
                // A folded continuation line, or anything else, as written.
                pre.appendChild(_fmValue(line));
            });
        }

        var FRONTMATTER_COLLAPSED_KEY = 'proseview-frontmatter-collapsed';

        function _fmCollapsed() {
            try { return localStorage.getItem(FRONTMATTER_COLLAPSED_KEY) === 'true'; } catch (e) { return false; }
        }

        function _fmFieldCount(text) {
            return String(text || '').split('\n').filter(function(line) { return /^[^\s#-][^:]*:/.test(line); }).length;
        }

        // A quiet line above the frontmatter that folds it away and back.
        // One choice for every file, remembered in this browser.
        function _fmFrame(text, content) {
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
            frame.append(toggle, content);
            return frame;
        }

        // The highlighted, foldable block for *text*.
        function renderFrontmatterBlock(text) {
            var pre = document.createElement('pre');
            pre.className = 'fm-block';
            pre.setAttribute('aria-label', 'Frontmatter');
            fillFrontmatterHighlight(pre, text);
            return _fmFrame(text, pre);
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
