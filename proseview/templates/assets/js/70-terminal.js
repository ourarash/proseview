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
        // Hash hydration runs before the preview function's source position, so
        // lifecycle state used by it must be initialized at bundle entry.
        var _repoPreviewRequestVersion = 0;

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
                    method: 'POST', headers: pvHeaders(),
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
                method: 'POST', headers: pvHeaders(),
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
                    method: 'POST', headers: pvHeaders(),
                    body: JSON.stringify({id: tid, data: btoa(binary)})
                }).catch(function() {});
            }
            session.send = sendToTerm;

            term.onData(function(data) { sendToTerm(data); });
            term.onResize(function(sz) {
                fetch('/terminal-resize', {
                    method: 'POST', headers: pvHeaders(),
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
            if (rightOpen && typeof hideDiscussForTerminal === 'function') hideDiscussForTerminal();
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
                    html.style.setProperty('--utility-dock-w', newW + 'px');
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
            [['agentMenuFile', 'agentMenuFileBtn'], ['agentMenuScene', 'agentMenuSceneBtn']].forEach(function(pair) {
                var id = pair[0], btnId = pair[1];
                var m = document.getElementById(id);
                if (m) m.style.display = 'none';
                var btn = document.getElementById(btnId);
                if (btn) btn.setAttribute('aria-expanded', 'false');
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
            var btn = document.getElementById(btnId);
            if (btn) btn.setAttribute('aria-expanded', 'true');
            setTimeout(function() {
                document.addEventListener('click', function close(e) {
                    if (!e.target.closest('#' + id) && e.target.id !== btnId) {
                        menu.style.display = 'none';
                        if (btn) btn.setAttribute('aria-expanded', 'false');
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

          // Built on demand by the Analysis tab -- see 19-analysis.js. Kept in
          // this closure so it still has makeChart and the theme helpers.
          window.buildAnalysisCharts = function(data) {
            if (chartRefs.rhythmChart) { chartRefs.rhythmChart.destroy(); }
            if (chartRefs.lexicalScatterChart) { chartRefs.lexicalScatterChart.destroy(); }
            chartRefs.rhythmChart = makeChart('rhythmChart', 250, {
              type: 'line', data: data.rhythmChart,
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
              type: 'scatter', data: { datasets: data.scatterChart.datasets },
              options: { scales: { x: { min:0.65, max:0.85, title: { display: true, text: 'Local Variety (MATTR)' } }, y: { min:50, max:180, title: { display: true, text: 'Whole-Scene Variety (MTLD)' } } },
              plugins: { legend: { display: false }, annotation: { annotations: { target: { type: 'box', xMin: data.scatterChart.bands.mattr[0], xMax: data.scatterChart.bands.mattr[1], yMin: data.scatterChart.bands.mtld[0], yMax: data.scatterChart.bands.mtld[1], borderWidth: 2 } } } } }
            });
          };

        });

        const NOTE_TAGS = ['note', 'continuity', 'character', 'theme', 'question'];

        function todoEntryHtml(t, absPath) {
            const tagChip = '<span class="note-tag-chip note-tag-todo">todo</span>';
            if (t.source === 'frontmatter') {
                return '<div class="todo-entry">' +
                    '<div class="todo-entry-display">' +
                    tagChip +
                    '<span class="todo-entry-text">' + escHtml(t.text) + '</span>' +
                    '</div></div>';
            }
            const lineLabel = t.line ? '<span class="todo-line">L' + t.line + '</span>' : '';
            const actionBtns = '<div class="note-entry-actions"><button class="todo-edit-btn" type="button">Edit</button><button class="todo-delete-btn" type="button">Delete</button></div>';
            return '<div class="todo-entry" data-abs-path="' + attrEscape(absPath) + '" data-todo-text="' + attrEscape(t.text) + '">' +
                '<div class="todo-entry-display">' +
                tagChip +
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
            const lineLabel = n.line ? '<span class="todo-line">L' + n.line + '</span>' : '';
            const actionBtns = '<div class="note-entry-actions"><button class="note-edit-btn" type="button">Edit</button><button class="note-delete-btn" type="button">Delete</button></div>';
            return '<div class="note-entry" data-abs-path="' + attrEscape(absPath) + '" data-note-text="' + attrEscape(n.text) + '" data-note-tag="' + attrEscape(n.tag) + '">' +
                '<div class="note-entry-display">' +
                '<span class="note-tag-chip note-tag-' + escHtml(n.tag) + '">' + escHtml(n.tag) + '</span>' +
                lineLabel +
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
                    '<button class="notes-scene-link" type="button" data-scene-path="' + attrEscape(path) + '">' + escHtml(name) + '</button>' +
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
                    '<button class="notes-scene-link" type="button" data-scene-path="' + attrEscape(path) + '">' + escHtml(name) + '</button>' +
                    '</div>';
                todos.forEach(function(t) {
                    html += '<div class="notes-row">' + todoEntryHtml(t, abs_path) + '</div>';
                });
                html += '</div>';
            });
            content.innerHTML = html;
        }

        document.addEventListener('click', function(e) {
            const sceneLink = e.target.closest('.notes-scene-link[data-scene-path]');
            if (sceneLink) {
                e.preventDefault();
                openSceneModal(sceneLink.dataset.scenePath);
                return;
            }

            const jb = e.target.closest('.task-jump-btn');
            if (jb) {
                e.preventDefault();
                const paraIdx = parseInt(jb.dataset.paraIdx, 10);
                _scrollToPara(paraIdx);
                return;
            }
        });

        // Try several strategies to locate the paragraph in the live DOM
        // and scroll/flash it. Falls back to retries because ProseMirror
        // may finish mounting after the click fires (the user can click
        // immediately after a refresh).
        function _scrollToPara(paraIdx, attempt) {
            attempt = attempt || 0;
            var target = _findParaTarget(paraIdx);
            if (!target && attempt < 4) {
                setTimeout(function() { _scrollToPara(paraIdx, attempt + 1); }, 80);
                return;
            }
            if (!target) {
                console.warn('[proseview] task-jump: no DOM target for paragraph', paraIdx);
                return;
            }
            // ``block: 'start'`` aligns the target to the top of the
            // scroll container (modulo CSS scroll-padding-top). This makes
            // the jump visually unambiguous even when two TODO/Note
            // markers sit a few pixels apart in adjacent paragraphs --
            // ``block: 'center'`` produced nearly identical scroll
            // positions for those, so the second click looked like a no-op.
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            target.classList.add('para-flash');
            setTimeout(function() { target.classList.remove('para-flash'); }, 1600);
        }

        // Resolve a paragraph index (counted by paragraph_blocks() in
        // scenes.py) to a DOM element under the live ProseMirror view.
        // paragraph_blocks() splits on blank lines and filters out
        // headings; we apply the same filter to the rendered DOM so the
        // index lines up.
        //
        // Subtle point: the line-number gutter plugin emits a
        // Decoration.widget(offset+1) for every top-level node. For
        // paragraphs (non-atom) the widget renders INSIDE the <p>, so
        // it doesn't appear as a sibling. For annotation atoms the
        // widget can't render inside the atom, so ProseMirror places it
        // as a top-level sibling immediately after the annotation. That
        // shifted every index past the first annotation by one and made
        // task-jump arrows for any TODO/Note after a previous annotation
        // land on a .pm-line-jump <a> instead of the annotation itself.
        function _findParaTarget(paraIdx) {
            if (!Number.isFinite(paraIdx) || paraIdx < 0) return null;
            var host = document.getElementById('sceneProseHost');
            if (!host) return null;
            var root = host.querySelector('.ProseMirror');
            if (!root) return null;
            var blocks = [];
            for (var i = 0; i < root.children.length; i++) {
                var el = root.children[i];
                if (/^H[1-6]$/i.test(el.tagName)) continue;
                if (el.classList && el.classList.contains('ProseMirror-widget')) continue;
                blocks.push(el);
            }
            return blocks[paraIdx] || null;
        }

        function closeAllPopovers() {
            document.querySelectorAll('.note-popover.is-open, .todo-popover.is-open').forEach(function(p) { p.classList.remove('is-open'); });
        }

        function postAndReload(url, body, errorMsg, disableBtn) {
            if (disableBtn) disableBtn.disabled = true;
            fetch(url, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body)})
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
            if (name === 'analysis') buildAnalysisTab();
            if (name === 'timeline') buildTimelineTab();
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
                    previewRepoFile(route.arg, { route: false });
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

        function renderRepoFile(node, options) {
            options = options || {};
            var path = node.path;
            saveActiveScrollPosition();
            highlightSidebarItem(path);
            if (options.route !== false) routeToHash('/file/' + encodeURIComponent(path), true);
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
                        body.replaceChildren();
                        renderSafeMarkdown(body, node.body);
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
            if (typeof discussFollowActiveDocument === 'function') discussFollowActiveDocument();
            if (options.focus) document.getElementById('filePreviewTitle').focus({ preventScroll: true });
            return node;
        }

        function previewRepoFile(path, options) {
            options = options || {};
            const requestVersion = ++_repoPreviewRequestVersion;
            const cached = repoFileByPath[path];
            if (cached) return Promise.resolve(renderRepoFile(cached, options));

            saveActiveScrollPosition();
            highlightSidebarItem(path);
            if (options.route !== false) routeToHash('/file/' + encodeURIComponent(path), true);
            document.getElementById('filePreviewTitle').textContent = path;
            document.getElementById('filePreviewMeta').textContent = 'Loading preview…';
            document.getElementById('filePreviewBody').innerHTML = '<div class="repo-warn">Loading preview…</div>';
            document.documentElement.dataset.view = 'file';
            if (options.focus) document.getElementById('filePreviewTitle').focus({ preventScroll: true });

            return fetch('/repo-file?path=' + encodeURIComponent(path), { cache: 'no-store' })
                .then(function(response) {
                    return response.json().then(function(data) {
                        if (!response.ok || !data || !data.ok || !data.node) {
                            throw new Error((data && data.error) || 'Could not load file preview');
                        }
                        return data.node;
                    });
                })
                .then(function(node) {
                    if (!node || node.path !== path) throw new Error('File preview returned the wrong document');
                    repoFileByPath[path] = node;
                    if (requestVersion !== _repoPreviewRequestVersion) return null;
                    return renderRepoFile(node, { route: false, focus: options.focus });
                })
                .catch(function(error) {
                    if (requestVersion !== _repoPreviewRequestVersion) return null;
                    document.getElementById('filePreviewMeta').textContent = 'Preview unavailable';
                    document.getElementById('filePreviewBody').innerHTML = '';
                    var warning = document.createElement('div');
                    warning.className = 'repo-warn';
                    warning.textContent = error.message || 'Could not load file preview';
                    document.getElementById('filePreviewBody').appendChild(warning);
                    return null;
                });
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
        function refreshFilePreview(options) {
            options = options || {};
            var titleEl = document.getElementById('filePreviewTitle');
            var path = titleEl ? titleEl.textContent.trim() : '';
            if (!path) return;
            if (options.changedPaths && !pathListContains(options.changedPaths, path)) return;
            var btn = document.getElementById('filePreviewRefreshBtn');
            var prevHTML = btn ? btn.innerHTML : '';
            if (btn && !options.silent) { btn.disabled = true; btn.innerHTML = '\u2026'; }
            fetch('/repo-file?path=' + encodeURIComponent(path), { cache: 'no-store' })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (!data || !data.ok || !data.node) {
                        throw new Error((data && data.error) || 'unknown error');
                    }
                    repoFileByPath[path] = data.node;
                    if (activeRouteKey() !== '/file/' + path) return;
                    previewRepoFile(path, { route: false });
                })
                .catch(function(err) {
                    if (!options.silent) alert('Could not refresh file: ' + err);
                })
                .finally(function() {
                    if (btn && !options.silent) { btn.disabled = false; btn.innerHTML = prevHTML || '\u21BB'; }
                });
        }
