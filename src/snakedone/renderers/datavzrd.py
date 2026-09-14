"""Datavzrd renderer: snapshot DataFrames and build offline table reports."""

import json
import mimetypes
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..output import Renderer, dataframe_csv
from . import jsonify, load_spec, register

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


def _validate_config(config: dict[str, Any]):
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


def datavzrd(frame: Any, config: Mapping[str, Any] | str | Path | None = None):
    """Record a DataFrame for Datavzrd table rendering during HTML export.

    ``config`` is a native Datavzrd configuration mapping or YAML filename.
    Each view uses the managed dataset ``data``. Relative YAML filenames are
    resolved against the current working directory, like any Python file read.
    The snapshot contains the CSV and configuration, not their original paths.

    A single-view configuration without ``default-view`` opens that view
    directly instead of Datavzrd's landing page. Multiple views keep the
    landing page unless ``default-view`` selects one.
    """
    if config is not None:
        try:
            config = load_spec(config)
        except Exception as error:
            raise ValueError("Invalid Datavzrd configuration") from error
    if config is None:
        config = {}
    elif not isinstance(config, Mapping):
        raise TypeError("Datavzrd config must be a mapping or a YAML filename")
    snapshot = {"views": {"results": {"dataset": "data"}}} | jsonify(
        config, context="Datavzrd config"
    )
    views = snapshot["views"]
    if isinstance(views, dict) and len(views) == 1 and "default-view" not in snapshot:
        snapshot["default-view"] = next(iter(views))
    return Datavzrd(dataframe_csv(frame), snapshot)


@register
class Datavzrd(Renderer):
    """Registered renderer for ``snakedone.datavzrd`` snapshots."""

    name = "datavzrd"
    version = (1,)

    def __init__(self, csv: str, config: dict):
        if not isinstance(csv, str):
            raise ValueError("Datavzrd output data requires CSV string content")
        config_ = jsonify(config, context="Datavzrd config")
        _validate_config(config_)
        self.obj = {"csv": csv, "config": config_}

    def serialize(self):
        """Serialize the CSV and configuration into the archived fence."""
        body = json.dumps(self.obj, sort_keys=True, indent=2, allow_nan=False)
        return body

    @classmethod
    def to_html(cls, data: str):
        """Validate stored data, then return its inner HTML and report files."""
        parsed = cls._validate(data)
        return "", cls._build(parsed)

    @classmethod
    def _validate(cls, data: str):
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as error:
            raise ValueError("Datavzrd output data must be a JSON mapping") from error
        if not isinstance(parsed, dict):
            raise ValueError("Datavzrd output data must be a mapping")
        if not isinstance(parsed.get("csv"), str):
            raise ValueError("Datavzrd output data requires CSV string content")
        if not isinstance(parsed.get("config"), dict):
            raise ValueError("Datavzrd output config must be a mapping")
        _validate_config(parsed["config"])
        return parsed

    @classmethod
    def _build(cls, parsed: dict):
        """Return all report files; no temporary paths survive in the result."""
        executable = shutil.which("datavzrd")
        if executable is None:
            raise RuntimeError(
                "Datavzrd HTML export requires the datavzrd executable on PATH; "
                "install it with: conda install -c conda-forge datavzrd"
            )
        config = parsed["config"]
        dataset = config.setdefault("datasets", {}).setdefault("data", {})
        dataset["path"] = "data.csv"
        with tempfile.TemporaryDirectory(prefix="snakedone-datavzrd-") as directory:
            root = Path(directory)
            (root / "data.csv").write_text(parsed["csv"], encoding="utf-8", newline="")
            (root / "config.yaml").write_text(
                json.dumps(config, ensure_ascii=False, allow_nan=False),
                encoding="utf-8",
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

    runtime = (
        Path(__file__).with_name("datavzrd_runtime.js").read_text(encoding="utf-8")
    )
