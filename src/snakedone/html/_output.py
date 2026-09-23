"""Render statement code, recorded outputs, and hidden script blocks."""

from html import escape

from ..output import RecordedOutput, Report, split_output
from ..parse import Slot


def _ranges(numbers: set[int]):
    """Encode one-based line numbers as compact comma-separated ranges.
    >>> _ranges({1, 4, 5})
    '1,4-5'
    """
    if not numbers:
        return ""
    values = sorted(numbers)
    ranges: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def statement_html(span: tuple[int, int, set[int]]):
    """Emit a source-backed code placeholder for one physical statement.

    The browser runtime slices ``source[start:end]`` from the island and
    highlights it. ``data-snd-string-lines`` marks the continuation lines of a
    multiline string, which keep their indentation and drop the ``>>>`` prompt.
    """
    start, end, string_lines = span
    string_lines = _ranges(string_lines)
    encoded = f' data-snd-string-lines="{string_lines}"' if string_lines else ""
    return (
        f'<code class="doc-code" data-snd-start="{start}" data-snd-end="{end}"'
        f"{encoded}></code>"
    )


def output_html(
    statements: list[tuple[int, int, set[int]]],
    output: Slot | None,
    reports: list[Report],
    report_id: str,
):
    code_block = [*map(statement_html, statements)]

    def flush_text():
        if parts:
            code_block.append(f'<samp class="doc-out">{"".join(parts)}</samp>')
            parts.clear()
        elif not code_block:
            return
        blocks.append('<pre class="doc-text">{}</pre>'.format("".join(code_block)))
        code_block.clear()

    parts: list[str] = []
    blocks: list[str] = []
    boxed = True
    if output is None:
        text = ""
    else:
        text = output.value
        chunks = split_output(output)
        for ichunk, chunk in enumerate(chunks):
            if isinstance(chunk, RecordedOutput):
                flush_text()
                report = chunk.to_report(f"{report_id}-{ichunk}", reports, output.start)
                blocks.append(report.block)
                boxed = ichunk != 0 or report.boxed
                continue
            if str(chunk):
                boxed = True
            for line in str(chunk).splitlines(keepends=True):
                parts.append(escape(line))
    flush_text()
    content = "".join(blocks)
    if not text:
        return f'<div class="doctest-code">{content}</div>'
    expanded = str(boxed).lower()
    toggle = (
        '<button class="output-box-toggle" type="button"'
        f' aria-label="Show or hide code and frame" aria-expanded="{expanded}">'
        '<span aria-hidden="true">&lt;/&gt;</span></button>'
    )
    return f'<div class="doctest-code" data-boxed="{expanded}">{toggle}{content}</div>'


def script_html(start: int, end: int):
    """Emit a source-backed placeholder for the script region ``source[start:end]``.

    The browser fills it behind a toggle. Semicolons between adjacent document
    expressions are only separators, so a region that holds nothing else is
    removed by the runtime instead of showing an empty toggle.
    """
    if start == end:
        return ""
    return (
        f'<details class="script-block" data-snd-start="{start}"'
        f' data-snd-end="{end}"></details>'
    )
