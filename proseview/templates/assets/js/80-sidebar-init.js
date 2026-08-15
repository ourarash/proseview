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
            // The tree is rendered lazily (first open) and rebuilt wholesale,
            // so re-apply whatever the active document is.
            applySidebarReveal();
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
                    // openSceneModal reveals the scene in the sidebar itself.
                    a.onclick = () => openSceneModal(node.scene_path);
                } else {
                    a.innerHTML = '<span class="file-icon">\u25A1</span>' + escHtml(node.name);
                    // No cache guard: previewRepoFile serves from
                    // repoFileByPath when present and fetches otherwise, which
                    // is the only way to open files outside the preview
                    // folders (manuscript notes, say).
                    a.onclick = () => previewRepoFile(node.path);
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

        // The document the sidebar should point at, as {path} or {scenePath}.
        // Kept outside the DOM so a tree that has not been rendered yet (the
        // sidebar renders lazily on first open) still reveals the right file
        // once it is built.
        var _sidebarRevealTarget = null;

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
                if (hit) match = el;
            });
            // Files outside the sidebar's folders (search reaches the whole
            // repository) simply have nothing to reveal.
            if (!match) return;
            // Expand every ancestor folder so the file is actually on screen.
            for (var li = match.closest('li'); li && tree.contains(li);
                 li = li.parentElement && li.parentElement.closest('li')) {
                li.classList.add('expanded');
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
        });

        function sortTable(n) { sortTableEl(document.getElementById("sceneTable"), n); }

        function sortTableEl(t, n) {
            if (!t) return;
            var r = t.rows, s = true, d = "asc", c = 0;
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
