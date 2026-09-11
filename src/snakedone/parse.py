"""Locate record expressions and their replaceable output spans."""

import ast
import doctest
import io
import re
import tokenize
import warnings
from typing import Literal, NamedTuple


class DocExpression(NamedTuple):
    source: str
    line: int
    source_start: int
    source_end: int
    indent: str


class MDBlock(NamedTuple):
    node: ast.Expr
    codes: list[DocExpression]
    quote: Literal['"""', "'''"]
    content: str
    source_start: int
    source_end: int
    prefix: str  # rRuU

    @property
    def raw(self):
        return "r" in self.prefix.lower()


class AstDocument(NamedTuple):
    source: str
    tree: ast.Module
    blocks: list[MDBlock]


def _document_nodes(body: list[ast.stmt]):
    """Descend only through conditionals and synchronous contexts."""
    for node in body:
        yield node
        if isinstance(node, ast.If):
            yield from _document_nodes(node.body)
            yield from _document_nodes(node.orelse)
        elif isinstance(node, ast.With):
            yield from _document_nodes(node.body)


def _record_sources(value: str):
    """Read prompts only; output extends across blank lines until the next prompt."""
    lines = value.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        match = re.match(r"( *)>>> (.*)", lines[index])
        if match is None:
            index += 1
            continue
        start = index
        indent = match[1]
        source = match[2] + "\n"
        index += 1
        while index < len(lines) and lines[index].startswith(indent + "... "):
            source += lines[index][len(indent) + 4 :].rstrip("\r\n") + "\n"
            index += 1
        yield doctest.Example(source, "", lineno=start, indent=len(indent))


def parse(source: str, filename: str):
    tree = ast.parse(source, filename=filename)
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    blocks: list[MDBlock] = []
    for node in _document_nodes(tree.body):
        # region filter docstring node
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        value = node.value.value
        examples = list(_record_sources(value))
        if not examples:
            continue
        # endregion filter docstring node
        # region get doctest
        # Physical multiline literals keep source edits local and reviewable.
        # AST columns count UTF-8 bytes; tokenize columns count characters.
        column = len(lines[node.lineno - 1].encode()[: node.col_offset].decode())
        assert node.end_lineno is not None and node.end_col_offset is not None
        end_column = len(
            lines[node.end_lineno - 1].encode()[: node.end_col_offset].decode()
        )
        node_start = (node.lineno, column)
        node_end = (node.end_lineno, end_column)
        _tokens = (
            token
            for token in tokens
            if token.type == tokenize.STRING
            and node_start <= token.start < node_end
            and token.end <= node_end
        )
        token = next(_tokens, None)
        if token is None:
            raise ValueError(
                f"{filename}:{node.lineno}: record string literal not found"
            )
        next_token = next(_tokens, None)
        if next_token is not None:
            warnings.warn(
                f"{filename}:{next_token.start[0]}: "
                "record block skipped: implicit string concatenation",
                stacklevel=2,
            )
            continue
        # endregion get token with doctest

        literal = token.string
        prefix_length = len(literal) - len(literal.lstrip("rRuU"))
        quote = literal[prefix_length : prefix_length + 3]
        if quote not in ('"""', "'''"):
            warnings.warn(
                f"{filename}:{node.lineno}: record block skipped: need triple quotes",
                stacklevel=2,
            )
            continue
        # DocExpression offsets refer to decoded content, never physical source lines.
        content = value if value.endswith("\n") else value + "\n"
        content_offsets = [0]
        for line in content.splitlines(keepends=True):
            content_offsets.append(content_offsets[-1] + len(line))
        records: list[DocExpression] = []
        for example in examples:
            start_line = token.start[0] - 1 + example.lineno
            output_line = example.lineno + len(example.source.splitlines())
            # Validate all records before executing any user code.
            code = ast.parse(example.source, filename=filename)
            if not code.body:
                raise ValueError(f"{filename}:{start_line + 1}: empty record")
            records.append(
                DocExpression(
                    example.source,
                    start_line + 1,
                    content_offsets[example.lineno],
                    content_offsets[output_line],
                    " " * example.indent,
                )
            )
        blocks.append(
            MDBlock(
                node,
                records,
                quote,
                content,
                offsets[token.start[0] - 1] + token.start[1],
                offsets[token.end[0] - 1] + token.end[1],
                literal[:prefix_length],
            )
        )
    return AstDocument(source, tree, blocks)
