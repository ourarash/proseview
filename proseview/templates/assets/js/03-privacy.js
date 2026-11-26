        // ── Privacy screen ───────────────────────────────────────────────────
        // Hold Cmd (Ctrl off a Mac) and tap J twice to cover the page with a
        // dull spreadsheet; the same again uncovers it. Nothing behind is
        // touched -- an edit, its caret and scroll, an agent's reply all carry
        // on -- so uncovering finds the page exactly as it was. The server
        // remembers a covered screen, so a reload, another tab or a restart
        // opens on the spreadsheet too. With a password set (Settings, or
        // `proseview privacy-password`), uncovering asks for it and the
        // server checks it.
        var PRIVACY_TAP_MS = 500;
        var PRIVACY_MINUTE_MS = 60000;
        var PRIVACY_ACTIVITY_SYNC_MS = 5000;
        var PRIVACY_TITLE = 'Budget';
        var PRIVACY_MAC = /Mac|iPhone|iPad/.test(navigator.platform || '');
        var _privacyLastTap = -Infinity;
        var _privacyShown = false;
        var _privacyPassword = false;
        var _privacySaved = null;
        var _privacyTitleWatch = null;
        var _privacyIdleMinutes = 0;
        var _privacyIdleTimer = null;
        var _privacyLastActivity = Date.now();
        var _privacyLastActivitySync = 0;
        // With no server to remember it (a static snapshot, or the book
        // running in a browser tab), this browser keeps the covered flag.
        var _privacyLocal = !!window.PROSEVIEW_STATIC;
        var PRIVACY_LOCAL_KEY = 'proseview-privacy:' + location.pathname;
        var PRIVACY_IDLE_KEY = 'proseview-privacy-idle:' + location.pathname;
        var PRIVACY_ACTIVITY_KEY = 'proseview-privacy-activity:' + location.pathname;

        function privacyRememberLocally(covered) {
            try {
                if (covered) localStorage.setItem(PRIVACY_LOCAL_KEY, 'covered');
                else localStorage.removeItem(PRIVACY_LOCAL_KEY);
            } catch (err) { /* storage refused: the tab still covers */ }
        }

        function privacyParseIdleMinutes(value) {
            var n = Number(value);
            if (!isFinite(n) || n <= 0) return 0;
            return Math.min(1440, Math.floor(n));
        }

        function privacyReadLocalIdleMinutes() {
            try {
                return privacyParseIdleMinutes(localStorage.getItem(PRIVACY_IDLE_KEY));
            } catch (err) {
                return 0;
            }
        }

        function privacyRememberLocalIdleMinutes(minutes) {
            try {
                if (minutes > 0) localStorage.setItem(PRIVACY_IDLE_KEY, String(minutes));
                else localStorage.removeItem(PRIVACY_IDLE_KEY);
            } catch (err) { /* storage refused */ }
        }

        function privacyReadLastActivity() {
            var best = _privacyLastActivity;
            try {
                var raw = Number(localStorage.getItem(PRIVACY_ACTIVITY_KEY));
                if (isFinite(raw) && raw > best) best = raw;
            } catch (err) { /* storage refused */ }
            return best;
        }

        function privacyWriteLastActivity(now, force) {
            _privacyLastActivity = now;
            if (!force && now - _privacyLastActivitySync < PRIVACY_ACTIVITY_SYNC_MS) return;
            _privacyLastActivitySync = now;
            try {
                localStorage.setItem(PRIVACY_ACTIVITY_KEY, String(now));
            } catch (err) { /* storage refused */ }
            // Tabs on other origins (the phone) share activity only through
            // the server, which an idle cover asks first.
            if (!_privacyLocal && _privacyIdleMinutes > 0) privacyPost('/api/privacy/activity');
        }

        // Idle here: cover, unless the server has heard from another page
        // (the phone, say) more recently. Then wait out the rest from there.
        function privacyIdleCover() {
            if (_privacyLocal || window.PROSEVIEW_STATIC) {
                privacyCover(false);
                return;
            }
            privacyPost('/api/privacy/lock', {idle: true, idle_ms: _privacyIdleMinutes * PRIVACY_MINUTE_MS}).then(function(state) {
                if (_privacyShown) return;
                if (state && state.busy) {
                    _privacyLastActivity = Date.now() - Math.round((state.idle_seconds || 0) * 1000);
                    privacyCheckIdle();
                    return;
                }
                if (state && state.locked) {
                    privacyCover(true);
                    return;
                }
                privacyCover(false);
            });
        }

        function privacyClearIdleTimer() {
            if (_privacyIdleTimer) {
                clearTimeout(_privacyIdleTimer);
                _privacyIdleTimer = null;
            }
        }

        function privacyCheckIdle() {
            privacyClearIdleTimer();
            if (_privacyShown || !(_privacyIdleMinutes > 0)) return false;
            var timeoutMs = _privacyIdleMinutes * PRIVACY_MINUTE_MS;
            var last = privacyReadLastActivity();
            var elapsed = Date.now() - last;
            if (elapsed >= timeoutMs) {
                privacyIdleCover();
                return true;
            }
            var remaining = Math.max(100, timeoutMs - elapsed);
            _privacyIdleTimer = setTimeout(privacyCheckIdle, remaining);
            return false;
        }

        function privacyRecordActivity() {
            if (_privacyShown) return;
            var now = Date.now();
            if (_privacyIdleMinutes > 0) {
                var timeoutMs = _privacyIdleMinutes * PRIVACY_MINUTE_MS;
                if (now - _privacyLastActivity >= timeoutMs && now - privacyReadLastActivity() >= timeoutMs) {
                    privacyIdleCover();
                    return;
                }
            }
            privacyWriteLastActivity(now, false);
            if (_privacyIdleMinutes > 0 && !_privacyIdleTimer) {
                privacyCheckIdle();
            }
        }

        function privacySyncIdleSelect(minutes) {
            var select = document.getElementById('privacyIdleSelect');
            if (!select) return;
            var val = String(minutes);
            if (!select.querySelector('option[value="' + val + '"]')) {
                var opt = document.createElement('option');
                opt.value = val;
                opt.textContent = minutes === 1 ? '1 minute' : minutes + ' minutes';
                select.appendChild(opt);
            }
            select.value = val;
        }

        function privacyApplyIdleMinutes(minutes, resetActivity) {
            _privacyIdleMinutes = privacyParseIdleMinutes(minutes);
            privacySyncIdleSelect(_privacyIdleMinutes);
            if (resetActivity && !_privacyShown) {
                privacyWriteLastActivity(Date.now(), true);
            }
            if (_privacyIdleMinutes > 0) privacyCheckIdle();
            else privacyClearIdleTimer();
        }

        function privacySetIdleMinutes(value) {
            var minutes = privacyParseIdleMinutes(value);
            if (_privacyLocal) {
                privacyRememberLocalIdleMinutes(minutes);
                privacyApplyIdleMinutes(minutes, true);
                return;
            }
            privacyPost('/api/privacy/idle', {idle_minutes: minutes}).then(function(state) {
                if (state && state.ok) {
                    if (!_privacyShown) privacyWriteLastActivity(Date.now(), true);
                    privacySettingsShow(state);
                } else {
                    privacySyncIdleSelect(_privacyIdleMinutes);
                }
            });
        }

        function privacyIsShortcut(e) {
            if (e.code !== 'KeyJ' || e.shiftKey || e.altKey) return false;
            return PRIVACY_MAC ? (e.metaKey && !e.ctrlKey) : (e.ctrlKey && !e.metaKey);
        }

        function privacyIconLink() {
            return document.querySelector('link[rel="icon"]');
        }

        // The title the page would have now, for code that builds on it.
        function privacyRealTitle() {
            return _privacyShown && _privacySaved ? _privacySaved.title : document.title;
        }

        function privacyPost(path, body) {
            // A static snapshot has no server; there the screen is the
            // browser's alone, and never has a password.
            if (window.PROSEVIEW_STATIC) return Promise.resolve(null);
            return fetch(path, {method: 'POST', headers: pvHeaders(), body: JSON.stringify(body || {})})
                .then(function(response) { return response.json(); })
                .catch(function() { return null; });
        }

        function privacyCover(fromServer) {
            var screen = document.getElementById('privacyScreen');
            if (_privacyShown || !screen) return;
            var icon = privacyIconLink();
            var active = document.activeElement;
            var selection = window.getSelection();
            _privacySaved = window.PROSEVIEW_PRIVACY_SAVED || {
                title: document.title,
                icon: icon ? icon.getAttribute('href') : '',
            };
            window.PROSEVIEW_PRIVACY_SAVED = null;
            _privacySaved.focus = active && active !== document.body ? active : null;
            _privacySaved.ranges = [];
            for (var i = 0; selection && i < selection.rangeCount; i++) {
                _privacySaved.ranges.push(selection.getRangeAt(i).cloneRange());
            }
            if (active && typeof active.selectionStart === 'number') {
                _privacySaved.field = [active.selectionStart, active.selectionEnd, active.selectionDirection];
            }
            _privacySaved.scroll = [window.scrollX, window.scrollY];
            // Modal: it sits above any dialog already open and makes the
            // whole page behind it inert, out of reach of Tab and clicks.
            if (!screen.open) screen.showModal();
            _privacyShown = true;
            privacyClearIdleTimer();
            document.title = PRIVACY_TITLE;
            if (icon) icon.setAttribute('href', window.PROSEVIEW_PRIVACY_ICON);
            // The page may retitle itself meanwhile (an agent at work, say);
            // keep that for later and the tab still says Budget.
            var title = document.querySelector('title');
            if (title && window.MutationObserver) {
                _privacyTitleWatch = new MutationObserver(function() {
                    if (!_privacyShown || document.title === PRIVACY_TITLE) return;
                    _privacySaved.title = document.title;
                    document.title = PRIVACY_TITLE;
                });
                _privacyTitleWatch.observe(title, {childList: true, characterData: true, subtree: true});
            }
            if (fromServer) return;
            if (_privacyLocal) {
                privacyRememberLocally(true);
                return;
            }
            privacyPost('/api/privacy/lock').then(function(state) {
                if (!state || !state.ok) return;
                privacySettingsShow(state);
                // Covered before the page learned there is no server to keep it.
                if (_privacyLocal && _privacyShown) privacyRememberLocally(true);
            });
        }

        function privacyUncover() {
            var screen = document.getElementById('privacyScreen');
            if (!_privacyShown || !screen) return;
            privacyCloseBox();
            if (_privacyTitleWatch) _privacyTitleWatch.disconnect();
            _privacyTitleWatch = null;
            _privacyShown = false;
            screen.close();
            delete document.documentElement.dataset.privacy;
            var saved = _privacySaved || {};
            _privacySaved = null;
            if (saved.title) document.title = saved.title;
            var icon = privacyIconLink();
            if (icon && saved.icon) icon.setAttribute('href', saved.icon);
            if (saved.scroll) window.scrollTo(saved.scroll[0], saved.scroll[1]);
            var focus = saved.focus;
            if (focus && focus.isConnected && typeof focus.focus === 'function') {
                focus.focus({preventScroll: true});
                if (saved.field && typeof focus.setSelectionRange === 'function') {
                    try { focus.setSelectionRange(saved.field[0], saved.field[1], saved.field[2]); } catch (err) { /* not a text field now */ }
                }
            }
            if (!saved.field && saved.ranges && saved.ranges.length) {
                var selection = window.getSelection();
                selection.removeAllRanges();
                saved.ranges.forEach(function(range) { selection.addRange(range); });
            }
            privacyWriteLastActivity(Date.now(), true);
            if (_privacyIdleMinutes > 0) privacyCheckIdle();
        }

        function privacyOpenBox() {
            var box = document.getElementById('privacyPassword');
            if (!box) return;
            box.value = '';
            box.hidden = false;
            box.focus();
        }

        function privacyCloseBox() {
            var box = document.getElementById('privacyPassword');
            if (!box || box.hidden) return;
            box.value = '';
            box.hidden = true;
            var screen = document.getElementById('privacyScreen');
            if (screen && _privacyShown) screen.focus();
        }

        function privacySubmit() {
            var box = document.getElementById('privacyPassword');
            var password = box ? box.value : '';
            if (box) box.value = '';
            privacyPost('/api/privacy/unlock', {password: password}).then(function(state) {
                if (state && state.ok) privacyUncover();
                else privacyCloseBox();
            });
        }

        function privacyToggle() {
            if (!_privacyShown) {
                privacyCover(false);
            } else if (!_privacyPassword) {
                privacyUncover();
                if (_privacyLocal) privacyRememberLocally(false);
                else privacyPost('/api/privacy/unlock', {password: ''});
            } else if (document.getElementById('privacyPassword').hidden) {
                privacyOpenBox();
            } else {
                privacyCloseBox();
            }
        }

        // Another tab covered/uncovered the screen, or changed the idle timeout.
        function privacyFollowServer(payload) {
            if (!payload || typeof payload !== 'object') return;
            if (typeof payload.idle_minutes === 'number') {
                privacyApplyIdleMinutes(payload.idle_minutes, true);
            }
            if (typeof payload.locked === 'boolean') {
                if (payload.locked) {
                    _privacyPassword = !!payload.password;
                    privacyCover(true);
                } else {
                    privacyUncover();
                }
            }
        }

        // ── The password in Settings ──
        // One row: whether there is a password, and Set, or Change and
        // Remove. Changing or removing it takes the current one, which the
        // server checks; the CLI's --clear is the way out of a forgotten one.
        var _privacyFormMode = null;

        function privacySettingsShow(state) {
            _privacyPassword = !!state.password;
            if (state.available === false) _privacyLocal = true;
            if (_privacyLocal) {
                privacyApplyIdleMinutes(privacyReadLocalIdleMinutes(), false);
            } else if (typeof state.idle_minutes === 'number') {
                privacyApplyIdleMinutes(state.idle_minutes, false);
            }
            var row = document.getElementById('privacySettingsRow');
            if (!row) return;
            row.hidden = !state.available;
            document.getElementById('privacyPasswordStatus').textContent = _privacyPassword ? 'Password set' : 'Password: none';
            document.getElementById('privacySetBtn').hidden = _privacyPassword;
            document.getElementById('privacyChangeBtn').hidden = !_privacyPassword;
            document.getElementById('privacyRemoveBtn').hidden = !_privacyPassword;
        }

        function privacySettingsForm(mode) {
            var form = document.getElementById('privacyPasswordForm');
            if (!form) return;
            _privacyFormMode = mode;
            form.hidden = !mode;
            form.reset();
            document.getElementById('privacyPasswordMsg').textContent = '';
            if (!mode) return;
            document.getElementById('privacyCurrent').hidden = mode === 'set';
            document.getElementById('privacyNew').hidden = mode === 'remove';
            document.getElementById('privacyNewAgain').hidden = mode === 'remove';
            document.getElementById('privacyFormSubmit').textContent =
                mode === 'set' ? 'Set' : mode === 'change' ? 'Change' : 'Remove';
            var first = form.querySelector('input:not([hidden])');
            if (first) first.focus();
        }

        function privacySettingsSubmit() {
            var mode = _privacyFormMode;
            var message = document.getElementById('privacyPasswordMsg');
            var current = document.getElementById('privacyCurrent');
            var fresh = document.getElementById('privacyNew');
            var again = document.getElementById('privacyNewAgain');
            if (!mode) return;
            if (mode !== 'remove' && !fresh.value) {
                message.textContent = 'Type a new password';
                fresh.focus();
                return;
            }
            if (mode !== 'remove' && fresh.value !== again.value) {
                message.textContent = 'The two do not match';
                again.value = '';
                again.focus();
                return;
            }
            privacyPost('/api/privacy/password', {
                current: mode === 'set' ? '' : current.value,
                password: mode === 'remove' ? '' : fresh.value,
            }).then(function(state) {
                if (state && state.ok) {
                    privacySettingsShow(state);
                    privacySettingsForm(null);
                } else if (state && state.error === 'wrong password') {
                    message.textContent = 'Wrong password';
                    current.value = '';
                    current.focus();
                } else {
                    message.textContent = 'Could not save';
                }
            });
        }

        // On window, in the capture phase: ahead of every other key handler,
        // the editor's included, and of the browser's own use of the keys.
        window.addEventListener('keydown', function(e) {
            if (privacyIsShortcut(e)) {
                // Every press, the first of a pair too: on its own Cmd+J
                // would jump to the selection or open Downloads.
                e.preventDefault();
                e.stopImmediatePropagation();
                if (e.repeat) return;
                if (e.timeStamp - _privacyLastTap <= PRIVACY_TAP_MS) {
                    _privacyLastTap = -Infinity;
                    privacyToggle();
                } else {
                    _privacyLastTap = e.timeStamp;
                }
                return;
            }
            if (!_privacyShown) {
                privacyRecordActivity();
                return;
            }
            // Covered: the page behind hears no keys, and Esc, Tab, Space or
            // the arrows do nothing. Only the password box takes typing.
            e.stopImmediatePropagation();
            var box = document.getElementById('privacyPassword');
            if (box && !box.hidden && e.target === box) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    privacySubmit();
                } else if (e.key === 'Escape') {
                    e.preventDefault();
                    privacyCloseBox();
                } else if (e.key === 'Tab') {
                    e.preventDefault();
                }
                return;
            }
            if (!e.metaKey && !e.ctrlKey) e.preventDefault();
        }, true);

        (function initPrivacyScreen() {
            var screen = document.getElementById('privacyScreen');
            if (!screen) return;
            screen.addEventListener('cancel', function(e) { e.preventDefault(); });
            ['pointerdown', 'pointermove', 'wheel', 'scroll', 'touchstart', 'input'].forEach(function(type) {
                window.addEventListener(type, privacyRecordActivity, {capture: true, passive: true});
            });
            document.addEventListener('visibilitychange', function() {
                if (document.visibilityState === 'visible') privacyCheckIdle();
            });
            window.addEventListener('focus', function() {
                privacyCheckIdle();
            });
            window.addEventListener('storage', function(e) {
                if (e.key === PRIVACY_ACTIVITY_KEY && e.newValue) {
                    var ts = Number(e.newValue);
                    if (isFinite(ts) && ts > _privacyLastActivity) _privacyLastActivity = ts;
                } else if (_privacyLocal && e.key === PRIVACY_IDLE_KEY) {
                    privacyApplyIdleMinutes(privacyParseIdleMinutes(e.newValue), true);
                }
            });
            if (document.documentElement.dataset.privacy === 'locked') {
                _privacyPassword = document.documentElement.dataset.privacyPassword === '1';
                privacyCover(true);
            } else {
                privacyWriteLastActivity(Date.now(), true);
            }
            if (window.PROSEVIEW_STATIC) {
                privacyApplyIdleMinutes(privacyReadLocalIdleMinutes(), false);
                return;
            }
            fetch('/api/privacy').then(function(response) { return response.json(); }).then(function(state) {
                if (state && state.ok) {
                    privacySettingsShow(state);
                    if (state.locked && !_privacyShown) privacyCover(true);
                }
            }).catch(function() {});
        })();
