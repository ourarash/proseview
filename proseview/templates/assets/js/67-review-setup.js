        // Scene passes share scope, context, and the same guide UI.
        // Lane choices are remembered separately for each pass and craft book.
        const DISCUSS_REVIEW_MODES = [
            {id: 'quick_critique', label: 'Quick critique', run: 'Run critique'},
            {id: 'deepen_and_layer', label: 'Deepen & layer', run: 'Run deepen & layer'},
            {id: 'craft_review', label: 'Craft review', run: 'Run craft review'},
            {id: 'comedy_review', label: 'Comedy review', tabLabel: 'Comedy', run: 'Run comedy review'}
        ];

        // One cap on revision priorities for every review card. Customize
        // changes it, and the choice is remembered; a card's Run now keeps the
        // default. Bird by Bird keeps one assignment.
        const DISCUSS_DEFAULT_MAX_FINDINGS = 5;
        const DISCUSS_MAX_FINDINGS_LIMIT = 20;
        const DISCUSS_MAX_FINDINGS_PREF = 'proseview-review-max-findings';

        function _readReviewMaxFindingsPref() {
            try {
                var saved = Number(localStorage.getItem(DISCUSS_MAX_FINDINGS_PREF));
                if (Number.isInteger(saved) && saved >= 1 && saved <= DISCUSS_MAX_FINDINGS_LIMIT) return saved;
            } catch (e) {}
            return DISCUSS_DEFAULT_MAX_FINDINGS;
        }

        // A separate Keep list of what works. Off unless the writer turns it on
        // in Customize; shared by every card that has one and remembered.
        const DISCUSS_INCLUDE_KEEP_PREF = 'proseview-review-include-keep';
        function _readReviewIncludeKeepPref() {
            try { return localStorage.getItem(DISCUSS_INCLUDE_KEEP_PREF) === 'on'; } catch (e) { return false; }
        }
        // Open critique lets the reviewer choose what matters most without the
        // rigid lane-by-lane template. Off unless enabled.
        const DISCUSS_OPEN_CRITIQUE_PREF = 'proseview-review-open-critique';
        function _readReviewOpenCritiquePref() {
            try { return localStorage.getItem(DISCUSS_OPEN_CRITIQUE_PREF) === 'on'; } catch (e) { return false; }
        }
        // Deepen offers opportunities only, and Bird by Bird's keep/assignment
        // format is the review itself.
        function discussReviewHasKeepChoice(id) {
            return id !== 'deepen_and_layer' && id !== 'craft_lamott';
        }
        function discussReviewHasOpenCritiqueChoice(id) {
            return id !== 'deepen_and_layer' && id !== 'craft_lamott';
        }

        function discussReviewMode() {
            return DISCUSS_REVIEW_MODES.find(function(mode) { return mode.id === _discussCraftState.modeId; }) || DISCUSS_REVIEW_MODES[2];
        }

        function discussReviewDefaultLens(modeId) {
            if (modeId === 'craft_review') {
                return DISCUSS_CRAFT_LENSES.find(function(lens) { return lens.id === _discussCraftState.lensId; }) || DISCUSS_CRAFT_LENSES[0];
            }
            return discussCraftLens(modeId);
        }

        function discussReviewCard(row, live) {
            var lens = discussReviewDefaultLens(row.id);
            var label = live.label || row.label;
            var card = elementWith('discuss-review-card');
            card.dataset.review = row.id;
            var run = document.createElement('button');
            run.type = 'button';
            run.className = 'discuss-story-action discuss-review-run';
            run.id = 'discussReviewRun-' + row.id;
            run.setAttribute('aria-label', 'Run ' + label + ' with defaults');
            var head = elementWith('discuss-review-card-head');
            head.append(elementWith('discuss-story-action-title', label), elementWith('discuss-review-card-run', 'Run now →'));
            var summary = 'This scene · ' + (row.id === 'craft_review' ? lens.label + ' · ' : '') + 'All lanes';
            if (row.id === 'comedy_review') summary += ' · Existing humor + new chances';
            run.title = 'Run now: ' + summary + (row.id === 'comedy_review' ? '. Follow the draft’s tone.' : '');
            run.append(head, elementWith('discuss-story-action-copy', live.description || row.copy), elementWith('discuss-review-card-defaults', summary));
            run.onclick = function() { runDiscussScenePass(row.id); };
            var customize = document.createElement('button');
            customize.type = 'button';
            customize.className = 'discuss-review-customize';
            customize.id = 'discussReviewCustomize-' + row.id;
            customize.setAttribute('aria-label', 'Customize ' + label);
            customize.textContent = 'Customize…';
            customize.onclick = function() { startDiscussCraftReview(row.id); };
            card.append(run, customize);
            return card;
        }

        function discussReviewHeading() {
            var head = elementWith('discuss-review-heading');
            head.appendChild(elementWith('discuss-story-group', 'Read this scene'));
            var info = reviewInfoButton('What gets sent with a quick review?', 'discuss-review-info-trigger', toggleDiscussReviewInfo);
            info.id = 'discussReviewInfoTrigger';
            info.setAttribute('aria-controls', 'discussReviewInfoPopover');
            info.setAttribute('aria-expanded', document.getElementById('discussReviewInfoPopover') ? 'true' : 'false');
            head.appendChild(info);
            return head;
        }

        function appendDiscussReviewCards(container, includeHeading) {
            if (includeHeading !== false) container.appendChild(discussReviewHeading());
            container.appendChild(elementWith('discuss-review-cards-help', 'Click a card to run. Customize for more control.'));
            container.appendChild(discussPassGroup(DISCUSS_SCENE_PASSES, runDiscussScenePass));
        }

        var _discussReviewInfoTriggerId = '';

        function _addReviewInfoRow(rows, label, value, explanation) {
            var row = elementWith('discuss-review-info-row');
            var term = document.createElement('dt'); term.textContent = label;
            var detail = document.createElement('dd');
            detail.appendChild(document.createTextNode(value));
            if (explanation) detail.appendChild(elementWith('discuss-review-info-note', explanation));
            row.append(term, detail); rows.appendChild(row);
        }

        function closeDiscussReviewInfo(restoreFocus) {
            var popover = document.getElementById('discussReviewInfoPopover');
            if (popover) popover.remove();
            var trigger = _discussReviewInfoTriggerId ? document.getElementById(_discussReviewInfoTriggerId) : null;
            if (trigger) {
                trigger.setAttribute('aria-expanded', 'false');
                if (restoreFocus) trigger.focus({preventScroll: true});
            }
            _discussReviewInfoTriggerId = '';
        }

        function renderDiscussReviewInfoContents(body, error) {
            body.replaceChildren();
            var rows = document.createElement('dl');
            var loaded = !!window._discussContextDefaults;
            function flag(key) { return loaded ? (_discussDefaultFlag(key) ? 'Included' : 'Not included') : (error ? 'Unavailable' : 'Loading…'); }
            _addReviewInfoRow(rows, 'Scene', 'The current scene, in full.');
            _addReviewInfoRow(rows, 'Feedback', 'Every lane for the chosen review.');
            _addReviewInfoRow(rows, 'Saved story notes', 'Included when available.', 'Story facts and purpose saved for this scene.');
            _addReviewInfoRow(rows, 'Scene details', flag('includeFrontmatter'), 'Fields such as goal, conflict, and outcome.');
            _addReviewInfoRow(rows, 'Nearby scenes', flag('includeAdjacent'), 'Short excerpts from the scenes immediately before and after.');
            _addReviewInfoRow(rows, 'Revision priorities', 'Up to ' + DISCUSS_DEFAULT_MAX_FINDINGS, 'Most important first. Change the number in Customize.');
            _addReviewInfoRow(rows, 'Keep list', 'Off', 'To list moments that work apart from the priorities, turn on “Show what to keep” in Customize.');
            _addReviewInfoRow(rows, 'Check planned events', 'Off', 'Notes provide background. To check for missing events, turn on “Check my notes for planned beats” in Customize.');
            body.append(rows, elementWith('discuss-review-info-note', error
                ? 'Could not load Discuss settings. Close and reopen this information to retry.'
                : 'Scene details and nearby excerpts follow Settings → Discuss.'));
        }

        function renderOpenCritiqueInfoContents(body) {
            body.replaceChildren();
            var rows = document.createElement('dl');
            _addReviewInfoRow(
                rows,
                'Default (unchecked)',
                'Rigid template and strict rules',
                'Every finding must follow Lane → Before → Why → After with a pasteable rewrite, stay strictly inside the selected lanes, and include long principle essays.'
            );
            _addReviewInfoRow(
                rows,
                'Open critique (checked)',
                'Model chooses level and structure',
                'Picks whatever issues matter most (structure, character, or prose), keeps distinct points separate, treats selected lanes as a focus rather than a fence, and omits the long principle essays.'
            );
            _addReviewInfoRow(
                rows,
                'Rewrites & citations',
                'Drop-in Before/After when prose fits',
                'Anchors points with exact quoted lines and links, gives Before/After rewrites for localized prose changes, and allows brief directions for large cuts or restructures.'
            );
            body.append(rows, elementWith(
                'discuss-review-info-note',
                'Leave unchecked for the original structured review; check it when you want freer, less constrained feedback.'
            ));
        }

        function positionDiscussReviewInfo() {
            var popover = document.getElementById('discussReviewInfoPopover');
            if (!popover) return;
            var trigger = _discussReviewInfoTriggerId ? document.getElementById(_discussReviewInfoTriggerId) : null;
            var log = document.getElementById('discussLog');
            if (!trigger || !trigger.getClientRects().length || !log) { closeDiscussReviewInfo(); return; }
            var rect = trigger.getBoundingClientRect();
            var bounds = log.getBoundingClientRect();
            if (rect.bottom < bounds.top || rect.top > bounds.bottom) { closeDiscussReviewInfo(); return; }
            var below = innerHeight - rect.bottom - 14;
            var above = rect.top - 14;
            var opensUp = below < 300 && above > below;
            popover.style.width = Math.min(360, innerWidth - 24) + 'px';
            popover.style.maxHeight = Math.min(480, Math.max(0, opensUp ? above : below)) + 'px';
            popover.style.left = Math.max(12, Math.min(rect.left, innerWidth - popover.offsetWidth - 12)) + 'px';
            popover.style.top = (opensUp ? rect.top - popover.offsetHeight - 6 : rect.bottom + 6) + 'px';
        }

        function openDiscussReviewInfoPopover(triggerId, titleText, closeAriaLabel, renderContents) {
            if (document.getElementById('discussReviewInfoPopover')) {
                var same = _discussReviewInfoTriggerId === triggerId;
                closeDiscussReviewInfo(same);
                if (same) return null;
            }
            var trigger = document.getElementById(triggerId);
            if (!trigger) return null;
            _discussReviewInfoTriggerId = triggerId;
            var popover = elementWith('discuss-review-info-popover');
            popover.id = 'discussReviewInfoPopover';
            popover.setAttribute('role', 'dialog');
            popover.setAttribute('aria-labelledby', 'discussReviewInfoTitle');
            var head = elementWith('discuss-review-info-head');
            var title = document.createElement('strong');
            title.id = 'discussReviewInfoTitle'; title.textContent = titleText;
            var close = document.createElement('button'); close.type = 'button'; close.textContent = '×';
            close.setAttribute('aria-label', closeAriaLabel);
            close.onclick = function() { closeDiscussReviewInfo(true); };
            head.append(title, close);
            var body = elementWith('discuss-review-info-body');
            renderContents(body);
            popover.append(head, body); document.body.appendChild(popover);
            trigger.setAttribute('aria-expanded', 'true');
            positionDiscussReviewInfo(); close.focus({preventScroll: true});
            return {popover: popover, body: body};
        }

        function toggleDiscussReviewInfo() {
            var opened = openDiscussReviewInfoPopover(
                'discussReviewInfoTrigger',
                'What this review receives',
                'Close quick review information',
                renderDiscussReviewInfoContents
            );
            if (!opened) return;
            _ensureDiscussContextDefaults().then(function() {
                if (opened.popover.isConnected) { renderDiscussReviewInfoContents(opened.body); positionDiscussReviewInfo(); }
            }).catch(function() {
                if (opened.popover.isConnected) { renderDiscussReviewInfoContents(opened.body, true); positionDiscussReviewInfo(); }
            });
        }

        function toggleOpenCritiqueInfo() {
            openDiscussReviewInfoPopover(
                'discussReviewOpenCritiqueInfo',
                'Open critique vs. default template',
                'Close open critique information',
                renderOpenCritiqueInfoContents
            );
        }

        function toggleDiscussReviewCards() {
            if (_discussCraftState.cardsOpen) closeDiscussReviewCards();
            else openDiscussReviewCards();
        }

        function openDiscussReviewCards() {
            closeDiscussCraftInfoDialog();
            leaveDiscussReviewSetup();
            saveDiscussDraft();
            _discussCraftState.cardsOpen = true;
            _discussRepositoryAction = null;
            _discussPendingAction = null;
            renderDiscussTaskMode();
            renderDiscussSnapshot();
            var picker = document.querySelector('.discuss-review-card-picker');
            if (picker) picker.scrollIntoView({block: 'start'});
            var first = document.getElementById('discussReviewRun-quick_critique');
            if (first) first.focus({preventScroll: true});
        }

        function closeDiscussReviewCards() {
            _discussCraftState.cardsOpen = false;
            renderDiscussTaskMode();
            renderDiscussSnapshot();
            document.getElementById('discussCraftButton').focus({preventScroll: true});
        }

        function renderDiscussReviewCardPicker(container) {
            var picker = elementWith('discuss-empty discuss-review-container discuss-review-card-picker');
            picker.id = 'discussReviewCardPicker';
            var head = elementWith('discuss-craft-head');
            var back = document.createElement('button');
            back.type = 'button';
            back.className = 'discuss-secondary discuss-craft-back';
            back.textContent = '← Back to chat';
            back.onclick = closeDiscussReviewCards;
            head.append(discussReviewHeading(), back);
            picker.appendChild(head);
            appendDiscussReviewCards(picker, false);
            container.appendChild(picker);
        }

        function discussReviewSelectedLanes(guide) {
            guide = guide || discussCraftLens();
            var ids = _discussCraftState.selectedLanes[guide.id];
            if (!ids) ids = guide.lanes.map(function(lane) { return lane.id; });
            return guide.lanes.filter(function(lane) { return ids.indexOf(lane.id) >= 0; });
        }

        function setDiscussReviewLanes(ids, guide) {
            guide = guide || discussCraftLens();
            _discussCraftState.selectedLanes[guide.id] = ids.slice();
        }

        function discussReviewLaneSummary() {
            var guide = discussCraftLens();
            var selected = discussReviewSelectedLanes(guide);
            if (selected.length === guide.lanes.length) return 'All lanes';
            if (!selected.length) return 'Choose at least one lane';
            return selected.map(discussCraftLaneName).join(' · ');
        }

        function refreshDiscussReviewSetup() {
            renderDiscussTaskMode();
            renderDiscussSnapshot();
        }

        function reviewSectionHeading(label, hint) {
            var head = elementWith('discuss-craft-section-head');
            head.appendChild(elementWith('discuss-story-group', label));
            if (hint) head.appendChild(elementWith('discuss-craft-hint', hint));
            return head;
        }

        function reviewInfoButton(label, className, onclick) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = className;
            button.textContent = '\u24d8';
            button.title = label;
            button.setAttribute('aria-label', label);
            button.setAttribute('aria-haspopup', 'dialog');
            button.onclick = onclick;
            return button;
        }

        function reviewSceneTitle(path) {
            return (typeof meta !== 'undefined' && meta[path] && meta[path].title) || path.split('/').pop();
        }

        function renderDiscussReviewSetup(container) {
            var selectedScenes = discussCraftSelectedScenes();
            if (selectedScenes.indexOf(_discussCraftState.contextScenePath) < 0) {
                var active = discussCraftActivePath();
                _discussCraftState.contextScenePath = selectedScenes.indexOf(active) >= 0 ? active : (selectedScenes[0] || active);
            }
            selectedScenes.forEach(loadDiscussCraftContext);
            var mode = discussReviewMode();
            var wrap = elementWith('discuss-craft-setup');
            var head = elementWith('discuss-craft-head');
            var headText = elementWith('discuss-craft-head-text');
            var title = document.createElement('strong');
            title.textContent = 'Customize ' + mode.label.toLowerCase();
            headText.append(title, elementWith('discuss-craft-sub', 'Changes here apply when you run this custom review.'));
            var close = document.createElement('button');
            close.type = 'button';
            close.className = 'discuss-secondary discuss-craft-back';
            close.textContent = '← Review cards';
            close.setAttribute('aria-label', 'Close review setup');
            close.onclick = cancelDiscussCraftReview;
            head.append(headText, close);
            wrap.appendChild(head);

            if (mode.id === 'craft_review') {
                wrap.appendChild(reviewSectionHeading('Writing book', 'ⓘ for guide & examples'));
                var books = elementWith('discuss-craft-lens-grid');
                DISCUSS_CRAFT_LENSES.forEach(function(lens) {
                    var chosen = lens.id === _discussCraftState.lensId;
                    var card = elementWith('discuss-craft-lens' + (chosen ? ' is-selected' : ''));
                    card.dataset.lens = lens.id;
                    var pick = document.createElement('button');
                    pick.type = 'button';
                    pick.className = 'discuss-craft-lens-pick';
                    pick.id = 'discussReviewBook-' + lens.id;
                    pick.setAttribute('aria-pressed', chosen ? 'true' : 'false');
                    var live = _discussActionCopy[lens.id] || {};
                    pick.title = live.description || lens.tagline;
                    pick.append(elementWith('discuss-craft-lens-title', lens.purpose), elementWith('discuss-craft-lens-copy', live.label || lens.label));
                    pick.onclick = function() { _selectDiscussCraftLensAndScope(lens); refreshDiscussReviewSetup(); };
                    var info = reviewInfoButton('About ' + lens.book + ' by ' + lens.author, 'discuss-craft-info-btn', function() {
                        openDiscussCraftInfoDialog(lens.id);
                    });
                    info.id = 'discussReviewBookInfo-' + lens.id;
                    card.append(pick, info);
                    books.appendChild(card);
                });
                wrap.appendChild(books);
            }

            var totalWords = selectedScenes.reduce(function(sum, path) { return sum + ((meta[path] || {}).words || 0); }, 0);
            wrap.appendChild(reviewSectionHeading('1. Scenes to review', selectedScenes.length + (selectedScenes.length === 1 ? ' scene' : ' scenes') + ' · ~' + totalWords.toLocaleString() + ' words'));
            var scopeGrid = elementWith('discuss-craft-scope-grid');
            [
                {id: 'this_scene', label: 'This scene', hint: '1 scene'},
                {id: 'adjacent', label: '±1 adjacent', hint: discussCraftScenesCountHint('adjacent', discussCraftActivePath(), discussCraftAllPaths())},
                {id: 'this_chapter', label: 'This chapter', hint: discussCraftScenesCountHint('this_chapter', discussCraftActivePath(), discussCraftAllPaths())},
                {id: 'custom', label: 'Pick scenes…', hint: _discussCraftState.scopeMode === 'custom' ? selectedScenes.length + ' picked' : 'Choose any scenes'}
            ].forEach(function(scope) {
                var button = document.createElement('button');
                button.type = 'button';
                button.id = 'discussReviewScope-' + scope.id;
                button.className = 'discuss-craft-scope-btn' + (_discussCraftState.scopeMode === scope.id ? ' is-selected' : '');
                button.dataset.scope = scope.id;
                button.setAttribute('aria-pressed', _discussCraftState.scopeMode === scope.id ? 'true' : 'false');
                button.append(elementWith('discuss-craft-scope-label', scope.label), elementWith('discuss-craft-scope-hint', scope.hint));
                button.onclick = function() {
                    if (scope.id === 'custom') { openDiscussReviewScenePicker(); return; }
                    _discussCraftState.scopeMode = scope.id;
                    refreshDiscussReviewSetup();
                };
                scopeGrid.appendChild(button);
            });
            wrap.appendChild(scopeGrid);
            if (selectedScenes.length > 1) {
                var names = elementWith('discuss-review-selected-scenes');
                selectedScenes.forEach(function(path) {
                    var name = elementWith('discuss-review-selected-scene', reviewSceneTitle(path));
                    name.title = path;
                    names.appendChild(name);
                });
                wrap.appendChild(names);
            }
            wrap.appendChild(elementWith('discuss-craft-context-help', selectedScenes.length > 1
                ? 'Every selected scene is reviewed in full, in manuscript order.'
                : 'The selected scene is reviewed in full. Neighbor excerpts can be added as background.'));
            wrap.appendChild(reviewSectionHeading('2. Lanes to review', discussReviewSelectedLanes().length + ' selected'));
            wrap.appendChild(renderDiscussReviewFocusControl());
            wrap.appendChild(renderDiscussReviewLimitControl());
            if (mode.id === 'comedy_review') renderDiscussComedyOptions(wrap);
            renderDiscussReviewBackground(wrap, selectedScenes);
            wrap.appendChild(elementWith('discuss-craft-context-help', 'The main card will still run the default review of the current scene.'));
            container.appendChild(wrap);
        }

        function discussComedySummary() {
            var guide = discussCraftLens('comedy_review');
            var styles = guide.styles.filter(function(style) { return _discussCraftState.comedyStyles.indexOf(style.id) >= 0; });
            var goals = guide.goals.filter(function(item) { return _discussCraftState.comedyGoals.indexOf(item.id) >= 0; });
            return (styles.length ? styles.map(function(style) { return style.label; }).join(' + ') : 'Follow the draft')
                + ' · ' + (goals.length ? goals.map(function(goal) { return goal.label; }).join(' + ') : 'Choose at least one goal');
        }

        function renderDiscussComedyOptions(wrap) {
            var guide = discussCraftLens('comedy_review');
            var box = elementWith('discuss-comedy-options');
            box.appendChild(reviewSectionHeading('Comic approach', 'Optional styles'));
            var styles = elementWith('discuss-comedy-styles');
            styles.setAttribute('role', 'group');
            styles.setAttribute('aria-label', 'Comic styles');
            guide.styles.forEach(function(style) {
                var chip = elementWith('discuss-comedy-style');
                var label = document.createElement('label');
                label.title = style.brief;
                var input = document.createElement('input');
                input.type = 'checkbox'; input.id = 'discussComedyStyle-' + style.id;
                input.checked = _discussCraftState.comedyStyles.indexOf(style.id) >= 0;
                input.onchange = function() {
                    var ids = _discussCraftState.comedyStyles.filter(function(id) { return id !== style.id; });
                    if (input.checked) ids.push(style.id);
                    _discussCraftState.comedyStyles = guide.styles.filter(function(item) { return ids.indexOf(item.id) >= 0; }).map(function(item) { return item.id; });
                    renderDiscussTaskMode();
                };
                label.append(input, document.createTextNode(style.label));
                var info = reviewInfoButton(style.label + ': ' + style.brief, 'discuss-craft-focus-option-info', function() {
                    openDiscussCraftInfoDialog(guide.id, style.laneId);
                });
                info.id = 'discussComedyStyleInfo-' + style.id;
                chip.append(label, info); styles.appendChild(chip);
            });
            box.append(styles, elementWith('discuss-craft-context-help', 'Combine styles, or leave them clear to follow the draft. Styles guide your selected lanes.'));
            var goalLabel = document.createElement('strong'); goalLabel.textContent = 'Review goals (choose one or both)';
            box.appendChild(goalLabel);
            var goals = elementWith('discuss-comedy-goals');
            goals.setAttribute('role', 'group'); goals.setAttribute('aria-label', 'Comedy review goals');
            var goalHelp = elementWith('discuss-craft-context-help'); goalHelp.id = 'discussComedyGoalHelp';
            function updateGoalHelp() {
                var selected = guide.goals.filter(function(item) { return _discussCraftState.comedyGoals.indexOf(item.id) >= 0; });
                goalHelp.textContent = selected.length === 2
                    ? 'Review existing comic moments and suggest new opportunities. Feedback labels the two kinds of suggestion.'
                    : selected.length ? selected[0].brief : 'Choose at least one goal before running the review.';
            }
            guide.goals.forEach(function(goal) {
                var selected = _discussCraftState.comedyGoals.indexOf(goal.id) >= 0;
                var label = document.createElement('label');
                label.className = 'discuss-craft-scope-btn discuss-comedy-goal' + (selected ? ' is-selected' : '');
                label.title = goal.brief;
                var input = document.createElement('input');
                input.type = 'checkbox'; input.id = 'discussComedyGoal-' + goal.id; input.checked = selected;
                input.setAttribute('aria-describedby', goalHelp.id);
                var text = document.createElement('span'); text.textContent = goal.label;
                input.onchange = function() {
                    var ids = _discussCraftState.comedyGoals.filter(function(id) { return id !== goal.id; });
                    if (input.checked) ids.push(goal.id);
                    _discussCraftState.comedyGoals = guide.goals.filter(function(item) { return ids.indexOf(item.id) >= 0; }).map(function(item) { return item.id; });
                    label.classList.toggle('is-selected', input.checked);
                    updateGoalHelp();
                    renderDiscussTaskMode();
                };
                label.append(input, text); goals.appendChild(label);
            });
            updateGoalHelp();
            box.append(goals, goalHelp); wrap.appendChild(box);
        }

        function appendDiscussReviewSources(container, guide, ids) {
            var sources = (guide.sources || []).filter(function(source) { return !ids || ids.indexOf(source.id) >= 0; });
            if (!sources.length) return;
            var details = document.createElement('details');
            details.className = 'discuss-craft-guide-note discuss-review-sources';
            var summary = document.createElement('summary'); summary.textContent = ids ? 'Technique sources' : 'Books & further reading';
            details.appendChild(summary);
            if (!ids && guide.sourceNote) details.appendChild(elementWith('discuss-craft-check-desc', guide.sourceNote));
            sources.forEach(function(source) {
                var row = elementWith('discuss-review-source');
                var link = document.createElement('a'); link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
                link.textContent = source.label + ' ↗';
                row.append(link, elementWith('discuss-craft-check-desc', source.detail));
                details.appendChild(row);
            });
            container.appendChild(details);
        }

        function renderDiscussReviewFocusControl() {
            var guide = discussCraftLens();
            var selected = discussReviewSelectedLanes(guide);
            var narrowed = selected.length !== guide.lanes.length;
            var box = elementWith('discuss-craft-focus-box');
            var row = elementWith('discuss-craft-focus-row');
            row.appendChild(elementWith('discuss-craft-focus-label', 'Focus:'));
            var trigger = document.createElement('button');
            trigger.type = 'button';
            trigger.id = 'discussReviewFocusTrigger';
            trigger.className = 'discuss-craft-focus-trigger' + (narrowed ? ' is-focused' : '');
            trigger.setAttribute('aria-haspopup', 'dialog');
            trigger.setAttribute('aria-expanded', _discussCraftState.focusMenuOpen ? 'true' : 'false');
            trigger.setAttribute('aria-controls', 'discussReviewFocusPopover');
            trigger.title = narrowed ? (selected.map(discussCraftLaneName).join(', ') || 'Choose at least one lane') : 'Review all lanes in ' + guide.book + '. Click to choose one or several.';
            trigger.append(elementWith('discuss-craft-focus-trigger-text', narrowed && selected.length > 1 ? selected.length + ' lanes selected' : discussReviewLaneSummary()), elementWith('discuss-craft-focus-caret', '▾'));
            trigger.onclick = function() {
                _discussCraftState.focusMenuOpen = !_discussCraftState.focusMenuOpen;
                trigger.setAttribute('aria-expanded', _discussCraftState.focusMenuOpen ? 'true' : 'false');
                renderDiscussReviewFocusPopover();
                var first = document.querySelector('#discussReviewFocusPopover .discuss-craft-focus-option-pick');
                if (first) first.focus({preventScroll: true});
            };
            row.appendChild(trigger);
            if (narrowed) {
                var reset = document.createElement('button');
                reset.type = 'button';
                reset.id = 'discussReviewFocusReset';
                reset.className = 'discuss-craft-focus-clear';
                reset.textContent = '×';
                reset.title = 'Reset to all lanes';
                reset.setAttribute('aria-label', reset.title);
                reset.onclick = function() {
                    setDiscussReviewLanes(guide.lanes.map(function(lane) { return lane.id; }));
                    _discussCraftState.focusMenuOpen = false;
                    refreshDiscussReviewSetup();
                    document.getElementById('discussReviewFocusTrigger').focus({preventScroll: true});
                };
                row.appendChild(reset);
            }
            var info = reviewInfoButton('Browse lanes and before/after examples', 'discuss-craft-focus-info-btn', function() {
                closeDiscussReviewFocusPopover();
                openDiscussCraftInfoDialog(guide.id, (selected[0] || guide.lanes[0]).id);
            });
            info.id = 'discussReviewFocusInfo';
            row.appendChild(info);
            box.appendChild(row);
            return box;
        }

        function renderDiscussReviewLimitControl() {
            var guide = discussCraftLens();
            var box = elementWith('discuss-review-limit');
            if (guide.id === 'craft_lamott') {
                box.appendChild(elementWith('discuss-craft-context-help', 'Bird by Bird gives one small drafting assignment, so it has no priority limit.'));
                return box;
            }
            var noun = guide.id === 'deepen_and_layer' ? 'opportunities' : 'revision priorities';
            var label = document.createElement('label');
            label.htmlFor = 'discussReviewMaxFindings';
            label.textContent = 'Up to';
            var input = document.createElement('input');
            input.type = 'number'; input.id = 'discussReviewMaxFindings';
            input.min = '1'; input.max = String(DISCUSS_MAX_FINDINGS_LIMIT); input.step = '1';
            input.value = String(_discussCraftState.maxFindings);
            input.setAttribute('aria-describedby', 'discussReviewMaxFindingsHelp');
            var helpText = 'Most important first. The review gives fewer when fewer earn their place. Default '
                + DISCUSS_DEFAULT_MAX_FINDINGS + ', most ' + DISCUSS_MAX_FINDINGS_LIMIT + '.';
            var help = elementWith('discuss-craft-context-help', helpText);
            help.id = 'discussReviewMaxFindingsHelp';
            input.onchange = function() {
                var typed = Math.round(Number(input.value));
                var value = isFinite(typed) && input.value !== '' ? typed : DISCUSS_DEFAULT_MAX_FINDINGS;
                value = Math.min(DISCUSS_MAX_FINDINGS_LIMIT, Math.max(1, value));
                input.value = String(value);
                _discussCraftState.maxFindings = value;
                try { localStorage.setItem(DISCUSS_MAX_FINDINGS_PREF, String(value)); } catch (e) {}
                renderDiscussTaskMode();
                // Say so when the number typed is not the number that will be used.
                help.textContent = typed > DISCUSS_MAX_FINDINGS_LIMIT
                    ? 'The most a review can give is ' + DISCUSS_MAX_FINDINGS_LIMIT + ', so it is set to ' + DISCUSS_MAX_FINDINGS_LIMIT + '.'
                    : typed < 1 ? 'A review gives at least 1, so it is set to 1.' : helpText;
            };
            var row = elementWith('discuss-review-limit-row');
            row.append(label, input, elementWith('discuss-review-limit-noun', noun));
            box.append(row, help);
            function addReviewOptionToggle(className, id, helpId, titleText, helpText, checked, onChange, infoConfig) {
                var toggle = document.createElement(infoConfig ? 'div' : 'label');
                toggle.className = className;
                var toggleInput = document.createElement('input');
                toggleInput.type = 'checkbox'; toggleInput.id = id;
                toggleInput.checked = !!checked;
                toggleInput.setAttribute('aria-describedby', helpId);
                toggleInput.onchange = function() { onChange(toggleInput.checked); };
                var copy = elementWith('discuss-review-note-copy');
                var title = document.createElement('strong'); title.textContent = titleText;
                if (infoConfig) {
                    var headRow = elementWith('discuss-review-option-head');
                    var titleLabel = document.createElement('label');
                    titleLabel.htmlFor = id;
                    titleLabel.appendChild(title);
                    var infoBtn = reviewInfoButton(infoConfig.label, 'discuss-review-info-trigger discuss-review-option-info', infoConfig.onclick);
                    infoBtn.id = infoConfig.id;
                    infoBtn.setAttribute('aria-controls', 'discussReviewInfoPopover');
                    infoBtn.setAttribute('aria-expanded', _discussReviewInfoTriggerId === infoConfig.id && document.getElementById('discussReviewInfoPopover') ? 'true' : 'false');
                    headRow.append(titleLabel, infoBtn);
                    copy.appendChild(headRow);
                } else {
                    copy.appendChild(title);
                }
                var toggleHelp = elementWith('discuss-craft-context-help', helpText);
                toggleHelp.id = helpId;
                copy.appendChild(toggleHelp);
                toggle.append(toggleInput, copy);
                box.appendChild(toggle);
            }
            if (discussReviewHasKeepChoice(guide.id)) {
                addReviewOptionToggle(
                    'discuss-review-keep-toggle',
                    'discussReviewIncludeKeep',
                    'discussReviewIncludeKeepHelp',
                    'Show what to keep',
                    'One or two moments that work, listed apart from the revision priorities.',
                    _discussCraftState.includeKeep,
                    function(on) {
                        _discussCraftState.includeKeep = on;
                        try { localStorage.setItem(DISCUSS_INCLUDE_KEEP_PREF, on ? 'on' : 'off'); } catch (e) {}
                        renderDiscussTaskMode();
                    }
                );
            }
            if (discussReviewHasOpenCritiqueChoice(guide.id)) {
                addReviewOptionToggle(
                    'discuss-review-open-critique-toggle',
                    'discussReviewOpenCritique',
                    'discussReviewOpenCritiqueHelp',
                    'Open critique',
                    'Let the model decide what matters most—structure, character, or prose—without the rigid template.',
                    _discussCraftState.openCritique,
                    function(on) {
                        _discussCraftState.openCritique = on;
                        try { localStorage.setItem(DISCUSS_OPEN_CRITIQUE_PREF, on ? 'on' : 'off'); } catch (e) {}
                        renderDiscussTaskMode();
                    },
                    {
                        id: 'discussReviewOpenCritiqueInfo',
                        label: 'How Open critique differs from the default template',
                        onclick: toggleOpenCritiqueInfo
                    }
                );
            }
            return box;
        }

        function closeDiscussReviewFocusPopover(restoreFocus) {
            _discussCraftState.focusMenuOpen = false;
            var popover = document.getElementById('discussReviewFocusPopover');
            if (popover) popover.remove();
            var trigger = document.getElementById('discussReviewFocusTrigger');
            if (trigger) {
                trigger.setAttribute('aria-expanded', 'false');
                if (restoreFocus) trigger.focus({preventScroll: true});
            }
        }

        function positionDiscussReviewFocusPopover() {
            var popover = document.getElementById('discussReviewFocusPopover');
            var trigger = document.getElementById('discussReviewFocusTrigger');
            var panel = document.getElementById('discussPanel');
            if (!popover) return;
            if (!trigger || !panel || panel.hidden || !_discussCraftState.active) { closeDiscussReviewFocusPopover(); return; }
            var rect = trigger.getBoundingClientRect();
            var log = document.getElementById('discussLog').getBoundingClientRect();
            if (rect.bottom < log.top || rect.top > log.bottom) { closeDiscussReviewFocusPopover(); return; }
            var width = Math.min(Math.max(rect.width, 280), innerWidth - 16);
            var below = innerHeight - rect.bottom - 14;
            var above = rect.top - 14;
            var opensUp = below < 230 && above > below;
            popover.style.width = width + 'px';
            popover.style.maxHeight = Math.min(320, opensUp ? above : below) + 'px';
            popover.style.left = Math.max(8, Math.min(rect.left, innerWidth - width - 8)) + 'px';
            popover.style.top = (opensUp ? rect.top - popover.offsetHeight - 6 : rect.bottom + 6) + 'px';
        }

        function renderDiscussReviewFocusPopover() {
            var previous = document.getElementById('discussReviewFocusPopover');
            if (!_discussCraftState.active || !_discussCraftState.focusMenuOpen) {
                if (previous) previous.remove();
                return;
            }
            var focused = previous && previous.contains(document.activeElement) ? document.activeElement.id : '';
            var scroll = previous ? previous.scrollTop : 0;
            if (previous) previous.remove();
            var guide = discussCraftLens();
            var selected = discussReviewSelectedLanes(guide);
            var popover = elementWith('discuss-craft-focus-popover');
            popover.id = 'discussReviewFocusPopover';
            popover.setAttribute('role', 'dialog');
            popover.setAttribute('aria-label', 'Choose review lanes');
            function addOption(id, name, brief, checked, change, lane) {
                var option = elementWith('discuss-craft-focus-option' + (checked ? ' is-selected' : ''));
                option.dataset.focus = id;
                var pick = document.createElement('button');
                pick.type = 'button';
                pick.id = 'discussReviewLane-' + (id || 'all');
                pick.className = 'discuss-craft-focus-option-pick';
                pick.setAttribute('role', 'checkbox');
                pick.setAttribute('aria-checked', checked ? 'true' : 'false');
                pick.title = name + ': ' + brief + (lane ? '\n' + lane.summary : '');
                var check = elementWith('discuss-review-lane-check', checked ? '✓' : '');
                check.setAttribute('aria-hidden', 'true');
                var copy = elementWith('discuss-review-lane-copy');
                copy.append(elementWith('discuss-craft-focus-option-title', name), elementWith('discuss-craft-focus-option-brief', brief));
                pick.append(check, copy);
                pick.onclick = change;
                pick.onkeydown = function(event) {
                    var buttons = Array.from(popover.querySelectorAll('.discuss-craft-focus-option-pick'));
                    var index = buttons.indexOf(pick);
                    if (event.key === 'ArrowDown') index = (index + 1) % buttons.length;
                    else if (event.key === 'ArrowUp') index = (index - 1 + buttons.length) % buttons.length;
                    else if (event.key === 'Home') index = 0;
                    else if (event.key === 'End') index = buttons.length - 1;
                    else return;
                    event.preventDefault(); buttons[index].focus();
                };
                option.appendChild(pick);
                if (lane) {
                    var info = reviewInfoButton('Examples for ' + name, 'discuss-craft-focus-option-info', function() {
                        closeDiscussReviewFocusPopover();
                        // The item will be removed; return to the picker after the guide.
                        document.getElementById('discussReviewFocusTrigger').focus({preventScroll: true});
                        openDiscussCraftInfoDialog(guide.id, lane.id);
                    });
                    info.id = 'discussReviewLaneInfo-' + id;
                    option.appendChild(info);
                }
                popover.appendChild(option);
            }
            function update(ids, focusId) {
                setDiscussReviewLanes(ids, guide);
                refreshDiscussReviewSetup();
                var next = document.getElementById(focusId);
                if (next) next.focus({preventScroll: true});
            }
            addOption('', 'All lanes', 'Review every lane in ' + guide.book + '.', selected.length === guide.lanes.length, function() {
                update(selected.length === guide.lanes.length ? [] : guide.lanes.map(function(lane) { return lane.id; }), 'discussReviewLane-all');
            });
            guide.lanes.forEach(function(lane) {
                var checked = selected.some(function(item) { return item.id === lane.id; });
                addOption(lane.id, discussCraftLaneName(lane), lane.brief, checked, function() {
                    var ids = selected.map(function(item) { return item.id; });
                    if (checked) ids = ids.filter(function(id) { return id !== lane.id; });
                    else ids.push(lane.id);
                    update(ids, 'discussReviewLane-' + lane.id);
                }, lane);
            });
            var foot = elementWith('discuss-review-focus-footer');
            var clear = document.createElement('button');
            clear.type = 'button'; clear.className = 'discuss-secondary'; clear.textContent = 'Clear';
            clear.id = 'discussReviewLanesClear';
            clear.onclick = function() { update([], 'discussReviewLanesClear'); };
            var done = document.createElement('button');
            done.type = 'button'; done.className = 'discuss-secondary'; done.textContent = 'Done';
            done.onclick = function() { closeDiscussReviewFocusPopover(true); };
            foot.append(clear, elementWith('discuss-craft-hint', 'Choose one or several'), done);
            popover.appendChild(foot);
            document.body.appendChild(popover);
            positionDiscussReviewFocusPopover();
            popover.scrollTop = scroll;
            var next = focused ? document.getElementById(focused) : null;
            if (next) next.focus({preventScroll: true});
        }

        function renderDiscussReviewBackground(wrap, selectedScenes) {
            var head = reviewSectionHeading('3. Background notes', 'Shared settings');
            var settings = document.createElement('button');
            settings.type = 'button'; settings.className = 'discuss-craft-settings-link'; settings.textContent = 'Defaults';
            settings.title = 'Change the default context settings'; settings.onclick = openDiscussSettings;
            head.appendChild(settings); wrap.appendChild(head);
            var row = elementWith('discuss-craft-notes-row');
            function toggle(id, label, help, checked, set, disabled) {
                var field = document.createElement('label');
                field.className = 'discuss-craft-note-toggle' + (disabled ? ' is-disabled' : '');
                field.title = help;
                var input = document.createElement('input');
                input.type = 'checkbox'; input.id = id; input.checked = checked; input.disabled = !!disabled;
                input.onchange = function() { set(input.checked); renderDiscussTaskMode(); };
                var copy = elementWith('discuss-review-note-copy');
                var strong = document.createElement('strong'); strong.textContent = label;
                copy.append(strong, elementWith('discuss-craft-context-help', help));
                field.append(input, copy); row.appendChild(field);
            }
            toggle('discussReviewFrontmatter', 'Scene frontmatter', 'Include goals, conflicts, outcomes, and other scene metadata.', effectiveDiscussFrontmatter(), function(on) { _discussCraftState.includeFrontmatter = on; });
            toggle('discussReviewAdjacent', '±1 scene excerpts', selectedScenes.length === 1 ? 'Closing and opening paragraphs, supplied as background.' : 'Available for a single-scene review. Selected scenes are already supplied in full.', selectedScenes.length === 1 && effectiveDiscussAdjacent(), function(on) { _discussCraftState.includeAdjacent = on; }, selectedScenes.length !== 1);
            toggle('discussReviewCheckPlan', 'Check my notes for planned beats', 'Off: notes are background only. On: compare the draft with beats in your frontmatter, beat map, or TODO notes.', _discussCraftState.checkPlan, function(on) { _discussCraftState.checkPlan = on; });
            wrap.appendChild(row);
            var path = _discussCraftState.contextScenePath;
            var value = discussCraftContext(path);
            var details = document.createElement('details');
            details.className = 'discuss-craft-story-context';
            details.open = _discussCraftState.storyContextOpen === null ? !!value : _discussCraftState.storyContextOpen;
            details.ontoggle = function() { if (details.isConnected) _discussCraftState.storyContextOpen = details.open; };
            var summary = document.createElement('summary');
            summary.textContent = 'Story facts & purpose (optional, saved per scene)';
            summary.onclick = function() { _discussCraftState.storyContextOpen = !details.open; };
            details.appendChild(summary);
            if (selectedScenes.length > 1) {
                var selectLabel = document.createElement('label');
                selectLabel.htmlFor = 'discussReviewContextScene'; selectLabel.textContent = 'Notes for';
                var select = document.createElement('select'); select.id = 'discussReviewContextScene';
                selectedScenes.forEach(function(scenePath) {
                    var option = document.createElement('option'); option.value = scenePath;
                    option.textContent = reviewSceneTitle(scenePath) + ' · ' + scenePath;
                    option.selected = scenePath === path; select.appendChild(option);
                });
                select.onchange = function() { _discussCraftState.contextScenePath = select.value; renderDiscussSnapshot(); };
                details.append(selectLabel, select);
            }
            var label = document.createElement('label');
            label.htmlFor = 'discussCraftContext'; label.textContent = 'What the reviewer should know about this scene';
            var help = elementWith('discuss-craft-context-help'); help.id = 'discussCraftContextHelp';
            var guide = discussCraftLens();
            help.textContent = guide.id === 'craft_cron'
                ? 'Add a known belief, desire, or relevant character background. Notes stay with their own scene and are shared across review types.'
                : guide.id === 'craft_coyne'
                    ? 'Name the genre and the experience you want readers to have. Add where this scene fits in the story. Notes stay with their own scene across review types.'
                    : 'Add established facts or what this scene should achieve. Notes stay with their own scene across review types. Use the checkbox above to check planned beats against the draft.';
            var input = document.createElement('textarea');
            input.id = 'discussCraftContext'; input.rows = 4; input.maxLength = 2000; input.value = value;
            input.setAttribute('aria-describedby', help.id);
            input.oninput = function() { saveDiscussCraftContext(input.value, path); };
            var status = elementWith('discuss-craft-context-help', _discussCraftState.storyContextStatuses[discussCraftContextKey(path)] || 'Saved with this scene · shared across review types and providers');
            status.id = 'discussCraftContextStatus'; status.setAttribute('role', 'status');
            details.append(label, help, input, status); wrap.appendChild(details);
        }

        var _discussReviewSceneDraft = new Set();
        var _discussReviewSceneOpener = null;
        function openDiscussReviewScenePicker() {
            closeDiscussReviewFocusPopover();
            _discussReviewSceneDraft = new Set(discussCraftSelectedScenes());
            _discussReviewSceneOpener = document.activeElement;
            var dialog = document.getElementById('discussReviewSceneDialog');
            if (!dialog) {
                dialog = document.createElement('dialog');
                dialog.id = 'discussReviewSceneDialog';
                dialog.className = 'discuss-craft-info-dialog discuss-review-scene-dialog';
                dialog.setAttribute('aria-labelledby', 'discussReviewSceneTitle');
                var head = elementWith('discuss-craft-dialog-head');
                var title = document.createElement('h2'); title.id = 'discussReviewSceneTitle'; title.textContent = 'Choose scenes to review';
                head.appendChild(title); dialog.appendChild(head);
                var body = elementWith('discuss-craft-dialog-body');
                var search = document.createElement('input');
                search.id = 'discussReviewSceneSearch'; search.type = 'search'; search.placeholder = 'Find a scene…';
                search.setAttribute('aria-label', 'Find a scene'); search.oninput = renderDiscussReviewSceneChoices;
                body.appendChild(search);
                var tools = elementWith('discuss-review-scene-tools');
                var chapter = document.createElement('button');
                chapter.type = 'button'; chapter.className = 'discuss-secondary'; chapter.textContent = 'Select this chapter';
                chapter.onclick = function() {
                    var ch = (meta[discussCraftActivePath()] || {}).chapter;
                    discussCraftAllPaths().forEach(function(path) { if ((meta[path] || {}).chapter === ch) _discussReviewSceneDraft.add(path); });
                    renderDiscussReviewSceneChoices();
                };
                var clear = document.createElement('button');
                clear.type = 'button'; clear.className = 'discuss-secondary'; clear.textContent = 'Clear selection';
                clear.onclick = function() { _discussReviewSceneDraft.clear(); renderDiscussReviewSceneChoices(); };
                tools.append(chapter, clear); body.appendChild(tools);
                var choices = elementWith('discuss-review-scene-choices'); choices.id = 'discussReviewSceneChoices'; body.appendChild(choices);
                dialog.appendChild(body);
                var foot = elementWith('discuss-craft-dialog-foot');
                var count = elementWith('discuss-craft-hint'); count.id = 'discussReviewSceneCount'; count.setAttribute('role', 'status');
                var actions = elementWith('discuss-craft-dialog-actions');
                var cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'discuss-secondary'; cancel.textContent = 'Cancel';
                cancel.onclick = function() { dialog.close(); };
                var apply = document.createElement('button'); apply.id = 'discussReviewSceneApply'; apply.type = 'button'; apply.className = 'discuss-primary'; apply.textContent = 'Use selected scenes';
                apply.onclick = function() {
                    _discussCraftState.customScenes = discussCraftAllPaths().filter(function(path) { return _discussReviewSceneDraft.has(path); });
                    _discussCraftState.scopeMode = 'custom'; dialog.close(); refreshDiscussReviewSetup();
                };
                actions.append(cancel, apply); foot.append(count, actions); dialog.appendChild(foot);
                dialog.addEventListener('click', function(event) { if (event.target === dialog) dialog.close(); });
                dialog.addEventListener('close', function() {
                    var target = _discussReviewSceneOpener && _discussReviewSceneOpener.isConnected ? _discussReviewSceneOpener : document.getElementById('discussReviewScope-custom');
                    if (target) target.focus({preventScroll: true});
                });
                document.body.appendChild(dialog);
            }
            document.getElementById('discussReviewSceneSearch').value = '';
            renderDiscussReviewSceneChoices(); dialog.showModal();
            document.getElementById('discussReviewSceneSearch').focus();
        }

        function renderDiscussReviewSceneChoices() {
            var choices = document.getElementById('discussReviewSceneChoices');
            var query = document.getElementById('discussReviewSceneSearch').value.toLowerCase().trim();
            var count = _discussReviewSceneDraft.size;
            document.getElementById('discussReviewSceneCount').textContent = count + (count === 1 ? ' scene selected' : ' scenes selected');
            document.getElementById('discussReviewSceneApply').disabled = !count;
            choices.replaceChildren();
            var previousChapter = null;
            discussCraftAllPaths().forEach(function(path) {
                var scene = meta[path] || {};
                if (query && (path + ' ' + reviewSceneTitle(path)).toLowerCase().indexOf(query) < 0) return;
                var chapter = scene.chapter || path.split('/').slice(0, -1).join('/') || 'Scenes';
                if (chapter !== previousChapter) {
                    choices.appendChild(elementWith('discuss-review-picker-chapter', String(chapter)));
                    previousChapter = chapter;
                }
                var row = document.createElement('label'); row.className = 'discuss-craft-custom-item';
                var input = document.createElement('input'); input.type = 'checkbox'; input.value = path; input.checked = _discussReviewSceneDraft.has(path);
                input.onchange = function() {
                    if (input.checked) _discussReviewSceneDraft.add(path); else _discussReviewSceneDraft.delete(path);
                    var n = _discussReviewSceneDraft.size;
                    document.getElementById('discussReviewSceneCount').textContent = n + (n === 1 ? ' scene selected' : ' scenes selected');
                    document.getElementById('discussReviewSceneApply').disabled = !n;
                };
                var copy = elementWith('discuss-review-picker-copy');
                copy.append(elementWith('discuss-craft-custom-name', reviewSceneTitle(path)), elementWith('discuss-craft-hint', path));
                row.append(input, copy, elementWith('discuss-craft-custom-words', (scene.words || 0).toLocaleString() + ' words')); choices.appendChild(row);
            });
            if (!choices.children.length) choices.appendChild(elementWith('discuss-craft-context-help', 'No scenes match that search.'));
        }

        document.addEventListener('mousedown', function(event) {
            if (!_discussCraftState || !_discussCraftState.focusMenuOpen) return;
            if (event.target.closest('.discuss-craft-focus-box, #discussReviewFocusPopover')) return;
            closeDiscussReviewFocusPopover();
        });
        document.addEventListener('keydown', function(event) {
            if (!_discussCraftState || !_discussCraftState.focusMenuOpen || event.key !== 'Escape') return;
            event.preventDefault(); event.stopImmediatePropagation(); closeDiscussReviewFocusPopover(true);
        }, true);
        document.addEventListener('focusin', function(event) {
            if (_discussCraftState && _discussCraftState.focusMenuOpen
                && !event.target.closest('.discuss-craft-focus-box, #discussReviewFocusPopover')) closeDiscussReviewFocusPopover();
        });
        window.addEventListener('resize', positionDiscussReviewFocusPopover);
        document.addEventListener('scroll', positionDiscussReviewFocusPopover, true);

        document.addEventListener('mousedown', function(event) {
            if (!event.target.closest('#discussReviewInfoTrigger, #discussReviewOpenCritiqueInfo, #discussReviewInfoPopover')) closeDiscussReviewInfo();
        });
        document.addEventListener('keydown', function(event) {
            if (!document.getElementById('discussReviewInfoPopover')) return;
            if (event.key === 'Escape') {
                event.preventDefault(); event.stopImmediatePropagation(); closeDiscussReviewInfo(true);
            } else if (event.key === 'Tab') closeDiscussReviewInfo(true);
        }, true);
        window.addEventListener('resize', positionDiscussReviewInfo);
        document.addEventListener('scroll', positionDiscussReviewInfo, true);
