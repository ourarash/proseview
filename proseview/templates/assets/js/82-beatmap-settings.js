        // ── Settings › Beat Map ─────────────────────────────────────────
        //
        // What Proseview asks Codex or Claude when extracting or updating a
        // scene's narrative progression map: default agent and model, pacing
        // target, instruction files, narrative prompts, and dramatic tension
        // rubrics.
        // Saved into .proseview.yaml under beatmap: with the dialog's Save button.
        var _bmSettings = null;
        var _bmDirty = false;
        var _bmCatalogs = {};

        var BM_AGENTS = [
            {value: 'claude', label: 'Claude CLI'},
            {value: 'codex', label: 'Codex CLI'}
        ];

        var BM_PACING_OPTIONS = [
            {value: 'auto', label: 'Auto (proportional to scene length)'},
            {value: 'tight', label: 'Tight (~3–5 beats)'},
            {value: 'balanced', label: 'Balanced (~5–8 beats)'},
            {value: 'detailed', label: 'Detailed (~8–14 beats)'},
            {value: 'micro', label: 'Micro-paced (~12–20 beats)'}
        ];

        function _bmPost(path, body) {
            return fetch(path, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body || {})})
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data.ok) throw new Error(data.error || 'Request failed');
                    return data;
                });
        }

        function _bmEl(tag, cls, text) {
            var el = document.createElement(tag);
            if (cls) el.className = cls;
            if (text !== undefined) el.textContent = text;
            return el;
        }

        function _bmChanged() {
            _bmDirty = true;
            if (typeof markSettingsDirty === 'function') markSettingsDirty();
        }

        function _bmUpdateModelSelect() {
            var select = document.getElementById('bmSettingModel');
            if (!select || !_bmSettings) return;
            var book = _bmSettings.book || {};
            var selectedAgent = book.agent || 'claude';
            var agentCatalog = _bmCatalogs[selectedAgent];
            var modelOptions = [{value: '', label: 'Agent default (recommended)'}];
            if (agentCatalog && agentCatalog.models && agentCatalog.models.length) {
                agentCatalog.models.forEach(function(m) {
                    modelOptions.push({value: m.id, label: m.label || m.id});
                });
            } else if (agentCatalog && agentCatalog.unavailable) {
                modelOptions = [{value: '', label: 'Default CLI model (catalog unavailable)'}];
            }
            select.replaceChildren();
            modelOptions.forEach(function(opt) {
                var o = _bmEl('option', '', opt.label);
                o.value = opt.value;
                select.appendChild(o);
            });
            select.value = book.model || '';
        }

        function loadBeatMapSettings() {
            var body = document.getElementById('beatmapSettingsBody');
            if (!body) return Promise.resolve();
            return _bmPost('/api/discuss/beatmap-settings', {}).then(function(data) {
                _bmSettings = data.settings;
                _bmDirty = false;
                renderBeatMapSettings();
                BM_AGENTS.forEach(function(agent) {
                    _bmPost('/api/discuss/models', {agent: agent.value}).then(function(res) {
                        _bmCatalogs[agent.value] = res.catalog;
                        if (_bmDirty) {
                            _bmUpdateModelSelect();
                        } else {
                            renderBeatMapSettings();
                        }
                    }).catch(function() {
                        _bmCatalogs[agent.value] = {unavailable: true, models: []};
                        if (_bmDirty) {
                            _bmUpdateModelSelect();
                        } else {
                            renderBeatMapSettings();
                        }
                    });
                });
            }).catch(function(error) {
                if (body) {
                    body.replaceChildren(_bmEl('p', 'settings-unit', 'Could not load beat map settings: ' + error.message));
                }
            });
        }

        function saveBeatMapSettings() {
            if (!_bmSettings || !_bmDirty) return Promise.resolve();
            return _bmPost('/api/discuss/beatmap-settings', {save: true, book: _bmSettings.book})
                .then(function(data) {
                    _bmSettings = data.settings;
                    _bmDirty = false;
                    if (typeof _beatMapAgent !== 'undefined' && _bmSettings.book && _bmSettings.book.agent) {
                        _beatMapAgent = _bmSettings.book.agent;
                        try { localStorage.setItem('proseview_beatmap_agent', _beatMapAgent); } catch (e) {}
                    }
                    renderBeatMapSettings();
                });
        }

        function openBeatMapSettings() {
            var dlg = document.getElementById('settingsDialog');
            if (dlg && dlg.parentElement !== document.body) document.body.appendChild(dlg);
            if (typeof openSettings === 'function') openSettings();
            if (typeof selectSettingsTab === 'function') selectSettingsTab('beatmap');
            var tab = document.getElementById('settingsTabBeatmap');
            if (tab) tab.focus({preventScroll: true});
        }

        function _bmSelect(options, value, onChange, label) {
            var select = _bmEl('select', 'settings-input');
            select.setAttribute('aria-label', label);
            options.forEach(function(opt) {
                var o = _bmEl('option', '', opt.label);
                o.value = opt.value;
                select.appendChild(o);
            });
            select.value = value;
            if (select.value !== value) {
                var o = _bmEl('option', '', value + ' (custom)');
                o.value = value;
                select.appendChild(o);
                select.value = value;
            }
            select.onchange = function() { onChange(select.value); _bmChanged(); };
            return select;
        }

        function _bmCheckbox(checked, label, onChange) {
            var wrap = _bmEl('label', 'suggestion-check');
            var box = _bmEl('input');
            box.type = 'checkbox';
            box.checked = !!checked;
            box.onchange = function() { onChange(box.checked); _bmChanged(); };
            wrap.append(box, document.createTextNode(' ' + label));
            return wrap;
        }

        function _bmPromptField(label, value, fallback, onChange) {
            var wrap = _bmEl('div', 'suggestion-prompt');
            var head = _bmEl('div', 'suggestion-prompt-head');
            var title = _bmEl('span', 'settings-label', label);
            var reset = _bmEl('button', 'settings-plain-btn', 'Reset to default');
            reset.type = 'button';
            reset.disabled = (value || '').trim() === (fallback || '').trim();
            var area = _bmEl('textarea', 'suggestion-prompt-text');
            area.value = value || '';
            area.rows = Math.min(14, Math.max(5, Math.ceil((value || '').length / 65)));
            area.setAttribute('aria-label', label);
            area.oninput = function() {
                onChange(area.value);
                reset.disabled = area.value.trim() === (fallback || '').trim();
                _bmChanged();
            };
            reset.onclick = function() {
                area.value = fallback;
                onChange(fallback);
                reset.disabled = true;
                _bmChanged();
            };
            head.append(title, reset);
            wrap.append(head, area);
            return wrap;
        }

        function renderBeatMapSettings() {
            var body = document.getElementById('beatmapSettingsBody');
            if (!body || !_bmSettings) return;

            // Retain scroll position within settings body if re-rendering
            var savedScroll = body.scrollTop;
            body.replaceChildren();

            var book = _bmSettings.book || {};
            var defaults = _bmSettings.defaults || {};

            // 1. Generation Engine & Model
            body.appendChild(_bmEl('p', 'suggestion-subhead', 'Generation defaults'));

            var selectedAgent = book.agent || defaults.agent || 'claude';
            var agentCatalog = _bmCatalogs[selectedAgent];
            var modelOptions = [{value: '', label: 'Agent default (recommended)'}];
            if (agentCatalog && agentCatalog.models && agentCatalog.models.length) {
                agentCatalog.models.forEach(function(m) {
                    modelOptions.push({value: m.id, label: m.label || m.id});
                });
            } else if (agentCatalog && agentCatalog.unavailable) {
                modelOptions = [{value: '', label: 'Default CLI model (catalog unavailable)'}];
            }

            var generalRows = [
                [
                    'Default Agent',
                    'Which CLI agent extracts beats and drama tension curves for scenes.',
                    _bmSelect(BM_AGENTS, selectedAgent, function(v) {
                        book.agent = v;
                        book.model = ''; // Reset model when agent switches
                        renderBeatMapSettings();
                    }, 'Default agent')
                ],
                [
                    'Model',
                    'Specific model identifier to use with the selected agent.',
                    (function() {
                        var sel = _bmSelect(modelOptions, book.model || '', function(v) {
                            book.model = v;
                        }, 'Model');
                        sel.id = 'bmSettingModel';
                        return sel;
                    })()
                ],
                [
                    'Target Pacing',
                    'Guideline for how granularly beats should be broken down across the scene.',
                    _bmSelect(BM_PACING_OPTIONS, book.target_beats || 'auto', function(v) {
                        book.target_beats = v;
                    }, 'Target pacing')
                ],
                [
                    'Project Instructions',
                    'Read project instruction files when generating beat maps.',
                    _bmCheckbox(book.instructions !== false, 'Read instruction files', function(v) {
                        book.instructions = v;
                    })
                ]
            ];

            generalRows.forEach(function(r) {
                var row = _bmEl('div', 'settings-row');
                var label = _bmEl('span', 'settings-label', r[0]);
                label.title = r[1];
                var field = _bmEl('span', 'settings-field');
                field.appendChild(r[2]);
                row.append(label, field);
                body.appendChild(row);
            });

            // 2. Prompts & Rubrics Section
            body.appendChild(_bmEl('p', 'suggestion-subhead', 'Prompts & rubrics'));

            var promptsWrap = _bmEl('details', 'suggestion-prompts');
            promptsWrap.open = true; // Open by default for clarity in Beat Map tab
            promptsWrap.appendChild(_bmEl('summary', '', 'Beat Map extraction prompts'));

            var help = _bmEl('p', 'settings-unit');
            help.textContent = 'Supported runtime placeholders: {rel_path} (scene path), {total_paragraphs} (total paragraphs), {guidance} (scene-specific author instructions). Exact JSON schema format is appended automatically and preserved.';
            promptsWrap.appendChild(help);

            promptsWrap.appendChild(_bmPromptField(
                'Narrative Structure Prompt',
                book.prompt || defaults.prompt,
                defaults.prompt,
                function(v) { book.prompt = v; }
            ));

            promptsWrap.appendChild(_bmPromptField(
                'Dramatic Tension Rubric',
                book.tension_rubric || defaults.tension_rubric,
                defaults.tension_rubric,
                function(v) { book.tension_rubric = v; }
            ));

            body.appendChild(promptsWrap);

            if (savedScroll) {
                body.scrollTop = savedScroll;
            }
        }
