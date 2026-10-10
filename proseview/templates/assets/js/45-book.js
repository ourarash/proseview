        // The whole book in one scroll: every scene in book order under its
        // chapter's heading, read-only. Edit (or E) opens the scene being read
        // in the scene view; leaving that comes back here, to the same scene.

        var _bookReturn = false;   // the scene view was opened from the book
        var _bookCurrent = null;   // path of the scene at the top of the view
        var _bookSections = [];
        var _bookScrollQueued = false;

        function bookCurrentScene() {
            return _bookCurrent || paths[0] || null;
        }

        function _bookCanEdit() {
            return !(window.PROSEVIEW_STATIC && !window.PROSEVIEW_STATIC_EDITS);
        }

        // A chapter is headed by the name its scenes give it in frontmatter;
        // a chapter that is only a folder is numbered. A book of one unnamed
        // chapter has no heading at all.
        function _bookChapters() {
            var out = [];
            var last = null;
            paths.forEach(function(p) {
                var m = meta[p] || {};
                var key = String(m.chapter || '');
                if (!out.length || key !== last) {
                    var named = m.fm && m.fm.chapter !== undefined && m.fm.chapter !== null ? String(m.fm.chapter).trim() : '';
                    // `chapter: 3` names the chapter by its number.
                    if (/^\d+$/.test(named)) named = 'Chapter ' + named;
                    out.push({key: key, named: named, scenes: []});
                    last = key;
                }
                out[out.length - 1].scenes.push(p);
            });
            out.forEach(function(chapter, index) {
                chapter.heading = chapter.named || (out.length > 1 ? 'Chapter ' + (index + 1) : '');
            });
            return out;
        }

        function _bookBasePath(p) {
            var abs = (meta[p] && meta[p].abs_path) || '';
            var root = typeof repoRoot !== 'undefined' ? String(repoRoot).replace(/\/+$/, '') + '/' : '';
            return root && abs.indexOf(root) === 0 ? abs.slice(root.length) : '';
        }

        function _bookSceneTitle(p) {
            var m = meta[p] || {};
            return m.title || p.split('/').pop().replace(/\.md$/i, '').replace(/[-_]+/g, ' ');
        }

        function renderBook() {
            var body = document.getElementById('bookBody');
            if (!body) return;
            var canEdit = _bookCanEdit();
            var total = 0;
            paths.forEach(function(p) { total += (meta[p] && meta[p].words) || 0; });
            var before = 0;
            var frag = document.createDocumentFragment();
            _bookSections = [];
            _bookChapters().forEach(function(chapter) {
                var wrap = document.createElement('div');
                wrap.className = 'book-chapter';
                if (chapter.heading) {
                    var h = document.createElement('h2');
                    h.className = 'book-chapter-title';
                    h.textContent = chapter.heading;
                    wrap.appendChild(h);
                }
                chapter.scenes.forEach(function(p, index) {
                    if (index > 0) {
                        var gap = document.createElement('div');
                        gap.className = 'book-break';
                        gap.setAttribute('role', 'separator');
                        gap.textContent = '* * *';
                        wrap.appendChild(gap);
                    }
                    var section = document.createElement('section');
                    section.className = 'book-scene';
                    section.dataset.path = p;
                    section.dataset.chapter = chapter.heading;
                    section.dataset.at = total ? String(before / total) : '0';
                    section.setAttribute('aria-label', _bookSceneTitle(p));
                    before += (meta[p] && meta[p].words) || 0;
                    var open = document.createElement('button');
                    open.type = 'button';
                    open.className = 'book-scene-open';
                    open.dataset.path = p;
                    open.textContent = canEdit ? 'Edit' : 'Open';
                    open.title = (canEdit ? 'Edit ' : 'Open ') + '“' + _bookSceneTitle(p) + '”';
                    var prose = document.createElement('div');
                    prose.className = 'book-prose';
                    renderSafeMarkdown(prose, contents[p] || '', {basePath: _bookBasePath(p)});
                    section.append(open, prose);
                    wrap.appendChild(section);
                    _bookSections.push(section);
                });
                frag.appendChild(wrap);
            });
            body.replaceChildren(frag);
            var size = null;
            try { size = parseInt(localStorage.getItem(MODAL_FONT_SIZE_STORAGE_KEY), 10); } catch (e) {}
            body.style.fontSize = size ? normalizeModalFontSize(size) + 'px' : '';
            var editBtn = document.getElementById('bookEditBtn');
            if (editBtn) editBtn.hidden = !canEdit;
        }

        function _bookHeaderBottom() {
            var header = document.querySelector('#book-panel .book-header');
            return header ? header.getBoundingClientRect().bottom : 0;
        }

        // Where a scene starts: at its chapter's heading, when it opens one.
        function _bookAnchor(section) {
            var before = section.previousElementSibling;
            return before && before.classList.contains('book-chapter-title') ? before : section;
        }

        function _bookScrollTo(p) {
            var section = _bookSections.filter(function(s) { return s.dataset.path === p; })[0];
            if (!section) { window.scrollTo(0, 0); return; }
            var top = _bookAnchor(section).getBoundingClientRect().top + window.scrollY - _bookHeaderBottom() - 8;
            window.scrollTo({top: Math.max(0, top), left: 0, behavior: 'instant'});
        }

        function _bookTrack() {
            _bookScrollQueued = false;
            if (document.documentElement.dataset.view !== 'book' || !_bookSections.length) return;
            var line = _bookHeaderBottom() + 24;
            var current = _bookSections[0];
            for (var i = 0; i < _bookSections.length; i++) {
                if (_bookAnchor(_bookSections[i]).getBoundingClientRect().top > line) break;
                current = _bookSections[i];
            }
            var p = current.dataset.path;
            if (p === _bookCurrent) return;
            _bookCurrent = p;
            var where = document.getElementById('bookWhere');
            if (where) {
                var parts = [];
                if (current.dataset.chapter) parts.push(current.dataset.chapter);
                parts.push(_bookSceneTitle(p));
                where.textContent = parts.join(' · ') + ' · ' + Math.round(parseFloat(current.dataset.at) * 100) + '%';
            }
            routeToHash('/book/' + encodeURIComponent(p), false);
        }

        window.addEventListener('scroll', function() {
            if (_bookScrollQueued || document.documentElement.dataset.view !== 'book') return;
            _bookScrollQueued = true;
            requestAnimationFrame(_bookTrack);
        }, {passive: true});

        // Open the book at scene *p* (the start when none is given).
        function openBookView(p, options) {
            options = options || {};
            if (typeof guardDirtySceneNavigation === 'function' && guardDirtySceneNavigation()) {
                showUnsavedDialog({onContinue: function() { openBookView(p, options); }});
                return false;
            }
            if (paths.indexOf(p) < 0) p = null;
            var hash = '/book' + (p ? '/' + encodeURIComponent(p) : '');
            var view = document.documentElement.dataset.view;
            if (view === 'scene' && typeof closeSceneModal === 'function') {
                // Routed first, so a reload on the way out lands in the book.
                _bookReturn = false;
                if (options.route !== false) routeToHash(hash, true);
                options.route = false;
                if (!closeSceneModal({route: false})) return false;
            } else if (view !== 'book') {
                saveActiveScrollPosition();
            }
            _bookReturn = false;
            renderBook();
            document.documentElement.dataset.view = 'book';
            _bookCurrent = null;
            if (options.route !== false) routeToHash(hash, true);
            var land = function() {
                if (p) _bookScrollTo(p);
                else window.scrollTo({top: 0, left: 0, behavior: 'instant'});
                _bookTrack();
            };
            land();
            // Web fonts and images can move the text after the first layout.
            requestAnimationFrame(land);
            setTimeout(land, 150);
            if (p && typeof revealSidebarItem === 'function') revealSidebarItem({scenePath: p});
            var title = document.getElementById('bookTitle');
            if (title && options.focus !== false) title.focus({preventScroll: true});
            return true;
        }

        function closeBookView() {
            delete document.documentElement.dataset.view;
            _bookCurrent = null;
            routeToHash('/tab/' + currentTab, true);
            restoreActiveScrollPosition();
        }

        // Open scene *p* from the book, in the editor when *edit*.
        function openBookScene(p, edit) {
            if (!p) return;
            if (!openSceneModal(p)) return;
            _bookReturn = true;
            if (edit && _bookCanEdit() && typeof toggleSceneEdit === 'function' && !_pmEditMode) toggleSceneEdit();
        }

        // Called as the scene view closes: back to the book, at the scene the
        // writer ended on, when that is where they came from.
        function bookTakeReturn() {
            if (!_bookReturn) return null;
            _bookReturn = false;
            return paths[curIdx] || null;
        }

        (function initBookView() {
            var body = document.getElementById('bookBody');
            if (body) body.addEventListener('click', function(event) {
                var button = event.target.closest('.book-scene-open');
                if (button) openBookScene(button.dataset.path, _bookCanEdit());
            });
            var font = document.getElementById('bookFontSelect');
            var theme = document.getElementById('bookThemeSelect');
            if (typeof enhanceAppearanceSelect === 'function') {
                enhanceAppearanceSelect(font, 'font');
                enhanceAppearanceSelect(theme, 'theme');
            }
            document.addEventListener('keydown', function(event) {
                if (event.key !== 'e' && event.key !== 'E') return;
                if (event.ctrlKey || event.altKey || event.metaKey || event.defaultPrevented) return;
                if (document.documentElement.dataset.view !== 'book' || !_bookCanEdit()) return;
                var tag = (event.target && event.target.tagName || '').toUpperCase();
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (event.target && event.target.isContentEditable)) return;
                if (document.querySelector('dialog[open]')) return;
                event.preventDefault();
                openBookScene(bookCurrentScene(), true);
            });
        })();
