"""Renderer for output that should be interpreted as ordinary Markdown.

The Markdown source is archived verbatim;
the exported page renders it in the browser from the embedded archive,
so the server keeps no HTML here.
"""

from ..html.markup import markdown_image_origins
from ..output import Renderer
from . import register


class _Report(type(Renderer)):
    def __enter__(cls):
        return cls

    def __exit__(cls, *exc):
        return False


@register
class markdown(Renderer, metaclass=_Report):
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
    def to_html(cls, slot):
        """Mark the slot for the browser runtime; the server emits no HTML.

        The online image origins are carried on the output so the page CSP can
        allow them without re-reading the archive.
        """
        origins = tuple(markdown_image_origins(slot.value))
        return cls._htmlout("", boxed=False, origins=origins)
