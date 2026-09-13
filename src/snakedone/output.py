"""Snapshot explicitly selected rich outputs into portable record blocks."""

import json
import re
from typing import Any, NamedTuple

from .renderers import get

_FENCE = re.compile(r"^```snakedone-output[ \t]*(?:\r?\n)?$")
_CLOSE_FENCE = re.compile(r"^```[ \t]*(?:\r?\n)?$")


def dataframe_csv(frame: Any):
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


class RecordedOutput(NamedTuple):
    """Renderer-defined data stored in a snakedone-output fence."""

    renderer: str
    data: Any

    def validate(self):
        """Validate both author-created outputs and restored archive payloads."""
        if not isinstance(self.renderer, str) or not self.renderer:
            raise ValueError("snakedone-output requires a renderer name")
        renderer = get(self.renderer)
        if renderer is None:
            raise ValueError("Unsupported snakedone-output renderer")
        renderer.validate(self)

    def to_text(self):
        self.validate()
        payload = {
            "version": 2,
            "renderer": self.renderer,
            "data": self.data,
        }
        encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False)
        return f"```snakedone-output\n{encoded}\n```\n"

    def __repr__(self) -> str:
        return self.to_text().removesuffix("\n")

    __str__ = __repr__


def split_output(text: str):
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
        if payload["version"] != 2 or get(payload["renderer"]) is None:
            # Unknown versions and renderers stay readable as plain text.
            cursor = end + 1
            continue
        if "data" not in payload:
            raise ValueError("snakedone-output requires data")
        output = RecordedOutput(renderer=payload["renderer"], data=payload["data"])
        output.validate()
        if plain_start < cursor:
            yield "".join(lines[plain_start:cursor])
        yield output
        cursor = end + 1
        plain_start = cursor
    if plain_start < len(lines):
        yield "".join(lines[plain_start:])
