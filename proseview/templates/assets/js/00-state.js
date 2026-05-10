let currentTab = 'overview';
        let suppressHashWrite = false;
        const VALID_TABS = ['overview', 'todos', 'notes'];

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
        const FONT_ORDER = ['reader', 'literary', 'inter', 'georgia', 'baskerville', 'sans', 'mono'];
        const FONT_LABELS = { reader: 'Reader', literary: 'Literary', inter: 'Inter', georgia: 'Georgia', baskerville: 'Baskerville', sans: 'Sans', mono: 'Mono' };
        const chartRefs = {};
        let curIdx = -1;
        let hls = {};
        PASS_ORDER.forEach(p => hls[p] = false);
        let scrollSaveQueued = false;
        let routeHydrating = false;

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

