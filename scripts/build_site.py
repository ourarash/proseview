"""Build the website: the landing page, and Proseview in the browser at write/.

The Alice demo goes in demo/, written by `proseview snapshot` (see
.github/workflows/pages.yml). Pyodide comes from its npm package:

    npm install --prefix /tmp/pyodide pyodide@314.0.7
    python scripts/build_site.py --out _site --pyodide /tmp/pyodide/node_modules/pyodide

Everything the site loads is copied into it, so it depends on no CDN.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
PACKAGE = REPO / "proseview"

PYODIDE_FILES = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json")
#: Dependencies the browser cannot run: Typst makes PDFs and is a native binary.
NOT_IN_BROWSER = {"typst"}
#: README images the landing page shows.
LANDING_IMAGES = (
    "dashboard.png", "write-a-scene.png", "demo-writing.gif", "demo-highlights.gif",
    "demo-timeline.gif", "demo-agents.gif", "export-preview.png", "storylines.png",
)


def _dependencies() -> list[str]:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = [re.split(r"[<>=!~ ;\[]", spec, maxsplit=1)[0] for spec in project["dependencies"]]
    return [spec for spec, name in zip(project["dependencies"], names) if name.lower() not in NOT_IN_BROWSER]


def _epub_fonts() -> set[str]:
    """Fonts an e-book embeds; the rest are for PDFs, which the browser cannot make."""
    fonts: set[str] = set()
    for style in (PACKAGE / "book_styles").glob("*/style.yaml"):
        for line in style.read_text(encoding="utf-8").splitlines():
            if line.startswith("epub_fonts:"):
                fonts.update(re.findall(r"[\w.-]+\.(?:ttf|otf)", line))
    return fonts


def _add_tree(archive: zipfile.ZipFile, folder: Path, prefix: str, skip) -> None:
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if path.is_file() and "__pycache__" not in relative.parts and not skip(relative):
            archive.write(path, f"{prefix}/{relative.as_posix()}" if prefix else relative.as_posix())


def build_app_zip(out: Path) -> None:
    """Proseview and its pure-Python dependencies, unpacked into /app by the worker."""
    fonts = _epub_fonts()

    def skip_package(relative: Path) -> bool:
        if relative.parts[:2] == ("templates", "vendor"):
            return True  # served as files next to the page
        return relative.parts[:2] == ("book_styles", "fonts") and relative.suffix in {".ttf", ".otf"} \
            and relative.name not in fonts

    def skip_dependency(relative: Path) -> bool:
        # Compiled speedups are for this machine, not the browser; each
        # package falls back to its pure-Python code without them.
        return relative.suffix in {".so", ".pyd"} or relative.parts[0].endswith(".dist-info") \
            or relative.parts[0] == "bin"

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--target", tmp, *_dependencies()],
            check=True,
        )
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            _add_tree(archive, PACKAGE, "proseview", skip_package)
            _add_tree(archive, Path(tmp), "", skip_dependency)


def build_write(out: Path, pyodide: Path) -> None:
    out.mkdir(parents=True)
    for name in ("index.html", "worker.js", "sw.js"):
        shutil.copyfile(SITE / "write" / name, out / name)
    (out / "pyodide").mkdir()
    for name in PYODIDE_FILES:
        shutil.copyfile(pyodide / name, out / "pyodide" / name)
    shutil.copytree(PACKAGE / "templates" / "vendor", out / "vendor")
    build_app_zip(out / "app.zip")


def build_landing(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "landing.css"):
        shutil.copyfile(SITE / name, out / name)
    (out / "images").mkdir(exist_ok=True)
    for name in LANDING_IMAGES:
        shutil.copyfile(REPO / "docs" / "images" / name, out / "images" / name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="Folder to write the site into.")
    parser.add_argument("--pyodide", type=Path, required=True, help="The unpacked pyodide npm package.")
    args = parser.parse_args(argv)
    missing = [name for name in PYODIDE_FILES if not (args.pyodide / name).is_file()]
    if missing:
        parser.error(f"{args.pyodide} is missing {', '.join(missing)}")
    if (args.out / "write").exists():
        shutil.rmtree(args.out / "write")
    build_landing(args.out)
    build_write(args.out / "write", args.pyodide)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
