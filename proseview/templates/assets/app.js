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

        // ── Source line-number gutter ────────────────────────────────────
        var LINE_NUMBERS_KEY = 'proseview-line-numbers';
        var _lineNumbersOn = false;
        try { _lineNumbersOn = localStorage.getItem(LINE_NUMBERS_KEY) === '1'; } catch(e) {}

        function _applyLineNumbersClass() {
            var mc = document.querySelector('#sceneModal .modal-content');
            if (mc) mc.classList.toggle('line-numbers', _lineNumbersOn);
            var btn = document.getElementById('modalLineNumbersBtn');
            if (btn) {
                btn.classList.toggle('is-active', _lineNumbersOn);
                btn.title = _lineNumbersOn ? 'Hide source line numbers' : 'Show source line numbers';
            }
        }
        function _applyEditingProseClass() {
            var mc = document.querySelector('#sceneModal .modal-content');
            if (mc) mc.classList.toggle('editing-prose', !!_pmEditMode);
        }
        function toggleLineNumbers() {
            _lineNumbersOn = !_lineNumbersOn;
            try { localStorage.setItem(LINE_NUMBERS_KEY, _lineNumbersOn ? '1' : '0'); } catch(e) {}
            _applyLineNumbersClass();
        }

        // Build a DecorationSet that tags each top-level PM block with its
        // source line number (1-indexed). Pairs markdown-it tokens with PM
        // doc children in document order: both lists are emitted top-to-
        // bottom in the same sequence, so a single index pointer keeps them
        // in sync. We stop annotating if the counts diverge instead of
        // surfacing wrong numbers.
        function _buildLineNumberDecorations(doc, markdown, lineOffset, absPath) {
            var PM = window._PM;
            if (!PM || !PM.defaultMarkdownParser || !PM.defaultMarkdownParser.tokenizer) {
                return PM ? PM.DecorationSet.empty : null;
            }
            var tokens;
            try {
                tokens = PM.defaultMarkdownParser.tokenizer.parse(markdown, {});
            } catch (e) {
                return PM.DecorationSet.empty;
            }
            // lineOffset is the source-file line where this scene's body
            // begins (frontmatter + heading lines, supplied by the
            // generator as meta[path].txt_line_offset). Without it, our
            // numbers would restart at 1 per scene instead of matching
            // the underlying .md file.
            var base = (typeof lineOffset === 'number' && lineOffset >= 0) ? lineOffset : 0;
            var blockLines = [];
            for (var i = 0; i < tokens.length; i++) {
                var t = tokens[i];
                if (t.level !== 0) continue;
                if (!t.map) continue;
                if (t.nesting === 1 || t.nesting === 0) {
                    blockLines.push(base + t.map[0] + 1);
                    if (t.nesting === 1) {
                        // Skip everything until the matching close to avoid
                        // counting nested block opens (list items, etc.).
                        var depth = 1;
                        for (var j = i + 1; j < tokens.length; j++) {
                            if (tokens[j].nesting === 1) depth++;
                            else if (tokens[j].nesting === -1) {
                                depth--;
                                if (depth === 0) { i = j; break; }
                            }
                        }
                    }
                }
            }

            var decos = [];
            var idx = 0;
            doc.forEach(function(node, offset) {
                if (idx >= blockLines.length) return;
                var line = blockLines[idx];
                decos.push(PM.Decoration.node(offset, offset + node.nodeSize, {
                    'data-line': String(line)
                }));
                if (absPath) {
                    decos.push(PM.Decoration.widget(offset + 1, function() {
                        var a = document.createElement('a');
                        a.className = 'pm-line-jump';
                        a.href = buildEditorUrl(absPath, line);
                        a.target = '_blank';
                        a.rel = 'noopener';
                        a.title = 'Open line ' + line + ' in ' + editorLabel;
                        a.textContent = '↗';
                        return a;
                    }, { side: -1, ignoreSelection: true, key: 'lj:' + line }));
                }
                idx++;
            });
            return PM.DecorationSet.create(doc, decos);
        }

        var lnPluginKey = null;
        function _buildLnPlugin() {
            var PM = window._PM;
            if (!PM) return null;
            if (!lnPluginKey) lnPluginKey = new PM.PluginKey('proseviewLineNumbers');
            return new PM.Plugin({
                key: lnPluginKey,
                state: {
                    init: function() { return PM.DecorationSet.empty; },
                    apply: function(tr, set) {
                        var next = tr.getMeta(lnPluginKey);
                        if (next !== undefined) return next;
                        return set.map(tr.mapping, tr.doc);
                    }
                },
                props: {
                    decorations: function(state) { return lnPluginKey.getState(state); }
                }
            });
        }

        function setPmDirty(dirty) {
            _pmDirty = !!dirty;
            var bar = document.getElementById('sceneEditBar');
            var saveBtn = bar ? bar.querySelector('.scene-edit-save') : null;
            var stateEl = document.getElementById('sceneEditState');
            var title = document.getElementById('modalTitle');
            if (bar) {
                bar.classList.toggle('is-dirty', _pmDirty);
                if (_pmDirty) {
                    bar.classList.remove('is-saving', 'is-saved');
                }
            }
            if (saveBtn) saveBtn.disabled = !_pmDirty;
            if (stateEl) stateEl.textContent = _pmDirty ? 'Editing • unsaved' : 'Editing';
            if (title) title.classList.toggle('is-modified', _pmDirty);
            if (_pmSavedFlashTimer) {
                clearTimeout(_pmSavedFlashTimer);
                _pmSavedFlashTimer = null;
            }
        }

        function setPmSaving() {
            var bar = document.getElementById('sceneEditBar');
            var stateEl = document.getElementById('sceneEditState');
            if (bar) bar.classList.add('is-saving');
            if (stateEl) stateEl.textContent = 'Saving…';
        }

        function setPmSaved() {
            var bar = document.getElementById('sceneEditBar');
            var stateEl = document.getElementById('sceneEditState');
            var title = document.getElementById('modalTitle');
            if (bar) {
                bar.classList.remove('is-saving', 'is-dirty');
                bar.classList.add('is-saved');
            }
            if (stateEl) stateEl.textContent = 'Saved';
            if (title) title.classList.remove('is-modified');
            _pmDirty = false;
            var saveBtn = bar ? bar.querySelector('.scene-edit-save') : null;
            if (saveBtn) saveBtn.disabled = true;
            if (_pmSavedFlashTimer) clearTimeout(_pmSavedFlashTimer);
            _pmSavedFlashTimer = setTimeout(function() {
                if (!bar) return;
                bar.classList.remove('is-saved');
                if (stateEl) stateEl.textContent = _pmEditMode ? 'Editing' : '';
                _pmSavedFlashTimer = null;
            }, 1600);
        }
        var _pmAffordancePara = null;
        var _pmAffordancePos = -1;
        var _pmAffordanceTimer = null;
        var _pmAnnotationPos = -1;

        function currentTheme() {
            const t = document.documentElement.dataset.theme;
            return THEME_ORDER.includes(t) ? t : 'light';
        }

        function cssVar(name) {
            return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        }

        function getThemePalette() {
            return {
                text: cssVar('--chart-text'),
                grid: cssVar('--chart-grid'),
                primary: cssVar('--chart-primary'),
                secondary: cssVar('--chart-secondary'),
                success: cssVar('--chart-success'),
                warning: cssVar('--chart-warning'),
                danger: cssVar('--chart-danger'),
                pink: cssVar('--chart-pink'),
                cyan: cssVar('--chart-cyan'),
                neutral: cssVar('--chart-neutral'),
                zoneDanger: cssVar('--chart-zone-danger'),
                zoneSuccess: cssVar('--chart-zone-success'),
                zoneSecondary: cssVar('--chart-zone-secondary'),
                targetFill: cssVar('--chart-target-fill'),
                targetBorder: cssVar('--chart-target-border'),
                tooltipBg: cssVar('--surface-tooltip'),
                tooltipText: cssVar('--text-main'),
                tooltipBorder: cssVar('--border'),
            };
        }

        function applyAxisTheme(axis, palette) {
            if (!axis) return;
            axis.grid = axis.grid || {};
            axis.border = axis.border || {};
            axis.ticks = axis.ticks || {};
            axis.title = axis.title || {};
            axis.grid.color = palette.grid;
            axis.border.color = palette.grid;
            axis.ticks.color = palette.text;
            if (axis.title.display) axis.title.color = palette.text;
        }

        function applyLegendTheme(legend, palette) {
            if (!legend) return;
            legend.labels = legend.labels || {};
            legend.labels.color = palette.text;
        }

        function applyTooltipTheme(plugins, palette) {
            plugins.tooltip = plugins.tooltip || {};
            plugins.tooltip.backgroundColor = palette.tooltipBg;
            plugins.tooltip.titleColor = palette.tooltipText;
            plugins.tooltip.bodyColor = palette.tooltipText;
            plugins.tooltip.borderColor = palette.tooltipBorder;
            plugins.tooltip.borderWidth = 1;
        }

        function applyCommonChartTheme(chart, palette) {
            const options = chart.options || {};
            const plugins = options.plugins || (options.plugins = {});
            applyTooltipTheme(plugins, palette);
            if (plugins.legend) applyLegendTheme(plugins.legend, palette);
            if (options.scales) Object.values(options.scales).forEach(scale => applyAxisTheme(scale, palette));
        }

        function applyThemeToConfig(id, cfg, palette) {
            const opts = cfg.options || {};
            const plugins = opts.plugins || (opts.plugins = {});
            applyTooltipTheme(plugins, palette);
            if (plugins.legend) applyLegendTheme(plugins.legend, palette);
            if (opts.scales) Object.values(opts.scales).forEach(s => applyAxisTheme(s, palette));
            const datasets = (cfg.data || {}).datasets || [];
            if (id === 'presenceChart') {
                const colors = [palette.primary, palette.secondary, palette.success, palette.warning,
                                palette.danger, palette.pink, palette.cyan, palette.neutral];
                datasets.forEach((ds, i) => {
                    const c = colors[i % colors.length];
                    ds.borderColor = ds.backgroundColor = ds.pointBackgroundColor = ds.pointBorderColor = c;
                });
            } else if (id === 'rhythmChart') {
                if (datasets[0]) {
                    const c = palette.secondary;
                    datasets[0].borderColor = datasets[0].backgroundColor =
                        datasets[0].pointBackgroundColor = datasets[0].pointBorderColor = c;
                }
                const ann = ((plugins.annotation || {}).annotations || {});
                if (ann.staticZone) { ann.staticZone.backgroundColor = palette.zoneDanger; ann.staticZone.borderColor = 'transparent'; }
                if (ann.rhythmicZone) { ann.rhythmicZone.backgroundColor = palette.zoneSuccess; ann.rhythmicZone.borderColor = 'transparent'; }
                if (ann.dynamicZone) { ann.dynamicZone.backgroundColor = palette.zoneSecondary; ann.dynamicZone.borderColor = 'transparent'; }
            } else if (id === 'locationChart') {
                if (datasets[0]) {
                    datasets[0].backgroundColor = [palette.primary, palette.success, palette.warning,
                        palette.danger, palette.secondary, palette.pink, palette.cyan, palette.neutral];
                    datasets[0].borderColor = cssVar('--surface-card');
                    datasets[0].borderWidth = 2;
                }
            } else if (id === 'coOccurChart') {
                if (datasets[0]) datasets[0].backgroundColor = palette.secondary;
            } else if (id === 'lexicalScatterChart') {
                if (datasets[0]) datasets[0].backgroundColor = palette.primary;
                const ann = ((plugins.annotation || {}).annotations || {});
                if (ann.target) {
                    ann.target.backgroundColor = palette.targetFill;
                    ann.target.borderColor = palette.targetBorder;
                }
            }
        }

        function applyThemeToChart(chart) {
            if (!chart) return;
            const palette = getThemePalette();
            const id = chart.canvas.id;
            applyCommonChartTheme(chart, palette);

            if (id === 'presenceChart') {
                const colors = [palette.primary, palette.secondary, palette.success, palette.warning,
                                palette.danger, palette.pink, palette.cyan, palette.neutral];
                chart.data.datasets.forEach((dataset, index) => {
                    const color = colors[index % colors.length];
                    dataset.borderColor = color;
                    dataset.backgroundColor = color;
                    dataset.pointBackgroundColor = color;
                    dataset.pointBorderColor = color;
                });
            } else if (id === 'rhythmChart') {
                const rhythmDataset = chart.data.datasets[0];
                if (rhythmDataset) {
                    rhythmDataset.borderColor = palette.secondary;
                    rhythmDataset.backgroundColor = palette.secondary;
                    rhythmDataset.pointBackgroundColor = palette.secondary;
                    rhythmDataset.pointBorderColor = palette.secondary;
                }
                const annotations = (((chart.options || {}).plugins || {}).annotation || {}).annotations || {};
                if (annotations.staticZone) {
                    annotations.staticZone.backgroundColor = palette.zoneDanger;
                    annotations.staticZone.borderColor = 'transparent';
                }
                if (annotations.rhythmicZone) {
                    annotations.rhythmicZone.backgroundColor = palette.zoneSuccess;
                    annotations.rhythmicZone.borderColor = 'transparent';
                }
                if (annotations.dynamicZone) {
                    annotations.dynamicZone.backgroundColor = palette.zoneSecondary;
                    annotations.dynamicZone.borderColor = 'transparent';
                }
            } else if (id === 'locationChart') {
                const locationDataset = chart.data.datasets[0];
                if (locationDataset) {
                    locationDataset.backgroundColor = [
                        palette.primary, palette.success, palette.warning, palette.danger,
                        palette.secondary, palette.pink, palette.cyan, palette.neutral
                    ];
                    locationDataset.borderColor = cssVar('--surface-card');
                    locationDataset.borderWidth = 2;
                }
            } else if (id === 'coOccurChart') {
                const coOccurDataset = chart.data.datasets[0];
                if (coOccurDataset) coOccurDataset.backgroundColor = palette.secondary;
            } else if (id === 'lexicalScatterChart') {
                const scatterDataset = chart.data.datasets[0];
                if (scatterDataset) scatterDataset.backgroundColor = palette.primary;
                const annotations = (((chart.options || {}).plugins || {}).annotation || {}).annotations || {};
                if (annotations.target) {
                    annotations.target.backgroundColor = palette.targetFill;
                    annotations.target.borderColor = palette.targetBorder;
                }
            }

            chart.update('none');
        }

        function updateChartsForTheme() {
            Object.values(chartRefs).forEach(chart => applyThemeToChart(chart));
        }

        function syncThemeToggle() {
            const theme = currentTheme();
            const label = document.getElementById('themeToggleLabel');
            if (label) label.innerText = THEME_LABELS[theme];
            const button = document.getElementById('themeToggle');
            if (button) button.setAttribute('aria-label', 'Color theme: ' + THEME_LABELS[theme]);
            document.querySelectorAll('.theme-menu-item').forEach(el => {
                el.setAttribute('aria-selected', el.dataset.themeValue === theme ? 'true' : 'false');
            });
            const pvSel = document.getElementById('filePreviewThemeSelect');
            if (pvSel) pvSel.value = theme;
            const mSel = document.getElementById('modalThemeSelect');
            if (mSel) mSel.value = theme;
        }

        function selectTheme(name) {
            if (!THEME_ORDER.includes(name)) return;
            document.documentElement.dataset.theme = name;
            try { localStorage.setItem(THEME_STORAGE_KEY, name); } catch(e) {}
            syncThemeToggle();
            updateChartsForTheme();
            closeThemeMenu(true);
        }

        let committedTheme = null;
        let themeMenuDocHandler = null;

        function themeMenuIsOpen() {
            const m = document.getElementById('themeMenu');
            return !!(m && m.dataset.open === 'true');
        }

        function openThemeMenu() {
            committedTheme = currentTheme();
            const menu = document.getElementById('themeMenu');
            const btn = document.getElementById('themeToggle');
            if (menu) menu.dataset.open = 'true';
            if (btn) btn.setAttribute('aria-expanded', 'true');
            themeMenuDocHandler = function(e) {
                const menu = document.getElementById('themeMenu');
                if (menu && !menu.contains(e.target)) closeThemeMenu(false);
            };
            document.addEventListener('mousedown', themeMenuDocHandler);
        }

        function closeThemeMenu(commit) {
            const menu = document.getElementById('themeMenu');
            const btn = document.getElementById('themeToggle');
            if (menu) menu.dataset.open = 'false';
            if (btn) btn.setAttribute('aria-expanded', 'false');
            if (themeMenuDocHandler) {
                document.removeEventListener('mousedown', themeMenuDocHandler);
                themeMenuDocHandler = null;
            }
            if (!commit && committedTheme) {
                document.documentElement.dataset.theme = committedTheme;
                syncThemeToggle();
                updateChartsForTheme();
            }
            committedTheme = null;
        }

        function toggleThemeMenu() {
            if (themeMenuIsOpen()) closeThemeMenu(false);
            else openThemeMenu();
        }

        function previewTheme(name) {
            if (!THEME_ORDER.includes(name)) return;
            document.documentElement.dataset.theme = name;
            syncThemeToggle();
        }

        function currentFont() {
            const f = document.documentElement.dataset.font;
            return FONT_ORDER.indexOf(f) >= 0 ? f : 'reader';
        }

        function syncFontToggle() {
            const font = currentFont();
            const label = document.getElementById('fontToggleLabel');
            const button = document.getElementById('fontToggle');
            if (label) label.innerText = FONT_LABELS[font];
            if (button) button.title = 'Reading font: ' + FONT_LABELS[font];
            document.querySelectorAll('.font-menu-item').forEach(el => {
                el.setAttribute('aria-selected', el.dataset.fontValue === font ? 'true' : 'false');
            });
            const sel = document.getElementById('filePreviewFontSelect');
            if (sel) sel.value = font;
            const msel = document.getElementById('modalFontSelect');
            if (msel) msel.value = font;
        }

        let committedFont = null;
        let fontMenuDocHandler = null;

        function fontMenuIsOpen() {
            const menu = document.getElementById('fontMenu');
            return !!(menu && menu.dataset.open === 'true');
        }

        function openFontMenu() {
            if (fontMenuIsOpen()) return;
            committedFont = currentFont();
            const menu = document.getElementById('fontMenu');
            const button = document.getElementById('fontToggle');
            if (menu) menu.dataset.open = 'true';
            if (button) button.setAttribute('aria-expanded', 'true');
            fontMenuDocHandler = function(e) {
                if (!menu.contains(e.target)) closeFontMenu(false);
            };
            setTimeout(() => document.addEventListener('click', fontMenuDocHandler), 0);
        }

        function closeFontMenu(commit) {
            if (!fontMenuIsOpen()) return;
            const menu = document.getElementById('fontMenu');
            const button = document.getElementById('fontToggle');
            if (menu) menu.dataset.open = 'false';
            if (button) button.setAttribute('aria-expanded', 'false');
            if (fontMenuDocHandler) {
                document.removeEventListener('click', fontMenuDocHandler);
                fontMenuDocHandler = null;
            }
            if (!commit && committedFont && currentFont() !== committedFont) {
                document.documentElement.dataset.font = committedFont;
                syncFontToggle();
            }
            committedFont = null;
        }

        function toggleFontMenu() {
            if (fontMenuIsOpen()) closeFontMenu(false);
            else openFontMenu();
        }

        function previewFont(name) {
            if (FONT_ORDER.indexOf(name) < 0) return;
            document.documentElement.dataset.font = name;
            syncFontToggle();
        }

        function selectFont(name) {
            if (FONT_ORDER.indexOf(name) < 0) return;
            document.documentElement.dataset.font = name;
            try {
                localStorage.setItem(FONT_STORAGE_KEY, name);
            } catch (err) {
                // Ignore storage errors and keep the current session font.
            }
            syncFontToggle();
            closeFontMenu(true);
        }

        function normalizeModalFontSize(value) {
            const parsed = parseInt(value, 10);
            if (Number.isNaN(parsed)) return MODAL_FONT_SIZE_DEFAULT;
            return Math.min(MODAL_FONT_SIZE_MAX, Math.max(MODAL_FONT_SIZE_MIN, parsed));
        }

        function loadModalFontSize() {
            try {
                return normalizeModalFontSize(localStorage.getItem(MODAL_FONT_SIZE_STORAGE_KEY));
            } catch (err) {
                return MODAL_FONT_SIZE_DEFAULT;
            }
        }

        function syncModalFontSize() {
            const size = loadModalFontSize();
            const modalBody = document.getElementById('modalBody');
            const slider = document.getElementById('modalFontSize');
            if (modalBody) modalBody.style.fontSize = size + 'px';
            if (slider) slider.value = String(size);
            return size;
        }

        function activeRouteKey() {
            const route = parseHashRoute();
            if (!route) return '/tab/' + (currentTab || 'overview');
            if (route.kind === 'tab') return '/tab/' + (VALID_TABS.includes(route.arg) ? route.arg : 'overview');
            if (route.kind === 'scene' && route.arg) return '/scene/' + route.arg;
            if (route.kind === 'file' && route.arg) return '/file/' + route.arg;
            return '/tab/' + (currentTab || 'overview');
        }

        function activeScrollContainer() {
            const route = parseHashRoute();
            if (route && route.kind === 'scene') return document.querySelector('#sceneModal .modal-content');
            if (route && route.kind === 'file') return document.getElementById('filePreviewBody');
            return window;
        }

        function readScrollTop(container) {
            if (!container) return null;
            return container === window ? (window.scrollY || window.pageYOffset || 0) : container.scrollTop;
        }

        function writeScrollTop(container, top) {
            if (!container) return;
            if (container === window) window.scrollTo(0, top);
            else container.scrollTop = top;
        }

        function loadSavedScrollTop(key) {
            try {
                const raw = sessionStorage.getItem(VIEW_SCROLL_STORAGE_PREFIX + key);
                if (raw === null) return null;
                const parsed = parseInt(raw, 10);
                return Number.isNaN(parsed) ? null : Math.max(0, parsed);
            } catch (err) {
                return null;
            }
        }

        function saveActiveScrollPosition() {
            if (routeHydrating) return;
            const key = activeRouteKey();
            const top = readScrollTop(activeScrollContainer());
            if (!key || top === null) return;
            try {
                sessionStorage.setItem(VIEW_SCROLL_STORAGE_PREFIX + key, String(Math.round(top)));
            } catch (err) {
                // Ignore storage errors and keep default refresh behavior.
            }
        }

        function scheduleScrollSave() {
            if (scrollSaveQueued) return;
            scrollSaveQueued = true;
            requestAnimationFrame(function() {
                scrollSaveQueued = false;
                saveActiveScrollPosition();
            });
        }

        function restoreActiveScrollPosition() {
            const top = loadSavedScrollTop(activeRouteKey());
            if (top === null) return;
            const delays = [0, 40, 120, 260];
            delays.forEach(function(delay) {
                window.setTimeout(function() {
                    const container = activeScrollContainer();
                    if (!container) return;
                    writeScrollTop(container, top);
                }, delay);
            });
        }

        function buildEditorUrl(absPath, line) {
            const lineVal = (line && line > 1) ? line : 1;
            if (editorScheme === 'custom' && editorUrlTemplate) {
                return editorUrlTemplate
                    .replace('{abs_path}', encodeURI(absPath))
                    .replace('{line}', String(lineVal));
            }
            const base = editorScheme + '://file/' + encodeURI(absPath);
            return lineVal > 1 ? base + ':' + lineVal : base;
        }

        function openSceneModal(p) {
            saveActiveScrollPosition();
            curIdx = paths.indexOf(p);
            Object.keys(hls).forEach(k => hls[k] = false);
            updateModal();
            document.documentElement.dataset.view = 'scene';
            routeToHash('/scene/' + encodeURIComponent(p), true);
            restoreActiveScrollPosition();
            // highlight corresponding sidebar item
            document.querySelectorAll('#sidebarTree .file-link').forEach(el => {
                el.classList.toggle('active', el.dataset.scenePath === p);
            });
            if (typeof updateTerminalShortcuts === 'function') updateTerminalShortcuts();
        }

        function openRelatedDoc(path) {
            closeSceneModal();
            previewRepoFile(path);
        }

        function updateModal() {
            const p = paths[curIdx], m = meta[p], b = document.getElementById('modalBody'), a = document.getElementById('modalAlerts'), s = document.getElementById('modalStats');
            document.getElementById('modalTitle').innerText = p;
            const _modalEditorBtn = document.getElementById('modalEditorBtn');
            _modalEditorBtn.style.display = 'inline-block';
            _modalEditorBtn.href = buildEditorUrl(m.abs_path);
            _modalEditorBtn.innerText = '\u2197';
            _modalEditorBtn.title = 'Open in ' + editorLabel;

            const energyLabel = m.energy > 12 ? 'Action ⚡' : (m.energy < 7 ? 'Pensive 🧠' : 'Balanced ⚖️');
            s.innerHTML = '<div class="scene-stat-box"><span class="val">' + m.words.toLocaleString() + '</span><span class="lbl">Words</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.dlg_pct.toFixed(1) + '%</span><span class="lbl">Dialogue %</span></div>' +
                        '<div class="scene-stat-box"><span class="val" title="Dialogue Energy Score">' + energyLabel + '</span><span class="lbl">Energy</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.sensory.toFixed(1) + '</span><span class="lbl">Sensory Density</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.first_person.toFixed(1) + '</span><span class="lbl">1st Person</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.passive.toFixed(1) + '</span><span class="lbl">Passive Rate</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.avg_sent.toFixed(1) + '</span><span class="lbl">Avg. Sentence</span></div>' +
                        '<div class="scene-stat-box"><span class="val">' + m.crutch.toFixed(1) + '</span><span class="lbl">Crutch Rate</span></div>';

            const dlgKeywords = (m.top_dlg && m.top_dlg.length) ? m.top_dlg.join(', ') : 'None found';
            a.innerHTML = '<div class="modal-note">' +
                        'Toggle a pass to highlight its matches in the scene below. ' +
                        'Each color marks one pass; sensory hits include a category in the tooltip. ' +
                        'Top dialogue keywords this scene: <span style="color:var(--primary); font-weight:bold;">' + dlgKeywords + '</span>' +
                        '</div>';
            const row = document.createElement('div');
            row.className = 'alert-tag-row';
            const allBtn = document.createElement('button');
            allBtn.id = 'tag-all';
            allBtn.className = 'alert-tag-all';
            allBtn.type = 'button';
            allBtn.textContent = 'All';
            allBtn.onclick = toggleAllHighlights;
            row.appendChild(allBtn);
            PASS_ORDER.forEach(name => addTag(row, name, PASS_LABELS[name]));
            a.appendChild(row);
            render();
        }

        function updateFontSize(v) {
            const size = normalizeModalFontSize(v);
            const modalBody = document.getElementById('modalBody');
            const slider = document.getElementById('modalFontSize');
            if (modalBody) modalBody.style.fontSize = size + 'px';
            if (slider) slider.value = String(size);
            try {
                localStorage.setItem(MODAL_FONT_SIZE_STORAGE_KEY, String(size));
            } catch (err) {
                // Ignore storage errors and keep the current session size.
            }
        }

        function openBio(name) {
            const slug = name.toLowerCase().replace(/\s+/g, '-');
            const bio = bios[slug] || "# Bio not found for " + name;
            const b = document.getElementById('modalBody');
            const s = document.getElementById('modalStats');
            const a = document.getElementById('modalAlerts');
            const t = document.getElementById('modalTitle');

            t.innerText = "Character Bible: " + name;
            document.getElementById('modalEditorBtn').style.display = 'none';
            s.innerHTML = "";
            a.innerHTML = '<div class="alert-tag alert-tag-active" onclick="updateModal()">\u2190 Back to Scene</div>';
            b.innerHTML = '<div class="bio-card">' + marked.parse(bio) + '</div>';
            document.querySelector('.modal-content').scrollTop = 0;
        }

        function addTag(a, id, txt) { const t = document.createElement('div'); t.className = 'alert-tag'; t.id = 'tag-'+id; t.innerText = txt; t.onclick = () => toggleHighlight(id); a.appendChild(t); }
        function toggleHighlight(id) {
            hls[id] = !hls[id];
            document.getElementById('tag-'+id).classList.toggle('alert-tag-active', hls[id]);
            syncAllBtn();
            if (window._PM && _pmView) { updatePMHighlightDecorations(); } else { render(); }
        }
        function syncAllBtn() { const btn = document.getElementById('tag-all'); if (!btn) return; const anyOn = PASS_ORDER.some(k => hls[k]); btn.textContent = anyOn ? 'Clear' : 'All'; }
        function toggleAllHighlights() {
            const anyOn = PASS_ORDER.some(k => hls[k]);
            PASS_ORDER.forEach(k => { hls[k] = !anyOn; const el = document.getElementById('tag-'+k); if (el) el.classList.toggle('alert-tag-active', hls[k]); });
            syncAllBtn();
            if (window._PM && _pmView) { updatePMHighlightDecorations(); } else { render(); }
        }

        function attrEscape(s) {
            return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        function renderCharacterTags(chars) {
            return chars.map(function(c) {
                return '<div class="sc-char-tag" data-char-name="' +
                    attrEscape(c) +
                    '" onclick="openBio(this.dataset.charName)" title="Read bio">' +
                    escHtml(c) +
                    '</div>';
            }).join('');
        }

        function render() {
            const p = paths[curIdx], b = document.getElementById('modalBody'), m = meta[p];
            const fm = m.fm || {};
            const chars = Array.isArray(fm.characters) ? fm.characters : (typeof fm.characters === 'string' ? [fm.characters] : []);
            const relatedDocs = Array.isArray(m.related_docs) ? m.related_docs : [];
            const sceneTodos = Array.isArray(m.todos) ? m.todos : [];
            const todosByPara = {};
            const fmTodos = [];
            sceneTodos.forEach(function(t) {
                if (t.paragraph_index >= 0) {
                    if (!todosByPara[t.paragraph_index]) todosByPara[t.paragraph_index] = [];
                    todosByPara[t.paragraph_index].push(t);
                } else {
                    fmTodos.push(t);
                }
            });
            const sceneNotes = Array.isArray(m.notes) ? m.notes : [];
            const notesByPara = {};
            sceneNotes.forEach(function(n) {
                if (!notesByPara[n.paragraph_index]) notesByPara[n.paragraph_index] = [];
                notesByPara[n.paragraph_index].push(n);
            });

            const editorHref = buildEditorUrl(m.abs_path);
            let relatedHtml = '<div class="scene-card-related">' +
                              '<div class="sc-row">' +
                              '<span class="sc-label">Related Docs</span>';
            if (relatedDocs.length) {
                relatedHtml += '<ul class="related-doc-list">';
                relatedDocs.forEach(doc => {
                    const docHref = buildEditorUrl(doc.abs_path || '');
                    relatedHtml += '<li class="related-doc-item">' +
                                   '<button type="button" class="related-doc-link" data-path="' + attrEscape(doc.path || '') + '" onclick="openRelatedDoc(this.dataset.path)">' + escHtml(doc.path || '') + '</button>' +
                                   '<a class="related-doc-editor-icon" href="' + docHref + '" target="_blank" title="Open in ' + attrEscape(editorLabel) + '">\u2197</a>' +
                                   '</li>';
                });
                relatedHtml += '</ul>';
            } else {
                relatedHtml += '<div class="related-doc-empty">No related planning or continuity docs matched this scene.</div>';
            }
            relatedHtml += '</div></div>';
            let cardHtml = '<div class="scene-card">' +
                           '<div class="scene-card-meta">' +
                           '<div class="sc-row scene-card-top">' +
                           '<span class="sc-label">Scene File</span>' +
                           '<a class="editor-btn" href="' + editorHref + '" target="_blank">\u2197 Open in ' + editorLabel + '</a>' +
                           '</div>' +
                           '<div class="sc-row"><span class="sc-label">POV</span><span class="sc-value">' + (fm.pov || "Unknown") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">When</span><span class="sc-value">' + (fm.when || "Unknown") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">Where</span><span class="sc-value">' + (fm.where || fm.location || "Unknown") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">Characters</span><div class="sc-characters">' +
                           renderCharacterTags(chars) + '</div></div>' +
                           '</div>' +
                           '<div class="scene-card-arc">' +
                           '<div class="sc-row"><span class="sc-label">Goal</span><span class="sc-value">' + (fm.goal || "Not defined") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">Conflict</span><span class="sc-value">' + (fm.conflict || "Not defined") + '</span></div>' +
                           '<div class="sc-row"><span class="sc-label">Outcome</span><span class="sc-value">' + (fm.outcome || "Not defined") + '</span></div>' +
                           '</div>' +
                           relatedHtml +
                           '</div>';

            // Build tasks panel (all TODOs + notes sorted by paragraph order)
            const allTasks = [];
            sceneTodos.forEach(function(t) { allTasks.push({type: 'todo', para: t.paragraph_index, item: t}); });
            sceneNotes.forEach(function(n) { allTasks.push({type: 'note', para: n.paragraph_index, item: n}); });
            allTasks.sort(function(a, b) { return a.para - b.para; });
            let tasksHtml = '';
            if (allTasks.length) {
                const rows = allTasks.map(function(task) {
                    const jumpBtn = task.para >= 0
                        ? '<button class="task-jump-btn" type="button" data-para-idx="' + task.para + '" title="Scroll to paragraph">&#x2193;</button>'
                        : '';
                    const chip = task.type === 'todo'
                        ? '<span class="task-type-chip task-type-todo">TODO</span>'
                        : '<span class="task-type-chip task-type-note">Note</span>';
                    const entry = task.type === 'todo'
                        ? todoEntryHtml(task.item, m.abs_path)
                        : noteEntryHtml(task.item, m.abs_path);
                    return '<div class="task-row">' + chip + jumpBtn + entry + '</div>';
                }).join('');
                tasksHtml = '<div class="scene-tasks-section">' +
                    '<div class="scene-tasks-header"><span class="scene-tasks-label">Tasks</span>' +
                    '<span class="scene-tasks-count">' + allTasks.length + '</span></div>' +
                    rows + '</div>';
            }

            if (fmTodos.length) {
                const lineItems = fmTodos.map(function(t) {
                    return '<li class="scene-todo-item">' + escHtml(t.text) + '</li>';
                }).join('');
                cardHtml += '<div class="scene-todos-section"><div class="scene-todos-label">Scene TODOs (frontmatter)</div><ul class="scene-todos-list">' + lineItems + '</ul></div>';
            }

            // ProseMirror is the only renderer. If the module is still
            // loading, the inline ESM bootstrap at the bottom of the
            // template re-invokes render() once window._PM is ready.
            b.innerHTML = cardHtml + tasksHtml + '<div id="sceneProseHost"></div>';
            if (window._PM) mountProseView(p);
            b.scrollTop = 0;
        }

        function navigateScene(d) {
            _pmEditMode = false;
            saveActiveScrollPosition();
            curIdx = Math.max(0, Math.min(paths.length - 1, curIdx + d));
            updateModal();
            const p = paths[curIdx];
            if (p) {
                routeToHash('/scene/' + encodeURIComponent(p), true);
                restoreActiveScrollPosition();
            }
        }
        function closeSceneModal() {
            saveActiveScrollPosition();
            hideSelectionPill();
            clearSceneSelectionMemory();
            hideInsertAffordance();
            closeAnnotationPopover();
            if (_pmView) { _pmView.destroy(); _pmView = null; }
            _pmEditMode = false;
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) editBar.hidden = true;
            exitFocusMode();
            delete document.documentElement.dataset.view;
            routeToHash('/tab/' + currentTab, true);
            if (typeof updateTerminalShortcuts === 'function') updateTerminalShortcuts();
            restoreActiveScrollPosition();
        }

        function toggleFocusMode() {
            var mc = document.querySelector('#sceneModal .modal-content');
            if (!mc) return;
            var entering = !mc.classList.contains('modal-focus');
            mc.classList.toggle('modal-focus', entering);
            var btn = document.getElementById('modalFocusBtn');
            if (btn) btn.textContent = entering ? '▴' : '▾';
        }

        function exitFocusMode() {
            var mc = document.querySelector('#sceneModal .modal-content');
            if (mc) mc.classList.remove('modal-focus');
            var btn = document.getElementById('modalFocusBtn');
            if (btn) btn.textContent = '▾';
        }

        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey || e.altKey || e.metaKey) return;
            var tag = (e.target.tagName || '').toUpperCase();
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (document.documentElement.dataset.view !== 'scene') return;
            if ((e.key === 'f' || e.key === 'F') && !_pmEditMode) {
                e.preventDefault();
                toggleFocusMode();
            } else if ((e.key === 'e' || e.key === 'E') && !_pmEditMode) {
                e.preventDefault();
                toggleSceneEdit();
            } else if ((e.key === 'b' || e.key === 'B') && !_pmEditMode) {
                e.preventDefault();
                setSidebarOpen(document.documentElement.dataset.sidebar === 'closed');
            }
        });

        function mountProseView(p) {
            if (_pmView) { _pmView.destroy(); _pmView = null; }
            var PM = window._PM;
            if (!PM) return;
            var host = document.getElementById('sceneProseHost');
            if (!host) return;

            var markdown = (contents[p] || '').trim();

            var parser = new PM.MarkdownParser(
                PM.mySchema,
                PM.defaultMarkdownParser.tokenizer,
                Object.assign({}, PM.defaultMarkdownParser.tokens, {
                    html_block: {
                        block: 'annotation',
                        getAttrs: function(tok) { return { raw: tok.content.trim() }; }
                    }
                })
            );

            var doc = parser.parse(markdown);

            var lnPlugin = _buildLnPlugin();
            var plugins = [
                PM.buildHlPlugin(),
                lnPlugin,
                PM.history(),
                PM.keymap(Object.assign({}, PM.baseKeymap, {
                    'Mod-z': PM.undo,
                    'Mod-y': PM.redo,
                    'Mod-Shift-z': PM.redo,
                    'Mod-b': PM.toggleMark(PM.mySchema.marks.strong),
                    'Mod-i': PM.toggleMark(PM.mySchema.marks.em),
                    'Mod-s': function() { saveSceneEdit(); return true; }
                }))
            ];

            var state = PM.EditorState.create({ doc: doc, plugins: plugins });
            _pmView = new PM.EditorView(host, {
                state: state,
                editable: function() { return _pmEditMode; },
                // Keep the cursor away from the very top/bottom of the
                // modal scroll container so arrow-key navigation produces
                // small, frequent scrolls instead of one large jump when
                // the cursor finally hits the edge.
                scrollThreshold: 80,
                scrollMargin: 80,
                // Track unsaved changes so the edit pill / title can show a
                // modified indicator. Only flips on transactions that
                // actually change the document, not selection-only ones.
                dispatchTransaction: function(tr) {
                    var newState = _pmView.state.apply(tr);
                    _pmView.updateState(newState);
                    if (_pmEditMode && tr.docChanged && !_pmDirty) {
                        setPmDirty(true);
                    }
                },
                handleClickOn: function(view, pos, node, nodePos, event, direct) {
                    if (node.type.name === 'annotation' && direct && _pmEditMode) {
                        setTimeout(function() { openAnnotationPopover(nodePos, node); }, 0);
                    }
                    return false;
                }
            });

            initAffordance(_pmView);
            updatePMHighlightDecorations();

            // Tag each top-level block with its source line and apply the
            // toggle's current state (so a freshly-mounted scene reflects
            // the saved preference).
            try {
                var lnSet = _buildLineNumberDecorations(_pmView.state.doc, markdown, (meta[p] && meta[p].txt_line_offset) || 0, meta[p] && meta[p].abs_path);
                if (lnSet) {
                    var tr = _pmView.state.tr.setMeta(lnPluginKey, lnSet);
                    _pmView.dispatch(tr);
                }
            } catch (e) {}
            _applyLineNumbersClass();
            _applyEditingProseClass();
        }

        function updatePMHighlightDecorations() {
            if (!_pmView || !window._PM) return;
            var p = paths[curIdx];
            var PM = window._PM;
            var sceneHls = highlightsByPath[p] || { paragraphs: [], highlights: {} };
            var hlData = sceneHls.highlights || {};
            var doc = _pmView.state.doc;

            var paraNodes = [];
            doc.descendants(function(node, pos) {
                if (node.type.name === 'paragraph') paraNodes.push(pos);
            });

            var decorations = [];
            PASS_ORDER.forEach(function(name) {
                if (!hls[name]) return;
                var insts = hlData[name] || [];
                insts.forEach(function(inst) {
                    var paraIdx = inst.paragraph_index;
                    var offsets = inst.char_offsets;
                    if (!offsets || paraIdx >= paraNodes.length) return;
                    var nodePos = paraNodes[paraIdx];
                    var from = nodePos + 1 + offsets[0];
                    var to = nodePos + 1 + offsets[1];
                    if (from >= to || to > doc.content.size) return;
                    var cls = PASS_CLASSES[name] || '';
                    var title = PASS_LABELS[name] || name;
                    if (inst.note) title += ' (' + inst.note + ')';
                    var attrs = { class: cls, title: title };
                    if (name === 'repeats' && inst.note) attrs['data-count'] = inst.note;
                    decorations.push(PM.Decoration.inline(from, to, attrs));
                });
            });

            var decoSet = PM.DecorationSet.create(doc, decorations);
            var tr = _pmView.state.tr.setMeta(PM.hlPluginKey, decoSet);
            _pmView.dispatch(tr);
        }

        function toggleSceneEdit() {
            if (!window._PM) return;
            if (_pmEditMode) {
                cancelSceneEdit();
                return;
            }
            if (!_pmView) {
                render();
                if (!_pmView) return;
            }
            _pmEditMode = true;
            _pmView.setProps({ editable: function() { return true; } });
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) editBar.hidden = false;
            var btn = document.getElementById('sceneEditBtn');
            if (btn) btn.textContent = '✗ Cancel';
            var p = paths[curIdx];
            _pmOpenMtime = meta[p] && meta[p].mtime;
            setPmDirty(false);
            _applyEditingProseClass();
            _pmView.focus();
        }

        function saveSceneEdit() {
            if (!_pmView || !_pmEditMode) return;
            if (!_pmDirty) return;
            var PM = window._PM;
            var p = paths[curIdx];

            var nodes = Object.assign({}, PM.defaultMarkdownSerializer.nodes, {
                annotation: function(state, node) {
                    state.write(node.attrs.raw);
                    state.closeBlock(node);
                }
            });
            var serializer = new PM.MarkdownSerializer(nodes, PM.defaultMarkdownSerializer.marks);
            var markdown = serializer.serialize(_pmView.state.doc);

            // Stay in edit mode while the request is in flight; reflect
            // progress in the pill instead of yanking the bar away.
            setPmSaving();

            // The save will trigger an SSE "reload" event via the server's
            // file-watcher invalidation. Mark it expected so reloadOrDefer
            // can swallow it (else we'd get a jolting full page reload).
            _pendingSelfReloads++;
            if (_pendingSelfReloadTimer) clearTimeout(_pendingSelfReloadTimer);
            _pendingSelfReloadTimer = setTimeout(function() {
                _pendingSelfReloads = 0;
                _pendingSelfReloadTimer = null;
            }, 4000);

            var absPath = meta[p] && meta[p].abs_path;
            fetch('/save-scene', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ abs_path: absPath, content: markdown, open_mtime: _pmOpenMtime })
            }).then(function(r) {
                if (r.status === 409) {
                    setPmDirty(true);
                    alert('Conflict: the file was modified externally. Close and reopen to reload.');
                    return null;
                }
                return r.json();
            }).then(function(data) {
                if (!data) return;
                if (!data.ok) { setPmDirty(true); return; }
                if (data.mtime) _pmOpenMtime = data.mtime;
                contents[p] = markdown;
                setPmSaved();
                cancelSceneEdit();
            }).catch(function(err) {
                setPmDirty(true);
                alert('Save failed: ' + (err && err.message || 'unknown error'));
            });
        }

        function cancelSceneEdit() {
            _pmEditMode = false;
            setPmDirty(false);
            _applyEditingProseClass();
            hideInsertAffordance();
            closeAnnotationPopover();
            if (_pmView) _pmView.setProps({ editable: function() { return false; } });
            var editBar = document.getElementById('sceneEditBar');
            if (editBar) {
                editBar.hidden = true;
                editBar.classList.remove('is-saving', 'is-saved', 'is-dirty');
            }
            var btn = document.getElementById('sceneEditBtn');
            if (btn) btn.textContent = '✏ Edit';
            var p = paths[curIdx];
            mountProseView(p);
        }

        // ── Confirm-on-discard dialog for Esc-out-of-edit ─────────────────
        // Returns true if the keydown should be considered handled (i.e. we
        // either cancelled cleanly or popped a confirmation; the caller
        // should stop further Esc handlers from also firing).
        function tryEscapeEditMode() {
            if (!_pmEditMode) return false;
            if (!_pmDirty) {
                cancelSceneEdit();
                return true;
            }
            showUnsavedDialog();
            return true;
        }

        var _unsavedDialog = null;
        function showUnsavedDialog() {
            if (_unsavedDialog) return;
            var overlay = document.createElement('div');
            overlay.className = 'unsaved-dialog-overlay';
            overlay.innerHTML =
                '<div class="unsaved-dialog" role="dialog" aria-modal="true" aria-labelledby="unsavedDialogTitle">' +
                    '<div class="unsaved-dialog-title" id="unsavedDialogTitle">Unsaved changes</div>' +
                    '<div class="unsaved-dialog-body">You have unsaved edits in this scene. Save them before exiting edit mode?</div>' +
                    '<div class="unsaved-dialog-actions">' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-cancel" data-action="cancel">Cancel</button>' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-discard" data-action="discard">Discard</button>' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-save" data-action="save">Save</button>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(overlay);
            _unsavedDialog = overlay;
            function close() {
                if (!_unsavedDialog) return;
                document.removeEventListener('keydown', onKey, true);
                _unsavedDialog.remove();
                _unsavedDialog = null;
            }
            function onKey(e) {
                if (e.key === 'Escape') {
                    e.preventDefault(); e.stopPropagation();
                    close();
                } else if (e.key === 'Enter') {
                    e.preventDefault(); e.stopPropagation();
                    close();
                    saveSceneEdit();
                }
            }
            overlay.addEventListener('click', function(e) {
                var btn = e.target.closest('button[data-action]');
                if (!btn && e.target === overlay) { close(); return; }
                if (!btn) return;
                var action = btn.dataset.action;
                close();
                if (action === 'save') {
                    saveSceneEdit();
                } else if (action === 'discard') {
                    cancelSceneEdit();
                }
            });
            document.addEventListener('keydown', onKey, true);
            var saveBtn = overlay.querySelector('.unsaved-dialog-save');
            if (saveBtn) saveBtn.focus();
        }

        function parseAnnotationRaw(raw) {
            var m = raw.match(/^<!--\s*TODO:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: 'TODO', text: m[1] };
            m = raw.match(/^<!--\s*NOTE\[(\w+)\]:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: m[1], text: m[2] };
            m = raw.match(/^<!--\s*NOTE:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: 'NOTE', text: m[1] };
            return { tag: 'TODO', text: raw.replace(/^<!--\s*/, '').replace(/\s*-->$/, '') };
        }

        function buildAnnotationRaw(tag, text) {
            if (tag === 'TODO') return '<!-- TODO: ' + text + ' -->';
            if (tag === 'NOTE') return '<!-- NOTE: ' + text + ' -->';
            return '<!-- NOTE[' + tag + ']: ' + text + ' -->';
        }

        function initAffordance(view) {
            var btn = document.getElementById('pmInsertAffordance');
            if (!btn) return;

            btn.onmouseenter = function() { clearTimeout(_pmAffordanceTimer); };
            btn.onmouseleave = function() { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); };
            btn.onclick = function() {
                if (_pmAffordancePos < 0 || !_pmView) return;
                var PM = window._PM;
                var annotNode = PM.mySchema.nodes.annotation.create({ raw: '<!-- TODO:  -->' });
                var insertPos = _pmAffordancePos;
                var tr = _pmView.state.tr.insert(insertPos, annotNode);
                _pmView.dispatch(tr);
                hideInsertAffordance();
                setTimeout(function() { openAnnotationPopover(insertPos, annotNode); }, 0);
            };

            view.dom.addEventListener('mousemove', function(e) {
                if (!_pmEditMode) { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); return; }
                var p = e.target.closest && e.target.closest('p');
                if (!p || !view.dom.contains(p)) { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); return; }
                clearTimeout(_pmAffordanceTimer);
                if (p !== _pmAffordancePara) {
                    _pmAffordancePara = p;
                    try { _pmAffordancePos = view.posAtDOM(p, 0) - 1; }
                    catch(err) { _pmAffordancePos = -1; }
                }
                if (_pmAffordancePos >= 0) {
                    var rect = p.getBoundingClientRect();
                    btn.style.top = (rect.top + 2) + 'px';
                    btn.style.left = (rect.left - 30) + 'px';
                    btn.hidden = false;
                }
            });

            view.dom.addEventListener('mouseleave', function() {
                _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180);
            });
        }

        function hideInsertAffordance() {
            clearTimeout(_pmAffordanceTimer);
            var btn = document.getElementById('pmInsertAffordance');
            if (btn) btn.hidden = true;
            _pmAffordancePara = null;
            _pmAffordancePos = -1;
        }

        function openAnnotationPopover(nodePos, node) {
            if (!_pmView) return;
            _pmAnnotationPos = nodePos;
            var parsed = parseAnnotationRaw(node.attrs.raw);
            var tagSel = document.getElementById('pmAnnotationTag');
            var textArea = document.getElementById('pmAnnotationText');
            if (tagSel) tagSel.value = parsed.tag;
            if (textArea) textArea.value = parsed.text;

            var popover = document.getElementById('pmAnnotationPopover');
            if (!popover) return;

            try {
                var domRef = _pmView.domAtPos(nodePos + 1);
                var el = domRef.node;
                if (el.nodeType !== 1) el = el.parentElement;
                el = el.closest('.pm-annotation') || el;
                var rect = el.getBoundingClientRect();
                popover.style.top = Math.min(rect.bottom + 4, window.innerHeight - 200) + 'px';
                popover.style.left = Math.min(rect.left, window.innerWidth - 300) + 'px';
            } catch(err) {
                popover.style.top = '200px';
                popover.style.left = '200px';
            }

            popover.hidden = false;
            if (textArea) { textArea.focus(); textArea.select(); }
        }

        function closeAnnotationPopover() {
            var popover = document.getElementById('pmAnnotationPopover');
            if (popover) popover.hidden = true;
            _pmAnnotationPos = -1;
        }

        function saveAnnotationPopover() {
            if (_pmAnnotationPos < 0 || !_pmView) return;
            var tag = (document.getElementById('pmAnnotationTag') || {}).value || 'TODO';
            var text = ((document.getElementById('pmAnnotationText') || {}).value || '').trim();
            var raw = buildAnnotationRaw(tag, text);
            var tr = _pmView.state.tr.setNodeMarkup(_pmAnnotationPos, null, { raw: raw });
            _pmView.dispatch(tr);
            closeAnnotationPopover();
        }

        function deleteAnnotationNode() {
            if (_pmAnnotationPos < 0 || !_pmView) return;
            var node = _pmView.state.doc.nodeAt(_pmAnnotationPos);
            if (!node) return;
            var tr = _pmView.state.tr.delete(_pmAnnotationPos, _pmAnnotationPos + node.nodeSize);
            _pmView.dispatch(tr);
            closeAnnotationPopover();
        }

        window.onclick = e => {
            var popover = document.getElementById('pmAnnotationPopover');
            if (popover && !popover.hidden && !popover.contains(e.target)) {
                closeAnnotationPopover();
            }
        };
        function applyIssueFilter() {
            const f = document.getElementById('issueFilter').value;
            document.querySelectorAll('.ch-row').forEach(r => r.style.display = f === 'all' ? '' : 'none');
            document.querySelectorAll('.scene-row').forEach(r => {
                const d = parseFloat(r.dataset.dlg), s = parseFloat(r.dataset.sent), rp = parseFloat(r.dataset.rep);
                const todos = parseInt(r.dataset.todos || '0', 10);
                const notes = parseInt(r.dataset.notes || '0', 10);
                let show = f === 'all' || (f === 'repetition' && rp > 25) || (f === 'clipped' && s < 8.5) || (f === 'talky' && d > 45) || (f === 'dense' && d < 8) || (f === 'todos' && todos > 0) || (f === 'notes' && notes > 0) || (f.startsWith('status-') && r.dataset.status === f.slice(7));
                r.style.display = show ? '' : 'none';
            });
        }

        // ── Selection pill ───────────────────────────────────────────────────
        let pillDragging = false;
        let pillDragStartX = 0, pillDragStartY = 0;
        let pillCurrentX = 0, pillCurrentY = 0;
        let currentSelectionText = '';
        let currentSelectionRange = null;

        function nodeInsideElement(el, node) {
            if (!el || !node) return false;
            const target = node.nodeType === 3 ? node.parentNode : node;
            return !!(target && el.contains(target));
        }

        function rememberSceneSelection(sel) {
            const modalBody = document.getElementById('modalBody');
            if (!modalBody || !sel || sel.isCollapsed || !sel.rangeCount) return false;
            const text = sel.toString().trim();
            if (!text) return false;
            const range = sel.getRangeAt(0);
            if (
                !nodeInsideElement(modalBody, range.startContainer) ||
                !nodeInsideElement(modalBody, range.endContainer)
            ) {
                return false;
            }
            currentSelectionText = text;
            currentSelectionRange = range.cloneRange();
            return true;
        }

        function restoreSceneSelection() {
            if (!currentSelectionRange || !window.getSelection) return false;
            if (
                !document.body.contains(currentSelectionRange.startContainer) ||
                !document.body.contains(currentSelectionRange.endContainer)
            ) {
                currentSelectionRange = null;
                return false;
            }
            const sel = window.getSelection();
            if (!sel) return false;
            sel.removeAllRanges();
            sel.addRange(currentSelectionRange.cloneRange());
            return true;
        }

        function restoreSceneSelectionSoon() {
            if (!currentSelectionRange) return;
            setTimeout(function() { restoreSceneSelection(); }, 0);
        }

        function clearSceneSelectionMemory() {
            currentSelectionText = '';
            currentSelectionRange = null;
            clearPinnedSelectionHighlight();
        }

        // ── Pinned scene selection highlight ─────────────────────────────
        // The browser only ever shows one Selection at a time, and clicking
        // into the xterm canvas / its hidden textarea moves that selection
        // off the prose. To let the user select text, click into the
        // terminal, type, and then press +sel without losing the visual
        // marker, we paint the saved range with the CSS Custom Highlight
        // API. It survives focus changes because it isn't tied to Selection.
        var PINNED_HL_NAME = 'proseview-pinned-selection';
        var _pinnedHighlight = null;

        function pinSelectionHighlight(range) {
            if (!range) return;
            if (typeof CSS === 'undefined' || !CSS.highlights || typeof Highlight === 'undefined') return;
            try {
                _pinnedHighlight = new Highlight(range);
                CSS.highlights.set(PINNED_HL_NAME, _pinnedHighlight);
            } catch (e) {
                _pinnedHighlight = null;
            }
        }

        function clearPinnedSelectionHighlight() {
            if (typeof CSS !== 'undefined' && CSS.highlights) {
                try { CSS.highlights.delete(PINNED_HL_NAME); } catch (e) {}
            }
            _pinnedHighlight = null;
        }

        function getOrCreatePill() {
            let pill = document.getElementById('selectionPill');
            if (pill) return pill;
            pill = document.createElement('div');
            pill.id = 'selectionPill';
            pill.className = 'selection-pill';
            pill.innerHTML =
                '<button class="selection-pill-btn" id="selectionPillBtn" type="button">···</button>' +
                '<div class="selection-pill-menu" id="selectionPillMenu" hidden>' +
                    '<button class="selection-pill-action" id="selectionEditorBtn" type="button">↗ Open in editor at line</button>' +
                    '<button class="selection-pill-action" id="selectionTodoBtn" type="button">📝 Add TODO</button>' +
                    '<div class="selection-todo-form" id="selectionTodoForm" hidden>' +
                        '<textarea class="selection-todo-textarea" id="selectionTodoText" placeholder="Describe what needs to change..."></textarea>' +
                        '<div class="selection-todo-actions">' +
                            '<button class="selection-todo-copy-btn" id="selectionTodoCopy" type="button">Add to file</button>' +
                            '<button class="selection-todo-cancel-btn" id="selectionTodoCancel" type="button">Cancel</button>' +
                        '</div>' +
                    '</div>' +
                    (SKILLS.length ? '<div style="position:relative"><button class="selection-pill-action" id="selectionSkillsBtn" type="button">&#x2728; Skills &#x25BE;</button><div id="selectionSkillsMenu" class="skills-dropdown" style="display:none;left:100%;top:0;bottom:auto;right:auto;"></div></div>' : '') +
                    '<button class="selection-pill-action" id="selectionCodexBtn" type="button">&#x26A1; Run in Codex</button>' +
                    '<div class="selection-codex-form" id="selectionCodexForm" hidden>' +
                        '<textarea class="selection-todo-textarea" id="selectionCodexInstruction" placeholder="What should Codex do with this passage?" rows="3"></textarea>' +
                        '<label class="selection-codex-autoapprove"><input type="checkbox" id="selectionCodexAutoApprove"> Auto-approve changes</label>' +
                        '<div class="selection-todo-actions">' +
                            '<button class="selection-todo-copy-btn" id="selectionCodexRun" type="button">Run</button>' +
                            '<button class="selection-todo-cancel-btn" id="selectionCodexCancel" type="button">Cancel</button>' +
                        '</div>' +
                    '</div>' +
                    '<button class="selection-pill-action" id="selectionNoteBtn" type="button">📌 Add Note</button>' +
                    '<div class="selection-todo-form" id="selectionNoteForm" hidden>' +
                        '<select class="selection-note-tag" id="selectionNoteTag">' +
                            '<option value="note">note</option>' +
                            '<option value="continuity">continuity</option>' +
                            '<option value="character">character</option>' +
                            '<option value="theme">theme</option>' +
                            '<option value="question">question</option>' +
                        '</select>' +
                        '<textarea class="selection-todo-textarea" id="selectionNoteText" placeholder="Editorial observation..."></textarea>' +
                        '<div class="selection-todo-actions">' +
                            '<button class="selection-todo-copy-btn" id="selectionNoteCopy" type="button">Add to file</button>' +
                            '<button class="selection-todo-cancel-btn" id="selectionNoteCancel" type="button">Cancel</button>' +
                        '</div>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(pill);

            document.getElementById('selectionPillBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                const menu = document.getElementById('selectionPillMenu');
                const isOpen = !menu.hidden;
                menu.hidden = isOpen;
                if (!isOpen) {
                    document.getElementById('selectionTodoForm').hidden = true;
                    document.getElementById('selectionTodoText').value = '';
                    document.getElementById('selectionNoteForm').hidden = true;
                    document.getElementById('selectionNoteText').value = '';
                }
            });

            document.getElementById('selectionEditorBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                const selText = (window.getSelection() || {}).toString ? window.getSelection().toString().trim() : '';
                let line = (m.txt_line_offset || 0) + 1;
                if (selText && contents[p]) {
                    const needle = selText.substring(0, 50);
                    const idx = contents[p].indexOf(needle);
                    if (idx >= 0) line = (m.txt_line_offset || 0) + contents[p].substring(0, idx).split('\n').length;
                }
                window.open(buildEditorUrl(m.abs_path, line), '_blank');
                hideSelectionPill();
            });

            document.getElementById('selectionTodoBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionTodoForm').hidden = false;
                document.getElementById('selectionTodoText').focus();
            });

            document.getElementById('selectionTodoCopy').addEventListener('click', function(e) {
                e.stopPropagation();
                const todoText = document.getElementById('selectionTodoText').value.trim();
                if (!todoText) return;
                const btn = document.getElementById('selectionTodoCopy');
                function flash(msg) {
                    const orig = btn.textContent;
                    btn.textContent = msg || orig;
                    btn.disabled = true;
                    setTimeout(function() { btn.textContent = orig; btn.disabled = false; }, 1800);
                }
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                btn.disabled = true;
                fetch('/insert-todo', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        abs_path: m.abs_path,
                        selection_text: currentSelectionText,
                        txt_line_offset: m.txt_line_offset || 0,
                        todo_text: todoText,
                    })
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.ok) {
                        flash('Added!');
                        setTimeout(function() { location.reload(); }, 700);
                    } else {
                        btn.disabled = false;
                        alert('Could not insert TODO: ' + (data.error || 'unknown error'));
                    }
                }).catch(function(err) {
                    btn.disabled = false;
                    alert('Request failed: ' + err);
                });
            });

            document.getElementById('selectionTodoCancel').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionTodoText').value = '';
                document.getElementById('selectionTodoForm').hidden = true;
            });

            document.getElementById('selectionNoteBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionNoteForm').hidden = false;
                document.getElementById('selectionNoteText').focus();
            });

            document.getElementById('selectionNoteCopy').addEventListener('click', function(e) {
                e.stopPropagation();
                const noteText = document.getElementById('selectionNoteText').value.trim();
                if (!noteText) return;
                const tag = document.getElementById('selectionNoteTag').value;
                const btn = document.getElementById('selectionNoteCopy');
                function flash(msg) {
                    const orig = btn.textContent;
                    btn.textContent = msg;
                    btn.disabled = true;
                    setTimeout(function() { btn.textContent = orig; btn.disabled = false; }, 1800);
                }
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                btn.disabled = true;
                fetch('/add-note', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        abs_path: m.abs_path,
                        selection_text: currentSelectionText,
                        txt_line_offset: m.txt_line_offset || 0,
                        note_text: noteText,
                        tag: tag,
                    })
                }).then(function(r) { return r.json(); }).then(function(data) {
                    if (data.ok) {
                        flash('Added!');
                        setTimeout(function() { location.reload(); }, 700);
                    } else {
                        btn.disabled = false;
                        alert('Could not insert note: ' + (data.error || 'unknown error'));
                    }
                }).catch(function(err) {
                    btn.disabled = false;
                    alert('Request failed: ' + err);
                });
            });

            document.getElementById('selectionNoteCancel').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionNoteText').value = '';
                document.getElementById('selectionNoteForm').hidden = true;
            });

            if (SKILLS.length) {
                document.getElementById('selectionSkillsBtn').addEventListener('click', function(e) {
                    e.stopPropagation();
                    var menu = document.getElementById('selectionSkillsMenu');
                    var isOpen = menu.style.display !== 'none';
                    menu.style.display = isOpen ? 'none' : 'block';
                    if (!isOpen) {
                        menu.innerHTML = '';
                        var snippetSkills = SKILLS.filter(function(s) { return s.type === 'snippet'; });
                        snippetSkills.forEach(function(skill) {
                            var btn = document.createElement('button');
                            btn.className = 'skills-dropdown-item';
                            btn.textContent = skill.display_name;
                            btn.title = skill.short_description;
                            btn.onclick = function(ev) {
                                ev.stopPropagation();
                                menu.style.display = 'none';
                                if (curIdx < 0) return;
                                var p = paths[curIdx], m = meta[p];
                                if (!m) return;
                                var sel = currentSelectionText.trim();
                                var prompt = skill.default_prompt
                                    + (sel ? '\n\n"' + sel + '"' : '')
                                    + '\n\nin @' + p;
                                hideSelectionPill();
                                openCodexTerminal(prompt, m.abs_path, false, p);
                            };
                            menu.appendChild(btn);
                        });
                    }
                });
            }

            document.getElementById('selectionCodexBtn').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionCodexForm').hidden = false;
                document.getElementById('selectionCodexInstruction').focus();
            });

            document.getElementById('selectionCodexRun').addEventListener('click', function(e) {
                e.stopPropagation();
                if (curIdx < 0) return;
                const p = paths[curIdx];
                const m = meta[p];
                if (!m) return;
                const sel = currentSelectionText.trim();
                if (!sel) {
                    alert('Select some text in the scene first.');
                    return;
                }
                const instruction = document.getElementById('selectionCodexInstruction').value.trim();
                const autoApprove = document.getElementById('selectionCodexAutoApprove').checked;
                const fullPrompt = instruction
                    ? 'Run ' + instruction + ' on "' + sel + '" in @' + p
                    : 'Review "' + sel + '" in @' + p;
                hideSelectionPill();
                openCodexTerminal(fullPrompt, m.abs_path, autoApprove, p);
            });

            document.getElementById('selectionCodexCancel').addEventListener('click', function(e) {
                e.stopPropagation();
                document.getElementById('selectionCodexInstruction').value = '';
                document.getElementById('selectionCodexForm').hidden = true;
            });

            // Drag: only when clicking the pill background (not a button/textarea)
            pill.addEventListener('mousedown', function(e) {
                if (e.target.closest('button') || e.target.tagName === 'TEXTAREA') return;
                pillDragging = true;
                pillDragStartX = e.clientX - pillCurrentX;
                pillDragStartY = e.clientY - pillCurrentY;
                e.preventDefault();
            });

            return pill;
        }

        function collapseSelectionPillMenu() {
            const menu = document.getElementById('selectionPillMenu');
            if (menu) menu.hidden = true;
            ['selectionTodoForm', 'selectionNoteForm', 'selectionCodexForm'].forEach(function(id) {
                const el = document.getElementById(id);
                if (el) el.hidden = true;
            });
            ['selectionTodoText', 'selectionNoteText', 'selectionCodexInstruction'].forEach(function(id) {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            const skillsMenu = document.getElementById('selectionSkillsMenu');
            if (skillsMenu) skillsMenu.style.display = 'none';
        }

        function showSelectionPill(x, y, selText) {
            currentSelectionText = selText || '';
            const pill = getOrCreatePill();
            collapseSelectionPillMenu();
            pillCurrentX = Math.min(x, window.innerWidth - 160);
            pillCurrentY = Math.min(y + 8, window.innerHeight - 50);
            pill.style.left = pillCurrentX + 'px';
            pill.style.top = pillCurrentY + 'px';
            pill.style.display = 'flex';
        }

        function hideSelectionPill() {
            const pill = document.getElementById('selectionPill');
            if (pill) pill.style.display = 'none';
            collapseSelectionPillMenu();
        }

        function initSelectionPill() {
            const modalBody = document.getElementById('modalBody');
            if (!modalBody) return;

            modalBody.addEventListener('mouseup', function(e) {
                const pill = document.getElementById('selectionPill');
                if (pill && pill.contains(e.target)) return;
                setTimeout(function() {
                    const sel = window.getSelection();
                    if (!rememberSceneSelection(sel)) {
                        hideSelectionPill();
                        return;
                    }
                    // The live browser selection is what the user sees right
                    // now; drop any old pinned highlight so we don't paint
                    // two ranges. We re-pin only when focus is about to
                    // leave the prose (e.g., user clicks into the terminal).
                    clearPinnedSelectionHighlight();
                    const range = currentSelectionRange;
                    const rect = range.getBoundingClientRect();
                    showSelectionPill(rect.right, rect.bottom, currentSelectionText);
                }, 10);
            });

            document.addEventListener('mousedown', function(e) {
                const pill = document.getElementById('selectionPill');
                if (!pill || pill.style.display === 'none') return;
                if (e.target.closest('#terminalPanel')) return;
                if (!pill.contains(e.target) && !e.target.closest('#modalBody')) {
                    hideSelectionPill();
                    clearSceneSelectionMemory();
                }
            });

            const terminalPanel = document.getElementById('terminalPanel');
            if (terminalPanel) {
                let terminalMouseDown = null;
                terminalPanel.addEventListener('mousedown', function(e) {
                    // Snapshot the current prose selection AND paint it as a
                    // pinned highlight before xterm steals focus. The pinned
                    // highlight is what the user actually sees while they
                    // type into the terminal; the snapshot is what +sel
                    // pastes if the live Selection has been cleared by then.
                    if (window.getSelection) {
                        rememberSceneSelection(window.getSelection());
                    }
                    if (currentSelectionRange) {
                        pinSelectionHighlight(currentSelectionRange);
                    }
                    terminalMouseDown = {x: e.clientX, y: e.clientY};
                }, true);
                terminalPanel.addEventListener('mouseup', function(e) {
                    if (!terminalMouseDown) return;
                    terminalMouseDown = null;
                    // Intentionally do NOT call restoreSceneSelection here.
                    // Restoring the live Selection moves focus/caret back
                    // into the prose. In edit mode the prose is a
                    // contenteditable ProseMirror, so the next keystroke
                    // would type into the editor (and replace any selected
                    // range) instead of going to the terminal. The pinned
                    // CSS highlight already shows the user where their
                    // selection was, and +sel reads from the cached
                    // currentSelectionText snapshot, so we don't need the
                    // live Selection at all.
                }, true);
                // Prevent terminal header buttons from stealing focus (and clearing prose selection)
                var termHeader = terminalPanel.querySelector('.terminal-header');
                if (termHeader) {
                    termHeader.addEventListener('mousedown', function(e) {
                        if (e.target.closest('button')) e.preventDefault();
                    });
                }
            }

            document.addEventListener('mousemove', function(e) {
                if (!pillDragging) return;
                pillCurrentX = e.clientX - pillDragStartX;
                pillCurrentY = e.clientY - pillDragStartY;
                const pill = document.getElementById('selectionPill');
                if (pill) { pill.style.left = pillCurrentX + 'px'; pill.style.top = pillCurrentY + 'px'; }
            });

            document.addEventListener('mouseup', function() { pillDragging = false; });

            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') hideSelectionPill();
            });
        }

        // Global Esc -> exit edit mode (with unsaved-changes confirmation).
        // Capture phase so we run before any popover/selection handlers and
        // before ProseMirror's keymap.
        document.addEventListener('keydown', function(e) {
            if (e.key !== 'Escape') return;
            // Don't interfere if our own confirmation dialog is up; it has
            // its own Esc handler.
            if (_unsavedDialog) return;
            if (tryEscapeEditMode()) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);

        initSelectionPill();

        var _pendingReload = false;
        var _refreshTimer = null;
        var _refreshInFlight = false;
        var _refreshQueued = false;
        const TERMINAL_REFRESH_DEBOUNCE_MS = 150;

        function setPendingIndicator(visible) {
            var indicator = document.getElementById('termReloadIndicator');
            if (indicator) { indicator.hidden = !visible; }
        }

        function reloadOrDefer() {
            // Always do a partial refresh instead of location.reload() —
            // a full reload jolts the viewport (jump to top, then
            // scroll-restore back) and tears down the live editor. This
            // covers both self-saves and external file edits.
            // refreshContent() is a no-op for the open modal while
            // _pmEditMode is true so the editor stays mounted.
            if (_pendingSelfReloads > 0) _pendingSelfReloads--;
            refreshContent();
        }

        function scheduleContentRefresh(delay) {
            if (_termSessions.length === 0) {
                location.reload();
                return;
            }
            _pendingReload = true;
            if (_refreshInFlight) {
                _refreshQueued = true;
                setPendingIndicator(true);
                return;
            }
            if (_refreshTimer) clearTimeout(_refreshTimer);
            _refreshTimer = setTimeout(function() {
                _refreshTimer = null;
                refreshContent();
            }, delay);
        }

        function refreshContent() {
            if (_refreshInFlight) {
                _refreshQueued = true;
                _pendingReload = true;
                setPendingIndicator(true);
                return;
            }
            if (_refreshTimer) {
                clearTimeout(_refreshTimer);
                _refreshTimer = null;
            }
            _refreshInFlight = true;
            var refreshSucceeded = false;
            fetch('/data.json').then(function(r) {
                if (!r.ok) throw new Error('Refresh failed: ' + r.status);
                return r.json();
            }).then(function(data) {
                if (data.contents) contents = data.contents;
                if (data.meta) meta = data.meta;
                if (data.highlightsByPath) highlightsByPath = data.highlightsByPath;
                refreshSucceeded = true;
                // re-render scene view if open, but never while we're in
                // edit mode -- that would tear down the live ProseMirror
                // view and drop the user's cursor mid-edit.
                if (document.documentElement.dataset.view === 'scene' && curIdx >= 0 && !_pmEditMode) {
                    updateModal();
                }
            }).catch(function() {
                _pendingReload = true;
                setPendingIndicator(true);
            }).finally(function() {
                _refreshInFlight = false;
                if (!refreshSucceeded) return;
                if (_refreshQueued) {
                    _refreshQueued = false;
                    scheduleContentRefresh(0);
                } else {
                    setPendingIndicator(false);
                }
            });
        }

        function hotSwapCss() {
            fetch('/app.css?t=' + Date.now(), { cache: 'no-store' })
                .then(function(r) { return r.text(); })
                .then(function(css) {
                    var styleEl = document.getElementById('proseview-app-css');
                    if (styleEl) styleEl.textContent = css;
                })
                .catch(function() {});
        }

        function showAssetReloadBanner() {
            // Terminal sessions now reattach across reload (server keeps the
            // PTYs alive, client replays the scrollback). The only thing a
            // reload destroys is an in-progress unsaved edit. So we only
            // surface the banner when the user is in edit mode -- otherwise
            // just refresh silently.
            var editing = (typeof _pmEditMode !== 'undefined') && _pmEditMode;
            if (!editing) {
                location.reload();
                return;
            }
            if (document.getElementById('assetReloadBanner')) return;
            var banner = document.createElement('div');
            banner.id = 'assetReloadBanner';
            banner.className = 'asset-reload-banner';
            banner.innerHTML =
                '<span class="asset-reload-banner-msg">Page assets updated</span>' +
                '<button type="button" class="asset-reload-banner-btn" onclick="location.reload()">Reload</button>' +
                '<button type="button" class="asset-reload-banner-dismiss" title="Dismiss" onclick="this.parentElement.remove()">&times;</button>';
            document.body.appendChild(banner);
        }

        (function connectSSE() {
            const es = new EventSource('/events');
            es.onmessage = function(e) {
                if (!e.data) return;
                if (e.data === 'reload' || e.data === 'reload:content') {
                    reloadOrDefer();
                } else if (e.data === 'reload:css') {
                    hotSwapCss();
                } else if (e.data === 'reload:html' || e.data === 'reload:js') {
                    showAssetReloadBanner();
                }
            };
            es.onerror = function() {
                es.close();
                setTimeout(connectSSE, 3000);
            };
        })();

        // ── In-browser terminal (multi-tab) ─────────────────────────────────
        // Each session has its own xterm instance, EventSource, PTY id, and mount div.
        // Inactive tabs stay alive — only the active mount is visible.
        var _termSessions = [];        // [{id, label, type, termId, xterm, fit, es, send, contextFile, contextSel, mountEl, ...}]
        var _termActiveId = null;      // local id of active session
        var _termSeq = { shell: 0, codex: 0, claude: 0, gemini: 0 };
        // Globals below are mirrors of the active session, kept for backward-compat
        // with terminalInsertSel / terminalInsertFile / presets / skills.
        var _termId = null;
        var _termXterm = null;
        var _termES = null;
        var _termFit = null;
        var _termSend = null;
        var _termContextFile = null;
        var _termContextSel = null;

        function _activeSession() {
            for (var i = 0; i < _termSessions.length; i++) {
                if (_termSessions[i].id === _termActiveId) return _termSessions[i];
            }
            return null;
        }

        function _syncActiveGlobals() {
            var s = _activeSession();
            _termId = s ? s.termId : null;
            _termXterm = s ? s.xterm : null;
            _termES = s ? s.es : null;
            _termFit = s ? s.fit : null;
            _termSend = s ? s.send : null;
            _termContextFile = s ? s.contextFile : null;
            _termContextSel = s ? s.contextSel : null;
            updateTerminalShortcuts();
        }

        function _renderTabs() {
            var bar = document.getElementById('terminalTabs');
            if (!bar) return;
            bar.innerHTML = '';
            _termSessions.forEach(function(s) {
                var tab = document.createElement('div');
                tab.className = 'terminal-tab' + (s.id === _termActiveId ? ' active' : '');
                tab.title = s.contextFile ? (s.label + ' — ' + s.contextFile) : s.label;
                var label = document.createElement('span');
                label.className = 'terminal-tab-label';
                label.textContent = s.label;
                label.onclick = function() { _setActiveSession(s.id); };
                var closeBtn = document.createElement('button');
                closeBtn.className = 'terminal-tab-close';
                closeBtn.innerHTML = '&times;';
                closeBtn.title = 'Close ' + s.label;
                closeBtn.onclick = function(e) { e.stopPropagation(); _closeSession(s.id); };
                tab.appendChild(label);
                tab.appendChild(closeBtn);
                bar.appendChild(tab);
            });
        }

        function _setActiveSession(id) {
            _termActiveId = id;
            _termSessions.forEach(function(s) {
                s.mountEl.hidden = (s.id !== id);
            });
            _syncActiveGlobals();
            _renderTabs();
            var s = _activeSession();
            if (s && s.fit) requestAnimationFrame(function() { try { s.fit.fit(); } catch(e) {} });
            if (s && s.xterm) try { s.xterm.focus(); } catch(e) {}
            _persistTermSessions();
        }

        // ── Cross-reload terminal persistence ─────────────────────────────
        // The PTY processes are owned by the server, so they outlive a
        // browser reload. We mirror just enough metadata in localStorage
        // to rebuild the tab UI on the next page load and re-subscribe to
        // each PTY's output stream (the server replays its scrollback
        // buffer as the first SSE frame, see TerminalSession.subscribe).
        var _TERM_STATE_KEY = 'proseview-terminal-state';
        function _persistTermSessions() {
            try {
                var payload = {
                    sessions: _termSessions
                        .filter(function(s) { return !!s.termId; })
                        .map(function(s) {
                            return {
                                id: s.id, termId: s.termId,
                                type: s.type, label: s.label,
                                contextFile: s.contextFile || null,
                                contextSel: s.contextSel || null
                            };
                        }),
                    activeId: _termActiveId,
                    seq: _termSeq
                };
                if (payload.sessions.length === 0) {
                    localStorage.removeItem(_TERM_STATE_KEY);
                } else {
                    localStorage.setItem(_TERM_STATE_KEY, JSON.stringify(payload));
                }
            } catch(e) {}
        }

        function _reattachTerminals() {
            var saved = null;
            try { saved = JSON.parse(localStorage.getItem(_TERM_STATE_KEY) || 'null'); } catch(e) { saved = null; }
            if (!saved || !Array.isArray(saved.sessions) || saved.sessions.length === 0) return;

            fetch('/terminal-list').then(function(r) { return r.json(); }).then(function(data) {
                if (!data || !data.ok || !Array.isArray(data.sessions)) {
                    // Server forgot about these (probably restarted). Drop stale state.
                    try { localStorage.removeItem(_TERM_STATE_KEY); } catch(e) {}
                    return;
                }
                var liveByTid = {};
                data.sessions.forEach(function(s) { liveByTid[s.id] = s; });

                var panel = document.getElementById('terminalPanel');
                var mounts = document.getElementById('terminalMounts');
                if (!panel || !mounts) return;

                var restored = [];
                saved.sessions.forEach(function(ss) {
                    if (!ss.termId || !liveByTid[ss.termId]) return;
                    var mountEl = document.createElement('div');
                    mountEl.className = 'terminal-tab-mount';
                    mounts.appendChild(mountEl);
                    var session = {
                        id: ss.id, label: ss.label, type: ss.type, termId: ss.termId,
                        xterm: null, fit: null, es: null, send: null,
                        contextFile: ss.contextFile || null,
                        contextSel: ss.contextSel || null,
                        mountEl: mountEl
                    };
                    _termSessions.push(session);
                    // Pass null prompt: the original initial prompt was
                    // already sent in the previous session, the replayed
                    // scrollback shows it.
                    _initSessionXterm(session, null);
                    restored.push(session);
                });

                if (restored.length === 0) {
                    try { localStorage.removeItem(_TERM_STATE_KEY); } catch(e) {}
                    return;
                }

                if (saved.seq && typeof saved.seq === 'object') {
                    for (var k in saved.seq) {
                        if (Object.prototype.hasOwnProperty.call(saved.seq, k) && typeof saved.seq[k] === 'number') {
                            _termSeq[k] = Math.max(_termSeq[k] || 0, saved.seq[k]);
                        }
                    }
                }

                panel.hidden = false;
                _applyTerminalDock();

                var preferred = saved.activeId;
                var activeFound = restored.some(function(s) { return s.id === preferred; });
                _setActiveSession(activeFound ? preferred : restored[0].id);
                _persistTermSessions();
            }).catch(function() {});
        }

        function _closeSession(id) {
            var idx = -1;
            for (var i = 0; i < _termSessions.length; i++) if (_termSessions[i].id === id) { idx = i; break; }
            if (idx < 0) return;
            var s = _termSessions[idx];
            if (s.termId) {
                fetch('/terminal-kill', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({id: s.termId})
                }).catch(function() {});
            }
            if (s.es) try { s.es.close(); } catch(e) {}
            if (s.xterm) try { s.xterm.dispose(); } catch(e) {}
            if (s.mountEl && s.mountEl.parentNode) s.mountEl.parentNode.removeChild(s.mountEl);
            _termSessions.splice(idx, 1);
            _persistTermSessions();
            if (_termSessions.length === 0) {
                _termActiveId = null;
                _syncActiveGlobals();
                _renderTabs();
                document.getElementById('terminalPanel').hidden = true;
                document.body.classList.remove('terminal-right-open');
                if (_pendingReload) { _pendingReload = false; location.reload(); }
                return;
            }
            if (_termActiveId === id) {
                var next = _termSessions[Math.max(0, idx - 1)];
                _setActiveSession(next.id);
            } else {
                _renderTabs();
            }
        }

        function _spawnSession(type, command, contextFile, contextSel, initialPrompt) {
            var panel = document.getElementById('terminalPanel');
            panel.hidden = false;
            _applyTerminalDock();
            var seq = ++_termSeq[type];
            var label = type.charAt(0).toUpperCase() + type.slice(1) + ' ' + seq;
            var localId = type + '-' + seq;
            var mounts = document.getElementById('terminalMounts');
            var mountEl = document.createElement('div');
            mountEl.className = 'terminal-tab-mount';
            mounts.appendChild(mountEl);

            var session = {
                id: localId, label: label, type: type, termId: null,
                xterm: null, fit: null, es: null, send: null,
                contextFile: contextFile || null, contextSel: contextSel || null,
                mountEl: mountEl
            };
            _termSessions.push(session);
            _setActiveSession(localId);

            fetch('/terminal-spawn', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    command: command, rows: 40, cols: 160,
                    type: type, label: label
                })
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (!data.ok) {
                    alert('Could not start ' + type + ': ' + (data.error || 'unknown error'));
                    _closeSession(localId);
                    return;
                }
                session.termId = data.id;
                _initSessionXterm(session, initialPrompt);
                if (session.id === _termActiveId) _syncActiveGlobals();
                _persistTermSessions();
            }).catch(function(err) {
                alert('Failed to spawn terminal: ' + err);
                _closeSession(localId);
            });
        }

        // ── Terminal font size ───────────────────────────────────────────
        // Persisted to localStorage and applied to every xterm instance
        // (existing + newly spawned + reattached).
        var TERM_FONT_KEY = 'proseview-terminal-fontsize';
        var TERM_FONT_DEFAULT = 13;
        var TERM_FONT_MIN = 10;
        var TERM_FONT_MAX = 22;
        function _normalizeTermFontSize(v) {
            var n = parseInt(v, 10);
            if (!isFinite(n)) return TERM_FONT_DEFAULT;
            return Math.max(TERM_FONT_MIN, Math.min(TERM_FONT_MAX, n));
        }
        function _loadTermFontSize() {
            try { return _normalizeTermFontSize(localStorage.getItem(TERM_FONT_KEY)); }
            catch(e) { return TERM_FONT_DEFAULT; }
        }
        function updateTerminalFontSize(v) {
            var size = _normalizeTermFontSize(v);
            try { localStorage.setItem(TERM_FONT_KEY, String(size)); } catch(e) {}
            var slider = document.getElementById('terminalFontSize');
            if (slider) slider.value = String(size);
            _termSessions.forEach(function(s) {
                if (!s.xterm) return;
                try { s.xterm.options.fontSize = size; } catch(e) {}
                if (s.fit) requestAnimationFrame(function() { try { s.fit.fit(); } catch(e) {} });
            });
        }
        // Initialise the slider from storage as soon as the script runs.
        (function() {
            var slider = document.getElementById('terminalFontSize');
            if (slider) slider.value = String(_loadTermFontSize());
        })();

        function _initSessionXterm(session, initialPrompt) {
            var mount = session.mountEl;
            var termOpts = {
                cursorBlink: true,
                fontSize: _loadTermFontSize(),
                fontFamily: 'Menlo, Monaco, "Cascadia Code", "Courier New", monospace',
                theme: {
                    background: '#0d1117', foreground: '#c9d1d9',
                    cursor: '#58a6ff', selectionBackground: 'rgba(88,166,255,0.25)',
                    black: '#484f58', red: '#ff7b72', green: '#3fb950',
                    yellow: '#d29922', blue: '#58a6ff', magenta: '#bc8cff',
                    cyan: '#39c5cf', white: '#b1bac4',
                    brightBlack: '#6e7681', brightRed: '#ffa198', brightGreen: '#56d364',
                    brightYellow: '#e3b341', brightBlue: '#79c0ff', brightMagenta: '#d2a8ff',
                    brightCyan: '#56d4dd', brightWhite: '#f0f6fc',
                },
                allowTransparency: false,
                scrollback: 5000,
            };
            var term = (typeof Terminal !== 'undefined') ? new Terminal(termOpts) : null;
            if (!term) { mount.textContent = 'xterm.js not loaded -- check network connection'; return; }
            session.xterm = term;

            var fitAddon = (typeof FitAddon !== 'undefined') ? new FitAddon.FitAddon() : null;
            if (fitAddon) { term.loadAddon(fitAddon); session.fit = fitAddon; }
            term.open(mount);
            if (fitAddon) {
                requestAnimationFrame(function() { try { fitAddon.fit(); } catch(e) {} });
                var ro = new ResizeObserver(function() { try { fitAddon.fit(); } catch(e) {} });
                ro.observe(mount);
            }

            var tid = session.termId;
            function sendToTerm(str) {
                var bytes = new TextEncoder().encode(str);
                var binary = '';
                bytes.forEach(function(b) { binary += String.fromCharCode(b); });
                fetch('/terminal-input', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({id: tid, data: btoa(binary)})
                }).catch(function() {});
            }
            session.send = sendToTerm;

            term.onData(function(data) { sendToTerm(data); });
            term.onResize(function(sz) {
                fetch('/terminal-resize', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({id: tid, rows: sz.rows, cols: sz.cols})
                }).catch(function() {});
            });

            var es = new EventSource('/terminal-output/' + tid);
            session.es = es;
            var promptSent = false, idleTimer = null;
            var maxWaitTimer = initialPrompt ? setTimeout(function() {
                if (!promptSent) { promptSent = true; clearTimeout(idleTimer); sendToTerm(initialPrompt + '\n'); }
            }, 6000) : null;
            es.onmessage = function(ev) {
                if (ev.data === 'connected') return;
                if (ev.data === '__exit__') {
                    term.write('\r\n\x1b[33m[process exited]\x1b[0m\r\n');
                    es.close();
                    return;
                }
                try {
                    var binary = atob(ev.data);
                    var bytes = new Uint8Array(binary.length);
                    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                    term.write(bytes);
                } catch(e) {}
                if (initialPrompt && !promptSent) {
                    clearTimeout(idleTimer);
                    idleTimer = setTimeout(function() {
                        if (!promptSent) {
                            promptSent = true;
                            clearTimeout(maxWaitTimer);
                            sendToTerm(initialPrompt + '\n');
                        }
                    }, 400);
                }
            };
            es.onerror = function() {
                term.write('\r\n\x1b[31m[connection lost]\x1b[0m\r\n');
                es.close();
            };
        }

        // ── Terminal docking (bottom | right) ────────────────────────────────
        var _termDock = 'bottom';
        try {
            var savedDock = localStorage.getItem('proseview-terminal-dock');
            if (savedDock === 'right' || savedDock === 'bottom') _termDock = savedDock;
        } catch(e) {}

        function _applyTerminalDock() {
            var panel = document.getElementById('terminalPanel');
            if (!panel) return;
            panel.classList.toggle('dock-bottom', _termDock === 'bottom');
            panel.classList.toggle('dock-right', _termDock === 'right');
            var rightOpen = (_termDock === 'right') && !panel.hidden;
            document.body.classList.toggle('terminal-right-open', rightOpen);
            // Refit every session — orientation change resizes both axes.
            _termSessions.forEach(function(s) {
                if (s.fit) requestAnimationFrame(function() { try { s.fit.fit(); } catch(e) {} });
            });
        }

        function toggleTerminalDock() {
            _termDock = (_termDock === 'bottom') ? 'right' : 'bottom';
            try { localStorage.setItem('proseview-terminal-dock', _termDock); } catch(e) {}
            _applyTerminalDock();
        }
        _applyTerminalDock();  // restore from localStorage on load
        // Try to rebuild terminal tabs that were live before this page load.
        // If the server still has the PTY sessions in memory, each tab
        // re-mounts an xterm and gets its scrollback replayed via SSE.
        _reattachTerminals();

        // Drag-to-resize the terminal panel (axis depends on dock mode)
        (function() {
            var handle = document.getElementById('terminalResizeHandle');
            if (!handle) return;
            var dragging = false, startCoord = 0, startSize = 0, axis = 'y';
            handle.addEventListener('mousedown', function(e) {
                dragging = true;
                axis = (_termDock === 'right') ? 'x' : 'y';
                var panel = document.getElementById('terminalPanel');
                if (axis === 'y') {
                    startCoord = e.clientY;
                    startSize = panel.offsetHeight;
                } else {
                    startCoord = e.clientX;
                    startSize = panel.offsetWidth;
                }
                handle.classList.add('is-dragging');
                document.body.style.userSelect = 'none';
                e.preventDefault();
            });
            document.addEventListener('mousemove', function(e) {
                if (!dragging) return;
                var html = document.documentElement;
                if (axis === 'y') {
                    var newH = Math.max(150, Math.min(window.innerHeight - 80, startSize + (startCoord - e.clientY)));
                    html.style.setProperty('--terminal-h', newH + 'px');
                } else {
                    var newW = Math.max(320, Math.min(window.innerWidth - 200, startSize + (startCoord - e.clientX)));
                    html.style.setProperty('--terminal-w', newW + 'px');
                }
            });
            document.addEventListener('mouseup', function() {
                if (dragging) {
                    dragging = false;
                    handle.classList.remove('is-dragging');
                    document.body.style.userSelect = '';
                    // Refit active session after drag ends
                    var s = _activeSession();
                    if (s && s.fit) try { s.fit.fit(); } catch(e) {}
                }
            });
        })();

        function openSceneInCodex() {
            if (curIdx < 0) return;
            var p = paths[curIdx], m = meta[p];
            if (m) openCodexTerminal(null, m.abs_path, false, p);
        }

        function openFileInCodex() {
            var titleEl = document.getElementById('filePreviewTitle');
            var p = titleEl ? titleEl.textContent.trim() : '';
            if (!p) return;
            var node = repoFileByPath[p];
            openCodexTerminal(null, node ? node.abs_path : null, false, p);
        }

        function openSceneInClaude() {
            if (curIdx < 0) return;
            var p = paths[curIdx], m = meta[p];
            if (m) openClaudeTerminal(null, m.abs_path, p);
        }

        function openFileInClaude() {
            var titleEl = document.getElementById('filePreviewTitle');
            var p = titleEl ? titleEl.textContent.trim() : '';
            if (!p) return;
            var node = repoFileByPath[p];
            openClaudeTerminal(null, node ? node.abs_path : null, p);
        }

        function openShellTerminal() {
            _spawnSession('shell', [], null, null, null);
        }

        function openCodexTerminal(prompt, absPath, autoApprove, relPath) {
            var command = autoApprove ? ['codex', '--full-auto'] : ['codex'];
            _spawnSession('codex', command, relPath || null, currentSelectionText || null, prompt);
        }

        function openClaudeTerminal(prompt, absPath, relPath) {
            _spawnSession('claude', ['claude'], relPath || null, currentSelectionText || null, prompt);
        }

        function openSceneInGemini() {
            if (curIdx < 0) return;
            var p = paths[curIdx], m = meta[p];
            if (m) openGeminiTerminal(null, m.abs_path, p);
        }

        function openFileInGemini() {
            var titleEl = document.getElementById('filePreviewTitle');
            var p = titleEl ? titleEl.textContent.trim() : '';
            if (!p) return;
            var node = repoFileByPath[p];
            openGeminiTerminal(null, node ? node.abs_path : null, p);
        }

        function openGeminiTerminal(prompt, absPath, relPath) {
            _spawnSession('gemini', ['gemini'], relPath || null, currentSelectionText || null, prompt);
        }

        function closeAgentMenus() {
            ['agentMenuFile', 'agentMenuScene'].forEach(function(id) {
                var m = document.getElementById(id);
                if (m) m.style.display = 'none';
            });
        }

        function toggleAgentMenu(surface) {
            var id = surface === 'scene' ? 'agentMenuScene' : 'agentMenuFile';
            var btnId = surface === 'scene' ? 'agentMenuSceneBtn' : 'agentMenuFileBtn';
            var menu = document.getElementById(id);
            if (!menu) return;
            var open = menu.style.display !== 'none';
            closeAgentMenus();
            if (open) return;
            menu.style.display = 'block';
            setTimeout(function() {
                document.addEventListener('click', function close(e) {
                    if (!e.target.closest('#' + id) && e.target.id !== btnId) {
                        menu.style.display = 'none';
                        document.removeEventListener('click', close);
                    }
                });
            }, 0);
        }

        // Shared template for the +polish button and the "Polish" preset.
        // Sets scope discipline up front so the agent reads broadly for
        // context but doesn't drift into edits the user didn't ask for.
        // Stays on a single line so the user can append their specific
        // request and press Enter.
        function _polishPromptFile(f) {
            return (
                'Polish in @' + f + '. ' +
                'Feel free to read the whole file and surrounding paragraphs ' +
                'for context, but only change what I ask. If broader edits ' +
                'seem needed (continuity, voice consistency, setup/payoff), ' +
                'propose them first and wait for my approval. Request: '
            );
        }
        function _polishPromptSelection(s, f) {
            return (
                'Polish "' + s + '" in @' + f + '. ' +
                'Feel free to read the whole file and surrounding paragraphs ' +
                'for context, but only change the selected text. If broader ' +
                'edits seem needed, propose them first and wait for my ' +
                'approval. Request: '
            );
        }

        // Each preset declares what it `needs`:
        //   'file'     -> usable any time the file context is known
        //   'sel+file' -> usable only when there is also a text selection
        var TERM_PRESETS = [
            { label: 'Polish whole file',        needs: 'file',     tpl: function(s,f){ return _polishPromptFile(f); } },
            { label: 'Polish selection',         needs: 'sel+file', tpl: function(s,f){ return _polishPromptSelection(s, f); } },
            { label: 'Make vivid / sensory',     needs: 'sel+file', tpl: function(s,f){ return 'Make "' + s + '" in @' + f + ' more vivid and sensory'; } },
            { label: 'Tighten prose',            needs: 'sel+file', tpl: function(s,f){ return 'Tighten the prose in "' + s + '" in @' + f + ' — cut filler, sharpen images'; } },
            { label: 'Check continuity',         needs: 'sel+file', tpl: function(s,f){ return 'Check "' + s + '" in @' + f + ' for continuity issues with earlier chapters'; } },
            { label: 'Vary sentence rhythm',     needs: 'sel+file', tpl: function(s,f){ return 'Vary the sentence rhythm in "' + s + '" in @' + f; } },
            { label: 'Show don\'t tell',         needs: 'sel+file', tpl: function(s,f){ return 'Rewrite "' + s + '" in @' + f + ' to show rather than tell'; } },
        ];

        // Current file path the @file button should target. Prefer the live UI
        // context (open scene modal or file preview) so @file works even when
        // the active terminal tab is plain shell.
        function _currentFileContext() {
            if (document.documentElement.dataset.view === 'scene' && curIdx >= 0) {
                return paths[curIdx] || null;
            }
            var prevTitle = document.getElementById('filePreviewTitle');
            if (prevTitle) {
                var t = prevTitle.textContent.trim();
                if (t) return t;
            }
            return _termContextFile || null;
        }

        function updateTerminalShortcuts() {
            var hasFile = !!_currentFileContext();
            var isOpen = !!_termSend;
            var selBtn = document.getElementById('termSelBtn');
            var fileBtn = document.getElementById('termFileBtn');
            var polishBtn = document.getElementById('termPolishBtn');
            var presetsBtn = document.getElementById('termPresetsBtn');
            var skillsBtn = document.getElementById('termSkillsBtn');
            if (selBtn) selBtn.disabled = !isOpen;
            if (fileBtn) fileBtn.disabled = !(isOpen && hasFile);
            if (polishBtn) polishBtn.disabled = !(isOpen && hasFile);
            // Presets has at least one file-only entry, so enable as soon as a
            // file is known. Per-item gating still happens in the click handler.
            if (presetsBtn) presetsBtn.disabled = !(isOpen && hasFile);
            if (skillsBtn) skillsBtn.disabled = !isOpen;
        }

        function terminalInsertSel(e) {
            if (e && e.preventDefault) e.preventDefault(); // keep selection alive, prevent focus shift
            if (!_termSend) return;
            var liveSel = window.getSelection ? window.getSelection().toString().trim() : '';
            var text = liveSel || _termContextSel;
            if (text) _termSend(text);
            // Blur so Enter key doesn't re-trigger this button
            var btn = document.getElementById('termSelBtn');
            if (btn) btn.blur();
        }

        // Snapshot selection before any click can clear it (e.g. clicking into terminal canvas)
        document.addEventListener('mousedown', function(e) {
            if (e.target.closest && e.target.closest('#terminalMounts')) return;
            var s = window.getSelection ? window.getSelection().toString().trim() : '';
            if (s) {
                _termContextSel = s;
                var sess = _activeSession();
                if (sess) sess.contextSel = s;
            }
        });

        function terminalInsertFile() {
            var f = _currentFileContext();
            if (_termSend && f) _termSend('@' + f);
        }

        function terminalPolishFile() {
            var f = _currentFileContext();
            if (_termSend && f) _termSend(_polishPromptFile(f));
            var btn = document.getElementById('termPolishBtn');
            if (btn) btn.blur();
        }

        function terminalToggleSkills() {
            var menu = document.getElementById('termSkillsMenu');
            var btn = document.getElementById('termSkillsBtn');
            if (!menu || !btn) return;
            var isOpen = menu.style.display === 'block';
            _closeOtherTermDropdowns('termSkillsMenu');
            if (isOpen) { menu.style.display = 'none'; return; }
            menu.innerHTML = '';
            SKILLS.filter(function(s) { return s.type === 'snippet'; }).forEach(function(skill) {
                var item = document.createElement('button');
                item.className = 'term-preset-item';
                item.textContent = skill.display_name;
                item.title = skill.short_description;
                item.onclick = function() {
                    menu.style.display = 'none';
                    if (!_termSend) return;
                    var liveSel = window.getSelection ? window.getSelection().toString().trim() : '';
                    var sel = liveSel || _termContextSel || '';
                    var ctxFile = _currentFileContext();
                    var prompt = skill.default_prompt;
                    if (sel) prompt += '\n\n"' + sel + '"';
                    if (ctxFile) prompt += '\n\nin @' + ctxFile;
                    _termSend(prompt);
                };
                menu.appendChild(item);
            });
            _positionTermDropdown(menu, btn);
            _bindTermDropdownClose(menu, btn);
        }

        // Anchor a header dropdown to its trigger button using fixed
        // positioning. Picks above-vs-below based on viewport space so it
        // works in both dock-bottom and dock-right modes (the original
        // CSS-only `bottom: calc(100% + 6px)` placed it off-screen above
        // the viewport when the terminal panel was right-docked).
        function _positionTermDropdown(menu, btn) {
            menu.style.position = 'fixed';
            menu.style.right = 'auto';
            menu.style.bottom = 'auto';
            menu.style.left = '0';
            menu.style.top = '0';
            menu.style.visibility = 'hidden';
            menu.style.display = 'block';
            var br = btn.getBoundingClientRect();
            var mh = menu.offsetHeight || 200;
            var mw = menu.offsetWidth || 200;
            var spaceAbove = br.top;
            var spaceBelow = window.innerHeight - br.bottom;
            var top = (spaceAbove >= mh + 8 || spaceAbove >= spaceBelow)
                ? Math.max(8, br.top - mh - 6)
                : Math.min(window.innerHeight - mh - 8, br.bottom + 6);
            var left = Math.max(8, Math.min(window.innerWidth - mw - 8, br.right - mw));
            menu.style.top = top + 'px';
            menu.style.left = left + 'px';
            menu.style.visibility = '';
        }

        function _closeTermDropdown(id) {
            var m = document.getElementById(id);
            if (m) m.style.display = 'none';
        }

        function _closeOtherTermDropdowns(keepId) {
            ['termPresetsMenu', 'termSkillsMenu'].forEach(function(id) {
                if (id !== keepId) _closeTermDropdown(id);
            });
        }

        // Outside-click handling that can't accidentally close on the same
        // click that opened the menu. We capture the originating click by
        // installing the listener on the next animation frame, and we
        // anchor "outside" off the trigger button as well as the menu.
        function _bindTermDropdownClose(menu, btn) {
            requestAnimationFrame(function() {
                function close(e) {
                    if (menu.contains(e.target) || btn.contains(e.target)) return;
                    menu.style.display = 'none';
                    document.removeEventListener('mousedown', close, true);
                }
                document.addEventListener('mousedown', close, true);
            });
        }

        function terminalTogglePresets() {
            var menu = document.getElementById('termPresetsMenu');
            var btn = document.getElementById('termPresetsBtn');
            if (!menu || !btn) return;
            var isOpen = menu.style.display === 'block';
            _closeOtherTermDropdowns('termPresetsMenu');
            if (isOpen) { menu.style.display = 'none'; return; }
            menu.innerHTML = '';
            var ctxFile = _currentFileContext();
            var liveSel = (window.getSelection ? window.getSelection().toString().trim() : '');
            var sel = liveSel || _termContextSel || '';
            TERM_PRESETS.forEach(function(preset) {
                var item = document.createElement('button');
                item.className = 'term-preset-item';
                item.textContent = preset.label;
                var needs = preset.needs || 'sel+file';
                var enabled = !!_termSend && !!ctxFile && (needs === 'file' || !!sel);
                item.disabled = !enabled;
                if (!enabled && needs === 'sel+file' && !sel) {
                    item.title = 'Select some text in a scene first';
                }
                item.onclick = function() {
                    menu.style.display = 'none';
                    if (!_termSend || !ctxFile) return;
                    _termSend(preset.tpl(sel, ctxFile));
                };
                menu.appendChild(item);
            });
            _positionTermDropdown(menu, btn);
            _bindTermDropdownClose(menu, btn);
        }

        function clearTerminal() {
            var s = _activeSession();
            if (s && s.xterm) s.xterm.clear();
        }

        function closeTerminal() {
            // Close every tab; _closeSession() of the last one hides the panel
            // and triggers a pending reload if needed.
            var ids = _termSessions.map(function(s) { return s.id; });
            ids.forEach(function(id) { _closeSession(id); });
        }

        syncThemeToggle();
        syncFontToggle();
        syncModalFontSize();
        document.addEventListener('scroll', scheduleScrollSave, true);
        window.addEventListener('beforeunload', saveActiveScrollPosition);

        // Defer chart init so the page layout settles before Chart.js attaches
        // its ResizeObserver. Initialising charts synchronously in a WebView
        // (VS Code Live Preview uses Electron/Chromium) can cause an immediate
        // ResizeObserver → resize → ResizeObserver loop that exhausts the call
        // stack (RangeError from the cross-origin chart.js bundle).
        requestAnimationFrame(function() {
          // responsive:false avoids the ResizeObserver setter cycle (Object.set
          // ↔ Object.set infinite recursion) in Electron/Chromium WebViews.
          function makeChart(id, h, cfg) {
            var canvas = document.getElementById(id);
            if (!canvas) return null;
            var w = (canvas.parentElement ? canvas.parentElement.offsetWidth : 0) || 400;
            canvas.width = w;
            canvas.height = h;
            // animation:false + responsive:false prevent both the async rAF
            // render path and the ResizeObserver setter cycle in Electron WebViews.
            cfg.options = Object.assign({responsive: false, maintainAspectRatio: false, animation: false}, cfg.options || {});
            applyThemeToConfig(id, cfg, getThemePalette());
            try { return new Chart(canvas, cfg); }
            catch(e) { console.error('proseview: chart init failed (' + id + ')', e); return null; }
          }

          chartRefs.presenceChart = makeChart('presenceChart', 250, {
              type: 'line', data: presenceChartData,
              options: { scales: { x: { title: { display: true, text: 'Chapter' } }, y: { beginAtZero: true, title: { display: true, text: 'Mentions' } } }, plugins: { legend: { position: 'right', labels: { boxWidth: 10, font: { size: 9 } } } } }
          });

          chartRefs.rhythmChart = makeChart('rhythmChart', 250, {
              type: 'line', data: rhythmChartData,
              options: { scales: { x: { title: { display: true, text: 'Chapter' } }, y: { min: 0, max: 20, title: { display: true, text: 'Length Variety (Stdev)' } } },
              plugins: { legend: { display: false }, annotation: { annotations: {
                  staticZone: { type: 'box', yMin: 0, yMax: 4.5 },
                  rhythmicZone: { type: 'box', yMin: 4.5, yMax: 12.5 },
                  dynamicZone: { type: 'box', yMin: 12.5, yMax: 20 }
              } } } }
          });

          chartRefs.locationChart = makeChart('locationChart', 250, {
              type: 'doughnut', data: locationChartData,
              options: { scales: { }, plugins: { legend: { position: 'right', labels: { boxWidth: 10, font: { size: 9 } } } } }
          });

          chartRefs.coOccurChart = makeChart('coOccurChart', 250, {
              type: 'bar', data: coOccurChartData,
              options: { indexAxis: 'y', plugins: { legend: { display: false } } }
          });

          chartRefs.lexicalScatterChart = makeChart('lexicalScatterChart', 350, {
              type: 'scatter', data: { datasets: lexicalScatterChartData.datasets },
              options: { scales: { x: { min:0.65, max:0.85, title: { display: true, text: 'Local Variety (MATTR)' } }, y: { min:50, max:180, title: { display: true, text: 'Whole-Scene Variety (MTLD)' } } },
              plugins: { legend: { display: false }, annotation: { annotations: { target: { type: 'box', xMin: lexicalScatterChartData.bands.mattr[0], xMax: lexicalScatterChartData.bands.mattr[1], yMin: lexicalScatterChartData.bands.mtld[0], yMax: lexicalScatterChartData.bands.mtld[1], borderWidth: 2 } } } } }
          });

        });

        const NOTE_TAGS = ['note', 'continuity', 'character', 'theme', 'question'];

        function todoEntryHtml(t, absPath) {
            if (t.source === 'frontmatter') {
                return '<div class="todo-entry">' +
                    '<div class="todo-entry-display">' +
                    '<span class="todo-entry-text">' + escHtml(t.text) + '</span>' +
                    '</div></div>';
            }
            const lineLabel = t.line ? '<span class="todo-line">L' + t.line + '</span>' : '';
            const actionBtns = '<div class="note-entry-actions"><button class="todo-edit-btn" type="button">Edit</button><button class="todo-delete-btn" type="button">Delete</button></div>';
            return '<div class="todo-entry" data-abs-path="' + attrEscape(absPath) + '" data-todo-text="' + attrEscape(t.text) + '">' +
                '<div class="todo-entry-display">' +
                lineLabel +
                '<span class="todo-entry-text">' + escHtml(t.text) + '</span>' +
                actionBtns +
                '</div>' +
                '<div class="todo-entry-edit" hidden>' +
                '<textarea class="note-edit-textarea">' + escHtml(t.text) + '</textarea>' +
                '<div class="note-edit-actions">' +
                '<button class="todo-save-btn" type="button">Save</button>' +
                '<button class="todo-cancel-edit-btn" type="button">Cancel</button>' +
                '</div></div></div>';
        }

        function noteEntryHtml(n, absPath) {
            const tagOptions = NOTE_TAGS.map(function(t) {
                return '<option value="' + t + '"' + (t === n.tag ? ' selected' : '') + '>' + t + '</option>';
            }).join('');
            const actionBtns = '<div class="note-entry-actions"><button class="note-edit-btn" type="button">Edit</button><button class="note-delete-btn" type="button">Delete</button></div>';
            return '<div class="note-entry" data-abs-path="' + attrEscape(absPath) + '" data-note-text="' + attrEscape(n.text) + '" data-note-tag="' + attrEscape(n.tag) + '">' +
                '<div class="note-entry-display">' +
                '<span class="note-tag-chip note-tag-' + escHtml(n.tag) + '">' + escHtml(n.tag) + '</span>' +
                '<span class="note-entry-text">' + escHtml(n.text) + '</span>' +
                actionBtns +
                '</div>' +
                '<div class="note-entry-edit" hidden>' +
                '<select class="note-edit-tag">' + tagOptions + '</select>' +
                '<textarea class="note-edit-textarea">' + escHtml(n.text) + '</textarea>' +
                '<div class="note-edit-actions">' +
                '<button class="note-save-btn" type="button">Save</button>' +
                '<button class="note-cancel-edit-btn" type="button">Cancel</button>' +
                '</div></div></div>';
        }

        function buildNotesTab() {
            const content = document.getElementById('notesTabContent');
            if (!content) return;
            const tagFilter = (document.getElementById('notesTagFilter') || {}).value || 'all';
            const grouped = {};
            Object.keys(meta).forEach(function(path) {
                const notes = (meta[path].notes || []).filter(function(n) {
                    return tagFilter === 'all' || n.tag === tagFilter;
                });
                if (notes.length) grouped[path] = {notes: notes, abs_path: meta[path].abs_path};
            });
            const keys = Object.keys(grouped).sort();
            if (!keys.length) {
                content.innerHTML = '<div class="notes-empty">No notes' + (tagFilter !== 'all' ? ' tagged "' + escHtml(tagFilter) + '"' : '') + '.</div>';
                return;
            }
            let html = '';
            keys.forEach(function(path) {
                const {notes, abs_path} = grouped[path];
                const name = path.split('/').pop() || path;
                html += '<div class="notes-scene-group">' +
                    '<div class="notes-scene-header">' +
                    '<button class="notes-scene-link" type="button" onclick="openSceneModal(' + JSON.stringify(path) + ')">' + escHtml(name) + '</button>' +
                    '</div>';
                notes.forEach(function(n) {
                    html += '<div class="notes-row">' + noteEntryHtml(n, abs_path) + '</div>';
                });
                html += '</div>';
            });
            content.innerHTML = html;
        }

        function filterNotes() { buildNotesTab(); }

        function buildTodosTab() {
            const content = document.getElementById('todosTabContent');
            if (!content) return;
            const grouped = {};
            Object.keys(meta).forEach(function(path) {
                const todos = meta[path].todos || [];
                if (todos.length) grouped[path] = {todos: todos, abs_path: meta[path].abs_path};
            });
            const keys = Object.keys(grouped).sort();
            if (!keys.length) {
                content.innerHTML = '<div class="notes-empty">No TODOs found.</div>';
                return;
            }
            let html = '';
            keys.forEach(function(path) {
                const {todos, abs_path} = grouped[path];
                const name = path.split('/').pop() || path;
                html += '<div class="notes-scene-group">' +
                    '<div class="notes-scene-header">' +
                    '<button class="notes-scene-link" type="button" onclick="openSceneModal(' + JSON.stringify(path) + ')">' + escHtml(name) + '</button>' +
                    '</div>';
                todos.forEach(function(t) {
                    html += '<div class="notes-row">' + todoEntryHtml(t, abs_path) + '</div>';
                });
                html += '</div>';
            });
            content.innerHTML = html;
        }

        document.addEventListener('click', function(e) {
            const jb = e.target.closest('.task-jump-btn');
            if (jb) {
                const paraIdx = jb.dataset.paraIdx;
                const target = document.getElementById('modalBody').querySelector('.prose-para[data-para-idx="' + paraIdx + '"]');
                if (target) {
                    target.scrollIntoView({behavior: 'smooth', block: 'center'});
                    target.classList.add('para-flash');
                    setTimeout(function() { target.classList.remove('para-flash'); }, 1400);
                }
                return;
            }
        });

        function closeAllPopovers() {
            document.querySelectorAll('.note-popover.is-open, .todo-popover.is-open').forEach(function(p) { p.classList.remove('is-open'); });
        }

        function postAndReload(url, body, errorMsg, disableBtn) {
            if (disableBtn) disableBtn.disabled = true;
            fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.ok) setTimeout(function() { location.reload(); }, 300);
                    else { if (disableBtn) disableBtn.disabled = false; alert(errorMsg + ': ' + (data.error || 'unknown error')); }
                })
                .catch(function(err) { if (disableBtn) disableBtn.disabled = false; alert('Request failed: ' + err); });
        }

        document.addEventListener('click', function(e) {
            // Note icon: toggle popover open/closed
            const noteIcon = e.target.closest('.note-marker-icon');
            if (noteIcon) {
                const popover = noteIcon.closest('.note-marker') && noteIcon.closest('.note-marker').querySelector('.note-popover');
                if (popover) {
                    const wasOpen = popover.classList.contains('is-open');
                    closeAllPopovers();
                    if (!wasOpen) popover.classList.add('is-open');
                }
                return;
            }

            // TODO icon: toggle popover open/closed
            const todoIcon = e.target.closest('.todo-marker-icon');
            if (todoIcon) {
                const popover = todoIcon.closest('.todo-marker') && todoIcon.closest('.todo-marker').querySelector('.todo-popover');
                if (popover) {
                    const wasOpen = popover.classList.contains('is-open');
                    closeAllPopovers();
                    if (!wasOpen) popover.classList.add('is-open');
                }
                return;
            }

            // Actions inside a note entry
            const noteEntry = e.target.closest('.note-entry');
            if (noteEntry) {
                if (e.target.closest('.note-edit-btn')) {
                    noteEntry.querySelector('.note-entry-display').hidden = true;
                    const editSec = noteEntry.querySelector('.note-entry-edit');
                    editSec.hidden = false;
                    editSec.querySelector('.note-edit-textarea').focus();
                    return;
                }
                if (e.target.closest('.note-cancel-edit-btn')) {
                    noteEntry.querySelector('.note-entry-display').hidden = false;
                    noteEntry.querySelector('.note-entry-edit').hidden = true;
                    return;
                }
                if (e.target.closest('.note-save-btn')) {
                    const btn = e.target.closest('.note-save-btn');
                    const newText = noteEntry.querySelector('.note-edit-textarea').value.trim();
                    const newTag = noteEntry.querySelector('.note-edit-tag').value;
                    if (!newText) return;
                    postAndReload('/edit-note', {abs_path: noteEntry.dataset.absPath, old_note_text: noteEntry.dataset.noteText, old_tag: noteEntry.dataset.noteTag, new_note_text: newText, new_tag: newTag}, 'Could not save note', btn);
                    return;
                }
                if (e.target.closest('.note-delete-btn')) {
                    postAndReload('/delete-note', {abs_path: noteEntry.dataset.absPath, note_text: noteEntry.dataset.noteText, tag: noteEntry.dataset.noteTag}, 'Could not delete note', e.target.closest('.note-delete-btn'));
                    return;
                }
                return;
            }

            // Actions inside a todo entry
            const todoEntry = e.target.closest('.todo-entry');
            if (todoEntry && todoEntry.dataset.absPath) {
                if (e.target.closest('.todo-edit-btn')) {
                    todoEntry.querySelector('.todo-entry-display').hidden = true;
                    const editSec = todoEntry.querySelector('.todo-entry-edit');
                    editSec.hidden = false;
                    editSec.querySelector('.note-edit-textarea').focus();
                    return;
                }
                if (e.target.closest('.todo-cancel-edit-btn')) {
                    todoEntry.querySelector('.todo-entry-display').hidden = false;
                    todoEntry.querySelector('.todo-entry-edit').hidden = true;
                    return;
                }
                if (e.target.closest('.todo-save-btn')) {
                    const btn = e.target.closest('.todo-save-btn');
                    const newText = todoEntry.querySelector('.note-edit-textarea').value.trim();
                    if (!newText) return;
                    postAndReload('/edit-todo', {abs_path: todoEntry.dataset.absPath, old_todo_text: todoEntry.dataset.todoText, new_todo_text: newText}, 'Could not save TODO', btn);
                    return;
                }
                if (e.target.closest('.todo-delete-btn')) {
                    postAndReload('/delete-todo', {abs_path: todoEntry.dataset.absPath, todo_text: todoEntry.dataset.todoText}, 'Could not delete TODO', e.target.closest('.todo-delete-btn'));
                    return;
                }
                return;
            }

            // Click outside all markers/popovers: close everything
            if (!e.target.closest('.note-marker') && !e.target.closest('.note-popover') &&
                !e.target.closest('.todo-marker') && !e.target.closest('.todo-popover')) {
                closeAllPopovers();
            }
        });

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') closeAllPopovers();
        });

        function showTab(name) {
            saveActiveScrollPosition();
            name = VALID_TABS.includes(name) ? name : 'overview';
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.tab-nav button').forEach(b => b.classList.remove('active'));
            const panel = document.getElementById('tab-' + name);
            if (panel) panel.classList.add('active');
            const btn = document.querySelector('.tab-nav button[data-tab="' + name + '"]');
            if (btn) btn.classList.add('active');
            currentTab = name;
            if (name === 'notes') buildNotesTab();
            if (name === 'todos') buildTodosTab();
            routeToHash('/tab/' + name, true);
            restoreActiveScrollPosition();
        }

        function routeToHash(fragment, push) {
            if (suppressHashWrite) return;
            const full = '#' + fragment;
            if (window.location.hash === full) return;
            if (push) {
                history.pushState(null, '', full);
            } else {
                history.replaceState(null, '', full);
            }
        }

        function parseHashRoute() {
            const raw = window.location.hash;
            if (!raw || raw === '#' || raw === '#/') return null;
            const clean = raw.replace(/^#\/?/, '');
            const slash = clean.indexOf('/');
            if (slash < 0) return { kind: clean, arg: '' };
            const kind = clean.substring(0, slash);
            let arg = clean.substring(slash + 1);
            try { arg = decodeURIComponent(arg); } catch (err) { /* keep raw */ }
            return { kind: kind, arg: arg };
        }

        function applyHashRoute() {
            const route = parseHashRoute();
            suppressHashWrite = true;
            routeHydrating = true;
            try {
                if (!route) {
                    delete document.documentElement.dataset.view;
                    showTab('overview');
                    return;
                }
                if (route.kind === 'tab') {
                    delete document.documentElement.dataset.view;
                    showTab(VALID_TABS.includes(route.arg) ? route.arg : 'overview');
                } else if (route.kind === 'scene' && route.arg && paths.indexOf(route.arg) >= 0) {
                    openSceneModal(route.arg);
                } else if (route.kind === 'file' && route.arg) {
                    if (repoFileByPath[route.arg]) previewRepoFile(route.arg);
                } else {
                    delete document.documentElement.dataset.view;
                    showTab('overview');
                }
            } finally {
                routeHydrating = false;
                suppressHashWrite = false;
                restoreActiveScrollPosition();
            }
        }

        window.addEventListener('popstate', applyHashRoute);
        window.addEventListener('hashchange', applyHashRoute);
        if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
        if (window.location.hash && window.location.hash !== '#' && window.location.hash !== '#/') {
            applyHashRoute();
        } else {
            restoreActiveScrollPosition();
        }

        function escHtml(s) {
            return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }

        function previewRepoFile(path) {
            saveActiveScrollPosition();
            const node = repoFileByPath[path];
            if (!node) return;
            highlightSidebarItem(path);
            routeToHash('/file/' + encodeURIComponent(path), true);
            document.getElementById('filePreviewTitle').textContent = node.path;
            const sizeKb = (node.size / 1024).toFixed(1);
            document.getElementById('filePreviewMeta').textContent =
                'Last modified ' + node.modified_at + ' \u00b7 ' + sizeKb + ' KB';
            const editorBtn = document.getElementById('filePreviewEditorBtn');
            editorBtn.href = buildEditorUrl(node.abs_path);
            editorBtn.textContent = '\u2197';
            editorBtn.title = 'Open in ' + editorLabel;
            const body = document.getElementById('filePreviewBody');
            if (node.too_large) {
                const limitKb = (repoPreviewMax / 1024).toFixed(0);
                body.innerHTML = '<div class="repo-warn">This file is ' + sizeKb + ' KB, above the ' + limitKb + ' KB preview limit.</div>';
            } else if (!node.is_text || node.body === null) {
                body.innerHTML = '<div class="repo-warn">Preview not available for this file type.</div>';
            } else {
                const lname = node.name.toLowerCase();
                if (lname.endsWith('.md') || lname.endsWith('.markdown')) {
                    if (node.body.length > 65536) {
                        body.innerHTML = '<div class="repo-warn">This file is ' + sizeKb + ' KB \u2014 too large for inline rendering. <a class="editor-btn" href="' + editorBtn.href + '" target="_blank">\u2197 Open in ' + escHtml(editorLabel) + '</a></div>';
                    } else {
                        body.innerHTML = marked.parse(node.body);
                    }
                } else {
                    body.innerHTML = '';
                    const pre = document.createElement('pre');
                    pre.innerText = node.body;
                    body.appendChild(pre);
                }
            }
            body.scrollTop = 0;
            document.documentElement.dataset.view = 'file';
            restoreActiveScrollPosition();
            if (typeof updateTerminalShortcuts === 'function') updateTerminalShortcuts();
        }

        function closeFilePreview() {
            saveActiveScrollPosition();
            delete document.documentElement.dataset.view;
            routeToHash('/tab/' + currentTab, true);
            restoreActiveScrollPosition();
        }

        // Re-fetch the currently previewed file from disk and re-render only
        // the file preview body, leaving terminal sessions and other UI state
        // untouched.
        function refreshFilePreview() {
            var titleEl = document.getElementById('filePreviewTitle');
            var path = titleEl ? titleEl.textContent.trim() : '';
            if (!path) return;
            var btn = document.getElementById('filePreviewRefreshBtn');
            var prevHTML = btn ? btn.innerHTML : '';
            if (btn) { btn.disabled = true; btn.innerHTML = '\u2026'; }
            fetch('/repo-file?path=' + encodeURIComponent(path), { cache: 'no-store' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data || !data.ok || !data.node) {
                        throw new Error((data && data.error) || 'unknown error');
                    }
                    repoFileByPath[path] = data.node;
                    previewRepoFile(path);
                })
                .catch(function(err) { alert('Could not refresh file: ' + err); })
                .finally(function() {
                    if (btn) { btn.disabled = false; btn.innerHTML = prevHTML || '\u21BB'; }
                });
        }

        // ── Sidebar ──────────────────────────────────────────────────────────

        (function initSidebarResize() {
            var handle = document.getElementById('sidebarResizeHandle');
            if (!handle) return;
            var MIN_W = 160, MAX_W = 520;
            var startX, startW;
            var html = document.documentElement;

            function setSidebarWidth(w) {
                w = Math.max(MIN_W, Math.min(MAX_W, w));
                html.style.setProperty('--sidebar-w', w + 'px');
                try { localStorage.setItem('proseview-sidebar-w', w); } catch(e) {}
            }

            handle.addEventListener('mousedown', function(e) {
                e.preventDefault();
                startX = e.clientX;
                startW = document.getElementById('repoSidebar').offsetWidth;
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
                document.body.style.userSelect = 'none';
                document.body.style.cursor = 'col-resize';
            });

            function onMove(e) { setSidebarWidth(startW + (e.clientX - startX)); }
            function onUp() {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.style.userSelect = '';
                document.body.style.cursor = '';
            }

            try {
                var saved = localStorage.getItem('proseview-sidebar-w');
                if (saved) html.style.setProperty('--sidebar-w', Math.max(MIN_W, Math.min(MAX_W, +saved)) + 'px');
            } catch(e) {}
        })();

        function setSidebarOpen(open) {
            const html = document.documentElement;
            if (open) {
                html.dataset.sidebar = 'open';
                try { localStorage.setItem('proseview-sidebar', 'open'); } catch(e) {}
                if (!window.__sidebarRendered) {
                    try {
                        renderSidebarTree();
                        window.__sidebarRendered = true;
                    } catch(e) { console.error('proseview: sidebar render failed', e); }
                }
            } else {
                html.dataset.sidebar = 'closed';
                try { localStorage.setItem('proseview-sidebar', 'closed'); } catch(e) {}
            }
        }

        function renderSidebarTree() {
            const container = document.getElementById('sidebarTree');
            if (!container || !sidebarTree.length) return;
            container.innerHTML = '';
            container.appendChild(buildSidebarList(sidebarTree, 0));
        }

        function buildSidebarList(nodes, depth) {
            const ul = document.createElement('ul');
            for (const node of nodes) ul.appendChild(buildSidebarItem(node, depth));
            return ul;
        }

        function buildSidebarItem(node, depth) {
            const li = document.createElement('li');
            if (node.is_file) {
                const a = document.createElement('span');
                a.className = 'file-link';
                a.dataset.path = node.path;
                if (node.is_scene) {
                    a.dataset.scenePath = node.scene_path || '';
                    a.innerHTML = '<span class="file-icon sidebar-scene-icon">\u25A0</span>' + escHtml(node.name);
                    a.onclick = () => {
                        highlightSidebarItem(node.path);
                        openSceneModal(node.scene_path);
                    };
                } else {
                    a.innerHTML = '<span class="file-icon">\u25A1</span>' + escHtml(node.name);
                    a.onclick = () => {
                        if (repoFileByPath[node.path]) previewRepoFile(node.path);
                    };
                }
                li.appendChild(a);
            } else {
                const tog = document.createElement('span');
                tog.className = 'dir-toggle';
                tog.appendChild(document.createTextNode(node.name));
                tog.onclick = () => li.classList.toggle('expanded');
                li.appendChild(tog);
                if (node.children && node.children.length)
                    li.appendChild(buildSidebarList(node.children, depth + 1));
                if (depth === 0) li.classList.add('expanded');
            }
            return li;
        }

        function highlightSidebarItem(fullPath) {
            document.querySelectorAll('#sidebarTree .file-link').forEach(el => {
                el.classList.toggle('active', el.dataset.path === fullPath);
            });
        }

        // Defer sidebar render so it does not block or interfere with initial
        // page layout and chart initialisation.
        requestAnimationFrame(function() {
            if (document.documentElement.dataset.sidebar !== 'closed') {
                try {
                    renderSidebarTree();
                    window.__sidebarRendered = true;
                } catch(e) {
                    console.error('proseview: sidebar render failed', e);
                }
            }
        });

        function sortTable(n) {
            var t = document.getElementById("sceneTable"), r = t.rows, s = true, d = "asc", c = 0;
            while (s) {
                s = false;
                for (var i = 1; i < (r.length - 1); i++) {
                    var x = r[i].getElementsByTagName("TD")[n], y = r[i+1].getElementsByTagName("TD")[n], should = false;
                    if (!x || !y) continue;
                    var xv = x.innerText.replace(/,/g, '').replace(/%/g, ''), yv = y.innerText.replace(/,/g, '').replace(/%/g, '');
                    if (!isNaN(parseFloat(xv)) && !isNaN(parseFloat(yv))) { xv = parseFloat(xv); yv = parseFloat(yv); } else { xv = xv.toLowerCase(); yv = yv.toLowerCase(); }
                    if (d == "asc" ? xv > yv : xv < yv) { should = true; break; }
                }
                if (should) { r[i].parentNode.insertBefore(r[i+1], r[i]); s = true; c++; } else if (c == 0 && d == "asc") { d = "desc"; s = true; }
            }
        }
