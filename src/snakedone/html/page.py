"""Assemble a complete HTML page from a document's recorded blocks."""

import textwrap
from html import escape
from typing import TYPE_CHECKING

from ._island import source_island
from ._markup import external_links, image_origins
from ._navigate import anchors, navigate_html
from ._output import output_html, script_html
from ._resources import page_resources

if TYPE_CHECKING:
    from ..document import AstDocument
    from ..output import Report

_HIGHLIGHT_SELECTORS = ":is(.doc-code, .script-code)"


def _build_render_helpers():
    """Build the Markdown renderer, Python highlighter, and highlight CSS.

    Importing here keeps the optional ``html`` extra out of the core package,
    so a missing dependency becomes an actionable ``RuntimeError`` instead of
    an import-time crash.
    """
    try:
        from markdown_it import MarkdownIt
        from pygments import highlight, lexers
        from pygments.formatters import HtmlFormatter
    except ImportError as error:
        raise RuntimeError(
            'HTML export requires: pip install "snakedone[html]"'
        ) from error

    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    lexer = lexers.PythonLexer(stripnl=False, ensurenl=False)
    formatter = HtmlFormatter(nowrap=True, style="default")

    light = formatter.get_style_defs(_HIGHLIGHT_SELECTORS)
    dark = HtmlFormatter(style="native").get_style_defs(_HIGHLIGHT_SELECTORS)
    highlight_css = light + "\n@media (prefers-color-scheme: dark) { " + dark + " }"

    def render_markdown(prose: str):
        rendered = external_links(markdown.render(prose))
        return '<div class="doc-md">' + rendered + "</div>"

    def highlight_python(source: str) -> str:
        return highlight(source, lexer, formatter)

    return render_markdown, highlight_python, highlight_css


def render(self: AstDocument, *, title: str = "snakedone document"):
    """Render recorded content as offline HTML without executing the document."""
    render_markdown, highlight_python, highlight_css = _build_render_helpers()

    parts: list[str] = []
    reports: list[Report] = []
    cursor = 0
    for iblock, block in enumerate(self.blocks):
        node = block.node
        assert node.end_lineno is not None and node.end_col_offset is not None
        start = self.position(node.lineno, node.col_offset)
        end = self.position(node.end_lineno, node.end_col_offset)
        parts.append(script_html(self.source[cursor:start], highlight_python))
        cursor = end
        parts.append(
            '<section class="report-block"'
            f' data-snd-start="{start}" data-snd-end="{end}"'
            f' data-snd-line="{node.lineno}">'
        )
        prose = textwrap.dedent(block.markdown).strip()
        if prose:
            parts.append(render_markdown(prose))
        pending_codes: list[str] = []
        last_istatement = len(block.statements) - 1
        for istatement, statement in enumerate(block.statements):
            # TODO: change statement.start to statement.node.lineno
            #  and statement.end to statement.node.end_lineno
            line_start = self.source.rfind("\n", 0, statement.start) + 1
            line_end = self.source.find("\n", statement.end)
            if line_end == -1:
                line_end = len(self.source)
            pending_codes.append(self.source[line_start:line_end])
            output = self.slot_output(statement)
            if output or istatement == last_istatement:
                report_id = f"report-{iblock}-{istatement}"
                parts.append(
                    output_html(
                        pending_codes, output, reports, report_id, highlight_python
                    )
                )
                pending_codes = []
        parts.append("</section>")

    parts.append(script_html(self.source[cursor:], highlight_python))
    body, entries = anchors(parts)
    island = source_island(self.source)
    style, csp, scripts = page_resources(reports, image_origins(body), island)
    navigate_class, navigate = navigate_html(entries)

    return f"""<!doctype html>
<html lang="en">
 <head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{csp}">
  <title>{escape(title)}</title>
   <style>
    {highlight_css}
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
