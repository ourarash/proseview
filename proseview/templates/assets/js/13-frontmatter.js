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
            var trimmed = text.trim();
            if (/^(-?\d+(\.\d+)?|true|false|null|yes|no)$/i.test(trimmed)) return _fmSpan('fm-number', text);
            return _fmSpan('fm-string', text);
        }

        // The highlighted block for *text* (the lines between the --- fences).
        function renderFrontmatterBlock(text) {
            var pre = document.createElement('pre');
            pre.className = 'fm-block';
            pre.setAttribute('aria-label', 'Frontmatter');
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
            return pre;
        }

        // The edit box for *text*; *onInput* runs on every change.
        function frontmatterEditor(text, onInput) {
            var wrap = document.createElement('div');
            wrap.className = 'fm-edit';
            var area = document.createElement('textarea');
            area.className = 'fm-editor';
            area.value = String(text || '');
            area.spellcheck = false;
            area.setAttribute('aria-label', 'Frontmatter (YAML)');
            var size = function() {
                area.style.height = 'auto';
                area.style.height = (area.scrollHeight + 4) + 'px';
            };
            area.addEventListener('input', function() { size(); if (onInput) onInput(area.value); });
            var error = document.createElement('p');
            error.className = 'fm-error';
            error.setAttribute('role', 'alert');
            error.hidden = true;
            wrap.append(area, error);
            requestAnimationFrame(size);
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
