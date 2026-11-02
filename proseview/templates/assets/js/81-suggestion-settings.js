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
            var grid = _sgEl('div', 'suggestion-grid room-seat-grid');
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

        // Settings has three tabs: General, Suggestions, and Writers' Room.
        var SETTINGS_TABS = ['general', 'suggestions', 'room'];

        function selectSettingsTab(name) {
            SETTINGS_TABS.forEach(function(tab) {
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
            if (name === 'room' && !_rm) loadRoomSettings();
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

        // The Room header's gear: Settings, opened on the Writers' Room tab.
        function openRoomSettings() {
            var dlg = document.getElementById('settingsDialog');
            if (dlg && dlg.parentElement !== document.body) document.body.appendChild(dlg);
            if (typeof openSettings === 'function') openSettings();
            selectSettingsTab('room');
            var tab = document.getElementById('settingsTabRoom');
            if (tab) tab.focus({preventScroll: true});
        }

        // ── Settings › Writers' Room ───────────────────────────────────
        var _rm = null;
        var _rmDirty = false;
        function _rmChanged() {
            _rmDirty = true;
            if (typeof markSettingsDirty === 'function') markSettingsDirty();
        }

        function loadRoomSettings() {
            var body = document.getElementById('roomSettingsBody');
            return _sgPost('/api/discuss/room-settings', {}).then(function(data) {
                var prevCatalogs = (_rm && _rm.catalogs) || {};
                _rm = data.settings;
                _rm.catalogs = prevCatalogs;
                _rmDirty = false;
                renderRoomSettings();
                if (typeof syncRoomSettingsState === 'function') syncRoomSettingsState(_rm);
                SG_AGENTS.forEach(function(agent) {
                    if (_rm.catalogs[agent.id]) return;
                    _sgPost('/api/discuss/models', {agent: agent.id}).then(function(res) {
                        _rm.catalogs[agent.id] = res.catalog;
                        if (!document.getElementById('roomSettingsBody').contains(document.activeElement)) renderRoomSettings();
                    }).catch(function() {
                        _rm.catalogs[agent.id] = {unavailable: true, models: []};
                        if (!document.getElementById('roomSettingsBody').contains(document.activeElement)) renderRoomSettings();
                    });
                });
                return _rm;
            }).catch(function(error) {
                if (body) body.replaceChildren(_sgEl('p', 'settings-unit', 'Could not load: ' + error.message));
            });
        }

        function saveRoomSettings() {
            if (!_rm || !_rmDirty) return Promise.resolve();
            return _sgPost('/api/discuss/room-settings', {save: true, library: _rm.library})
                .then(function(data) {
                    var catalogs = _rm.catalogs;
                    _rm = data.settings;
                    _rm.catalogs = catalogs;
                    _rmDirty = false;
                    renderRoomSettings();
                    if (typeof syncRoomSettingsState === 'function') syncRoomSettingsState(_rm);
                });
        }

        function _rmSelect(options, value, onChange, label) {
            var select = _sgEl('select', 'settings-input');
            select.setAttribute('aria-label', label);
            options.forEach(function(opt) {
                var o = _sgEl('option', '', opt.label);
                o.value = opt.value;
                select.appendChild(o);
            });
            select.value = String(value);
            if (select.value !== String(value) && value) {
                var o = _sgEl('option', '', value + ' (not listed)');
                o.value = String(value);
                select.appendChild(o);
                select.value = String(value);
            }
            select.onchange = function() { onChange(select.value); _rmChanged(); };
            return select;
        }

        function _rmPromptField(label, value, fallback, onChange) {
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
            area.oninput = function() { onChange(area.value); reset.disabled = area.value === fallback; _rmChanged(); };
            reset.onclick = function() { area.value = fallback; onChange(fallback); reset.disabled = true; _rmChanged(); };
            head.append(title, reset);
            wrap.append(head, area);
            return wrap;
        }

        function _rmField(container, label, value, onChange, multiline, maxLength) {
            var wrap = _sgEl('label', 'room-library-field');
            var visibleLabel = label.replace(/^(?:Profile|Preset) \d+ /, '');
            visibleLabel = visibleLabel === 'style' ? 'Conversational style' : visibleLabel.charAt(0).toUpperCase() + visibleLabel.slice(1);
            wrap.appendChild(_sgEl('span', 'settings-label', visibleLabel));
            var field = _sgEl(multiline ? 'textarea' : 'input', multiline ? 'suggestion-prompt-text' : 'settings-input');
            field.setAttribute('aria-label', label);
            field.value = value || '';
            if (multiline) field.rows = 3;
            field.maxLength = maxLength || 8000;
            field.oninput = function() { onChange(field.value); _rmChanged(); };
            wrap.appendChild(field);
            container.appendChild(wrap);
        }

        function _rmProfileOptions() {
            return _rm.library.profiles.map(function(p) { return {value: p.id, label: p.name + ' · ' + (p.agent === 'claude' ? 'Claude' : 'Codex')}; });
        }

        function _rmPairFields(container, pair, prefix) {
            pair.forEach(function(id, index) {
                var label = _sgEl('label', 'room-library-field');
                label.appendChild(_sgEl('span', 'settings-label', prefix.replace(/^Preset \d+ /, '') + ' ' + (index + 1)));
                var select = _rmSelect(_rmProfileOptions().filter(function(p) { return p.value !== pair[1 - index]; }), id,
                    function(v) { pair[index] = v; renderRoomSettings(); }, prefix + ' ' + (index + 1));
                label.appendChild(select);
                container.appendChild(label);
            });
        }

        function _rmResizeInvitations(preset, count) {
            preset.invitations = preset.invitations.slice(0, count);
            while (preset.invitations.length < count) preset.invitations.push({seat: preset.invitations.length % 2 + 1,
                prompt: 'Respond to the discussion so far. Agree, disagree, or refine anything useful.'});
        }

        function renderRoomSettings() {
            var body = document.getElementById('roomSettingsBody');
            if (!body || !_rm || !_rm.library) return;
            var opened = Array.from(body.querySelectorAll('.room-library-card')).map(function(card) { return card.open; });
            body.replaceChildren();
            var library = _rm.library;
            body.appendChild(_sgEl('p', 'settings-note', 'Profiles and presets are reusable across books on this computer. Each Room keeps its participants as they were when the conversation started. Blank model and effort choices inherit the agent’s individual chat settings.'));
            body.appendChild(_sgEl('p', 'suggestion-subhead', 'Default participants'));
            var defaults = _sgEl('div', 'room-library-pair');
            _rmPairFields(defaults, library.default_profiles, 'Default participant');
            body.appendChild(defaults);
            body.appendChild(_sgEl('p', 'suggestion-subhead', 'Agent profiles'));
            library.profiles.forEach(function(profile, index) {
                var card = _sgEl('details', 'room-library-card');
                var prefix = 'Profile ' + (index + 1);
                card.appendChild(_sgEl('summary', '', profile.name + ' · ' + (profile.agent === 'claude' ? 'Claude' : 'Codex')));
                _rmField(card, prefix + ' name', profile.name, function(v) { profile.name = v; }, false, 60);
                _rmField(card, prefix + ' specialty', profile.specialty, function(v) { profile.specialty = v; }, true);
                _rmField(card, prefix + ' style', profile.style, function(v) { profile.style = v; }, true);
                var provider = _sgEl('label', 'room-library-field');
                provider.appendChild(_sgEl('span', 'settings-label', 'Provider'));
                provider.appendChild(_rmSelect(SG_AGENTS.map(function(a) { return {value: a.id, label: a.label}; }), profile.agent,
                    function(v) { profile.agent = v; profile.model = ''; profile.effort = ''; renderRoomSettings(); }, prefix + ' provider'));
                card.appendChild(provider);
                var catalog = (_rm.catalogs || {})[profile.agent] || {};
                var models = [{value: '', label: 'Same as chat'}].concat((catalog.models || []).map(function(m) { return {value: m.id, label: m.label || m.id}; }));
                var model = _sgEl('label', 'room-library-field');
                model.appendChild(_sgEl('span', 'settings-label', 'Model'));
                model.appendChild(_rmSelect(models, profile.model, function(v) { profile.model = v; profile.effort = ''; renderRoomSettings(); }, prefix + ' model'));
                card.appendChild(model);
                var selected = (catalog.models || []).find(function(m) { return m.id === profile.model; });
                var efforts = selected && selected.efforts && selected.efforts.length ? selected.efforts.map(function(e) { return e.id; }) : ['low', 'medium', 'high', 'xhigh', 'max'];
                var effort = _sgEl('label', 'room-library-field');
                effort.appendChild(_sgEl('span', 'settings-label', 'Reasoning effort'));
                effort.appendChild(_rmSelect([{value: '', label: 'Same as chat'}].concat(efforts.map(function(e) { return {value: e, label: e}; })), profile.effort,
                    function(v) { profile.effort = v; }, prefix + ' effort'));
                card.appendChild(effort);
                var used = library.default_profiles.includes(profile.id) || library.presets.some(function(p) { return p.profiles.includes(profile.id); });
                var remove = _sgEl('button', 'settings-plain-btn', 'Delete profile');
                remove.type = 'button'; remove.disabled = used || library.profiles.length <= 2;
                remove.title = used ? 'Choose another profile in defaults and presets before deleting this one.' : '';
                remove.onclick = function() { library.profiles.splice(index, 1); _rmChanged(); renderRoomSettings(); };
                card.appendChild(remove);
                body.appendChild(card);
            });
            var addProfile = _sgEl('button', 'settings-plain-btn', '+ Add profile');
            addProfile.type = 'button'; addProfile.disabled = library.profiles.length >= 32;
            addProfile.onclick = function() {
                library.profiles.push({id: 'profile-' + Date.now(), name: 'New Editor', specialty: '', style: '', agent: 'codex', model: '', effort: ''});
                _rmChanged(); renderRoomSettings();
                body.querySelectorAll('.room-library-card')[library.profiles.length - 1].open = true;
            };
            body.appendChild(addProfile);
            body.appendChild(_sgEl('p', 'suggestion-subhead', 'Discussion presets'));
            body.appendChild(_sgEl('p', 'settings-note', 'A preset posts invitations to the two participants. Either participant can pass. An optional recap is one extra invitation to the selected participant; the conversation stays open afterward.'));
            library.presets.forEach(function(preset, index) {
                var card = _sgEl('details', 'room-library-card');
                var prefix = 'Preset ' + (index + 1);
                card.appendChild(_sgEl('summary', '', preset.name + ' · ' + preset.invitations.length + ' invitations'));
                _rmField(card, prefix + ' name', preset.name, function(v) { preset.name = v; }, false, 100);
                _rmField(card, prefix + ' description', preset.description, function(v) { preset.description = v; }, true, 500);
                _rmPairFields(card, preset.profiles, prefix + ' participant');
                var count = _sgEl('label', 'room-library-field');
                count.appendChild(_sgEl('span', 'settings-label', 'Invitations'));
                count.appendChild(_rmSelect(Array.from({length: 11}, function(_, i) { return {value: String(i + 2), label: String(i + 2)}; }), preset.invitations.length,
                    function(v) { _rmResizeInvitations(preset, Number(v)); renderRoomSettings(); }, prefix + ' invitations'));
                card.appendChild(count);
                var names = preset.profiles.map(function(id) { return library.profiles.find(function(p) { return p.id === id; }).name; });
                preset.invitations.forEach(function(step, stepIndex) {
                    var label = prefix + ' invitation ' + (stepIndex + 1);
                    var wrap = _sgEl('div', 'room-library-step');
                    wrap.appendChild(_rmSelect([{value: '1', label: names[0]}, {value: '2', label: names[1]}], step.seat,
                        function(v) { step.seat = Number(v); }, label + ' recipient'));
                    _rmField(wrap, label, step.prompt, function(v) { step.prompt = v; }, true);
                    card.appendChild(wrap);
                });
                var recap = _sgEl('label', 'room-library-field');
                recap.appendChild(_sgEl('span', 'settings-label', 'Optional recap'));
                recap.appendChild(_rmSelect([{value: '0', label: 'No recap'}, {value: '1', label: names[0]}, {value: '2', label: names[1]}], preset.recap,
                    function(v) { preset.recap = Number(v); }, prefix + ' recap'));
                card.appendChild(recap);
                var remove = _sgEl('button', 'settings-plain-btn', 'Delete preset'); remove.type = 'button';
                remove.onclick = function() { library.presets.splice(index, 1); _rmChanged(); renderRoomSettings(); };
                card.appendChild(remove); body.appendChild(card);
            });
            var addPreset = _sgEl('button', 'settings-plain-btn', '+ Add preset'); addPreset.type = 'button'; addPreset.disabled = library.presets.length >= 32;
            addPreset.onclick = function() {
                library.presets.push({id: 'preset-' + Date.now(), name: 'New discussion', description: '', profiles: library.default_profiles.slice(), recap: 0,
                    invitations: [{seat: 1, prompt: 'Give your opinion on this scene.'}, {seat: 2, prompt: 'Give your own view and respond to the discussion.'}]});
                _rmChanged(); renderRoomSettings();
                var cards = body.querySelectorAll('.room-library-card'); cards[cards.length - 1].open = true;
            };
            body.appendChild(addPreset);
            body.querySelectorAll('.room-library-card').forEach(function(card, i) { card.open = !!opened[i]; });
        }

        document.addEventListener('DOMContentLoaded', function() {
            // Arrow keys move between the tabs, as in any tab row.
            var row = document.querySelector('.settings-tabs');
            if (row) row.addEventListener('keydown', function(e) {
                if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
                var idx = SETTINGS_TABS.findIndex(function(t) {
                    var id = t.charAt(0).toUpperCase() + t.slice(1);
                    var btn = document.getElementById('settingsTab' + id);
                    return btn && btn.getAttribute('aria-selected') === 'true';
                });
                if (idx < 0) idx = 0;
                var delta = e.key === 'ArrowRight' ? 1 : -1;
                var next = SETTINGS_TABS[(idx + delta + SETTINGS_TABS.length) % SETTINGS_TABS.length];
                selectSettingsTab(next);
                var nextId = next.charAt(0).toUpperCase() + next.slice(1);
                var nextBtn = document.getElementById('settingsTab' + nextId);
                if (nextBtn) nextBtn.focus({preventScroll: true});
                e.preventDefault();
            });
        });
