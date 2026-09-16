"""An executable Python document and its archive and HTML operations."""

import ast
from collections.abc import Callable
from typing import NamedTuple

from .execute import execute as _execute
from .html import render as _render_html
from .parse import Region, Statement, locate
from .snd import render as _render_snd


def parse(source: str, filename: str):
    """Locate module-level report regions, never compute a block here.

    for with block, only one with item is allowed
    """
    tree, position, regions = locate(source, filename)
    return AstDocument(source, tree, position, regions)


class AstDocument(NamedTuple):
    source: str
    tree: ast.Module
    position: Callable[[int, int], int]
    """(line, column) -> character offset in the source."""
    regions: dict[int, Region]

    def indent_of(self, start: int):
        source = self.source
        return source[source.rfind("\n", 0, start) + 1 : start]

    @property
    def blocks(self):
        """Compute all report blocks from the document's regions."""
        return [
            region.parse_block(self.position)
            for region in self.regions.values()
            if region.kind == "if" or region.marker
        ]

    def slot_output(self, statement: Statement):
        """Read a recorded output slot, removing only its archive indentation."""
        if statement.slot is None:
            return ""
        output = statement.slot.value
        indent = self.indent_of(statement.start)
        if indent:
            output = "".join(
                line.removeprefix(indent) for line in output.splitlines(keepends=True)
            )
        return output.removeprefix("\n")

    execute = _execute
    render_snd = _render_snd
    render_html = _render_html
