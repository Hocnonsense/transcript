"""Build native Datavzrd reports from archived snapshots."""

import copy
import json
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path

from .output import RecordedOutput, validate_output


def build_report(output: RecordedOutput) -> dict[str, tuple[str, bytes]]:
    """Return all report files; no temporary paths survive in the result."""
    validate_output(output)
    executable = shutil.which("datavzrd")
    if executable is None:
        raise RuntimeError(
            "Datavzrd HTML export requires the datavzrd executable on PATH; "
            "install it with: conda install -c conda-forge datavzrd"
        )
    config = copy.deepcopy(output.config)
    dataset = config.setdefault("datasets", {}).setdefault("data", {})
    dataset["path"] = "data.csv"
    with tempfile.TemporaryDirectory(prefix="snakedone-datavzrd-") as temporary:
        root = Path(temporary)
        (root / "data.csv").write_text(
            output.datasets["data"]["content"], encoding="utf-8", newline=""
        )
        (root / "config.yaml").write_text(
            json.dumps(config, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        result = subprocess.run(
            [executable, "config.yaml", "--output", "report"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"Datavzrd failed: {message}")
        report = root / "report"
        files = {}
        for path in sorted(report.rglob("*")):
            if path.is_symlink() or not path.resolve().is_relative_to(report):
                raise ValueError(
                    "Datavzrd report contains a file outside its directory"
                )
            if path.is_file():
                name = path.relative_to(report).as_posix()
                mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                files[name] = (mime, path.read_bytes())
        if "index.html" not in files:
            raise RuntimeError("Datavzrd did not produce an index.html entry point")
        return files


def runtime_source() -> str:
    return Path(__file__).with_name("datavzrd_runtime.js").read_text(encoding="utf-8")
