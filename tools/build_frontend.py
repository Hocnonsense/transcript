"""Bundle the authored browser runtime into the assets embedded by Python."""

import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "frontend" / "index.ts"
TARGET = ROOT / "src" / "transcript" / "html" / "_assets" / "transcript.min.js"
ASSETS = TARGET.parent
STYLE = ASSETS / "style.min.css"
STAMP = ASSETS / ".frontend.sha256"


def fingerprint(esbuild: str):
    digest = sha256(Path(__file__).read_bytes())
    digest.update(subprocess.check_output([esbuild, "--version"]))
    srcdir = ROOT / "src" / "frontend"
    for path in sorted(srcdir.rglob("*")):
        if path.suffix in {".ts", ".css", ".json"} and path.is_file():
            if path.with_suffix("").suffix in {".test", ".spec"}:
                continue
            digest.update(str(path.relative_to(srcdir)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    esbuild = shutil.which("esbuild")
    if esbuild is None:
        print("esbuild not found on PATH", file=sys.stderr)
        return 1
    ASSETS.mkdir(parents=True, exist_ok=True)
    current = fingerprint(esbuild)
    if TARGET.is_file() and STYLE.is_file() and STAMP.is_file():
        if STAMP.read_text(encoding="ascii") == current:
            return 0
    subprocess.run(
        [
            esbuild,
            str(ENTRY),
            "--bundle",
            "--format=iife",
            "--minify",
            "--charset=utf8",
            "--target=es2020",
            f"--outfile={TARGET}",
        ],
        check=True,
    )
    subprocess.run(
        [
            esbuild,
            str(ROOT / "src" / "frontend" / "style.css"),
            "--minify",
            "--charset=utf8",
            "--target=es2020",
            f"--outfile={STYLE}",
        ],
        check=True,
    )
    STAMP.write_text(current, encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
