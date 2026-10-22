        // The whole book in one scroll: every scene in book order under its
        // chapter's heading, read-only. Edit (or E) opens the scene being read
        // in the scene view; leaving that comes back here, to the same scene.

        var _bookReturn = false;   // the scene view was opened from the book
        var _bookCurrent = null;   // path of the scene at the top of the view
        var _bookSections = [];
        var _bookScrollQueued = false;
        var _bookChapterStarts = [];   // index into _bookSections of each chapter's first scene
        var _bookSidebarBefore = null; // the file browser's state before the book closed it
        var _bookPages = null;         // the print layout viewer, once made
        var _bookPagesScroll = null;   // where the text was when print layout opened
        var _bookOrigin = null;        // {scene, top}: the scene the book was opened from
        var BOOK_LAYOUT_KEY = 'proseview-book-layout';
        var BOOK_PRINT_ANCHOR_KEY = 'proseview-book-print-anchor';
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
            var sizeSlider = document.getElementById('bookFontSize');
            if (sizeSlider && size) sizeSlider.value = String(normalizeModalFontSize(size));
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
        // In the print layout the same moves jump to where the scene or
        // chapter starts on its page.
        function bookGoScene(delta) {
            var index = _bookSections.indexOf(_bookCurrentSection());
            var next = _bookSections[Math.max(0, Math.min(_bookSections.length - 1, index + delta))];
            if (!next) return;
            if (_bookPagesScroll !== null) { if (_bookPages) _bookPages.goTo(_bookSceneMark(next.dataset.path)); return; }
            _bookScrollTo(next.dataset.path);
            _bookTrack();
        }

        function _bookSceneMark(p) {
            return 'scene-' + p.replace(/\.md$/i, '');
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
            if (!first) return;
            if (_bookPagesScroll !== null) {
                if (_bookPages && !_bookPages.goTo('chapter-' + (index + 1))) _bookPages.goTo(_bookSceneMark(first.dataset.path));
                return;
            }
            _bookScrollTo(first.dataset.path);
            _bookTrack();
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
            if (document.documentElement.dataset.view !== 'book' || !_bookSections.length || _bookPagesScroll !== null) return;
            _bookShowProgress();
            var line = _bookHeaderBottom() + 24;
            var current = _bookSections[0];
            for (var i = 0; i < _bookSections.length; i++) {
                if (_bookAnchor(_bookSections[i]).getBoundingClientRect().top > line) break;
                current = _bookSections[i];
            }
            _bookShowWhere(current);
        }

        // Name the scene being read in the header and the bar.
        function _bookShowWhere(current) {
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

        // The header steps aside while reading on and comes back on the way
        // up, as the scene view's toolbar does (and follows its setting:
        // Pinned keeps it). It keeps its space, so the text never moves.
        var _bookLastScroll = 0;
        function _bookSetHeaderHidden(hidden) {
            var panel = document.getElementById('book-panel');
            if (panel) panel.classList.toggle('is-header-hidden', hidden);
        }

        window.addEventListener('scroll', function() {
            if (document.documentElement.dataset.view !== 'book') return;
            var current = window.scrollY;
            var delta = current - _bookLastScroll;
            _bookLastScroll = current;
            var panel = document.getElementById('book-panel');
            if (!panel || panel.classList.contains('is-focus')) return;
            var mode = typeof _sceneToolbarMode === 'string' ? _sceneToolbarMode : 'auto';
            if (mode === 'pinned' || (typeof sceneToolbarReducedMotion === 'function' && sceneToolbarReducedMotion())) return;
            // A jump (a chapter, a page, opening the book) is not reading on.
            if (Math.abs(delta) > window.innerHeight) return;
            if (current < 24 || delta < -8) _bookSetHeaderHidden(false);
            else if (current > 80 && delta > 8 && !document.querySelector('#book-panel .scene-toolbar-popover:not([hidden])')) _bookSetHeaderHidden(true);
        }, {passive: true});

        window.addEventListener('scroll', function() {
            if (_bookScrollQueued || document.documentElement.dataset.view !== 'book') return;
            _bookScrollQueued = true;
            requestAnimationFrame(_bookTrack);
        }, {passive: true});

        // Open the book at scene *p* (the start when none is given).
        function openBookView(p, options) {
            options = options || {};
            // Without scenes there is no book to read.
            if (!paths.length) return false;
            if (typeof guardDirtySceneNavigation === 'function' && guardDirtySceneNavigation()) {
                showUnsavedDialog({onContinue: function() { openBookView(p, options); }});
                return false;
            }
            if (paths.indexOf(p) < 0) p = null;
            var hash = '/book' + (p ? '/' + encodeURIComponent(p) : '');
            var view = document.documentElement.dataset.view;
            // Back returns to the scene the book was opened from, where it was
            // scrolled to. Coming back from Edit keeps that.
            if (!options.returning) {
                var sceneBody = document.querySelector('#sceneModal .modal-content');
                _bookOrigin = view === 'scene' && paths[curIdx]
                    ? {scene: paths[curIdx], top: sceneBody ? sceneBody.scrollTop : 0} : null;
            }
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
            if (typeof syncReadingMeasure === 'function') syncReadingMeasure();
            _bookHideSidebar();
            document.documentElement.dataset.view = 'book';
            _bookCurrent = null;
            if (options.route !== false) routeToHash(hash, true);
            var land = function() {
                // Opened in the print layout, the page is the pages' to scroll.
                if (_bookPagesScroll !== null) return;
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
            var layout = options.layout;
            if (!layout) {
                try { layout = localStorage.getItem(BOOK_LAYOUT_KEY); } catch (e) {}
            }
            setBookLayout(layout === 'print');
            if (!options.returning && layout !== 'print') _bookShowIntro();
            return true;
        }

        // Back: to the scene the book was opened from, or the dashboard.
        function leaveBookView() {
            var origin = _bookOrigin;
            _bookOrigin = null;
            if (!origin || paths.indexOf(origin.scene) < 0) {
                closeBookView();
                return;
            }
            if (openSceneModal(origin.scene) === false) return;
            [0, 40, 120, 260].forEach(function(delay) {
                setTimeout(function() {
                    var body = document.querySelector('#sceneModal .modal-content');
                    if (body && paths[curIdx] === origin.scene) body.scrollTo({top: origin.top, left: 0, behavior: 'instant'});
                }, delay);
            });
        }

        // Focus: the bars step aside so the pages fill the screen. They slide
        // back over the pages while the pointer is near the top or bottom.
        function toggleBookFocus(on) {
            var panel = document.getElementById('book-panel');
            if (!panel) return;
            if (on === undefined) on = !panel.classList.contains('is-focus');
            if (on && _bookPagesScroll === null) return;
            panel.classList.toggle('is-focus', on);
            panel.classList.remove('is-peek-top', 'is-peek-bottom');
            document.getElementById('bookFocusBtn').setAttribute('aria-pressed', on ? 'true' : 'false');
        }

        // Style, PDF kind, trim and paper: Export's settings, chosen here too.
        // The choices come from Export's outline; what is shown is what the
        // PDF on screen was laid out as.
        var _bookPrintOptions = null;

        function _bookFillPrintFields(facts) {
            var load = _bookPrintOptions ? Promise.resolve(_bookPrintOptions)
                : fetch('/api/export/outline').then(function(r) { return r.json(); }).then(function(outline) {
                    _bookPrintOptions = outline;
                    var fill = function(id, items) {
                        var select = document.getElementById(id);
                        select.innerHTML = '';
                        items.forEach(function(item) { select.add(new Option(item.label, item.name)); });
                    };
                    fill('bookPrintStyle', outline.styles.filter(function(style) {
                        return style.formats.indexOf('pdf-print') >= 0 || style.formats.indexOf('pdf-share') >= 0;
                    }));
                    fill('bookPrintTrim', outline.trims);
                    fill('bookPrintPaper', outline.papers);
                    return outline;
                });
            return load.then(function() {
                if (facts.style) document.getElementById('bookPrintStyle').value = facts.style;
                document.getElementById('bookPrintFormat').value = facts.layout === 'print' ? 'pdf-print' : 'pdf-share';
                if (facts.trim) document.getElementById('bookPrintTrim').value = facts.trim;
                if (facts.paper) document.getElementById('bookPrintPaper').value = facts.paper;
                _bookSyncPrintFields();
            }).catch(function() {});
        }

        function _bookSyncPrintFields() {
            var style = document.getElementById('bookPrintStyle').value;
            var entry = (_bookPrintOptions && _bookPrintOptions.styles || []).filter(function(s) { return s.name === style; })[0];
            var printable = !entry || entry.formats.indexOf('pdf-print') >= 0;
            var format = document.getElementById('bookPrintFormat');
            format.options[0].disabled = !printable;
            if (!printable) format.value = 'pdf-share';
            document.getElementById('bookPrintNote').textContent = printable ? '' : (entry ? entry.label : style) + ' makes a shareable PDF only.';
            var print = format.value === 'pdf-print';
            document.getElementById('bookPrintTrimField').hidden = !print;
            document.getElementById('bookPrintPaperField').hidden = print;
        }

        // A new style or size: laid out again where the reader is, and
        // remembered as Export's.
        function setBookPrintLayout() {
            if (!_bookPages || _bookPagesScroll === null) return;
            _bookSyncPrintFields();
            // Where the reader is, as a scene and how far into it.
            var anchor = _bookPages.anchor('scene-');
            var source = fetchBookPdf({remember: {
                style: document.getElementById('bookPrintStyle').value,
                format: document.getElementById('bookPrintFormat').value,
                trim: document.getElementById('bookPrintTrim').value,
                paper: document.getElementById('bookPrintPaper').value,
            }});
            source.then(_bookFillPrintFields, function() {});
            _bookPages.load(source, anchor ? {dest: anchor.name, anchor: anchor} : null);
        }

        // The pages take the theme's colors, as the text does.
        function _bookPageColors() {
            var styles = getComputedStyle(document.documentElement);
            var background = styles.getPropertyValue('--surface-card').trim();
            var foreground = styles.getPropertyValue('--text-main').trim();
            return background && foreground ? {background: background, foreground: foreground} : null;
        }

        // Print layout: the book as Export lays it out, opened at the chapter
        // being read. Text again goes back to the same place in the text.
        function setBookLayout(on, remember) {
            var panel = document.getElementById('book-panel');
            var stage = document.getElementById('bookPages');
            if (!panel || !stage) return;
            // The demo has no server to lay the pages out.
            if (window.PROSEVIEW_STATIC) on = false;
            if (remember !== false && document.documentElement.dataset.view === 'book') {
                try { localStorage.setItem(BOOK_LAYOUT_KEY, on ? 'print' : 'text'); } catch (e) {}
            }
            document.getElementById('bookViewText').setAttribute('aria-checked', on ? 'false' : 'true');
            document.getElementById('bookViewPrint').setAttribute('aria-checked', on ? 'true' : 'false');
            document.getElementById('bookFocusBtn').hidden = !on;
            if (on === (_bookPagesScroll !== null)) return;
            document.getElementById('bookPagesNav').hidden = !on;
            if (!on) {
                toggleBookFocus(false);
                if (_bookPages) _bookPages.close();
                stage.hidden = true;
                panel.classList.remove('is-pages');
                var y = _bookPagesScroll;
                _bookPagesScroll = null;
                if (document.documentElement.dataset.view === 'book') window.scrollTo({top: y, left: 0, behavior: 'instant'});
                return;
            }
            _bookPagesScroll = window.scrollY;
            toggleBookToc(false);
            document.getElementById('bookIntro').hidden = true;
            panel.classList.add('is-pages');
            stage.hidden = false;
            if (!_bookPages) {
                _bookPages = createPdfPages(stage, {
                    prev: document.getElementById('bookPagesPrev'),
                    next: document.getElementById('bookPagesNext'),
                    pick: document.getElementById('bookPagesPick'),
                    status: document.getElementById('bookPagesStatus'),
                }, 'book', {
                    // Flat in the page, like the text: a page as wide as the
                    // text column, under the header.
                    continuous: true,
                    columnWidth: function() {
                        return parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--reading-measure')) || 760;
                    },
                    pageColors: _bookPageColors,
                    topOffset: function() {
                        return document.getElementById('book-panel').classList.contains('is-focus') ? 0 : _bookHeaderBottom();
                    },
                });
                // The header and the bar name the scene on screen, as in the
                // text, and Edit opens it.
                _bookPages.onshow = function() {
                    var position = _bookPages.position();
                    var scene = _bookPages.markAt('scene-', position);
                    var chapter = _bookPages.markAt('chapter-', position);
                    // A chapter's opening page, before its first scene, is that chapter's.
                    var opening = chapter && (!scene || chapter.page > scene.page || (chapter.page === scene.page && chapter.top > scene.top));
                    var section = !opening && scene
                        ? _bookSections.filter(function(s) { return _bookSceneMark(s.dataset.path) === scene.name; })[0] : null;
                    if (!section && chapter) section = _bookSections[_bookChapterStarts[Number(chapter.name.slice(8)) - 1]];
                    if (section) _bookShowWhere(section);
                    // Kept for this tab, so a reload of the page (Proseview
                    // updated, say) opens at this same spot.
                    try { sessionStorage.setItem(BOOK_PRINT_ANCHOR_KEY, JSON.stringify(_bookPages.anchor('scene-'))); } catch (e) {}
                };
                document.getElementById('bookPagesNext').after(_bookPages.tools);
                // A new theme (or one tried in the theme menu) redraws them.
                var themeTimer = null;
                new MutationObserver(function() {
                    if (_bookPagesScroll === null) return;
                    clearTimeout(themeTimer);
                    themeTimer = setTimeout(function() { _bookPages.refresh(); }, 80);
                }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
            }
            // Opened where the scene being read starts on its page.
            var section = _bookCurrentSection();
            var chapter = section ? (parseInt(section.dataset.chapterIndex, 10) || 0) + 1 : 1;
            var mark = section ? _bookSceneMark(section.dataset.path) : '';
            // Within that scene, the spot the reader last had in view, if
            // this tab was reading it (a reload comes back to it).
            var anchor = null;
            try { anchor = JSON.parse(sessionStorage.getItem(BOOK_PRINT_ANCHOR_KEY) || 'null'); } catch (e) {}
            if (!anchor || anchor.name !== mark) anchor = null;
            var source = fetchBookPdf({});
            source.then(_bookFillPrintFields, function() {});
            _bookPages.load(source, {dest: mark || 'chapter-' + chapter, anchor: anchor}).then(function() {
                if (_bookPagesScroll === null || anchor) return;
                if (!_bookPages.goTo(mark)) _bookPages.goTo('chapter-' + chapter);
            });
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
            var pagesPrev = document.getElementById('bookPagesPrev');
            var pagesNext = document.getElementById('bookPagesNext');
            var pagesPick = document.getElementById('bookPagesPick');
            if (pagesPrev) pagesPrev.addEventListener('click', function() { if (_bookPages) _bookPages.turn(-1); });
            if (pagesNext) pagesNext.addEventListener('click', function() { if (_bookPages) _bookPages.turn(1); });
            if (pagesPick) pagesPick.addEventListener('change', function() { if (_bookPages) _bookPages.show(Number(pagesPick.value)); });
            document.addEventListener('keydown', function(event) {
                if (document.documentElement.dataset.view !== 'book') return;
                // Pages fills the screen, so Cmd/Ctrl + − 0 zoom its pages.
                if (_bookPagesScroll !== null && _bookPages && !event.defaultPrevented && _bookPages.handleKey(event)) return;
                if (event.ctrlKey || event.altKey || event.metaKey || event.defaultPrevented) return;
                var tag = (event.target && event.target.tagName || '').toUpperCase();
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (event.target && event.target.isContentEditable)) return;
                if (document.querySelector('dialog[open]')) return;
                var tocOpen = toc && !toc.hidden;
                var panel = document.getElementById('book-panel');
                // Shift+F: full screen, as in the scene view.
                if ((event.key === 'f' || event.key === 'F') && event.shiftKey && typeof toggleFullscreen === 'function') {
                    event.preventDefault();
                    toggleFullscreen();
                    return;
                }
                if ((event.key === 'f' || event.key === 'F') && !event.shiftKey && _bookPagesScroll !== null) {
                    event.preventDefault();
                    toggleBookFocus();
                    return;
                }
                if (event.key === 'Escape' && !tocOpen) {
                    if (document.querySelector('.scene-toolbar-popover:not([hidden])')) return;
                    event.preventDefault();
                    // Esc steps back one thing at a time: full screen, Focus, the book.
                    if (document.fullscreenElement && typeof toggleFullscreen === 'function') toggleFullscreen();
                    else if (panel.classList.contains('is-focus')) toggleBookFocus(false);
                    else leaveBookView();
                    return;
                }
                if (_bookPagesScroll !== null) {
                    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
                        event.preventDefault();
                        if (_bookPages) _bookPages.turn(event.key === 'ArrowRight' ? 1 : -1);
                    }
                    return;
                }
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
            // In Focus, the bars come back while the pointer is near them.
            document.addEventListener('mousemove', function(event) {
                var panel = document.getElementById('book-panel');
                if (panel && panel.classList.contains('is-header-hidden') && event.clientY < 56) _bookSetHeaderHidden(false);
                if (!panel || !panel.classList.contains('is-focus')) return;
                var nearTop = event.clientY < 56 || !!event.target.closest('.book-header');
                var nearBottom = event.clientY > window.innerHeight - 64 || !!event.target.closest('.book-nav');
                panel.classList.toggle('is-peek-top', nearTop);
                panel.classList.toggle('is-peek-bottom', nearBottom);
            });
            var bookHeader = document.querySelector('#book-panel .book-header');
            if (bookHeader) bookHeader.addEventListener('focusin', function() { _bookSetHeaderHidden(false); });
            // Leaving the book, however it happens, gives the file browser back.
            new MutationObserver(function() {
                if (document.documentElement.dataset.view !== 'book') {
                    setBookLayout(false, false);
                    _bookRestoreSidebar();
                    var intro = document.getElementById('bookIntro');
                    if (intro) intro.hidden = true;
                    toggleBookToc(false);
                }
            }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-view']});
        })();
