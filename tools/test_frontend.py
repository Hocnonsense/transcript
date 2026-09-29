"""Bundle and run the frontend review tests in node."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "frontend" / "review" / "reviewstore.test.ts"
TARGET = ROOT / ".pixi" / "frontend-test.mjs"


def main():
    esbuild = shutil.which("esbuild")
    if esbuild is None:
        print("esbuild not found on PATH", file=sys.stderr)
        return 1
    node = shutil.which("node")
    if node is None:
        print("node not found on PATH", file=sys.stderr)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            esbuild,
            str(ENTRY),
            "--bundle",
            "--format=esm",
            "--platform=node",
            f"--outfile={TARGET}",
        ],
        check=True,
    )
    return subprocess.run([node, str(TARGET)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
