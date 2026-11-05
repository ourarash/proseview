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
                    alert('Beat map generation failed: ' + (data.error || 'unknown error'));
                    renderCurrentPlacement();
                }
            })
            .catch(function (err) {
                if (_beatMapUpdatingScene === generatingScene) {
                    _beatMapUpdatingScene = null;
                }
                _beatMapIsUpdating = (_beatMapUpdatingScene !== null && _beatMapUpdatingScene === _beatMapCurrentScene);
                if (opSeq !== _beatMapOpSeq || generatingScene !== _beatMapCurrentScene) {
                    renderCurrentPlacement();
                    return;
                }
                alert('Beat map request failed: ' + (err.message || err));
                renderCurrentPlacement();
            });
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

    function findProseParagraph(paraIdx, exactQuote, validAnchor) {
        if (validAnchor === false) return null;
        var host = document.getElementById('sceneProseHost');
        if (!host) return null;
        var root = host.querySelector('.ProseMirror');
        if (!root) return null;

        // 1. Gather only text paragraphs (<p>), strictly ignoring headings, annotations, and widgets
        var pElements = [];
        for (var i = 0; i < root.children.length; i++) {
            var child = root.children[i];
            if (child.tagName === 'P') {
                pElements.push(child);
            }
        }

        var cleanQuote = exactQuote ? exactQuote.replace(/^[“”"'\s]+|[“”"'\s]+$/g, '').slice(0, 30) : '';

        // 2. If paraIdx is valid and matches the quote (or quote is empty), return it directly
        if (typeof paraIdx === 'number' && paraIdx >= 0 && paraIdx < pElements.length) {
            var candidate = pElements[paraIdx];
            if (!cleanQuote) return candidate;
            var normCand = candidate.textContent.replace(/["“”]/g, '"');
            var normQ = cleanQuote.replace(/["“”]/g, '"');
            if (normCand.indexOf(normQ) !== -1) {
                return candidate;
            }
        }

        // 3. If index shifted, search all <p> elements for the quote
        if (cleanQuote && cleanQuote.length >= 4) {
            var normSearch = cleanQuote.replace(/["“”]/g, '"');
            for (var j = 0; j < pElements.length; j++) {
                var normText = pElements[j].textContent.replace(/["“”]/g, '"');
                if (normText.indexOf(normSearch) !== -1) {
                    return pElements[j];
                }
            }
        }

        // 4. Fallback ONLY if there was NO quote specified and validAnchor is not false.
        // If an exactQuote was provided but cannot be found in the manuscript,
        // do not fall back to an arbitrary paragraph index (prevents highlighting unrelated prose).
        if (!cleanQuote && typeof paraIdx === 'number' && paraIdx >= 0 && paraIdx < pElements.length) {
            return pElements[paraIdx];
        }

        return null;
    }

    function syncProseHighlight(moment) {
        if (!moment) return;
        if (!isMomentAnchorValid(moment)) {
            // Anchor is marked invalid/unresolved - do not jump to or highlight unrelated prose
            return;
        }
        var sourceRef = moment.source_ref;
        if (!sourceRef) return;
        var paraIdx = sourceRef.paragraph;
        if (typeof paraIdx !== 'number') return;
        var quote = sourceRef.exact_quote ? sourceRef.exact_quote.trim() : '';
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
        var cleanSearch = searchText.replace(/^[“”"'\s]+|[“”"'\s]+$/g, '');
        if (!cleanSearch || cleanSearch.length < 3) return;

        var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
        var node;
        while ((node = walker.nextNode())) {
            var idx = node.nodeValue.indexOf(cleanSearch);
            if (idx === -1) {
                // Try normalised quote marks
                var normText = node.nodeValue.replace(/["“”]/g, '"');
                var normSearch = cleanSearch.replace(/["“”]/g, '"');
                idx = normText.indexOf(normSearch);
            }
            if (idx !== -1) {
                var range = document.createRange();
                range.setStart(node, idx);
                range.setEnd(node, idx + cleanSearch.length);
                var span = document.createElement('span');
                span.className = 'moment-active-highlight';
                range.surroundContents(span);
                break;
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

    if (!_beatMapData || !_beatMapData.beats || !_beatMapData.beats.length) {
        container.innerHTML =
            '<div class="beat-strip-horizontal">' +
            '<div class="strip-control-bar">' +
            '<div class="strip-status-left">' +
            '<span class="status-saved-tag"><span class="status-dot stale"></span> Beat map not generated</span>' +
            '</div>' +
            '<div class="strip-controls-right">' +
            '<div style="display:inline-flex; align-items:center; gap:6px;">' +
            '<select id="stripAgentSelect" class="beatmap-agent-picker" style="font-size:11px; padding:2px 6px;">' +
            '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
            '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
            '</select>' +
            '<button type="button" class="beatmap-generate-btn" id="stripGenerateBtn" style="font-size:11px; padding:3px 10px;"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
            (isGeneratingCurrent ? 'Generating…' : '↻ Generate Beat Map') +
            '</button>' +
            '</div>' +
            '<button type="button" class="strip-close-btn" id="emptyStripCloseBtn" title="Close horizontal beat strip">✕</button>' +
            '</div>' +
            '</div>' +
            '<div class="strip-cards-viewport" style="align-items:center; justify-content:center;">' +
            '<div style="display:flex; align-items:center; gap:16px; background:var(--surface-card); border:1px dashed var(--border); border-radius:6px; padding:10px 18px; max-width:650px;">' +
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
            '</div>' +
            '</div>' +
            '<div class="scene-text-subbar">' +
            '<div class="subbar-left">' +
            '<span class="subbar-scene-label">Scene text</span>' +
            '<span class="subbar-crumb">Awaiting beat map generation</span>' +
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
        '<span class="status-saved-tag"><span class="' + statusDotCls + '"></span> ' + statusLabel + '</span>' +
        '</div>' +
        '<div class="strip-controls-right">' +
        '<div class="moment-stepper">' +
        '<button type="button" class="stepper-btn" id="stepperPrev" title="Previous moment">&lt;</button>' +
        '<span>' + counterText + '</span>' +
        '<button type="button" class="stepper-btn" id="stepperNext" title="Next moment">&gt;</button>' +
        '</div>' +
        '<div style="display:inline-flex; align-items:center; background:var(--surface-field); border:1px solid var(--border); border-radius:4px; padding:1px 6px;">' +
        '<select id="stripActiveAgent" class="beat-agent-select">' +
        '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
        '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
        '</select>' +
        '<button type="button" class="strip-btn" id="stripUpdateBtn" style="border:0; padding:2px 4px;">' +
        (isGeneratingCurrent ? 'Updating…' : '↻ Update') +
        '</button>' +
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
                '<div class="moment-quote">“' + escHtml(quoteText) + '”</div>' +
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

    container.innerHTML =
        '<div class="beat-strip-horizontal">' +
        controlBar +
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

    if (!_beatMapData || !_beatMapData.beats || !_beatMapData.beats.length) {
        var emptyToggleBtn =
            '<button type="button" class="beatmap-toggle-strip-btn' + (isHorizontalStripVisible() ? ' active' : '') + '" id="emptyPaneToggleStripBtn" title="Toggle horizontal timeline strip at top of scene">' +
            '<span>⬌</span> Top Strip' +
            '</button>';

        var emptyHeaderHtml =
            '<div class="beatmap-dock-header">' +
            '<div style="display:flex; align-items:center; gap:8px;">' +
            '<span style="font-weight:600; font-size:12px; color:var(--text-main);">Scene Beat Map</span>' +
            '<span class="status-saved-tag" style="font-size:10.5px; color:var(--text-muted);"><span class="status-dot stale"></span> Not generated</span>' +
            '</div>' +
            emptyToggleBtn +
            '</div>';

        var emptyHeroHtml =
            '<div class="beatmap-empty-state">' +
            '<div class="beatmap-empty-hero">' +
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
            '<div class="beatmap-empty-ghosts">' +
            '<div class="beatmap-ghost-row"><span>BEAT 1 &bull; Opening</span><span>Tension 25%</span></div>' +
            '<div class="beatmap-ghost-row"><span>BEAT 2 &bull; Complication</span><span>Tension 60%</span></div>' +
            '<div class="beatmap-ghost-row"><span>BEAT 3 &bull; Turning point</span><span style="color:var(--primary, #dd635f); font-weight:700;">Tension 95%</span></div>' +
            '</div>' +
            '<div class="beatmap-action-group">' +
            '<select id="paneAgentSelect" class="beatmap-agent-picker">' +
            '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
            '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
            '</select>' +
            '<button type="button" class="beatmap-generate-btn" id="paneGenerateBtn"' + (isGeneratingCurrent ? ' disabled' : '') + '>' +
            (isGeneratingCurrent ? 'Generating…' : '↻ Generate Beat Map') +
            '</button>' +
            '</div>' +
            '<div class="beatmap-empty-footnote">Generated on demand &bull; Stored locally with revision hash</div>' +
            '</div>' +
            '</div>';

        pane.innerHTML = emptyHeaderHtml + emptyHeroHtml;

        var emptyToggle = pane.querySelector('#emptyPaneToggleStripBtn');
        if (emptyToggle) emptyToggle.onclick = function () { toggleHorizontalStrip(); };

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
        '<button type="button" class="beatmap-toggle-strip-btn' + (isStripOn ? ' active' : '') + '" id="paneToggleStripBtn" title="Toggle horizontal timeline strip at top of scene">' +
        '<span>⬌</span> Top Strip' +
        '</button>';

    var headerHtml =
        '<div class="beatmap-dock-header">' +
        '<div style="display:flex; align-items:center; gap:8px;">' +
        '<span style="font-weight:600; font-size:12px; color:var(--text-main);">Scene Beat Map</span>' +
        '<span class="status-saved-tag" style="font-size:10.5px; color:var(--text-muted);"><span class="' + statusDotCls + '"></span> ' + statusLabel + '</span>' +
        '</div>' +
        stripToggleBtn +
        '</div>';

    // 2. Control Toolbar
    var toolbarHtml =
        '<div style="padding:6px 14px; border-bottom:1px solid var(--border); background:var(--bg-app); display:flex; justify-content:space-between; align-items:center;">' +
        '<div style="display:inline-flex; align-items:center; gap:4px; font-size:11px;">' +
        '<span style="color:var(--text-muted);">Agent:</span>' +
        '<select id="paneActiveAgent" class="beat-agent-select" style="background:var(--surface-field); border:1px solid var(--border); border-radius:3px; padding:2px 4px;">' +
        '<option value="claude"' + (_beatMapAgent === 'claude' ? ' selected' : '') + '>Claude CLI</option>' +
        '<option value="codex"' + (_beatMapAgent === 'codex' ? ' selected' : '') + '>Codex CLI</option>' +
        '</select>' +
        '</div>' +
        '<button type="button" class="strip-btn" id="paneUpdateBtn">' +
        (isGeneratingCurrent ? 'Updating…' : '↻ Update') +
        '</button>' +
        '</div>';

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
                    speakerHtml + '“' + escHtml(quote) + '”' +
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

    var updateBtn = pane.querySelector('#paneUpdateBtn');
    var activeAgentSel = pane.querySelector('#paneActiveAgent');
    if (updateBtn) updateBtn.onclick = function () {
        if (activeAgentSel) {
            _beatMapAgent = activeAgentSel.value;
            try { localStorage.setItem('proseview_beatmap_agent', _beatMapAgent); } catch (e) { }
        }
        updateSceneBeatMap();
    };

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
        hdr.onclick = function () {
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
        // Drop updates if they target another scene than the one currently open
        if (bm.scene_path && _beatMapCurrentScene && bm.scene_path !== _beatMapCurrentScene) {
            return;
        }
        _beatMapData = bm;
        _beatMapStale = !!data.stale;
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
window.getBeatMapData = function () { return _beatMapData; };

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
