        // ── Pages: the real PDF, page by page ───────────────────────────────
        // One viewer for the book as Export lays it out: white pages on a dark
        // panel, facing pages for a printed book, drawn by pdf.js with its
        // text layer over each page so the words can be selected and copied.
        // Only the spread on screen is drawn. pdf.js (vendor/pdfjs/) is
        // loaded the first time a viewer opens.

        var _pdfjsLoading = null;

        // pdf.js 6 closes a document through the task that opened it.
        function closePdf(pdf) {
            if (pdf) pdf.loadingTask.destroy();
        }

        function loadPdfjs() {
            if (!_pdfjsLoading) {
                var base = new URL('vendor/pdfjs/', document.baseURI).href;
                _pdfjsLoading = import(base + 'pdf.min.mjs').then(function(lib) {
                    lib.GlobalWorkerOptions.workerSrc = base + 'pdf.worker.min.mjs';
                    return lib;
                });
                _pdfjsLoading.catch(function() { _pdfjsLoading = null; });
            }
            return _pdfjsLoading;
        }

        // The book as a PDF from the server: *body* is an Export request, or
        // {} for the whole book as Export would make it now.
        function fetchBookPdf(body) {
            return fetch('/api/export/pdf', {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body || {})})
                .catch(function() { throw new Error('Proseview has stopped running. Start it again, then reload this page.'); })
                .then(function(response) {
                    if (!response.ok) {
                        return response.json().catch(function() { return {}; }).then(function(data) {
                            throw new Error(data.error || 'The pages could not be laid out.');
                        });
                    }
                    // What it was laid out as: layout (print or share), style, trim, paper.
                    var facts = {};
                    ['layout', 'style', 'trim', 'paper'].forEach(function(name) {
                        facts[name] = response.headers.get('X-Proseview-' + name.charAt(0).toUpperCase() + name.slice(1)) || '';
                    });
                    if (!facts.layout) facts.layout = 'share';
                    return response.arrayBuffer().then(function(data) { facts.data = data; return facts; });
                });
        }

        //: Zoom steps, in percent of the page's real size.
        var PDF_ZOOM_STEPS = [50, 67, 75, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400];
        //: Below this width a spread's pages are too small to read.
        var PDF_NARROW = 440;

        function _pdfToolButton(label, html, extra) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'pdf-pages-tool' + (extra ? ' ' + extra : '');
            button.setAttribute('aria-label', label);
            button.title = label;
            button.innerHTML = html;
            return button;
        }

        // *stage* holds the pages; *controls* are the {prev, next, pick, status}
        // the host shows them with (the host wires their events to turn/show).
        // viewer.tools is the one/two-page and zoom group, for the host to
        // place beside its controls. *name* keeps this viewer's choices of
        // pages and zoom apart from another viewer's.
        //
        // Boxed (the Export preview), one spread fills the panel at a time.
        // With options.continuous (the reader), every page is a sheet in the
        // page's own scroll, drawn as it comes near the screen; Fit makes a
        // page as wide as options.columnWidth(), and options.topOffset() is
        // what covers the top of the window (a sticky header).
        // options.pageColors() gives {background, foreground} to draw the
        // pages in (pdf.js recolours text and lines, and leaves photographs
        // and illustrations as they are), or null for the PDF's own colors;
        // viewer.refresh() redraws them after it changes.
        function createPdfPages(stage, controls, name, options) {
            options = options || {};
            var continuous = !!options.continuous;
            var viewer = {pdf: null, layout: '', spreads: false, index: 0, count: 0, onshow: null, marks: []};
            var loadSeq = 0;
            var drawSeq = 0;
            var tasks = [];
            var lastSize = '';
            var scaleNow = 0;
            var prefKey = 'proseview-pdf-pages-' + (name || 'view');
            var pref = {};   // {pages: 'one'|'two', zoom: percent} -- unset is the default, and Fit
            try { pref = JSON.parse(localStorage.getItem(prefKey) || '{}') || {}; } catch (e) {}
            delete pref.page;  // a page color chosen before pages followed the theme

            function pageColors() {
                return options.pageColors ? options.pageColors() : null;
            }
            stage.classList.add('pdf-pages');
            stage.classList.toggle('is-continuous', continuous);
            stage.tabIndex = 0;

            function savePref() {
                try { localStorage.setItem(prefKey, JSON.stringify(pref)); } catch (e) {}
            }

            // ── One or two pages, and zoom ──
            var tools = document.createElement('div');
            tools.className = 'pdf-pages-tools';
            tools.setAttribute('role', 'group');
            tools.setAttribute('aria-label', 'Page view');
            tools.hidden = true;
            var oneBtn = _pdfToolButton('One page', '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4.5" y="2.5" width="7" height="11" rx="1"/></svg>');
            var twoBtn = _pdfToolButton('Two pages', '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="6.5" height="11" rx="1"/><rect x="8" y="2.5" width="6.5" height="11" rx="1"/></svg>');
            var outBtn = _pdfToolButton('Zoom out', '&minus;');
            var levelBtn = _pdfToolButton(continuous ? 'Fit the page to the reading column' : 'Fit the page to the panel', 'Fit', 'pdf-pages-zoom');
            var inBtn = _pdfToolButton('Zoom in', '+');
            var pagesGroup = document.createElement('span');
            pagesGroup.className = 'pdf-pages-tool-group';
            pagesGroup.append(oneBtn, twoBtn);
            tools.append(pagesGroup, outBtn, levelBtn, inBtn);
            viewer.tools = tools;

            function narrow() {
                return stage.clientWidth > 0 && stage.clientWidth < PDF_NARROW;
            }

            // Facing pages for a printed book, single pages for a shareable
            // PDF and on a narrow screen, unless the reader chose otherwise.
            function wantSpreads() {
                if (narrow()) return false;
                return pref.pages ? pref.pages === 'two' : viewer.layout === 'print';
            }

            function updateTools() {
                pagesGroup.hidden = narrow();
                oneBtn.setAttribute('aria-pressed', viewer.spreads ? 'false' : 'true');
                twoBtn.setAttribute('aria-pressed', viewer.spreads ? 'true' : 'false');
                levelBtn.textContent = pref.zoom ? pref.zoom + '%' : 'Fit';
                levelBtn.setAttribute('aria-pressed', pref.zoom ? 'false' : 'true');
                outBtn.disabled = !!pref.zoom && pref.zoom <= PDF_ZOOM_STEPS[0];
                inBtn.disabled = !!pref.zoom && pref.zoom >= PDF_ZOOM_STEPS[PDF_ZOOM_STEPS.length - 1];
            }

            // The zoom as a percent of the page's real size (pdf.js's 100%:
            // a point of the page is 4/3 of a CSS pixel).
            function percentNow() {
                return Math.round(scaleNow * 75);
            }

            function zoomTo(percent) {
                if (percent) percent = Math.max(PDF_ZOOM_STEPS[0], Math.min(PDF_ZOOM_STEPS[PDF_ZOOM_STEPS.length - 1], Math.round(percent)));
                if (percent) pref.zoom = percent; else delete pref.zoom;
                savePref();
                updateTools();
                return show(viewer.index, true);
            }

            viewer.zoom = function(direction) {
                if (!viewer.pdf) return;
                if (!direction) { zoomTo(null); return; }
                var current = pref.zoom || percentNow();
                var steps = direction > 0 ? PDF_ZOOM_STEPS : PDF_ZOOM_STEPS.slice().reverse();
                var next = steps.find(function(step) { return direction > 0 ? step > current : step < current; });
                if (next) zoomTo(next);
            };

            viewer.refresh = function() {
                if (viewer.pdf) show(viewer.index, true);
            };

            function setPages(mode) {
                pref.pages = mode;
                savePref();
                show(viewer.index, true);
            }

            oneBtn.addEventListener('click', function() { setPages('one'); });
            twoBtn.addEventListener('click', function() { setPages('two'); });
            outBtn.addEventListener('click', function() { viewer.zoom(-1); });
            inBtn.addEventListener('click', function() { viewer.zoom(1); });
            levelBtn.addEventListener('click', function() { viewer.zoom(0); });

            // Cmd/Ctrl + − 0 zoom the pages, not the page around them.
            viewer.handleKey = function(event) {
                if (!viewer.pdf || !(event.metaKey || event.ctrlKey) || event.altKey) return false;
                var direction = {'+': 1, '=': 1, '-': -1, '_': -1, '0': 0}[event.key];
                if (direction === undefined) return false;
                event.preventDefault();
                viewer.zoom(direction);
                return true;
            };
            [stage, tools].forEach(function(el) {
                el.addEventListener('keydown', function(event) { viewer.handleKey(event); });
            });

            // A pinch on a trackpad (a wheel with Ctrl held) zooms the pages.
            var wheelTimer = null;
            stage.addEventListener('wheel', function(event) {
                if (!event.ctrlKey || !viewer.pdf) return;
                event.preventDefault();
                var current = pref.zoom || percentNow();
                pref.zoom = Math.max(PDF_ZOOM_STEPS[0], Math.min(PDF_ZOOM_STEPS[PDF_ZOOM_STEPS.length - 1],
                    Math.round(current * Math.exp(-event.deltaY / 200))));
                updateTools();
                clearTimeout(wheelTimer);
                wheelTimer = setTimeout(function() { savePref(); show(viewer.index, true); }, 120);
            }, {passive: false});

            function setStatus(text) {
                if (controls.status) controls.status.textContent = text;
            }

            function message(text, isError) {
                var note = document.createElement('p');
                note.className = 'pdf-pages-note' + (isError ? ' is-error' : '');
                if (isError) note.setAttribute('role', 'alert');
                note.textContent = text;
                stage.replaceChildren(note);
            }

            // A printed book opens with page 1 alone on the right; after that
            // pages face each other in pairs (2–3, 4–5, …).
            function spreadOf(index) {
                if (!viewer.spreads) return [index];
                if (index === 0) return [0];
                var left = index % 2 === 1 ? index : index - 1;
                return left + 1 < viewer.count ? [left, left + 1] : [left];
            }

            function label(spread) {
                return spread.length > 1 ? 'Pages ' + (spread[0] + 1) + '–' + (spread[1] + 1) : 'Page ' + (spread[0] + 1);
            }

            function fillPicker() {
                if (!controls.pick) return;
                var pick = controls.pick;
                pick.innerHTML = '';
                for (var i = 0; i < viewer.count; ) {
                    var spread = spreadOf(i);
                    pick.add(new Option(label(spread), String(spread[0])));
                    i = spread[spread.length - 1] + 1;
                }
            }

            function updateControls(spread) {
                viewer.index = spread[0];
                var last = spread[spread.length - 1];
                if (controls.pick) controls.pick.value = String(spread[0]);
                if (controls.prev) controls.prev.disabled = spread[0] === 0;
                if (controls.next) controls.next.disabled = last >= viewer.count - 1;
                setStatus(label(spread) + ' of ' + viewer.count);
            }

            function drawPage(lib, page, scale) {
                var viewport = page.getViewport({scale: scale});
                var box = document.createElement('div');
                box.className = 'pdf-page';
                box.style.width = Math.floor(viewport.width) + 'px';
                box.style.height = Math.floor(viewport.height) + 'px';
                box.style.setProperty('--total-scale-factor', String(scale));
                var colors = pageColors();
                if (colors) box.style.background = colors.background;
                var ratio = window.devicePixelRatio || 1;
                var canvas = document.createElement('canvas');
                canvas.width = Math.floor(viewport.width * ratio);
                canvas.height = Math.floor(viewport.height * ratio);
                canvas.setAttribute('aria-hidden', 'true');
                var text = document.createElement('div');
                text.className = 'textLayer';
                box.append(canvas, text);
                var render = page.render({
                    canvasContext: canvas.getContext('2d'), viewport: viewport,
                    transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null,
                    pageColors: colors,
                });
                var layer = new lib.TextLayer({textContentSource: page.streamTextContent(), container: text, viewport: viewport});
                tasks.push(render, layer);
                return Promise.all([render.promise, layer.render()]).then(function() {
                    // Selecting past the last line keeps the selection on the page.
                    var end = document.createElement('div');
                    end.className = 'endOfContent';
                    text.appendChild(end);
                    return box;
                });
            }

            // ── Continuous: every page a sheet in the page's scroll ──
            var sheets = [];      // per page: {el, n, canvas, text, layer, task, drawn, pending, near}
            var basePage = null;  // page 1's size at scale 1; a book's pages are all one size
            var observer = null;

            function topOffset() {
                return options.topOffset ? options.topOffset() : 0;
            }

            function continuousScale() {
                if (pref.zoom) return pref.zoom / 75;
                // One page as wide as the text column; facing pages a little
                // narrower each, so the pair still sits within the window.
                var across = viewer.spreads ? 2 : 1;
                var room = stage.clientWidth / across - 8;
                var column = options.columnWidth ? options.columnWidth() * (across > 1 ? 0.65 : 1) : room;
                return Math.max(0.1, Math.min(column, room) / basePage.width);
            }

            function freeSheet(sheet) {
                if (sheet.task) { try { sheet.task.cancel(); } catch (e) {} }
                if (sheet.canvas) sheet.canvas.remove();
                if (sheet.text) sheet.text.remove();
                sheet.task = sheet.canvas = sheet.text = sheet.layer = sheet.drawn = sheet.pending = null;
            }

            function drawSheet(sheet) {
                var pdf = viewer.pdf;
                var scale = scaleNow;
                var colors = pageColors();
                var key = scale + '/' + JSON.stringify(colors);
                if (!pdf || sheet.drawn === key || sheet.pending === key) return;
                if (sheet.task) { try { sheet.task.cancel(); } catch (e) {} }
                sheet.pending = key;
                Promise.all([loadPdfjs(), pdf.getPage(sheet.n + 1)]).then(function(found) {
                    if (sheet.pending !== key || viewer.pdf !== pdf) return;
                    var lib = found[0], page = found[1];
                    var viewport = page.getViewport({scale: scale});
                    var ratio = window.devicePixelRatio || 1;
                    var canvas = document.createElement('canvas');
                    canvas.width = Math.floor(viewport.width * ratio);
                    canvas.height = Math.floor(viewport.height * ratio);
                    canvas.setAttribute('aria-hidden', 'true');
                    sheet.task = page.render({
                        canvasContext: canvas.getContext('2d'), viewport: viewport,
                        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null,
                        pageColors: colors,
                    });
                    return sheet.task.promise.then(function() {
                        if (sheet.pending !== key) return;
                        // The old drawing stays (stretched) until the new one is ready.
                        if (sheet.canvas) sheet.canvas.replaceWith(canvas); else sheet.el.prepend(canvas);
                        sheet.canvas = canvas;
                        sheet.drawn = key;
                        sheet.pending = null;
                        sheet.task = null;
                        if (sheet.layer) { sheet.layer.update({viewport: viewport}); return; }
                        var text = document.createElement('div');
                        text.className = 'textLayer';
                        sheet.el.appendChild(text);
                        sheet.text = text;
                        sheet.layer = new lib.TextLayer({textContentSource: page.streamTextContent(), container: text, viewport: viewport});
                        return sheet.layer.render().then(function() {
                            var end = document.createElement('div');
                            end.className = 'endOfContent';
                            text.appendChild(end);
                        });
                    });
                }).catch(function(error) {
                    if (sheet.pending === key) sheet.pending = null;
                    if (error && error.name === 'RenderingCancelledException') return;
                });
            }

            function buildSheets() {
                if (observer) observer.disconnect();
                sheets.forEach(freeSheet);
                sheets = [];
                var column = document.createElement('div');
                column.className = 'pdf-pages-column';
                for (var i = 0; i < viewer.count; ) {
                    var spread = spreadOf(i);
                    var row = document.createElement('div');
                    row.className = 'pdf-pages-spread';
                    row.dataset.first = String(spread[0]);
                    spread.forEach(function(n) {
                        var el = document.createElement('div');
                        el.className = 'pdf-page';
                        el.dataset.page = String(n);
                        el.setAttribute('aria-label', 'Page ' + (n + 1));
                        sheets[n] = {el: el, n: n};
                        row.appendChild(el);
                    });
                    if (viewer.spreads && spread.length === 1) {
                        var blank = document.createElement('div');
                        blank.className = 'pdf-page-blank';
                        if (spread[0] === 0) row.prepend(blank); else row.appendChild(blank);
                    }
                    column.appendChild(row);
                    i = spread[spread.length - 1] + 1;
                }
                stage.replaceChildren(column);
                // Drawn as they come within a screen or so; dropped once far away.
                observer = new IntersectionObserver(function(entries) {
                    entries.forEach(function(entry) {
                        var sheet = sheets[Number(entry.target.dataset.page)];
                        sheet.near = entry.isIntersecting;
                        if (sheet.near) drawSheet(sheet); else freeSheet(sheet);
                    });
                }, {rootMargin: '150% 0px'});
                sheets.forEach(function(sheet) { observer.observe(sheet.el); });
            }

            function sizeSheets(scale) {
                scaleNow = scale;
                var width = Math.floor(basePage.width * scale) + 'px';
                var height = Math.floor(basePage.height * scale) + 'px';
                var colors = pageColors();
                stage.querySelectorAll('.pdf-page-blank').forEach(function(blank) { blank.style.width = width; });
                sheets.forEach(function(sheet) {
                    sheet.el.style.width = width;
                    sheet.el.style.height = height;
                    sheet.el.style.setProperty('--total-scale-factor', String(scale));
                    sheet.el.style.background = colors ? colors.background : '';
                    if (sheet.near) drawSheet(sheet);
                });
            }

            function rowOf(index) {
                var sheet = sheets[spreadOf(index)[0]];
                return sheet ? sheet.el.parentElement : null;
            }

            function scrollToIndex(index) {
                var row = rowOf(index);
                if (!row) return;
                var top = row.getBoundingClientRect().top + window.scrollY - topOffset() - 12;
                window.scrollTo({top: Math.max(0, top), left: window.scrollX, behavior: 'instant'});
                track();
            }

            // The page in the middle of the screen, and how far down it.
            function anchorNow() {
                var middle = (topOffset() + window.innerHeight) / 2;
                for (var i = 0; i < sheets.length; i++) {
                    var rect = sheets[i].el.getBoundingClientRect();
                    if (rect.bottom >= middle) {
                        return {
                            n: i, along: Math.max(0, middle - rect.top) / (rect.height || 1),
                            across: (stage.scrollLeft + stage.clientWidth / 2) / (stage.scrollWidth || 1),
                        };
                    }
                }
                return null;
            }

            function keepAnchor(anchor) {
                if (!anchor || !sheets[anchor.n]) return;
                var rect = sheets[anchor.n].el.getBoundingClientRect();
                var middle = (topOffset() + window.innerHeight) / 2;
                window.scrollTo({top: window.scrollY + rect.top + anchor.along * rect.height - middle, left: window.scrollX, behavior: 'instant'});
                stage.scrollLeft = anchor.across * stage.scrollWidth - stage.clientWidth / 2;
            }

            // The reading line: just under whatever covers the top.
            function readingLine() {
                return topOffset() + 24;
            }

            // Where the reader is: the spread across the reading line.
            var swapping = false;  // a new PDF going in: where the reader is must not move

            function track() {
                if (!continuous || swapping || !viewer.pdf || !sheets.length || !stage.offsetParent) return;
                var line = readingLine();
                var found = sheets[0].el.parentElement;
                var rows = stage.querySelectorAll('.pdf-pages-spread');
                for (var i = 0; i < rows.length; i++) {
                    if (rows[i].getBoundingClientRect().top > line) break;
                    found = rows[i];
                }
                var first = Number(found.dataset.first);
                var spread = spreadOf(first);
                if (first !== viewer.index || !controls.pick || controls.pick.value !== String(first)) updateControls(spread);
                if (viewer.onshow) viewer.onshow(spread);
            }

            var trackQueued = false;
            window.addEventListener('scroll', function() {
                if (!continuous || trackQueued) return;
                trackQueued = true;
                requestAnimationFrame(function() { trackQueued = false; track(); });
            }, {passive: true});

            function showContinuous(index, keep) {
                var anchor = keep && sheets.length ? anchorNow() : null;
                var spreads = wantSpreads();
                if (spreads !== viewer.spreads || !sheets.length) {
                    viewer.spreads = spreads;
                    stage.classList.toggle('is-spread', spreads);
                    fillPicker();
                    buildSheets();
                }
                updateTools();
                sizeSheets(continuousScale());
                lastSize = String(stage.clientWidth);
                if (anchor) { keepAnchor(anchor); track(); } else scrollToIndex(index);
                return Promise.resolve();
            }

            // ── Marks: where each chapter and scene starts ──
            // The PDF names them (chapter-3, scene-ch03/01-…); each mark is
            // {name, page, top}, top in points down from the top of the page.
            function readMarks(pdf, height) {
                return pdf.getDestinations().then(function(all) {
                    var entries = all instanceof Map ? Array.from(all) : Object.entries(all || {});
                    return Promise.all(entries.filter(function(entry) { return /^(chapter|scene)-/.test(entry[0]); }).map(function(entry) {
                        var dest = entry[1];
                        return Promise.resolve(typeof dest[0] === 'number' ? dest[0] : pdf.getPageIndex(dest[0])).then(function(page) {
                            var y = dest[1] && dest[1].name === 'XYZ' && typeof dest[3] === 'number' ? dest[3] : height;
                            return {name: entry[0], page: page, top: Math.max(0, height - y)};
                        });
                    }));
                }).then(function(marks) {
                    return marks.sort(function(a, b) { return a.page - b.page || a.top - b.top; });
                }).catch(function() { return []; });
            }

            // Where the reading line falls: {page, top}. Facing pages are
            // read together, so on a spread it is the right-hand page.
            viewer.position = function() {
                if (!continuous || !sheets.length) return {page: viewer.index, top: 0};
                var line = readingLine();
                for (var i = 0; i < sheets.length; i++) {
                    var rect = sheets[i].el.getBoundingClientRect();
                    if (rect.bottom <= line) continue;
                    var row = Array.prototype.filter.call(sheets[i].el.parentElement.children, function(el) {
                        return el.classList.contains('pdf-page');
                    });
                    var n = Number(row[row.length - 1].dataset.page);
                    return {page: n, top: rect.top > line ? 0 : (line - rect.top) / (scaleNow || 1)};
                }
                return {page: sheets.length - 1, top: Infinity};
            };

            // The last mark named *prefix…* at or before *position*, as {name, page, top}.
            viewer.markAt = function(prefix, position) {
                var found = null;
                viewer.marks.forEach(function(mark) {
                    if (mark.name.indexOf(prefix) !== 0) return;
                    if (mark.page < position.page || (mark.page === position.page && mark.top <= position.top + 1)) found = mark;
                });
                return found;
            };

            // Distance down the book, in page heights, as the pages are laid
            // out on screen: facing pages share a row.
            function rowOfPage(page) {
                return viewer.spreads ? (page === 0 ? 0 : Math.floor((page + 1) / 2)) : page;
            }

            function along(page, top) {
                return rowOfPage(page) * basePage.height + Math.min(top, basePage.height);
            }

            // How far into the part the reader is in: {name, prefix, fraction},
            // where the part runs from its *prefix…* mark to the next one (or
            // the end of the book).
            viewer.anchor = function(prefix) {
                var position = viewer.position();
                var mark = viewer.markAt(prefix, position);
                if (!mark || !basePage) return null;
                var next = viewer.marks.filter(function(m) {
                    return m.name.indexOf(prefix) === 0 && along(m.page, m.top) > along(mark.page, mark.top);
                })[0];
                var start = along(mark.page, mark.top);
                var end = next ? along(next.page, next.top) : (rowOfPage(viewer.count - 1) + 1) * basePage.height;
                return {name: mark.name, prefix: prefix, fraction: Math.max(0, Math.min(1, (along(position.page, position.top) - start) / ((end - start) || 1)))};
            };

            // Put the reading line back at that point of the same part.
            function restoreAnchor(anchor) {
                var mark = viewer.marks.filter(function(m) { return m.name === anchor.name; })[0];
                if (!mark || !basePage) return false;
                var next = viewer.marks.filter(function(m) {
                    return m.name.indexOf(anchor.prefix) === 0 && along(m.page, m.top) > along(mark.page, mark.top);
                })[0];
                var start = along(mark.page, mark.top);
                var end = next ? along(next.page, next.top) : (rowOfPage(viewer.count - 1) + 1) * basePage.height;
                var point = start + anchor.fraction * (end - start);
                var row = Math.floor(point / basePage.height);
                var page = Math.min(viewer.count - 1, viewer.spreads ? (row === 0 ? 0 : row * 2 - 1) : row);
                var sheet = sheets[page];
                if (!sheet) return false;
                var top = sheet.el.getBoundingClientRect().top + window.scrollY + (point - row * basePage.height) * scaleNow - readingLine() + 1;
                window.scrollTo({top: Math.max(0, top), left: window.scrollX, behavior: 'instant'});
                return true;
            }

            viewer.restoreAnchor = function(anchor) {
                var done = restoreAnchor(anchor);
                track();
                return done;
            };

            // Jump (at once, no animation) to the mark called *name*.
            viewer.goTo = function(name) {
                var mark = viewer.marks.filter(function(m) { return m.name === name; })[0];
                if (!mark || !viewer.pdf) return false;
                if (!continuous) { show(mark.page); return true; }
                var sheet = sheets[mark.page];
                if (!sheet) return false;
                var top = sheet.el.getBoundingClientRect().top + window.scrollY + mark.top * scaleNow - topOffset() - 12;
                window.scrollTo({top: Math.max(0, top), left: window.scrollX, behavior: 'instant'});
                track();
                return true;
            };

            // Draw the spread holding page *index*, and only then swap it in,
            // so the panel never flashes empty between spreads. With *keep*
            // (a new zoom or page count) the same part of the page stays in view.
            function show(index, keep) {
                var pdf = viewer.pdf;
                if (!pdf) return Promise.resolve();
                index = Math.max(0, Math.min(index, viewer.count - 1));
                if (continuous) return showContinuous(index, keep);
                var spreads = wantSpreads();
                if (spreads !== viewer.spreads) {
                    viewer.spreads = spreads;
                    stage.classList.toggle('is-spread', spreads);
                    fillPicker();
                }
                updateTools();
                var spread = spreadOf(index);
                viewer.index = spread[0];
                updateControls(spread);
                var seq = ++drawSeq;
                tasks.forEach(function(task) { try { task.cancel(); } catch (e) {} });
                tasks = [];
                return Promise.all([loadPdfjs()].concat(spread.map(function(n) { return pdf.getPage(n + 1); }))).then(function(found) {
                    var lib = found[0];
                    var pages = found.slice(1);
                    if (seq !== drawSeq) return;
                    var base = pages[0].getViewport({scale: 1});
                    var styles = getComputedStyle(stage);
                    var width = stage.clientWidth - parseFloat(styles.paddingLeft) - parseFloat(styles.paddingRight);
                    var height = stage.clientHeight - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom);
                    // A printed book always leaves room for two pages, so a
                    // page sits where it will when its facing page arrives.
                    var across = viewer.spreads ? 2 : 1;
                    var scale = pref.zoom ? pref.zoom / 75
                        : Math.max(0.1, Math.min(width / (base.width * across), height / base.height));
                    scaleNow = scale;
                    lastSize = stage.clientWidth + 'x' + stage.clientHeight;
                    return Promise.all(pages.map(function(page) { return drawPage(lib, page, scale); })).then(function(boxes) {
                        if (seq !== drawSeq) return;
                        var row = document.createElement('div');
                        row.className = 'pdf-pages-spread';
                        if (viewer.spreads && boxes.length === 1) {
                            var blank = document.createElement('div');
                            blank.className = 'pdf-page-blank';
                            blank.style.width = boxes[0].style.width;
                            if (spread[0] === 0) row.append(blank, boxes[0]);
                            else row.append(boxes[0], blank);
                        } else {
                            boxes.forEach(function(box) { row.appendChild(box); });
                        }
                        // Where the middle of the view is, as a share of the pages.
                        var midX = (stage.scrollLeft + stage.clientWidth / 2) / (stage.scrollWidth || 1);
                        var midY = (stage.scrollTop + stage.clientHeight / 2) / (stage.scrollHeight || 1);
                        stage.replaceChildren(row);
                        if (keep) {
                            stage.scrollLeft = midX * stage.scrollWidth - stage.clientWidth / 2;
                            stage.scrollTop = midY * stage.scrollHeight - stage.clientHeight / 2;
                        } else {
                            stage.scrollLeft = (stage.scrollWidth - stage.clientWidth) / 2;
                            stage.scrollTop = 0;
                        }
                        stage.setAttribute('aria-label', label(spread) + ' of ' + viewer.count);
                        if (viewer.onshow) viewer.onshow(spread);
                    });
                }).catch(function(error) {
                    if (seq !== drawSeq || (error && error.name === 'RenderingCancelledException')) return;
                    message('This page could not be drawn: ' + (error && error.message || error), true);
                });
            }

            // Where to open: {page: n} (from 0), {dest: 'chapter-3'}, or the
            // first chapter, past the title page and contents.
            function resolveStart(pdf, at) {
                if (at && typeof at.page === 'number') return Promise.resolve(at.page);
                var named = at && at.dest
                    ? pdf.getDestination(at.dest).then(function(dest) { return dest ? [dest] : []; })
                    : pdf.getDestinations().then(function(all) {
                        // A Map in pdf.js 6, a plain object before.
                        var entries = all instanceof Map ? Array.from(all) : Object.entries(all || {});
                        return entries.filter(function(entry) { return /^chapter-\d+$/.test(entry[0]); })
                            .map(function(entry) { return entry[1]; });
                    });
                return named.then(function(dests) {
                    return Promise.all(dests.map(function(dest) {
                        return typeof dest[0] === 'number' ? dest[0] : pdf.getPageIndex(dest[0]);
                    }));
                }).then(function(pages) {
                    return pages.length ? Math.min.apply(null, pages) : 0;
                }).catch(function() { return 0; });
            }

            // Open the PDF that *source* (a promise of {data, layout}) brings.
            // What is on screen stays until the new pages are ready.
            viewer.load = function(source, at) {
                var seq = ++loadSeq;
                if (!viewer.pdf) message('Laying out pages…');
                setStatus('Laying out pages…');
                return Promise.all([loadPdfjs(), source]).then(function(found) {
                    if (seq !== loadSeq) return;
                    var lib = found[0];
                    return lib.getDocument({data: found[1].data, isEvalSupported: false}).promise.then(function(pdf) {
                        if (seq !== loadSeq) { closePdf(pdf); return; }
                        return Promise.all([resolveStart(pdf, at), pdf.getPage(1)]).then(function(found2) {
                            var start = found2[0];
                            basePage = found2[1].getViewport({scale: 1});
                            return readMarks(pdf, basePage.height).then(function(marks) { return [start, marks]; });
                        }).then(function(found2) {
                            var start = found2[0];
                            if (seq !== loadSeq) { closePdf(pdf); return; }
                            viewer.marks = found2[1];
                            if (continuous) {
                                if (observer) observer.disconnect();
                                sheets.forEach(freeSheet);
                                sheets = [];
                            }
                            var old = viewer.pdf;
                            swapping = true;
                            viewer.pdf = pdf;
                            viewer.count = pdf.numPages;
                            viewer.layout = found[1].layout;
                            viewer.spreads = wantSpreads();
                            stage.classList.toggle('is-spread', viewer.spreads);
                            fillPicker();
                            tools.hidden = false;
                            // A new layout of the same book (another style or
                            // size) opens at the same point of the same scene.
                            return show(start, !!old && !(at && at.anchor)).then(function() {
                                if (continuous && at && at.anchor) restoreAnchor(at.anchor);
                                swapping = false;
                                track();
                                closePdf(old);
                            });
                        });
                    });
                }).catch(function(error) {
                    swapping = false;
                    if (seq !== loadSeq) return;
                    viewer.close();
                    message(error && error.message || 'The pages could not be laid out.', true);
                    setStatus('');
                });
            };

            viewer.show = show;

            viewer.turn = function(direction) {
                if (!viewer.pdf) return;
                var spread = spreadOf(viewer.index);
                var next = direction > 0 ? spread[spread.length - 1] + 1 : spread[0] - 1;
                if (next >= 0 && next < viewer.count) show(next);
            };

            // Drop the PDF (and whatever is still loading).
            viewer.close = function() {
                loadSeq++;
                drawSeq++;
                tasks.forEach(function(task) { try { task.cancel(); } catch (e) {} });
                tasks = [];
                if (observer) observer.disconnect();
                sheets.forEach(freeSheet);
                sheets = [];
                closePdf(viewer.pdf);
                viewer.pdf = null;
                viewer.count = 0;
                tools.hidden = true;
                stage.replaceChildren();
            };

            // Text being selected: the end marker covers the page so the
            // selection does not jump to the top while the pointer is past
            // the last line (as pdf.js's own viewer does).
            stage.addEventListener('mousedown', function(event) {
                var layer = event.target.closest && event.target.closest('.textLayer');
                if (layer) layer.classList.add('selecting');
            });
            document.addEventListener('pointerup', function() {
                stage.querySelectorAll('.textLayer.selecting').forEach(function(layer) { layer.classList.remove('selecting'); });
            });

            // Redrawn at the new size when the panel changes size.
            var resizeTimer = null;
            if (typeof ResizeObserver === 'function') {
                new ResizeObserver(function() {
                    if (!viewer.pdf || !stage.clientWidth) return;
                    // A continuous column grows with its pages; only its width matters.
                    if ((continuous ? String(stage.clientWidth) : stage.clientWidth + 'x' + stage.clientHeight) === lastSize) return;
                    clearTimeout(resizeTimer);
                    resizeTimer = setTimeout(function() { show(viewer.index, true); }, 150);
                }).observe(stage);
            }
            return viewer;
        }
