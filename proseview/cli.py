"""Proseview command-line entry point.

Subcommands:

``proseview serve``
    Start the local HTTP server (default if no subcommand is given).

``proseview init``
    Drop a starter ``.proseview.yaml`` next to a manuscript folder, so a
    new repo gets working defaults without hand-editing config.

``proseview roster``
    Print likely character names found in the prose, for pasting into
    ``characters:``. Suggestion only -- nothing is written.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .roster import DEFAULT_TOP_N, extract_roster
from .server import DEFAULT_PORT, serve


STARTER_CONFIG = """\
# proseview configuration. Every key has a sensible default; this
# file just documents what you can tune. Delete keys you don't want
# to override and proseview will fall back to the built-in defaults.

# Where the manuscript lives.
manuscript_path: manuscript/

# Where character bios live (one .md per character).
characters_path: story-bible/characters

# Where reusable agent prompts live.
skills_path: skills

# Word-count goal for the finished book.
target_words: 80000

# Daily word goal (drives the "days to finish" estimate).
daily_target: 500

# Genre. Sets the typical MTLD range your scenes are compared against:
#   childrens     40-60    contemporary  60-85
#   literary      85-110   speculative   90-120
# Dialogue-heavy prose repeats pronouns and scores lower; world-building
# genres keep introducing distinct nouns and score higher.
genre: contemporary

# Healthy band for local lexical variety (MATTR).
mattr_band: [0.74, 0.77]

# Healthy band for whole-scene lexical variety (MTLD). Uncomment to override
# the genre range above -- worth doing if you have measured your own corpus.
# mtld_band: [60, 85]

# Editor URL handler. One of: vscode, cursor, zed, positron, custom.
editor:
  scheme: vscode

# Folders shown in the file tree alongside the manuscript.
repo_tab:
  folders: [plans, continuity, outline, story-bible, docs, templates]

# Stable shortcuts shown when asking Codex about selected prose.
# Personal favorites are stored in this browser and appear before these.
# discuss:
#   selection_presets:
#     - Is the grammar correct?
#     - Make this more direct.
#     - Check the point of view.

# Whether rendered Markdown may load images.
#   all   - repo images and remote URLs (default)
#   local - only files inside this repo, served by this server
#   off   - none; alt text is shown instead
images:
  mode: all
  # Remote images inside AI replies are blocked by default: there the URL is
  # chosen by the model, and fetching it tells that host you opened the
  # document. Set true only when that network disclosure is acceptable.
  remote_in_agent_output: false
"""


def _add_serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Path to the novel repo (default: current directory).",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="File-watch polling interval in seconds (default: 2.0).",
    )
    parser.add_argument(
        "--no-open", dest="open_browser", action="store_false", default=True,
        help="Do not auto-open the browser.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proseview",
        description=(
            "A local dashboard and AI harness for Markdown-first novel "
            "repositories."
        ),
    )
    sub = parser.add_subparsers(dest="cmd")

    serve_p = sub.add_parser(
        "serve", help="Start the dashboard server (default).",
        description="Start the local HTTP server.",
    )
    _add_serve_args(serve_p)

    init_p = sub.add_parser(
        "init", help="Write a starter .proseview.yaml in the target repo.",
        description="Write a starter .proseview.yaml in the target repo.",
    )
    init_p.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Path to the novel repo (default: current directory).",
    )
    init_p.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing .proseview.yaml.",
    )

    roster_p = sub.add_parser(
        "roster",
        help="Suggest character names found in the manuscript.",
        description=(
            "Scan the prose for likely character names and print them ranked "
            "by mentions. Nothing is written; copy the ones you want into "
            "characters: in .proseview.yaml, or into story-bible/characters/."
        ),
    )
    roster_p.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Path to the novel repo (default: current directory).",
    )
    roster_p.add_argument(
        "--top", type=int, default=DEFAULT_TOP_N,
        help=f"How many candidates to print (default: {DEFAULT_TOP_N}).",
    )
    roster_p.add_argument(
        "--yaml", action="store_true",
        help="Print as a characters: YAML block ready to paste into config.",
    )

    export_p = sub.add_parser(
        "export", help="Compile the whole manuscript, or chosen chapters and scenes, into an EPUB.",
        description=(
            "Compile the manuscript, or a selection of it, into an EPUB. Nothing "
            "else needs installing; --engine pandoc keeps the old pandoc path "
            "for one more release."
        ),
    )
    export_p.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Path to the novel repo (default: current directory).",
    )
    export_p.add_argument(
        "--format", choices=["epub"], default="epub",
        help="Output format (default: epub).",
    )
    export_p.add_argument(
        "--output", type=Path, default=None,
        help="Destination file (default: <root>/exports/<book>-<date>.epub).",
    )
    pick = export_p.add_argument_group(
        "choosing what to export",
        "With none of these, the whole book is exported.",
    )
    pick.add_argument(
        "--chapters", action=_PickAction, kind="chapter", dest="picks", default=None, metavar="LIST",
        help=(
            "Chapters by number, range, folder or title, comma-separated: "
            "--chapters 3,7-9 or --chapters ch03. Repeatable."
        ),
    )
    pick.add_argument(
        "--scenes", action=_PickAction, kind="scene", dest="picks", default=None, metavar="LIST",
        help=(
            "Scenes by path, file name, title, or chapter.scene number, "
            "comma-separated: --scenes ch01/02-down-down-down,4.1. Repeatable."
        ),
    )
    pick.add_argument(
        "--order", choices=["book", "custom"], default="book",
        help="book keeps manuscript order (default); custom keeps the order you listed.",
    )
    pick.add_argument(
        "--selection", default="", metavar="NAME",
        help="Export a selection saved under export.selections in .proseview.yaml.",
    )
    pick.add_argument(
        "--save-selection", default="", metavar="NAME",
        help="Save the chapters and scenes picked here under NAME, then export them.",
    )
    pick.add_argument(
        "--list-selections", action="store_true",
        help="List saved selections, then exit.",
    )
    look = export_p.add_argument_group("how it looks")
    look.add_argument(
        "--style", default="", metavar="NAME",
        help="Book style: a built-in name (classic) or a folder holding epub.css (default: classic).",
    )
    look.add_argument(
        "--scene-titles", action=argparse.BooleanOptionalAction, default=None,
        help="Show scene titles as headings instead of scene breaks (default: the style's choice).",
    )
    look.add_argument(
        "--cover-image", type=Path, default=None,
        help="Cover image: JPEG, PNG, GIF or WebP (default: export.cover_image).",
    )
    look.add_argument(
        "--css", type=Path, action="append", default=None,
        help="Extra stylesheet, applied after the style. Repeatable.",
    )
    export_p.add_argument(
        "--title", default="",
        help="Title (default: export.title in .proseview.yaml, else the repo folder name).",
    )
    export_p.add_argument("--subtitle", default="", help="Subtitle (default: export.subtitle).")
    export_p.add_argument("--author", default="", help="Author (default: export.author).")
    export_p.add_argument(
        "--language", default="", help="Language (default: export.language, else en-US).",
    )
    export_p.add_argument(
        "--epub-version", choices=["epub3", "epub2"], default="",
        help="Try epub2 for older readers (default: export.epub_version, else epub3).",
    )
    export_p.add_argument(
        "--engine", choices=["builtin", "pandoc"], default="builtin",
        help=(
            "builtin needs nothing installed (default). pandoc uses an installed "
            "pandoc as before; it ignores --style and --scene-titles, and will be "
            "removed in a later release."
        ),
    )
    export_p.add_argument(
        "--appendix", action="append", default=None, metavar="FOLDER",
        help=(
            "Repo-relative folder whose Markdown files are appended after the "
            "manuscript, e.g. --appendix plans. Repeatable; appendices appear "
            "in the order given."
        ),
    )
    export_p.add_argument(
        "--list-appendix-folders", action="store_true",
        help="List repository folders that contain Markdown files, then exit.",
    )

    snapshot_p = sub.add_parser(
        "snapshot", help="Write a read-only copy of the dashboard as static files.",
        description=(
            "Write the dashboard as static files any web host can serve: "
            "readable, searchable, and editable nowhere. Paths from this "
            "machine are replaced by the repository's folder name."
        ),
    )
    snapshot_p.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Path to the novel repo (default: current directory).",
    )
    snapshot_p.add_argument(
        "--out", type=Path, required=True,
        help="Folder to write, outside the repository. A previous snapshot there is replaced.",
    )
    snapshot_p.add_argument(
        "--demo", action="store_true",
        help="Let visitors try edit mode too. Their saves stay in their browser tab; nothing is uploaded.",
    )
    snapshot_p.add_argument("--title", default="", help="Page title (default: '<folder> · Proseview').")
    snapshot_p.add_argument("--description", default="", help="Summary shown in link previews.")
    snapshot_p.add_argument(
        "--site-url", default="",
        help="Address the snapshot will be served from, for link previews.",
    )
    snapshot_p.add_argument(
        "--preview-image", type=Path, default=None,
        help="Image shown in link previews; needs --site-url.",
    )

    propose_p = sub.add_parser(
        "propose", help="Create an AI proposal in a running proseview server.",
        description="Create an AI proposal in a running proseview server.",
    )
    propose_p.add_argument("--root", type=Path, default=Path.cwd())
    propose_p.add_argument("--file", required=True, help="Repo-relative manuscript file.")
    propose_p.add_argument("--quote", default="", help="Exact passage to highlight.")
    propose_p.add_argument("--start", type=int, default=None, help="Optional start offset in scene text.")
    propose_p.add_argument("--end", type=int, default=None, help="Optional end offset in scene text.")
    propose_p.add_argument("--start-line", type=int, default=None, help="Optional raw Markdown start line.")
    propose_p.add_argument("--start-col", type=int, default=None, help="Optional raw Markdown start column.")
    propose_p.add_argument("--end-line", type=int, default=None, help="Optional raw Markdown end line.")
    propose_p.add_argument("--end-col", type=int, default=None, help="Optional raw Markdown end column.")
    propose_p.add_argument("--message", required=True, help="Issue summary for the proposal.")
    propose_p.add_argument(
        "--option", action="append", required=True,
        help="Replacement option. Pass multiple times for multiple choices.",
    )
    propose_p.add_argument("--client-id", default=None, help="Optional Proseview browser client id.")

    proposal_p = sub.add_parser(
        "proposal", help="Focus, update, apply, or skip an existing AI proposal.",
        description="Focus, update, apply, or skip an existing AI proposal.",
    )
    proposal_sub = proposal_p.add_subparsers(dest="proposal_cmd", required=True)
    status_p = proposal_sub.add_parser("status")
    status_p.add_argument("id", nargs="?")
    status_p.add_argument("--root", type=Path, default=Path.cwd())
    for name in ("focus", "skip"):
        p = proposal_sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--root", type=Path, default=Path.cwd())
        p.add_argument("--client-id", default=None)
    apply_p = proposal_sub.add_parser("apply")
    apply_p.add_argument("id")
    apply_p.add_argument("--root", type=Path, default=Path.cwd())
    apply_p.add_argument("--option", type=int, default=1)
    apply_p.add_argument("--client-id", default=None)
    update_p = proposal_sub.add_parser("update")
    update_p.add_argument("id")
    update_p.add_argument("--root", type=Path, default=Path.cwd())
    update_p.add_argument("--quote", default=None)
    update_p.add_argument("--start", type=int, default=None)
    update_p.add_argument("--end", type=int, default=None)
    update_p.add_argument("--start-line", type=int, default=None)
    update_p.add_argument("--start-col", type=int, default=None)
    update_p.add_argument("--end-line", type=int, default=None)
    update_p.add_argument("--end-col", type=int, default=None)
    update_p.add_argument("--message", default=None)
    update_p.add_argument("--option", action="append")
    update_p.add_argument("--client-id", default=None)

    # Top-level flags so ``proseview --root X`` (no subcommand) keeps
    # working as a synonym for ``proseview serve --root X``.
    _add_serve_args(parser)
    return parser


class _PickAction(argparse.Action):
    """Collect --chapters and --scenes into one ordered list of picks.

    Both flags share a destination so ``--order custom`` can follow the
    order they were typed in, interleaved.
    """

    def __init__(self, option_strings, dest, kind: str, **kwargs):
        self.kind = kind
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        picks = list(getattr(namespace, self.dest, None) or [])
        tokens = [token.strip() for token in str(values).split(",") if token.strip()]
        if not tokens:
            parser.error(f"{option_string} needs at least one name")
        picks += [(self.kind, token) for token in tokens]
        setattr(namespace, self.dest, picks)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse argv. Returned namespace always has a ``cmd`` attribute
    (defaulting to ``"serve"``) plus the flags for that subcommand.
    """
    args = _build_parser().parse_args(argv)
    if args.cmd is None:
        args.cmd = "serve"
    return args


def suggest_roster(args: argparse.Namespace) -> int:
    """Print ranked character-name candidates found in the prose.

    Deliberately read-only. The candidates are a starting point a writer
    prunes, not a detection the tool acts on by itself.
    """
    from .config import Config
    from .scenes import collect_scene_stats

    root = args.root.resolve()
    cfg = Config.load(root)
    scenes = collect_scene_stats(root, cfg, lexical=False)
    if not scenes:
        sys.stderr.write(f"no scenes found under {root}\n")
        return 1

    candidates = extract_roster([s.text for s in scenes], top_n=args.top)
    if not candidates:
        sys.stderr.write("no character-name candidates found.\n")
        return 1

    if args.yaml:
        sys.stdout.write("characters:\n")
        for name, _ in candidates:
            sys.stdout.write(f"  - {name}\n")
        return 0

    width = max(len(name) for name, _ in candidates)
    sys.stdout.write(f"{len(candidates)} candidates from {len(scenes)} scenes:\n\n")
    for name, count in candidates:
        sys.stdout.write(f"  {name:<{width}}  {count:>5} mentions\n")
    sys.stdout.write(textwrap.dedent(f"""
        These are guesses from capitalisation, so place names and stray words
        will be mixed in. Keep the real characters and drop the rest.

        To use them:
          proseview roster --yaml >> .proseview.yaml   # then edit the list
        or create one file per character under {cfg.characters_dir}/.
    """))
    return 0


def init_repo(root: Path, *, force: bool = False) -> int:
    target = root / ".proseview.yaml"
    if target.exists() and not force:
        sys.stderr.write(
            f"refusing to overwrite {target}; pass --force to replace it.\n"
        )
        return 1
    target.write_text(STARTER_CONFIG, encoding="utf-8")
    sys.stdout.write(f"wrote {target}\n")
    sys.stdout.write(textwrap.dedent("""\
        Next steps:
          1. Create a manuscript/ folder with chapter subfolders (ch01/, ch02/...)
             and one .md per scene.
          2. Edit .proseview.yaml if your repo uses different folder names.
          3. Run ``proseview serve`` to open the dashboard.
        """))
    return 0


def _find_runtime_file(root: Path) -> Path | None:
    cur = root.resolve()
    for candidate in [cur, *cur.parents]:
        path = candidate / ".proseview" / "server.json"
        if path.exists():
            return path
    return None


def _server_runtime(root: Path) -> tuple[str, str]:
    """Return the running server's ``(url, session_token)``.

    Reading the token from ``.proseview/server.json`` is how the CLI proves it
    is a local process rather than a web page: a browser can reach the port,
    but it cannot read a file on disk.
    """
    runtime = _find_runtime_file(root)
    if not runtime:
        raise SystemExit("No running proseview server found. Start `proseview serve` first.")
    try:
        data = json.loads(runtime.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Could not read {runtime}: {exc}") from exc
    url = str(data.get("url") or "").rstrip("/")
    if not url:
        raise SystemExit(f"{runtime} does not contain a server url")
    return url, str(data.get("session_token") or "")


def _server_url(root: Path) -> str:
    return _server_runtime(root)[0]


def _request_json(root: Path, method: str, path: str, payload: dict) -> dict:
    url, token = _server_runtime(root)
    body = json.dumps(payload).encode("utf-8") if method != "GET" else None
    headers = {"X-Proseview-Session": token} if token else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(
        url + path,
        data=body,
        method=method,
        headers=headers,
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Proseview server returned {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"Could not reach proseview server: {exc.reason}") from exc


def create_proposal(args: argparse.Namespace) -> int:
    payload = {
        "file": args.file,
        "quote": args.quote,
        "message": args.message,
        "options": args.option,
        "client_id": args.client_id,
        "created_by": "codex",
    }
    if args.start is not None or args.end is not None:
        if args.start is None or args.end is None:
            raise SystemExit("--start and --end must be provided together")
        payload["range"] = {"start": args.start, "end": args.end}
    line_col = [args.start_line, args.start_col, args.end_line, args.end_col]
    if any(v is not None for v in line_col):
        if any(v is None for v in line_col):
            raise SystemExit("--start-line, --start-col, --end-line, and --end-col must be provided together")
        payload["range"] = {
            "start_line": args.start_line,
            "start_col": args.start_col,
            "end_line": args.end_line,
            "end_col": args.end_col,
        }
    data = _request_json(args.root, "POST", "/ai/proposals", payload)
    if not data.get("ok"):
        sys.stderr.write(f"proposal failed: {data.get('error', 'unknown error')}\n")
        return 1
    prop = data["proposal"]
    sys.stdout.write(f"proposal {prop['id']} created for {prop['file']}\n")
    return 0


def proposal_action(args: argparse.Namespace) -> int:
    cmd = args.proposal_cmd
    payload: dict[str, object] = {}
    if cmd == "status":
        path = f"/ai/proposals/{args.id}" if args.id else "/ai/proposals"
        data = _request_json(args.root, "GET", path, {})
        if not data.get("ok"):
            sys.stderr.write(f"proposal status failed: {data.get('error', 'unknown error')}\n")
            return 1
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return 0
    if getattr(args, "client_id", None):
        payload["client_id"] = args.client_id
    if cmd == "update":
        if args.quote is not None:
            payload["quote"] = args.quote
        if args.start is not None or args.end is not None:
            if args.start is None or args.end is None:
                raise SystemExit("--start and --end must be provided together")
            payload["range"] = {"start": args.start, "end": args.end}
        line_col = [args.start_line, args.start_col, args.end_line, args.end_col]
        if any(v is not None for v in line_col):
            if any(v is None for v in line_col):
                raise SystemExit("--start-line, --start-col, --end-line, and --end-col must be provided together")
            payload["range"] = {
                "start_line": args.start_line,
                "start_col": args.start_col,
                "end_line": args.end_line,
                "end_col": args.end_col,
            }
        if args.message is not None:
            payload["message"] = args.message
        if args.option:
            payload["options"] = args.option
        data = _request_json(args.root, "PATCH", f"/ai/proposals/{args.id}", payload)
    else:
        if cmd == "apply":
            payload["option_index"] = args.option
        data = _request_json(args.root, "POST", f"/ai/proposals/{args.id}/{cmd}", payload)
    if not data.get("ok"):
        sys.stderr.write(f"proposal {cmd} failed: {data.get('error', 'unknown error')}\n")
        return 1
    prop = data["proposal"]
    sys.stdout.write(f"proposal {prop['id']} {cmd} queued\n")
    return 0


def export_manuscript(args: argparse.Namespace) -> int:
    """Compile the manuscript, or a selection of it, to a file."""
    from .config import Config, ConfigError, ExportSelection
    from .export import (
        ExportError,
        candidate_appendix_folders,
        ensure_gitignored,
        export_book,
        new_book_identifier,
        save_book_identifier,
        save_selection,
        scene_count_summary,
    )

    root = args.root.resolve()
    try:
        cfg = Config.load(root)
    except ConfigError as exc:
        raise SystemExit(f"{root / '.proseview.yaml'}: {exc}") from exc

    if args.list_appendix_folders:
        folders = candidate_appendix_folders(root, cfg)
        if not folders:
            print(f"No folders with Markdown files found in {root}")
            return 0
        print("Folders you can pass to --appendix:")
        for name, count in folders:
            print(f"  {name:<20} {count} file{'s' if count != 1 else ''}")
        return 0

    if args.list_selections:
        if not cfg.export.selections:
            print("No saved selections. Save one with --chapters/--scenes and --save-selection NAME.")
            return 0
        print("Saved selections (export with --selection NAME):")
        for saved in cfg.export.selections:
            described = ", ".join(f"{kind} {token}" for kind, token in saved.picks)
            order = " (custom order)" if saved.order == "custom" else ""
            print(f"  {saved.name}: {described}{order}")
        return 0

    picks = tuple(args.picks or ())
    selection: ExportSelection | None = None
    try:
        if args.selection:
            if picks:
                raise ExportError("Use --selection or --chapters/--scenes, not both")
            selection = cfg.export.selection(args.selection)
            if selection is None:
                names = ", ".join(saved.name for saved in cfg.export.selections) or "none saved yet"
                raise ExportError(f"No saved selection called {args.selection!r} ({names})")
        elif picks:
            selection = ExportSelection(name=args.save_selection, picks=picks, order=args.order)
        if args.save_selection:
            if not picks:
                raise ExportError("--save-selection needs --chapters or --scenes to save")
            save_selection(root, cfg, selection)
            print(f"Saved selection {args.save_selection!r} to {root / '.proseview.yaml'}")

        identifier = cfg.export.identifier or new_book_identifier()
        result = export_book(
            root, cfg, args.output,
            selection=selection,
            title=args.title,
            subtitle=args.subtitle,
            author=args.author,
            language=args.language,
            identifier=identifier,
            epub_version=args.epub_version,
            engine=args.engine,
            style=args.style,
            scene_titles=args.scene_titles,
            cover_image=args.cover_image,
            css=args.css,
            appendix_folders=args.appendix,
        )
        if not cfg.export.identifier:
            save_book_identifier(root, identifier)
            print(f"Saved a book identifier to {root / '.proseview.yaml'}, so re-exports replace this book")
    except ExportError as exc:
        raise SystemExit(str(exc)) from exc
    if args.output is None and ensure_gitignored(root):
        print("Added exports/ to .gitignore")
    print(f"Wrote {result.path}")
    print(scene_count_summary(result.book.scenes))
    return 0


def write_static_snapshot(args: argparse.Namespace) -> int:
    from .snapshot import SnapshotError, write_snapshot

    try:
        out = write_snapshot(
            args.root, args.out, demo=args.demo,
            title=args.title, description=args.description,
            site_url=args.site_url, preview_image=args.preview_image,
        )
    except SnapshotError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote a {'demo' if args.demo else 'read-only'} snapshot to {out}")
    print("Open index.html through any static web server; it does not need Proseview running.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)

    if args.cmd == "init":
        return init_repo(args.root, force=args.force)
    if args.cmd == "roster":
        return suggest_roster(args)
    if args.cmd == "export":
        return export_manuscript(args)
    if args.cmd == "snapshot":
        return write_static_snapshot(args)
    if args.cmd == "propose":
        return create_proposal(args)
    if args.cmd == "proposal":
        return proposal_action(args)

    # Default: serve.
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")
    try:
        serve(
            args.root.resolve(),
            port=args.port,
            watch_interval=args.interval,
            open_browser=args.open_browser,
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
