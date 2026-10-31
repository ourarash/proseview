        // ── Sentence length strip ───────────────────────────────────────
        //
        // Two views of the scene's sentences, switched in place at the same
        // height. In order: one thin bar per sentence, as tall as it is long,
        // so a run of long sentences and a short punch show at a glance.
        // By length: how many sentences fall in each length band, against the
        // book's typical mix. Read from the scene as the editor holds it, so
        // it follows an edit and adds nothing to the page but the book's mix.
        //
        // The splitting follows lexical.sentence_spans (test_sentence_rhythm_e2e
        // keeps the two in step): no break after Mr. or an initial, none before
        // a lowercase word ('"Wait!" she said'), and every paragraph ends one.
        var RHYTHM_LONG = 40;
        var RHYTHM_HEIGHT = 46;
        var RHYTHM_LARGE_HEIGHT = 180;
        // The large window's own size and place, kept for this browser.
        var RHYTHM_WINDOW_KEY = 'proseview-rhythm-window';
        // Room the window needs besides its bars, until it can be measured.
        var RHYTHM_WINDOW_CHROME = 230;
        // Upper bounds of the By length view's bands; highlights.SENTENCE_BUCKETS.
        var RHYTHM_BUCKETS = [5, 10, 15, 20, 30, 40];
        var RHYTHM_BUCKET_LABELS = ['1–5', '6–10', '11–15', '16–20', '21–30', '31–40', '41+'];
        var RHYTHM_VIEW_KEY = 'proseview-rhythm-view';
        var RHYTHM_ABBREVIATIONS = ['mr', 'mrs', 'ms', 'dr', 'st', 'jr', 'sr', 'prof', 'vs', 'etc', 'e.g', 'i.e'];
        var RHYTHM_END = /([.!?…]+)["'”’)\]]*(\s+)/g;
        var RHYTHM_WORD = /[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g;
        // Speech, as lexical.dialogue_spans reads it.
        var RHYTHM_SPEECH = /"[^"]*(?:"|$)|“[^”]*(?:”|$)|(?:^|[\s—(])‘(?!(?:em|tis|twas|til|cause|n)\b)[\s\S]*?(?:’(?![A-Za-z])|$)/g;
        var _rhythmBucket = null;
        // What is picked in the large view: {kind: 'bar'|'band', index}.
        var _rhythmPick = null;
        var _rhythmBucketPath = null;

        function _rhythmEnds(text, m) {
            var next = text.charAt(m.index + m[0].length);
            if (next && next !== next.toUpperCase()) return false;
            if (m[1] === '.') {
                var before = /([A-Za-z]+(?:\.[A-Za-z]+)*)$/.exec(text.slice(Math.max(0, m.index - 12), m.index));
                if (before) {
                    var word = before[1];
                    if (RHYTHM_ABBREVIATIONS.indexOf(word.toLowerCase()) !== -1) return false;
                    if (word.length === 1 && word !== 'I' && word === word.toUpperCase()) return false;
                }
            }
            return true;
        }

        function _rhythmBucketOf(words) {
            for (var i = 0; i < RHYTHM_BUCKETS.length; i++) if (words <= RHYTHM_BUCKETS[i]) return i;
            return RHYTHM_BUCKETS.length;
        }

        // [{from, to, words, text, paragraphStart, dialogue}] in document
        // positions. Headings are not sentences and are left out.
        function sceneSentences(view) {
            var out = [];
            view.state.doc.descendants(function(node, pos) {
                if (!node.isTextblock) return true;
                if (node.type.name === 'heading') return false;
                var start = pos + 1;
                // One character per position, so offsets map straight back.
                var text = view.state.doc.textBetween(start, start + node.content.size, '\n', '￼');
                var speech = [], sm;
                RHYTHM_SPEECH.lastIndex = 0;
                while ((sm = RHYTHM_SPEECH.exec(text))) {
                    if (!sm[0]) { RHYTHM_SPEECH.lastIndex++; continue; }
                    speech.push([sm.index, sm.index + sm[0].length]);
                }
                var spans = [], from = 0, m;
                RHYTHM_END.lastIndex = 0;
                while ((m = RHYTHM_END.exec(text))) {
                    if (!_rhythmEnds(text, m)) continue;
                    spans.push([from, m.index + m[0].length - m[2].length]);
                    from = m.index + m[0].length;
                }
                spans.push([from, text.replace(/\s+$/, '').length]);
                var first = true;
                spans.forEach(function(span) {
                    var a = span[0], b = span[1];
                    while (a < b && /\s/.test(text.charAt(a))) a++;
                    if (a >= b) return;
                    var sentence = text.slice(a, b);
                    var words = (sentence.match(RHYTHM_WORD) || []).length;
                    if (!words) return;
                    // Speech when most of it is inside quotation marks.
                    var inside = speech.reduce(function(n, s) {
                        return n + Math.max(0, Math.min(b, s[1]) - Math.max(a, s[0]));
                    }, 0);
                    out.push({from: start + a, to: start + b, words: words, text: sentence,
                              paragraphStart: first, dialogue: inside > (b - a) / 2});
                    first = false;
                });
                return false;
            });
            return out;
        }

        function _rhythmMedians() {
            // A top-level const, not a property of window.
            return (typeof medians !== 'undefined' && medians) || {};
        }

        function _rhythmStdev(values) {
            if (values.length < 2) return 0;
            var mean = values.reduce(function(a, b) { return a + b; }, 0) / values.length;
            var sq = values.reduce(function(a, b) { return a + (b - mean) * (b - mean); }, 0);
            return Math.sqrt(sq / (values.length - 1));
        }

        function _rhythmView() {
            try { return localStorage.getItem(RHYTHM_VIEW_KEY) === 'spread' ? 'spread' : 'order'; }
            catch (e) { return 'order'; }
        }

        function _rhythmEl(tag, cls, text) {
            var el = document.createElement(tag);
            if (cls) el.className = cls;
            if (text !== undefined) el.textContent = text;
            return el;
        }

        function _rhythmOrder(sentences, avg, height, large) {
            var counts = sentences.map(function(s) { return s.words; });
            var cap = Math.max(20, Math.min(Math.max.apply(null, counts), 60));
            var bars = _rhythmEl('div', 'rhythm-bars');
            // Long scenes get thinner bars, never a scrollbar.
            bars.style.gap = sentences.length > 150 ? '0' : sentences.length > 70 ? '1px' : '2px';
            sentences.forEach(function(s, i) {
                var cls = 'rhythm-bar' + (s.words > RHYTHM_LONG ? ' is-long' : '') + (s.dialogue ? ' is-dialogue' : '')
                    + (s.paragraphStart && i ? ' is-paragraph' : '');
                var bar = _rhythmEl('span', cls);
                bar.style.height = Math.max(2, Math.round(Math.min(s.words, cap) / cap * height)) + 'px';
                var preview = s.text.split(/\s+/).slice(0, 8).join(' ');
                bar.title = (s.text.split(/\s+/).length > 8 ? preview + '…' : preview) + ' — '
                    + s.words + (s.words === 1 ? ' word' : ' words') + (s.dialogue ? ' (dialogue)' : '');
                bar.dataset.index = String(i);
                if (large && _rhythmPick && _rhythmPick.kind === 'bar' && _rhythmPick.index === i) bar.classList.add('is-picked');
                // A bar takes you to its sentence, from the panel or the large
                // window alike; the window stays open beside the text.
                bar.onclick = function() {
                    if (large) pickRhythm({kind: 'bar', index: i});
                    revealSentence(sentences[i]);
                };
                // Pointing at a bar lights its sentence for as long as it stays.
                bar.onmouseenter = function() { lightSentence(sentences[i]); };
                bar.onmouseleave = function() { lightSentence(null); };
                bars.appendChild(bar);
            });
            bars.style.height = height + 'px';
            // The scene's average, as a faint line across the bars.
            var line = _rhythmEl('span', 'rhythm-avg');
            line.style.bottom = Math.round(Math.min(avg, cap) / cap * height) + 'px';
            line.title = 'Average: ' + Math.round(avg) + ' words';
            bars.appendChild(line);
            return bars;
        }

        function _rhythmSpread(sentences, height, large) {
            var counts = [0, 0, 0, 0, 0, 0, 0];
            sentences.forEach(function(s) { counts[_rhythmBucketOf(s.words)] += 1; });
            var shares = _rhythmMedians().sent_buckets || [];
            var expected = counts.map(function(_, i) { return (shares[i] || 0) * sentences.length; });
            var top = Math.max.apply(null, counts.concat(expected).concat([1]));
            // Headroom above the tallest bar for its count, so nothing clips.
            var room = height - 12 - 12;
            var wrap = _rhythmEl('div', 'rhythm-spread');
            counts.forEach(function(n, i) {
                var col = _rhythmEl('button', 'rhythm-bucket' + (_rhythmBucket === i ? ' is-on' : ''));
                col.type = 'button';
                col.dataset.bucket = String(i);
                col.setAttribute('aria-pressed', _rhythmBucket === i ? 'true' : 'false');
                col.title = n + (n === 1 ? ' sentence, ' : ' sentences, ') + RHYTHM_BUCKET_LABELS[i] + ' words'
                    + (shares.length ? ' (your typical scene: about ' + Math.round(expected[i]) + ')' : '');
                var area = _rhythmEl('span', 'rhythm-bucket-area');
                var bar = _rhythmEl('span', 'rhythm-bucket-bar' + (i === RHYTHM_BUCKETS.length ? ' is-long' : ''));
                bar.style.height = Math.round(n / top * room) + 'px';
                area.appendChild(bar);
                // The count, quietly, on top of its bar; none for an empty band.
                var count = _rhythmEl('span', 'rhythm-bucket-count', n ? String(n) : '');
                // Above the bar or the typical outline, whichever is taller.
                count.style.bottom = (Math.round(Math.max(n, shares.length ? expected[i] : 0) / top * room) + 1) + 'px';
                area.appendChild(count);
                if (shares.length) {
                    var typical = _rhythmEl('span', 'rhythm-bucket-typical');
                    typical.style.height = Math.round(expected[i] / top * room) + 'px';
                    area.appendChild(typical);
                }
                col.append(area, _rhythmEl('span', 'rhythm-bucket-label', RHYTHM_BUCKET_LABELS[i]));
                col.onclick = function() {
                    var off = _rhythmBucket === i;
                    tintRhythmBucket(off ? null : i);
                    if (large) pickRhythm(off ? null : {kind: 'band', index: i});
                };
                wrap.appendChild(col);
            });
            wrap.style.height = height + 'px';
            return wrap;
        }

        // What the marks mean, one quiet line under the graph. Both views keep
        // the same height for it, so switching moves nothing.
        function _rhythmLegend(view) {
            var legend = _rhythmEl('p', 'rhythm-legend');
            var items = view === 'spread'
                ? [['rhythm-key-bar', 'this scene'], ['rhythm-key-outline', 'your typical scene']]
                : [['rhythm-key-bar', 'narration'], ['rhythm-key-bar is-dialogue', 'dialogue'],
                   ['rhythm-key-avg', 'average'], ['rhythm-key-tick', 'new paragraph']];
            items.forEach(function(item, i) {
                if (i) legend.appendChild(document.createTextNode(' \u00b7 '));
                var key = _rhythmEl('span', 'rhythm-key');
                var swatch = _rhythmEl('span', item[0]);
                swatch.setAttribute('aria-hidden', 'true');
                key.append(swatch, document.createTextNode(item[1]));
                legend.appendChild(key);
            });
            return legend;
        }

        // "Average 9 words; most sentences 3–15 words": the middle two-thirds,
        // read as the average plus or minus one standard deviation.
        function _rhythmRange(avg, sd) {
            return Math.max(1, Math.round(avg - sd)) + '\u2013' + Math.round(avg + sd);
        }

        // The strip for the open scene, or null before its editor is mounted.
        // The large one is the same drawing at the size of the dialog.
        function sceneRhythmStrip(path, large) {
            if (!_pmView || typeof _pmViewPath === 'undefined' || _pmViewPath !== path) return null;
            var sentences = sceneSentences(_pmView);
            var height = large ? _rhythmLargeHeight() : RHYTHM_HEIGHT;
            var wrap = _rhythmEl('div', 'rhythm' + (large ? ' rhythm-large' : ''));
            wrap.id = large ? 'sceneRhythmLarge' : 'sceneRhythm';
            if (!sentences.length) {
                wrap.appendChild(_rhythmEl('p', 'scene-panel-note', 'No sentences yet.'));
                return wrap;
            }
            var view = _rhythmView();
            var counts = sentences.map(function(s) { return s.words; });
            var avg = counts.reduce(function(a, b) { return a + b; }, 0) / counts.length;

            var tabs = _rhythmEl('div', 'rhythm-switch');
            tabs.setAttribute('role', 'tablist');
            tabs.setAttribute('aria-label', 'Sentence length view');
            [['order', 'In order'], ['spread', 'By length']].forEach(function(pair) {
                var b = _rhythmEl('button', 'rhythm-switch-btn', pair[1]);
                b.type = 'button';
                b.setAttribute('role', 'tab');
                b.dataset.view = pair[0];
                b.setAttribute('aria-selected', view === pair[0] ? 'true' : 'false');
                b.onclick = function() {
                    try { localStorage.setItem(RHYTHM_VIEW_KEY, pair[0]); } catch (e) {}
                    if (pair[0] === 'order') tintRhythmBucket(null);
                    refreshSceneRhythm();
                };
                tabs.appendChild(b);
            });
            if (!large) {
                var grow = _rhythmEl('button', 'rhythm-switch-btn rhythm-enlarge', '\u2922');
                grow.type = 'button';
                grow.setAttribute('aria-label', 'Enlarge the sentence length graph');
                grow.title = 'Enlarge';
                grow.onclick = openRhythmDialog;
                tabs.appendChild(grow);
            }
            wrap.appendChild(tabs);
            wrap.appendChild(view === 'spread' ? _rhythmSpread(sentences, height, large) : _rhythmOrder(sentences, avg, height, large));
            wrap.appendChild(_rhythmLegend(view));

            var md = _rhythmMedians();
            var line = 'Average ' + Math.round(avg) + ' words; most sentences '
                + _rhythmRange(avg, _rhythmStdev(counts)) + ' words.';
            if (typeof md.avg_sent === 'number') {
                line += ' Your typical scene: ' + Math.round(md.avg_sent)
                    + (typeof md.sent_stdev === 'number' ? ', mostly ' + _rhythmRange(md.avg_sent, md.sent_stdev) : '') + '.';
            }
            line += ' Darker bars are over ' + RHYTHM_LONG + ' words.';
            // The numbers behind the graph, behind an ⓘ on the heading row:
            // shown on hover, focus or a click, and Esc puts them away.
            var info = _rhythmEl('button', 'rhythm-switch-btn rhythm-info', '\u24d8');
            info.type = 'button';
            info.setAttribute('aria-label', 'About these numbers');
            info.setAttribute('aria-expanded', 'false');
            var pop = _rhythmEl('span', 'rhythm-info-pop');
            pop.id = wrap.id + 'Info';
            pop.setAttribute('role', 'tooltip');
            pop.appendChild(_rhythmEl('span', 'rhythm-note', line));
            pop.appendChild(_rhythmEl('span', 'rhythm-info-hint', 'Range is average \u00b1 one standard deviation.'));
            info.setAttribute('aria-describedby', pop.id);
            info.onclick = function() {
                info.setAttribute('aria-expanded', info.getAttribute('aria-expanded') === 'true' ? 'false' : 'true');
            };
            info.addEventListener('keydown', function(e) {
                if (e.key === 'Escape' && info.getAttribute('aria-expanded') === 'true') {
                    e.stopPropagation();
                    info.setAttribute('aria-expanded', 'false');
                    info.blur();
                }
            });
            info.addEventListener('blur', function() { info.setAttribute('aria-expanded', 'false'); });
            tabs.insertBefore(pop, tabs.firstChild);
            tabs.insertBefore(info, pop);
            return wrap;
        }

        // Redraws the strip in the Analysis pane, if it is showing, from the
        // scene as now mounted: after the editor first mounts and after a save.
        function refreshSceneRhythm() {
            var path = typeof paths !== 'undefined' ? paths[curIdx] : null;
            if (!path) return;
            // A band tinted in one scene is not carried into the next.
            if (path !== _rhythmBucketPath) _rhythmBucket = null;
            [['sceneRhythm', false], ['sceneRhythmLarge', true]].forEach(function(pair) {
                var old = document.getElementById(pair[0]);
                var strip = old && sceneRhythmStrip(path, pair[1]);
                if (strip) old.replaceWith(strip);
            });
            tintRhythmBucket(_rhythmBucket);
            // A bar redrawn under the pointer never gets its mouseleave.
            lightSentence(null);
        }

        // Tints every sentence in one length band, in place; null clears it.
        var RHYTHM_BUCKET_TINT = 'proseview-rhythm-bucket';
        function tintRhythmBucket(bucket) {
            _rhythmBucket = bucket;
            _rhythmBucketPath = typeof paths !== 'undefined' ? paths[curIdx] : null;
            document.querySelectorAll('.rhythm .rhythm-bucket').forEach(function(col) {
                var on = Number(col.dataset.bucket) === bucket;
                col.classList.toggle('is-on', on);
                col.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
            if (!(window.CSS && CSS.highlights && typeof Highlight === 'function')) return;
            if (bucket === null || !_pmView) { CSS.highlights.delete(RHYTHM_BUCKET_TINT); return; }
            var ranges = [];
            sceneSentences(_pmView).forEach(function(s) {
                if (_rhythmBucketOf(s.words) !== bucket) return;
                try {
                    var a = _pmView.domAtPos(s.from), b = _pmView.domAtPos(s.to);
                    var range = document.createRange();
                    range.setStart(a.node, a.offset);
                    range.setEnd(b.node, b.offset);
                    ranges.push(range);
                } catch (e) {}
            });
            CSS.highlights.set(RHYTHM_BUCKET_TINT, new Highlight(...ranges));
        }

        // A click on a bar: the sentence is brought to the middle of the
        // reading view and lit for a moment. Hovering never scrolls.
        var RHYTHM_FLASH = 'proseview-rhythm-flash';
        function revealSentence(sentence) {
            if (!_pmView) return;
            var scroller = document.querySelector('#sceneModal .modal-content');
            try {
                var coords = _pmView.coordsAtPos(sentence.from);
                if (scroller) {
                    var box = scroller.getBoundingClientRect();
                    // The middle of what the large window leaves in view, or
                    // of the whole reading view when it is closed.
                    var from = box.top, to = box.bottom;
                    var dialog = document.getElementById('rhythmDialog');
                    if (dialog && dialog.open) {
                        var d = dialog.getBoundingClientRect();
                        if (d.top - box.top >= box.bottom - d.bottom) to = Math.max(box.top + 40, d.top);
                        else from = Math.min(box.bottom - 40, d.bottom);
                    }
                    scroller.scrollBy({top: coords.top - (from + to) / 2, behavior: 'smooth'});
                }
                if (window.CSS && CSS.highlights && typeof Highlight === 'function') {
                    CSS.highlights.set(RHYTHM_FLASH, new Highlight(_rhythmTextRange(sentence)));
                    clearTimeout(revealSentence.timer);
                    revealSentence.timer = setTimeout(function() { CSS.highlights.delete(RHYTHM_FLASH); }, 1600);
                }
            } catch (e) {}
        }

        // A bar pointed at: its sentence is lit in place, never scrolled to;
        // null puts it out.
        var RHYTHM_HOVER = 'proseview-rhythm-hover';
        function lightSentence(sentence) {
            if (!(window.CSS && CSS.highlights && typeof Highlight === 'function')) return;
            if (!sentence || !_pmView) { CSS.highlights.delete(RHYTHM_HOVER); return; }
            try { CSS.highlights.set(RHYTHM_HOVER, new Highlight(_rhythmTextRange(sentence))); } catch (e) {}
        }

        function _rhythmTextRange(sentence) {
            var a = _pmView.domAtPos(sentence.from), b = _pmView.domAtPos(sentence.to);
            var range = document.createRange();
            range.setStart(a.node, a.offset);
            range.setEnd(b.node, b.offset);
            return range;
        }

        // ── The large view ──
        // The same graph in a window over the page that leaves the page usable:
        // a bar or a band clicked there acts on the text behind, as in the
        // panel. Drag its title bar to move it; Esc or × closes it.
        function openRhythmDialog() {
            var path = typeof paths !== 'undefined' ? paths[curIdx] : null;
            if (!path) return;
            var dialog = document.getElementById('rhythmDialog');
            if (!dialog) {
                dialog = _rhythmEl('dialog', 'rhythm-dialog');
                dialog.id = 'rhythmDialog';
                dialog.setAttribute('aria-labelledby', 'rhythmDialogTitle');
                var head = _rhythmEl('div', 'rhythm-dialog-head');
                head.title = 'Drag to move; double-click to put it back';
                _rhythmDraggable(dialog, head);
                head.addEventListener('dblclick', function(e) {
                    if (e.target.closest('button')) return;
                    try { localStorage.removeItem(RHYTHM_WINDOW_KEY); } catch (err) {}
                    _rhythmPlace(dialog);
                    refreshSceneRhythm();
                    _rhythmPlace(dialog);
                    _rhythmRoom(dialog);
                });
                // Resized by its corner: the bars take the new height.
                if (typeof ResizeObserver === 'function') {
                    var lastHeight = 0;
                    new ResizeObserver(function() {
                        if (!dialog.open || !dialog.style.height) return;
                        var h = Math.round(dialog.getBoundingClientRect().height);
                        if (h === lastHeight) return;
                        lastHeight = h;
                        _rhythmSaveWindow(dialog);
                        refreshSceneRhythm();
                        _rhythmRoom(dialog);
                    }).observe(dialog);
                }
                var title = _rhythmEl('h2', 'rhythm-dialog-title');
                title.id = 'rhythmDialogTitle';
                var close = _rhythmEl('button', 'ledger-close', '\u00d7');
                close.type = 'button';
                close.setAttribute('aria-label', 'Close');
                close.onclick = closeRhythmDialog;
                head.append(title, close);
                var slot = _rhythmEl('div', 'rhythm');
                slot.id = 'sceneRhythmLarge';
                // Where a band's sentences are listed.
                var detail = _rhythmEl('div', 'rhythm-detail');
                detail.id = 'rhythmDetail';
                detail.setAttribute('aria-live', 'polite');
                dialog.append(head, slot, detail);
                dialog.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape') { e.preventDefault(); closeRhythmDialog(); }
                });
                document.body.appendChild(dialog);
            }
            var m = (typeof meta !== 'undefined' && meta[path]) || {};
            document.getElementById('rhythmDialogTitle').textContent = 'Sentence length \u00b7 ' + (m.title || path);
            if (!dialog.open) {
                _rhythmPick = null;
                // Not modal: the text stays visible and reachable behind it.
                dialog.show();
                // Sized first, so the graph is drawn at that size; placed again
                // once it is in, so it opens wholly on screen.
                _rhythmPlace(dialog);
                refreshSceneRhythm();
                _renderRhythmDetail();
                _rhythmPlace(dialog);
                _rhythmRoom(dialog);
            }
            refreshSceneRhythm();
            _renderRhythmDetail();
            var tab = dialog.querySelector('.rhythm-switch-btn[aria-selected="true"]');
            if (tab) tab.focus({preventScroll: true});
        }

        function closeRhythmDialog() {
            var dialog = document.getElementById('rhythmDialog');
            if (dialog && dialog.open) dialog.close();
            _rhythmRoom(null);
        }

        // While the window is open the reading view gets as much empty space
        // after the scene as the window is tall, so even the last sentences
        // can be brought up clear of it. Space after the text moves nothing.
        function _rhythmRoom(dialog) {
            var body = document.getElementById('modalBody');
            if (!body) return;
            body.style.paddingBottom = dialog ? Math.round(dialog.getBoundingClientRect().height + 24) + 'px' : '';
        }

        function pickRhythm(pick) {
            _rhythmPick = pick;
            document.querySelectorAll('#sceneRhythmLarge .rhythm-bar').forEach(function(bar) {
                bar.classList.toggle('is-picked', !!pick && pick.kind === 'bar' && Number(bar.dataset.index) === pick.index);
            });
            _renderRhythmDetail();
        }

        // The area under the large graph: a band's sentences, each one a way
        // to it in the text.
        function _renderRhythmDetail() {
            var detail = document.getElementById('rhythmDetail');
            if (!detail || !_pmView) return;
            detail.replaceChildren();
            var sentences = sceneSentences(_pmView);
            var pick = _rhythmPick;
            if (!pick || pick.kind !== 'band') {
                detail.appendChild(_rhythmEl('p', 'rhythm-detail-hint',
                    'Click a bar to go to its sentence, or a length band to list its sentences.'));
                return;
            }
            var inBand = [];
            sentences.forEach(function(s, i) { if (_rhythmBucketOf(s.words) === pick.index) inBand.push(i); });
            detail.appendChild(_rhythmEl('p', 'rhythm-detail-meta',
                inBand.length + (inBand.length === 1 ? ' sentence of ' : ' sentences of ') + RHYTHM_BUCKET_LABELS[pick.index] + ' words'));
            var list = _rhythmEl('ol', 'rhythm-detail-list');
            inBand.forEach(function(i) {
                var li = _rhythmEl('li');
                var b = _rhythmEl('button', 'rhythm-detail-item', sentences[i].text);
                b.type = 'button';
                b.onclick = function() { revealSentence(sentences[i]); };
                li.appendChild(b);
                list.appendChild(li);
            });
            detail.appendChild(list);
        }

        // Moves the window by its title bar, kept within the viewport.
        // The bars' height in the large window: what its size leaves for them.
        function _rhythmLargeHeight() {
            var dialog = document.getElementById('rhythmDialog');
            if (!dialog || !dialog.style.height) return RHYTHM_LARGE_HEIGHT;
            // What the window holds besides the bars, measured as drawn now.
            var graph = dialog.querySelector('#sceneRhythmLarge .rhythm-bars, #sceneRhythmLarge .rhythm-spread');
            var last = dialog.lastElementChild;
            var chrome = RHYTHM_WINDOW_CHROME;
            if (graph && last) {
                var top = dialog.getBoundingClientRect().top - dialog.scrollTop;
                var content = last.getBoundingClientRect().bottom - top + parseFloat(getComputedStyle(dialog).paddingBottom || 0);
                chrome = content - graph.getBoundingClientRect().height;
            }
            var h = dialog.clientHeight - chrome;
            return Math.max(80, Math.min(Math.round(h), 900));
        }

        function _rhythmSaveWindow(dialog) {
            var box = dialog.getBoundingClientRect();
            var geometry = {left: box.left, top: box.top};
            if (dialog.style.height) { geometry.width = box.width; geometry.height = box.height; }
            try { localStorage.setItem(RHYTHM_WINDOW_KEY, JSON.stringify(geometry)); } catch (e) {}
        }

        // Where the window opens: where it was left, kept inside the screen,
        // or at the bottom of the screen the first time.
        function _rhythmPlace(dialog) {
            var saved = null;
            try { saved = JSON.parse(localStorage.getItem(RHYTHM_WINDOW_KEY) || 'null'); } catch (e) {}
            ['left', 'top', 'right', 'bottom', 'margin', 'width', 'height'].forEach(function(k) { dialog.style[k] = ''; });
            if (saved && saved.width && saved.height) {
                dialog.style.width = Math.min(saved.width, window.innerWidth - 16) + 'px';
                dialog.style.height = Math.min(saved.height, window.innerHeight - 16) + 'px';
            }
            var box = dialog.getBoundingClientRect();
            var left = saved ? saved.left : box.left, top = saved ? saved.top : box.top;
            dialog.style.margin = '0';
            dialog.style.right = 'auto';
            dialog.style.bottom = 'auto';
            dialog.style.left = Math.max(0, Math.min(left, window.innerWidth - box.width)) + 'px';
            dialog.style.top = Math.max(0, Math.min(top, window.innerHeight - Math.min(box.height, 120))) + 'px';
        }

        function _rhythmDraggable(dialog, handle) {
            handle.addEventListener('pointerdown', function(e) {
                if (e.button !== 0 || e.target.closest('button')) return;
                e.preventDefault();
                var box = dialog.getBoundingClientRect();
                var dx = e.clientX - box.left, dy = e.clientY - box.top;
                dialog.style.margin = '0';
                dialog.style.bottom = 'auto';
                dialog.style.right = 'auto';
                dialog.style.left = box.left + 'px';
                dialog.style.top = box.top + 'px';
                handle.setPointerCapture(e.pointerId);
                function move(ev) {
                    var left = Math.max(0, Math.min(ev.clientX - dx, window.innerWidth - box.width));
                    var top = Math.max(0, Math.min(ev.clientY - dy, window.innerHeight - 40));
                    dialog.style.left = left + 'px';
                    dialog.style.top = top + 'px';
                }
                function up() {
                    handle.removeEventListener('pointermove', move);
                    handle.removeEventListener('pointerup', up);
                    _rhythmSaveWindow(dialog);
                }
                handle.addEventListener('pointermove', move);
                handle.addEventListener('pointerup', up);
            });
        }
