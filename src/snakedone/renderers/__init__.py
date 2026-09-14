"""Registry of ``snakedone-output`` renderer classes.

The ``Renderer`` protocol and the fence format live in :mod:`snakedone.output`;
this package only maps renderer names to their classes and is imported by the
individual renderer modules.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

if TYPE_CHECKING:
    from ..output import Renderer

RENDERERS: dict[str, type[Renderer]] = {}


def register[R: Renderer](renderer: type[R]):
    if not renderer.name:
        renderer.name = renderer.__name__.lower()
    if renderer.name in RENDERERS:
        raise ValueError(f"duplicate renderer: {renderer.name}")
    RENDERERS[renderer.name] = renderer
    return renderer


def get(name: str):
    """Return the registered renderer class, or ``None`` for an unknown name."""
    return RENDERERS.get(name)


@overload
def jsonify(value: Mapping[str, Any], *, context: str = ...) -> dict[str, Any]: ...
@overload
def jsonify(value: list[Any] | tuple[Any, ...], *, context: str = ...) -> list[Any]: ...
@overload
def jsonify(value: Any, *, context: str = ...) -> Any: ...


def jsonify(value: Any, *, context: str = "JSON") -> Any:
    """Copy *value* into JSON-compatible data.

    - ``Mapping`` -> ``dict`` (keys must be strings)
    - ``list``/``tuple`` -> ``list`` (recursively)
    - non-finite ``float`` -> ``None`` (Vega-Lite's missing value)
    - ``date``/``datetime`` -> ISO-8601 string
    - objects with a callable ``.item`` (numpy scalars, ...) are unwrapped
    - everything else raises ``ValueError``
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"{context} keys must be strings")
        return {key: jsonify(item, context=context) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [jsonify(item, context=context) for item in value]

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    item = getattr(value, "item", None)
    if callable(item):
        return jsonify(item(), context=context)

    raise ValueError(f"{context} value is not JSON-compatible: {value!r}")


ConfigType = Mapping[str, Any] | str | Path


def load_spec(spec: ConfigType, *, format=None) -> Mapping[str, Any]:
    """Return a spec mapping, loading a configfile if needed.

    ``spec`` may already be a mapping (returned unchanged) or a ``str``/``Path``
    pointing at a ``.json`` or YAML file. ``context`` appears in error messages
    (e.g. ``"Datavzrd configuration"``); ``extra`` names the optional
    dependency group advertised when PyYAML is missing (e.g. ``"datavzrd"``).
    """
    if not isinstance(spec, (str, Path)):
        return spec
    path = Path(spec)
    text = path.read_text(encoding="utf-8")
    if format is None:
        format = path.suffix
    format = format.lower().strip(".")
    if format == "json":
        import json

        try:
            loaded = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"Broken {format} file: {path}") from error
    elif format in {"yaml", "yml"}:
        import yaml

        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ValueError(f"Broken {format} file: {path}") from error
    elif format == "toml":
        import tomli

        try:
            loaded = tomli.loads(text)
        except tomli.TOMLDecodeError as error:
            raise ValueError(f"Broken {format} file: {path}") from error
    else:  # assume "ini":
        import configparser

        parser = configparser.ConfigParser()
        try:
            parser.read_string(text)
        except configparser.Error as error:
            raise ValueError(f"Invalid {format} file: {path}") from error
        loaded = {section: dict(parser[section]) for section in parser.sections()}
    return loaded
