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
        "export", help="Compile the manuscript into an EPUB (requires pandoc).",
        description="Compile the manuscript into a single document via pandoc.",
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
        help="Destination file (default: <root>/output/<repo>.epub).",
    )
    export_p.add_argument("--title", default="", help="Title metadata (default: the repo folder name).")
    export_p.add_argument("--author", default="", help="Author metadata.")
    export_p.add_argument("--language", default="en-US", help="Language metadata (default: en-US).")
    export_p.add_argument(
        "--epub-version", choices=["epub3", "epub2"], default="epub3",
        help="Try epub2 for older readers (default: epub3).",
    )
    export_p.add_argument("--cover-image", type=Path, default=None, help="Cover image passed to pandoc.")
    export_p.add_argument(
        "--css", type=Path, action="append", default=None,
        help="Stylesheet to embed. Repeatable.",
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
    """Compile the manuscript to a file. pandoc is imported lazily on purpose."""
    from .config import Config
    from .export import (
        ExportError,
        candidate_appendix_folders,
        collect_scene_documents,
        export_epub,
        scene_count_summary,
    )

    root = args.root.resolve()
    cfg = Config.load(root)

    if args.list_appendix_folders:
        folders = candidate_appendix_folders(root, cfg)
        if not folders:
            print(f"No folders with Markdown files found in {root}")
            return 0
        print("Folders you can pass to --appendix:")
        for name, count in folders:
            print(f"  {name:<20} {count} file{'s' if count != 1 else ''}")
        return 0

    output = args.output or (root / "output" / f"{root.name}.epub")
    try:
        written = export_epub(
            root, cfg, Path(output),
            title=args.title,
            author=args.author,
            language=args.language,
            epub_version=args.epub_version,
            cover_image=args.cover_image,
            css=args.css,
            appendix_folders=args.appendix,
        )
        summary = scene_count_summary(collect_scene_documents(root, cfg))
    except ExportError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {written}")
    print(summary)
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
