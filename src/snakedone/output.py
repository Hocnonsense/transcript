"""Snapshot explicitly selected rich outputs into portable record blocks."""

import re
from collections.abc import Sequence
from logging import warning
from typing import Any, NamedTuple, Protocol, runtime_checkable

from .renderers import get

_FENCE = re.compile(
    r"(?P<fence>```(`*))snakedone-output"
    r"[ \t]+(?P<renderer>\w+)"
    r"((?P<op>==|>=|<=|>|<|=)(?P<version>\d+(?:\.\d+)*))?"
    r"[ \t]*\r?\n?$"
)


def fence(renderer: Renderer, data: str):
    """Wrap serialized renderer *data* in a ``snakedone-output`` fence."""
    header = renderer.name
    version = getattr(renderer, "version", None)
    if version is not None:
        header += "=" + ".".join(str(part) for part in version)
    body = data.rstrip("\n")
    marker = "```"
    while marker in body:
        marker += "`"
    return f"{marker}snakedone-output {header}\n{body}\n{marker}\n"


@runtime_checkable
class Renderer(Protocol):
    """Adapter that serializes, validates, and renders one kind of output.

    An instance wraps a Python object
    - ``serialize`` converts it to a reloadable string that
        can be reladed by corresponding method ``to_html``
    - ``to_snd`` add fence arround the serialized string for storage in a report
    - ``to_html`` turns the reloadable string to HTML,
        also extra files for the report.
    - ``STYLE`` and ``runtime`` contribute browser assets only when the renderer
        occurs in a document; ``sources`` adds CSP sources required by its runtime.
    """

    name: str
    version: tuple[int, ...] | None = None
    STYLE = ""
    """CSS needed by this renderer in exported HTML."""
    def __init__(self):
        """Wrap the Python object this renderer serializes."""
        ...

    def serialize(self) -> str:
        """Return the renderer's data, ready for the output fence."""
        ...

    def to_snd(self):
        """Return the archived ``snakedone-output`` representation."""
        return fence(self, self.serialize())

    def __repr__(self):
        return self.to_snd().removesuffix("\n")

    @classmethod
    def _htmlout(
        cls,
        text: str,
        files: dict[str, tuple[str, bytes]],
        children=(),
        *,
        boxed=True,
    ):
        """Quickly return a ``RecordedOutput`` for the given HTML and report files."""
        return RecordedOutput(cls, text, files, children, boxed)

    @classmethod
    def to_html(cls, sndata: str) -> RecordedOutput:
        """Validate stored *data* and return a rendered output tree."""
        ...

    @classmethod
    def merge_children(cls, text: str, child_blocks: Sequence[str]):
        """Return a new output node with the same renderer and text but new children."""
        for block in child_blocks:
            text += "\n" + block
        return text

    runtime = None
    """Browser script serving the embedded report"""

    sources = []
    """Extra Content-Security-Policy sources for this renderer"""


class Report:
    """A report to embed in the HTML output.

    The report is identified by its *renderer* name and a unique *id*.
    The *files* dictionary maps file names to ``(mime, data)`` pairs.
    """

    def __init__(self, chunk: RecordedOutput, id: str):
        self.chunk = chunk
        self.id = id
        if self.files and not chunk.renderer.runtime:
            raise RuntimeError(
                f"Renderer {self.name!r} has report files but no offline HTML runtime"
            )

    @property
    def name(self):
        return self.chunk.renderer.name

    @property
    def files(self):
        return self.chunk.files

    @property
    def boxed(self):
        return self.chunk.boxed

    @property
    def block(self):
        return (
            '<div class="snakedone-report"'
            f' data-snakedone-report="{self.id}"'
            f' data-snakedone-renderer="{self.name}">'
            f"{self.chunk.text}</div>"
        )


class RecordedOutput(NamedTuple):
    """A rendered output and its recursively nested report nodes."""

    renderer: type[Renderer]
    """Renderer class that owns this output and contributes its browser assets."""
    text: str
    """Rendered HTML, with optional ``{{i}}`` slots for ``children[i]``."""
    files: dict[str, tuple[str, bytes]]
    """Report-relative file names mapped to their MIME type and byte content."""
    children: Sequence[RecordedOutput] = ()
    """Nested outputs substituted into the corresponding slots in ``text``."""
    boxed: bool = True
    """Initial state of the statement code and its surrounding output box."""

    @classmethod
    def validate(
        cls,
        renderer_name: str,
        data: str,
        op: str | None = None,
        version: str | None = None,
    ):
        """Check that the stored *data* is valid for the named renderer and version.
        Return ``(output, None)`` or ``(None, reason)`` for stored *data*.
        """
        if not isinstance(renderer_name, str) or not renderer_name:
            return None, f"requires a renderer name, got {renderer_name!r}"
        renderer = get(renderer_name)
        if renderer is None:
            return None, f"unknown renderer: {renderer_name}"
        current = getattr(renderer, "version", None)
        if current is not None and version is not None:
            declared = _parse_version(version)
            if not _version_ok(op, declared, current):
                supported = ".".join(str(part) for part in current)
                return None, (
                    f"unsupported version: {version} for renderer "
                    f"{renderer.name} (supported: {op}{supported})"
                )
        try:
            rendered = renderer.to_html(data)
        except Exception as error:
            return None, f"renderer {renderer.name} failed to render: {error}"
        if not isinstance(rendered, RecordedOutput):
            return None, f"renderer {renderer.name} did not return RecordedOutput"
        return rendered, None

    def __repr__(self):
        return self.text.removesuffix("\n")

    __str__ = __repr__

    def to_report(self, ireport: str, reports: list[Report]):
        """Render *node*, substituting nested report blocks for child tokens.
        Add id to childs for reference in `h_reports_payload`
        """
        child_blocks = (
            child.to_report(f"{ireport}-{i}", reports).block
            for i, child in enumerate(self.children)
        )
        html = self.renderer.merge_children(self.text, child_blocks)
        report = Report(self._replace(text=html, children=()), ireport)
        reports.append(report)
        return report


def _parse_version(value: str):
    return tuple(int(part) for part in value.split("."))


def _version_ok(op, declared, current):
    """Whether the installed *current* version satisfies the declared constraint."""
    if op is None:
        return True
    if op in ("=", "=="):
        return current == declared
    if op == ">":
        return current > declared
    if op == ">=":
        return current >= declared
    if op == "<":
        return current < declared
    if op == "<=":
        return current <= declared
    return False


def split_output(text: str):
    """Split recognized blocks while retaining ordinary text and future formats."""
    lines = text.splitlines(keepends=True)
    cursor = 0
    plain_start = 0
    while cursor < len(lines):
        header = _FENCE.fullmatch(lines[cursor])
        if not header:
            cursor += 1
            continue
        end = cursor + 1
        close_fence = re.compile(r"^" + header.group("fence") + r"[ \t]*(?:\r?\n)?$")
        while end < len(lines) and not close_fence.fullmatch(lines[end]):
            end += 1
        if end == len(lines):
            warning(f"Incomplete snakedone-output block: {lines[cursor].rstrip()}")
            yield "".join(lines[plain_start:])
            return
        body = "".join(lines[cursor + 1 : end]).removesuffix("\n")
        output, reason = RecordedOutput.validate(
            header.group("renderer"), body, header.group("op"), header.group("version")
        )
        if output is None:
            warning(f"Invalid snakedone-output block: {reason}")
            yield "".join(lines[plain_start : end + 1])
            cursor = end + 1
            plain_start = cursor
            continue
        if plain_start < cursor:
            yield "".join(lines[plain_start:cursor])
        yield output
        cursor = end + 1
        plain_start = cursor
    if plain_start < len(lines):
        yield "".join(lines[plain_start:])


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
