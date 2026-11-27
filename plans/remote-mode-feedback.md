# Final feedback on `plans/remote-mode.md`

Reviewed 2026-11-26. Good to implement, with four final clarifications.

## 1. Correct the authentication spike's expected results

The plan currently expects a forged or missing identity header to produce a 403 through `tailscale serve`. Serve strips client-supplied identity headers and inserts the caller's real identity, so an authorized phone should still succeed whether it supplies a forged header or no header at all.

Check these cases separately:

- Through the real HTTPS address, an authorized caller succeeds and client-supplied identity headers cannot change the identity seen by Proseview.
- A different Tailscale identity cannot impersonate the allowed login, even by supplying that login in a header.
- Tagged clients are denied because Serve supplies no user identity header for them.
- At the remote backend listener, a missing or mismatched identity header produces a 403, including on `/`.

Use the pairing fallback only if a client can obtain access under an identity it does not own. See [Tailscale's identity-header documentation](https://tailscale.com/docs/features/tailscale-serve).

## 2. Keep unsaved text accessible during connection failures

The Mac-offline UI must preserve the Quick edit textarea and chat draft, with copying still available. A dropped connection, failed save, or Retry must leave the text in place.

Show the connection message alongside the editor or composer. Retry should reconnect streams and refresh server state without a full page reload or replacing unsaved text. Keep the Quick edit draft's original conflict baseline when reconnecting.

Verify in a browser test that disconnecting during editing and then retrying preserves the draft and its original mtime.

## 3. Avoid accidental triggers on paragraph tap (Add TODO / note)

Opening the "Add TODO / note" sheet immediately on a single paragraph tap will fire constantly while scrolling, resting a thumb, or tapping inside a scene on a phone.

Instead, tapping a paragraph should highlight it and show a small **+ TODO / Note** pill (or trigger via long-press / toolbar button), so normal reading never pops up a sheet by mistake.

## 4. Anchor paragraph TODOs/notes safely on formatted Markdown

`_annotation_insert_line()` in `proseview/server.py` currently checks `selection_text.strip()[:50] in para` directly against the raw Markdown. If a paragraph contains `*italics*`, `**bold**`, or a link in its first 50 characters, sending rendered `textContent` fails to match and raises `_AnnotationAnchorError`.

Pass a paragraph index or raw source anchor (or fall back to matching Markdown-stripped text) so tapping a formatted paragraph inserts the TODO/note reliably.
