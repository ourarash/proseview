        // ── Export ───────────────────────────────────────────────────────────────
        // A three-step dialog that turns the book, or part of it, into an EPUB:
        // what to export, how it looks, and the book's details with a preview.
        // The server builds the same book the `proseview export` command does
        // (see proseview/export_dashboard.py); this file only gathers choices.

        var exportState = {
            outline: null,
            checked: new Set(),     // scene keys
            expanded: new Set(),    // chapter numbers
            reorder: false,
            order: [],              // [{kind: 'chapter'|'scene', id}] while reordering
            step: 1,
            details: null,
            preview: null,          // {token, pages}
            pageIndex: 0,
            previewTimer: null,
            previewSeq: 0,
            job: null,
            returnFocus: null,
            preset: null,
        };

        var EXPORT_STEP_HINTS = {
            1: 'Choose what goes into the e-book.',
            2: 'Choose the kind of book and how it looks.',
            3: 'Check the details readers and stores will see.',
            run: 'This takes a few seconds.',
            done: '',
        };

        function exportEl(id) { return document.getElementById(id); }

        function exportFormat(n) { return Number(n || 0).toLocaleString(); }

        function exportPlural(n, noun) { return exportFormat(n) + ' ' + noun + (n === 1 ? '' : 's'); }

        //: What the dialog needs the server to understand. A server started
        //: before an update keeps its old code while the page picks up the new
        //: one; this tells them apart.
        var EXPORT_API = 3;

        var EXPORT_MESSAGES = {
            offline: 'Proseview has stopped running, so this could not be done. '
                + 'Start it again (the same way you started it before), then reload this page.',
            stale: 'This page was opened by an earlier run of Proseview. Reload the page and try again.',
            outdated: 'Proseview was updated while it was running. Stop it, start it again, then reload this page.',
        };

        function exportError(message, code, data) {
            var error = new Error(message);
            error.code = code || '';
            error.data = data || {};
            return error;
        }

        function exportFetchJson(url, options) {
            return fetch(url, options).catch(function() {
                // The browser says only "Failed to fetch": nothing answered.
                throw exportError(EXPORT_MESSAGES.offline, 'offline');
            }).then(function(response) {
                return response.json().catch(function() { return {}; }).then(function(data) {
                    if (response.status === 403 && /page session/.test(data.error || '')) {
                        throw exportError(EXPORT_MESSAGES.stale, 'stale', data);
                    }
                    if (!response.ok || data.ok === false) {
                        throw exportError(data.error || 'Something went wrong. Please try again.', '', data);
                    }
                    return data;
                });
            });
        }

        function exportPost(url, body) {
            return exportFetchJson(url, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body)});
        }

        // ── Opening ──────────────────────────────────────────────────────────

        // preset: null (whole book), {scene: key} or {chapterOf: key}, or
        // {folder: 'manuscript/ch01'} from the file browser.
        // The read-only snapshot has no Export; the demo answers it from
        // ready-made books of the whole manuscript (01-static-snapshot.js).
        function exportAvailable() { return !window.PROSEVIEW_STATIC || !!window.PROSEVIEW_STATIC_EDITS; }
        function exportIsDemo() { return !!window.PROSEVIEW_STATIC; }

        function exportPreviewUrl(token, href) {
            return exportIsDemo() ? 'export/previews/' + token + '/' + href : '/api/export/preview/' + token + '/' + href;
        }

        function exportFileUrl(file) {
            return exportIsDemo() ? file.path : '/api/export/file?path=' + encodeURIComponent(file.path);
        }

        function openExportDialog(preset) {
            if (!exportAvailable()) return;
            var dialog = exportEl('exportDialog');
            if (!dialog || dialog.open) return;
            exportState.returnFocus = document.activeElement;
            exportEl('exportDemoNote').hidden = !exportIsDemo();
            exportState.preset = preset || null;
            exportState.step = 1;
            exportState.job = null;
            exportState.preview = null;
            exportEl('exportTree').innerHTML = '<li class="export-loading">Loading chapters…</li>';
            exportShowStep(1);
            dialog.showModal();
            exportFetchJson('/api/export/outline').then(function(outline) {
                if (!(outline.api >= EXPORT_API)) throw exportError(EXPORT_MESSAGES.outdated, 'outdated');
                exportState.outline = outline;
                exportState.details = Object.assign({}, outline.details);
                exportApplyPreset(exportState.preset);
                // "Preview as PDF" skips to the preview in the format it names.
                if (exportState.preset && exportState.preset.format) exportState.details.format = exportState.preset.format;
                exportRenderAll();
                if (exportState.preset && exportState.preset.step) exportShowStep(exportState.preset.step);
                var first = exportEl('exportTree').querySelector('input');
                if (first && !exportState.preset) first.focus();
            }).catch(function(error) {
                exportEl('exportTree').innerHTML = '';
                var item = document.createElement('li');
                item.className = 'export-error';
                item.setAttribute('role', 'alert');
                item.textContent = error.message;
                if (error.code) {
                    item.appendChild(document.createTextNode(' '));
                    item.appendChild(exportButton('Reload page', 'export-btn-primary', function() { location.reload(); }));
                }
                exportEl('exportTree').appendChild(item);
            });
        }

        function openExportForCurrentScene(what) {
            var scenePath = typeof currentScenePath === 'function' ? currentScenePath() : null;
            if (!scenePath) return;
            var key = scenePath.replace(/\.md$/i, '');
            if (what === 'pdf') openExportDialog({scene: key, format: 'pdf-share', step: 3});
            else openExportDialog(what === 'chapter' ? {chapterOf: key} : {scene: key});
        }

        function exportMenuItemsFor(node) {
            // Called by the file browser's row menu (75-file-management.js).
            if (!exportAvailable() || !node) return [];
            if (node.is_file) {
                if (!node.scene_path) return [];
                var key = node.scene_path.replace(/\.md$/i, '');
                return [
                    {label: 'Export this scene…', action: 'export-scene', run: function() { openExportDialog({scene: key}); }},
                    {label: 'Export this chapter…', action: 'export-chapter', run: function() { openExportDialog({chapterOf: key}); }},
                ];
            }
            var scenes = 0;
            var folders = 0;
            (node.children || []).forEach(function(child) {
                if (child.is_file && child.scene_path) scenes += 1;
                if (!child.is_file) sidebarWalk([child], function(inner) { if (inner.is_file && inner.scene_path) folders += 1; });
            });
            if (!scenes && !folders) return [];
            var label = folders && !scenes ? 'Export these chapters…' : 'Export this chapter…';
            return [{label: label, action: 'export-folder', run: function() { openExportDialog({folder: node.path}); }}];
        }

        function exportAllScenes() {
            var keys = [];
            (exportState.outline ? exportState.outline.chapters : []).forEach(function(chapter) {
                chapter.scenes.forEach(function(scene) { keys.push(scene.key); });
            });
            return keys;
        }

        function exportChapterOf(key) {
            return (exportState.outline.chapters || []).find(function(chapter) {
                return chapter.scenes.some(function(scene) { return scene.key === key; });
            });
        }

        function exportApplyPreset(preset) {
            var outline = exportState.outline;
            exportState.reorder = false;
            exportState.order = [];
            exportState.expanded = new Set();
            exportState.checked = new Set();
            if (!preset) {
                exportState.checked = new Set(exportAllScenes());
                return;
            }
            outline.chapters.forEach(function(chapter) {
                chapter.scenes.forEach(function(scene) {
                    var take = (preset.scene && scene.key === preset.scene)
                        || (preset.folder && scene.path.indexOf(preset.folder.replace(/\/$/, '') + '/') === 0);
                    if (take) {
                        exportState.checked.add(scene.key);
                        if (preset.scene) exportState.expanded.add(chapter.number);
                    }
                });
            });
            if (preset.chapterOf) {
                var chapter = exportChapterOf(preset.chapterOf);
                if (chapter) chapter.scenes.forEach(function(scene) { exportState.checked.add(scene.key); });
            }
            if (!exportState.checked.size) exportState.checked = new Set(exportAllScenes());
        }

        // ── Step 1: what to export ───────────────────────────────────────────

        function exportChapterState(chapter) {
            var ticked = chapter.scenes.filter(function(scene) { return exportState.checked.has(scene.key); }).length;
            return ticked === 0 ? 'none' : (ticked === chapter.scenes.length ? 'all' : 'some');
        }

        function exportSelectionItems() {
            if (exportState.reorder) return exportState.order.slice();
            var items = [];
            exportState.outline.chapters.forEach(function(chapter) {
                var state = exportChapterState(chapter);
                if (state === 'all') items.push({kind: 'chapter', id: String(chapter.number)});
                else if (state === 'some') {
                    chapter.scenes.forEach(function(scene) {
                        if (exportState.checked.has(scene.key)) items.push({kind: 'scene', id: scene.key});
                    });
                }
            });
            return items;
        }

        function exportSelectionPayload() {
            return {order: exportState.reorder ? 'custom' : 'book', items: exportSelectionItems()};
        }

        function exportIsWholeBook() {
            return !exportState.reorder && exportState.checked.size === exportAllScenes().length;
        }

        function exportTotals() {
            var chapters = 0, scenes = 0, words = 0;
            (exportState.outline ? exportState.outline.chapters : []).forEach(function(chapter) {
                var any = false;
                chapter.scenes.forEach(function(scene) {
                    if (!exportState.checked.has(scene.key)) return;
                    any = true;
                    scenes += 1;
                    words += scene.words;
                });
                if (any) chapters += 1;
            });
            return {chapters: chapters, scenes: scenes, words: words};
        }

        function exportRenderTotals() {
            var totals = exportTotals();
            var text = totals.scenes
                ? exportPlural(totals.chapters, 'chapter') + ', ' + exportPlural(totals.scenes, 'scene') + ', ' + exportPlural(totals.words, 'word')
                : 'Nothing ticked yet';
            if (exportIsWholeBook()) text = 'The whole book: ' + text;
            exportEl('exportTotals').textContent = text;
        }

        function exportChapterHeading(chapter) {
            return chapter.title ? chapter.label + ' · ' + chapter.title : chapter.label;
        }

        function exportRenderTree() {
            var tree = exportEl('exportTree');
            tree.innerHTML = '';
            exportState.outline.chapters.forEach(function(chapter) {
                var state = exportChapterState(chapter);
                var open = exportState.expanded.has(chapter.number);
                var li = document.createElement('li');
                li.className = 'export-chapter';
                var row = document.createElement('div');
                row.className = 'export-row export-chapter-row';

                var toggle = document.createElement('button');
                toggle.type = 'button';
                toggle.className = 'export-disclosure';
                toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
                toggle.setAttribute('aria-label', (open ? 'Hide' : 'Show') + ' scenes in ' + chapter.label);
                toggle.innerHTML = '<span aria-hidden="true">&#9656;</span>';
                toggle.addEventListener('click', function() {
                    if (exportState.expanded.has(chapter.number)) exportState.expanded.delete(chapter.number);
                    else exportState.expanded.add(chapter.number);
                    exportRenderTree();
                    var again = exportEl('exportTree').querySelector('[data-chapter-toggle="' + chapter.number + '"]');
                    if (again) again.focus();
                });
                toggle.dataset.chapterToggle = String(chapter.number);

                var label = document.createElement('label');
                label.className = 'export-check';
                var box = document.createElement('input');
                box.type = 'checkbox';
                box.checked = state === 'all';
                box.indeterminate = state === 'some';
                box.dataset.chapter = String(chapter.number);
                box.addEventListener('change', function() {
                    chapter.scenes.forEach(function(scene) {
                        if (box.checked) exportState.checked.add(scene.key);
                        else exportState.checked.delete(scene.key);
                    });
                    exportSelectionChanged();
                    var again = exportEl('exportTree').querySelector('input[data-chapter="' + chapter.number + '"]');
                    if (again) again.focus();
                });
                var name = document.createElement('span');
                name.className = 'export-name';
                name.textContent = exportChapterHeading(chapter);
                label.appendChild(box);
                label.appendChild(name);

                var meta = document.createElement('span');
                meta.className = 'export-meta';
                meta.textContent = exportPlural(chapter.scenes.length, 'scene') + ' · ' + exportFormat(chapter.words) + ' words';

                row.appendChild(toggle);
                row.appendChild(label);
                row.appendChild(meta);
                li.appendChild(row);

                if (open) {
                    var list = document.createElement('ul');
                    list.className = 'export-scenes';
                    list.setAttribute('aria-label', 'Scenes in ' + chapter.label);
                    chapter.scenes.forEach(function(scene) {
                        var item = document.createElement('li');
                        item.className = 'export-row export-scene-row';
                        var sceneLabel = document.createElement('label');
                        sceneLabel.className = 'export-check';
                        var sceneBox = document.createElement('input');
                        sceneBox.type = 'checkbox';
                        sceneBox.checked = exportState.checked.has(scene.key);
                        sceneBox.dataset.scene = scene.key;
                        sceneBox.addEventListener('change', function() {
                            if (sceneBox.checked) exportState.checked.add(scene.key);
                            else exportState.checked.delete(scene.key);
                            exportSelectionChanged();
                            var again = exportEl('exportTree').querySelector('input[data-scene="' + CSS.escape(scene.key) + '"]');
                            if (again) again.focus();
                        });
                        var sceneName = document.createElement('span');
                        sceneName.className = 'export-name';
                        sceneName.textContent = scene.title;
                        sceneLabel.appendChild(sceneBox);
                        sceneLabel.appendChild(sceneName);
                        var sceneMeta = document.createElement('span');
                        sceneMeta.className = 'export-meta';
                        sceneMeta.textContent = exportFormat(scene.words) + ' words';
                        item.appendChild(sceneLabel);
                        item.appendChild(sceneMeta);
                        list.appendChild(item);
                    });
                    li.appendChild(list);
                }
                tree.appendChild(li);
            });
            var allOpen = exportState.expanded.size === exportState.outline.chapters.length;
            exportEl('exportExpandAll').textContent = allOpen ? 'Hide scenes' : 'Show all scenes';
        }

        function exportItemLabel(item) {
            var chapters = exportState.outline.chapters;
            if (item.kind === 'chapter') {
                var chapter = chapters.find(function(c) { return String(c.number) === item.id; });
                return chapter ? exportChapterHeading(chapter) + ' (' + exportPlural(chapter.scenes.length, 'scene') + ')' : item.id;
            }
            for (var i = 0; i < chapters.length; i++) {
                var scene = chapters[i].scenes.find(function(s) { return s.key === item.id; });
                if (scene) return scene.title + ' — ' + chapters[i].label;
            }
            return item.id;
        }

        function exportMoveOrder(from, to) {
            if (to < 0 || to >= exportState.order.length || from === to) return;
            var moved = exportState.order.splice(from, 1)[0];
            exportState.order.splice(to, 0, moved);
            exportRenderOrder(to);
            exportSchedulePreview();
        }

        function exportRenderOrder(focusIndex) {
            var list = exportEl('exportOrder');
            list.innerHTML = '';
            exportState.order.forEach(function(item, index) {
                var li = document.createElement('li');
                li.className = 'export-order-item';
                li.draggable = true;
                li.tabIndex = 0;
                li.dataset.index = String(index);
                li.setAttribute('aria-label', (index + 1) + '. ' + exportItemLabel(item) + '. Alt plus arrow keys move it.');
                li.innerHTML = '<span class="export-grip" aria-hidden="true">&#8942;&#8942;</span>';
                var text = document.createElement('span');
                text.className = 'export-name';
                text.textContent = exportItemLabel(item);
                li.appendChild(text);
                [['up', '&#8593;', -1], ['down', '&#8595;', 1]].forEach(function(spec) {
                    var button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'export-icon-btn';
                    button.innerHTML = spec[1];
                    button.setAttribute('aria-label', 'Move ' + exportItemLabel(item) + ' ' + spec[0]);
                    button.disabled = (spec[2] < 0 && index === 0) || (spec[2] > 0 && index === exportState.order.length - 1);
                    button.addEventListener('click', function() { exportMoveOrder(index, index + spec[2]); });
                    li.appendChild(button);
                });
                li.addEventListener('keydown', function(event) {
                    if (event.target !== li || !event.altKey) return;
                    if (event.key === 'ArrowUp') { event.preventDefault(); exportMoveOrder(index, index - 1); }
                    if (event.key === 'ArrowDown') { event.preventDefault(); exportMoveOrder(index, index + 1); }
                });
                li.addEventListener('dragstart', function(event) {
                    event.dataTransfer.effectAllowed = 'move';
                    event.dataTransfer.setData('text/plain', String(index));
                    li.classList.add('is-dragging');
                });
                li.addEventListener('dragend', function() { li.classList.remove('is-dragging'); });
                li.addEventListener('dragover', function(event) {
                    event.preventDefault();
                    li.classList.add('is-drop-target');
                });
                li.addEventListener('dragleave', function() { li.classList.remove('is-drop-target'); });
                li.addEventListener('drop', function(event) {
                    event.preventDefault();
                    li.classList.remove('is-drop-target');
                    var from = Number(event.dataTransfer.getData('text/plain'));
                    if (!Number.isNaN(from)) exportMoveOrder(from, index);
                });
                list.appendChild(li);
            });
            if (typeof focusIndex === 'number') {
                var target = list.querySelector('[data-index="' + focusIndex + '"]');
                if (target) target.focus();
            }
        }

        function exportSetReorder(on) {
            exportState.reorder = !!on;
            if (on && !exportState.order.length) {
                exportState.reorder = false;
                exportState.order = exportSelectionItems();
                exportState.reorder = true;
            }
            if (!on) exportState.order = [];
            exportEl('exportReorder').checked = exportState.reorder;
            exportEl('exportTree').hidden = exportState.reorder;
            exportEl('exportOrder').hidden = !exportState.reorder;
            exportEl('exportReorderNote').hidden = !exportState.reorder;
            exportEl('exportExpandAll').hidden = exportState.reorder;
            exportEl('exportListLabel').textContent = exportState.reorder ? 'Order of the book' : 'Chapters and scenes';
            if (exportState.reorder) exportRenderOrder();
            else exportRenderTree();
            exportRenderTotals();
            exportSchedulePreview();
        }

        function exportRenderQuickPicks() {
            var row = exportEl('exportQuickPicks');
            row.innerHTML = '';
            function chip(label, title, onPick, extra) {
                var button = document.createElement('button');
                button.type = 'button';
                button.className = 'export-chip' + (extra ? ' ' + extra : '');
                button.textContent = label;
                if (title) button.title = title;
                button.addEventListener('click', onPick);
                row.appendChild(button);
                return button;
            }
            chip('Whole book', 'Every chapter, with a title page and contents', function() {
                exportApplyPreset(null);
                exportSelectionChanged(true);
            });
            if (exportState.outline.chapters.length > 3) {
                chip('First three chapters', 'What agents usually ask for', function() {
                    exportApplyPreset(null);
                    exportState.checked = new Set();
                    exportState.outline.chapters.slice(0, 3).forEach(function(chapter) {
                        chapter.scenes.forEach(function(scene) { exportState.checked.add(scene.key); });
                    });
                    exportSelectionChanged(true);
                });
            }
            var wpp = (exportState.outline.words_per_page || {})[exportState.details.trim] || 290;
            var fiftyPages = exportFirstPages(50 * wpp);
            if (fiftyPages.size && fiftyPages.size < exportAllScenes().length) {
                chip('First 50 pages', 'About ' + exportFormat(50 * wpp) + ' words at the '
                    + exportState.details.trim.replace('x', ' × ') + ' trim size, in whole scenes', function() {
                    exportApplyPreset(null);
                    exportState.checked = exportFirstPages(50 * wpp);
                    exportSelectionChanged(true);
                });
            }
            (exportState.outline.selections || []).forEach(function(saved) {
                if (saved.error) {
                    var stale = chip(saved.name, saved.error, function() {}, 'is-stale');
                    stale.disabled = true;
                    stale.setAttribute('aria-description', saved.error);
                    return;
                }
                chip(saved.name, 'Saved selection', function() {
                    exportApplyPreset(null);
                    exportState.checked = new Set(saved.scenes);
                    if (saved.order === 'custom') {
                        exportState.order = (saved.items || []).slice();
                        exportState.reorder = true;
                    }
                    exportSelectionChanged(true);
                }, 'is-saved');
            });
        }

        function exportFirstPages(words) {
            // Whole scenes from the start until the words would fill the pages.
            var picked = new Set();
            var total = 0;
            exportState.outline.chapters.some(function(chapter) {
                return chapter.scenes.some(function(scene) {
                    if (total >= words) return true;
                    picked.add(scene.key);
                    total += scene.words;
                    return false;
                });
            });
            return picked;
        }

        var EXPORT_PICK_FIELDS = [
            ['status', 'Status'], ['pov', 'Point of view'], ['characters', 'Character'], ['changed', 'Changed since'],
        ];

        function exportRenderPickBy() {
            var facets = exportState.outline.facets || {};
            var field = exportEl('exportPickField');
            var current = field.value;
            field.innerHTML = '';
            EXPORT_PICK_FIELDS.forEach(function(spec) {
                if (spec[0] === 'changed' || (facets[spec[0]] || []).length) field.add(new Option(spec[1], spec[0]));
            });
            if (current && Array.prototype.some.call(field.options, function(o) { return o.value === current; })) field.value = current;
            exportRenderPickValues();
        }

        function exportRenderPickValues() {
            var field = exportEl('exportPickField').value;
            var values = exportEl('exportPickValue');
            var date = exportEl('exportPickDate');
            values.innerHTML = '';
            values.hidden = field === 'changed';
            date.hidden = field !== 'changed';
            if (field === 'changed') {
                if (!date.value) {
                    var weekAgo = new Date(Date.now() - 7 * 864e5);
                    date.value = weekAgo.toISOString().slice(0, 10);
                }
                return;
            }
            ((exportState.outline.facets || {})[field] || []).forEach(function(entry) {
                values.add(new Option(entry.value + ' (' + exportPlural(entry.count, 'scene') + ')', entry.value));
            });
        }

        function exportPickMatches(scene, field, value) {
            if (field === 'changed') return !!scene.changed && scene.changed >= value;
            if (field === 'characters') return (scene.characters || []).some(function(name) { return name === value; });
            return scene[field] === value;
        }

        function exportApplyPickBy() {
            var field = exportEl('exportPickField').value;
            var value = field === 'changed' ? exportEl('exportPickDate').value : exportEl('exportPickValue').value;
            if (!field || !value) return;
            var picked = new Set();
            exportState.outline.chapters.forEach(function(chapter) {
                chapter.scenes.forEach(function(scene) {
                    if (exportPickMatches(scene, field, value)) picked.add(scene.key);
                });
            });
            if (!picked.size) {
                sidebarShowToast('No scene matches that. Nothing was changed.', true);
                return;
            }
            exportApplyPreset(null);
            exportState.checked = picked;
            exportState.outline.chapters.forEach(function(chapter) {
                var state = exportChapterState(chapter);
                if (state === 'some') exportState.expanded.add(chapter.number);
            });
            exportSelectionChanged(true);

        }

        function exportSelectionChanged(rerender) {
            if (rerender) exportSetReorder(exportState.reorder);
            else {
                exportRenderTree();
                exportRenderTotals();
                exportSchedulePreview();
            }
            exportUpdateButtons();
        }

        function exportSaveSelection(event) {
            event.preventDefault();
            var name = exportEl('exportSaveName').value.trim();
            if (!name) return;
            if (exportIsWholeBook()) {
                sidebarShowToast('The whole book is always one click away. Tick part of it to save a selection.', true);
                return;
            }
            exportPost('/api/export/selections', {name: name, selection: exportSelectionPayload()}).then(function(data) {
                exportState.outline.selections = data.outline.selections;
                exportRenderQuickPicks();
                exportToggleSaveForm(false);
                sidebarShowToast('Saved “' + data.name + '”. It is now a quick pick, here and on the command line.');
            }).catch(function(error) { sidebarShowToast(error.message, true); });
        }

        function exportToggleSaveForm(show) {
            var form = exportEl('exportSaveForm');
            form.hidden = !show;
            exportEl('exportSaveToggle').hidden = !!show;
            exportEl('exportSaveToggle').setAttribute('aria-expanded', show ? 'true' : 'false');
            if (show) {
                exportEl('exportSaveName').value = '';
                exportEl('exportSaveName').focus();
            } else {
                exportEl('exportSaveToggle').focus();
            }
        }

        // ── Step 2: style ────────────────────────────────────────────────────

        var EXPORT_FORMAT_ICONS = {
            'epub': '<path d="M5 4h9a5 5 0 0 1 5 5v11H8a3 3 0 0 1-3-3z"/><path d="M8 20a3 3 0 0 1 0-6h11"/>',
            'pdf-print': '<path d="M6 3h9l4 4v14H6z"/><path d="M9 11h7M9 14h7M9 17h5"/>',
            'pdf-share': '<path d="M7 3h8l4 4v14H7z"/><path d="M3 12h8m-3-3 3 3-3 3"/>',
            'all': '<path d="M4 6h10v14H4z"/><path d="M8 3h10v14"/>',
        };

        function exportFormats() {
            var format = exportState.details.format;
            return format === 'all' ? ['epub', 'pdf-print', 'pdf-share'] : [format];
        }

        function exportStyleFits(style) {
            return exportFormats().every(function(format) { return style.formats.indexOf(format) >= 0; });
        }

        // A tiny page in each style, so a writer chooses by eye.
        var EXPORT_THUMB_TEXT = 'lice was beginning to get very tired of sitting by her sister on the bank.';

        function exportStyleThumb(name) {
            if (name === 'manuscript') {
                return '<span class="export-style-thumb export-style-manuscript" aria-hidden="true">'
                    + '<span class="thumb-head">Carroll / ALICE / 1</span><span class="thumb-kicker">Chapter 1</span>'
                    + '<span class="thumb-text">A' + EXPORT_THUMB_TEXT + '</span><span class="thumb-break">#</span></span>';
            }
            if (name === 'modern') {
                return '<span class="export-style-thumb export-style-modern" aria-hidden="true">'
                    + '<span class="thumb-numeral">1</span><span class="thumb-title">The Rabbit-Hole</span>'
                    + '<span class="thumb-text">A' + EXPORT_THUMB_TEXT + '</span><span class="thumb-break">·&nbsp;&nbsp;·&nbsp;&nbsp;·</span></span>';
            }
            if (name === 'romance') {
                return '<span class="export-style-thumb export-style-romance" aria-hidden="true">'
                    + '<span class="thumb-kicker">&#10086; 1 &#10086;</span><span class="thumb-title">The Rabbit-Hole</span>'
                    + '<span class="thumb-text"><span class="thumb-cap">A</span>' + EXPORT_THUMB_TEXT + '</span><span class="thumb-break">&#10086;</span></span>';
            }
            return '<span class="export-style-thumb export-style-' + name + '" aria-hidden="true">'
                + '<span class="thumb-kicker">Chapter One</span><span class="thumb-title">The Rabbit-Hole</span>'
                + '<span class="thumb-text"><span class="thumb-cap">A</span>' + EXPORT_THUMB_TEXT + '</span>'
                + '<span class="thumb-break">*&nbsp;&nbsp;*&nbsp;&nbsp;*</span></span>';
        }

        function exportRenderFormatAndStyle() {
            var details = exportState.details;
            var cards = exportEl('exportFormatCards');
            cards.innerHTML = '';
            exportState.outline.formats.forEach(function(format) {
                var card = document.createElement('label');
                card.className = 'export-format-card';
                var input = document.createElement('input');
                input.type = 'radio';
                input.name = 'exportFormat';
                input.value = format.name;
                input.checked = details.format === format.name;
                input.addEventListener('change', function() {
                    details.format = format.name;
                    exportState.preview = null;
                    exportEl('exportPreviewFormat').innerHTML = '';
                    exportRenderFormatAndStyle();
                    exportUpdateButtons();
                });
                card.appendChild(input);
                card.insertAdjacentHTML('beforeend', '<svg class="export-format-icon" viewBox="0 0 24 24" aria-hidden="true">'
                    + EXPORT_FORMAT_ICONS[format.name] + '</svg>');
                var copy = document.createElement('span');
                copy.className = 'export-format-copy';
                var name = document.createElement('strong');
                name.textContent = format.label;
                var blurb = document.createElement('span');
                blurb.className = 'export-hint';
                blurb.textContent = format.blurb;
                copy.appendChild(name);
                copy.appendChild(blurb);
                card.appendChild(copy);
                cards.appendChild(card);
            });

            var formats = exportFormats();
            exportEl('exportEpubOptions').hidden = formats.indexOf('epub') < 0;
            exportEl('exportPrintOptions').hidden = formats.indexOf('pdf-print') < 0;
            exportEl('exportShareOptions').hidden = formats.indexOf('pdf-share') < 0;
            var trim = exportEl('exportTrim');
            trim.innerHTML = '';
            exportState.outline.trims.forEach(function(option) {
                trim.add(new Option(option.label, option.name, false, option.name === details.trim));
            });
            var paper = exportEl('exportPaper');
            paper.innerHTML = '';
            exportState.outline.papers.forEach(function(option) {
                paper.add(new Option(option.label, option.name, false, option.name === details.paper));
            });
            exportEl('exportRecto').checked = details.recto_chapters !== false;
            exportEl('exportWatermark').value = details.watermark || '';
            exportEl('exportSceneTitles').checked = !!details.scene_titles;
            document.querySelectorAll('input[name="exportEpubVersion"]').forEach(function(radio) {
                radio.checked = radio.value === details.epub_version;
            });

            // A style that cannot make the chosen format is not offered; if the
            // chosen one cannot, Classic (which makes everything) takes over.
            var styles = exportState.outline.styles.filter(exportStyleFits);
            if (!styles.some(function(style) { return style.name === details.style; })) {
                details.style = styles.length ? styles[0].name : 'classic';
            }
            var host = exportEl('exportStyleCards');
            host.innerHTML = '';
            styles.forEach(function(style) {
                var card = document.createElement('label');
                card.className = 'export-style-card';
                var input = document.createElement('input');
                input.type = 'radio';
                input.name = 'exportStyle';
                input.value = style.name;
                input.checked = details.style === style.name;
                input.addEventListener('change', function() {
                    details.style = style.name;
                    exportRenderDetails();
                    exportSchedulePreview();
                });
                // A tiny page in the style itself, so a writer chooses by eye.
                card.innerHTML = exportStyleThumb(style.name);
                card.insertBefore(input, card.firstChild);
                var copy = document.createElement('span');
                copy.className = 'export-style-copy';
                var name = document.createElement('strong');
                name.textContent = style.label;
                var blurb = document.createElement('span');
                blurb.className = 'export-hint';
                blurb.textContent = style.blurb;
                copy.appendChild(name);
                copy.appendChild(blurb);
                card.appendChild(copy);
                host.appendChild(card);
            });
            if (formats.indexOf('pdf-share') < 0 || formats.length > 1) {
                var more = document.createElement('p');
                more.className = 'export-hint export-style-more';
                more.textContent = 'Manuscript format, for agents and editors, is under Shareable PDF.';
                host.appendChild(more);
            }
        }

        // ── Step 3: details and preview ──────────────────────────────────────

        function exportRenderDetails() {
            var details = exportState.details;
            exportEl('exportTitle').value = details.title || '';
            exportEl('exportTitle').placeholder = exportState.outline.book.default_title;
            exportEl('exportSubtitle').value = details.subtitle || '';
            exportEl('exportAuthor').value = details.author || '';
            exportEl('exportContact').value = details.contact || '';
            exportEl('exportCopyright').checked = details.copyright_page !== false;
            exportEl('exportIsbn').value = details.isbn || '';
            exportEl('exportDedication').value = details.dedication || '';
            exportEl('exportAlsoBy').value = details.also_by || '';
            exportEl('exportMatterFiles').checked = details.matter_files !== false;
            var files = exportState.outline.matter_files || [];
            exportEl('exportMatterFiles').closest('label').hidden = !files.length;
            exportEl('exportMatterFilesHint').textContent = files.length
                ? files.map(function(file) { return file.title + ' (' + file.path + ')'; }).join(', ')
                : '';
            // A manuscript goes to an agent without front or back matter.
            exportEl('exportMatter').hidden = details.style === 'manuscript';
            exportEl('exportContactGroup').hidden = details.style !== 'manuscript';
            var printOnly = exportFormats().length === 1 && exportFormats()[0] === 'pdf-print';
            exportEl('exportCoverLabel').textContent = printOnly ? 'Cover (for your records; printers take it separately)' : 'Cover';
            // A manuscript has no cover page.
            var noCover = details.style === 'manuscript';
            exportEl('exportCoverLabel').hidden = noCover;
            exportEl('exportCoverDrop').hidden = noCover;
            exportRenderCover();
        }

        function exportReadDetails() {
            var details = exportState.details;
            details.title = exportEl('exportTitle').value.trim();
            details.subtitle = exportEl('exportSubtitle').value.trim();
            details.author = exportEl('exportAuthor').value.trim();
            details.scene_titles = exportEl('exportSceneTitles').checked;
            var version = document.querySelector('input[name="exportEpubVersion"]:checked');
            details.epub_version = version ? version.value : 'epub3';
            details.trim = exportEl('exportTrim').value || details.trim;
            details.paper = exportEl('exportPaper').value || details.paper;
            details.recto_chapters = exportEl('exportRecto').checked;
            details.watermark = exportEl('exportWatermark').value.trim();
            details.contact = exportEl('exportContact').value.trim();
            details.copyright_page = exportEl('exportCopyright').checked;
            details.isbn = exportEl('exportIsbn').value.trim();
            details.dedication = exportEl('exportDedication').value.trim();
            details.also_by = exportEl('exportAlsoBy').value.trim();
            details.matter_files = exportEl('exportMatterFiles').checked;
            return details;
        }

        function exportRenderCover() {
            var path = exportState.details.cover_image;
            var img = exportEl('exportCoverImg');
            var status = exportEl('exportCoverStatus');
            var hint = exportEl('exportCoverHint');
            exportEl('exportCoverRemove').hidden = !path;
            exportEl('exportCoverChoose').textContent = path ? 'Choose another…' : 'Choose image…';
            hint.classList.remove('is-warning');
            if (!path) {
                img.hidden = true;
                img.removeAttribute('src');
                status.textContent = 'Drop an image here, or choose one.';
                hint.textContent = 'JPEG or PNG, at least 1600 × 2560 px for stores.';
                return;
            }
            status.textContent = path.split('/').pop();
            img.onload = function() {
                var w = img.naturalWidth, h = img.naturalHeight;
                var small = Math.min(w, h) < 1600;
                hint.textContent = w + ' × ' + h + ' px' + (small ? '. Stores ask for at least 1600 px on the short side.' : '');
                hint.classList.toggle('is-warning', small);
            };
            img.alt = 'Cover';
            img.src = '/repo-asset/' + path.split('/').map(encodeURIComponent).join('/') + '?v=' + Date.now();
            img.hidden = false;
        }

        function exportUploadCover(file) {
            if (!file) return;
            var status = exportEl('exportCoverStatus');
            if (!/\.(jpe?g|png|gif|webp)$/i.test(file.name)) {
                exportShowDetailsError('A cover must be a JPEG, PNG, GIF or WebP image.');
                return;
            }
            status.textContent = 'Adding ' + file.name + '…';
            var reader = new FileReader();
            reader.onload = function() {
                var data = String(reader.result || '').split(',')[1] || '';
                exportPost('/api/export/cover', {name: file.name, data: data}).then(function(result) {
                    exportState.details.cover_image = result.path;
                    exportShowDetailsError('');
                    exportRenderCover();
                    exportSchedulePreview();
                }).catch(function(error) {
                    exportShowDetailsError(error.message);
                    exportRenderCover();
                });
            };
            reader.onerror = function() { exportShowDetailsError('That file could not be read.'); };
            reader.readAsDataURL(file);
        }

        function exportShowDetailsError(message) {
            var box = exportEl('exportDetailsError');
            box.textContent = message || '';
            box.hidden = !message;
        }

        function exportSchedulePreview() {
            if (exportState.step !== 3) {
                exportState.preview = null;
                return;
            }
            clearTimeout(exportState.previewTimer);
            exportState.previewTimer = setTimeout(exportLoadPreview, 450);
        }

        function exportLoadPreview() {
            if (!exportSelectionItems().length) return;
            var seq = ++exportState.previewSeq;
            var status = exportEl('exportPreviewStatus');
            status.textContent = 'Updating preview…';
            var keepHref = exportState.preview && exportState.preview.pages[exportState.pageIndex]
                ? exportState.preview.pages[exportState.pageIndex].href : '';
            var formats = exportFormats();
            var chooser = exportEl('exportPreviewFormat');
            chooser.hidden = formats.length < 2;
            if (formats.length > 1 && !chooser.options.length) {
                exportState.outline.formats.forEach(function(format) {
                    if (formats.indexOf(format.name) >= 0) chooser.add(new Option(format.label, format.name));
                });
            }
            var wanted = formats.length > 1 ? (chooser.value || formats[0]) : formats[0];
            if (exportState.preview && exportState.preview.format !== wanted) keepHref = '';
            exportPost('/api/export/preview', {
                selection: exportSelectionPayload(), details: exportReadDetails(), preview: wanted,
            }).then(function(data) {
                if (seq !== exportState.previewSeq) return;
                exportState.preview = data;
                var paper = data.format !== 'epub';
                exportEl('exportPreviewFrame').parentElement.hidden = paper;
                exportEl('exportPaperView').hidden = !paper;
                exportEl('exportPreviewFrame').title = paper ? '' : 'Preview of the e-book';
                if (paper) {
                    exportRenderPaperPicker(data);
                    var kept = keepHref ? data.pages.findIndex(function(page) { return page.href === keepHref; }) : -1;
                    exportShowSpread(kept >= 0 ? kept : exportFirstPdfPage(data));
                    return;
                }
                var keep = data.pages.findIndex(function(page) { return page.href === keepHref; });
                exportState.pageIndex = keep >= 0 ? keep : exportFirstTextPage(data.pages);
                var pick = exportEl('exportPagePick');
                pick.innerHTML = '';
                data.pages.forEach(function(page, index) {
                    var option = document.createElement('option');
                    option.value = String(index);
                    option.textContent = page.label;
                    pick.appendChild(option);
                });
                exportShowPreviewPage(exportState.pageIndex, 0);
                status.textContent = '';
            }).catch(function(error) {
                if (seq !== exportState.previewSeq) return;
                status.textContent = error.message;
            });
        }

        // ── PDF preview: page images, as spreads for a printed book ──────────

        function exportSpreadOf(data, index) {
            // A printed book opens with page 1 alone on the right; after that
            // pages face each other in pairs (2–3, 4–5, …).
            if (!data.spreads || index === 0) return data.spreads ? [index] : [index];
            var left = index % 2 === 1 ? index : index - 1;
            return left + 1 < data.pages.length ? [left, left + 1] : [left];
        }

        function exportSpreads(data) {
            var spreads = [];
            for (var i = 0; i < data.pages.length; ) {
                var spread = exportSpreadOf(data, i);
                spreads.push(spread);
                i = spread[spread.length - 1] + 1;
            }
            return spreads;
        }

        function exportFirstPdfPage(data) {
            // Open on the first page of text, past the title page and contents.
            return Math.max(0, Math.min((data.first_text_page || 1) - 1, data.pages.length - 1));
        }

        function exportRenderPaperPicker(data) {
            var pick = exportEl('exportPagePick');
            pick.innerHTML = '';
            exportSpreads(data).forEach(function(spread) {
                var label = spread.length > 1
                    ? 'Pages ' + (spread[0] + 1) + '–' + (spread[1] + 1)
                    : 'Page ' + (spread[0] + 1);
                pick.add(new Option(label, String(spread[0])));
            });
        }

        function exportShowSpread(index) {
            var data = exportState.preview;
            if (!data || !data.pages.length) return;
            index = Math.max(0, Math.min(index, data.pages.length - 1));
            var spread = exportSpreadOf(data, index);
            exportState.pageIndex = spread[0];
            var view = exportEl('exportPaperView');
            view.innerHTML = '';
            view.classList.toggle('is-spread', !!data.spreads);
            if (data.spreads && spread.length === 1 && spread[0] === 0) view.classList.add('is-first');
            else view.classList.remove('is-first');
            spread.forEach(function(n) {
                var img = document.createElement('img');
                img.className = 'export-paper-page';
                img.alt = 'Page ' + (n + 1);
                img.src = exportPreviewUrl(data.token, data.pages[n].href);
                view.appendChild(img);
            });
            view.setAttribute('aria-label', 'Preview of ' + (spread.length > 1
                ? 'pages ' + (spread[0] + 1) + ' and ' + (spread[1] + 1) : 'page ' + (spread[0] + 1)));
            exportEl('exportPagePick').value = String(spread[0]);
            var last = spread[spread.length - 1];
            exportEl('exportPrevPage').disabled = spread[0] === 0;
            exportEl('exportNextPage').disabled = last >= data.pages.length - 1;
            var where = spread.length > 1 ? 'Pages ' + (spread[0] + 1) + '–' + (last + 1) : 'Page ' + (spread[0] + 1);
            exportEl('exportPreviewStatus').textContent = where + ' of ' + data.pages.length
                + (data.note ? ' · ' + data.note : '');
        }

        function exportFirstTextPage(pages) {
            // Open on the first chapter rather than the cover: that is where the style shows.
            var index = pages.findIndex(function(page) { return /chapter-|scene\.xhtml/.test(page.href); });
            return index >= 0 ? index : 0;
        }

        function exportFrameDoc() {
            try { return exportEl('exportPreviewFrame').contentDocument; } catch (error) { return null; }
        }

        function exportShowPreviewPage(index, screen) {
            var preview = exportState.preview;
            if (!preview || !preview.pages.length) return;
            exportState.pageIndex = Math.max(0, Math.min(index, preview.pages.length - 1));
            var frame = exportEl('exportPreviewFrame');
            var page = preview.pages[exportState.pageIndex];
            exportEl('exportPagePick').value = String(exportState.pageIndex);
            frame.onload = function() {
                var doc = exportFrameDoc();
                if (doc && doc.head) {
                    // Lay the page out in screen-wide columns, the way an
                    // e-reader paginates, so a page never ends mid-line.
                    var style = doc.createElement('style');
                    style.textContent = 'html{height:100%;overflow:hidden}'
                        + 'body{box-sizing:border-box;height:100vh;margin:0;padding:28px 26px;'
                        + 'column-width:calc(100vw - 52px);column-gap:52px;column-fill:auto}'
                        + 'img{max-height:calc(100vh - 56px);object-fit:contain}';
                    doc.head.appendChild(style);
                    var metrics = exportPageMetrics();
                    if (metrics) metrics.scroller.scrollLeft = screen === -1 ? (metrics.total - 1) * metrics.width : 0;
                }
                exportUpdatePageStatus();
            };
            frame.src = exportPreviewUrl(preview.token, page.href);
        }

        function exportPageMetrics() {
            var doc = exportFrameDoc();
            var frame = exportEl('exportPreviewFrame');
            if (!doc || !doc.documentElement) return null;
            var scroller = doc.scrollingElement || doc.documentElement;
            var width = frame.clientWidth || 1;
            return {
                scroller: scroller,
                width: width,
                current: Math.round(scroller.scrollLeft / width) + 1,
                total: Math.max(1, Math.round(scroller.scrollWidth / width)),
            };
        }

        function exportUpdatePageStatus() {
            var metrics = exportPageMetrics();
            var preview = exportState.preview;
            if (!metrics || !preview) return;
            var page = preview.pages[exportState.pageIndex];
            exportEl('exportPreviewStatus').textContent = page.label + ' · page ' + metrics.current + ' of ' + metrics.total;
            exportEl('exportPrevPage').disabled = exportState.pageIndex === 0 && metrics.current <= 1;
            exportEl('exportNextPage').disabled = exportState.pageIndex === preview.pages.length - 1 && metrics.current >= metrics.total;
        }

        function exportTurnPage(direction) {
            var data = exportState.preview;
            if (data && data.format !== 'epub') {
                var spread = exportSpreadOf(data, exportState.pageIndex);
                exportShowSpread(direction > 0 ? spread[spread.length - 1] + 1 : spread[0] - 1);
                return;
            }
            var metrics = exportPageMetrics();
            if (!metrics) return;
            if (direction > 0 && metrics.current < metrics.total) {
                metrics.scroller.scrollLeft = metrics.current * metrics.width;
            } else if (direction < 0 && metrics.current > 1) {
                metrics.scroller.scrollLeft = (metrics.current - 2) * metrics.width;
            } else {
                exportShowPreviewPage(exportState.pageIndex + direction, direction < 0 ? -1 : 0);
                return;
            }
            exportUpdatePageStatus();
        }

        // ── Steps and buttons ────────────────────────────────────────────────

        function exportShowStep(step) {
            exportState.step = step;
            document.querySelectorAll('#exportDialog [data-export-panel]').forEach(function(panel) {
                panel.hidden = panel.dataset.exportPanel !== String(step);
            });
            var numeric = typeof step === 'number';
            document.querySelectorAll('#exportDialog [data-export-step]').forEach(function(button) {
                var n = Number(button.dataset.exportStep);
                if (numeric && n === step) button.setAttribute('aria-current', 'step');
                else button.removeAttribute('aria-current');
                button.classList.toggle('is-done', numeric && n < step);
                button.disabled = !numeric;
            });
            exportEl('exportStepHint').textContent = EXPORT_STEP_HINTS[step] || '';
            exportEl('exportDialog').classList.toggle('is-finished', !numeric);
            if (step === 3) {
                exportRenderDetails();
                exportLoadPreview();
            }
            exportUpdateButtons();
        }

        function exportUpdateButtons() {
            var back = exportEl('exportBack');
            var next = exportEl('exportNext');
            var step = exportState.step;
            var nothing = !exportState.outline || !exportState.checked.size;
            back.hidden = step === 1 || step === 'run';
            next.hidden = step === 'run';
            next.disabled = !exportState.outline || (step !== 'done' && nothing);
            var format = exportState.details ? exportState.details.format : 'epub';
            if (step === 1) next.textContent = 'Next: Format and style';
            else if (step === 2) next.textContent = 'Next: Book details';
            else if (step === 3) next.textContent = format === 'all' ? 'Export all three' : (format === 'epub' ? 'Export EPUB' : 'Export PDF');
            else if (step === 'done') next.textContent = 'Done';
            if (step === 'done') back.textContent = 'Export again';
            else back.textContent = 'Back';
        }

        function exportNext() {
            var step = exportState.step;
            if (step === 1) exportShowStep(2);
            else if (step === 2) exportShowStep(3);
            else if (step === 3) exportStart();
            else if (step === 'done') exportEl('exportDialog').close();
        }

        function exportBack() {
            var step = exportState.step;
            if (step === 'done') exportShowStep(3);
            else if (typeof step === 'number' && step > 1) exportShowStep(step - 1);
        }

        // ── Running and finishing ───────────────────────────────────────────

        function exportSetProgress(fraction, step) {
            var bar = exportEl('exportProgress');
            var percent = Math.round(Math.max(0, Math.min(1, fraction)) * 100);
            bar.setAttribute('aria-valuenow', String(percent));
            bar.firstElementChild.style.width = percent + '%';
            if (step) exportEl('exportRunStep').textContent = step;
        }

        function exportStart() {
            var details = exportReadDetails();
            exportEl('exportRunTitle').textContent = details.format === 'all' ? 'Making your books'
                : (details.format === 'epub' ? 'Making your e-book' : 'Laying out your PDF');
            exportSetProgress(0, 'Starting');
            exportShowStep('run');
            exportPost('/api/export/start', {selection: exportSelectionPayload(), details: details}).then(function(job) {
                exportState.job = job.id;
                exportPoll(job.id);
            }).catch(function(error) {
                exportShowFailure({message: error.message, code: error.code});
            });
        }

        function exportPoll(id, misses) {
            if (exportState.job !== id) return;
            exportFetchJson('/api/export/jobs/' + id).then(function(job) {
                misses = 0;
                exportSetProgress(job.fraction, job.step);
                if (job.state === 'running') {
                    setTimeout(function() { exportPoll(id); }, 250);
                } else if (job.state === 'done') {
                    exportState.outline.details = Object.assign({}, exportState.details);
                    exportShowDone(job.result);
                } else {
                    exportShowFailure(job.error || {});
                }
            }).catch(function(error) {
                // A dropped request or two is not a stopped server; keep asking
                // for a few seconds before saying so.
                misses = (misses || 0) + 1;
                if (error.code === 'offline' && misses < 12) {
                    setTimeout(function() { exportPoll(id, misses); }, 500);
                    return;
                }
                exportShowFailure({message: error.message, code: error.code});
            });
        }

        function exportFormatSize(bytes) {
            if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
            return Math.max(1, Math.round(bytes / 1024)) + ' KB';
        }

        function exportButton(label, className, onClick) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'export-btn ' + (className || '');
            button.textContent = label;
            button.addEventListener('click', onClick);
            return button;
        }

        function exportOpenScene(scenePath) {
            exportEl('exportDialog').close();
            window.location.hash = '#/scene/' + encodeURIComponent(scenePath);
        }

        function exportFixButton(finding) {
            if (finding.fix === 'scene' && finding.scene) {
                return exportButton('Open “' + (finding.scene_title || finding.scene) + '”', 'export-btn-quiet', function() {
                    exportOpenScene(finding.scene + '.md');
                });
            }
            var fields = {
                title: ['exportTitle', 'Add the title'], author: ['exportAuthor', 'Add the author'],
                cover: ['exportCoverChoose', 'Choose a cover'], contact: ['exportContact', 'Add contact details'],
            };
            var field = fields[finding.fix];
            if (!field) return null;
            return exportButton(field[1], 'export-btn-quiet', function() {
                exportShowStep(3);
                exportEl(field[0]).focus();
            });
        }

        function exportChecksCard(checks, id) {
            checks = checks || {findings: []};
            var card = document.createElement('section');
            card.className = 'export-checks ' + (checks.ready ? 'is-ready' : 'has-findings');
            card.setAttribute('aria-labelledby', id);
            var headline = document.createElement('h4');
            headline.id = id;
            headline.innerHTML = '<span aria-hidden="true">' + (checks.ready ? '&#10003;' : '!') + '</span> ';
            headline.appendChild(document.createTextNode(checks.headline || ''));
            card.appendChild(headline);
            if (checks.findings && checks.findings.length) {
                var list = document.createElement('ul');
                checks.findings.forEach(function(finding) {
                    var item = document.createElement('li');
                    item.className = 'export-finding is-' + finding.level;
                    var text = document.createElement('span');
                    text.textContent = finding.message;
                    item.appendChild(text);
                    var fix = exportFixButton(finding);
                    if (fix) item.appendChild(fix);
                    list.appendChild(item);
                });
                card.appendChild(list);
            }
            return card;
        }

        function exportFileBlock(file, index, several) {
            var block = document.createElement('section');
            block.className = 'export-file-block';
            block.setAttribute('aria-label', file.label);
            if (several) {
                var label = document.createElement('h4');
                label.className = 'export-file-label';
                label.textContent = file.label;
                block.appendChild(label);
            }
            var name = document.createElement('p');
            name.className = 'export-file';
            name.textContent = file.name;
            var meta = document.createElement('p');
            meta.className = 'export-hint';
            meta.textContent = exportFormatSize(file.size) + (file.pages ? ' · ' + exportPlural(file.pages, 'page') : '');
            block.appendChild(name);
            block.appendChild(meta);
            var actions = document.createElement('div');
            actions.className = 'export-file-actions';
            if (!exportIsDemo()) {
                actions.appendChild(exportButton('Open', index === 0 ? 'export-btn-primary' : '', function() {
                    exportPost('/api/export/open', {path: file.path}).catch(function(error) { sidebarShowToast(error.message, true); });
                }));
                actions.appendChild(exportButton('Show in folder', '', function() {
                    exportPost('/api/export/reveal', {path: file.path}).catch(function(error) { sidebarShowToast(error.message, true); });
                }));
            }
            var download = document.createElement('a');
            download.className = 'export-btn' + (exportIsDemo() && index === 0 ? ' export-btn-primary' : '');
            download.href = exportFileUrl(file);
            download.setAttribute('download', file.name);
            download.textContent = 'Download';
            actions.appendChild(download);
            block.appendChild(actions);
            block.appendChild(exportChecksCard(file.checks, 'exportChecksTitle' + index));
            return block;
        }

        function exportShowDone(result) {
            var box = exportEl('exportDoneBox');
            box.innerHTML = '';
            var files = result.files || [];
            var several = files.length > 1;
            var head = document.createElement('div');
            head.className = 'export-done-head';
            head.innerHTML = '<span class="export-done-icon" aria-hidden="true">&#10003;</span>';
            var copy = document.createElement('div');
            var title = document.createElement('h3');
            title.textContent = several ? 'Your books are ready'
                : (files[0] && files[0].format !== 'epub' ? 'Your PDF is ready' : 'Your e-book is ready');
            var meta = document.createElement('p');
            meta.className = 'export-hint';
            meta.textContent = exportPlural(result.chapters, 'chapter') + ', ' + exportPlural(result.scenes, 'scene') + ', '
                + exportPlural(result.words, 'word')
                + (exportIsDemo() ? ' · the whole demo book, ready to download'
                    : ' · saved in the exports folder of your novel');
            copy.appendChild(title);
            copy.appendChild(meta);
            head.appendChild(copy);
            box.appendChild(head);
            var list = document.createElement('div');
            list.className = 'export-file-list' + (several ? ' is-several' : '');
            files.forEach(function(file, index) { list.appendChild(exportFileBlock(file, index, several)); });
            box.appendChild(list);
            if (result.saved_selection) {
                var saved = document.createElement('p');
                saved.className = 'export-hint';
                saved.textContent = 'Saved as “' + result.saved_selection + '”.';
                box.appendChild(saved);
            }
            exportShowStep('done');
            box.scrollTop = 0;
            box.focus({preventScroll: true});
        }

        function exportShowFailure(error) {
            var box = exportEl('exportDoneBox');
            box.innerHTML = '';
            var card = document.createElement('section');
            card.className = 'export-checks has-error';
            card.setAttribute('role', 'alert');
            var title = document.createElement('h3');
            var format = exportState.details ? exportState.details.format : 'epub';
            title.textContent = format === 'all' ? 'The books could not be made'
                : (format === 'epub' ? 'The e-book could not be made' : 'The PDF could not be made');
            var message = document.createElement('p');
            message.textContent = error.message || 'Something went wrong. Please try again.';
            card.appendChild(title);
            card.appendChild(message);
            if (error.scene_path) {
                card.appendChild(exportButton('Open the scene', 'export-btn-primary', function() {
                    exportOpenScene(error.scene_path);
                }));
            }
            if (error.code === 'stale' || error.code === 'outdated' || error.code === 'offline') {
                card.appendChild(exportButton('Reload page', 'export-btn-primary', function() { location.reload(); }));
            }
            box.appendChild(card);
            exportShowStep('done');
            exportEl('exportNext').textContent = 'Close';
            exportEl('exportBack').textContent = 'Back';
            box.focus();
        }

        function exportRenderAll() {
            exportRenderQuickPicks();
            exportRenderPickBy();
            exportSetReorder(exportState.reorder);
            exportRenderFormatAndStyle();
            exportRenderDetails();
            exportUpdateButtons();
        }

        (function initExportDialog() {
            var dialog = exportEl('exportDialog');
            if (!dialog) return;
            dialog.querySelector('[data-export-close]').addEventListener('click', function() { dialog.close(); });
            dialog.addEventListener('close', function() {
                exportState.job = null;
                clearTimeout(exportState.previewTimer);
                exportEl('exportPreviewFrame').removeAttribute('src');
                var back = exportState.returnFocus;
                if (back && back.isConnected) back.focus({preventScroll: true});
            });
            dialog.addEventListener('cancel', function(event) {
                // Esc closes, except while the book is being written.
                if (exportState.step === 'run') event.preventDefault();
            });
            dialog.addEventListener('click', function(event) {
                if (event.target === dialog && exportState.step !== 'run') dialog.close();
            });
            dialog.querySelectorAll('[data-export-step]').forEach(function(button) {
                button.addEventListener('click', function() {
                    var step = Number(button.dataset.exportStep);
                    if (step > 1 && !exportState.checked.size) return;
                    exportShowStep(step);
                });
            });
            exportEl('exportNext').addEventListener('click', exportNext);
            exportEl('exportBack').addEventListener('click', exportBack);
            exportEl('exportReorder').addEventListener('change', function(event) { exportSetReorder(event.target.checked); });
            exportEl('exportExpandAll').addEventListener('click', function() {
                var chapters = exportState.outline ? exportState.outline.chapters : [];
                var allOpen = exportState.expanded.size === chapters.length;
                exportState.expanded = new Set(allOpen ? [] : chapters.map(function(c) { return c.number; }));
                exportRenderTree();
            });
            exportEl('exportSaveToggle').addEventListener('click', function() { exportToggleSaveForm(true); });
            exportEl('exportSaveForm').addEventListener('submit', exportSaveSelection);
            dialog.querySelector('[data-export-save-cancel]').addEventListener('click', function() { exportToggleSaveForm(false); });
            exportEl('exportSceneTitles').addEventListener('change', function() { exportReadDetails(); exportSchedulePreview(); });
            document.querySelectorAll('input[name="exportEpubVersion"]').forEach(function(radio) {
                radio.addEventListener('change', function() { exportReadDetails(); exportSchedulePreview(); });
            });
            ['exportTitle', 'exportSubtitle', 'exportAuthor'].forEach(function(id) {
                exportEl(id).addEventListener('input', function() { exportReadDetails(); exportSchedulePreview(); });
            });
            exportEl('exportCoverChoose').addEventListener('click', function() { exportEl('exportCoverInput').click(); });
            exportEl('exportCoverInput').addEventListener('change', function(event) {
                exportUploadCover(event.target.files && event.target.files[0]);
                event.target.value = '';
            });
            exportEl('exportCoverRemove').addEventListener('click', function() {
                exportState.details.cover_image = '';
                exportRenderCover();
                exportSchedulePreview();
                exportEl('exportCoverChoose').focus();
            });
            var drop = exportEl('exportCoverDrop');
            ['dragenter', 'dragover'].forEach(function(type) {
                drop.addEventListener(type, function(event) {
                    event.preventDefault();
                    drop.classList.add('is-dragover');
                });
            });
            ['dragleave', 'drop'].forEach(function(type) {
                drop.addEventListener(type, function() { drop.classList.remove('is-dragover'); });
            });
            drop.addEventListener('drop', function(event) {
                event.preventDefault();
                exportUploadCover(event.dataTransfer.files && event.dataTransfer.files[0]);
            });
            exportEl('exportPrevPage').addEventListener('click', function() { exportTurnPage(-1); });
            exportEl('exportNextPage').addEventListener('click', function() { exportTurnPage(1); });
            exportEl('exportPagePick').addEventListener('change', function(event) {
                if (exportState.preview && exportState.preview.format !== 'epub') exportShowSpread(Number(event.target.value));
                else exportShowPreviewPage(Number(event.target.value), 0);
            });
            exportEl('exportPreviewFormat').addEventListener('change', function() { exportLoadPreview(); });
            exportEl('exportPickField').addEventListener('change', exportRenderPickValues);
            exportEl('exportPickApply').addEventListener('click', exportApplyPickBy);
            ['exportTrim', 'exportPaper', 'exportRecto'].forEach(function(id) {
                exportEl(id).addEventListener('change', function() { exportReadDetails(); exportSchedulePreview(); });
            });
            ['exportCopyright', 'exportMatterFiles'].forEach(function(id) {
                exportEl(id).addEventListener('change', function() { exportReadDetails(); exportSchedulePreview(); });
            });
            ['exportWatermark', 'exportContact', 'exportIsbn', 'exportDedication', 'exportAlsoBy'].forEach(function(id) {
                exportEl(id).addEventListener('input', function() { exportReadDetails(); exportSchedulePreview(); });
            });
            exportEl('exportStep3').addEventListener('keydown', function(event) {
                if (event.target.matches('input, select, textarea')) return;
                if (event.key === 'PageDown' || event.key === 'ArrowRight') { event.preventDefault(); exportTurnPage(1); }
                if (event.key === 'PageUp' || event.key === 'ArrowLeft') { event.preventDefault(); exportTurnPage(-1); }
            });
        })();
