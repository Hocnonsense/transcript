"""Snapshot explicitly selected rich outputs into portable record blocks."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from logging import warning
from typing import TYPE_CHECKING, NamedTuple, Protocol, runtime_checkable

from .renderers import get

if TYPE_CHECKING:
    from .parse import Slot

_FENCE = re.compile(
    r"(?P<fence>[ \t]*```(`*))snakedone-output"
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
        files: dict[str, tuple[str, bytes]] | None = None,
        children=(),
        *,
        boxed=True,
        origins=(),
    ):
        """Quickly return a ``Rendered`` for the given HTML and report files."""
        return Rendered(text, files or {}, children, boxed, origins)

    @classmethod
    def to_html(cls, slot: Slot) -> Rendered:
        """Validate stored *slot* and return a rendered output tree."""
        ...

    @classmethod
    def render_node(cls, output: RecordedOutput, child_blocks: Iterable[str]):
        """Render one output node after its child reports have been rendered.
        This method is called recursively from ``RecordedOutput.to_report``
         to produce the final HTML.
        """
        text = output.rendered.text
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

    def __init__(self, chunk: RecordedOutput, id: str, span: tuple[int, int]):
        self.chunk = chunk
        self.id = id
        self.span = span
        if self.files and not chunk.renderer.runtime:
            raise RuntimeError(
                f"Renderer {self.name!r} has report files but no offline HTML runtime"
            )

    @property
    def name(self):
        return self.chunk.renderer.name

    @property
    def files(self):
        return self.chunk.rendered.files

    @property
    def boxed(self):
        return self.chunk.rendered.boxed

    @property
    def block(self):
        start, end = self.span
        return (
            '<div class="snakedone-report"'
            f' data-snd-report="{self.id}" data-snd-renderer="{self.name}"'
            f' data-snd-span="{start},{end}">'
            f"{self.chunk.rendered.text}</div>"
        )


class Rendered(NamedTuple):
    """A renderer's output, before the archive gives it a position."""

    text: str
    """Rendered HTML, with optional ``{{i}}`` slots for ``children[i]``."""
    files: dict[str, tuple[str, bytes]]
    """Report-relative file names mapped to their MIME type and byte content."""
    children: Sequence[RecordedOutput] = ()
    """Nested outputs substituted into the corresponding slots in ``text``."""
    boxed: bool = True
    """Initial state of the statement code and its surrounding output box."""
    origins: tuple[str, ...] = ()
    """Online image origins this output can render, for the page's CSP."""


class RecordedOutput(NamedTuple):
    """A rendered output at one archive occurrence, with its body range."""

    renderer: type[Renderer]
    """Renderer class that owns this output and contributes its browser assets."""
    rendered: Rendered
    span: tuple[int, int]
    """This output's body range relative to its parent."""

    @classmethod
    def validate(
        cls,
        renderer_name: str,
        body: Slot,
        op: str | None = None,
        version: str | None = None,
    ):
        """Render the stored *body* for the named renderer and version.

        Return ``((renderer, rendered), None)`` on success
        or ``(None, reason)`` for an unusable stored body.
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
            rendered = renderer.to_html(body)
        except Exception as error:
            return None, f"renderer {renderer.name} failed to render: {error}"
        if not isinstance(rendered, Rendered):
            return None, f"renderer {renderer.name} did not return Rendered"
        return (renderer, rendered), None

    def __repr__(self):
        return self.rendered.text.removesuffix("\n")

    __str__ = __repr__

    def to_report(self, ireport: str, reports: list[Report], shift: int):
        """Render this output, substituting nested report blocks for child tokens.

        *shift* is the absolute archive start of this output's parent,
        each child's range is relative to this output and is shifted by ``span[0]``.
        """
        span = shift + self.span[0], shift + self.span[1]
        child_blocks = [
            child.to_report(f"{ireport}-{i}", reports, span[0]).block
            for i, child in enumerate(self.rendered.children)
        ]
        html = self.renderer.render_node(self, child_blocks)
        rendered = self.rendered._replace(text=html, children=())
        report = Report(self._replace(rendered=rendered), ireport, span)
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


def split_output(slot: Slot):
    """Split output, retaining each recognized block's archive occurrence."""
    text = slot.raw
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    cursor = 0
    for line in lines:
        starts.append(cursor)
        cursor += len(line)
    plain_start = index = 0
    while index < len(lines):
        header = _FENCE.fullmatch(lines[index])
        if not header:
            index += 1
            continue
        close_fence = re.compile(r"^" + header.group("fence") + r"[ \t]*(?:\r?\n)?$")
        for end in range(index + 1, len(lines)):
            if close_fence.fullmatch(lines[end]):
                break
        else:
            warning(f"Incomplete snakedone-output block: {lines[index].rstrip()}")
            yield slot.dedent(lines[plain_start:])
            return
        if plain_start < index:
            yield slot.dedent(lines[plain_start:index])
        body_start = (
            starts[index + 1]
            if index + 1 < len(lines)
            else starts[index] + len(lines[index])
        )
        body_end = starts[end]
        while body_end > body_start and text[body_end - 1] in "\r\n":
            body_end -= 1
        body = slot.slice(body_start, body_end)
        output, reason = RecordedOutput.validate(
            header.group("renderer"), body, header.group("op"), header.group("version")
        )
        if output is None:
            warning(f"Invalid snakedone-output block: {reason}")
            yield slot.dedent(lines[index : end + 1])
        else:
            yield RecordedOutput(*output, (body_start, body_end))
        plain_start = index = end + 1
    if plain_start < len(lines):
        yield slot.dedent(lines[plain_start:])


def dataframe_csv(frame):
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
