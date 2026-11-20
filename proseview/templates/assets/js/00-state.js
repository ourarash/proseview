let currentTab = 'overview';
        let suppressHashWrite = false;
        const VALID_TABS = ['overview', 'analysis', 'timeline', 'tasks'];

        // TODOs and Notes were two tabs before they became Tasks; their old
        // links still land there. Settings is a dialog over the current tab,
        // and its old link opens it.
        function canonicalTab(name) {
            if (name === 'todos' || name === 'notes') return 'tasks';
            if (name === 'settings') return 'settings';
            return VALID_TABS.includes(name) ? name : 'overview';
        }

        // Headers for every state-changing request. The session token is the
        // only thing separating this page from any other site the user has
        // open: the server rejects mutations without it, and a cross-origin
        // caller cannot set a custom header without a preflight we refuse.
        function pvHeaders() {
            return {
                'Content-Type': 'application/json',
                'X-Proseview-Session': pageSessionToken,
            };
        }

        // Global toast notification helper. Defined early so all modules
        // can notify the user without falling back to modal alert() dialogs.
        function sidebarShowToast(message, isError) {
            var toast = document.getElementById('sidebarFileToast');
            if (!toast || !message) return;
            toast.setAttribute('role', isError ? 'alert' : 'status');
            toast.textContent = message;
            toast.hidden = false;
            if (message.indexOf('Proseview was restarted') !== -1 && typeof showAssetReloadBanner === 'function') {
                showAssetReloadBanner('Proseview was restarted. Reload the page to continue.');
            }
            clearTimeout(sidebarShowToast._timer);
            sidebarShowToast._timer = setTimeout(function() { toast.hidden = true; }, 6000);
        }
        window.sidebarShowToast = sidebarShowToast;

        // EventSource cannot send the custom header used by mutations. Carry
        // the same per-run token in its URL so a replacement server can answer
        // stale tabs with 204 and make their automatic reconnects stop.
        function pvEventSourceUrl(path) {
            const separator = path.includes('?') ? '&' : '?';
            return path + separator + 'session=' + encodeURIComponent(pageSessionToken);
        }

        const PASS_LABELS = {
            passive_voice: 'Passive Voice',
            filter_verbs: 'Filter Verbs',
            crutch_words: 'Crutch Words',
            hyperbole: 'Hyperbole',
            lyrical: 'Lyrical',
            sensory: 'Sensory',
            sentence_starts: 'Sentence Openings',
            repeats: 'Repeats',
            first_person: 'First Person',
            echoes: 'Echoes',
            sticky_sentences: 'Sticky Sentences',
            dialogue_tags: 'Dialogue Tags',
            dialogue: 'Dialogue'
        };
        const PASS_CLASSES = {
            passive_voice: 'hl-passive',
            filter_verbs: 'hl-filter',
            crutch_words: 'hl-crutch',
            hyperbole: 'hl-hyperbole',
            lyrical: 'hl-lyrical',
            sensory: 'hl-sensory',
            sentence_starts: 'hl-openings',
            repeats: 'hl-repeat',
            first_person: 'hl-first-person',
            echoes: 'hl-echo',
            sticky_sentences: 'hl-sticky',
            dialogue_tags: 'hl-dialogue-tag',
            dialogue: 'hl-dialogue'
        };
        // Every pass carries a line of examples rather than a definition:
        // "felt, saw, heard, noticed" says what Filter Verbs are faster than a
        // sentence can, and it survives on a touch screen where a tooltip does
        // not. A name alone can mislead -- Lyrical is simile markers -- which is
        // the case for showing the vocabulary rather than the label alone.
        const PASS_EXAMPLES = {
            repeats: 'words this scene leans on',
            first_person: 'I, me, my, myself',
            sentence_starts: 'She… She… She…',
            crutch_words: 'just, really, quite, actually',
            lyrical: 'like, as, seemed, became',
            filter_verbs: 'felt, saw, heard, noticed',
            hyperbole: 'always, never, everything',
            sensory: 'sight, sound, smell, touch, taste',
            passive_voice: 'was written, is known',
            echoes: 'walked … walking, close together',
            sticky_sentences: 'the, of, in, her, over 60%',
            dialogue_tags: 'she cried, said sternly, she smiled',
            dialogue: 'everything in quotes'
        };
        // The one explanation of each check: what it marks, and why it might
        // matter. The check's ⓘ and a mark's click card both show it.
        const PASS_NOTES = {
            repeats: "Marks the content words this scene uses most (\u201cthe\u201d, \u201cand\u201d and the like are left out), with every form of a word counted together: \u201cblock\u201d and \u201cblocks\u201d are one. Repeating a word on purpose builds rhythm; repeating it by accident is what readers notice. The small 2/6 on each says which use of the word it is and how many the scene has; click one for how many are in its paragraph, or point at it to light its other uses. Swap some for a synonym or a pronoun, or cut them.",
            first_person: 'Marks I, me, my, mine and myself in the narration of a third-person scene, where they can mean the narrator has slipped into the character’s voice. Dialogue is skipped, and so is a scene told in first person (its pov: says first, or its narration plainly is).',
            sentence_starts: 'Marks three or more sentences in a row that begin with the same word (She… She… She…), counting across paragraph breaks. Readers hear the pattern even when they can’t name it. Vary the openings: start with an action, a detail, or a clause.',
            crutch_words: 'Marks, outside dialogue, filler words that rarely add meaning: just, very, really, quite, rather, pretty, somewhat, slightly, somehow, suddenly, actually, basically, essentially, literally, indeed. Read the sentence without the word. If it means the same, delete it; if it goes flat, pick a stronger verb or adjective instead (“very cold” → “freezing”).',
            lyrical: 'Marks words that signal a comparison or a change: like, as, seemed, became, transformed, shimmered, bloomed, dissolved, echoed. They show how much figurative language the scene carries. “As” and “like” also have plain uses, so not every mark is a simile.',
            filter_verbs: 'Marks verbs of perceiving and thinking: saw, heard, felt, noticed, thought, knew, wondered, realized, seemed, looked, watched. They report that the character perceived something instead of showing the thing itself. Try cutting the verb: “she saw the door open” → “the door opened”.',
            hyperbole: 'Marks, outside dialogue, absolute words: never, always, forever, perfect, impossible, utterly, completely, entirely, absolute, totally, worst, best, everything, nothing. Used often, they stop carrying weight and can read as exaggeration. Keep the ones you mean literally; soften or cut the rest.',
            sensory: 'Marks words tied to one of the five senses: sight, sound, smell, touch and taste. Click a mark to see which sense. Useful for spotting a scene that leans on sight alone.',
            passive_voice: 'Marks a form of “to be” followed by a past participle, as in “the letter was written”. Passive hides who did the action. That is sometimes what you want, but a scene full of it feels static. Try naming who acted: “she wrote the letter”.',
            echoes: 'Marks words that come back within 50 words of each other, counting their forms (walk, walked), every one of them. The small 2/3 on each says which word of its echo it is and how many it has; the first is lighter, and pointing at one lights its partners. Names and everyday words like time or enough are skipped. The count is of echoes, not of words.',
            sticky_sentences: 'Marks sentences of 10+ words where more than 60% are glue words like the, of, in, her. They carry little meaning, so the sentence takes longer to get somewhere.',
            dialogue_tags: 'Marks the \u201cshe said\u201d next to dialogue when it uses a verb other than said or asked, has an adverb, uses a non-speech verb like smiled, or when 6+ lines go by with no tag. Fancy tags aren\u2019t wrong; this shows where you use them.',
            dialogue: 'Tints everything inside quotation marks ("\u2026", \u201c\u2026\u201d and \u2018\u2026\u2019), which is what the Dialogue % counts. Apostrophes are not quotes, and speech left open at a paragraph\u2019s end runs to its end. Straight single quotes are not counted, since they can\u2019t be told from apostrophes.'
        };

        // A pass whose marks come in kinds lists a count of each under its row
        // while it is on. A mark is of a kind when its note contains the
        // kind's `match`, which mirrors DIALOGUE_TAG_NOTES in highlights.py.
        const PASS_BREAKDOWNS = {
            dialogue_tags: [
                // A phrase like "in a sad little voice" counts with the adverbs.
                {label: 'Adverb on a tag', match: ['Adverb on a dialogue tag', 'Describes how it was said']},
                {label: 'Other than said or asked', match: 'Other than said or asked'},
                {label: 'Not a speech verb', match: 'Not a speech verb'},
                {label: '6+ lines with no tag', match: 'lines in a row with no tag'}
            ]
        };

        const THEME_STORAGE_KEY = 'proseview-theme';
        const THEME_ORDER = ['light', 'dark', 'docsify', 'hopscotch', 'graphite-light', 'graphite-dark'];
        // What a first visit opens in: light, which most people new to the
        // app expect. A theme picked once in Settings is kept. The <html>
        // attribute and the pre-paint bootstrap in index.html.j2 repeat it;
        // test_themes.py keeps all three in step.
        const DEFAULT_THEME = 'graphite-light';
        const THEME_LABELS = {
            light: 'Light',
            dark: 'Dark',
            docsify: 'Docsify',
            hopscotch: 'Hopscotch',
            'graphite-light': 'Graphite Light',
            'graphite-dark': 'Graphite Dark'
        };
        const FONT_STORAGE_KEY = 'proseview-font';
        const MODAL_FONT_SIZE_STORAGE_KEY = 'proseview-modal-font-size';
        const MODAL_FONT_SIZE_DEFAULT = 18;
        const MODAL_FONT_SIZE_MIN = 12;
        const MODAL_FONT_SIZE_MAX = 36;
        // Measure, not margins: the reading column is centred, so the only
        // real variable is how wide the text is. Stored in px but shown to the
        // reader as characters per line, which is the number that means
        // something when choosing a comfortable measure.
        const READING_MEASURE_STORAGE_KEY = 'proseview-reading-measure';
        const READING_MEASURE_DEFAULT = 760;
        const READING_MEASURE_MIN = 480;
        const READING_MEASURE_MAX = 1100;
        const VIEW_SCROLL_STORAGE_PREFIX = 'proseview-scroll:';
        const HIGHLIGHTS_STORAGE_KEY = 'proseview-highlights';
        const FONT_ORDER = ['reader', 'literary', 'inter', 'georgia', 'baskerville', 'sans', 'mono'];
        const FONT_LABELS = { reader: 'Reader', literary: 'Literary', inter: 'Inter', georgia: 'Georgia', baskerville: 'Baskerville', sans: 'Sans', mono: 'Mono' };
        const chartRefs = {};
        let curIdx = -1;
        let hls = {};
        PASS_ORDER.forEach(p => hls[p] = false);
        let scrollSaveQueued = false;
        let routeHydrating = false;

        // The dock and the reading column compete for the same pixels. Rather
        // than pick a breakpoint, ask whether the prose can still hold the
        // measure the reader chose: if splitting the viewport would squeeze it
        // below that, the dock overlays instead of docking. A reader on a
        // 1280px laptop who has asked for a wide measure gets the overlay; one
        // on the same screen reading narrow keeps the split view.
        const OVERLAY_MIN_PROSE_WIDTH = 420;

        function _dockWouldCrushTheProse(logicalViewportWidth) {
            if (!document.body.classList.contains('discuss-open')) return false;
            const dock = Math.min(
                parseFloat(getComputedStyle(document.documentElement)
                    .getPropertyValue('--utility-dock-w')) || 420,
                logicalViewportWidth / 2
            );
            const measure = typeof storedReadingMeasure === 'function'
                ? storedReadingMeasure() : READING_MEASURE_DEFAULT;
            // 48px of gutter is the least the reading column looks deliberate in.
            const wanted = Math.min(measure, OVERLAY_MIN_PROSE_WIDTH) + 48;
            return logicalViewportWidth - dock < wanted;
        }

        function syncCssZoomViewport() {
            const root = document.documentElement;
            const body = document.body;
            if (!body) return;
            const zoom = parseFloat(getComputedStyle(body).zoom) || 1;
            if (zoom <= 1) {
                delete root.dataset.cssZoom;
                const width = window.innerWidth;
                if (_dockWouldCrushTheProse(width)) {
                    root.dataset.utilityOverlay = 'true';
                    root.style.setProperty('--css-zoom-body-width', Math.max(220, width) + 'px');
                    root.style.setProperty('--css-zoom-dock-width', Math.max(220, width) + 'px');
                } else {
                    delete root.dataset.utilityOverlay;
                    root.style.removeProperty('--css-zoom-body-width');
                    root.style.removeProperty('--css-zoom-dock-width');
                }
                window.dispatchEvent(new Event('proseview:workspace-metrics'));
                return;
            }
            const logicalViewportWidth = window.innerWidth / zoom;
            // At browser text zoom the sidebar is responsively retracted in
            // CSS, so the reader owns the full logical viewport. Subtracting
            // the hidden sidebar here made the scene toolbar wrap into three
            // rows at 200% zoom.
            const sidebarWidth = 0;
            root.dataset.cssZoom = 'true';
            if (logicalViewportWidth < 700) root.dataset.utilityOverlay = 'true';
            else delete root.dataset.utilityOverlay;
            root.style.setProperty(
                '--css-zoom-body-width',
                Math.max(220, logicalViewportWidth - sidebarWidth) + 'px'
            );
            root.style.setProperty(
                '--css-zoom-dock-width',
                Math.max(220, logicalViewportWidth < 700 ? logicalViewportWidth : logicalViewportWidth / 2) + 'px'
            );
            window.dispatchEvent(new Event('proseview:workspace-metrics'));
        }

        (function observeCssZoomViewport() {
            syncCssZoomViewport();
            window.addEventListener('resize', syncCssZoomViewport);
            if (window.visualViewport) window.visualViewport.addEventListener('resize', syncCssZoomViewport);
            // "class" is in here because opening the dock is a class change on
            // body, and whether the dock overlays depends on it being open.
            new MutationObserver(syncCssZoomViewport).observe(document.body, {
                attributes: true,
                attributeFilter: ['style', 'class'],
            });
            new MutationObserver(syncCssZoomViewport).observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-sidebar'],
            });
        })();

        function syncSidebarInteractiveState() {
            const root = document.documentElement;
            const sidebar = document.getElementById('repoSidebar');
            if (!sidebar) return;
            const utilityDockOpen = document.body.classList.contains('discuss-open');
            const compactDock = utilityDockOpen && window.matchMedia('(max-width: 1120px)').matches;
            const responsivelyRetracted = window.matchMedia('(max-width: 700px)').matches
                || root.dataset.cssZoom === 'true'
                || compactDock;
            const hidden = root.dataset.sidebar === 'closed' || responsivelyRetracted;
            sidebar.inert = hidden;
        }

        (function observeSidebarInteractiveState() {
            syncSidebarInteractiveState();
            window.addEventListener('resize', syncSidebarInteractiveState);
            window.addEventListener('proseview:workspace-metrics', syncSidebarInteractiveState);
            new MutationObserver(syncSidebarInteractiveState).observe(document.body, {
                attributes: true,
                attributeFilter: ['class'],
            });
            new MutationObserver(syncSidebarInteractiveState).observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-sidebar', 'data-css-zoom'],
            });
        })();

        function workspaceZoomFactor() {
            return Math.max(1, parseFloat(getComputedStyle(document.body).zoom) || 1);
        }

        function workspaceLogicalViewportWidth() {
            return (document.documentElement.clientWidth || window.innerWidth) / workspaceZoomFactor();
        }

        function workspaceDockWidthBounds(minWidth) {
            const viewportWidth = workspaceLogicalViewportWidth();
            const zoomed = document.documentElement.dataset.cssZoom === 'true';
            const compact = !zoomed && viewportWidth <= 1120;
            const sidebar = document.getElementById('repoSidebar');
            const sidebarReserved = !compact && !zoomed && document.documentElement.dataset.sidebar !== 'closed' && sidebar
                ? sidebar.getBoundingClientRect().width / workspaceZoomFactor() + 10
                : 0;
            const minimumWritingWidth = viewportWidth < 700
                ? Math.max(180, viewportWidth * 0.375)
                : Math.min(480, Math.max(320, viewportWidth * 0.4));
            let maximum = Math.max(220, Math.floor(viewportWidth - sidebarReserved - minimumWritingWidth));
            if (compact) maximum = Math.min(maximum, Math.floor(viewportWidth / 2));
            return {
                min: Math.min(minWidth, maximum),
                max: Math.max(Math.min(minWidth, maximum), maximum)
            };
        }

        function workspaceSidebarWidthBounds() {
            const minimum = 160;
            const maximum = Math.max(minimum, Math.min(520, Math.floor(workspaceLogicalViewportWidth() - 370)));
            return {min: minimum, max: maximum};
        }

        function updateSeparatorValue(handle, value, minimum, maximum) {
            if (!handle) return;
            handle.setAttribute('aria-valuemin', String(Math.round(minimum)));
            handle.setAttribute('aria-valuemax', String(Math.round(maximum)));
            handle.setAttribute('aria-valuenow', String(Math.round(value)));
        }

        var _pmView = null;
        // The editor state each scene was last left in, undo history and all,
        // so saving or leaving edit mode does not forget what Cmd+Z can undo.
        var _pmUndoStates = {};
        var _pmViewPath = null;
        var _pmEditMode = false;
        var _pmOpenMtime = null;
        var _pmDirty = false;
        var _pmSavedFlashTimer = null;
        var _pmConflictDraft = null;
        var _pmSaveInFlight = false;
        var _pmSourceBlocks = null;
        var _pmLastCaret = null;
        // The frontmatter as typed in edit mode, or null when it is untouched.
        var _pmFrontmatterDraft = null;
        // Until when a scroll of the reading column is Proseview keeping the
        // page still, not the writer: the toolbar does not hide or show for it.
        var _sceneScrollIsOursUntil = 0;
        // Set when a frontmatter save changed story fields the dashboard shows
        // (status, chapter, timeline); going back to the dashboard reloads it.
        var _dashboardStale = false;

        // Reload into the dashboard when its data is out of date; true if so.
        function reloadIfDashboardStale() {
            if (!_dashboardStale) return false;
            _dashboardStale = false;
            location.reload();
            return true;
        }
        // Counts SSE reload events we expect to be triggered by our own
        // /save-scene calls. Decremented (with a tail timeout) when the
        // event arrives, so reloadOrDefer can skip the page reload our
        // own save would otherwise cause.
        var _pendingSelfReloads = 0;
        var _pendingSelfReloadTimer = null;

        var LABEL_MODE_STORAGE_KEY = 'proseview-label-colors';
        var LABEL_MODES = ['subtle', 'rows', 'off'];
        var DEFAULT_LABEL_MODE = 'subtle';
        var LABEL_COLOR_NAMES = ['blue', 'orange', 'teal', 'amber', 'pink', 'green', 'purple', 'red'];

        function _labelColorTitle(idxOrName) {
            var s = typeof idxOrName === 'number' ? (LABEL_COLOR_NAMES[idxOrName] || '') : String(idxOrName || '');
            return s ? (s.charAt(0).toUpperCase() + s.slice(1)) : '';
        }

        function labelColorDisplayName(slot, isConfigured) {
            var base = '';
            if (typeof slot === 'number' && slot >= 0 && slot < LABEL_COLOR_NAMES.length) {
                base = _labelColorTitle(slot);
            } else if (typeof slot === 'string' && slot.indexOf('#') === 0) {
                base = slot.toLowerCase();
            } else if (slot === 'other') {
                base = 'Neutral';
            }
            if (!base) return 'Auto';
            return isConfigured ? base : ('Auto · ' + base);
        }

        function currentLabelColorMode() {
            var mode = document.documentElement.dataset.labelMode;
            return LABEL_MODES.indexOf(mode) >= 0 ? mode : DEFAULT_LABEL_MODE;
        }

        function syncLabelColorMode() {
            var mode = currentLabelColorMode();
            document.documentElement.dataset.labelMode = mode;
            var select = document.getElementById('setting_label_mode');
            if (select) select.value = mode;
        }

        function selectLabelColorMode(mode) {
            if (LABEL_MODES.indexOf(mode) < 0) return;
            document.documentElement.dataset.labelMode = mode;
            try { localStorage.setItem(LABEL_MODE_STORAGE_KEY, mode); } catch (err) {}
            syncLabelColorMode();
        }

        function labelColorCssExpr(slot) {
            if (slot === 'other') return 'var(--accent-neutral)';
            if (typeof slot === 'number' && slot >= 0 && slot < 8) return 'var(--story-c' + slot + ')';
            if (typeof slot === 'string' && /^[0-7]$/.test(slot)) return 'var(--story-c' + slot + ')';
            if (typeof slot === 'string' && /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(slot)) return slot;
            return '';
        }

        function _resolveSlotHex(slot) {
            if (typeof slot === 'string' && /^#[0-9a-f]{6}$/i.test(slot)) return slot.toLowerCase();
            var idx = (typeof slot === 'number' && slot >= 0 && slot < 8) ? slot
                : (typeof slot === 'string' && /^[0-7]$/.test(slot) ? Number(slot) : -1);
            var val = idx >= 0
                ? getComputedStyle(document.documentElement).getPropertyValue('--story-c' + idx).trim()
                : '';
            if (/^#[0-9a-f]{6}$/i.test(val)) return val.toLowerCase();
            if (/^#[0-9a-f]{3}$/i.test(val)) {
                return '#' + val[1] + val[1] + val[2] + val[2] + val[3] + val[3];
            }
            return '#2a78d6';
        }

        function recomputeClientLabelSlots() {
            if (typeof paths === 'undefined' || typeof meta === 'undefined') return;
            var configured = {};
            var used = {};
            var prevCatalog = (typeof storyModel === 'object' && storyModel && Array.isArray(storyModel.label_catalog))
                ? storyModel.label_catalog : [];
            prevCatalog.forEach(function(entry) {
                if (!entry || !entry.configured || !entry.label) return;
                if (typeof entry.slot === 'number' && entry.slot >= 0 && entry.slot < 8) {
                    configured[entry.label] = entry.slot;
                    used[entry.slot] = true;
                } else if (typeof entry.slot === 'string' && entry.slot.indexOf('#') === 0) {
                    configured[entry.label] = entry.slot;
                }
            });
            var slotByLabel = Object.assign({}, configured);
            var counts = {};
            var ordered = [];
            paths.forEach(function(p) {
                var m = meta[p];
                var lbl = m && m.label ? String(m.label).trim() : '';
                if (!lbl) return;
                counts[lbl] = (counts[lbl] || 0) + 1;
                if (ordered.indexOf(lbl) < 0) ordered.push(lbl);
                if (!Object.prototype.hasOwnProperty.call(slotByLabel, lbl)) {
                    var assigned = 'other';
                    for (var i = 0; i < 8; i++) {
                        if (!used[i]) {
                            assigned = i;
                            used[i] = true;
                            break;
                        }
                    }
                    slotByLabel[lbl] = assigned;
                }
            });
            Object.keys(configured).forEach(function(name) {
                if (ordered.indexOf(name) < 0) ordered.push(name);
            });
            paths.forEach(function(p) {
                var m = meta[p];
                if (!m) return;
                var lbl = m.label ? String(m.label).trim() : '';
                m.label_slot = lbl ? slotByLabel[lbl] : null;
            });
            if (typeof storyModel === 'object' && storyModel) {
                storyModel.label_catalog = ordered.map(function(lbl) {
                    return {
                        label: lbl,
                        slot: slotByLabel[lbl],
                        count: counts[lbl] || 0,
                        configured: Object.prototype.hasOwnProperty.call(configured, lbl)
                    };
                });
                storyModel.labels = ordered.slice();
                storyModel.has_labels = paths.some(function(p) { return !!(meta[p] && meta[p].label); });
                if (Array.isArray(storyModel.scenes)) {
                    storyModel.scenes.forEach(function(s) {
                        var m = meta[s.path];
                        if (!m) return;
                        s.label = m.label || '';
                        s.label_slot = m.label_slot;
                    });
                }
            }
        }

        function syncAllLabelSurfaces(activeScenePath) {
            if (typeof syncSidebarLabels === 'function') syncSidebarLabels();
            if (typeof syncOverviewTableLabels === 'function') syncOverviewTableLabels();
            if (typeof syncOverviewLabelFilter === 'function') syncOverviewLabelFilter();
            if (typeof syncBookLabels === 'function') syncBookLabels();
            var grid = document.getElementById('sceneCardsGrid');
            if (grid && grid.childNodes.length && typeof window.renderOverviewSceneCards === 'function') {
                window.renderOverviewSceneCards();
            }
            if (typeof refreshTimelineTab === 'function') refreshTimelineTab();
            if (typeof renderSettingsLabelColors === 'function') renderSettingsLabelColors();
            if (activeScenePath && typeof renderSceneFrontmatter === 'function'
                && typeof paths !== 'undefined' && typeof curIdx === 'number' && paths[curIdx] === activeScenePath) {
                renderSceneFrontmatter(activeScenePath);
            }
        }

        function saveLabelColorChoice(labelName, colorTokenOrHex, onDone) {
            var clean = String(labelName || '').trim();
            if (!clean) return;
            var payloadVal = colorTokenOrHex ? String(colorTokenOrHex).trim() : null;
            _pendingSelfReloads++;
            if (_pendingSelfReloadTimer) clearTimeout(_pendingSelfReloadTimer);
            _pendingSelfReloadTimer = setTimeout(function() {
                _pendingSelfReloads = 0;
                _pendingSelfReloadTimer = null;
            }, 4000);

            var bodyObj = { label_color: {} };
            bodyObj.label_color[clean] = payloadVal;
            fetch('/api/settings', {
                method: 'PATCH',
                headers: pvHeaders(),
                body: JSON.stringify(bodyObj)
            }).then(function(r) {
                return r.json();
            }).then(function(data) {
                if (!data || data.ok === false) {
                    throw new Error((data && data.error) || 'Could not update label color');
                }
                if (Array.isArray(data.label_catalog) && typeof storyModel === 'object' && storyModel) {
                    storyModel.label_catalog = data.label_catalog;
                } else if (typeof storyModel === 'object' && storyModel && Array.isArray(storyModel.label_catalog)) {
                    var entry = storyModel.label_catalog.find(function(e) { return e && e.label === clean; });
                    if (entry) {
                        var low = payloadVal ? payloadVal.toLowerCase() : '';
                        var namedIdx = LABEL_COLOR_NAMES.indexOf(low);
                        if (!payloadVal) {
                            entry.configured = false;
                            delete entry.slot;
                        } else if (namedIdx >= 0) {
                            entry.configured = true;
                            entry.slot = namedIdx;
                        } else if (/^c([0-7])$/.test(low)) {
                            entry.configured = true;
                            entry.slot = Number(low.slice(1));
                        } else {
                            entry.configured = true;
                            entry.slot = low;
                        }
                    }
                }
                recomputeClientLabelSlots();
                var openPath = (document.documentElement.dataset.view === 'scene'
                    && typeof paths !== 'undefined' && typeof curIdx === 'number' && curIdx >= 0)
                    ? paths[curIdx] : null;
                syncAllLabelSurfaces(openPath);
                if (typeof onDone === 'function') onDone();
            }).catch(function(err) {
                if (typeof sidebarShowToast === 'function') {
                    sidebarShowToast('Color update failed: ' + ((err && err.message) || 'unknown error'), true);
                }
            });
        }

        function buildLabelColorPickerStrip(labelName, currentSlot, isConfigured, onUpdated) {
            var strip = document.createElement('div');
            strip.className = 'label-color-strip';
            strip.addEventListener('click', function(ev) { ev.stopPropagation(); });

            for (var i = 0; i < 8; i++) {
                (function(idx) {
                    var colorName = LABEL_COLOR_NAMES[idx] || ('c' + idx);
                    var colorTitle = _labelColorTitle(colorName);
                    var sw = document.createElement('button');
                    sw.type = 'button';
                    sw.className = 'label-color-swatch' + (currentSlot === idx ? ' is-active' : '');
                    sw.style.setProperty('--swatch-color', 'var(--story-c' + idx + ')');
                    sw.title = colorTitle;
                    sw.setAttribute('aria-label', 'Set ' + labelName + ' color to ' + colorName);
                    sw.addEventListener('click', function(ev) {
                        ev.stopPropagation();
                        saveLabelColorChoice(labelName, colorName, onUpdated);
                    });
                    strip.appendChild(sw);
                })(i);
            }

            var isCustomHex = typeof currentSlot === 'string' && currentSlot.indexOf('#') === 0;
            var wellWrap = document.createElement('label');
            wellWrap.className = 'label-color-well-wrap' + (isCustomHex ? ' is-active' : '');
            wellWrap.title = 'Pick any custom color';
            var wheel = document.createElement('span');
            wheel.className = 'label-color-wheel';
            wheel.setAttribute('aria-hidden', 'true');
            if (isCustomHex) wheel.style.background = currentSlot;
            var wellText = document.createElement('span');
            wellText.className = 'label-color-custom-text';
            wellText.textContent = 'Custom\u2026';
            var well = document.createElement('input');
            well.type = 'color';
            well.className = 'label-color-well';
            well.value = _resolveSlotHex(currentSlot);
            well.setAttribute('aria-label', 'Custom color for ' + labelName);
            well.addEventListener('click', function(ev) { ev.stopPropagation(); });
            well.addEventListener('change', function(ev) {
                ev.stopPropagation();
                saveLabelColorChoice(labelName, well.value, onUpdated);
            });
            wellWrap.append(wheel, wellText, well);
            strip.appendChild(wellWrap);

            if (isConfigured) {
                var reset = document.createElement('button');
                reset.type = 'button';
                reset.className = 'label-color-auto-btn';
                reset.textContent = 'Auto';
                reset.title = 'Reset to automatic color';
                reset.addEventListener('click', function(ev) {
                    ev.stopPropagation();
                    saveLabelColorChoice(labelName, null, onUpdated);
                });
                strip.appendChild(reset);
            }

            return strip;
        }

        function _applyServerLabelMutation(payload, refreshScenesFromDisk) {
            if (typeof _pmEditMode !== 'undefined' && _pmEditMode && typeof _pmDirty !== 'undefined' && _pmDirty && refreshScenesFromDisk) {
                if (typeof sidebarShowToast === 'function') {
                    sidebarShowToast('Save or cancel your open scene edits before renaming or removing a label.', true);
                }
                return Promise.resolve(false);
            }
            _pendingSelfReloads++;
            if (_pendingSelfReloadTimer) clearTimeout(_pendingSelfReloadTimer);
            _pendingSelfReloadTimer = setTimeout(function() {
                _pendingSelfReloads = 0;
                _pendingSelfReloadTimer = null;
            }, 4000);

            return fetch('/api/settings', {
                method: 'PATCH',
                headers: pvHeaders(),
                body: JSON.stringify(payload)
            }).then(function(r) {
                return r.json();
            }).then(function(data) {
                if (!data || data.ok === false) {
                    throw new Error((data && data.error) || 'Could not update labels');
                }
                if (Array.isArray(data.label_catalog) && typeof storyModel === 'object' && storyModel) {
                    storyModel.label_catalog = data.label_catalog;
                }
                if (!refreshScenesFromDisk) {
                    recomputeClientLabelSlots();
                    var openPath = (document.documentElement.dataset.view === 'scene'
                        && typeof paths !== 'undefined' && typeof curIdx === 'number' && curIdx >= 0)
                        ? paths[curIdx] : null;
                    syncAllLabelSurfaces(openPath);
                    return true;
                }
                return fetch('/data.json', { cache: 'no-store' }).then(function(r) {
                    return r.ok ? r.json() : null;
                }).then(function(fresh) {
                    if (fresh && fresh.meta && typeof meta === 'object' && meta) {
                        Object.keys(fresh.meta).forEach(function(p) {
                            meta[p] = fresh.meta[p];
                        });
                    }
                    recomputeClientLabelSlots();
                    var openPath = (document.documentElement.dataset.view === 'scene'
                        && typeof paths !== 'undefined' && typeof curIdx === 'number' && curIdx >= 0)
                        ? paths[curIdx] : null;
                    syncAllLabelSurfaces(openPath);
                    return true;
                });
            }).catch(function(err) {
                if (typeof sidebarShowToast === 'function') {
                    sidebarShowToast('Label update failed: ' + ((err && err.message) || 'unknown error'), true);
                }
                return false;
            });
        }

        var _settingsLabelUiState = { renaming: null, confirmingRemove: null };

        function renderSettingsLabelColors() {
            var row = document.getElementById('settingsLabelPaletteRow');
            var list = document.getElementById('settingsLabelPaletteList');
            if (!row || !list) return;
            row.hidden = false;
            var catalog = (typeof storyModel === 'object' && storyModel && Array.isArray(storyModel.label_catalog))
                ? storyModel.label_catalog : [];
            list.replaceChildren();

            catalog.forEach(function(entry) {
                if (!entry || !entry.label) return;
                var item = document.createElement('div');
                item.className = 'settings-label-palette-item';
                item.dataset.labelName = entry.label;

                if (_settingsLabelUiState.renaming === entry.label) {
                    var renameForm = document.createElement('form');
                    renameForm.className = 'settings-label-rename-form';
                    var rInput = document.createElement('input');
                    rInput.type = 'text';
                    rInput.className = 'settings-input settings-label-rename-input';
                    rInput.value = entry.label;
                    rInput.maxLength = 48;
                    rInput.setAttribute('aria-label', 'Rename label ' + entry.label);
                    var rSave = document.createElement('button');
                    rSave.type = 'submit';
                    rSave.className = 'settings-plain-btn';
                    rSave.textContent = 'Save';
                    var rCancel = document.createElement('button');
                    rCancel.type = 'button';
                    rCancel.className = 'settings-plain-btn';
                    rCancel.textContent = 'Cancel';
                    rCancel.addEventListener('click', function() {
                        _settingsLabelUiState.renaming = null;
                        renderSettingsLabelColors();
                    });
                    renameForm.addEventListener('submit', function(ev) {
                        ev.preventDefault();
                        var nextName = rInput.value.trim();
                        if (!nextName || nextName === entry.label) {
                            _settingsLabelUiState.renaming = null;
                            renderSettingsLabelColors();
                            return;
                        }
                        rSave.disabled = true;
                        _applyServerLabelMutation(
                            { label_rename: { old: entry.label, new: nextName } },
                            true
                        ).then(function(ok) {
                            _settingsLabelUiState.renaming = null;
                            if (ok && typeof sidebarShowToast === 'function') {
                                sidebarShowToast('Renamed label to \u201c' + nextName + '\u201d');
                            }
                            renderSettingsLabelColors();
                        });
                    });
                    renameForm.append(rInput, rSave, rCancel);
                    item.appendChild(renameForm);
                    setTimeout(function() { rInput.focus(); rInput.select(); }, 0);
                } else {
                    var header = document.createElement('div');
                    header.className = 'settings-label-palette-head';
                    var dot = document.createElement('span');
                    dot.className = 'scene-label-dot';
                    var colorExpr = labelColorCssExpr(entry.slot);
                    if (colorExpr) dot.style.setProperty('--label-color', colorExpr);
                    var name = document.createElement('span');
                    name.className = 'settings-label-palette-name';
                    name.textContent = entry.label;
                    var colorChip = document.createElement('span');
                    colorChip.className = 'settings-label-palette-color';
                    colorChip.textContent = labelColorDisplayName(entry.slot, !!entry.configured);
                    var count = document.createElement('span');
                    count.className = 'settings-label-palette-count';
                    count.textContent = String(entry.count || 0) + (entry.count === 1 ? ' scene' : ' scenes');

                    var actions = document.createElement('span');
                    actions.className = 'settings-label-actions';

                    if (_settingsLabelUiState.confirmingRemove === entry.label) {
                        var confirmBtn = document.createElement('button');
                        confirmBtn.type = 'button';
                        confirmBtn.className = 'settings-danger-btn settings-label-action-btn';
                        confirmBtn.textContent = 'Confirm remove';
                        confirmBtn.addEventListener('click', function() {
                            confirmBtn.disabled = true;
                            _applyServerLabelMutation(
                                { label_remove: { name: entry.label } },
                                (entry.count || 0) > 0
                            ).then(function(ok) {
                                _settingsLabelUiState.confirmingRemove = null;
                                if (ok && typeof sidebarShowToast === 'function') {
                                    sidebarShowToast('Removed label \u201c' + entry.label + '\u201d');
                                }
                                renderSettingsLabelColors();
                            });
                        });
                        var cancelRmBtn = document.createElement('button');
                        cancelRmBtn.type = 'button';
                        cancelRmBtn.className = 'settings-plain-btn settings-label-action-btn';
                        cancelRmBtn.textContent = 'Cancel';
                        cancelRmBtn.addEventListener('click', function() {
                            _settingsLabelUiState.confirmingRemove = null;
                            renderSettingsLabelColors();
                        });
                        actions.append(confirmBtn, cancelRmBtn);
                    } else {
                        var renBtn = document.createElement('button');
                        renBtn.type = 'button';
                        renBtn.className = 'settings-plain-btn settings-label-action-btn';
                        renBtn.textContent = 'Rename';
                        renBtn.addEventListener('click', function() {
                            _settingsLabelUiState.confirmingRemove = null;
                            _settingsLabelUiState.renaming = entry.label;
                            renderSettingsLabelColors();
                        });
                        var rmBtn = document.createElement('button');
                        rmBtn.type = 'button';
                        rmBtn.className = 'settings-danger-btn settings-label-action-btn';
                        rmBtn.textContent = 'Remove';
                        rmBtn.addEventListener('click', function() {
                            if ((entry.count || 0) > 0) {
                                _settingsLabelUiState.renaming = null;
                                _settingsLabelUiState.confirmingRemove = entry.label;
                                renderSettingsLabelColors();
                                return;
                            }
                            rmBtn.disabled = true;
                            _applyServerLabelMutation({ label_remove: { name: entry.label } }, false).then(function(ok) {
                                if (ok && typeof sidebarShowToast === 'function') {
                                    sidebarShowToast('Removed label \u201c' + entry.label + '\u201d');
                                }
                                renderSettingsLabelColors();
                            });
                        });
                        actions.append(renBtn, rmBtn);
                    }

                    header.append(dot, name, colorChip, count, actions);
                    item.appendChild(header);
                }

                item.appendChild(buildLabelColorPickerStrip(entry.label, entry.slot, !!entry.configured));
                list.appendChild(item);
            });

            var addForm = document.createElement('form');
            addForm.className = 'settings-label-add-form';
            var addInput = document.createElement('input');
            addInput.type = 'text';
            addInput.className = 'settings-input settings-label-add-input';
            addInput.placeholder = 'New label name\u2026';
            addInput.maxLength = 48;
            addInput.setAttribute('aria-label', 'New label name');
            var addBtn = document.createElement('button');
            addBtn.type = 'submit';
            addBtn.className = 'settings-plain-btn';
            addBtn.textContent = '+ Add label';
            addForm.append(addInput, addBtn);
            addForm.addEventListener('submit', function(ev) {
                ev.preventDefault();
                var lblName = addInput.value.trim();
                if (!lblName) return;
                addBtn.disabled = true;
                _applyServerLabelMutation({ label_add: { name: lblName } }, false).then(function(ok) {
                    addBtn.disabled = false;
                    if (ok) {
                        addInput.value = '';
                        if (typeof sidebarShowToast === 'function') {
                            sidebarShowToast('Added label \u201c' + lblName + '\u201d');
                        }
                    }
                    renderSettingsLabelColors();
                });
            });
            list.appendChild(addForm);
        }

        function buildSceneLabelMenuPanel(opts) {
            var container = opts.container;
            if (!container) return;
            var currentLabel = opts.currentLabel || '';
            var canChangeColor = !(typeof IS_STATIC_SNAPSHOT !== 'undefined' && IS_STATIC_SNAPSHOT)
                && !(window.PROSEVIEW_STATIC && !window.PROSEVIEW_STATIC_EDITS);
            var expandedColorFor = null;

            function render(showNewInput) {
                container.replaceChildren();
                var catalog = (typeof storyModel === 'object' && storyModel && Array.isArray(storyModel.label_catalog))
                    ? storyModel.label_catalog : [];

                if (opts.titleText) {
                    var title = document.createElement('div');
                    title.className = 'scene-label-popover-title';
                    title.textContent = opts.titleText;
                    container.appendChild(title);
                }

                catalog.forEach(function(entry) {
                    if (!entry || !entry.label) return;
                    var rowWrap = document.createElement('div');
                    rowWrap.className = 'scene-label-row-wrap';

                    var row = document.createElement('div');
                    row.className = 'scene-label-item-row' + (entry.label === currentLabel ? ' is-selected' : '');

                    var itemColor = labelColorCssExpr(entry.slot);
                    if (canChangeColor) {
                        var colorBtn = document.createElement('button');
                        colorBtn.type = 'button';
                        colorBtn.className = 'scene-label-swatch-btn';
                        colorBtn.title = 'Change color for ' + entry.label;
                        colorBtn.setAttribute('aria-label', 'Change color for ' + entry.label);
                        colorBtn.setAttribute('aria-expanded', expandedColorFor === entry.label ? 'true' : 'false');
                        var sDot = document.createElement('span');
                        sDot.className = 'scene-label-dot';
                        if (itemColor) sDot.style.setProperty('--label-color', itemColor);
                        colorBtn.appendChild(sDot);
                        colorBtn.addEventListener('click', function(ev) {
                            ev.stopPropagation();
                            expandedColorFor = expandedColorFor === entry.label ? null : entry.label;
                            render(false);
                        });
                        row.appendChild(colorBtn);
                    }

                    var item = document.createElement('button');
                    item.type = 'button';
                    item.className = 'scene-label-item' + (entry.label === currentLabel ? ' is-selected' : '');
                    item.setAttribute('role', 'menuitem');
                    if (!canChangeColor && itemColor) {
                        var iDot = document.createElement('span');
                        iDot.className = 'scene-label-dot';
                        iDot.style.setProperty('--label-color', itemColor);
                        iDot.setAttribute('aria-hidden', 'true');
                        item.appendChild(iDot);
                    }
                    var nameSpan = document.createElement('span');
                    nameSpan.className = 'scene-label-item-name';
                    nameSpan.textContent = entry.label;
                    var countSpan = document.createElement('span');
                    countSpan.className = 'scene-label-item-count';
                    countSpan.textContent = String(entry.count || 0);
                    item.append(nameSpan, countSpan);
                    item.addEventListener('click', function(ev) {
                        ev.stopPropagation();
                        if (typeof opts.onSelect === 'function') opts.onSelect(entry.label);
                    });
                    row.appendChild(item);
                    rowWrap.appendChild(row);

                    if (canChangeColor && expandedColorFor === entry.label) {
                        rowWrap.appendChild(buildLabelColorPickerStrip(entry.label, entry.slot, !!entry.configured, function() {
                            render(false);
                            if (typeof opts.onAfterColorChange === 'function') opts.onAfterColorChange();
                        }));
                    }
                    container.appendChild(rowWrap);
                });

                if (catalog.length) {
                    var sep = document.createElement('div');
                    sep.className = 'scene-label-sep';
                    container.appendChild(sep);
                }

                if (showNewInput) {
                    var form = document.createElement('form');
                    form.className = 'scene-label-new-form';
                    var input = document.createElement('input');
                    input.type = 'text';
                    input.className = 'scene-label-new-input';
                    input.placeholder = 'Label name…';
                    input.maxLength = 48;
                    input.setAttribute('aria-label', 'New label name');
                    var addBtn = document.createElement('button');
                    addBtn.type = 'submit';
                    addBtn.className = 'scene-label-new-submit';
                    addBtn.textContent = 'Add';
                    form.append(input, addBtn);
                    form.addEventListener('submit', function(ev) {
                        ev.preventDefault();
                        ev.stopPropagation();
                        var val = input.value.trim();
                        if (!val) return;
                        if (typeof opts.onSelect === 'function') opts.onSelect(val);
                    });
                    input.addEventListener('click', function(ev) { ev.stopPropagation(); });
                    input.addEventListener('keydown', function(ev) {
                        if (ev.key === 'Escape') {
                            ev.stopPropagation();
                            if (typeof opts.onCancel === 'function') opts.onCancel();
                        }
                    });
                    container.appendChild(form);
                    setTimeout(function() { input.focus(); }, 0);
                } else {
                    var newBtn = document.createElement('button');
                    newBtn.type = 'button';
                    newBtn.className = 'scene-label-item';
                    newBtn.setAttribute('role', 'menuitem');
                    newBtn.textContent = '+ New\u2026';
                    newBtn.addEventListener('click', function(ev) {
                        ev.stopPropagation();
                        expandedColorFor = null;
                        render(true);
                    });
                    container.appendChild(newBtn);
                }

                if (currentLabel) {
                    var clearBtn = document.createElement('button');
                    clearBtn.type = 'button';
                    clearBtn.className = 'scene-label-item is-clear';
                    clearBtn.setAttribute('role', 'menuitem');
                    clearBtn.textContent = 'Clear';
                    clearBtn.addEventListener('click', function(ev) {
                        ev.stopPropagation();
                        if (typeof opts.onSelect === 'function') opts.onSelect('');
                    });
                    container.appendChild(clearBtn);
                }

                if (canChangeColor && typeof openAppearanceSettings === 'function') {
                    var manageSep = document.createElement('div');
                    manageSep.className = 'scene-label-sep';
                    var manageBtn = document.createElement('button');
                    manageBtn.type = 'button';
                    manageBtn.className = 'scene-label-item is-manage';
                    manageBtn.setAttribute('role', 'menuitem');
                    manageBtn.textContent = 'Manage labels\u2026';
                    manageBtn.addEventListener('click', function(ev) {
                        ev.stopPropagation();
                        if (typeof opts.onClose === 'function') opts.onClose();
                        else if (typeof opts.onCancel === 'function') opts.onCancel();
                        openAppearanceSettings();
                    });
                    container.append(manageSep, manageBtn);
                }
            }

            render(false);
        }
