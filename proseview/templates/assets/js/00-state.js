let currentTab = 'overview';
        let suppressHashWrite = false;
        const VALID_TABS = ['overview', 'todos', 'notes'];

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
        const THEME_ORDER = ['light', 'dark', 'docsify', 'hopscotch'];
        const THEME_LABELS = {
            light: 'Light',
            dark: 'Dark',
            docsify: 'Docsify',
            hopscotch: 'Hopscotch'
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
                root.style.removeProperty('--css-zoom-body-width');
                return;
            }
            const logicalViewportWidth = window.innerWidth / zoom;
            const sidebarWidth = root.dataset.sidebar === 'closed'
                ? 0
                : (parseFloat(getComputedStyle(root).getPropertyValue('--sidebar-w')) || 0) + 10;
            root.dataset.cssZoom = 'true';
            root.style.setProperty(
                '--css-zoom-body-width',
                Math.max(220, logicalViewportWidth - sidebarWidth) + 'px'
            );
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

        var _pmView = null;
        var _pmEditMode = false;
        var _pmOpenMtime = null;
        var _pmDirty = false;
        var _pmSavedFlashTimer = null;
        // Counts SSE reload events we expect to be triggered by our own
        // /save-scene calls. Decremented (with a tail timeout) when the
        // event arrives, so reloadOrDefer can skip the page reload our
        // own save would otherwise cause.
        var _pendingSelfReloads = 0;
        var _pendingSelfReloadTimer = null;
