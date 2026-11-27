# Code Review: Remote Mode Implementation

Reviewed 2026-11-26 across commits `74ece8c..e007a9c` plus the uncommitted working-tree changes (`proseview/remote.py`, `proseview/qr.py`, `proseview/server.py`, `proseview/cli.py`, `proseview/templates/assets/js/90-phone.js`, `60-selection.js`, `68-discuss.js`, `80-settings.js`, `app.css`, `index.html.j2`, and tests).

**Test run:** 102 unit tests (`test_remote.py`, `test_note_edit.py`, `test_annotations.py`, `test_cli.py`) and 7 Playwright phone E2E tests (`test_phone_e2e.py`) all pass.

Overall the implementation is clean and faithful to `plans/remote-mode.md` — `remote.py`'s listener separation, `qr.py`'s zero-dependency SVG encoder, the frontmatter spacing fix, and the Markdown-stripped TODO anchor fix are all solid. Below are the real bugs and UX gaps found in the code.

---

## High-priority bugs

### 1. Unread `stderr=subprocess.PIPE` on `tailscale serve` can deadlock phone traffic
- **Where:** `proseview/remote.py:197-215`
- **What happens:** `RemoteSession.start()` starts `tailscale serve` with `stderr=subprocess.PIPE` and only reads `stderr` if `wait(timeout=2)` returns early. On the normal success path (`code is None`), nothing ever reads from `self._serve.stderr`. Over a long session, once `tailscale serve` writes ~64 KB of proxy warnings or connection resets, the OS pipe buffer fills and `tailscale serve` blocks indefinitely on `write(2)`, freezing all phone requests until Proseview is restarted.
- **Fix:** Drain `self._serve.stderr` in a daemon thread (optionally keeping the last few lines for diagnostics and logging if `tailscale serve` exits unexpectedly mid-session).

### 2. AI chat breaks ("Reload") after the Mac sleeps and you tap Retry
- **Where:** `proseview/templates/assets/js/68-discuss.js:4070-4075`, `proseview/templates/assets/js/90-phone.js:137-154`
- **What happens:** When the Mac sleeps while `#discussPanel` is open, `tailscale serve` returns `502`, closing `/api/discuss/conversations/<cid>/events` (`source.readyState === EventSource.CLOSED`).
  - `60-selection.js` checks `pvConnectionDown('closed')` for `/events` to tell a sleeping Mac apart from a server restart, but `68-discuss.js:4072` does not — it immediately calls `showDiscussReloadRequired(source)`, permanently disabling `#discussSend`, changing its label to `"Reload"`, and telling the user Proseview restarted.
  - When the Mac wakes and you tap **Retry** on the offline banner, `pvPhone.retry()` only reconnects `/events` (`pvReconnectEvents()`) and never reconnects `_discussEventSource` or restores `#discussSend`.
- **Fix:** Route `EventSource.CLOSED` in `68-discuss.js` through the same Mac-asleep vs. restarted check, and expose a reconnect hook so `pvPhone.retry()` and `visibilitychange` also reconnect the active chat stream and re-enable `#discussSend` when the server is the same process.

### 3. `openQuickEdit()` race while `Opening…` can wipe typed text or re-open a closed sheet
- **Where:** `proseview/templates/assets/js/90-phone.js:473-511`
- **What happens:** `openQuickEdit()` shows `#pvEditSheet` immediately (`Opening…`) while `loadFresh(target)` is still in flight over Tailscale, without disabling `#pvEditText` or `#pvEditSave` and without cancelling stale callbacks.
  - If the user taps **Cancel** before `loadFresh` resolves, `closeEditSheet()` hides the sheet, and then `loadFresh.then()` runs and pops the closed sheet back open.
  - If the user begins typing before `loadFresh` resolves, `show()` overwrites `area.value` and wipes what they typed.
- **Fix:** Increment an open-generation counter (ignore `.then`/`.catch` if the sheet closed or another open started) and disable `#pvEditText` and `#pvEditSave` while `Opening…`.

### 4. Offline Quick edit draft drops recent typing on Cancel
- **Where:** `proseview/templates/assets/js/90-phone.js:503, 521-531`
- **What happens:** When Quick edit opens offline from an existing draft, `state.edit.original` is set to `null`. In `cancelQuickEdit()`, the check `e.original !== null && area.value !== e.original` is `false`, so tapping **Cancel** within the 400 ms debounce window skips flushing the latest typing to `localStorage` (and skips the "Draft kept" toast).
- **Fix:** Call `clearTimeout(keepEditDraft.timer)` in `cancelQuickEdit()` and write the draft whenever `e.original === null || area.value !== e.original`.

---

## Medium bugs & UX issues

### 5. `refreshSceneIfChangedOnDisk()` is a no-op if save/TODO completes before SSE arrives
- **Where:** `proseview/templates/assets/js/90-phone.js:565, 762`, `proseview/templates/assets/js/60-selection.js:1219-1221`
- **What happens:** After `/save-scene`, `/insert-todo`, or `/add-note` succeeds, `90-phone.js` calls `refreshSceneIfChangedOnDisk(path)`, which only refreshes if `_scenesChangedOnDisk[path]` was already set by an SSE `reload` event. If the HTTP response lands ahead of SSE (or while SSE is reconnecting), the scene and `meta[path].mtime` stay stale — adding a second TODO immediately after the first can hit a false `409` conflict against your own edit.
- **Fix:** Call `refreshContent([path])` directly on success (`_refreshInFlight` already deduplicates overlapping SSE refreshes).

### 6. Privacy screen phone UX gaps
- **Where:** `proseview/templates/assets/js/90-phone.js:338-346, 378-393`, `proseview/templates/index.html.j2:150-152`
- **Issues:**
  1. **No Cover button in Read the book:** `data-view="book"` hides both `.toolbar-actions` (`#pvCoverTop`) and `#pvSceneBar`, so you can't cover the screen while reading the book without leaving it first.
  2. **Cannot dismiss `#privacyPassword` once revealed:** `watchCoverTaps()` returns early when `!box.hidden`, and phones have no `Escape` key — once opened, the only way to hide the password field again is submitting a wrong password.
  3. **iOS keyboard & submit risk:** Focusing `#privacyPassword` inside `pointerup` (rather than `click`/`touchend`) can fail to open the iOS virtual keyboard, and `#privacyPassword` is a bare `<input>` outside a `<form>` with no visible Submit/Cancel buttons (mobile keyboards may show `Done` instead of `Go`).
- **Fix:** Add a Cover button in the book header on phone, allow double-tapping again (or a small Cancel button) to dismiss `#privacyPassword`, and wrap `#privacyPassword` in a `<form>` (or add a small Unlock button on phone) triggered from `click`.

### 7. Add TODO/Note conflict loses the saved draft if the paragraph text changed on the Mac
- **Where:** `proseview/templates/assets/js/90-phone.js:676-677, 751-753`
- **What happens:** On a `409` conflict, the sheet tells the user `"Your text is kept; close and tap the paragraph again."` However, `openNoteSheet()` only restores the draft if `draft.anchor === pill.dataset.text` (exact string match). If the Mac edited even one word inside that paragraph, tapping it again opens an empty textarea and the draft looks gone.
- **Fix:** Restore any pending per-scene note draft even if the anchor text changed slightly (or keep the sheet open with a Retry action after refreshing `meta[n.path]`).

### 8. Several Mac-only controls are still exposed on the phone UI
- **Where:** `proseview/templates/assets/app.css:20849-20856`, `proseview/templates/assets/js/75-file-management.js:314`
- **What happens:**
  - `#filePreviewEditorBtn` ("Open in VS Code" in note preview's `…` menu) is not hidden under `html[data-remote="phone"]` (only `#modalEditorBtn` is).
  - **Reveal in Finder** in the sidebar file menu (`75-file-management.js:314`) is still shown on the phone and fails with 403 when tapped.
  - `#privacySettingsRow` (Set/Change/Remove privacy password) is still shown in Settings on the phone and fails with 403 (`/api/privacy/password`).
  - `#settingsOpenBtn` remains in the phone top bar and opens the full desktop Settings dialog (book goal, backups, AI settings, etc.), even though the plan calls for hiding most settings on phone.
- **Fix:** Hide `#filePreviewEditorBtn`, `#privacySettingsRow`, and the sidebar Reveal menu item when `data-remote="phone"`, and trim or hide Settings on phone (theme/font/size are already available in the `Aa` menu).

---

## Minor polish & housekeeping

- **`X-Forwarded-Host` fallback in `RemoteGate.allows()` (`proseview/remote.py:162-167`):** When `Host` doesn't match `dns_name`, requiring `Host` to be loopback (`127.0.0.1` / `localhost`) before trusting `X-Forwarded-Host` is slightly tighter defense-in-depth (not exploitable behind `tailscale serve`, since Serve overwrites `X-Forwarded-Host`).
- **Phone Home doesn't live-refresh while open (`90-phone.js:820`):** `renderHome()` only runs on init and when `data-view` transitions back to `""`. If an SSE `reload` updates TODOs or scenes while the phone is sitting on Home, the list won't update until you open a scene and return.
- **Uncommitted working-tree files:**
  - The privacy Cover button + double-tap uncover changes in `90-phone.js` and `app.css` are currently uncommitted and have no E2E test yet in `test_phone_e2e.py`.
  - `tests/e2e/test_labels_e2e.py` has an unrelated uncommitted CI-debugging `try/except` block worth checking before committing.

---

## Additional findings from the working-tree review (2026-11-26)

Reviewed `200ddee` plus the working-tree fixes being made during this review. The findings below are additional to items 1–8; their locations refer to the working tree, so function names are included as well as line numbers.

**Validation:** 104 tests in `test_remote.py`, `test_note_edit.py`, `test_annotations.py` and `test_cli.py` pass, as do all 17 current Playwright phone tests. Separate browser reproductions confirm items 9, 11, 13 and 14; direct Python reproductions confirm items 10 and 12. This pass did not exercise a live Tailscale proxy or a physical iPhone/Safari.

### 9. [P1] Typing while Save is pending can be permanently lost

- **Where:** `proseview/templates/assets/js/90-phone.js:567`, `saveQuickEdit()` and its success callback.
- **What happens:** Save captures `area.value` and disables only the Save button. The textarea remains editable while the request is in flight. When the response arrives, the callback unconditionally clears the file's draft and closes the sheet, even if more text was typed after the submitted snapshot. Those later words are absent from the saved file and their already-persisted draft is deleted.
- **Reproduction:** Delay the `/save-scene` response, keep typing or dictating into Quick edit, wait more than the 400 ms draft debounce, then release a successful response. The sheet closes and the new words are missing from both disk and `localStorage`. Confirmed in a browser with an intercepted response.
- **Fix:** Either make the editor read-only for the duration of Save, or track edit generations and clear/close only when the current text still matches the submitted snapshot. If editing continues, retain the newer draft and update its baseline to the successful save's returned mtime. Also ignore an old save callback if its sheet has been closed or replaced.

### 10. [P2] Remote setup errors crash while trying to print the error

- **Where:** `proseview/server.py`, `serve()`'s `RemoteSession.prepare()` exception handler (around line 4088) and the later function-local `import sys` (around line 4306).
- **What happens:** The later `import sys` makes `sys` local throughout `serve()`. If preflight raises `RemoteError`, the early handler accesses that local before it has been assigned. Missing Tailscale, HTTPS being disabled, a tagged laptop, or an occupied Serve mapping therefore produces `UnboundLocalError` instead of the intended plain setup message and exit code.
- **Reproduction:** Patch `RemoteSession.prepare` to raise `RemoteError("Tailscale is not installed")`, then call `serve(root, remote=True)`. Confirmed result: `UnboundLocalError: cannot access local variable 'sys' where it is not associated with a value`.
- **Fix:** Remove the function-local import and use the module import, or import `sys` before preflight. Add a test that calls `serve()` through this failure path; the current tests exercise the helper errors without invoking this handler.

### 11. [P2] A pending draft timer recreates a draft after a successful save

- **Where:** `proseview/templates/assets/js/90-phone.js:477`, `keepEditDraft()`, and `saveQuickEdit()`'s success callback.
- **What happens:** An input event schedules a draft write in 400 ms. A fast successful save clears the draft but leaves that timer running. Its callback still holds the old editor state and writes the saved text back with the pre-save mtime. Reopening Edit then says an unsaved draft was restored, and saving it raises a conflict against the user's own previous save. This is separate from item 4's Cancel path, which now clears its timer.
- **Reproduction:** Change the textarea and immediately press Save before the debounce expires. After the sheet closes, wait 400 ms, reopen Edit, and save again. Confirmed in a browser: the stale draft returns and the conflict sheet appears.
- **Fix:** Cancel pending draft writes when taking a save snapshot and when successfully saving or discarding. Scope each delayed callback to the active editor generation so it cannot write after that editor has closed or changed files.

### 12. [P2] TODO/Note can attach to a different paragraph sharing its first 50 characters

- **Where:** `proseview/server.py:1341`, `_annotation_insert_line()`; the phone sends the selected paragraph through `addNote()` in `90-phone.js`.
- **What happens:** The helper truncates the selected paragraph to 50 characters and takes the first match. Clicking a later paragraph with the same opening as an earlier one inserts the annotation above the earlier paragraph, even when the full paragraphs differ. The Markdown-stripping fallback preserves the same ambiguity. The existing helper bug is now exposed through the phone's paragraph-tap flow.
- **Reproduction:** Use two paragraphs beginning `Alice counted the cards upon the table with careful attention, ` and ending differently. Pass the full second paragraph as `selection_text`. Confirmed with the helper: the selected paragraph starts on line 2, but the annotation insertion line returned is 0.
- **Fix:** Match the complete rendered paragraph before considering a shorter anchor, and carry a validated paragraph position to distinguish repeated paragraphs. Refuse ambiguous matches rather than silently choosing the first one. Cover shared prefixes and identical repeated paragraphs in tests.
- **Remaining after the fix:** The new shared-prefix tests pass, but raw Markdown matches still take precedence over all rendered-text matches. If the selected paragraph starts `*Alice* counted the cards upon the table with careful attention, ...` and a later paragraph has the same opening without the emphasis, only the later paragraph enters `candidates`. The phone's correct `paragraph_line` then produces a false “paragraph has moved” error. Confirmed with `_annotation_insert_line()` on an unchanged file. Include both raw and normalized candidates before applying the supplied paragraph position, and test a formatted paragraph followed by a similar unformatted paragraph.

### 13. [P2] An idle laptop covers a phone that is actively being used

- **Where:** `proseview/templates/assets/js/03-privacy.js:55`, `privacyReadLastActivity()`, `privacyWriteLastActivity()` and `privacyCheckIdle()`.
- **What happens:** Activity is synchronized only through browser-local `localStorage`, while an idle timeout calls the server-wide `/api/privacy/lock`. With the idle lock enabled, the untouched laptop cannot see activity on the phone and covers both screens when its own timer expires, interrupting reading, typing or chat on the phone. The phone's `.ts.net` origin also cannot share storage with the laptop's `localhost` origin.
- **Reproduction:** Open laptop and phone in separate browser contexts, enable the one-minute idle lock, record fresh activity on the phone, and expire the laptop's activity timestamp. Confirmed in a browser: the phone's privacy screen opens despite activity less than a second earlier.
- **Fix:** Coordinate last activity through the server before applying an automatic lock to all clients. Keep explicit Cover synchronized, and test an idle laptop alongside an actively typing phone.

### 14. [P3] Quick edit is offered for file types the save endpoint rejects

- **Where:** `proseview/templates/assets/js/90-phone.js:361`, `syncBar()`, and `openQuickEdit()`.
- **What happens:** The phone disables Edit only for `.yaml` and `.yml`. Other readable text files can open in Quick edit even though `/api/files/save` accepts only Markdown and YAML. A user can edit or dictate into a `.txt` file and then discover that every save is refused.
- **Reproduction:** Open a visible `story-bible/example.txt` file on the phone. Edit is enabled, the textarea loads normally, and Save returns `Only Markdown and YAML files can be edited in the dashboard`. Confirmed in a browser.
- **Fix:** Enable phone Quick edit only for scenes and supported Markdown suffixes (`.md` and `.markdown`); keep other file previews read-only and guard `openQuickEdit()` as well as the button.

---

## Follow-up after fixes (2026-11-26)

**Validation:** 125 tests across `test_remote.py`, `test_note_edit.py`, `test_annotations.py`, `test_cli.py` and `test_privacy.py` pass, along with all 20 current Playwright phone tests. Additional browser reproductions confirm the four findings below. Item 12 also has a remaining formatted-text matching case, recorded above. Live Tailscale and physical iPhone/Safari checks remain outside this pass.

### 15. [P1] TODO/Note still loses text typed while Add is pending

- **Where:** `proseview/templates/assets/js/90-phone.js:784`, `addNote()`.
- **What happens:** The Quick edit fix makes its textarea read-only during Save, but the TODO/Note textarea remains editable during Add. A successful response clears the per-scene draft and closes the sheet without checking whether newer text was entered. Any words typed or dictated after submission disappear from both disk and the already-updated local draft. A callback can also close a replacement note sheet because it never checks `state.note === n`.
- **Reproduction:** Hold the `/insert-todo` response, type additional words into the note sheet, then release the successful response. Confirmed in a browser: the submitted TODO is saved, but the later words are absent from disk and `localStorage`.
- **Fix:** Apply the same snapshot/read-only protection to TODO and Note saves, and scope response callbacks to the note operation that initiated them before clearing drafts or changing the sheet.

### 16. [P2] Reloading before the draft debounce loses the latest Quick edit input

- **Where:** `proseview/templates/assets/js/90-phone.js:482`, `keepEditDraft()`, and `init()`'s visibility handler.
- **What happens:** Draft persistence still waits 400 ms. There is no flush on page exit or when the page becomes hidden. Reloading immediately after an input restores the previous persisted draft and loses the most recent text; the previous “Draft saved” indicator also remains visible during this window.
- **Reproduction:** Wait for an initial draft to be saved, append more text, and reload immediately in the same browser task. Confirmed in a browser: reopening Quick edit restores only the initial draft.
- **Fix:** Persist synchronously on input, as the note sheet already does, or flush pending draft writes on `pagehide` and when visibility becomes hidden. Add an immediate-reload regression test rather than waiting for the debounce before reloading.

### 17. [P2] Cancelling a pending save leaves the next Quick edit sheet read-only

- **Where:** `proseview/templates/assets/js/90-phone.js`, `saveQuickEdit()` (around line 573), `closeEditSheet()` and `openQuickEdit()`'s `show()` callback.
- **What happens:** Save sets the shared textarea's `readOnly` property. Cancel stays available, but closing and reopening the sheet never resets that property. A different file therefore opens read-only until the previous request finishes. The old request's callbacks also change the shared Save button and textarea before checking `state.edit !== e`, so a stale response can alter a newer editor's save state.
- **Reproduction:** Hold a scene save, tap Cancel, navigate to a Markdown note without reloading, and open Edit. Confirmed in a browser: the note loads and its textarea is enabled, but it still has the `readonly` attribute.
- **Fix:** Initialize read-only state for each editor opening and check operation identity before any callback mutates shared controls. Keep pending-save state scoped to the editor that owns the request.

### 18. [P2] An unclosed HTML comment makes the book show raw Markdown and author notes

- **Where:** `proseview/templates/assets/js/68-discuss.js:6068`, the `hideComments` branch in `appendMarkdownTokens()`, called by Read the book.
- **What happens:** For `<!-- unfinished`, the comment-removal regex removes nothing because it requires `-->`. The unchanged text is lexed and recursively rendered again until the call stack overflows. `renderSafeMarkdown()` catches that exception and replaces the entire scene with its raw source, exposing Markdown syntax and otherwise-hidden TODO/Note comments.
- **Reproduction:** Render a scene containing formatted prose, a complete TODO comment, and an unclosed comment with `{hideComments: true}`. Confirmed in a browser: the inner renderer raises `RangeError`; the public renderer falls back to a plain text node containing the raw Markdown and the complete TODO comment.
- **Fix:** Handle comments that continue to the end of the input, and recurse only when stripping comments has made progress. Test an unclosed comment alongside a normal TODO to ensure prose stays formatted and comments remain hidden.
