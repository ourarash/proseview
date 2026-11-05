        // ── Sidebar ──────────────────────────────────────────────────────────

        (function initSidebarResize() {
            var handle = document.getElementById('sidebarResizeHandle');
            if (!handle) return;
            var startX, startW;
            var html = document.documentElement;

            function setSidebarWidth(w) {
                var bounds = workspaceSidebarWidthBounds();
                w = Math.max(bounds.min, Math.min(bounds.max, w));
                html.style.setProperty('--sidebar-w', w + 'px');
                updateSeparatorValue(handle, w, bounds.min, bounds.max);
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

            handle.addEventListener('keydown', function(e) {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
                var current = document.getElementById('repoSidebar').getBoundingClientRect().width;
                var next = current;
                var bounds = workspaceSidebarWidthBounds();
                if (e.key === 'Home') next = bounds.min;
                else if (e.key === 'End') next = bounds.max;
                else next += (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 50 : 20);
                setSidebarWidth(next);
                e.preventDefault();
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
                if (saved) setSidebarWidth(+saved);
                else setSidebarWidth(document.getElementById('repoSidebar').getBoundingClientRect().width);
            } catch(e) {}
            window.addEventListener('resize', function() {
                setSidebarWidth(document.getElementById('repoSidebar').getBoundingClientRect().width / workspaceZoomFactor());
            });
            window.addEventListener('proseview:workspace-metrics', function() {
                setSidebarWidth(parseFloat(getComputedStyle(html).getPropertyValue('--sidebar-w')) || 280);
            });
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
            if (typeof syncSidebarInteractiveState === 'function') syncSidebarInteractiveState();
        }

        function renderSidebarTree() {
            const container = document.getElementById('sidebarTree');
            if (!container || !sidebarTree.length) return;
            container.setAttribute('role', 'tree');
            container.setAttribute('aria-label', 'Repository files');
            container.innerHTML = '';
            // Folders that were open before a file change reloaded the page.
            var restored = null;
            try {
                restored = JSON.parse(sessionStorage.getItem('proseview-sidebar-expanded') || 'null');
                sessionStorage.removeItem('proseview-sidebar-expanded');
            } catch (e) {}
            _sidebarExpandedBefore = Array.isArray(restored) ? new Set(restored) : null;
            container.appendChild(buildSidebarList(sidebarTree, 0));
            _sidebarExpandedBefore = null;
            const first = container.querySelector('[role="treeitem"]');
            if (first) first.tabIndex = 0;
            // The tree is rendered lazily (first open) and rebuilt wholesale,
            // so re-apply whatever the active document is.
            applySidebarReveal();
            updateSidebarFooter();
        }

        function updateSidebarFooter() {
            var footer = document.getElementById('sidebarFooter');
            var label = document.getElementById('sidebarFooterLabel');
            var action = document.getElementById('sidebarFooterAction');
            var caption = document.getElementById('sidebarFooterCaption');
            if (!footer || !label) return;

            if (typeof sidebarWholeFolder !== 'undefined' && sidebarWholeFolder) {
                label.textContent = 'All repository folders';
                if (action) action.hidden = true;
                if (caption) caption.textContent = 'Whole folder listed';
                return;
            }

            var dirCount = 0;
            if (typeof sidebarTree !== 'undefined' && Array.isArray(sidebarTree)) {
                for (var i = 0; i < sidebarTree.length; i++) {
                    var n = sidebarTree[i];
                    if (n && !n.is_file && n.path !== '.proseview.yaml') {
                        dirCount++;
                    }
                }
            }
            var extraFolders = dirCount > 1 ? dirCount - 1 : 0;
            if (extraFolders > 0) {
                label.textContent = 'Showing manuscript & ' + extraFolders + (extraFolders === 1 ? ' folder' : ' folders');
            } else if (dirCount === 1) {
                label.textContent = 'Showing manuscript';
            } else {
                label.textContent = 'Files list';
            }

            var unlistedNames = [];
            if (typeof repositoryTree !== 'undefined' && Array.isArray(repositoryTree)) {
                var listedSet = new Set();
                if (typeof sidebarTree !== 'undefined' && Array.isArray(sidebarTree)) {
                    for (var j = 0; j < sidebarTree.length; j++) {
                        if (sidebarTree[j] && sidebarTree[j].name) listedSet.add(sidebarTree[j].name);
                    }
                }
                for (var k = 0; k < repositoryTree.length; k++) {
                    var rn = repositoryTree[k];
                    if (rn && !rn.is_file && rn.name && !listedSet.has(rn.name)) {
                        unlistedNames.push(rn.name);
                    }
                }
            }
            if (caption) {
                if (unlistedNames.length > 0) {
                    var pills = unlistedNames.map(function(name) {
                        return '<button type="button" class="sidebar-add-folder-pill" onclick="_addFolderToFiles(\''
                            + _searchEscHtml(name) + '\', event)" title="Add ' + _searchEscHtml(name) + ' to Files in .proseview.yaml">+ '
                            + _searchEscHtml(name) + '</button>';
                    }).join(' ');
                    caption.title = 'Other folders on disk: ' + unlistedNames.join(', ');
                    caption.innerHTML = '<span>On disk:</span> ' + pills;
                } else {
                    caption.title = '';
                    caption.innerHTML = 'Configured in <code>repo_tab.folders</code>';
                }
            }
        }

        var _sidebarExpandedBefore = null;

        function buildSidebarList(nodes, depth) {
            const ul = document.createElement('ul');
            if (depth > 0) ul.setAttribute('role', 'group');
            for (const node of nodes) ul.appendChild(buildSidebarItem(node, depth));
            return ul;
        }

        function sidebarFileType(node) {
            if (node && node.is_scene) return 'scene';
            var name = String((node && (node.name || node.path)) || '').toLowerCase();
            var dot = name.lastIndexOf('.');
            var ext = dot >= 0 ? name.slice(dot) : '';

            if (ext === '.md' || ext === '.markdown') return 'markdown';
            if (ext === '.txt' || ext === '.log') return 'text';
            if (ext === '.yaml' || ext === '.yml' || ext === '.toml') return 'yaml';
            if (ext === '.json') return 'json';
            if (ext === '.csv' || ext === '.tsv') return 'data';
            if (['.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.bmp', '.avif', '.ico'].indexOf(ext) >= 0) return 'image';
            if (ext === '.pdf') return 'pdf';
            if (['.m4a', '.mp3', '.wav', '.ogg', '.flac', '.aac'].indexOf(ext) >= 0) return 'audio';
            if (['.py', '.sh', '.bash', '.js', '.ts', '.html', '.css', '.zsh'].indexOf(ext) >= 0) return 'code';
            return 'file';
        }

        function sidebarIcon(kind, extraClass) {
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '0 0 24 24');
            svg.setAttribute('aria-hidden', 'true');
            svg.setAttribute('focusable', 'false');
            svg.classList.add(kind === 'chevron' ? 'sidebar-disclosure-icon' : 'sidebar-node-icon');
            if (extraClass) svg.classList.add(extraClass);

            const paths = {
                chevron: ['M9 18l6-6-6-6'],
                folder: ['M3.5 8h17v9.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z', 'M3.5 8V6.5a2 2 0 0 1 2-2h4l2.2 3.5'],
                file: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5'],
                scene: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M8.5 13h7M8.5 16.5h4.5'],
                markdown: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M9 14.5l1.5-2 1.5 2 1.5-2v4'],
                text: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M8.5 12h7M8.5 15h7M8.5 18h4'],
                yaml: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M8.5 13h7M10.5 11.5v3M8.5 16.5h7M14 15v3'],
                json: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M10 13a1 1 0 0 0-1 1 1 1 0 0 1-1 1 1 1 0 0 1 1 1 1 1 0 0 0 1 1M14 13a1 1 0 0 1 1 1 1 1 0 0 0 1 1 1 1 0 0 0-1 1 1 1 0 0 1-1 1'],
                image: ['M3.5 6.5A1.5 1.5 0 0 1 5 5h14a1.5 1.5 0 0 1 1.5 1.5v11A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5v-11z', 'M8.5 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z', 'M3.5 16l4.5-4 4 3.5 3-2.5 5 4.5'],
                pdf: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M9 13h2.5a1.5 1.5 0 0 1 0 3H9v2M9 15.5h2.5'],
                audio: ['M9 18V5l10-2v13', 'M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z', 'M19 16a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z'],
                data: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M8.5 13h7M8.5 16h7M12 12v6'],
                code: ['M6 3.5h7l5 5v12a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5z', 'M13 3.5v5h5', 'M9.5 15l-1.5-1.5 1.5-1.5M14.5 12l1.5 1.5-1.5 1.5M12.5 11l-1.5 6']
            };
            const pathList = paths[kind] || paths.file;
            for (const data of pathList) {
                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', data);
                svg.appendChild(path);
            }
            return svg;
        }

        function sidebarLabel(name) {
            const label = document.createElement('span');
            label.className = 'sidebar-row-label';
            label.textContent = name;
            return label;
        }

        function buildSidebarItem(node, depth) {
            const li = document.createElement('li');
            li.setAttribute('role', 'none');
            if (node.is_file) {
                const a = document.createElement('button');
                a.type = 'button';
                a.className = 'file-link';
                a.setAttribute('role', 'treeitem');
                a.setAttribute('aria-level', String(depth + 1));
                a.tabIndex = -1;
                a.dataset.path = node.path;
                const iconSpacer = document.createElement('span');
                iconSpacer.className = 'sidebar-icon-spacer';
                iconSpacer.setAttribute('aria-hidden', 'true');
                a.appendChild(iconSpacer);
                if (node.is_scene) {
                    a.dataset.scenePath = node.scene_path || '';
                    a.appendChild(sidebarIcon('scene', 'sidebar-scene-icon'));
                    a.appendChild(sidebarLabel(node.name));
                    // openSceneModal reveals the scene in the sidebar itself.
                    a.onclick = () => sidebarOpenScene(node);
                } else {
                    const kind = sidebarFileType(node);
                    a.appendChild(sidebarIcon(kind, 'sidebar-' + kind + '-icon'));
                    a.appendChild(sidebarLabel(node.name));
                    // No cache guard: previewRepoFile serves from
                    // repoFileByPath when present and fetches otherwise, which
                    // is the only way to open files outside the preview
                    // folders (manuscript notes, say).
                    a.onclick = () => previewRepoFile(node.path);
                }
                li.appendChild(a);
                if (typeof sidebarAttachRowActions === 'function') sidebarAttachRowActions(node, li, a, depth);
            } else {
                const tog = document.createElement('button');
                tog.type = 'button';
                tog.className = 'dir-toggle';
                tog.setAttribute('role', 'treeitem');
                tog.setAttribute('aria-level', String(depth + 1));
                const open = _sidebarExpandedBefore ? _sidebarExpandedBefore.has(node.path) : depth === 0;
                tog.setAttribute('aria-expanded', open ? 'true' : 'false');
                tog.dataset.path = node.path;
                tog.tabIndex = -1;
                tog.appendChild(sidebarIcon('chevron'));
                tog.appendChild(sidebarIcon('folder'));
                tog.appendChild(sidebarLabel(node.name));
                tog.onclick = () => {
                    const expanded = li.classList.toggle('expanded');
                    tog.setAttribute('aria-expanded', expanded ? 'true' : 'false');
                };
                li.appendChild(tog);
                if (typeof sidebarAttachRowActions === 'function') sidebarAttachRowActions(node, li, tog, depth);
                if (node.children && node.children.length)
                    li.appendChild(buildSidebarList(node.children, depth + 1));
                if (open) li.classList.add('expanded');
            }
            return li;
        }

        // A scene added since the page loaded is not in its scene index yet,
        // so it is read first. If it cannot be, it opens as a plain file.
        function sidebarOpenScene(node) {
            const p = node.scene_path;
            if (paths.indexOf(p) >= 0) {
                openSceneModal(p);
                return;
            }
            fetch('/scene-data?path=' + encodeURIComponent(p), { cache: 'no-store' }).then(function(r) {
                if (!r.ok) throw new Error('scene not found');
                return r.json();
            }).then(function(data) {
                if (paths.indexOf(p) < 0) {
                    if (!data.meta || !data.meta[p] || !data.contents || data.contents[p] === undefined) {
                        throw new Error('scene not found');
                    }
                    contents[p] = data.contents[p];
                    meta[p] = data.meta[p];
                    if (data.highlightsByPath && data.highlightsByPath[p]) highlightsByPath[p] = data.highlightsByPath[p];
                    paths.push(p);
                }
                openSceneModal(p);
            }).catch(function() {
                previewRepoFile(node.path);
            });
        }

        function visibleSidebarTreeItems(tree) {
            return Array.from(tree.querySelectorAll('[role="treeitem"]')).filter(function(item) {
                return item.getClientRects().length > 0;
            });
        }

        function focusSidebarTreeItem(tree, item) {
            tree.querySelectorAll('[role="treeitem"]').forEach(function(candidate) {
                candidate.tabIndex = candidate === item ? 0 : -1;
            });
            item.focus();
        }

        document.getElementById('sidebarTree').addEventListener('keydown', function(event) {
            const tree = event.currentTarget;
            const current = event.target.closest('[role="treeitem"]');
            if (!current) return;
            const items = visibleSidebarTreeItems(tree);
            const index = items.indexOf(current);
            if (event.key === 'ArrowDown' && index < items.length - 1) {
                focusSidebarTreeItem(tree, items[index + 1]);
            } else if (event.key === 'ArrowUp' && index > 0) {
                focusSidebarTreeItem(tree, items[index - 1]);
            } else if (event.key === 'Home' && items.length) {
                focusSidebarTreeItem(tree, items[0]);
            } else if (event.key === 'End' && items.length) {
                focusSidebarTreeItem(tree, items[items.length - 1]);
            } else if (event.key === 'ArrowRight' && current.classList.contains('dir-toggle')) {
                if (current.getAttribute('aria-expanded') === 'false') current.click();
                else if (index < items.length - 1) focusSidebarTreeItem(tree, items[index + 1]);
            } else if (event.key === 'ArrowLeft') {
                if (current.classList.contains('dir-toggle') && current.getAttribute('aria-expanded') === 'true') {
                    current.click();
                } else {
                    const parent = current.closest('ul[role="group"]');
                    const parentItem = parent && parent.parentElement && parent.parentElement.querySelector(':scope > .dir-toggle');
                    if (parentItem) focusSidebarTreeItem(tree, parentItem);
                }
            } else if ((event.key === 'Enter' || event.key === ' ') && current) {
                current.click();
            } else {
                return;
            }
            event.preventDefault();
        });

        // The document the sidebar should point at, as {path} or {scenePath}.
        // Kept outside the DOM so a tree that has not been rendered yet (the
        // sidebar renders lazily on first open) still reveals the right file
        // once it is built.
        // Declared without a value: the route is applied while the page's
        // script is still running, before this line, and an initializer here
        // would wipe the target it set -- a scene opened from its address was
        // never revealed.
        var _sidebarRevealTarget;

        function revealSidebarItem(target) {
            _sidebarRevealTarget = target || null;
            applySidebarReveal();
        }

        function highlightSidebarItem(fullPath) {
            revealSidebarItem({ path: fullPath });
        }

        function applySidebarReveal() {
            const tree = document.getElementById('sidebarTree');
            if (!tree) return;
            const target = _sidebarRevealTarget;
            let match = null;
            tree.querySelectorAll('.file-link').forEach(el => {
                const hit = !!target && (
                    (!!target.path && el.dataset.path === target.path) ||
                    (!!target.scenePath && el.dataset.scenePath === target.scenePath)
                );
                el.classList.toggle('active', hit);
                if (hit) el.setAttribute('aria-current', 'page');
                else el.removeAttribute('aria-current');
                if (hit) match = el;
            });
            // Files outside the sidebar's folders (search reaches the whole
            // repository) simply have nothing to reveal.
            if (!match) return;
            // Expand every ancestor folder so the file is actually on screen.
            for (var li = match.closest('li'); li && tree.contains(li);
                 li = li.parentElement && li.parentElement.closest('li')) {
                li.classList.add('expanded');
                var toggle = li.querySelector(':scope > .dir-toggle');
                if (toggle) toggle.setAttribute('aria-expanded', 'true');
            }
            match.scrollIntoView({ block: 'nearest' });
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
            updateSidebarFooter();
        });

        function sortTable(n) { sortTableEl(document.getElementById("sceneTable"), n); }

        // Each header cycles ascending, descending, then back to book order:
        // the chapters with their scenes under them, as the table was built.
        function sortTableEl(t, n) {
            if (!t || !t.tBodies[0]) return;
            var body = t.tBodies[0], rows = Array.from(body.rows);
            if (rows.some(function(row) { return row.dataset.bookOrder === undefined; })) {
                // A fresh table body: number its rows and forget the old sort.
                rows.forEach(function(row, i) { row.dataset.bookOrder = i; });
                delete t.dataset.sortCol;
            }
            var d = 'asc';
            if (t.dataset.sortCol === String(n)) d = t.dataset.sortDir === 'asc' ? 'desc' : 'none';
            var value = function(row) {
                var cell = row.getElementsByTagName('TD')[n], text = cell ? cell.innerText.replace(/,/g, '').replace(/%/g, '') : '';
                var num = parseFloat(text);
                return isNaN(num) ? text.toLowerCase() : num;
            };
            rows.sort(function(a, b) {
                if (d === 'none') return a.dataset.bookOrder - b.dataset.bookOrder;
                var x = value(a), y = value(b);
                if (typeof x !== typeof y) { x = String(x); y = String(y); }
                var c = x < y ? -1 : x > y ? 1 : a.dataset.bookOrder - b.dataset.bookOrder;
                return d === 'asc' ? c : -c;
            });
            rows.forEach(function(row) { body.appendChild(row); });
            if (d === 'none') { delete t.dataset.sortCol; delete t.dataset.sortDir; } else { t.dataset.sortCol = n; t.dataset.sortDir = d; }
            Array.from(t.tHead ? t.tHead.rows[0].cells : []).forEach(function(header, index) {
                header.setAttribute('aria-sort', index === n && d !== 'none' ? (d === 'asc' ? 'ascending' : 'descending') : 'none');
            });
        }
