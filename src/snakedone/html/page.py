"""Assemble a complete HTML page from a document's recorded blocks."""

import io
import tokenize
from html import escape
from typing import TYPE_CHECKING

from ._island import source_island
from ._navigate import anchors, navigate_html
from ._output import output_html, script_html
from ._resources import page_resources
from .markup import markdown_image_origins

if TYPE_CHECKING:
    from ..document import AstDocument
    from ..output import Report


def _multiline_string_lines(source: str):
    """Return physical lines inside multiline strings after their first line."""
    string_interior_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING and token.start[0] != token.end[0]:
            string_interior_lines.update(range(token.start[0] + 1, token.end[0] + 1))
    return string_interior_lines


def render(self: AstDocument, *, title: str = "snakedone document"):
    """Render recorded content as offline HTML without executing the document."""
    parts: list[str] = []
    reports: list[Report] = []
    origins: set[str] = set()
    cursor = 0
    for iblock, block in enumerate(self.blocks):
        node = block.node
        assert node.end_lineno is not None and node.end_col_offset is not None
        start = self.position(node.lineno, node.col_offset)
        end = self.position(node.end_lineno, node.end_col_offset)
        parts.append(script_html(cursor, start))
        cursor = end
        parts.append('<section class="report-block">')
        if block.markdown is not None:
            markdown_start, markdown_end = block.markdown
            origins.update(
                markdown_image_origins(self.source[markdown_start:markdown_end])
            )
            parts.append(
                f'<div class="doc-md"'
                f' data-snd-span="{markdown_start},{markdown_end}"></div>'
            )
        pending_codes: list[tuple[int, int, set[int]]] = []
        last_istatement = len(block.statements) - 1
        for istatement, statement in enumerate(block.statements):
            # TODO: change statement.start to statement.node.lineno
            #  and statement.end to statement.node.end_lineno
            line_start = self.source.rfind("\n", 0, statement.start) + 1
            line_end = self.source.find("\n", statement.end)
            if line_end == -1:
                line_end = len(self.source)
            stringlines = _multiline_string_lines(self.source[line_start:line_end])
            pending_codes.append((line_start, line_end, stringlines))
            output = statement.slot
            if (output is not None and output.value) or istatement == last_istatement:
                report_id = f"report-{iblock}-{istatement}"
                parts.append(output_html(pending_codes, output, reports, report_id))
                pending_codes = []
        parts.append("</section>")

    content_end = len(self.source) if self.review is None else self.review.start
    parts.append(script_html(cursor, content_end))
    body, entries = anchors(parts)
    island = source_island(self.source)
    origins.update(
        image_origin
        for report in reports
        for image_origin in report.chunk.rendered.origins
    )
    style, csp, scripts = page_resources(reports, sorted(origins), island)
    navigate_class, navigate = navigate_html(entries)

    return f"""<!doctype html>
<html lang="en">
 <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{csp}">
  <title>{escape(title)}</title>
   <style>
    {style}
   </style>
 </head>
 <body>
   <div class="{navigate_class}">{navigate}
   <main>
    {body}
   </main>
  </div>
  {scripts}
 </body>
</html>
"""
