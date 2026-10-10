        // The whole book in one scroll: every scene in book order under its
        // chapter's heading, read-only. Edit (or E) opens the scene being read
        // in the scene view; leaving that comes back here, to the same scene.

        var _bookReturn = false;   // the scene view was opened from the book
        var _bookCurrent = null;   // path of the scene at the top of the view
        var _bookSections = [];
        var _bookScrollQueued = false;
        var _bookChapterStarts = [];   // index into _bookSections of each chapter's first scene
        var _bookSidebarBefore = null; // the file browser's state before the book closed it
        var BOOK_INTRO_KEY = 'proseview-book-intro-seen';
        var BOOK_INTRO_TIMES = 3;

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
            _bookChapterStarts = [];
            var chapters = _bookChapters();
            chapters.forEach(function(chapter, chapterIndex) {
                _bookChapterStarts.push(_bookSections.length);
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
                    section.dataset.chapterIndex = String(chapterIndex);
                    section.dataset.scene = String(index + 1);
                    section.dataset.scenes = String(chapter.scenes.length);
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
            _bookRenderToc(chapters);
        }

        // The chapter list behind the middle of the navigator.
        function _bookRenderToc(chapters) {
            var toc = document.getElementById('bookToc');
            if (!toc) return;
            toc.replaceChildren();
            chapters.forEach(function(chapter, index) {
                var item = document.createElement('button');
                item.type = 'button';
                item.className = 'book-toc-item';
                item.dataset.chapterIndex = String(index);
                item.textContent = chapter.heading || 'The book';
                toc.appendChild(item);
            });
        }

        function toggleBookToc(open) {
            var toc = document.getElementById('bookToc');
            var button = document.getElementById('bookNavWhere');
            if (!toc || !button) return;
            if (open === undefined) open = toc.hidden;
            toc.hidden = !open;
            button.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (!open) return;
            var current = _bookCurrentSection();
            var at = current ? current.dataset.chapterIndex : '0';
            Array.prototype.forEach.call(toc.children, function(item) {
                item.setAttribute('aria-current', item.dataset.chapterIndex === at ? 'true' : 'false');
            });
            var mine = toc.querySelector('[aria-current="true"]') || toc.firstElementChild;
            if (mine) { mine.scrollIntoView({block: 'nearest'}); mine.focus({preventScroll: true}); }
        }

        function _bookCurrentSection() {
            var p = bookCurrentScene();
            for (var i = 0; i < _bookSections.length; i++) {
                if (_bookSections[i].dataset.path === p) return _bookSections[i];
            }
            return _bookSections[0] || null;
        }

        // Next or previous scene.
        function bookGoScene(delta) {
            var index = _bookSections.indexOf(_bookCurrentSection());
            var next = _bookSections[Math.max(0, Math.min(_bookSections.length - 1, index + delta))];
            if (next) { _bookScrollTo(next.dataset.path); _bookTrack(); }
        }

        // Next chapter, or back to the start of this one and then the one
        // before, as an e-reader does.
        function bookGoChapter(delta) {
            var section = _bookCurrentSection();
            if (!section) return;
            var chapter = parseInt(section.dataset.chapterIndex, 10) || 0;
            var target = chapter + delta;
            if (delta < 0 && _bookSections.indexOf(section) !== _bookChapterStarts[chapter]) target = chapter;
            target = Math.max(0, Math.min(_bookChapterStarts.length - 1, target));
            bookGoToChapter(target);
        }

        function bookGoToChapter(index) {
            var first = _bookSections[_bookChapterStarts[index]];
            if (first) { _bookScrollTo(first.dataset.path); _bookTrack(); }
        }

        // How far through the book the reader is, as the bottom bar shows it.
        function _bookShowProgress() {
            var max = document.documentElement.scrollHeight - window.innerHeight;
            var done = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 1;
            var bar = document.getElementById('bookNavBar');
            if (bar) bar.style.width = (done * 100).toFixed(2) + '%';
            var pct = document.getElementById('bookNavPct');
            if (pct) pct.textContent = Math.round(done * 100) + '%';
        }

        // What reading mode is, the first few times the book opens.
        function _bookShowIntro() {
            var intro = document.getElementById('bookIntro');
            if (!intro) return;
            var seen = 0;
            try { seen = parseInt(localStorage.getItem(BOOK_INTRO_KEY), 10) || 0; } catch (e) {}
            if (seen >= BOOK_INTRO_TIMES) return;
            try { localStorage.setItem(BOOK_INTRO_KEY, String(seen + 1)); } catch (e) {}
            intro.hidden = false;
            clearTimeout(_bookShowIntro.timer);
            _bookShowIntro.timer = setTimeout(function() { intro.hidden = true; }, 12000);
        }

        function dismissBookIntro() {
            var intro = document.getElementById('bookIntro');
            if (intro) intro.hidden = true;
            try { localStorage.setItem(BOOK_INTRO_KEY, String(BOOK_INTRO_TIMES)); } catch (e) {}
        }

        // The file browser steps aside for the book, and comes back after,
        // unless the reader opened it while reading.
        function _bookHideSidebar() {
            var html = document.documentElement;
            if (_bookSidebarBefore !== null || html.dataset.sidebar === 'closed') return;
            _bookSidebarBefore = html.dataset.sidebar || 'open';
            html.dataset.sidebar = 'closed';
            if (typeof syncSidebarInteractiveState === 'function') syncSidebarInteractiveState();
        }

        function _bookRestoreSidebar() {
            if (_bookSidebarBefore === null) return;
            var html = document.documentElement;
            if (html.dataset.sidebar === 'closed') html.dataset.sidebar = _bookSidebarBefore;
            _bookSidebarBefore = null;
            if (typeof syncSidebarInteractiveState === 'function') syncSidebarInteractiveState();
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
            _bookShowProgress();
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
                where.textContent = parts.join(' · ');
            }
            var nav = document.getElementById('bookNavWhere');
            if (nav) {
                // On a phone the header names the chapter; the bar has room
                // for the scene only.
                var narrow = window.innerWidth < 640;
                var scene = parseInt(current.dataset.scenes, 10) > 1
                    ? current.dataset.scene + ' of ' + current.dataset.scenes : '';
                var chapter = current.dataset.chapter || 'The book';
                nav.textContent = narrow
                    ? (scene ? 'Scene ' + scene : chapter) + ' \u25b4'
                    : chapter + (scene ? ' \u00b7 scene ' + scene : '');
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
            toggleBookToc(false);
            _bookHideSidebar();
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
            if (!options.returning) _bookShowIntro();
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
            var toc = document.getElementById('bookToc');
            if (toc) toc.addEventListener('click', function(event) {
                var item = event.target.closest('.book-toc-item');
                if (!item) return;
                toggleBookToc(false);
                bookGoToChapter(parseInt(item.dataset.chapterIndex, 10));
            });
            document.addEventListener('mousedown', function(event) {
                var toc = document.getElementById('bookToc');
                if (toc && !toc.hidden && !event.target.closest('.book-nav-where-wrap')) toggleBookToc(false);
            });
            document.addEventListener('keydown', function(event) {
                if (document.documentElement.dataset.view !== 'book') return;
                if (event.ctrlKey || event.altKey || event.metaKey || event.defaultPrevented) return;
                var tag = (event.target && event.target.tagName || '').toUpperCase();
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (event.target && event.target.isContentEditable)) return;
                if (document.querySelector('dialog[open]')) return;
                var tocOpen = toc && !toc.hidden;
                if (event.key === 'Escape' && tocOpen) {
                    event.preventDefault();
                    toggleBookToc(false);
                    document.getElementById('bookNavWhere').focus();
                } else if (tocOpen && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
                    event.preventDefault();
                    var items = Array.prototype.slice.call(toc.children);
                    var at = items.indexOf(document.activeElement);
                    var next = items[Math.max(0, Math.min(items.length - 1, at + (event.key === 'ArrowDown' ? 1 : -1)))];
                    if (next) next.focus();
                } else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                    event.preventDefault();
                    var delta = event.key === 'ArrowRight' ? 1 : -1;
                    if (event.shiftKey) bookGoChapter(delta); else bookGoScene(delta);
                } else if ((event.key === 'e' || event.key === 'E') && _bookCanEdit()) {
                    event.preventDefault();
                    openBookScene(bookCurrentScene(), true);
                }
            });
            // Leaving the book, however it happens, gives the file browser back.
            new MutationObserver(function() {
                if (document.documentElement.dataset.view !== 'book') {
                    _bookRestoreSidebar();
                    var intro = document.getElementById('bookIntro');
                    if (intro) intro.hidden = true;
                    toggleBookToc(false);
                }
            }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-view']});
        })();
