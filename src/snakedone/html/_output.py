"""Render statement code, recorded outputs, and hidden script blocks."""

import io
import tokenize
from collections.abc import Callable
from html import escape

from ..output import RecordedOutput, Report, split_output
from ._markup import external_image, png_image

Highlighter = Callable[[str], str]
"""Turn Python source into syntax-highlighted HTML."""


def _multiline_string_lines(source: str):
    """Return physical lines inside multiline strings after their first line."""
    string_interior_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING and token.start[0] != token.end[0]:
            string_interior_lines.update(range(token.start[0] + 1, token.end[0] + 1))
    return string_interior_lines


def highlight_statement(source: str, highlight_python: Highlighter):
    """Render one physical statement as a prompted ``>>>`` code block.

    The block's shared indentation is stripped before highlighting, except on
    continuation lines of a multiline string, which keep their indentation and
    drop the prompt.
    """
    string_lines = _multiline_string_lines(source)
    indent = source[: len(source) - len(source.lstrip())]
    code = "".join(
        line if lineno in string_lines else line.removeprefix(indent)
        for lineno, line in enumerate(source.splitlines(keepends=True), start=1)
    )
    lines = highlight_python(code).removesuffix("\n").split("\n")
    prompted = "".join(
        '<span class="doc-line'
        + (" multiline-string" if lineno in string_lines else "")
        + f'">{line}</span>'
        for lineno, line in enumerate(lines, start=1)
    )
    return '<code class="doc-code">' + prompted + "</code>"


def output_html(
    statements: list[str],
    output: str,
    reports: list[Report],
    report_id: str,
    highlight_python: Highlighter,
):
    code_block = "\n".join(
        highlight_statement(physical_code, highlight_python)
        for physical_code in statements
    )

    def flush_text():
        nonlocal code_block
        if parts:
            code_block += f'<samp class="doc-out">{"".join(parts)}</samp>'
            parts.clear()
        elif not code_block:
            return
        blocks.append(f'<pre class="doc-text">{code_block}</pre>')
        code_block = ""

    parts: list[str] = []
    blocks: list[str] = []
    boxed = True
    for ichunk, chunk in enumerate(split_output(output)):
        if isinstance(chunk, RecordedOutput):
            flush_text()
            report = chunk.to_report(f"{report_id}-{ichunk}", reports)
            blocks.append(report.block)
            boxed = ichunk != 0 or report.boxed
            continue
        boxed = True
        for line in str(chunk).splitlines(keepends=True):
            png = png_image(line)
            if png is not None:
                uri, width, height = png
                parts.append(
                    f'<img class="recorded-image" src="{escape(uri, quote=True)}"'
                    f' width="{width}" height="{height}"'
                    f' style="--image-ratio: {width / height}"'
                    f' alt="Recorded PNG ({width} × {height} pixels)">'
                )
                continue
            external = external_image(line)
            if external is not None:
                url, alt = external
                parts.append(
                    f'<img src="{escape(url, quote=True)}"'
                    f' alt="{escape(alt, quote=True)}" loading="lazy">'
                )
                continue
            parts.append(escape(line))
    flush_text()
    content = "".join(blocks)
    if not output:
        return f'<div class="doctest-code">{content}</div>'
    expanded = str(boxed).lower()
    toggle = (
        '<button class="output-box-toggle" type="button"'
        f' aria-label="Show or hide code and frame" aria-expanded="{expanded}">'
        '<span aria-hidden="true">&lt;/&gt;</span></button>'
    )
    return f'<div class="doctest-code" data-boxed="{expanded}">{toggle}{content}</div>'


def script_html(source: str, highlight_python: Highlighter):
    """Hide the source code of a script block behind a toggle button in HTML.

    Semicolons between adjacent document expressions are only separators.
    """
    if not source.strip(" \t\r\n\f;"):
        return ""
    return (
        '<details class="script-block">'
        ' <summary class="script-toggle"'
        '   title="Show or hide script" aria-label="Toggle script block">'
        '  <span aria-hidden="true">&lt;/&gt;</span>'
        " </summary>"
        ' <pre class="script-code"><code class="language-python">'
        + highlight_python(source.strip("\r\n")).removesuffix("\n")
        + " </code></pre>"
        "</details>"
    )
