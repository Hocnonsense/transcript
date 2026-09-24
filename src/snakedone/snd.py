"""Rebuild archives from captured outputs and write files atomically."""

import ast
import os
import re
import tempfile
import textwrap
import tokenize
from pathlib import Path
from typing import TYPE_CHECKING

from .parse import (
    REPORT_MARKER_COMMENT,
    ReportBlock,
    with_report_marker,
)

if TYPE_CHECKING:
    from ._rule import Rule
    from .document import AstDocument


def escape_slot(content: str):
    """Escape *content* so it can be embedded in a ``\"\"\"...\"\"\"`` literal.
    i.e., `'\"\"\"' + escape_slot(content) + '\"\"\"'` is a valid Python string.

    - Backslashes, CR, TAB and non-printable controls are escaped.
    - LF is preserved as a literal newline.
    - Quotes are only escaped when they'd close / collide with the
      surrounding triple quotes (runs of 3+, or trailing).
    """

    content = content.replace("\\", "\\\\")
    content = content.replace("\r", "\\r").replace("\t", "\\t")
    content = re.sub(
        r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]",
        lambda match: f"\\x{ord(match.group()):02x}",
        content,
    )
    return re.sub(
        r'(?:"{3,}|"+$)', lambda match: match.group().replace('"', '\\"'), content
    )


def _slot_literal(output: str, prefix: str):
    """Render *output* as an indented triple-quoted literal source snippet.

    The parsed-back value is ``"\\n" + prefix-each-line(output) [+ "\\n" + prefix]``,
    so it does NOT round-trip to *output*.
    """
    content = escape_slot(output)
    inner = textwrap.indent(content, prefix, lambda line: line.rstrip("\r\n") != "")
    if content.endswith("\n"):
        return f'"""\n{inner}{prefix}"""'
    return f'"""\n{inner}"""'


def _find_line_start(source: str, token: tokenize.TokenInfo):
    lines = source.splitlines(keepends=True)
    return sum(len(line) for line in lines[: token.end[0] - 1])


def _strip_stale_markers(document: AstDocument, blocks: list[ReportBlock]):
    """Remove ``# snakedone`` from ``with`` regions that are not report blocks."""

    confirmed = {id(block.node) for block in blocks}
    for region in document.regions.values():
        node = region.node
        if isinstance(node, ast.If) or id(region.node) in confirmed:
            continue
        start, end, token, is_marker = with_report_marker(
            document.source, node, document.position
        )
        if not is_marker:
            continue
        comment_line = start + _find_line_start(document.source[start:end], token)
        end = len(token.line.rstrip("\r\n"))
        yield (comment_line + token.end[1], comment_line + end, "")


def render(
    self: AstDocument,
    blocks: list[ReportBlock],
    outputs: list[list[str]],
    job: Rule | None = None,
):
    """Rebuild output slots and markers using the captured execution results."""

    edits: list[tuple[int, int, str]] = [*_strip_stale_markers(self, blocks)]
    for block, output_block in zip(blocks, outputs):
        if isinstance(block.node, ast.With):
            start, end, token, is_marker = with_report_marker(
                self.source, block.node, self.position
            )
            if not is_marker:
                comment_line = start + _find_line_start(self.source[start:end], token)
                colon_next = comment_line + token.end[1]
                edits.append((colon_next, colon_next, "  " + REPORT_MARKER_COMMENT))
        for statement, output in zip(block.statements, output_block):
            indent = self.indent_of(statement.start)
            if statement.slot is not None:
                literal = _slot_literal(output, indent) if output else ""
                edits.append((*statement.slot.literal, literal))
            elif output:
                newline = self.source.find("\n", statement.end)
                if newline == -1:
                    newline = len(self.source)
                literal = "\n" + indent + _slot_literal(output, indent)
                edits.append((newline, newline, literal))
    if job is not None:
        edits.extend(job.make_rule_block())
    body = self.source_without_review
    result = body
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    result = result.rstrip("\n") + "\n"
    if self.review is not None:
        block = self.review.to_block(body.rstrip("\n") + "\n", result)
        if block is None:
            block = self.source[self.review.start : self.review.end]
        if block:
            result = result + "\n" + block + "\n"
    ast.parse(result)  # Never publish a non-Python archive.
    return result


def write(path: Path, source: str):
    """Write *source* to *path* via a temporary file and atomic replace."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(source)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
