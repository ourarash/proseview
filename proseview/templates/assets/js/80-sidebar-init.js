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
