"""Snapshot explicitly selected rich outputs into portable record blocks."""

import json
import math
import re
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Set for the complete module execution, including document expressions.
document_directory: ContextVar[Path | None] = ContextVar(
    "snakedone_document_directory", default=None
)

_FENCE = re.compile(r"^```snakedone-output[ \t]*(?:\r?\n)?$")
_CLOSE_FENCE = re.compile(r"^```[ \t]*(?:\r?\n)?$")
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


def dataframe_csv(frame: Any) -> str:
    """Export pandas or polars through their public CSV methods, without imports."""
    if callable(getattr(frame, "to_csv", None)) and hasattr(frame, "index"):
        index = frame.index
        include_index = index.name is not None or type(index).__name__ != "RangeIndex"
        content = frame.to_csv(index=include_index, lineterminator="\n")
    elif callable(getattr(frame, "write_csv", None)):
        content = frame.write_csv(line_terminator="\n")
    else:
        raise TypeError("datavzrd expects a pandas or polars DataFrame")
    if not isinstance(content, str):
        raise TypeError("DataFrame CSV export must return a string")
    return content


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
        if name in {".", ".."} or any(char in name for char in "/\\\x00"):
            raise ValueError("Datavzrd view names must be plain directory names")
        if view.get("dataset") != "data" or "datasets" in view:
            raise ValueError(f"Datavzrd view {name!r} must use dataset 'data'")
    if "default-view" in config and config["default-view"] not in views:
        raise ValueError("Datavzrd default-view must name an archived view")


@dataclass(frozen=True, slots=True)
class RecordedOutput:
    """A data and configuration snapshot stored in a snakedone-output fence."""

    renderer: str
    datasets: dict[str, dict[str, str]]
    config: dict[str, Any]
    version: int = 1

    def to_text(self) -> str:
        validate_output(self)
        payload = {
            "version": self.version,
            "renderer": self.renderer,
            "datasets": self.datasets,
            "config": self.config,
        }
        encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False)
        return f"```snakedone-output\n{encoded}\n```\n"

    def __str__(self) -> str:
        return self.to_text().removesuffix("\n")


def validate_output(output: RecordedOutput) -> None:
    """Validate both author-created outputs and restored archive payloads."""
    if type(output.version) is not int or output.version != 1:
        raise ValueError("Unsupported snakedone-output version")
    if output.renderer != "datavzrd":
        raise ValueError("Unsupported snakedone-output renderer")
    if not isinstance(output.datasets, dict) or set(output.datasets) != {"data"}:
        raise ValueError("Datavzrd output must archive exactly the dataset 'data'")
    data = output.datasets["data"]
    if (
        not isinstance(data, dict)
        or data.get("format") != "csv"
        or not isinstance(data.get("content"), str)
    ):
        raise ValueError("Datavzrd output dataset 'data' requires CSV string content")
    if not isinstance(output.config, dict):
        raise ValueError("Datavzrd output config must be a mapping")
    _validate_config(output.config)


def datavzrd(
    frame: Any, config: Mapping[str, Any] | str | Path | None = None
) -> RecordedOutput:
    """Record a DataFrame for Datavzrd table rendering during HTML export.

    ``config`` is a native Datavzrd configuration mapping or YAML filename.
    Each view uses the managed dataset ``data``. Relative YAML filenames are
    resolved against the source document directory when run by snakedone.
    The snapshot contains the CSV and configuration, not their original paths.
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
    output = RecordedOutput(
        renderer="datavzrd",
        datasets={"data": {"format": "csv", "content": dataframe_csv(frame)}},
        config=snapshot,
    )
    validate_output(output)
    return output


def split_output(text: str) -> Iterator[str | RecordedOutput]:
    """Split recognized blocks while retaining ordinary text and future formats."""
    lines = text.splitlines(keepends=True)
    cursor = 0
    plain_start = 0
    while cursor < len(lines):
        if not _FENCE.fullmatch(lines[cursor]):
            cursor += 1
            continue
        end = cursor + 1
        while end < len(lines) and not _CLOSE_FENCE.fullmatch(lines[end]):
            end += 1
        if end == len(lines):
            raise ValueError("Unterminated snakedone-output block")
        try:
            payload = json.loads("".join(lines[cursor + 1 : end]))
        except json.JSONDecodeError as error:
            raise ValueError("Invalid JSON in snakedone-output block") from error
        if (
            not isinstance(payload, dict)
            or type(payload.get("version")) is not int
            or not isinstance(payload.get("renderer"), str)
        ):
            raise ValueError("snakedone-output requires integer version and renderer")
        if payload["version"] != 1 or payload["renderer"] != "datavzrd":
            cursor = end + 1
            continue
        output = RecordedOutput(
            version=payload["version"],
            renderer=payload["renderer"],
            datasets=payload.get("datasets"),
            config=payload.get("config"),
        )
        validate_output(output)
        if plain_start < cursor:
            yield "".join(lines[plain_start:cursor])
        yield output
        cursor = end + 1
        plain_start = cursor
    if plain_start < len(lines):
        yield "".join(lines[plain_start:])
