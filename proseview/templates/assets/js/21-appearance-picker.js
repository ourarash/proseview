        // The reading font and theme pickers of the scene and file views:
        // menus that show each choice on the page while the pointer (or the
        // arrow keys) rests on it, and go back if nothing is chosen. A native
        // <select> cannot do that, so each one is replaced by a small listbox;
        // the select stays, out of sight, as what the rest of the page syncs.

        function enhanceAppearanceSelect(select, kind) {
            if (!select || select.dataset.enhanced) return;
            select.dataset.enhanced = 'true';
            var preview = kind === 'font' ? previewFont : previewTheme;
            var choose = kind === 'font' ? selectFont : selectTheme;
            var current = kind === 'font' ? currentFont : currentTheme;
            var title = select.getAttribute('title') || (kind === 'font' ? 'Reading font' : 'Color theme');

            var wrap = document.createElement('div');
            wrap.className = 'appearance-picker';
            wrap.dataset.kind = kind;
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'appearance-picker-btn';
            button.setAttribute('aria-haspopup', 'listbox');
            button.setAttribute('aria-expanded', 'false');
            button.title = title;
            var label = document.createElement('span');
            var caret = document.createElement('span');
            caret.className = 'appearance-picker-caret';
            caret.setAttribute('aria-hidden', 'true');
            caret.textContent = '▾';
            button.append(label, caret);
            var list = document.createElement('ul');
            list.className = 'appearance-picker-list';
            list.setAttribute('role', 'listbox');
            list.setAttribute('aria-label', title);
            list.hidden = true;
            Array.prototype.forEach.call(select.options, function(option) {
                var item = document.createElement('li');
                item.setAttribute('role', 'option');
                item.tabIndex = -1;
                item.dataset.value = option.value;
                item.textContent = option.textContent;
                list.appendChild(item);
            });
            wrap.append(button, list);
            select.classList.add('appearance-picker-native');
            select.tabIndex = -1;
            select.setAttribute('aria-hidden', 'true');
            select.after(wrap);

            var committed = null;
            var onDocument = null;
            var items = function() { return Array.prototype.slice.call(list.children); };
            var syncLabel = function() {
                var value = current();
                var match = items().filter(function(item) { return item.dataset.value === value; })[0];
                label.textContent = match ? match.textContent : value;
                items().forEach(function(item) { item.setAttribute('aria-selected', item.dataset.value === value ? 'true' : 'false'); });
            };
            var close = function(commit) {
                if (list.hidden) return;
                list.hidden = true;
                button.setAttribute('aria-expanded', 'false');
                if (onDocument) document.removeEventListener('mousedown', onDocument, true);
                onDocument = null;
                if (!commit && committed && current() !== committed) preview(committed);
                committed = null;
                syncLabel();
            };
            var open = function() {
                committed = current();
                list.hidden = false;
                button.setAttribute('aria-expanded', 'true');
                var selected = items().filter(function(item) { return item.dataset.value === committed; })[0] || items()[0];
                if (selected) selected.focus({preventScroll: true});
                // In a menu the list opens in place; keep all of it in view.
                if (wrap.closest('.scene-toolbar-popover')) list.scrollIntoView({block: 'nearest'});
                onDocument = function(event) { if (!wrap.contains(event.target)) close(false); };
                document.addEventListener('mousedown', onDocument, true);
            };
            button.addEventListener('click', function(event) {
                event.stopPropagation();
                if (list.hidden) open(); else close(false);
            });
            list.addEventListener('mouseover', function(event) {
                var item = event.target.closest('[role="option"]');
                if (item) { item.focus({preventScroll: true}); preview(item.dataset.value); }
            });
            // Off the list, the page shows what is chosen again.
            list.addEventListener('mouseleave', function() {
                if (committed) preview(committed);
            });
            list.addEventListener('click', function(event) {
                var item = event.target.closest('[role="option"]');
                if (!item) return;
                event.stopPropagation();
                choose(item.dataset.value);
                close(true);
                button.focus({preventScroll: true});
            });
            list.addEventListener('keydown', function(event) {
                var all = items();
                var index = Math.max(0, all.indexOf(document.activeElement));
                if (event.key === 'ArrowDown') index = (index + 1) % all.length;
                else if (event.key === 'ArrowUp') index = (index - 1 + all.length) % all.length;
                else if (event.key === 'Home') index = 0;
                else if (event.key === 'End') index = all.length - 1;
                else if (event.key === 'Enter' || event.key === ' ' || event.key === 'Tab') {
                    if (event.key !== 'Tab') event.preventDefault();
                    choose(all[index].dataset.value);
                    close(true);
                    if (event.key !== 'Tab') button.focus({preventScroll: true});
                    return;
                } else if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopPropagation();
                    close(false);
                    button.focus({preventScroll: true});
                    return;
                } else {
                    return;
                }
                event.preventDefault();
                all[index].focus({preventScroll: true});
                preview(all[index].dataset.value);
            });
            // Whatever else changes the font or theme, the label follows.
            select.addEventListener('proseview:appearance', syncLabel);
            syncLabel();
        }

        function syncAppearancePickers() {
            document.querySelectorAll('select.appearance-picker-native').forEach(function(select) {
                select.dispatchEvent(new Event('proseview:appearance'));
            });
        }

        (function initAppearancePickers() {
            enhanceAppearanceSelect(document.getElementById('filePreviewFontSelect'), 'font');
            enhanceAppearanceSelect(document.getElementById('filePreviewThemeSelect'), 'theme');
            enhanceAppearanceSelect(document.getElementById('modalFontSelect'), 'font');
            enhanceAppearanceSelect(document.getElementById('modalThemeSelect'), 'theme');
        })();
