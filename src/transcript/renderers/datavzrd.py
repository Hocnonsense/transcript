"""Datavzrd renderer: snapshot DataFrames and build offline table reports."""

import json
import mimetypes
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

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


def _check_options(value, location: str = "config", *, properties=True) -> None:
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


def _validate_config(config: dict):
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
        raise ValueError("Datavzrd datasets.data.path is managed by transcript")
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


_NUMERIC_KINDS = "iuf"
_TEXT_LIMIT = 30


def _dtype_is_numeric(dtype):
    """Whether a pandas or polars column dtype is numeric, without imports."""
    is_numeric = getattr(dtype, "is_numeric", None)
    if callable(is_numeric):
        return bool(is_numeric())
    return getattr(dtype, "kind", "") in _NUMERIC_KINDS


def _columns(frame):
    """Yield ``(label, dtype)`` per column, or nothing without dtype info."""
    labels = getattr(frame, "columns", None)
    if labels is None:
        return
    labels = list(labels)
    dtypes = getattr(frame, "dtypes", None)
    if dtypes is not None and len(dtypes) == len(labels):
        pairs = zip(labels, dtypes)
    else:  # polars use schema
        schema = getattr(frame, "schema", None)
        if not isinstance(schema, Mapping):
            return
        pairs = ((label, schema.get(label)) for label in labels)
    yield from pairs


def _text_kind(frame, label):
    """Classify a column as short ``categorical`` text, ``long`` text, or None.

    Only a column whose every non-missing value is a string (or a boolean)
    counts; dates, numbers stored as objects, and anything else return None so
    Datavzrd keeps its own default.
    """
    try:
        series = frame[label]
    except KeyError, TypeError, ValueError:
        return None
    to_list = getattr(series, "to_list", None)
    if not callable(to_list):
        return None
    values = cast("list", to_list())
    longest = 0
    seen = False
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            length = 1
        elif isinstance(value, str):
            length = len(value)
        else:
            return None
        longest = max(longest, length)
        seen = True
    if not seen:
        return None
    return "categorical" if longest <= _TEXT_LIMIT else "long"


def _column_spec(frame, label, dtype):
    """Infer one Datavzrd column spec; ``None`` leaves the column to Datavzrd."""
    if _dtype_is_numeric(dtype):
        return {"plot": {"bars": {}}}
    kind = _text_kind(frame, label)
    if kind == "categorical":
        return {"plot": {"pills": {"color-scheme": "category20"}}}
    if kind == "long":
        return {"ellipsis": _TEXT_LIMIT}
    return None


def _check_input(frame, config: Mapping | str | Path):
    """Load *config* and return ``(csv, snapshot)`` for the archived report.

    ``config`` is a native Datavzrd configuration mapping or YAML filename;
    relative YAML filenames are resolved against the current working directory,
    like any Python file read. Every view must use the managed dataset ``data``,
    and the snapshot holds the CSV and configuration, not their original paths.
    A single view without ``default-view`` opens that view directly instead of
    Datavzrd's landing page; multiple views keep the landing page unless
    ``default-view`` selects one.
    """
    try:
        config = load_spec(config)
    except Exception as error:
        raise ValueError("Invalid Datavzrd configuration") from error
    if not isinstance(config, Mapping):
        raise TypeError("Datavzrd config must be a mapping or a YAML filename")
    snapshot = {"views": {"results": {"dataset": "data"}}} | jsonify(
        config, context="Datavzrd config"
    )
    views = snapshot["views"]
    if isinstance(views, dict) and len(views) == 1 and "default-view" not in snapshot:
        snapshot["default-view"] = next(iter(views))
    return dataframe_csv(frame), snapshot


@register
class datavzrd(Renderer):
    """Registered renderer for ``transcript.datavzrd`` snapshots."""

    name = "datavzrd"
    version = (1,)

    def __init__(self, frame, config: Mapping | str | Path | None = None):
        if config is None:
            config = {}
        csv, config = _check_input(frame, config)
        if not isinstance(csv, str):
            raise ValueError("Datavzrd output data requires CSV string content")
        config_ = jsonify(config, context="Datavzrd config")
        _validate_config(config_)
        self.obj = {"csv": csv, "config": config_}

    @staticmethod
    def infer_config(frame) -> dict[str, Any]:
        """Suggest a configuration from a DataFrame's columns.

        This is opt-in: ``datavzrd(frame)`` omits configuration and keeps
        Datavzrd's own defaults. Pass the result explicitly, for example
        ``datavzrd(frame, datavzrd.infer_config(frame))``, to start from:

        - numeric columns -> a bar plot,
        - short categorical text (or boolean) columns -> pills,
        - text columns whose longest value exceeds ``_TEXT_LIMIT`` -> ellipsis.

        Only the managed single view ``results`` is produced; a column that
        cannot be classified (a non-DataFrame or custom frame, dates, numbers
        stored as objects) is left to Datavzrd, and the plain view is returned
        when nothing can be inferred.
        """
        columns = {}
        for label, dtype in _columns(frame):
            spec = _column_spec(frame, label, dtype)
            if spec is not None:
                columns[str(label)] = spec
        if not columns:
            return {"views": {"results": {"dataset": "data"}}}
        return {
            "views": {
                "results": {
                    "dataset": "data",
                    "render-table": {"columns": columns},
                }
            }
        }

    def serialize(self):
        """Serialize the CSV and configuration into the archived fence."""
        body = json.dumps(self.obj, sort_keys=True, indent=2, allow_nan=False)
        return body

    @classmethod
    def to_html(cls, slot):
        """Validate stored data, then return its inner HTML and report files."""
        parsed = cls._validate(slot.value)
        return cls._htmlout("", cls._build(parsed))

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
        with tempfile.TemporaryDirectory(prefix="transcript-datavzrd-") as directory:
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
