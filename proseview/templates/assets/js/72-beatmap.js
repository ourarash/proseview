// ── Visual Beat Map for Proseview ─────────────────────────────────────────
// Provides an abstract narrative progression map of a scene with:
// - Bidirectional tension sparkline curve
// - Ordered moments (dialogue, action, silent reaction, interiority)
// - Verbatim source references with synchronized prose jumps
// - Locked constant-height horizontal strip (above prose) and vertical right dock tab
(function () {
    var _beatMapCurrentScene = null;
    var _beatMapData = null;
    var _beatMapPlacement = 'vertical';
    var _beatMapSelectedBeat = 1;
    var _beatMapSelectedMoment = 1;
    var _beatMapIsZoomed = false;
    var _beatMapAgent = 'claude';
    var _beatMapIsUpdating = false;
    var _beatMapUpdatingScene = null;
    var _beatMapStale = false;
    var _beatMapCollapsedBeats = {};
    var _beatMapOpSeq = 0;
    var _beatMapGenerateStartedAt = 0;
    var _beatMapGenerateTimer = null;
    var _beatMapGeneratePollTimer = null;
    var _beatMapGenerateStatus = null;

    var ALLOWED_MOMENT_TYPES = ['dialogue', 'action', 'silent_reaction', 'interiority'];

    function escHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    var BEAT_PALETTE = [
        '#34d399', // Beat 1: Mint / Emerald
        '#fbbf24', // Beat 2: Amber / Gold
        '#38bdf8', // Beat 3: Sky Blue / Cyan
        '#f87171', // Beat 4: Coral / Salmon Red
        '#c084fc', // Beat 5: Purple / Lilac
        '#fb923c', // Beat 6: Warm Orange
        '#818cf8', // Beat 7: Indigo
        '#f472b6', // Beat 8: Rose Pink
        '#2dd4bf', // Beat 9: Teal
        '#a3e635'  // Beat 10: Lime
    ];

    function getBeatColor(order) {
        var num = parseInt(order, 10);
        if (isNaN(num) || num < 1) num = 1;
        return BEAT_PALETTE[(num - 1) % BEAT_PALETTE.length];
    }

    function getTensionRubric(tension) {
        var t = (typeof tension === 'number') ? tension : 50;
        if (t <= 25) return { label: 'Low', color: '#34d399', bg: 'rgba(52, 211, 153, 0.15)' };
        if (t <= 50) return { label: 'Moderate', color: '#fbbf24', bg: 'rgba(251, 191, 36, 0.15)' };
        if (t <= 75) return { label: 'High', color: '#fb923c', bg: 'rgba(251, 146, 60, 0.15)' };
        return { label: 'Crisis', color: '#f87171', bg: 'rgba(248, 113, 113, 0.15)' };
    }

    function formatElapsed(sec) {
        var s = Math.max(0, Math.floor(sec || 0));
        var m = Math.floor(s / 60);
        var rem = s % 60;
        return m + ':' + (rem < 10 ? '0' : '') + rem;
    }

    function getGenerationStageInfo(elapsedSec, status, agent) {
        var agentName = (agent === 'codex' ? 'Codex CLI' : 'Claude CLI');
        var wordCount = (status && status.word_count) ? status.word_count : 0;
        var totalParas = (status && status.total_paragraphs) ? status.total_paragraphs : 0;
        var draftLen = (status && typeof status.draft_length === 'number') ? status.draft_length : 0;
        var tokensStarted = !!(status && status.tokens_started);

        var countText = '';
        if (wordCount > 0 && totalParas > 0) {
            countText = wordCount.toLocaleString() + ' words &bull; ' + totalParas + ' paragraphs';
        } else if (wordCount > 0) {
            countText = wordCount.toLocaleString() + ' words';
        }

        if (tokensStarted || draftLen > 0) {
            var streamProgress = Math.min(45, Math.floor(draftLen / 65));
            var percent = Math.min(95, 50 + streamProgress);
            var sub = draftLen > 0
                ? draftLen.toLocaleString() + ' chars streamed' + (countText ? ' &bull; ' + countText : '')
                : (countText || 'Streaming beat structure');

            return {
                percent: percent,
                stage: 'Extracting narrative beats & dialogue moments…',
                subtext: sub
            };
        }

        if (elapsedSec <= 4) {
            var p = Math.min(20, Math.floor(5 + elapsedSec * 3.5));
            return {
                percent: p,
                stage: 'Initializing ' + agentName + '…',
                subtext: countText || 'Loading scene context'
            };
        } else if (elapsedSec <= 15) {
            var p2 = Math.min(38, Math.floor(20 + (elapsedSec - 4) * 1.6));
            return {
                percent: p2,
                stage: agentName + ' reading scene & evaluating dramatic tension…',
                subtext: countText ? 'Analyzing ' + countText : 'Analyzing scene narrative arc'
            };
        } else if (elapsedSec <= 30) {
            var p3 = Math.min(46, Math.floor(38 + (elapsedSec - 15) * 0.5));
            return {
                percent: p3,
                stage: agentName + ' synthesizing beats, pacing & dialogue…',
                subtext: countText ? 'Synthesizing ' + countText : 'Synthesizing beat progression'
            };
        } else {
            var p4 = Math.min(49, Math.floor(46 + (elapsedSec - 30) * 0.08));
            return {
                percent: p4,
                stage: agentName + ' reasoning across narrative arc…',
                subtext: 'Deep scene analysis in progress (' + formatElapsed(elapsedSec) + ' elapsed)'
            };
        }
    }

    function clearGenerationTimers() {
        if (_beatMapGenerateTimer) {
            clearInterval(_beatMapGenerateTimer);
            _beatMapGenerateTimer = null;
        }
        if (_beatMapGeneratePollTimer) {
            clearInterval(_beatMapGeneratePollTimer);
            _beatMapGeneratePollTimer = null;
        }
    }

    function startGenerationTimers(scenePath) {
        clearGenerationTimers();

        _beatMapGenerateTimer = setInterval(function () {
            if (_beatMapUpdatingScene !== scenePath) {
                clearGenerationTimers();
                return;
            }
            updateGenerationProgressDom();
        }, 1000);

        function pollStatus() {
            if (_beatMapUpdatingScene !== scenePath) {
                clearGenerationTimers();
                return;
            }
            fetch('/api/scene/beatmap/status?path=' + encodeURIComponent(scenePath))
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (_beatMapUpdatingScene !== scenePath) return;
                    if (data && data.ok && data.status) {
                        _beatMapGenerateStatus = data.status;
                        updateGenerationProgressDom();
                    }
                })
                .catch(function () {});
        }

        setTimeout(pollStatus, 800);
        _beatMapGeneratePollTimer = setInterval(pollStatus, 1500);
    }

    function updateGenerationProgressDom() {
        var isGeneratingCurrent = (_beatMapUpdatingScene !== null && _beatMapUpdatingScene === _beatMapCurrentScene);
        if (!isGeneratingCurrent) return;

        var elapsedSec = Math.max(0, Math.floor((Date.now() - _beatMapGenerateStartedAt) / 1000));
        var elapsedFormatted = formatElapsed(elapsedSec);
        var stageInfo = getGenerationStageInfo(elapsedSec, _beatMapGenerateStatus, _beatMapAgent);

        var elapsedEls = document.querySelectorAll('.beatmap-btn-elapsed');
        elapsedEls.forEach(function (el) {
            el.textContent = elapsedFormatted;
        });

        var fillEls = document.querySelectorAll('.beatmap-progress-bar-fill');
        fillEls.forEach(function (fill) {
            fill.style.width = stageInfo.percent + '%';
        });

        var stageEls = document.querySelectorAll('.beatmap-progress-stage');
        stageEls.forEach(function (st) {
            st.textContent = stageInfo.stage;
        });

        var timeEls = document.querySelectorAll('.beatmap-progress-time');
        timeEls.forEach(function (t) {
            t.textContent = elapsedFormatted;
        });

        var subtextEls = document.querySelectorAll('.beatmap-progress-subtext');
        subtextEls.forEach(function (sub) {
            sub.innerHTML = '<span class="beatmap-pulse-dot"></span> ' + escHtml(stageInfo.subtext);
        });

        var crumbEl = document.getElementById('stripSubbarCrumb');
        if (crumbEl) {
            crumbEl.textContent = stageInfo.stage + ' (' + elapsedFormatted + ')';
        }
    }

    function getBeatFractions(beats) {
        if (!beats || !beats.length) return [];
        var totalSpan = 0;
        var spans = beats.map(function (b) {
            var startP = (typeof b.start_paragraph === 'number') ? b.start_paragraph : 0;
            var endP = (typeof b.end_paragraph === 'number') ? b.end_paragraph : startP;
            var span = Math.max(1, endP - startP + 1);
            totalSpan += span;
            return span;
        });

        var cum = 0;
        return beats.map(function (b, i) {
            var span = spans[i];
            var startPct = (cum / totalSpan) * 100;
            var widthPct = (span / totalSpan) * 100;
            var centerPct = startPct + (widthPct / 2);
            cum += span;
            return {
                order: parseInt(b.order, 10) || (i + 1),
                span: span,
                startPct: startPct,
                widthPct: widthPct,
                centerPct: centerPct
            };
        });
    }

    function renderPacingBarHtml(beats, activeBeatOrder) {
        if (!beats || !beats.length) return '';
        var fractions = getBeatFractions(beats);
        var segmentsHtml = beats.map(function (b, i) {
            var bOrder = fractions[i] ? fractions[i].order : (parseInt(b.order, 10) || (i + 1));
            var isActive = (bOrder === activeBeatOrder);
            var color = getBeatColor(bOrder);
            var startP = (typeof b.start_paragraph === 'number') ? b.start_paragraph : 0;
            var endP = (typeof b.end_paragraph === 'number') ? b.end_paragraph : startP;
            var span = fractions[i] ? fractions[i].span : 1;
            var t = (typeof b.estimated_tension === 'number') ? b.estimated_tension : 50;
            var rubric = getTensionRubric(t);
            var title = 'Beat ' + bOrder + ': ' + (b.title || '') + ' (¶' + startP + '–' + endP + ') · Tension ' + t + '/100 (' + rubric.label + ')';
            var cls = 'pacing-segment' + (isActive ? ' active-segment' : '');
            return '<div class="' + cls + '" data-beat-order="' + escHtml(String(bOrder)) + '" style="flex:' + span + '; background:' + color + ';" title="' + escHtml(title) + '"></div>';
        }).join('');

        return '<div class="pacing-bar-track" role="navigation" aria-label="Scene Beat Pacing">' + segmentsHtml + '</div>';
    }

    // A quote that opens with its own quotation mark (most dialogue) is
    // shown as written; anything else is wrapped in curly quotes.
    function quotedMoment(text) {
        var t = String(text || '').trim();
        if (/^["\u201c\u2018']/.test(t)) return escHtml(t);
        return '\u201c' + escHtml(t) + '\u201d';
    }

    function safeMomentType(type) {
        if (typeof type !== 'string') return 'action';
        var clean = type.toLowerCase().trim().replace(/[^a-z0-9_-]/g, '');
        return ALLOWED_MOMENT_TYPES.indexOf(clean) !== -1 ? clean : 'action';
    }

    function isMomentAnchorValid(m) {
        if (!m) return false;
        if (m.valid_anchor === false) return false;
        if (m.source_ref && m.source_ref.valid_anchor === false) return false;
        return true;
    }

    function renderTensionInfoTooltip() {
        return '<span class="tension-title-wrap">' +
            '<span>Dramatic Tension Trajectory</span>' +
            '<span class="tension-info-btn" tabindex="0" role="button" aria-label="Dramatic Tension guide and rubric">' +
            '<svg class="tension-info-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<circle cx="12" cy="12" r="10"></circle>' +
            '<line x1="12" y1="16" x2="12" y2="12"></line>' +
            '<line x1="12" y1="8" x2="12.01" y2="8"></line>' +
            '</svg>' +
            '<div class="tension-tooltip-popover">' +
            '<div class="tension-tooltip-title">Dramatic Tension (0–100)</div>' +
            '<div class="tension-tooltip-desc">Measures narrative stakes, psychological pressure, conflict, uncertainty, and emotional intensity across each beat.</div>' +
            '<div class="tension-rubric-grid">' +
            '<div class="rubric-row"><span class="rubric-score">0–25</span><span class="rubric-label"><strong>Low:</strong> Calm exposition, domestic routine, low stakes</span></div>' +
            '<div class="rubric-row"><span class="rubric-score">26–50</span><span class="rubric-label"><strong>Moderate:</strong> Simmering friction, subtle unease, curiosity</span></div>' +
            '<div class="rubric-row"><span class="rubric-score">51–75</span><span class="rubric-label"><strong>High:</strong> Active confrontation, escalation, urgency</span></div>' +
            '<div class="rubric-row"><span class="rubric-score">76–100</span><span class="rubric-label"><strong>Crisis:</strong> Climax, major turning point, acute stakes</span></div>' +
            '</div>' +
            '</div>' +
            '</span>' +
            '</span>';
    }

    // Load initial user preferences from localStorage
    try {
        var savedPlacement = localStorage.getItem('proseview_beatmap_placement');
        if (savedPlacement === 'horizontal' || savedPlacement === 'vertical') {
            _beatMapPlacement = savedPlacement;
        }
        var savedAgent = localStorage.getItem('proseview_beatmap_agent');
        if (savedAgent === 'claude' || savedAgent === 'codex') {
            _beatMapAgent = savedAgent;
        }
    } catch (e) { }

    function getActiveBeat() {
        if (!_beatMapData || !_beatMapData.beats || !_beatMapData.beats.length) return null;
        var b = _beatMapData.beats.find(function (beat) { return beat.order === _beatMapSelectedBeat; });
        return b || _beatMapData.beats[0];
    }

    function getAllMoments() {
        if (!_beatMapData || !_beatMapData.beats) return [];
        var all = [];
        _beatMapData.beats.forEach(function (beat) {
            (beat.moments || []).forEach(function (m) {
                all.push(Object.assign({}, m, { beatOrder: beat.order }));
            });
        });
        return all;
    }

    function getActiveMoment() {
        var all = getAllMoments();
        if (!all.length) return null;
        var found = all.find(function (m) { return m.order === _beatMapSelectedMoment; });
        return found || all[0];
    }

    // ── API & Persistence ─────────────────────────────────────────────────
    function loadSceneBeatMap(scenePath, callback) {
        if (!scenePath) return;
        var seq = ++_beatMapOpSeq;
        var targetScene = scenePath;
        var isNewScene = (_beatMapCurrentScene !== scenePath);
        _beatMapCurrentScene = scenePath;

        if (isNewScene) {
            _beatMapData = null;
            _beatMapStale = false;
            _beatMapSelectedMoment = 1;
            _beatMapSelectedBeat = 1;
            _beatMapIsZoomed = false;
            _beatMapCollapsedBeats = {};
            renderCurrentPlacement();
        }

        fetch('/api/scene/beatmap?path=' + encodeURIComponent(scenePath))
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (seq !== _beatMapOpSeq || targetScene !== _beatMapCurrentScene) return;
                if (data.beatmap && data.beatmap.scene_path && data.beatmap.scene_path !== _beatMapCurrentScene) return;
                if (_beatMapData && data.beatmap && data.beatmap.generated_at && _beatMapData.generated_at && data.beatmap.generated_at < _beatMapData.generated_at) {
                    return; // Stale delayed load arrived after fresher generation; keep fresh map
                }
                if (data.ok && data.has_map) {
                    _beatMapData = data.beatmap;
                    _beatMapStale = !!data.stale;
                    // The picker names the agent that made this map, so
                    // Update asks the same one.
                    var maker = String(data.beatmap.agent_used || '').toLowerCase();
                    if (maker === 'claude' || maker === 'codex') _beatMapAgent = maker;
                } else {
                    _beatMapData = null;
                    _beatMapStale = false;
                }
                syncStaleIndicator();
                renderCurrentPlacement();
                if (typeof callback === 'function') callback();
            })
            .catch(function (err) {
                if (seq !== _beatMapOpSeq || targetScene !== _beatMapCurrentScene) return;
                console.warn('[proseview] Failed to load beat map:', err);
                _beatMapData = null;
                renderCurrentPlacement();
            });
    }

    function updateSceneBeatMap() {
        if (!_beatMapCurrentScene && typeof paths !== 'undefined' && typeof curIdx !== 'undefined' && paths[curIdx]) {
            _beatMapCurrentScene = paths[curIdx];
        }
        if (!_beatMapCurrentScene) return;
        if (_beatMapUpdatingScene === _beatMapCurrentScene) return;

        var opSeq = ++_beatMapOpSeq;
        var generatingScene = _beatMapCurrentScene;
        _beatMapUpdatingScene = generatingScene;
        _beatMapIsUpdating = true;
        _beatMapGenerateStartedAt = Date.now();
        _beatMapGenerateStatus = null;
        startGenerationTimers(generatingScene);
        renderCurrentPlacement();

        var payload = {
            path: generatingScene,
            agent: _beatMapAgent
        };

        fetch('/api/scene/beatmap/generate', {
            method: 'POST',
            headers: (typeof pvHeaders === 'function') ? pvHeaders() : { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(function (res) {
                if (!res.ok) {
                    return res.json().then(function (d) {
                        throw new Error(d.error || ('HTTP ' + res.status));
                    }).catch(function (e) {
                        throw new Error(e.message || ('HTTP ' + res.status));
                    });
                }
                return res.json();
            })
            .then(function (data) {
                clearGenerationTimers();
                _beatMapGenerateStatus = null;
                _beatMapGenerateStartedAt = 0;
                if (_beatMapUpdatingScene === generatingScene) {
                    _beatMapUpdatingScene = null;
                }
                _beatMapIsUpdating = (_beatMapUpdatingScene !== null && _beatMapUpdatingScene === _beatMapCurrentScene);

                if (opSeq !== _beatMapOpSeq || generatingScene !== _beatMapCurrentScene) {
                    renderCurrentPlacement();
                    return;
                }
                if (data.beatmap && data.beatmap.scene_path && data.beatmap.scene_path !== _beatMapCurrentScene) {
                    renderCurrentPlacement();
                    return;
                }
                if (data.ok && data.beatmap) {
                    _beatMapData = data.beatmap;
                    _beatMapStale = !!data.stale;
                    syncStaleIndicator();
                    renderCurrentPlacement();
                } else {
                    var errMsg = data.error || 'unknown error';
                    if (typeof sidebarShowToast === 'function') {
                        sidebarShowToast('Beat map generation failed: ' + errMsg, true);
                    }
                    window.dispatchEvent(new CustomEvent('beatmap-generation-failed', {
                        detail: { scene_path: generatingScene, error: errMsg }
                    }));
                    renderCurrentPlacement();
                }
            })
            .catch(function (err) {
                clearGenerationTimers();
                _beatMapGenerateStatus = null;
                _beatMapGenerateStartedAt = 0;
                if (_beatMapUpdatingScene === generatingScene) {
                    _beatMapUpdatingScene = null;
                }
                _beatMapIsUpdating = (_beatMapUpdatingScene !== null && _beatMapUpdatingScene === _beatMapCurrentScene);
                if (opSeq !== _beatMapOpSeq || generatingScene !== _beatMapCurrentScene) {
                    renderCurrentPlacement();
                    return;
                }
                var errMsg = err.message || String(err);
                if (typeof sidebarShowToast === 'function') {
                    sidebarShowToast('Beat map request failed: ' + errMsg, true);
                }
                window.dispatchEvent(new CustomEvent('beatmap-generation-failed', {
                    detail: { scene_path: generatingScene, error: errMsg }
                }));
                renderCurrentPlacement();
            });
    }

    function deleteSceneBeatMap(scenePath) {
        if (!scenePath) return;
        fetch('/api/scene/beatmap/delete', {
            method: 'POST',
            headers: (typeof pvHeaders === 'function') ? pvHeaders() : { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: scenePath })
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && data.ok) {
                    if (_beatMapCurrentScene === scenePath) {
                        clearGenerationTimers();
                        _beatMapData = null;
                        _beatMapStale = false;
                        _beatMapUpdatingScene = null;
                        _beatMapIsUpdating = false;
                        syncStaleIndicator();
                        renderCurrentPlacement();
                    }
                    window.dispatchEvent(new CustomEvent('beatmap-deleted', { detail: { scene_path: scenePath } }));
                } else {
                    if (typeof sidebarShowToast === 'function') {
                        sidebarShowToast('Failed to delete beat map: ' + (data.error || 'unknown error'), true);
                    }
                    renderCurrentPlacement();
                }
            })
            .catch(function (err) {
                if (typeof sidebarShowToast === 'function') {
                    sidebarShowToast('Failed to delete beat map: ' + (err.message || String(err)), true);
                }
                renderCurrentPlacement();
            });
    }

    function renderTrashIconSvg() {
        return '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<polyline points="3 6 5 6 21 6"></polyline>' +
            '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>' +
            '</svg>';
    }

    function bindDeleteHandler(containerEl, scenePath) {
        if (!containerEl || !scenePath) return;

        function renderDefault() {
            containerEl.innerHTML =
                '<button type="button" class="beatmap-delete-btn" title="Delete beat map for this scene" aria-label="Delete beat map">' +
                renderTrashIconSvg() +
                '</button>';

            var btn = containerEl.querySelector('.beatmap-delete-btn');
            if (btn) {
                btn.onclick = function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    renderConfirm();
                };
            }
        }

        function renderConfirm() {
            containerEl.innerHTML =
                '<div class="beatmap-delete-confirm-wrap">' +
                '<span class="beatmap-delete-prompt">Delete map?</span>' +
                '<button type="button" class="beatmap-delete-confirm-btn" title="Confirm deletion">Delete</button>' +
                '<button type="button" class="beatmap-delete-cancel-btn" title="Cancel">Cancel</button>' +
                '</div>';

            var confirmBtn = containerEl.querySelector('.beatmap-delete-confirm-btn');
            var cancelBtn = containerEl.querySelector('.beatmap-delete-cancel-btn');

            if (cancelBtn) {
                cancelBtn.onclick = function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    renderDefault();
                };
            }

            if (confirmBtn) {
                confirmBtn.onclick = function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    confirmBtn.disabled = true;
                    confirmBtn.textContent = '…';
                    deleteSceneBeatMap(scenePath);
                };
            }
        }

        renderDefault();
    }

    function syncStaleIndicator() {
        var tab = document.getElementById('utilityTabBeats');
        if (tab) {
            tab.classList.toggle('utility-tab-attention', _beatMapStale);
        }
    }

    // ── Strip & Dock Placement Control ───────────────────────────────────
    function isHorizontalStripVisible() {
        var strip = document.getElementById('sceneBeatMapStripContainer');
        return !!(strip && !strip.hidden);
    }

    function showHorizontalStrip() {
        var stripContainer = document.getElementById('sceneBeatMapStripContainer');
        var header = document.querySelector('#sceneModal .modal-header');
        if (header) {
            header.dataset.toolbarHidden = 'false';
        }
        if (stripContainer) {
            stripContainer.hidden = false;
            renderHorizontalStrip();
        }
        _beatMapPlacement = 'horizontal';
        try { localStorage.setItem('proseview_beatmap_placement', 'horizontal'); } catch (e) { }
        renderCurrentPlacement();
    }

    function hideHorizontalStrip() {
        var stripContainer = document.getElementById('sceneBeatMapStripContainer');
        if (stripContainer) {
            stripContainer.hidden = true;
        }
        _beatMapPlacement = 'vertical';
        try { localStorage.setItem('proseview_beatmap_placement', 'vertical'); } catch (e) { }
        renderCurrentPlacement();
    }

    function toggleHorizontalStrip() {
        if (isHorizontalStripVisible()) {
            hideHorizontalStrip();
        } else {
            showHorizontalStrip();
        }
    }

    function switchBeatMapPlacement(placement) {
        _beatMapPlacement = placement;
        try { localStorage.setItem('proseview_beatmap_placement', placement); } catch (e) { }

        if (placement === 'horizontal') {
            showHorizontalStrip();
        } else {
            hideHorizontalStrip();
            if (typeof showScenePanelTab === 'function') {
                showScenePanelTab('beats');
            }
        }
    }

    function toggleBeatMapPlacement() {
        toggleHorizontalStrip();
    }

    function renderCurrentPlacement() {
        var stripContainer = document.getElementById('sceneBeatMapStripContainer');
        if (_beatMapPlacement === 'horizontal' && stripContainer) {
            stripContainer.hidden = false;
        }
        if (stripContainer && !stripContainer.hidden) {
            renderHorizontalStrip();
        }
        var pane = document.getElementById('sceneBeatMapPane');
        if (pane) {
            renderSceneBeatMapPane();
        }
    }

    // ── Navigation & Selection ────────────────────────────────────────────
    function selectBeat(order, zoom) {
        _beatMapSelectedBeat = order;
        if (typeof zoom === 'boolean') {
            _beatMapIsZoomed = zoom;
        }
        _beatMapCollapsedBeats[order] = false;
        var activeB = getActiveBeat();
        if (activeB && activeB.moments && activeB.moments.length) {
            var currentM = getActiveMoment();
            if (!currentM || currentM.beatOrder !== order) {
                _beatMapSelectedMoment = activeB.moments[0].order;
            }
        }
        renderCurrentPlacement();
        syncProseHighlight(getActiveMoment());
    }

    function stepMoment(delta) {
        var all = getAllMoments();
        if (!all.length) return;
        var currentIdx = all.findIndex(function (m) { return m.order === _beatMapSelectedMoment; });
        if (currentIdx === -1) currentIdx = 0;
        var nextIdx = currentIdx + delta;
        if (nextIdx < 0) nextIdx = 0;
        if (nextIdx >= all.length) nextIdx = all.length - 1;

        var targetM = all[nextIdx];
        _beatMapSelectedMoment = targetM.order;
        _beatMapSelectedBeat = targetM.beatOrder;
        _beatMapCollapsedBeats[targetM.beatOrder] = false;
        renderCurrentPlacement();
        syncProseHighlight(targetM);
    }

    function selectMoment(order) {
        var all = getAllMoments();
        var target = all.find(function (m) { return m.order === order; });
        if (!target) return;

        var beatChanged = (_beatMapSelectedBeat !== target.beatOrder);
        _beatMapSelectedMoment = target.order;
        _beatMapSelectedBeat = target.beatOrder;
        _beatMapCollapsedBeats[target.beatOrder] = false;

        if (_beatMapPlacement === 'vertical') {
            var pane = document.getElementById('sceneBeatMapPane');
            // If the active beat in the vertical dock hasn't changed, update classes in place
            // to avoid blowing away pane.innerHTML and resetting the scroll position!
            if (pane && !beatChanged) {
                pane.querySelectorAll('.sidebar-moment-card').forEach(function (card) {
                    var ord = parseInt(card.dataset.momentOrder, 10);
                    card.classList.toggle('active-sidebar-moment', ord === target.order);
                });
                var activeCard = pane.querySelector('.sidebar-moment-card[data-moment-order="' + target.order + '"]');
                if (activeCard && typeof activeCard.scrollIntoView === 'function') {
                    activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
                syncProseHighlight(target);
                return;
            }
        }

        renderCurrentPlacement();
        syncProseHighlight(target);
    }

    function normalizeProseString(str) {
        if (!str) return '';
        return String(str)
            .replace(/[\u201c\u201d"]/g, '"')       // smart double quotes -> "
            .replace(/[\u2018\u2019']/g, "'")       // smart single quotes / curly apostrophes -> '
            .replace(/[\u2013\u2014]/g, '-')        // en-dash / em-dash -> -
            .replace(/\u2026/g, '...')              // ellipsis -> ...
            .replace(/\s+/g, ' ')                   // all newlines, tabs, and spaces -> single space
            .trim();
    }

    function findProseParagraph(paraIdx, exactQuote, validAnchor) {
        var host = document.getElementById('sceneProseHost');
        if (!host) return null;
        var root = host.querySelector('.ProseMirror');
        if (!root) return null;

        // 1. Gather all top-level prose blocks matching Python paragraph_blocks()
        // (excludes headings and decoration widgets, but includes <p>, <hr>, <blockquote> etc.)
        var blocks = [];
        for (var i = 0; i < root.children.length; i++) {
            var child = root.children[i];
            if (/^H[1-6]$/i.test(child.tagName)) continue;
            if (child.classList && child.classList.contains('ProseMirror-widget')) continue;
            blocks.push(child);
        }
        if (!blocks.length) return null;

        var cleanQuote = exactQuote ? exactQuote.replace(/^[“”"'\s]+|[“”"'\s]+$/g, '').trim() : '';
        var normQuote = normalizeProseString(cleanQuote);

        // 2. Direct check at paraIdx
        if (typeof paraIdx === 'number' && paraIdx >= 0 && paraIdx < blocks.length) {
            var candidate = blocks[paraIdx];
            if (candidate && candidate.tagName === 'P') {
                if (!normQuote) return candidate;
                if (normalizeProseString(candidate.textContent).indexOf(normQuote) !== -1) {
                    return candidate;
                }
            }
            // Check immediately adjacent blocks (±1, ±2) in case of divider or annotation offset
            for (var offset = 1; offset <= 2; offset++) {
                var prev = blocks[paraIdx - offset];
                if (prev && prev.tagName === 'P' && normQuote && normalizeProseString(prev.textContent).indexOf(normQuote) !== -1) {
                    return prev;
                }
                var next = blocks[paraIdx + offset];
                if (next && next.tagName === 'P' && normQuote && normalizeProseString(next.textContent).indexOf(normQuote) !== -1) {
                    return next;
                }
            }
        }

        // 3. Search all blocks for the full normalized quote
        if (normQuote && normQuote.length >= 3) {
            for (var j = 0; j < blocks.length; j++) {
                var b = blocks[j];
                if (b.tagName !== 'P' && !b.textContent) continue;
                if (normalizeProseString(b.textContent).indexOf(normQuote) !== -1) {
                    return b;
                }
            }
        }

        // 4. If full quote didn't match (e.g. quote was very long or slightly paraphrased),
        // try searching for the first 3-4 words (at least 10 chars)
        if (normQuote && normQuote.length >= 10) {
            var words = normQuote.split(' ');
            if (words.length >= 3) {
                var snippet = words.slice(0, 4).join(' ');
                if (snippet.length >= 10) {
                    for (var k = 0; k < blocks.length; k++) {
                        var b2 = blocks[k];
                        if (b2.tagName !== 'P' && !b2.textContent) continue;
                        if (normalizeProseString(b2.textContent).indexOf(snippet) !== -1) {
                            return b2;
                        }
                    }
                }
            }
        }

        // 5. Fallback: If quote text search failed, jump to referenced paraIdx if valid
        // (prevents unresponsive clicks; always lands author in the right neighborhood)
        if (typeof paraIdx === 'number' && paraIdx >= 0 && paraIdx < blocks.length) {
            var target = blocks[paraIdx];
            if (target && target.tagName === 'P') return target;
            if (paraIdx + 1 < blocks.length && blocks[paraIdx + 1].tagName === 'P') return blocks[paraIdx + 1];
            if (paraIdx - 1 >= 0 && blocks[paraIdx - 1].tagName === 'P') return blocks[paraIdx - 1];
            return target;
        }

        return null;
    }

    function syncProseHighlight(moment) {
        if (!moment) return;
        var sourceRef = moment.source_ref;
        var paraIdx = sourceRef ? sourceRef.paragraph : null;
        var quote = (sourceRef && sourceRef.exact_quote) ? sourceRef.exact_quote.trim() : (moment.text || '');
        var validAnchor = isMomentAnchorValid(moment);

        // Find block in ProseMirror
        var targetBlock = findProseParagraph(paraIdx, quote, validAnchor);

        // Clear existing highlights
        document.querySelectorAll('.para-beat-active').forEach(function (el) {
            el.classList.remove('para-beat-active');
        });
        document.querySelectorAll('.moment-active-highlight').forEach(function (el) {
            var parent = el.parentNode;
            if (parent) {
                parent.replaceChild(document.createTextNode(el.textContent), el);
                parent.normalize();
            }
        });

        if (targetBlock) {
            targetBlock.classList.add('para-beat-active');

            if (quote) {
                highlightSubstringInElement(targetBlock, quote);
            }

            targetBlock.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    function highlightSubstringInElement(el, searchText) {
        if (!el || !searchText) return;
        var rawSearch = searchText.replace(/^[“”"'\s]+|[“”"'\s]+$/g, '').trim();
        if (!rawSearch || rawSearch.length < 2) return;

        var normSearch = normalizeProseString(rawSearch);
        if (!normSearch) return;

        var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
        var node;
        while ((node = walker.nextNode())) {
            var val = node.nodeValue || '';
            if (!val) continue;

            // 1. Direct match in node
            var idx = val.indexOf(rawSearch);
            var matchLen = rawSearch.length;

            // 2. Normalized match in node (handles smart quotes, curly apostrophes, and \n -> space)
            if (idx === -1) {
                var cleanVal = val.replace(/[\u201c\u201d"]/g, '"').replace(/[\u2018\u2019']/g, "'").replace(/\s+/g, ' ');
                var cleanKey = normSearch.length > 35 ? normSearch.slice(0, 35) : normSearch;
                var cleanKeyFixed = cleanKey.replace(/[\u201c\u201d"]/g, '"').replace(/[\u2018\u2019']/g, "'").replace(/\s+/g, ' ');
                var kIdx = cleanVal.indexOf(cleanKeyFixed);
                if (kIdx !== -1) {
                    idx = kIdx;
                    matchLen = Math.min(cleanKeyFixed.length, val.length - idx);
                }
            }

            // 3. Fallback: match first 2-3 words in node if long
            if (idx === -1 && normSearch.length > 15) {
                var words = normSearch.split(' ');
                if (words.length >= 2) {
                    var leadWords = words.slice(0, 3).join(' ');
                    var leadClean = leadWords.replace(/[\u201c\u201d"]/g, '"').replace(/[\u2018\u2019']/g, "'").replace(/\s+/g, ' ');
                    var cleanVal2 = val.replace(/[\u201c\u201d"]/g, '"').replace(/[\u2018\u2019']/g, "'").replace(/\s+/g, ' ');
                    var lIdx = cleanVal2.indexOf(leadClean);
                    if (lIdx !== -1) {
                        idx = lIdx;
                        matchLen = Math.min(leadClean.length, val.length - idx);
                    }
                }
            }

            if (idx !== -1 && idx + matchLen <= val.length) {
                try {
                    var range = document.createRange();
                    range.setStart(node, idx);
                    range.setEnd(node, idx + matchLen);
                    var span = document.createElement('span');
                    span.className = 'moment-active-highlight';
                    range.surroundContents(span);
                    return;
                } catch (e) {
                    // Ignore DOM range boundary error
                }
            }
        }
    }

    function jumpToActiveMoment() {
        var m = getActiveMoment();
        if (!isMomentAnchorValid(m)) return;
        syncProseHighlight(m);
    }

    // ── Tension Curve Sparkline Rendering ─────────────────────────────────
    function renderTensionCurveSvg(beats, activeBeatOrder) {
        var count = beats ? beats.length : 0;
        if (count < 2) return '';

        var fractions = getBeatFractions(beats);
        var height = 22;

        var points = fractions.map(function (f, i) {
            var b = beats[i];
            var x = (f.centerPct / 100) * 1000;
            var t = (typeof b.estimated_tension === 'number') ? b.estimated_tension : 50;
            var y = 17 - ((t / 100) * 13);
            var bOrder = f.order;
            return { x: x, y: y, order: bOrder, tension: t, centerPct: f.centerPct, beat: b };
        });

        // Build cubic bezier path
        var pathD = 'M ' + points[0].x.toFixed(1) + ' ' + points[0].y.toFixed(1);
        for (var i = 0; i < points.length - 1; i++) {
            var p0 = points[i];
            var p1 = points[i + 1];
            var cp1x = p0.x + (p1.x - p0.x) / 2;
            var cp1y = p0.y;
            var cp2x = p0.x + (p1.x - p0.x) / 2;
            var cp2y = p1.y;
            pathD += ' C ' + cp1x.toFixed(1) + ' ' + cp1y.toFixed(1) + ', ' + cp2x.toFixed(1) + ' ' + cp2y.toFixed(1) + ', ' + p1.x.toFixed(1) + ' ' + p1.y.toFixed(1);
        }

        var fillD = pathD + ' L ' + points[points.length - 1].x.toFixed(1) + ' ' + height + ' L ' + points[0].x.toFixed(1) + ' ' + height + ' Z';

        var strokeGradId = 'tc_stroke_grad_' + Math.floor(Math.random() * 1000000);
        var fillGradId = 'tc_fill_grad_' + Math.floor(Math.random() * 1000000);

        var strokeStops = points.map(function (pt) {
            var pct = pt.centerPct.toFixed(1);
            var color = getBeatColor(pt.order);
            return '<stop offset="' + pct + '%" stop-color="' + color + '"/>';
        }).join('');

        var nodesHtml = points.map(function (pt) {
            var isActive = (pt.order === activeBeatOrder);
            var color = getBeatColor(pt.order);
            var rubric = getTensionRubric(pt.tension);
            var titleAttr = 'Beat ' + pt.order + (pt.beat.title ? ': ' + pt.beat.title : '') + ' • Tension: ' + pt.tension + '/100 (' + rubric.label + ')';
            var cls = 'curve-node' + (isActive ? ' active-node' : '');
            var bg = isActive ? '#ffffff' : color;
            var borderStyle = isActive ? ('border: 1.6px solid ' + color + ';') : 'border: none;';
            return '<div class="' + cls + '" data-beat-order="' + escHtml(String(pt.order)) + '" style="left:' + pt.centerPct.toFixed(2) + '%; top:' + pt.y.toFixed(1) + 'px; background:' + bg + '; ' + borderStyle + '" title="' + escHtml(titleAttr) + '"></div>';
        }).join('');

        return '<div class="tension-curve-wrapper">' +
            '<svg class="tension-curve-svg" viewBox="0 0 1000 ' + height + '" preserveAspectRatio="none">' +
            '<defs>' +
            '<linearGradient id="' + strokeGradId + '" x1="0%" y1="0%" x2="100%" y2="0%">' +
            strokeStops +
            '</linearGradient>' +
            '<linearGradient id="' + fillGradId + '" x1="0%" y1="0%" x2="0%" y2="100%">' +
            '<stop offset="0%" stop-color="var(--primary, #dd635f)" stop-opacity="0.2"/>' +
            '<stop offset="100%" stop-color="var(--primary, #dd635f)" stop-opacity="0.0"/>' +
            '</linearGradient>' +
            '</defs>' +
            '<line x1="' + points[0].x.toFixed(1) + '" y1="20" x2="' + points[points.length - 1].x.toFixed(1) + '" y2="20" stroke="var(--border, #35393c)" stroke-width="1" stroke-dasharray="3 3"/>' +
            '<path class="tension-fill" d="' + fillD + '" fill="url(#' + fillGradId + ')"/>' +
            '<path class="tension-path" d="' + pathD + '" stroke="url(#' + strokeGradId + ')" vector-effect="non-scaling-stroke"/>' +
            '</svg>' +
            '<div class="curve-nodes-layer">' +
            nodesHtml +
            '</div>' +
            '</div>';
    }

    function bindDotTooltips(container) {
        var tensionRow = container.querySelector('.tension-curve-row');
        if (!tensionRow) return;

        function showTip(targetEl, bOrder) {
            if (!_beatMapData || !_beatMapData.beats) return;
            var beat = _beatMapData.beats.find(function (b) {
                return (parseInt(b.order, 10) || 1) === bOrder;
            });
            if (!beat) return;
            var tip = tensionRow.querySelector('.tension-dot-tooltip');
            if (!tip) return;

            var t = (typeof beat.estimated_tension === 'number') ? beat.estimated_tension : 50;
            var rubric = getTensionRubric(t);
            var color = getBeatColor(bOrder);
            var tpBadge = beat.is_turning_point ? '<span class="tip-tp-badge">Turning Point</span>' : '';

            tip.innerHTML =
                '<div class="tip-header">' +
                '<span class="beat-color-dot" style="background:' + color + ';"></span>' +
                '<span>Beat ' + bOrder + (beat.title ? ': ' + escHtml(beat.title) : '') + '</span>' +
                tpBadge +
                '</div>' +
                '<div class="tip-val">' +
                '<span>Tension: <strong style="color:var(--text-main); font-size:11px;">' + t + ' / 100</strong></span>' +
                '<span class="tip-rubric" style="background:' + rubric.bg + '; color:' + rubric.color + ';">' + rubric.label + '</span>' +
                '</div>';

            var targetRect = targetEl.getBoundingClientRect();
            var rowRect = tensionRow.getBoundingClientRect();
            var x = targetRect.left + (targetRect.width / 2) - rowRect.left;
            var y = targetRect.top - rowRect.top;

            var minX = 75;
            var maxX = rowRect.width - 75;
            if (maxX > minX) {
                x = Math.max(minX, Math.min(maxX, x));
            }

            tip.style.left = x + 'px';
            tip.style.top = y + 'px';
            tip.classList.add('visible');
        }

        function hideTip() {
            var tip = tensionRow.querySelector('.tension-dot-tooltip');
            if (tip) tip.classList.remove('visible');
        }

        tensionRow.querySelectorAll('.curve-node').forEach(function (node) {
            var order = parseInt(node.dataset.beatOrder, 10);
            node.addEventListener('mouseenter', function () { showTip(node, order); });
            node.addEventListener('mouseleave', hideTip);
        });

        tensionRow.querySelectorAll('.pacing-segment').forEach(function (seg) {
            var order = parseInt(seg.dataset.beatOrder, 10);
            seg.addEventListener('mouseenter', function () { showTip(seg, order); });
            seg.addEventListener('mouseleave', hideTip);
        });
    }

    // ── Horizontal Strip View ─────────────────────────────────────────────
    function renderHorizontalStrip() {
    var container = document.getElementById('sceneBeatMapStripContainer');
    if (!container) return;

    var isGeneratingCurrent = (_beatMapUpdatingScene !== null && _beatMapUpdatingScene === _beatMapCurrentScene);
    var elapsedSec = isGeneratingCurrent ? Math.max(0, Math.floor((Date.now() - _beatMapGenerateStartedAt) / 1000)) : 0;
    var stageInfo = isGeneratingCurrent ? getGenerationStageInfo(elapsedSec, _beatMapGenerateStatus, _beatMapAgent) : null;

    if (!_beatMapData || !_beatMapData.beats || !_beatMapData.beats.length) {
        container.innerHTML =
            '<div class="beat-strip-horizontal">' +
            '<div class="strip-control-bar">' +
            '<div class="strip-status-left">' +
            (isGeneratingCurrent
                ? '<span class="status-saved-tag"><span class="beatmap-pulse-dot"></span> <strong style="color:var(--text-main);">Generating Beat Map</strong> <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span></span>'
                : '<span class="status-saved-tag"><span class="status-dot stale"></span> Beat map not generated</span>') +
            '</div>' +
            '<div class="strip-controls-right">' +
            '<div style="display:inline-flex; align-items:center; gap:6px;">' +
            '<select id="stripAgentSelect" class="beatmap-agent-picker" style="font-size:11px; padding:2px 6px;"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
            '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
            '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
            '</select>' +
            '<button type="button" class="beatmap-generate-btn' + (isGeneratingCurrent ? ' is-generating' : '') + '" id="stripGenerateBtn" style="font-size:11px; padding:3px 10px;"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
            (isGeneratingCurrent
                ? '<span class="beatmap-spinner"></span> Generating… <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span>'
                : '↻ Generate Beat Map') +
            '</button>' +
            '</div>' +
            '<button type="button" class="strip-close-btn" id="emptyStripCloseBtn" title="Close horizontal beat strip">✕</button>' +
            '</div>' +
            '</div>' +
            '<div class="strip-cards-viewport" style="align-items:center; justify-content:center;">' +
            (isGeneratingCurrent
                ? '<div class="beatmap-progress-panel" style="max-width:620px; width:100%; margin:0 20px;">' +
                  '<div class="beatmap-progress-bar-wrap">' +
                  '<div class="beatmap-progress-bar-fill" style="width:' + stageInfo.percent + '%;"></div>' +
                  '</div>' +
                  '<div class="beatmap-progress-label">' +
                  '<span class="beatmap-progress-stage">' + escHtml(stageInfo.stage) + '</span>' +
                  '<span class="beatmap-progress-time">' + formatElapsed(elapsedSec) + '</span>' +
                  '</div>' +
                  '<div class="beatmap-progress-subtext">' +
                  '<span class="beatmap-pulse-dot"></span> ' + escHtml(stageInfo.subtext) +
                  '</div>' +
                  '</div>'
                : '<div style="display:flex; align-items:center; gap:16px; background:var(--surface-card); border:1px dashed var(--border); border-radius:6px; padding:10px 18px; max-width:650px;">' +
                  '<svg style="width:120px; height:32px; flex-shrink:0;" viewBox="0 0 120 32">' +
                  '<line x1="5" y1="28" x2="115" y2="28" stroke="var(--border)" stroke-width="1" stroke-dasharray="2 2"/>' +
                  '<path d="M 10 22 Q 40 18 70 8 T 110 16" fill="none" stroke="var(--primary)" stroke-width="1.8"/>' +
                  '<circle cx="10" cy="22" r="2.5" fill="var(--primary)"/>' +
                  '<circle cx="70" cy="8" r="3.5" fill="#fff" stroke="var(--primary)" stroke-width="1.5"/>' +
                  '<circle cx="110" cy="16" r="2.5" fill="var(--primary)"/>' +
                  '</svg>' +
                  '<div style="font-size:11px; color:var(--text-muted); line-height:1.4;">' +
                  '<strong style="color:var(--text-main); font-size:11.5px; display:block; margin-bottom:2px;">Visual Beat Progression</strong>' +
                  'Click <strong>↻ Generate Beat Map</strong> to extract narrative beats, tension curve, and sequential dialogue moments for this scene.' +
                  '</div>' +
                  '</div>') +
            '</div>' +
            '<div class="scene-text-subbar">' +
            '<div class="subbar-left">' +
            '<span class="subbar-scene-label">Scene text</span>' +
            '<span class="subbar-crumb" id="stripSubbarCrumb">' +
            (isGeneratingCurrent
                ? escHtml(stageInfo.stage) + ' (' + formatElapsed(elapsedSec) + ')'
                : 'Awaiting beat map generation') +
            '</span>' +
            '</div>' +
            '<div class="subbar-right">' +
            '<span style="color:var(--text-muted); font-size:10.5px;">• On demand</span>' +
            '</div>' +
            '</div>' +
            '</div>';

        var closeBtn = container.querySelector('#emptyStripCloseBtn');
        if (closeBtn) closeBtn.onclick = function () { hideHorizontalStrip(); };

        var genBtn = container.querySelector('#stripGenerateBtn');
        var agentSel = container.querySelector('#stripAgentSelect');
        if (genBtn) genBtn.onclick = function () {
            if (agentSel) {
                _beatMapAgent = agentSel.value;
                try { localStorage.setItem('proseview_beatmap_agent', _beatMapAgent); } catch (e) { }
            }
            updateSceneBeatMap();
        };
        return;
    }

    var beats = _beatMapData.beats;
    var activeBeat = getActiveBeat();
    var allMoments = getAllMoments();
    var activeMoment = getActiveMoment();
    var currentMIndex = allMoments.findIndex(function (m) { return m.order === _beatMapSelectedMoment; });
    var totalMoments = allMoments.length;
    var counterText = (currentMIndex >= 0 ? (currentMIndex + 1) : 1).toString().padStart(2, '0') + ' / ' + totalMoments.toString().padStart(2, '0');

    var statusDotCls = 'status-dot' + (_beatMapStale ? ' stale' : '');
    var statusLabel = _beatMapStale ? 'Outdated • Scene edited' : 'All beats • Saved';

    // 1. Control Bar
    var controlBar =
        '<div class="strip-control-bar">' +
        '<div class="strip-status-left">' +
        (isGeneratingCurrent
            ? '<span class="status-saved-tag"><span class="beatmap-pulse-dot"></span> Updating map… <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span></span>'
            : '<span class="status-saved-tag"><span class="' + statusDotCls + '"></span> ' + statusLabel + '</span>') +
        '</div>' +
        '<div class="strip-controls-right">' +
        '<div class="moment-stepper">' +
        '<button type="button" class="stepper-btn" id="stepperPrev" title="Previous moment">&lt;</button>' +
        '<span>' + counterText + '</span>' +
        '<button type="button" class="stepper-btn" id="stepperNext" title="Next moment">&gt;</button>' +
        '</div>' +
        '<div style="display:inline-flex; align-items:center; background:var(--surface-field); border:1px solid var(--border); border-radius:4px; padding:1px 6px; gap:4px;">' +
        '<select id="stripActiveAgent" class="beat-agent-select"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
        '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
        '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
        '</select>' +
        '<button type="button" class="strip-btn' + (isGeneratingCurrent ? ' is-generating' : '') + '" id="stripUpdateBtn" style="border:0; padding:2px 4px;"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
        (isGeneratingCurrent
            ? '<span class="beatmap-spinner subtle"></span> Updating… <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span>'
            : '↻ Update') +
        '</button>' +
        (!isGeneratingCurrent ? '<div id="stripDeleteContainer" style="display:inline-flex; align-items:center;"></div>' : '') +
        '</div>' +
        '<button type="button" class="strip-close-btn" id="stripCloseBtn" title="Close horizontal beat strip">✕</button>' +
        '</div>' +
        '</div>';

    // 2. Tension Curve
    var tensionRow =
        '<div class="tension-curve-row">' +
        '<div class="tension-curve-header">' +
        renderTensionInfoTooltip() +
        '<span class="tension-estimate-caption">Estimated Interpretation</span>' +
        '</div>' +
        renderTensionCurveSvg(beats, activeBeat ? activeBeat.order : 1) +
        renderPacingBarHtml(beats, activeBeat ? activeBeat.order : 1) +
        '<div class="tension-dot-tooltip" role="tooltip" aria-hidden="true"></div>' +
        '</div>';

    // 3. Viewport (Locked 106px Height)
    var viewportContent = '';
    if (_beatMapIsZoomed) {
        // Zoomed moments view
        var momentCards = (activeBeat.moments || []).map(function (m) {
            var mOrder = parseInt(m.order, 10) || 1;
            var isActive = (mOrder === _beatMapSelectedMoment);
            var cls = 'moment-item-card' + (isActive ? ' active-moment' : '');
            var quoteText = (m.source_ref && m.source_ref.exact_quote) ? m.source_ref.exact_quote : m.text;
            var speakerHtml = m.speaker ? '<span class="moment-speaker">' + escHtml(m.speaker) + '</span>' : '';
            var sType = safeMomentType(m.type);
            var seqStr = escHtml(mOrder.toString().padStart(2, '0'));
            return '<div class="' + cls + '" data-moment-order="' + escHtml(String(mOrder)) + '">' +
                '<div class="moment-top-row">' +
                '<span class="moment-seq">#' + seqStr + '</span>' +
                '<span class="moment-type-tag type-' + sType + '">' + escHtml(sType.replace(/_/g, ' ')) + '</span>' +
                '</div>' +
                (speakerHtml ? '<div>' + speakerHtml + '</div>' : '') +
                '<div class="moment-quote">' + quotedMoment(quoteText) + '</div>' +
                '</div>';
        }).join('');

        viewportContent =
            '<div class="beat-moments-zoom">' +
            '<button type="button" class="btn-all-beats" id="btnReturnAllBeats" title="Back to all beats (Esc)">&larr; All beats <kbd style="opacity:0.6; font-size:9.5px; font-family:var(--font-mono); margin-left:3px; padding:1px 3px; border:1px solid var(--border); border-radius:3px;">Esc</kbd></button>' +
            '<div class="moments-scroll-row">' + momentCards + '</div>' +
            '</div>';
    } else {
        // Overview with flexible horizontal scrolling for any number of narrative beats
        var beatCards = beats.map(function (b) {
            var bOrder = parseInt(b.order, 10) || 1;
            var isSelected = (activeBeat && bOrder === (parseInt(activeBeat.order, 10) || 1));
            var cls = 'beat-nav-card' + (isSelected ? ' selected' : '');
            var tpBadge = b.is_turning_point ? '<span class="turning-point-badge">Turning point</span>' : '';
            return '<div class="' + cls + '" data-beat-order="' + escHtml(String(bOrder)) + '" title="Click to select, double-click to view moments">' +
                '<div class="card-top">' +
                '<span class="beat-index-tag"><span class="beat-color-dot" style="background:' + getBeatColor(bOrder) + ';"></span>BEAT ' + escHtml(String(bOrder)) + '</span>' +
                tpBadge +
                '<span class="card-arrow" title="View moments">&nearr;</span>' +
                '</div>' +
                '<div class="beat-card-title">' + escHtml(b.title) + '</div>' +
                '<div class="beat-card-desc">' + escHtml(b.summary) + '</div>' +
                '</div>';
        }).join('');

        viewportContent = '<div class="beat-cards-overview">' + beatCards + '</div>';
    }

    var cardsViewport = '<div class="strip-cards-viewport">' + viewportContent + '</div>';

    // 4. Scene Context Sub-bar
    var pIdx = (activeMoment && activeMoment.source_ref && typeof activeMoment.source_ref.paragraph === 'number') ? activeMoment.source_ref.paragraph : null;
    var hasValidAnchor = isMomentAnchorValid(activeMoment);
    var curBeatOrder = activeBeat ? (parseInt(activeBeat.order, 10) || 1) : 1;
    var curMomOrder = activeMoment ? (parseInt(activeMoment.order, 10) || 1) : 1;
    var curMomStr = curMomOrder.toString().padStart(2, '0');
    var subBar =
        '<div class="scene-text-subbar">' +
        '<div class="subbar-left">' +
        '<span class="subbar-scene-label">Scene text</span>' +
        '<span class="subbar-crumb"><span class="beat-color-dot" style="background:' + getBeatColor(curBeatOrder) + ';"></span>Beat ' + curBeatOrder + ' · Moment ' + escHtml(curMomStr) + (typeof pIdx === 'number' && hasValidAnchor ? ' · Paragraph ' + (pIdx + 1) : '') + '</span>' +
        '</div>' +
        '<div class="subbar-right">' +
        (hasValidAnchor
            ? '<button type="button" class="jump-moment-btn" id="btnJumpToMoment">Jump to moment &darr;</button>'
            : '<button type="button" class="jump-moment-btn" id="btnJumpToMoment" disabled title="Source reference unverified in current text" style="opacity:0.5; cursor:not-allowed;">Unresolved reference</button>') +
        '</div>' +
        '</div>';

    var inlineStripProgress = isGeneratingCurrent
        ? '<div class="beatmap-inline-progress-wrap" style="padding:4px 16px; background:var(--surface-card); border-bottom:1px solid var(--border);">' +
          '<div class="beatmap-progress-bar-wrap" style="height:3px; margin-bottom:4px;">' +
          '<div class="beatmap-progress-bar-fill" style="width:' + stageInfo.percent + '%;"></div>' +
          '</div>' +
          '<div class="beatmap-progress-label" style="font-size:10.5px;">' +
          '<span class="beatmap-progress-stage" style="color:var(--text-main); font-weight:500;"><span class="beatmap-pulse-dot" style="margin-right:5px;"></span>' + escHtml(stageInfo.stage) + '</span>' +
          '<span class="beatmap-progress-time" style="font-family:var(--font-mono, monospace); color:var(--text-muted);">' + formatElapsed(elapsedSec) + '</span>' +
          '</div>' +
          '</div>'
        : '';

    container.innerHTML =
        '<div class="beat-strip-horizontal">' +
        controlBar +
        inlineStripProgress +
        tensionRow +
        cardsViewport +
        subBar +
        '</div>';

    // Scroll active card into view in horizontal scroller
    if (!_beatMapIsZoomed) {
        var activeCard = container.querySelector('.beat-nav-card.selected');
        if (activeCard && typeof activeCard.scrollIntoView === 'function') {
            activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
        }
    } else {
        var activeMomentCard = container.querySelector('.moment-item-card.active-moment');
        if (activeMomentCard && typeof activeMomentCard.scrollIntoView === 'function') {
            activeMomentCard.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
        }
    }

    // Attach event listeners
    var closeBtn = container.querySelector('#stripCloseBtn');
    if (closeBtn) closeBtn.onclick = function () { hideHorizontalStrip(); };

    var btnPrev = container.querySelector('#stepperPrev');
    if (btnPrev) btnPrev.onclick = function () { stepMoment(-1); };

    var btnNext = container.querySelector('#stepperNext');
    if (btnNext) btnNext.onclick = function () { stepMoment(1); };

    var updateBtn = container.querySelector('#stripUpdateBtn');
    var activeAgentSel = container.querySelector('#stripActiveAgent');
    if (updateBtn) updateBtn.onclick = function () {
        if (activeAgentSel) {
            _beatMapAgent = activeAgentSel.value;
            try { localStorage.setItem('proseview_beatmap_agent', _beatMapAgent); } catch (e) { }
        }
        updateSceneBeatMap();
    };

    bindDeleteHandler(container.querySelector('#stripDeleteContainer'), _beatMapCurrentScene);

    var returnAllBtn = container.querySelector('#btnReturnAllBeats');
    if (returnAllBtn) returnAllBtn.onclick = function () {
        _beatMapIsZoomed = false;
        renderHorizontalStrip();
    };

    var jumpBtn = container.querySelector('#btnJumpToMoment');
    if (jumpBtn) jumpBtn.onclick = function () { jumpToActiveMoment(); };

    container.querySelectorAll('.curve-node').forEach(function (node) {
        node.onclick = function () {
            var order = parseInt(node.dataset.beatOrder, 10);
            selectBeat(order, false);
        };
    });

    container.querySelectorAll('.pacing-segment').forEach(function (seg) {
        seg.onclick = function () {
            var order = parseInt(seg.dataset.beatOrder, 10);
            selectBeat(order, false);
        };
    });

    bindDotTooltips(container);

    container.querySelectorAll('.beat-nav-card').forEach(function (card) {
        card.onclick = function () {
            var order = parseInt(card.dataset.beatOrder, 10);
            selectBeat(order, false);
        };
        card.ondblclick = function (e) {
            e.stopPropagation();
            var order = parseInt(card.dataset.beatOrder, 10);
            selectBeat(order, true);
        };
        var arrow = card.querySelector('.card-arrow');
        if (arrow) {
            arrow.onclick = function (e) {
                e.stopPropagation();
                var order = parseInt(card.dataset.beatOrder, 10);
                selectBeat(order, true);
            };
        }
    });

    container.querySelectorAll('.moment-item-card').forEach(function (card) {
        card.onclick = function () {
            var order = parseInt(card.dataset.momentOrder, 10);
            selectMoment(order);
        };
    });

    // Guard against horizontal trackpad overscroll triggering browser back/forward history navigation
    if (!container.dataset.overscrollGuarded) {
        container.dataset.overscrollGuarded = 'true';
        container.addEventListener('wheel', function (e) {
            var targetScrollRow = e.target.closest ? (e.target.closest('.moments-scroll-row') || e.target.closest('.beat-cards-overview')) : null;
            if (targetScrollRow) {
                if (e.deltaX < 0 && targetScrollRow.scrollLeft <= 0) {
                    e.preventDefault();
                } else if (e.deltaX > 0 && (targetScrollRow.scrollLeft + targetScrollRow.clientWidth >= targetScrollRow.scrollWidth - 1)) {
                    e.preventDefault();
                }
                return;
            }
            if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
                e.preventDefault();
            }
        }, { passive: false });
    }
}

// ── Right Panel Dock Tab View ─────────────────────────────────────────
function renderSceneBeatMapPane() {
    var pane = document.getElementById('sceneBeatMapPane');
    if (!pane) return;
    if (!_beatMapCurrentScene && typeof paths !== 'undefined' && typeof curIdx !== 'undefined' && paths[curIdx]) {
        _beatMapCurrentScene = paths[curIdx];
    }

    var isGeneratingCurrent = (_beatMapUpdatingScene !== null && _beatMapUpdatingScene === _beatMapCurrentScene);
    var elapsedSec = isGeneratingCurrent ? Math.max(0, Math.floor((Date.now() - _beatMapGenerateStartedAt) / 1000)) : 0;
    var stageInfo = isGeneratingCurrent ? getGenerationStageInfo(elapsedSec, _beatMapGenerateStatus, _beatMapAgent) : null;

    if (!_beatMapData || !_beatMapData.beats || !_beatMapData.beats.length) {
        var emptyToggleBtn =
            '<div style="display:inline-flex; align-items:center; gap:6px;">' +
            '<button type="button" class="beatmap-toggle-strip-btn' + (isHorizontalStripVisible() ? ' active' : '') + '" id="emptyPaneToggleStripBtn" title="Toggle horizontal timeline strip at top of scene">' +
            '<span>⬌</span> Top Strip' +
            '</button>' +
            '<button type="button" class="beatmap-toggle-strip-btn" id="emptyPaneSettingsBtn" title="Beat Map settings">' +
            '⚙ Settings' +
            '</button>' +
            '</div>';

        var emptyHeaderHtml =
            '<div class="beatmap-dock-header">' +
            '<div style="display:flex; align-items:center; gap:8px;">' +
            '<span style="font-weight:600; font-size:12px; color:var(--text-main);">Scene Beat Map</span>' +
            (isGeneratingCurrent
                ? '<span class="status-saved-tag" style="font-size:10.5px; color:var(--text-muted);"><span class="beatmap-pulse-dot"></span> Generating… <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span></span>'
                : '<span class="status-saved-tag" style="font-size:10.5px; color:var(--text-muted);"><span class="status-dot stale"></span> Not generated</span>') +
            '</div>' +
            emptyToggleBtn +
            '</div>';

        var progressPanelHtml = isGeneratingCurrent
            ? '<div class="beatmap-progress-panel" id="beatmapProgressPanel">' +
              '<div class="beatmap-progress-bar-wrap">' +
              '<div class="beatmap-progress-bar-fill" style="width:' + stageInfo.percent + '%;"></div>' +
              '</div>' +
              '<div class="beatmap-progress-label">' +
              '<span class="beatmap-progress-stage">' + escHtml(stageInfo.stage) + '</span>' +
              '<span class="beatmap-progress-time">' + formatElapsed(elapsedSec) + '</span>' +
              '</div>' +
              '<div class="beatmap-progress-subtext">' +
              '<span class="beatmap-pulse-dot"></span> ' + escHtml(stageInfo.subtext) +
              '</div>' +
              '</div>'
            : '';

        var emptyHeroHtml =
            '<div class="beatmap-empty-state">' +
            '<div class="beatmap-empty-hero' + (isGeneratingCurrent ? ' is-generating' : '') + '">' +
            '<svg class="beatmap-empty-wave" viewBox="0 0 280 40">' +
            '<line x1="10" y1="34" x2="270" y2="34" stroke="var(--border)" stroke-width="1" stroke-dasharray="3 3"/>' +
            '<path d="M 20 28 Q 70 24 120 16 T 190 8 T 260 22" fill="none" stroke="var(--primary, #dd635f)" stroke-width="1.8" stroke-linecap="round" opacity="0.85"/>' +
            '<circle cx="20" cy="28" r="3" fill="var(--surface-card)" stroke="var(--border)" stroke-width="1.5"/>' +
            '<circle cx="70" cy="24" r="3" fill="var(--surface-card)" stroke="var(--border)" stroke-width="1.5"/>' +
            '<circle cx="120" cy="16" r="3.5" fill="var(--surface-card)" stroke="var(--border)" stroke-width="1.5"/>' +
            '<circle cx="190" cy="8" r="4.5" fill="var(--primary, #dd635f)"/>' +
            '<circle cx="260" cy="22" r="3" fill="var(--surface-card)" stroke="var(--border)" stroke-width="1.5"/>' +
            '</svg>' +
            '<div class="beatmap-empty-title">Visual Beat Progression</div>' +
            '<div class="beatmap-empty-desc">' +
            'Map narrative trajectory, dramatic tension, and sequential dialogue and moments across this scene without reading the entire text.' +
            '</div>' +
            progressPanelHtml +
            '<div class="beatmap-empty-ghosts">' +
            '<div class="beatmap-ghost-row"><span>BEAT 1 &bull; Opening</span><span>Tension 25%</span></div>' +
            '<div class="beatmap-ghost-row"><span>BEAT 2 &bull; Complication</span><span>Tension 60%</span></div>' +
            '<div class="beatmap-ghost-row"><span>BEAT 3 &bull; Turning point</span><span style="color:var(--primary, #dd635f); font-weight:700;">Tension 95%</span></div>' +
            '</div>' +
            '<div class="beatmap-action-group">' +
            '<select id="paneAgentSelect" class="beatmap-agent-picker"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
            '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
            '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
            '</select>' +
            '<button type="button" class="beatmap-generate-btn' + (isGeneratingCurrent ? ' is-generating' : '') + '" id="paneGenerateBtn"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
            (isGeneratingCurrent
                ? '<span class="beatmap-spinner"></span> Generating… <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span>'
                : '↻ Generate Beat Map') +
            '</button>' +
            '</div>' +
            '<div class="beatmap-empty-footnote">Generated on demand &bull; Stored locally with revision hash</div>' +
            '</div>' +
            '</div>';

        pane.innerHTML = emptyHeaderHtml + emptyHeroHtml;

        var emptyToggle = pane.querySelector('#emptyPaneToggleStripBtn');
        if (emptyToggle) emptyToggle.onclick = function () { toggleHorizontalStrip(); };
        var emptySettings = pane.querySelector('#emptyPaneSettingsBtn');
        if (emptySettings) emptySettings.onclick = function () { if (typeof openBeatMapSettings === 'function') openBeatMapSettings(); };

        var genBtn = pane.querySelector('#paneGenerateBtn');
        var agentSel = pane.querySelector('#paneAgentSelect');
        if (genBtn) genBtn.onclick = function () {
            if (agentSel) {
                _beatMapAgent = agentSel.value;
                try { localStorage.setItem('proseview_beatmap_agent', _beatMapAgent); } catch (e) { }
            }
            updateSceneBeatMap();
        };
        return;
    }

    var beats = _beatMapData.beats;
    var activeBeat = getActiveBeat();
    var statusDotCls = 'status-dot' + (_beatMapStale ? ' stale' : '');
    var statusLabel = _beatMapStale ? 'Outdated • Scene edited' : 'Saved';

    // 1. Pane Header
    var isStripOn = isHorizontalStripVisible();
    var stripToggleBtn =
        '<div style="display:inline-flex; align-items:center; gap:6px;">' +
        '<button type="button" class="beatmap-toggle-strip-btn' + (isStripOn ? ' active' : '') + '" id="paneToggleStripBtn" title="Toggle horizontal timeline strip at top of scene">' +
        '<span>⬌</span> Top Strip' +
        '</button>' +
        '<button type="button" class="beatmap-toggle-strip-btn" id="paneSettingsBtn" title="Beat Map settings">' +
        '⚙ Settings' +
        '</button>' +
        '</div>';

    var headerHtml =
        '<div class="beatmap-dock-header">' +
        '<div style="display:flex; align-items:center; gap:8px;">' +
        '<span style="font-weight:600; font-size:12px; color:var(--text-main);">Scene Beat Map</span>' +
        (isGeneratingCurrent
            ? '<span class="status-saved-tag" style="font-size:10.5px; color:var(--text-muted);"><span class="beatmap-pulse-dot"></span> Updating… <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span></span>'
            : '<span class="status-saved-tag" style="font-size:10.5px; color:var(--text-muted);"><span class="' + statusDotCls + '"></span> ' + statusLabel + '</span>') +
        '</div>' +
        stripToggleBtn +
        '</div>';

    // 2. Control Toolbar
    var toolbarHtml =
        '<div style="padding:6px 14px; border-bottom:1px solid var(--border); background:var(--bg-app); display:flex; justify-content:space-between; align-items:center;">' +
        '<div style="display:inline-flex; align-items:center; gap:4px; font-size:11px;">' +
        '<span style="color:var(--text-muted);">Agent:</span>' +
        '<select id="paneActiveAgent" class="beat-agent-select" style="background:var(--surface-field); border:1px solid var(--border); border-radius:3px; padding:2px 4px;"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
        '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
        '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
        '</select>' +
        '</div>' +
        '<div style="display:inline-flex; align-items:center; gap:6px;">' +
        '<button type="button" class="strip-btn' + (isGeneratingCurrent ? ' is-generating' : '') + '" id="paneUpdateBtn"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
        (isGeneratingCurrent
            ? '<span class="beatmap-spinner subtle"></span> Updating… <span class="beatmap-btn-elapsed">' + formatElapsed(elapsedSec) + '</span>'
            : '↻ Update') +
        '</button>' +
        (!isGeneratingCurrent ? '<div id="paneDeleteContainer" style="display:inline-flex; align-items:center;"></div>' : '') +
        '</div>' +
        '</div>' +
        (isGeneratingCurrent
            ? '<div class="beatmap-inline-progress-wrap" style="padding:6px 14px; background:color-mix(in srgb, var(--surface-card) 60%, var(--bg-app, #18191c)); border-bottom:1px solid var(--border);">' +
              '<div class="beatmap-progress-bar-wrap" style="height:4px; margin-bottom:5px;">' +
              '<div class="beatmap-progress-bar-fill" style="width:' + stageInfo.percent + '%;"></div>' +
              '</div>' +
              '<div class="beatmap-progress-label" style="font-size:10.5px;">' +
              '<span class="beatmap-progress-stage" style="color:var(--text-main); font-weight:500;"><span class="beatmap-pulse-dot" style="margin-right:5px;"></span>' + escHtml(stageInfo.stage) + '</span>' +
              '<span class="beatmap-progress-time" style="font-family:var(--font-mono, monospace); color:var(--text-muted);">' + formatElapsed(elapsedSec) + '</span>' +
              '</div>' +
              '</div>'
            : '');

    // 3. Tension Curve
    var peakBeat = beats.length ? beats.reduce(function (max, b) {
        return (b.estimated_tension || 0) > (max.estimated_tension || 0) ? b : max;
    }, beats[0]) : null;
    var peakBeatOrder = peakBeat ? (parseInt(peakBeat.order, 10) || 1) : 1;
    var peakCaption = peakBeat ? ('Peak: Beat ' + peakBeatOrder) : 'Dramatic Tension';
    var tensionHtml =
        '<div class="tension-curve-row" style="padding:8px 14px 4px; border-bottom:1px solid var(--border);">' +
        '<div class="tension-curve-header">' +
        renderTensionInfoTooltip() +
        '<span class="tension-peak-caption">' + escHtml(peakCaption) + '</span>' +
        '</div>' +
        renderTensionCurveSvg(beats, activeBeat ? activeBeat.order : 1) +
        renderPacingBarHtml(beats, activeBeat ? activeBeat.order : 1) +
        '<div class="tension-dot-tooltip" role="tooltip" aria-hidden="true"></div>' +
        '</div>';

    // 4. Beat Groups & Moments Walkthrough
    var prevScrollDiv = pane.querySelector('#beatmapDockScroll');
    var savedScroll = prevScrollDiv ? prevScrollDiv.scrollTop : 0;

    var groupsHtml = beats.map(function (b) {
        var bOrder = parseInt(b.order, 10) || 1;
        var isSelected = (activeBeat && bOrder === (parseInt(activeBeat.order, 10) || 1));
        var isCollapsed = !!_beatMapCollapsedBeats[bOrder];
        var cls = 'sidebar-beat-group' + (isSelected ? ' selected' : '');
        var tpBadge = b.is_turning_point ? '<span class="turning-point-badge">Turning point</span>' : '';

        var collapseIcon = (isSelected && !isCollapsed) ? '&#9662;' : '&#9656;';
        var collapseTitle = (isSelected && !isCollapsed) ? 'Collapse moments' : 'Expand moments';
        var collapseBtn = '<button type="button" class="beat-collapse-btn" data-beat-order="' + escHtml(String(bOrder)) + '" title="' + collapseTitle + '" aria-label="' + collapseTitle + '">' + collapseIcon + '</button>';

        var momentsHtml = '';
        if (isSelected && !isCollapsed) {
            var items = (b.moments || []).map(function (m) {
                var mOrder = parseInt(m.order, 10) || 1;
                var isActive = (mOrder === _beatMapSelectedMoment);
                var mCls = 'sidebar-moment-card' + (isActive ? ' active-sidebar-moment' : '');
                var speakerHtml = m.speaker ? '<strong style="color:var(--text-main); font-size:11px;">' + escHtml(m.speaker) + ':</strong> ' : '';
                var quote = (m.source_ref && m.source_ref.exact_quote) ? m.source_ref.exact_quote : m.text;
                var sType = safeMomentType(m.type);
                var isAnchorValid = isMomentAnchorValid(m);
                var unverifiedBadge = !isAnchorValid ? ' <span style="font-size:9.5px; opacity:0.65; color:var(--text-muted);">(unverified)</span>' : '';
                return '<div class="' + mCls + '" data-moment-order="' + escHtml(String(mOrder)) + '"' + (!isAnchorValid ? ' data-unverified="true"' : '') + '>' +
                    '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:3px;">' +
                    '<span style="font-family:var(--font-mono); font-size:10px; font-weight:700; color:var(--text-muted);">#' + escHtml(mOrder.toString().padStart(2, '0')) + unverifiedBadge + '</span>' +
                    '<span class="moment-type-tag type-' + sType + '">' + escHtml(sType.replace(/_/g, ' ')) + '</span>' +
                    '</div>' +
                    '<div style="font-size:11px; line-height:1.35; color:var(--text-main); font-style:italic;">' +
                    speakerHtml + quotedMoment(quote) +
                    '</div>' +
                    '</div>';
            }).join('');

            momentsHtml = '<div class="sidebar-moments-list">' + items + '</div>';
        }

        return '<div class="' + cls + '">' +
            '<div class="sidebar-beat-header" data-beat-order="' + escHtml(String(bOrder)) + '">' +
            '<div style="display:flex; justify-content:space-between; align-items:center;">' +
            '<div style="display:inline-flex; align-items:center; gap:6px;">' +
            '<span class="beat-color-dot" style="background:' + getBeatColor(bOrder) + ';"></span>' +
            '<span style="font-family:var(--font-mono); font-size:10px; font-weight:700; color:' + (isSelected ? 'var(--primary)' : 'var(--text-muted)') + ';">BEAT ' + escHtml(String(bOrder)) + '</span>' +
            tpBadge +
            '</div>' +
            collapseBtn +
            '</div>' +
            '<div style="font-size:12px; font-weight:600; color:var(--text-main);">' + escHtml(b.title) + '</div>' +
            '<div style="font-size:11px; color:var(--text-muted); line-height:1.3;">' + escHtml(b.summary) + '</div>' +
            '</div>' +
            momentsHtml +
            '</div>';
    }).join('');

    pane.innerHTML =
        headerHtml +
        toolbarHtml +
        tensionHtml +
        '<div id="beatmapDockScroll" style="padding:12px 14px; overflow-y:auto; flex:1;">' + groupsHtml + '</div>';

    var newScrollDiv = pane.querySelector('#beatmapDockScroll');
    if (newScrollDiv) {
        newScrollDiv.scrollTop = savedScroll;
    }

    // Attach listeners
    var toggleStrip = pane.querySelector('#paneToggleStripBtn');
    if (toggleStrip) toggleStrip.onclick = function () { toggleHorizontalStrip(); };
    var paneSettings = pane.querySelector('#paneSettingsBtn');
    if (paneSettings) paneSettings.onclick = function () { if (typeof openBeatMapSettings === 'function') openBeatMapSettings(); };

    var updateBtn = pane.querySelector('#paneUpdateBtn');
    var activeAgentSel = pane.querySelector('#paneActiveAgent');
    if (updateBtn) updateBtn.onclick = function () {
        if (activeAgentSel) {
            _beatMapAgent = activeAgentSel.value;
            try { localStorage.setItem('proseview_beatmap_agent', _beatMapAgent); } catch (e) { }
        }
        updateSceneBeatMap();
    };

    bindDeleteHandler(pane.querySelector('#paneDeleteContainer'), _beatMapCurrentScene);

    pane.querySelectorAll('.curve-node').forEach(function (node) {
        node.onclick = function () {
            var order = parseInt(node.dataset.beatOrder, 10);
            selectBeat(order, false);
        };
    });

    pane.querySelectorAll('.pacing-segment').forEach(function (seg) {
        seg.onclick = function () {
            var order = parseInt(seg.dataset.beatOrder, 10);
            selectBeat(order, false);
        };
    });

    pane.querySelectorAll('.beat-collapse-btn').forEach(function (btn) {
        btn.onclick = function (e) {
            e.stopPropagation();
            var order = parseInt(btn.dataset.beatOrder, 10);
            if (_beatMapSelectedBeat !== order) {
                _beatMapSelectedBeat = order;
                _beatMapCollapsedBeats[order] = false;
            } else {
                _beatMapCollapsedBeats[order] = !_beatMapCollapsedBeats[order];
            }
            renderSceneBeatMapPane();
        };
    });

    pane.querySelectorAll('.sidebar-beat-header').forEach(function (hdr) {
        hdr.onclick = function (e) {
            if (e && e.target && e.target.closest && e.target.closest('.beat-collapse-btn')) return;
            var order = parseInt(hdr.dataset.beatOrder, 10);
            if (_beatMapSelectedBeat === order && !_beatMapCollapsedBeats[order]) {
                _beatMapCollapsedBeats[order] = true;
                renderSceneBeatMapPane();
            } else {
                selectBeat(order, false);
            }
        };
    });

    pane.querySelectorAll('.sidebar-moment-card').forEach(function (card) {
        card.onclick = function () {
            var order = parseInt(card.dataset.momentOrder, 10);
            selectMoment(order);
        };
    });

    bindDotTooltips(pane);
}

function updateBeatMapState(data) {
    if (!data) return;
    var bm = data.beatmap || data;
    if (bm && bm.beats) {
        clearGenerationTimers();
        _beatMapGenerateStatus = null;
        _beatMapGenerateStartedAt = 0;
        _beatMapUpdatingScene = null;
        _beatMapIsUpdating = false;
        // Drop updates if they target another scene than the one currently open
        if (bm.scene_path && _beatMapCurrentScene && bm.scene_path !== _beatMapCurrentScene) {
            return;
        }
        _beatMapData = bm;
        _beatMapStale = !!data.stale;
        syncStaleIndicator();
        renderCurrentPlacement();
    }
}

// Expose functions globally for Proseview integration
window.loadSceneBeatMap = loadSceneBeatMap;
window.updateBeatMapState = updateBeatMapState;
window.renderSceneBeatMapPane = renderSceneBeatMapPane;
window.renderHorizontalStrip = renderHorizontalStrip;
window.showHorizontalStrip = showHorizontalStrip;
window.hideHorizontalStrip = hideHorizontalStrip;
window.toggleHorizontalStrip = toggleHorizontalStrip;
window.switchBeatMapPlacement = switchBeatMapPlacement;
window.toggleBeatMapPlacement = toggleBeatMapPlacement;
window.selectBeat = selectBeat;
window.selectMoment = selectMoment;
window.jumpToActiveMoment = jumpToActiveMoment;
window.deleteSceneBeatMap = deleteSceneBeatMap;
window.getBeatMapData = function () { return _beatMapData; };

window.addEventListener('beatmap-deleted', function (evt) {
    if (!evt || !evt.detail) return;
    var target = evt.detail.scene_path;
    if (target && target === _beatMapCurrentScene) {
        clearGenerationTimers();
        _beatMapData = null;
        _beatMapStale = false;
        _beatMapUpdatingScene = null;
        _beatMapIsUpdating = false;
        syncStaleIndicator();
        renderCurrentPlacement();
    }
});

window.addEventListener('beatmap-generating', function (evt) {
    if (!evt || !evt.detail) return;
    var target = evt.detail.scene_path;
    if (!target) return;
    var isCurrent = (_beatMapCurrentScene && target === _beatMapCurrentScene);
    _beatMapUpdatingScene = target;
    _beatMapIsUpdating = isCurrent;
    _beatMapGenerateStartedAt = Date.now();
    _beatMapGenerateStatus = null;
    if (evt.detail.agent) {
        _beatMapAgent = evt.detail.agent;
    }
    startGenerationTimers(target);
    if (isCurrent) {
        renderCurrentPlacement();
    }
});

window.addEventListener('beatmap-generation-failed', function (evt) {
    if (!evt || !evt.detail) return;
    if (!_beatMapUpdatingScene || evt.detail.scene_path === _beatMapUpdatingScene) {
        clearGenerationTimers();
        _beatMapGenerateStatus = null;
        _beatMapGenerateStartedAt = 0;
        _beatMapUpdatingScene = null;
        _beatMapIsUpdating = false;
        renderCurrentPlacement();
    }
});

window.addEventListener('beatmap-updated', function (evt) {
    if (evt && evt.detail) {
        updateBeatMapState(evt.detail);
    }
});

// Close moments view and return to all beats on Escape key
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && _beatMapIsZoomed) {
        e.preventDefault();
        e.stopPropagation();
        _beatMapIsZoomed = false;
        renderHorizontalStrip();
    }
}, true);

// Auto-load on initial boot / refresh if a scene is open in modal or URL hash
function initOnBoot() {
    var currentPath = null;
    if (typeof paths !== 'undefined' && typeof curIdx !== 'undefined' && curIdx >= 0 && paths[curIdx]) {
        currentPath = paths[curIdx];
    } else if (window.location.hash) {
        var match = window.location.hash.match(/^#\/scene\/(.+)$/);
        if (match) {
            try { currentPath = decodeURIComponent(match[1]); } catch (e) { currentPath = match[1]; }
        }
    }
    if (currentPath) {
        loadSceneBeatMap(currentPath);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOnBoot);
} else {
    setTimeout(initOnBoot, 50);
}
}) ();
