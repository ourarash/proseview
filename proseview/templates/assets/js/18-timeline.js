// ── Timeline tab: shape, threads, chronology ────────────────────────────
// Three layers over `storyModel`, each needing more frontmatter than the
// last. A layer whose data is absent renders a short line saying what it
// would need, and nothing else — never a nag, never an inferred value.

        const STORY_HUES = 8;
        var _timelineBuilt = false;

        function _storyEsc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;')
                .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function _storyChapters() {
            const seen = [];
            for (const s of storyModel.scenes) {
                if (!seen.includes(s.chapter)) seen.push(s.chapter);
            }
            return seen;
        }

        // A frontmatter `chapter: 2` is just "2", which reads as noise beside
        // the other facts. Name it, unless the value already names itself.
        function _storyChapterLabel(value) {
            const text = String(value == null ? '' : value).trim();
            if (!text) return '';
            return /^\d+$/.test(text) ? 'Chapter ' + text : text;
        }

        function _storyCardHtml(scene) {
            const bits = [_storyEsc(_storyChapterLabel(scene.chapter))];
            if (scene.day != null) bits.push(_storyEsc(storyModel.day_field + ' ' + scene.day));
            if (scene.thread) bits.push(_storyEsc(scene.thread));
            bits.push(scene.words.toLocaleString() + ' words');
            let html = '<b>' + _storyEsc(scene.title || scene.path) + '</b>'
                + '<em>' + bits.join(' · ') + '</em>';
            const place = [scene.when, scene.where].filter(Boolean).map(_storyEsc).join(' · ');
            if (place) html += '<em>' + place + '</em>';
            if (scene.blurb) html += '<p>' + _storyEsc(scene.blurb) + '</p>';
            return html;
        }

        var _storyCard = null;

        function _storyCardEl() {
            if (!_storyCard) {
                _storyCard = document.createElement('div');
                _storyCard.id = 'storyCard';
                _storyCard.setAttribute('role', 'tooltip');
                document.body.appendChild(_storyCard);
            }
            return _storyCard;
        }

        function _storyCardShow(scene, event) {
            const card = _storyCardEl();
            card.innerHTML = _storyCardHtml(scene);
            card.classList.add('on');
            const pad = 16;
            const w = card.offsetWidth || 320, h = card.offsetHeight || 120;
            let x = event.clientX + pad, y = event.clientY + pad;
            if (x + w > window.innerWidth - 8) x = event.clientX - w - pad;
            if (y + h > window.innerHeight - 8) y = Math.max(8, event.clientY - h - pad);
            card.style.left = x + 'px';
            card.style.top = y + 'px';
        }

        function _storyCardHide() {
            if (_storyCard) _storyCard.classList.remove('on');
        }

        function _storyEmpty(message) {
            return '<p class="story-empty">' + message + '</p>';
        }

        // ── Layer 1: shape ──────────────────────────────────────────────
        function _renderShape(chapterIndex) {
            const scenes = storyModel.scenes;
            if (!scenes.length) return _storyEmpty('No scenes yet.');
            const total = storyModel.total_words || 1;
            const max = Math.max.apply(null, scenes.map(s => s.words)) || 1;

            const strip = scenes.map(s =>
                '<div class="story-seg" style="flex:' + Math.max(s.words, 1)
                + ';background:var(--story-c' + (chapterIndex[s.chapter] % STORY_HUES) + ')"'
                + ' data-scene="' + s.index + '"></div>').join('');

            const bars = scenes.map(s =>
                '<div class="story-barwrap" data-scene="' + s.index + '">'
                + '<div class="story-bar" style="height:' + (100 * s.words / max).toFixed(2) + '%;'
                + 'background:var(--story-c' + (chapterIndex[s.chapter] % STORY_HUES) + ')"></div></div>').join('');

            const ticks = storyModel.bands.map(b =>
                '<div class="story-tick" style="flex:' + b.scenes + '"><span>' + _storyEsc(_storyChapterLabel(b.chapter))
                + (b.day_span ? ' · ' + _storyEsc(b.day_span) : '') + '</span></div>').join('');

            return '<h3 class="story-h">Proportion of the book</h3>'
                + '<div class="story-strip">' + strip + '</div>'
                + '<h3 class="story-h">Words per scene</h3>'
                + '<div class="story-chart">' + bars + '</div>'
                + '<div class="story-ticks">' + ticks + '</div>'
                + '<p class="story-note">' + scenes.length + ' scenes · '
                + total.toLocaleString() + ' words</p>';
        }

        // ── Layer 2: threads ────────────────────────────────────────────
        function _renderThreads(chapterIndex) {
            if (!storyModel.has_threads) {
                return _storyEmpty('No storylines yet. Add <code>' + storyModel.thread_field
                    + ': &lt;name&gt;</code> to a scene’s frontmatter and its lane appears here.');
            }
            const threads = storyModel.threads;
            const rows = threads.map(function(name, row) {
                const lane = storyModel.scenes.map(function(s) {
                    const on = s.thread === name;
                    return '<div class="story-slot' + (on ? ' on' : '') + '"'
                        + (on ? ' data-scene="' + s.index + '"' : '')
                        + (on ? ' style="background:var(--story-c' + (row % STORY_HUES) + ')"' : '')
                        + '></div>';
                }).join('');
                const count = storyModel.scenes.filter(s => s.thread === name).length;
                return '<div class="story-lane-row"><div class="story-lane-name">'
                    + '<i style="background:var(--story-c' + (row % STORY_HUES) + ')"></i>'
                    + _storyEsc(name) + ' <span>' + count + '</span></div>'
                    + '<div class="story-lane">' + lane + '</div></div>';
            }).join('');

            // Untagged scenes get a lane of their own. Drawn only as gaps in
            // the other lanes they read as a rendering fault rather than as
            // work still to do.
            const untagged = storyModel.scenes.filter(s => !s.thread).length;
            let untaggedRow = '';
            if (untagged) {
                const lane = storyModel.scenes.map(function(s) {
                    const on = !s.thread;
                    return '<div class="story-slot' + (on ? ' none' : '') + '"'
                        + (on ? ' data-scene="' + s.index + '"' : '') + '></div>';
                }).join('');
                untaggedRow = '<div class="story-lane-row story-lane-untagged">'
                    + '<div class="story-lane-name"><i class="story-swatch-none"></i>'
                    + 'no ' + _storyEsc(storyModel.thread_field) + ' <span>' + untagged + '</span></div>'
                    + '<div class="story-lane">' + lane + '</div></div>';
            }
            const foot = untagged
                ? '<p class="story-note">' + untagged + ' of ' + storyModel.scenes.length
                  + ' scenes have no ' + _storyEsc(storyModel.thread_field)
                  + ' yet — hover one to see which.</p>'
                : '<p class="story-note">Every scene belongs to a storyline.</p>';
            return '<h3 class="story-h">Storylines, in reading order</h3>'
                + rows + untaggedRow + foot;
        }

        // ── Layer 3: chronology ─────────────────────────────────────────
        function _renderChronology(chapterIndex) {
            if (!storyModel.has_chronology) {
                return _storyEmpty('No chronology yet. Add <code>' + storyModel.day_field
                    + ': &lt;number&gt;</code> to two or more scenes to compare reading order '
                    + 'with the order events happen.');
            }
            const dated = storyModel.scenes.filter(s => s.day != null);
            const order = storyModel.chronological;
            const byIndex = {};
            storyModel.scenes.forEach(s => { byIndex[s.index] = s; });
            const chrono = order.map(i => byIndex[i]).filter(Boolean);

            const W = 1180, BW = 58, TOP = 26, BOT = 176, H = 250;
            const step = (W - 40) / Math.max(dated.length, 1);
            const readAt = {}, storyAt = {}, readRank = {}, storyRank = {};
            dated.forEach((s, i) => { readAt[s.index] = 20 + i * step; readRank[s.index] = i; });
            chrono.forEach((s, i) => { storyAt[s.index] = 20 + i * step; storyRank[s.index] = i; });
            // "Moved" is measured in scene positions, not pixels, and scales
            // with the manuscript: a one-slot swap is noise in a long book and
            // a third of a short one.
            const jumpBy = Math.max(2, Math.ceil(dated.length * 0.15));
            const movedAway = s => Math.abs(readRank[s.index] - storyRank[s.index]) >= jumpBy;

            let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="story-svg" role="img" '
                + 'aria-label="Reading order compared with story order">';
            dated.forEach(function(s) {
                const x1 = readAt[s.index] + BW / 2, x2 = storyAt[s.index] + BW / 2;
                const moved = movedAway(s);
                svg += '<path d="M' + x1.toFixed(1) + ',74 C' + x1.toFixed(1) + ',130 '
                    + x2.toFixed(1) + ',120 ' + x2.toFixed(1) + ',' + BOT + '" fill="none" '
                    + 'stroke="var(--story-c' + (chapterIndex[s.chapter] % STORY_HUES) + ')" '
                    + 'stroke-width="' + (moved ? 2.4 : 1.2) + '" opacity="' + (moved ? 0.95 : 0.4) + '"/>';
            });
            [[dated, TOP], [chrono, BOT]].forEach(function(pair) {
                const arr = pair[0], y = pair[1];
                arr.forEach(function(s, i) {
                    const x = 20 + i * step;
                    svg += '<g data-scene="' + s.index + '" class="story-node">'
                        + '<rect x="' + x.toFixed(1) + '" y="' + y + '" width="' + BW + '" height="48" rx="5" '
                        + 'fill="var(--story-c' + (chapterIndex[s.chapter] % STORY_HUES) + ')"/>'
                        + '<text x="' + (x + BW / 2).toFixed(1) + '" y="' + (y + 20) + '" text-anchor="middle" '
                        + 'font-size="11" fill="#fff" font-weight="600">' + s.day + '</text>'
                        + '<text x="' + (x + BW / 2).toFixed(1) + '" y="' + (y + 36) + '" text-anchor="middle" '
                        + 'font-size="9" fill="#fff" opacity=".85">'
                        + _storyEsc(String(s.chapter).slice(0, 9)) + '</text></g>';
                });
            });
            svg += '</svg>';

            const moved = dated.filter(movedAway);
            const foot = moved.length
                ? '<p class="story-note"><b>' + moved.length + ' scene'
                  + (moved.length === 1 ? '' : 's') + '</b> read far from where they happen: '
                  + moved.map(s => _storyEsc(s.title || s.path)).join(', ') + '.</p>'
                : '<p class="story-note">Every dated scene is read in the order it happens.</p>';

            return '<h3 class="story-h">Reading order vs story order</h3>'
                + '<p class="story-sub">Top row is the order a reader meets these ' + dated.length
                + ' scenes. Bottom row is the order the events happen. Thick lines are the jumps.</p>'
                + '<div class="story-scroll">' + svg + '</div>' + foot;
        }

        function buildTimelineTab() {
            if (_timelineBuilt) return;
            const host = document.getElementById('timelineContent');
            if (!host || typeof storyModel !== 'object' || !storyModel) return;
            const chapters = _storyChapters();
            const chapterIndex = {};
            chapters.forEach((c, i) => { chapterIndex[c] = i; });

            host.innerHTML =
                '<div class="story-section">' + _renderShape(chapterIndex) + '</div>'
                + '<div class="story-section">' + _renderThreads(chapterIndex) + '</div>'
                + '<div class="story-section">' + _renderChronology(chapterIndex) + '</div>';

            // Any marked element opens its scene, so the views are navigation
            // as well as diagnosis.
            host.querySelectorAll('[data-scene]').forEach(function(el) {
                const scene = storyModel.scenes[+el.dataset.scene];
                if (!scene) return;
                el.style.cursor = 'pointer';
                el.addEventListener('mousemove', function(e) { _storyCardShow(scene, e); });
                el.addEventListener('mouseleave', _storyCardHide);
                el.addEventListener('click', function() {
                    _storyCardHide();
                    if (typeof openSceneModal === 'function') openSceneModal(scene.path);
                });
            });
            // A scroll or a tab change must not strand the card on screen.
            window.addEventListener('scroll', _storyCardHide, { passive: true });
            _timelineBuilt = true;
        }

        function refreshTimelineTab() {
            _timelineBuilt = false;
            if (currentTab === 'timeline') buildTimelineTab();
        }
