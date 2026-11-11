"""Locate report blocks, their markdown, code statements, and output slots."""

import ast
import io
import re
import tokenize
from collections.abc import Callable
from typing import NamedTuple, TypeGuard

REPORT_MARKER = "transcript"
REPORT_MARKER_COMMENT = f"# {REPORT_MARKER}"

_STRING_PREFIXES = "rRbBuUfF"
_ESCAPE = re.compile(r"\\([\\\"'rt]|x[0-9a-fA-F]{2})")
_ESCAPE_TEXT = {"\\": "\\", '"': '"', "'": "'", "r": "\r", "t": "\t"}


def _decode_escapes(raw: str):
    """Reverse the shared escape set (``\\``, quotes, ``\\r``, ``\\t``, ``\\xNN``).
    LF and unknown escapes stays literal.

    Mirrors the browser runtime's ``decodeEscapes`` and ``tmd.escape_slot``,
    the set that appears in machine-generated slot literals.
    """

    if "\\" not in raw:
        return raw

    def replace(match: re.Match):
        escape = match.group(1)
        if escape[0] == "x":
            return chr(int(escape[1:], 16))
        return _ESCAPE_TEXT[escape]

    return _ESCAPE.sub(replace, raw)


class Slot(NamedTuple):
    """A recorded output body and its coordinates in the source."""

    raw: str
    """the text inside the string delimiters"""
    start: int
    """absolute offset of .raw in the source"""
    indent: str
    literal: tuple[int, int]
    """the whole string-literal span, to replace during py2tmd"""

    @property
    def end(self):
        return self.start + len(self.raw)

    @property
    def shift(self):
        """How far the literal delimiters extend beyond the body on each side."""
        return self.literal[0] - self.start, self.literal[1] - self.end

    def dedent(self, text: list[str]):
        return "".join(_decode_escapes(line.removeprefix(self.indent)) for line in text)

    @property
    def value(self):
        """The decoded text with its archive indentation removed."""
        return self.dedent(self.raw.splitlines(keepends=True)).removeprefix("\n")

    def slice(self, start, end):
        return self.__class__(self.raw[start:end], 0, self.indent, (0, end - start))


class Statement(NamedTuple):
    node: ast.stmt
    start: int
    end: int
    slot: Slot | None


class ReportBlock(NamedTuple):
    node: ast.If | ast.With
    body_start: int
    body_end: int
    markdown: tuple[int, int] | None
    statements: list[Statement]


def line_offsets(source: str):
    """Return a ``(lineno, column) -> character offset`` mapper for *source*."""

    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def position(lineno: int, column: int):
        # AST columns count UTF-8 bytes; source slicing counts characters.
        return starts[lineno - 1] + len(lines[lineno - 1].encode()[:column].decode())

    return position


def _span_start(node: ast.stmt | ast.expr, position: Callable[[int, int], int]):
    return position(node.lineno, node.col_offset)


def _span_end(node: ast.stmt | ast.expr, position: Callable[[int, int], int]):
    assert node.end_lineno is not None and node.end_col_offset is not None
    return position(node.end_lineno, node.end_col_offset)


def span(node: ast.stmt | ast.expr, position: Callable[[int, int], int]):
    return _span_start(node, position), _span_end(node, position)


def _is_report_if(node: ast.stmt) -> TypeGuard[ast.If]:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Constant)
        and node.test.value == REPORT_MARKER
    )


def with_marker_text(source: str, node: ast.With, position: Callable[[int, int], int]):
    """Return the ``(start, end, colon, comment)`` after a ``with`` header.

    *comment* is the stripped text between the statement colon and the end of
    its physical line, empty when there is none.
    """
    start = _span_start(node, position)
    end = _span_start(node.body[0], position)
    tokens = list(tokenize.generate_tokens(io.StringIO(source[start:end]).readline))
    colon = None
    for token in tokens:
        # The header may contain colons (dict, slice, lambda); the statement
        # colon is the last one before the body.
        if token.type == tokenize.OP and token.string == ":":
            colon = token
    if colon is None:
        raise ValueError(f"line {node.lineno}: could not find colon in with statement")
    after_colon = colon.line[colon.end[1] :].lstrip()
    return start, end, colon, after_colon.strip()


def with_report_marker(
    source: str, node: ast.With, position: Callable[[int, int], int]
):
    start, end, colon, comment = with_marker_text(source, node, position)
    return start, end, colon, comment == REPORT_MARKER_COMMENT


def _string_expr(node: ast.stmt):
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return node.value
    return None


def _string_interior(source: str, span: tuple[int, int]):
    """Return the span of a string literal's content, between its delimiters."""
    start, end = span
    index = start
    while index < end and source[index] in _STRING_PREFIXES:
        index += 1
    quote = source[index]
    run = 0
    while index + run < end and source[index + run] == quote:
        run += 1
    width = 3 if run >= 3 else 1
    return index + width, end - width


class Region(NamedTuple):
    """A module-level report entry (``if "transcript":`` or a top-level ``with``)."""

    node: ast.If | ast.With
    marker: bool  # the comment right after the ``with`` colon is ``# transcript``

    @property
    def kind(self):
        return "if" if isinstance(self.node, ast.If) else "with"

    def parse_block(self, source: str, position: Callable[[int, int], int]):
        """Compute a block from its region; called when a report block is reached."""
        node = self.node
        body = node.body
        if not body:
            raise ValueError(f"line {node.lineno}: a report block must have a body")
        if body[0].lineno == node.lineno:
            raise ValueError(
                f"line {node.lineno}: a report block body must start on the next line; "
                "put the body on its own line"
            )
        markdown = None
        index = 0
        first = _string_expr(body[0])
        if first is not None:
            markdown = _string_interior(source, span(first, position))
            index = 1
        statements: list[Statement] = []
        previous_end_line = 0
        while index < len(body):
            statement = body[index]
            if _string_expr(statement) is not None:
                # A docstring that does not follow a code statement has no slot role.
                # warnings.warn(
                #     f"line {statement.lineno}: stray record docstring ignored",
                #     stacklevel=2,
                # )
                index += 1
                continue
            if statement.lineno <= previous_end_line:
                raise ValueError(
                    f"line {statement.lineno}: multiple statements on one line are "
                    "not supported in report blocks; put each statement on its own line"
                )
            previous_end_line = statement.end_lineno or 0
            start = _span_start(statement, position)
            line_start = source.rfind("\n", 0, start) + 1
            indent = source[line_start:start]
            slot = None
            if index + 1 < len(body):
                constant = _string_expr(body[index + 1])
                if constant is not None:
                    literal = span(constant, position)
                    slot_start, slot_end = _string_interior(source, literal)
                    if slot_start < slot_end and source[slot_start] == "\n":
                        slot_start += 1
                    slot = Slot(
                        source[slot_start:slot_end], slot_start, indent, literal
                    )
                    index += 1
            end = _span_end(statement, position)
            statements.append(Statement(statement, start, end, slot))
            index += 1
        body_start = _span_start(body[0], position)
        body_end = _span_end(body[-1], position)
        return ReportBlock(node, body_start, body_end, markdown, statements)


def locate(source: str, filename: str):
    """Locate module-level report regions without computing any block.

    A ``with`` block is a region only when it has a single item; the comment
    after its colon decides whether it is a report block.
    """
    tree = ast.parse(source, filename=filename)
    position = line_offsets(source)
    regions = {}
    for i, node in enumerate(tree.body):
        if _is_report_if(node):
            regions[i] = Region(node, True)
        elif isinstance(node, ast.With) and len(node.items) == 1:
            marker = with_report_marker(source, node, position)
            regions[i] = Region(node, marker[-1])
    return tree, position, regions
