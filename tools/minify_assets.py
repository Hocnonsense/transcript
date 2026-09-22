"""Regenerate the minified browser assets embedded in exported pages.

Every ``.js``/``.css`` under ``src/snakedone/html/_assets`` is minified with
esbuild into a sibling ``*.min.*`` file.  The exporters prefer those files, so
run this after editing any asset (``pixi run minify``); the test suite fails if
the committed output is stale.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "src/snakedone/html/_assets"
SOURCES = sorted((*ASSETS.glob("*.js"), *ASSETS.glob("*.css")))


def minified_name(path: Path):
    return f"{path.stem}.min{path.suffix}"


def main():
    esbuild = shutil.which("esbuild")
    if esbuild is None:
        print("esbuild not found on PATH", file=sys.stderr)
        return 1
    for path in SOURCES:
        if ".min." in path.name:
            continue
        target = path.with_name(minified_name(path))
        subprocess.run(
            [
                esbuild,
                str(path),
                "--minify",
                "--charset=utf8",
                "--target=es2020",
                f"--outfile={target}",
            ],
            check=True,
        )
        print(f"{path.name} -> {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
