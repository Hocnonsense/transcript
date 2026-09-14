"""Renderer for output that should be interpreted as ordinary Markdown."""

from ..output import Renderer
from . import register


@register
class Markdown(Renderer):
    """Mark a string output for normal Markdown rendering in exported HTML."""

    name = "markdown"
    version = (1,)

    def __init__(self, content: str):
        if not isinstance(content, str):
            raise TypeError("Markdown content must be a string")
        self.obj = content

    def serialize(self):
        """Return the Markdown source string."""
        return self.obj

    @classmethod
    def to_html(cls, data: str):
        """Render stored Markdown with the document's normal Markdown settings."""
        from markdown_it import MarkdownIt

        markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
        return markdown.render(data), {}
