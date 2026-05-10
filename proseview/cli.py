"""Proseview command-line entry point.

Subcommands:

``proseview serve``
    Start the local HTTP server (default if no subcommand is given).

``proseview init``
    Drop a starter ``.proseview.yaml`` next to a manuscript folder, so a
    new repo gets working defaults without hand-editing config.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

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

# Healthy band for local lexical variety (MATTR).
mattr_band: [0.74, 0.77]

# Healthy band for whole-scene lexical variety (MTLD).
mtld_band: [105, 130]

# Editor URL handler. One of: vscode, cursor, zed, positron, custom.
editor:
  scheme: vscode

# Folders shown in the file tree alongside the manuscript.
repo_tab:
  folders: [plans, continuity, outline, story-bible, docs, templates]
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


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)

    if args.cmd == "init":
        return init_repo(args.root, force=args.force)

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
