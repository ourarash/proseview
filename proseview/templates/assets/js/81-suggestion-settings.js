        // ── Settings › Suggestions ─────────────────────────────────────
        //
        // What a highlight's Suggest button asks Codex or Claude, what they
        // may see and use, and with what model. The model, effort, tools and
        // MCP servers are this computer's; the files and prompts are the
        // book's. Saved with the dialog's Save button, like every other
        // setting; Try it saves first, then runs a sample suggestion.
        var _sg = null;
        var _sgDirty = false;
        var SG_AGENTS = [{id: 'codex', label: 'Codex'}, {id: 'claude', label: 'Claude'}];
        var SG_KIND_LABELS = {
            'dialogue_tags.fancy': 'Dialogue Tags: other than said or asked',
            'dialogue_tags.adverb': 'Dialogue Tags: adverb on a tag',
            'dialogue_tags.not_speech': 'Dialogue Tags: not a speech verb',
            'dialogue_tags.untagged_run': 'Dialogue Tags: 6+ lines with no tag'
        };

        function _sgPost(path, body) {
            return fetch(path, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body || {})})
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data.ok) throw new Error(data.error || 'Request failed');
                    return data;
                });
        }

        function _sgEl(tag, cls, text) {
            var el = document.createElement(tag);
            if (cls) el.className = cls;
            if (text !== undefined) el.textContent = text;
            return el;
        }

        function _sgChanged() {
            _sgDirty = true;
            if (typeof markSettingsDirty === 'function') markSettingsDirty();
        }

        function loadSuggestionSettings() {
            var body = document.getElementById('suggestionSettingsBody');
            if (!body) return Promise.resolve();
            return _sgPost('/api/discuss/suggestion-settings', {}).then(function(data) {
                _sg = data.settings;
                _sg.catalogs = {};
                _sgDirty = false;
                renderSuggestionSettings();
                SG_AGENTS.forEach(function(agent) {
                    _sgPost('/api/discuss/models', {agent: agent.id}).then(function(res) {
                        _sg.catalogs[agent.id] = res.catalog;
                        renderSuggestionSettings();
                    }).catch(function() {
                        _sg.catalogs[agent.id] = {unavailable: true, models: []};
                        renderSuggestionSettings();
                    });
                });
            }).catch(function(error) {
                body.replaceChildren(_sgEl('p', 'settings-unit', 'Could not load: ' + error.message));
            });
        }

        function saveSuggestionSettings() {
            if (!_sg || !_sgDirty) return Promise.resolve();
            return _sgPost('/api/discuss/suggestion-settings', {save: true, book: _sg.book, app: _sg.app})
                .then(function(data) {
                    var catalogs = _sg.catalogs;
                    _sg = data.settings;
                    _sg.catalogs = catalogs;
                    _sgDirty = false;
                    renderSuggestionSettings();
                });
        }

        function _sgSelect(options, value, onChange, label) {
            var select = _sgEl('select', 'settings-input');
            select.setAttribute('aria-label', label);
            options.forEach(function(opt) {
                var o = _sgEl('option', '', opt.label);
                o.value = opt.value;
                select.appendChild(o);
            });
            select.value = value;
            if (select.value !== value) {
                // A saved choice the agent no longer lists stays visible.
                var o = _sgEl('option', '', value + ' (not listed)');
                o.value = value;
                select.appendChild(o);
                select.value = value;
            }
            select.onchange = function() { onChange(select.value); _sgChanged(); };
            return select;
        }

        function _sgCheckbox(checked, label, onChange) {
            var wrap = _sgEl('label', 'suggestion-check');
            var box = _sgEl('input');
            box.type = 'checkbox';
            box.checked = !!checked;
            box.onchange = function() { onChange(box.checked); _sgChanged(); };
            wrap.append(box, document.createTextNode(' ' + label));
            return wrap;
        }

        function _sgAgentCell(agentId, build) {
            var cell = _sgEl('div', 'suggestion-cell');
            cell.dataset.agent = agentId;
            build(cell, _sg.app[agentId], _sg.catalogs[agentId]);
            return cell;
        }

        function _sgRow(grid, label, tip, build) {
            var head = _sgEl('span', 'settings-label', label);
            if (tip) head.title = tip;
            grid.appendChild(head);
            SG_AGENTS.forEach(function(agent) { grid.appendChild(_sgAgentCell(agent.id, build)); });
        }

        function renderSuggestionSettings() {
            var body = document.getElementById('suggestionSettingsBody');
            if (!body || !_sg) return;
            var keepTry = {};
            body.querySelectorAll('.suggestion-try-out').forEach(function(out) { keepTry[out.dataset.agent] = out; });
            body.replaceChildren();

            // Per agent, on this computer.
            var grid = _sgEl('div', 'suggestion-grid');
            grid.appendChild(_sgEl('span', 'settings-unit', 'On this computer'));
            SG_AGENTS.forEach(function(agent) { grid.appendChild(_sgEl('strong', 'suggestion-agent', agent.label)); });

            _sgRow(grid, 'Model', 'Same as chat uses whatever the chat is set to.', function(cell, app, catalog) {
                if (catalog && catalog.unavailable) { cell.appendChild(_sgEl('span', 'settings-unit', 'Not available')); return; }
                var options = [{value: '', label: 'Same as chat'}].concat(((catalog || {}).models || []).map(function(m) {
                    return {value: m.id, label: m.label || m.id};
                }));
                cell.appendChild(_sgSelect(options, app.model, function(v) { app.model = v; app.effort = ''; renderSuggestionSettings(); },
                                           cell.dataset.agent + ' model'));
            });
            _sgRow(grid, 'Effort', 'How long the model thinks. Low answers about twice as fast.', function(cell, app, catalog) {
                var row = ((catalog || {}).models || []).find(function(m) { return m.id === app.model; });
                var efforts = row && row.efforts.length ? row.efforts.map(function(e) { return e.id; })
                    : ['low', 'medium', 'high'];
                var options = [{value: '', label: 'Same as chat'}].concat(efforts.map(function(e) {
                    return {value: e, label: e.charAt(0).toUpperCase() + e.slice(1)};
                }));
                cell.appendChild(_sgSelect(options, app.effort, function(v) { app.effort = v; }, cell.dataset.agent + ' effort'));
            });
            _sgRow(grid, 'Tools', 'Suggestions never change a file; Use does that.', function(cell, app) {
                var options = Object.keys(_sg.tools).map(function(k) { return {value: k, label: _sg.tools[k]}; });
                cell.appendChild(_sgSelect(options, app.tools, function(v) { app.tools = v; }, cell.dataset.agent + ' tools'));
            });
            _sgRow(grid, 'MCP servers', 'Off unless switched on here. Each adds start-up time.', function(cell, app) {
                var servers = _sg.mcp[cell.dataset.agent] || [];
                if (!servers.length) { cell.appendChild(_sgEl('span', 'settings-unit', 'None configured')); return; }
                servers.forEach(function(server) {
                    var label = server.name + (server.configured_on ? '' : ' (off in its config)');
                    cell.appendChild(_sgCheckbox(app.mcp_on.indexOf(server.name) !== -1, label, function(on) {
                        app.mcp_on = app.mcp_on.filter(function(n) { return n !== server.name; });
                        if (on) app.mcp_on.push(server.name);
                    }));
                });
            });
            _sgRow(grid, 'Try it', 'Saves, then asks for suggestions on a sample sentence and shows how it went.', function(cell) {
                var agentId = cell.dataset.agent;
                var btn = _sgEl('button', 'settings-plain-btn', 'Try it');
                btn.type = 'button';
                btn.onclick = function() { tryHighlightSuggestion(agentId); };
                cell.appendChild(btn);
                var out = keepTry[agentId] || _sgEl('div', 'suggestion-try-out');
                out.dataset.agent = agentId;
                out.setAttribute('role', 'status');
                cell.appendChild(out);
            });
            body.appendChild(grid);

            // Per book, in .proseview.yaml.
            body.appendChild(_sgEl('p', 'suggestion-subhead', 'In this book'));
            var book = _sg.book;
            var rows = [
                ['Project instructions', 'The book\u2019s own instruction files, read as the chat reads them.',
                 _sgCheckbox(book.instructions, 'Read them', function(v) { book.instructions = v; })],
                ['Context', 'What goes along with the marked passage.',
                 _sgSelect([{value: 'paragraph', label: 'Its paragraph'}, {value: 'scene', label: 'The whole scene'}],
                           book.context, function(v) { book.context = v; }, 'Context')]
            ];
            rows.forEach(function(r) {
                var row = _sgEl('div', 'settings-row');
                var label = _sgEl('span', 'settings-label', r[0]);
                label.title = r[1];
                var field = _sgEl('span', 'settings-field');
                field.appendChild(r[2]);
                row.append(label, field);
                body.appendChild(row);
            });

            var prompts = _sgEl('details', 'suggestion-prompts');
            prompts.appendChild(_sgEl('summary', '', 'Prompts'));
            var help = _sgEl('p', 'settings-unit');
            help.textContent = 'Placeholders: ' + Object.keys(_sg.placeholders).map(function(k) {
                return '{' + k + '} ' + _sg.placeholders[k];
            }).join('; ') + '. The request for three rewrites, and the passage itself, are added after these and can’t be changed.';
            prompts.appendChild(help);
            prompts.appendChild(_sgPromptField('Every check', book.prompt, _sg.defaults.prompt, function(v) { book.prompt = v; }));
            Object.keys(_sg.defaults.pass_prompts).forEach(function(key) {
                var name = SG_KIND_LABELS[key] || PASS_LABELS[key] || key;
                prompts.appendChild(_sgPromptField(name, book.pass_prompts[key], _sg.defaults.pass_prompts[key], function(v) {
                    book.pass_prompts[key] = v;
                }));
            });
            body.appendChild(prompts);
        }

        function _sgPromptField(label, value, fallback, onChange) {
            var wrap = _sgEl('div', 'suggestion-prompt');
            var head = _sgEl('div', 'suggestion-prompt-head');
            var title = _sgEl('span', 'settings-label', label);
            var reset = _sgEl('button', 'settings-plain-btn', 'Reset to default');
            reset.type = 'button';
            reset.disabled = value === fallback;
            var area = _sgEl('textarea', 'suggestion-prompt-text');
            area.value = value;
            area.rows = Math.min(8, Math.max(2, Math.ceil(value.length / 70)));
            area.setAttribute('aria-label', label + ' prompt');
            area.oninput = function() { onChange(area.value); reset.disabled = area.value === fallback; _sgChanged(); };
            reset.onclick = function() { area.value = fallback; onChange(fallback); reset.disabled = true; _sgChanged(); };
            head.append(title, reset);
            wrap.append(head, area);
            return wrap;
        }

        function _sgSeconds(n) { return (Math.round(n * 10) / 10).toFixed(1) + ' s'; }

        function tryHighlightSuggestion(agentId) {
            var out = document.querySelector('.suggestion-try-out[data-agent="' + agentId + '"]');
            if (!out) return;
            out.replaceChildren(_sgEl('span', 'hl-card-spinner'), _sgEl('span', 'settings-unit', ' Saving and asking…'));
            var chat = typeof discussModelSelection === 'function' && typeof _discussAgent === 'string'
                && _discussAgent === agentId ? discussModelSelection() : {model: '', effort: ''};
            saveSuggestionSettings().then(function() {
                return _sgPost('/api/discuss/suggestion-try', {agent: agentId, chat_model: chat.model, chat_effort: chat.effort});
            }).then(function(data) {
                var used = data.used || {};
                var t = used.timings || {};
                var lines = [
                    ['Model', (used.model || 'agent default') + (used.effort ? ' · ' + used.effort : '')],
                    ['Instructions', (used.instruction_files || []).join(', ') || 'none'],
                    ['Context', used.context],
                    ['Tools', (_sg.tools[used.tools] || used.tools) + ((used.activities || []).length
                        ? ' — used: ' + used.activities.map(function(a) { return a.title || a.kind; }).join('; ')
                        : ' — none used')],
                    ['MCP servers', (used.mcp_servers || []).join(', ') || 'none'],
                    ['Time', 'thread ' + _sgSeconds(t.thread_started || 0) + ' · first token '
                        + _sgSeconds(t.first_token || 0) + ' · total ' + _sgSeconds(t.total || 0)],
                    ['First option', ((data.alternatives || [])[0] || {}).text || '']
                ];
                var dl = _sgEl('dl', 'suggestion-try-result');
                lines.forEach(function(line) { dl.append(_sgEl('dt', '', line[0]), _sgEl('dd', '', line[1])); });
                out.replaceChildren(dl);
            }).catch(function(error) {
                out.replaceChildren(_sgEl('span', 'hl-card-error', error.message));
            });
        }

        // Settings has two tabs, so the suggestions' long list does not make
        // the everyday settings scroll.
        function selectSettingsTab(name) {
            ['general', 'suggestions'].forEach(function(tab) {
                var on = tab === name;
                var id = tab.charAt(0).toUpperCase() + tab.slice(1);
                var button = document.getElementById('settingsTab' + id);
                var panel = document.getElementById('settingsPanel' + id);
                if (button) {
                    button.setAttribute('aria-selected', on ? 'true' : 'false');
                    button.tabIndex = on ? 0 : -1;
                }
                if (panel) panel.hidden = !on;
            });
            if (name === 'suggestions' && !_sg) loadSuggestionSettings();
        }

        // The card's gear: Settings, opened on the Suggestions tab.
        function openSuggestionSettings() {
            // The dialog sits in the dashboard, which is hidden while a scene
            // is open; a modal shown from inside it would be invisible.
            var dlg = document.getElementById('settingsDialog');
            if (dlg && dlg.parentElement !== document.body) document.body.appendChild(dlg);
            if (typeof openSettings === 'function') openSettings();
            selectSettingsTab('suggestions');
            var tab = document.getElementById('settingsTabSuggestions');
            if (tab) tab.focus({preventScroll: true});
        }

        document.addEventListener('DOMContentLoaded', function() {
            // Arrow keys move between the tabs, as in any tab row.
            var row = document.querySelector('.settings-tabs');
            if (row) row.addEventListener('keydown', function(e) {
                if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
                var next = document.getElementById('settingsTabGeneral').getAttribute('aria-selected') === 'true'
                    ? 'suggestions' : 'general';
                selectSettingsTab(next);
                document.getElementById(next === 'general' ? 'settingsTabGeneral' : 'settingsTabSuggestions')
                    .focus({preventScroll: true});
                e.preventDefault();
            });
        });
