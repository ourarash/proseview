"""Proseview command-line entry point.

``python -m proseview`` (or ``proseview``) starts the local HTTP server.
Static-file generation is no longer a separate mode; the server is the
only way to run the dashboard.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .server import DEFAULT_PORT, serve


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="proseview",
        description="Start the proseview dashboard server for a novel repo.",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="Path to the novel repo (default: current directory).")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to listen on (default: {DEFAULT_PORT}).")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="File-watch polling interval in seconds (default: 2.0).")
    parser.add_argument("--no-open", dest="open_browser", action="store_false",
                        default=True, help="Do not auto-open the browser.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Tolerate ``proseview serve`` for muscle-memory; ``serve`` is the
    # only mode now, so the subcommand is purely cosmetic.
    if argv and argv[0] == "serve":
        argv = argv[1:]
    args = parse_args(argv)
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
