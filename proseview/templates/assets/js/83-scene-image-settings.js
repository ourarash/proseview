// ── Settings › Scene Image ─────────────────────────────────────────────────
// Built-in visual style gallery, optional art-direction override, default agent
// & model, aspect ratio, chapter assets folder, context toggles, and prompt
// template saved into .proseview.yaml under scene_image:.
var _siSettings = null;
var _siSettingsDirty = false;
var _siCatalogs = {};

function _siSetPost(path, body) {
    return fetch(path, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body || {})})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.ok) throw new Error(data.error || 'Request failed');
            return data;
        });
}

function _siEl(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
}

function _siSettingsChanged() {
    _siSettingsDirty = true;
    if (typeof markSettingsDirty === 'function') markSettingsDirty();
}

function _siUpdateModelSelect() {
    var select = document.getElementById('siSettingModel');
    if (!select || !_siSettings) return;
    var book = _siSettings.book || {};
    var selectedAgent = book.agent || 'codex';
    var cat = _siCatalogs[selectedAgent];
    var opts = [{value: '', label: 'Agent default (recommended)'}];
    if (cat && cat.models && cat.models.length) {
        cat.models.forEach(function(m) {
            opts.push({value: m.id, label: m.label || m.id});
        });
    } else if (cat && cat.unavailable) {
        opts = [{value: '', label: 'Default CLI model (catalog unavailable)'}];
    }
    select.replaceChildren();
    opts.forEach(function(o) {
        var el = _siEl('option', '', o.label);
        el.value = o.value;
        select.appendChild(el);
    });
    select.value = book.model || '';
}

function loadSceneImageSettings() {
    var body = document.getElementById('sceneImageSettingsBody');
    if (!body) return Promise.resolve();
    return _siSetPost('/api/discuss/scene-image-settings', {}).then(function(data) {
        _siSettings = data.settings;
        _siSettingsDirty = false;
        renderSceneImageSettings();
        ['codex', 'agy', 'claude'].forEach(function(agent) {
            _siSetPost('/api/discuss/models', {agent: agent}).then(function(res) {
                _siCatalogs[agent] = res.catalog;
                if (_siSettingsDirty) _siUpdateModelSelect();
                else renderSceneImageSettings();
            }).catch(function() {
                _siCatalogs[agent] = {unavailable: true, models: []};
                if (_siSettingsDirty) _siUpdateModelSelect();
                else renderSceneImageSettings();
            });
        });
    }).catch(function(err) {
        body.replaceChildren(_siEl('p', 'settings-unit', 'Could not load scene image settings: ' + err.message));
    });
}

function saveSceneImageSettings() {
    if (!_siSettings || !_siSettingsDirty) return Promise.resolve();
    return _siSetPost('/api/discuss/scene-image-settings', {save: true, book: _siSettings.book})
        .then(function(data) {
            _siSettings = data.settings;
            _siSettingsDirty = false;
            if (typeof syncSceneImageDefaultsFromSettings === 'function') {
                syncSceneImageDefaultsFromSettings(data.settings);
            }
            renderSceneImageSettings();
        });
}

function openSceneImageSettings() {
    var dlg = document.getElementById('settingsDialog');
    if (dlg && dlg.parentElement !== document.body) document.body.appendChild(dlg);
    if (typeof openSettings === 'function') openSettings();
    if (typeof selectSettingsTab === 'function') selectSettingsTab('sceneimage');
    var tab = document.getElementById('settingsTabSceneimage');
    if (tab) tab.focus({preventScroll: true});
}

function renderSceneImageSettings() {
    var body = document.getElementById('sceneImageSettingsBody');
    if (!body || !_siSettings) return;
    body.replaceChildren();

    var book = _siSettings.book;
    var defaults = _siSettings.defaults;
    var styles = _siSettings.styles || [];
    var caps = _siSettings.capabilities || {};
    var claudeMcp = !!(caps.claude && caps.claude.mcp_detected);

    // 1. Built-in Book Styles Gallery
    var gallerySection = _siEl('div', 'si-settings-section');
    var galleryHead = _siEl('div', 'si-settings-head');
    galleryHead.append(
        _siEl('span', 'settings-label', 'Built-in book styles'),
        _siEl('span', 'settings-unit', 'Same scene rendered across styles · click to choose')
    );
    var galleryGrid = _siEl('div', 'si-settings-style-gallery');
    styles.forEach(function(st) {
        var selected = book.style_preset === st.id;
        var card = _siEl('button', 'si-gallery-card' + (selected ? ' is-selected' : ''));
        card.type = 'button';
        var img = document.createElement('img');
        img.src = st.thumb;
        img.alt = st.name + ' sample';
        img.className = 'si-gallery-thumb';
        img.loading = 'lazy';
        var info = _siEl('div', 'si-gallery-info');
        var top = _siEl('div', 'si-gallery-top');
        top.append(_siEl('span', 'si-gallery-name', st.name));
        if (selected) top.append(_siEl('span', 'si-gallery-active', 'Active'));
        info.append(top, _siEl('span', 'si-gallery-tagline', st.tagline));
        card.append(img, info);
        card.onclick = function() {
            book.style_preset = st.id;
            book.style = st.prompt;
            _siSettingsChanged();
            renderSceneImageSettings();
        };
        galleryGrid.appendChild(card);
    });
    gallerySection.append(galleryHead, galleryGrid);
    body.appendChild(gallerySection);

    // 2. Art direction prompt (auto-filled from preset; editing switches to custom)
    var styleWrap = _siEl('div', 'suggestion-prompt');
    var styleHead = _siEl('div', 'suggestion-prompt-head');
    var presetMatch = styles.find(function(s) { return s.id === book.style_preset; });
    var styleReset = _siEl('button', 'settings-plain-btn', 'Reset to preset');
    styleReset.type = 'button';
    styleReset.disabled = !!(presetMatch && (book.style || '').trim() === (presetMatch.prompt || '').trim());
    var styleInput = _siEl('textarea', 'suggestion-prompt-text');
    styleInput.rows = 2;
    styleInput.value = book.style || '';
    styleInput.setAttribute('aria-label', 'Art direction prompt');
    styleInput.oninput = function() {
        book.style = styleInput.value;
        var exact = styles.find(function(s) { return s.prompt.trim() === styleInput.value.trim(); });
        book.style_preset = exact ? exact.id : 'custom';
        styleReset.disabled = !!exact;
        _siSettingsChanged();
    };
    styleReset.onclick = function() {
        var target = presetMatch || styles[0];
        if (!target) return;
        book.style_preset = target.id;
        book.style = target.prompt;
        _siSettingsChanged();
        renderSceneImageSettings();
    };
    styleHead.append(_siEl('span', 'settings-label', 'Art direction prompt'), styleReset);
    styleWrap.append(styleHead, styleInput, _siEl('span', 'settings-hint', 'Pre-filled from the selected style. Edit freely to tailor your book\'s look.'));
    body.appendChild(styleWrap);

    // 3. Default Agent & Model
    var agentRow = _siEl('div', 'settings-row');
    var agentSelect = _siEl('select', 'settings-input');
    agentSelect.setAttribute('aria-label', 'Default image agent');
    [
        {value: 'codex', label: 'Codex CLI (native image generation)', disabled: false},
        {value: 'agy', label: 'Agy CLI (native image-generator)', disabled: false},
        {
            value: 'claude',
            label: claudeMcp ? 'Claude CLI (image MCP server connected)' : 'Claude CLI (requires image MCP server)',
            disabled: !claudeMcp
        }
    ].forEach(function(opt) {
        var o = _siEl('option', '', opt.label);
        o.value = opt.value;
        o.disabled = opt.disabled;
        agentSelect.appendChild(o);
    });
    agentSelect.value = book.agent || 'codex';
    agentSelect.onchange = function() {
        book.agent = agentSelect.value;
        book.model = '';
        _siSettingsChanged();
        _siUpdateModelSelect();
    };
    var agentField = _siEl('span', 'settings-field');
    agentField.appendChild(agentSelect);
    var agentLabel = _siEl('label', '', 'Default agent');
    agentLabel.appendChild(_siEl('span', 'settings-hint', claudeMcp
        ? 'Image MCP detected in Claude Code; Codex and Agy have native raster generation.'
        : 'Codex and Agy generate images natively. Connect an image MCP server in Claude Code to enable Claude.'));
    agentRow.append(agentLabel, agentField);
    body.appendChild(agentRow);

    var modelRow = _siEl('div', 'settings-row');
    var modelSelect = _siEl('select', 'settings-input');
    modelSelect.id = 'siSettingModel';
    modelSelect.setAttribute('aria-label', 'Scene image model');
    modelSelect.onchange = function() {
        book.model = modelSelect.value;
        _siSettingsChanged();
    };
    var modelField = _siEl('span', 'settings-field');
    modelField.appendChild(modelSelect);
    modelRow.append(_siEl('label', '', 'Model'), modelField);
    body.appendChild(modelRow);
    _siUpdateModelSelect();

    // 4. Aspect Ratio & Scene Asset Folder
    var aspectRow = _siEl('div', 'settings-row');
    var aspectSelect = _siEl('select', 'settings-input');
    aspectSelect.setAttribute('aria-label', 'Aspect ratio');
    [
        {value: '16:9', label: '16:9 — Wide cinematic header'},
        {value: '3:2', label: '3:2 — Editorial book plate'},
        {value: '4:3', label: '4:3 — Classic illustration'},
        {value: '1:1', label: '1:1 — Square vignette'}
    ].forEach(function(opt) {
        var o = _siEl('option', '', opt.label);
        o.value = opt.value;
        aspectSelect.appendChild(o);
    });
    aspectSelect.value = book.aspect_ratio || '16:9';
    aspectSelect.onchange = function() { book.aspect_ratio = aspectSelect.value; _siSettingsChanged(); };
    var aspectField = _siEl('span', 'settings-field');
    aspectField.appendChild(aspectSelect);
    aspectRow.append(_siEl('label', '', 'Aspect ratio'), aspectField);
    body.appendChild(aspectRow);

    var folderRow = _siEl('div', 'settings-row');
    var folderInput = _siEl('input', 'settings-input');
    folderInput.type = 'text';
    folderInput.value = book.assets_dir || 'assets';
    folderInput.placeholder = 'assets';
    folderInput.setAttribute('aria-label', 'Chapter asset folder');
    folderInput.oninput = function() { book.assets_dir = folderInput.value.trim() || 'assets'; _siSettingsChanged(); };
    var folderLabel = _siEl('label', '', 'Chapter asset folder');
    folderLabel.appendChild(_siEl('span', 'settings-hint', 'Relative to each chapter folder (e.g. ch01/assets/01-opening.png). Start with / for one book-wide folder. Previews stay in .proseview/ until inserted.'));
    var folderField = _siEl('span', 'settings-field');
    folderField.appendChild(folderInput);
    folderRow.append(folderLabel, folderField);
    body.appendChild(folderRow);

    var widthRow = _siEl('div', 'settings-row');
    var widthInput = _siEl('input', 'settings-input');
    widthInput.type = 'number';
    widthInput.min = '120';
    widthInput.max = '1600';
    widthInput.step = '20';
    widthInput.value = String(book.width || 600);
    widthInput.setAttribute('aria-label', 'Inserted image width in pixels');
    widthInput.oninput = function() {
        var n = parseInt(widthInput.value, 10);
        if (!isNaN(n)) book.width = n;
        _siSettingsChanged();
    };
    var widthLabel = _siEl('label', '', 'Inserted image width');
    widthLabel.appendChild(_siEl('span', 'settings-hint', 'Written as width="…" on the inserted <img> tag (120–1600 px; 600 px fills the reading column).'));
    var widthField = _siEl('span', 'settings-field');
    widthField.append(widthInput, _siEl('span', 'settings-unit', 'px'));
    widthRow.append(widthLabel, widthField);
    body.appendChild(widthRow);

    // 5. Context checkboxes
    var ctxRow = _siEl('div', 'settings-row');
    var ctxField = _siEl('span', 'settings-field si-check-stack');
    [
        ['include_frontmatter', 'Scene frontmatter (POV, location, time)'],
        ['include_characters', 'Character bios & location notes'],
        ['instructions', 'Book & repository agent instructions']
    ].forEach(function(pair) {
        var wrap = _siEl('label', 'suggestion-check');
        var box = _siEl('input');
        box.type = 'checkbox';
        box.checked = !!book[pair[0]];
        box.onchange = function() { book[pair[0]] = box.checked; _siSettingsChanged(); };
        wrap.append(box, document.createTextNode(' ' + pair[1]));
        ctxField.appendChild(wrap);
    });
    ctxRow.append(_siEl('span', 'settings-label', 'Scene context'), ctxField);
    body.appendChild(ctxRow);

    // 6. Optional Base Prompt Template
    var promptWrap = _siEl('div', 'suggestion-prompt');
    var promptHead = _siEl('div', 'suggestion-prompt-head');
    var promptReset = _siEl('button', 'settings-plain-btn', 'Reset to default');
    promptReset.type = 'button';
    promptReset.disabled = (book.prompt || '').trim() === (defaults.prompt || '').trim();
    var promptArea = _siEl('textarea', 'suggestion-prompt-text');
    promptArea.rows = 3;
    promptArea.value = book.prompt || defaults.prompt || '';
    promptArea.setAttribute('aria-label', 'Base scene image prompt');
    promptArea.oninput = function() {
        book.prompt = promptArea.value;
        promptReset.disabled = promptArea.value.trim() === (defaults.prompt || '').trim();
        _siSettingsChanged();
    };
    promptReset.onclick = function() {
        book.prompt = defaults.prompt;
        promptArea.value = defaults.prompt;
        promptReset.disabled = true;
        _siSettingsChanged();
    };
    promptHead.append(_siEl('span', 'settings-label', 'Base prompt template (optional)'), promptReset);
    promptWrap.append(promptHead, promptArea);
    body.appendChild(promptWrap);
}
