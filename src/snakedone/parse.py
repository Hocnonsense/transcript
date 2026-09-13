"""Locate report blocks, their markdown, code statements, and output slots."""

import ast
import io
import tokenize
from collections.abc import Callable
from typing import NamedTuple, TypeGuard

REPORT_MARKER = "snakedone"
REPORT_MARKER_COMMENT = f"# {REPORT_MARKER}"


class Slot(NamedTuple):
    start: int
    end: int
    value: str


class Statement(NamedTuple):
    node: ast.stmt
    start: int
    end: int
    slot: Slot | None


class ReportBlock(NamedTuple):
    node: ast.If | ast.With
    body_start: int
    body_end: int
    markdown: str
    statements: list[Statement]


class Region(NamedTuple):
    """A module-level report entry (``if "snakedone":`` or a top-level ``with``)."""

    node: ast.If | ast.With
    marker: bool  # the comment right after the ``with`` colon is ``# snakedone``

    @property
    def kind(self):
        return "if" if isinstance(self.node, ast.If) else "with"


class AstDocument(NamedTuple):
    source: str
    tree: ast.Module
    position: Callable[[int, int], int]
    regions: dict[int, Region]

    def indent_of(self, start: int):
        source = self.source
        return source[source.rfind("\n", 0, start) + 1 : start]

    @property
    def blocks(self):
        """Compute all report blocks from the document's regions."""
        return [
            parse_block(region, self.position)
            for region in self.regions.values()
            if region.kind == "if" or region.marker
        ]


def _line_offsets(source: str):
    """Split source into lines plus each line's character offset."""

    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))

    def _position(lineno: int, column: int):
        # AST columns count UTF-8 bytes; source slicing counts characters.
        return starts[lineno - 1] + len(lines[lineno - 1].encode()[:column].decode())

    return _position


def span_start(node: ast.stmt | ast.expr, position: Callable[[int, int], int]):
    return position(node.lineno, node.col_offset)


def span_end(node: ast.stmt | ast.expr, position: Callable[[int, int], int]):
    assert node.end_lineno is not None and node.end_col_offset is not None
    return position(node.end_lineno, node.end_col_offset)


def _is_report_if(node: ast.stmt) -> TypeGuard[ast.If]:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Constant)
        and node.test.value == REPORT_MARKER
    )


def with_has_marker(source, node: ast.With, _position: Callable[[int, int], int]):
    start = span_start(node, _position)
    end = span_start(node.body[0], _position)
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
    return start, end, colon, after_colon.strip() == REPORT_MARKER_COMMENT


def parse(source: str, filename: str):
    """Locate module-level report regions, never compute a block here.

    for with block, only one with item is allowed
    """
    tree = ast.parse(source, filename=filename)
    _position = _line_offsets(source)
    regions = {}
    for i, node in enumerate(tree.body):
        if _is_report_if(node):
            regions[i] = Region(node, True)
        elif isinstance(node, ast.With) and len(node.items) == 1:
            marker = with_has_marker(source, node, _position)
            regions[i] = Region(node, marker[-1])
    return AstDocument(source, tree, _position, regions)


def _string_expr(node: ast.stmt):
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return node.value, node.value.value
    return None


def parse_block(region: Region, position: Callable[[int, int], int]):
    """Compute a block from its region; called when a report block is reached."""
    node, _ = region
    body = node.body
    if not body:
        raise ValueError(f"line {node.lineno}: a report block must have a body")
    if body[0].lineno == node.lineno:
        raise ValueError(
            f"line {node.lineno}: a report block body must start on the next line; "
            "put the body on its own line"
        )
    markdown = ""
    index = 0
    first = _string_expr(body[0])
    if first is not None:
        _, markdown = first
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
        slot = None
        if index + 1 < len(body):
            next_string = _string_expr(body[index + 1])
            if next_string is not None:
                constant, value = next_string
                slot = Slot(
                    span_start(constant, position),
                    span_end(constant, position),
                    value,
                )
                index += 1
        start = span_start(statement, position)
        end = span_end(statement, position)
        statements.append(Statement(statement, start, end, slot))
        index += 1
    body_start = span_start(body[0], position)
    body_end = span_end(body[-1], position)
    return ReportBlock(node, body_start, body_end, markdown, statements)
