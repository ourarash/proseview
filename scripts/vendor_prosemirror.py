#!/usr/bin/env python3
"""Vendor the ProseMirror ESM graph into ``templates/vendor/pm/``.

Run once when a ProseMirror version needs changing; the output is committed.
Nothing at runtime or in the test suite invokes this.

Why this exists: the editor used to ``import`` seven packages straight from
esm.sh on every page load. That cost ~170 ms of load time, broke the app
offline, and told a third party each time someone opened their manuscript --
for a tool whose whole pitch is that it is local.

Why it needs a script rather than seven ``curl`` calls: each esm.sh entry is a
shim that re-exports a real ``.mjs`` and pulls in transitive dependencies by
absolute path. This walks that graph, downloads every reachable module once,
and rewrites the import specifiers to sit next to each other on disk.

Shared dependencies matter here. ``prosemirror-model`` is reached from six of
the seven entries, and two copies would mean two ``Schema`` classes and
``instanceof`` checks failing across the boundary. Modules are keyed by
resolved URL, so a shared dependency is downloaded once and every importer
points at that single file -- which is exactly what the ``?deps=`` pinning in
the entry URLs is for.
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

VENDOR_DIR = Path(__file__).resolve().parents[1] / "proseview" / "templates" / "vendor" / "pm"

#: The seven entry points, matching the imports in index.html.j2. The ``deps``
#: pins keep every package resolving to the same shared copies.
PM_MODEL = "prosemirror-model@1.25.4"
PM_STATE = "prosemirror-state@1.4.4"
PM_TRANSFORM = "prosemirror-transform@1.10.4"
_CORE = f"?deps={PM_MODEL},{PM_STATE},{PM_TRANSFORM}"

ENTRIES = {
    "prosemirror-model": f"https://esm.sh/{PM_MODEL}",
    "prosemirror-markdown": f"https://esm.sh/prosemirror-markdown@1.13.4?deps={PM_MODEL}",
    "prosemirror-state": f"https://esm.sh/{PM_STATE}?deps={PM_MODEL},{PM_TRANSFORM}",
    "prosemirror-view": f"https://esm.sh/prosemirror-view@1.41.8{_CORE}",
    "prosemirror-history": f"https://esm.sh/prosemirror-history@1.5.0{_CORE}",
    "prosemirror-keymap": f"https://esm.sh/prosemirror-keymap@1.2.3{_CORE}",
    "prosemirror-commands": f"https://esm.sh/prosemirror-commands@1.7.1{_CORE}",
    "prosemirror-schema-list": f"https://esm.sh/prosemirror-schema-list@1.5.0{_CORE}",
    "prosemirror-inputrules": f"https://esm.sh/prosemirror-inputrules@1.4.0{_CORE}",
}

#: ``from "x"``, ``import "x"``, and ``export ... from "x"``. ESM specifiers are
#: always string literals, so a regex is sufficient and avoids a JS parser.
SPECIFIER_RE = re.compile(r"""(\bfrom\s*|\bimport\s*)(['"])([^'"]+)\2""")

#: ``//# sourceMappingURL=...`` trailers, which point at un-vendored .map files.
SOURCEMAP_RE = re.compile(r"^\s*//[#@]\s*sourceMappingURL=.*$", re.M)


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def local_name(url: str, entry_names: dict[str, str]) -> str:
    """Map a resolved URL to a flat, stable filename inside the vendor dir."""
    if url in entry_names:
        return entry_names[url] + ".js"
    path = urlparse(url).path
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", path.strip("/"))
    return (slug[:-4] if slug.endswith(".mjs") else slug) + ".js"


def main() -> int:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    entry_names = {url: name for name, url in ENTRIES.items()}

    seen: dict[str, str] = {}
    queue = list(ENTRIES.values())

    while queue:
        url = queue.pop()
        if url in seen:
            continue
        print(f"  fetch {url}")
        source = fetch(url)
        seen[url] = source
        for _kw, _q, spec in SPECIFIER_RE.findall(source):
            if spec.startswith("data:"):
                continue
            queue.append(urljoin(url, spec))

    names = {url: local_name(url, entry_names) for url in seen}
    if len(set(names.values())) != len(names):
        print("error: two modules collided on one filename", file=sys.stderr)
        return 1

    for url, source in seen.items():
        def rewrite(match: re.Match[str]) -> str:
            keyword, quote, spec = match.groups()
            if spec.startswith("data:"):
                return match.group(0)
            return f"{keyword}{quote}./{names[urljoin(url, spec)]}{quote}"

        rewritten = SPECIFIER_RE.sub(rewrite, source)
        # Drop the sourceMappingURL comment: the .map files are not vendored, so
        # it would have the browser reach back out to the CDN whenever DevTools
        # is open with source maps enabled -- exactly what vendoring is for.
        rewritten = SOURCEMAP_RE.sub("", rewritten)
        (VENDOR_DIR / names[url]).write_text(rewritten, encoding="utf-8")

    total = sum((VENDOR_DIR / n).stat().st_size for n in names.values())
    print(f"\nvendored {len(names)} modules, {total / 1024:.0f} KB into {VENDOR_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
