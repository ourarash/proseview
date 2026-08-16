
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
            // Theme the *raw* config, never `chart.options`.
            //
            // `chart.options` is Chart.js's resolved-options proxy. Reading a
            // nested object off it and assigning it straight back - which is
            // what `plugins.tooltip = plugins.tooltip || {}` does - stores the
            // proxy inside itself, and the setter then recurses until the
            // stack overflows. `chart.config` is the plain user config the
            // chart was built from, so the same edits are safe there.
            applyThemeToConfig(chart.canvas.id, chart.config, getThemePalette());
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
            focusAppearanceOption('themeMenuList', currentTheme(), 'themeValue');
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
            focusAppearanceOption('fontMenuList', currentFont(), 'fontValue');
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

        function focusAppearanceOption(listId, value, dataKey) {
            const list = document.getElementById(listId);
            if (!list) return;
            const options = Array.from(list.querySelectorAll('[role="option"]'));
            const selected = options.find(option => option.dataset[dataKey] === value) || options[0];
            options.forEach(option => { option.tabIndex = option === selected ? 0 : -1; });
            if (selected) selected.focus({preventScroll: true});
        }

        function moveAppearanceOption(list, event, preview, select, close, toggle) {
            const options = Array.from(list.querySelectorAll('[role="option"]'));
            if (!options.length) return;
            let index = Math.max(0, options.indexOf(document.activeElement));
            if (event.key === 'ArrowDown' || event.key === 'ArrowRight') index = (index + 1) % options.length;
            else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') index = (index - 1 + options.length) % options.length;
            else if (event.key === 'Home') index = 0;
            else if (event.key === 'End') index = options.length - 1;
            else if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                select(document.activeElement.dataset);
                toggle.focus({preventScroll: true});
                return;
            } else if (event.key === 'Escape') {
                event.preventDefault();
                close(false);
                toggle.focus({preventScroll: true});
                return;
            } else if (event.key === 'Tab') {
                event.preventDefault();
                select(document.activeElement.dataset);
                toggle.focus({preventScroll: true});
                return;
            } else {
                return;
            }
            event.preventDefault();
            options.forEach((option, optionIndex) => { option.tabIndex = optionIndex === index ? 0 : -1; });
            options[index].focus({preventScroll: true});
            preview(options[index].dataset);
        }

        (function initAppearanceListboxKeyboard() {
            const fontList = document.getElementById('fontMenuList');
            const themeList = document.getElementById('themeMenuList');
            const fontToggle = document.getElementById('fontToggle');
            const themeToggle = document.getElementById('themeToggle');
            if (fontList && fontToggle) {
                fontList.addEventListener('keydown', function(event) {
                    moveAppearanceOption(fontList, event,
                        data => previewFont(data.fontValue),
                        data => selectFont(data.fontValue),
                        closeFontMenu, fontToggle);
                });
                fontToggle.addEventListener('keydown', function(event) {
                    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
                    event.preventDefault();
                    if (!fontMenuIsOpen()) openFontMenu();
                });
            }
            if (themeList && themeToggle) {
                themeList.addEventListener('keydown', function(event) {
                    moveAppearanceOption(themeList, event,
                        data => previewTheme(data.themeValue),
                        data => selectTheme(data.themeValue),
                        closeThemeMenu, themeToggle);
                });
                themeToggle.addEventListener('keydown', function(event) {
                    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
                    event.preventDefault();
                    if (!themeMenuIsOpen()) openThemeMenu();
                });
            }
        })();

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
