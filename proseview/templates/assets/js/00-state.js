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
                    .getPropertyValue('--utility-dock-w')) || 504,
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
