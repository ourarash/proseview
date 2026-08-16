        // ── Confirm-on-discard dialog for Esc-out-of-edit ─────────────────
        // Returns true if the keydown should be considered handled (i.e. we
        // either cancelled cleanly or popped a confirmation; the caller
        // should stop further Esc handlers from also firing).
        function tryEscapeEditMode() {
            if (!_pmEditMode) return false;
            if (!_pmDirty) {
                cancelSceneEdit();
                return true;
            }
            showUnsavedDialog();
            return true;
        }

        var _unsavedDialog = null;
        function showUnsavedDialog(options) {
            if (_unsavedDialog) return;
            options = options || {};
            var returnFocus = document.activeElement;
            var overlay = document.createElement('div');
            overlay.className = 'unsaved-dialog-overlay';
            overlay.innerHTML =
                '<div class="unsaved-dialog" role="dialog" aria-modal="true" aria-labelledby="unsavedDialogTitle">' +
                    '<div class="unsaved-dialog-title" id="unsavedDialogTitle">Unsaved changes</div>' +
                    '<div class="unsaved-dialog-body">You have unsaved edits in this scene. Save them before exiting edit mode?</div>' +
                    '<div class="unsaved-dialog-actions">' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-cancel" data-action="cancel">Cancel</button>' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-discard" data-action="discard">Discard</button>' +
                        '<button type="button" class="unsaved-dialog-btn unsaved-dialog-save" data-action="save">Save</button>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(overlay);
            _unsavedDialog = overlay;
            var inerted = Array.from(document.body.children).filter(function(el) {
                return el !== overlay && !el.inert;
            });
            inerted.forEach(function(el) { el.inert = true; });
            function close() {
                if (!_unsavedDialog) return;
                document.removeEventListener('keydown', onKey, true);
                _unsavedDialog.remove();
                _unsavedDialog = null;
                inerted.forEach(function(el) { el.inert = false; });
                if (returnFocus && returnFocus.isConnected && typeof returnFocus.focus === 'function') {
                    returnFocus.focus({preventScroll: true});
                }
            }
            function onKey(e) {
                if (e.key === 'Escape') {
                    e.preventDefault(); e.stopPropagation();
                    close();
                } else if (e.key === 'Tab') {
                    var controls = Array.from(overlay.querySelectorAll('button:not([disabled])'));
                    if (!controls.length) return;
                    var first = controls[0], last = controls[controls.length - 1];
                    if (e.shiftKey && document.activeElement === first) {
                        last.focus(); e.preventDefault(); e.stopPropagation();
                    } else if (!e.shiftKey && document.activeElement === last) {
                        first.focus(); e.preventDefault(); e.stopPropagation();
                    }
                }
            }
            overlay.addEventListener('click', function(e) {
                var btn = e.target.closest('button[data-action]');
                if (!btn && e.target === overlay) { close(); return; }
                if (!btn) return;
                var action = btn.dataset.action;
                close();
                if (action === 'save') {
                    saveSceneEdit(options.onContinue);
                } else if (action === 'discard') {
                    if (cancelSceneEdit() !== false && typeof options.onContinue === 'function') {
                        options.onContinue();
                    }
                }
            });
            document.addEventListener('keydown', onKey, true);
            var saveBtn = overlay.querySelector('.unsaved-dialog-save');
            if (saveBtn) saveBtn.focus();
        }

        function parseAnnotationRaw(raw) {
            var m = raw.match(/^<!--\s*TODO:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: 'TODO', text: m[1] };
            m = raw.match(/^<!--\s*NOTE\[(\w+)\]:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: m[1], text: m[2] };
            m = raw.match(/^<!--\s*NOTE:\s*([\s\S]*?)\s*-->$/);
            if (m) return { tag: 'NOTE', text: m[1] };
            return { tag: 'TODO', text: raw.replace(/^<!--\s*/, '').replace(/\s*-->$/, '') };
        }

        function buildAnnotationRaw(tag, text) {
            if (tag === 'TODO') return '<!-- TODO: ' + text + ' -->';
            if (tag === 'NOTE') return '<!-- NOTE: ' + text + ' -->';
            return '<!-- NOTE[' + tag + ']: ' + text + ' -->';
        }

        function initAffordance(view) {
            var btn = document.getElementById('pmInsertAffordance');
            if (!btn) return;

            btn.onmouseenter = function() { clearTimeout(_pmAffordanceTimer); };
            btn.onmouseleave = function() { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); };
            btn.onclick = function() {
                if (_pmAffordancePos < 0 || !_pmView) return;
                var PM = window._PM;
                var annotNode = PM.mySchema.nodes.annotation.create({ raw: '<!-- TODO:  -->' });
                var insertPos = _pmAffordancePos;
                var tr = _pmView.state.tr.insert(insertPos, annotNode);
                _pmView.dispatch(tr);
                hideInsertAffordance();
                setTimeout(function() { openAnnotationPopover(insertPos, annotNode); }, 0);
            };

            view.dom.addEventListener('mousemove', function(e) {
                if (!_pmEditMode) { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); return; }
                var p = e.target.closest && e.target.closest('p');
                if (!p || !view.dom.contains(p)) { _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180); return; }
                clearTimeout(_pmAffordanceTimer);
                if (p !== _pmAffordancePara) {
                    _pmAffordancePara = p;
                    try { _pmAffordancePos = view.posAtDOM(p, 0) - 1; }
                    catch(err) { _pmAffordancePos = -1; }
                }
                if (_pmAffordancePos >= 0) {
                    var rect = p.getBoundingClientRect();
                    btn.style.top = (rect.top + 2) + 'px';
                    btn.style.left = (rect.left - 30) + 'px';
                    btn.hidden = false;
                }
            });

            view.dom.addEventListener('mouseleave', function() {
                _pmAffordanceTimer = setTimeout(hideInsertAffordance, 180);
            });
        }

        function hideInsertAffordance() {
            clearTimeout(_pmAffordanceTimer);
            var btn = document.getElementById('pmInsertAffordance');
            if (btn) btn.hidden = true;
            _pmAffordancePara = null;
            _pmAffordancePos = -1;
        }

        function openAnnotationPopover(nodePos, node, options) {
            if (!_pmView) return;
            var dom = _pmView.nodeDOM(nodePos);
            if (dom && dom._annotationStartEdit) {
                dom._annotationStartEdit(!!(options && options.autoSave));
            }
        }

        function closeAnnotationPopover() {
            _pmAnnotationPos = -1;
            _pmAnnotationAutoSave = false;
        }

        function saveAnnotationPopover() {
            return;
        }

        function deleteAnnotationNode() {
            return;
        }

        window.onclick = e => {
        };
        function applyIssueFilter() {
            const f = document.getElementById('issueFilter').value;
            document.querySelectorAll('.ch-row').forEach(r => r.style.display = f === 'all' ? '' : 'none');
            document.querySelectorAll('.scene-row').forEach(r => {
                const d = parseFloat(r.dataset.dlg), s = parseFloat(r.dataset.sent), rp = parseFloat(r.dataset.rep);
                const todos = parseInt(r.dataset.todos || '0', 10);
                const notes = parseInt(r.dataset.notes || '0', 10);
                let show = f === 'all' || (f === 'repetition' && rp > 25) || (f === 'clipped' && s < 8.5) || (f === 'talky' && d > 45) || (f === 'dense' && d < 8) || (f === 'todos' && todos > 0) || (f === 'notes' && notes > 0) || (f.startsWith('status-') && r.dataset.status === f.slice(7));
                r.style.display = show ? '' : 'none';
            });
        }
