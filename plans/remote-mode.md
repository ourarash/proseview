# Remote mode: use Proseview on the phone while it runs on the laptop

Status: plan only, nothing built. Revised 2026-11-26 after `plans/remote-mode-feedback.md` and Ari's scope call.

## Recommendation

`proseview --remote` publishes the laptop's Proseview on the tailnet with `tailscale serve` and trusts Tailscale's login header, so there's no pairing to build. The first version (v1) gives the phone reading, a plain-text Quick edit that works with dictation, one-tap TODOs and notes, and a simple AI chat. About 5 days.

## How it works today

- The server listens on `localhost` only. `_is_local_request()` requires a loopback `Host` and `Origin`.
- Writes need the `X-Proseview-Session` token, which is printed into the page. So **anyone who can load `/` can do everything**, and remote requests must be gated before the page is served.
- `/events` retries silently every 3 seconds, so nothing tells the writer the connection is gone.

## v1

### 1. Access (about 1 day)

- `--remote` goes in `_add_serve_args()`. Proseview opens a **second loopback listener just for Tailscale** and runs `tailscale serve` in the foreground, pointed at that listener. It prints `https://<laptop>.<tailnet>.ts.net`.
- **Gate by listener, not by header presence:**
  - The desktop listener stays exactly as today.
  - Every request on the remote listener must carry `Tailscale-User-Login`, and it must equal the laptop's own login (read from `tailscale status --json`).
  - A request with a missing or different login gets a 403, including on `/`. A missing header must never count as the laptop, because Tailscale sends no identity header for tagged devices.
  - Host and Origin must match the exact laptop name, not just any `.ts.net` name.
- **Proseview owns only its own serve mapping.** Serve runs as a child process supervised by Proseview and stops when Proseview exits.
  - Before starting, read `tailscale serve status --json`. If port 443 is already mapped, or a second book wants remote, stop with a plain message. Some Tailscale versions overwrite a mapping instead of failing, so don't rely on the error.
  - On exit, send SIGINT and wait, so serve removes its own mapping. Only use SIGKILL after a timeout.
  - Never use `tailscale serve reset` or `--bg`.
- **`tailscale status --json` details:**
  - Strip the trailing dot from `Self.DNSName`, and accept an optional `:443` in Host and Origin.
  - Require exactly one `Tailscale-User-Login` value (`headers.get_all`), compared case-insensitively.
  - If the laptop itself is a tagged device, stop with a plain message, since there's no login to match.
- Find Tailscale with `shutil.which`, falling back to `/Applications/Tailscale.app/Contents/MacOS/Tailscale`. If it's missing, or the tailnet doesn't have HTTPS turned on, stop with one plain sentence saying what to do.
- **First, a 1-hour check** that the gate holds. Run it through the real `https://….ts.net` address, not straight against the local port.
  - Serve replaces whatever identity headers a client sends with the real one. So the phone gets in whether it sends a forged header or none, and what Proseview sees is always its true login.
  - A different Tailscale user can't get in, even by sending Ari's login in a header.
  - Tagged devices are refused, because serve sends no login for them.
  - Requests that hit the remote listener directly with a missing or wrong header get a 403, including on `/`.
  - `/events` and a chat stream must arrive at once, without buffering, and stay up past the 15-second heartbeat.
  - Only if someone gets in under a login that isn't theirs, stop and use the pairing design under Later.
- **Laptop-only endpoints** refuse anything arriving on the remote listener: `/api/files/reveal`, `/api/export/open`, `/api/export/reveal`, `/api/discuss/claude/login`, `/api/privacy/password`.
- A small dot on the laptop shows while a phone is connected.
- **QR code for the address:** Settings shows the `https://` address as a QR code, so the phone camera opens it in one tap (a small vendored script, no new Python dependency). After that first visit, Add to Home Screen works like an app. This only saves typing; it isn't a login.
- **Keep the Mac awake:** run `caffeinate -i -w <pid>` while `--remote` is on. The docs should say this works only with the lid open.
- To cut off a lost phone, remove it in the Tailscale admin console. Settings links there.

### 2. Phone layout (about 2 days)

- **Home:** chapters, scenes and Recently modified, plus a Search button. Charts and the scene table are hidden on narrow screens.
- **Read the book:** thumb-sized chapter jump and progress bar, plus the Aa menu.
- **Scenes and notes:** read-only and full width.
- **Privacy screen:** a Cover button, and double-tap to uncover, with the password if one is set.
- **Hidden on the phone:** export, analysis, beat map, illustrations, history and most settings.

### 3. Mac-offline screen (about 0.25 day)

When `/events` or a fetch fails, a banner at the top says "Your Mac is asleep or Proseview stopped", with a Retry button. It's a banner, not a full screen, so whatever you were doing stays usable.
- The Quick edit text, the TODO/note sheet and the chat box stay in place and can still be copied.
- Retry reconnects the streams and refreshes data without reloading the page. The draft keeps its original mtime, so the conflict check still works.
- When the tab becomes visible again, reconnect at once, because iOS leaves half-dead connections behind.
- Browser test: drop the connection mid-edit, then Retry; the draft and its original mtime must survive.

### 4. Quick edit (about 0.5 day)

An Edit button opens the scene or note body as Markdown in a plain `<textarea>`, which works reliably with phone dictation. A sticky Save/Cancel bar stays above the keyboard.

- **Saving:** scenes save through `/save-scene` and other files through `/api/files/save`. Both already keep the frontmatter, and scenes also keep their header, so the textarea holds only the body.
  - Fix an existing bug first: `save_note_content` always writes a blank line after the closing `---`, which adds one to notes that had none.
  - `.yaml` and `.yml` files stay read-only on the phone.
  - Test: open and save a scene and a note that have frontmatter, without changing anything, and each file must stay byte-for-byte the same.
- **Drafts:** each draft is stored in `localStorage` together with the book, the path and the file's original mtime. After a Safari reload, the save still checks against that original mtime, so edits made on the laptop in the meantime raise a conflict instead of being overwritten. A draft is cleared only after a successful save or Discard. A quiet "Draft saved" line confirms each capture, and if storage fails, it says so on screen.
- **Conflict sheet:** if the laptop changed the file meanwhile, the phone doesn't get the desktop diff. It gets a simple sheet with three choices: Keep mine, Copy my draft, Discard and reload.
- **Typing on iOS:** the Save bar and the chat box follow `window.visualViewport`, so the keyboard never hides them. Text boxes use at least 16px type, so Safari doesn't zoom in. Return never sends (`enterkeyhint="enter"`).

### 5. Add TODO / note (about 0.5 day)

On a scene, tapping a paragraph only highlights it and shows a small **+ TODO / Note** pill, so a stray tap while reading never opens anything. Tapping the pill opens the sheet: type or dictate, choose TODO or Note, and tap Add.
- It reuses the existing `/insert-todo` and `/add-note` saves, sending the paragraph as `selection_text` with the line offset. Those saves already have the conflict check.
- Fix the anchor first: `_annotation_insert_line()` looks for the first 50 characters of the text inside the raw Markdown. A paragraph that starts with `*italics*`, bold or a link never matches and fails. When the raw match fails, compare against the paragraph with its Markdown stripped. This also fixes the same failure on the laptop.
- The new TODO or note shows under that paragraph straight away, and on the laptop.
- The sheet uses the same draft keeping, 16px type and above-the-keyboard bar as Quick edit.

### 6. Simple AI chat (about 0.5 day)

The existing chat panel becomes a full-screen sheet on the phone, with the same Codex, Claude and Agy tabs as the laptop. Approvals and the change card behave as they do today.

**Tests:** Playwright phone emulation for the reader, Quick edit, Add TODO / note and chat, plus unit tests for the gate and the laptop-only endpoints. Then one pass on a real iPhone in Safari.

## Later

- **Offline book cache.** The service worker can cache the book (HTTPS from serve allows it); today `sw.js` caches nothing. This needs a cache per book and per version. A refused login must never fall back to the cached copy, and getting a fresh session token on reconnect comes before writes or chat.
- **Pairing fallback,** only if the header check fails:
  - Bind a second socket on the Tailscale IP and treat anything arriving there as remote.
  - The QR code holds a one-time token, used only when the person taps a button (POST), never on page load.
  - The one-time code lasts 10 minutes, allows 5 attempts and is used up in a single step.
  - The device cookie is HttpOnly with `SameSite=Lax`, lasts 30 days (enforced by the server) and is stored as a SHA-256 hash.
  - It runs on plain HTTP, so offline reading and copy buttons stay off unless `tailscale cert` adds HTTPS.
  - Settings gets a Paired phones list with Remove.
- **Approvals that wait on the phone:** today Claude gives up after 10 minutes. The wait should belong to each conversation and survive a dropped connection, coming back on reconnect. It should not depend on whether a phone tab happens to be open.
- One-tap scene reviews, the Group, Tasks, a progress strip.
- Full ProseMirror editing on the phone, only if Quick edit isn't enough.

## Risks

- **A lost phone still on the tailnet can drive the agents,** which can run commands. Remove it in Tailscale. The flag stays opt-in.
- **A closed or sleeping laptop means no access.** The offline screen says so plainly.
- **Laptop and phone saving the same scene.** The existing conflict check covers it, and it needs a test from the phone.
- **iOS Safari is untested.** v1 isn't done until it has been checked on a real phone.
