let currentTab = 'overview';
        let suppressHashWrite = false;
        const VALID_TABS = ['overview', 'analysis', 'timeline', 'todos', 'notes'];

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

        const PASS_LABELS = {
            passive_voice: 'Passive Voice',
            filter_verbs: 'Filter Verbs',
            crutch_words: 'Crutch Words',
            hyperbole: 'Hyperbole',
            lyrical: 'Lyrical',
            sensory: 'Sensory',
            comedy_beats: 'Comedy Beats',
            repeats: 'Repeats',
            first_person: 'First Person'
        };
        const PASS_CLASSES = {
            passive_voice: 'hl-passive',
            filter_verbs: 'hl-filter',
            crutch_words: 'hl-crutch',
            hyperbole: 'hl-hyperbole',
            lyrical: 'hl-lyrical',
            sensory: 'hl-sensory',
            comedy_beats: 'hl-comedy',
            repeats: 'hl-repeat',
            first_person: 'hl-first-person'
        };

        const THEME_STORAGE_KEY = 'proseview-theme';
        const THEME_ORDER = ['light', 'dark', 'docsify', 'hopscotch', 'graphite-light', 'graphite-dark'];
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

        function syncCssZoomViewport() {
            const root = document.documentElement;
            const body = document.body;
            if (!body) return;
            const zoom = parseFloat(getComputedStyle(body).zoom) || 1;
            if (zoom <= 1) {
                delete root.dataset.cssZoom;
                delete root.dataset.utilityOverlay;
                root.style.removeProperty('--css-zoom-body-width');
                root.style.removeProperty('--css-zoom-dock-width');
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
            new MutationObserver(syncCssZoomViewport).observe(document.body, {
                attributes: true,
                attributeFilter: ['style'],
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
            const utilityDockOpen = document.body.classList.contains('discuss-open')
                || document.body.classList.contains('terminal-right-open');
            const compactDock = utilityDockOpen && window.matchMedia('(max-width: 1120px)').matches;
            const responsivelyRetracted = window.matchMedia('(max-width: 700px)').matches
                || root.dataset.cssZoom === 'true'
                || compactDock;
            const hidden = root.dataset.sidebar === 'closed' || responsivelyRetracted;
            sidebar.inert = hidden;
            if (hidden) sidebar.setAttribute('aria-hidden', 'true');
            else sidebar.removeAttribute('aria-hidden');
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
        var _pmEditMode = false;
        var _pmOpenMtime = null;
        var _pmDirty = false;
        var _pmSavedFlashTimer = null;
        var _pmConflictDraft = null;
        var _pmSaveInFlight = false;
        // Counts SSE reload events we expect to be triggered by our own
        // /save-scene calls. Decremented (with a tail timeout) when the
        // event arrives, so reloadOrDefer can skip the page reload our
        // own save would otherwise cause.
        var _pendingSelfReloads = 0;
        var _pendingSelfReloadTimer = null;
