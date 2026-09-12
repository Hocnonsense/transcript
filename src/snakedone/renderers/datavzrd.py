"""Datavzrd renderer: snapshot DataFrames and build offline table reports."""

from __future__ import annotations

import copy
import json
import math
import mimetypes
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..output import RecordedOutput, dataframe_csv, document_directory, validate_output
from . import register

_NAMED_MAPPINGS = {"views", "datasets", "columns", "links", "link-to-url", "headers"}
_UNSUPPORTED_OPTIONS = {
    "add-columns",
    "aux-libraries",
    "custom",
    "custom-content",
    "custom-path",
    "custom-plot",
    "render-html",
    "render-img",
    "render-plot",
    "script-path",
    "spec-path",
    "spell",
    "__use_yte__",
}


def _json_value(value: Any) -> Any:
    """Copy configuration so subsequent mutations cannot change a snapshot."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Datavzrd config keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("Datavzrd config must contain JSON-compatible values")


def _check_options(value: Any, location: str = "config", *, properties=True) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            # View, column and link names are user data, not option names.
            is_option = properties or (
                location.endswith(".link-to-url") and key == "custom-content"
            )
            if is_option and (key in _UNSUPPORTED_OPTIONS or key.startswith("?")):
                raise ValueError(
                    f"Datavzrd {location}.{key} is not supported by offline table "
                    "outputs; use built-in render-table options without external "
                    "assets, custom JavaScript, plots, or spells"
                )
            _check_options(
                item,
                f"{location}.{key}",
                properties=not (properties and key in _NAMED_MAPPINGS),
            )
    elif isinstance(value, list):
        for item in value:
            _check_options(item, location)


def _validate_config(config: dict[str, Any]) -> None:
    _json_value(config)
    _check_options(config)
    if config.get("webview-controls", False):
        raise ValueError("Datavzrd webview-controls requires an online service")
    datasets = config.get("datasets", {})
    if not isinstance(datasets, dict) or set(datasets) - {"data"}:
        raise ValueError(
            "Datavzrd config can only configure the archived dataset 'data'"
        )
    options = datasets.get("data", {})
    if not isinstance(options, dict):
        raise ValueError("Datavzrd datasets.data must be a mapping")
    if "path" in options:
        raise ValueError("Datavzrd datasets.data.path is managed by snakedone")
    if options.get("separator", ",") != "," or options.get("headers", 1) != 1:
        raise ValueError("Datavzrd dataset 'data' uses CSV with one header row")
    views = config.get("views")
    if not isinstance(views, dict) or not views:
        raise ValueError("Datavzrd config.views must contain at least one table view")
    for name, view in views.items():
        if not name or not isinstance(view, dict):
            raise ValueError("Datavzrd views must map nonempty names to mappings")
        if (
            name in {".", ".."}
            or name.startswith(" ")
            or any(
                char in "/\\:?#%" or ord(char) < 32 or 127 <= ord(char) <= 159
                for char in name
            )
        ):
            raise ValueError(
                "Datavzrd view names must be plain directory names without "
                "URL delimiters, control characters, or leading spaces"
            )
        if view.get("dataset") != "data" or "datasets" in view:
            raise ValueError(f"Datavzrd view {name!r} must use dataset 'data'")
    if "default-view" in config:
        selected = config["default-view"]
        if not isinstance(selected, str) or selected not in views:
            raise ValueError("Datavzrd default-view must name an archived view")


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


def datavzrd(
    frame: Any, config: Mapping[str, Any] | str | Path | None = None
) -> RecordedOutput:
    """Record a DataFrame for Datavzrd table rendering during HTML export.

    ``config`` is a native Datavzrd configuration mapping or YAML filename.
    Each view uses the managed dataset ``data``. Relative YAML filenames are
    resolved against the source document directory when run by snakedone.
    The snapshot contains the CSV and configuration, not their original paths.

    A single-view configuration without ``default-view`` opens that view
    directly instead of Datavzrd's landing page. Multiple views keep the
    landing page unless ``default-view`` selects one.
    """
    if isinstance(config, (str, Path)):
        try:
            import yaml
        except ImportError as error:
            raise RuntimeError(
                'YAML configuration requires: pip install "snakedone[datavzrd]"'
            ) from error
        path = Path(config)
        if not path.is_absolute() and (directory := document_directory.get()):
            path = directory / path
        try:
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise ValueError(f"Invalid Datavzrd YAML configuration: {path}") from error
        if not isinstance(config, Mapping):
            raise ValueError("Datavzrd YAML configuration must contain a mapping")
    if config is None:
        config = {}
    if not isinstance(config, Mapping):
        raise TypeError("Datavzrd config must be a mapping or a YAML filename")
    snapshot = _json_value(config)
    snapshot.setdefault("views", {"results": {"dataset": "data"}})
    views = snapshot.get("views")
    if isinstance(views, dict) and len(views) == 1 and "default-view" not in snapshot:
        snapshot["default-view"] = next(iter(views))
    output = RecordedOutput(
        renderer="datavzrd",
        datasets={"data": {"format": "csv", "content": dataframe_csv(frame)}},
        config=snapshot,
    )
    validate_output(output)
    return output


class Datavzrd:
    """Registered renderer for ``snakedone.datavzrd`` snapshots."""

    name = "datavzrd"

    def validate(self, output: RecordedOutput) -> None:
        if not isinstance(output.datasets, dict) or set(output.datasets) != {"data"}:
            raise ValueError("Datavzrd output must archive exactly the dataset 'data'")
        data = output.datasets["data"]
        if (
            not isinstance(data, dict)
            or data.get("format") != "csv"
            or not isinstance(data.get("content"), str)
        ):
            raise ValueError(
                "Datavzrd output dataset 'data' requires CSV string content"
            )
        if not isinstance(output.config, dict):
            raise ValueError("Datavzrd output config must be a mapping")
        _validate_config(output.config)

    def build(self, output: RecordedOutput) -> dict[str, tuple[str, bytes]]:
        return build_report(output)

    def runtime(self) -> str:
        return runtime_source()


register(Datavzrd())
