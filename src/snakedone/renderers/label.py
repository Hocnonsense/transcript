"""Renderer that wraps another output with a stable id and caption."""

import ast
import re
from html import escape

from ..output import RecordedOutput, Renderer, split_output
from . import register

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]*\Z")

_STYLE = """
/* labelled outputs */
.snakedone-label { margin: .5rem 0; }
.snakedone-label > figcaption { margin-top: .25rem; font-size: .9em; color: #888; }
"""


@register
class CodeRenderer(Renderer):
    """Archive a Python value using the same representation as a bare expression."""

    name = "code"
    version = (1,)

    def __init__(self, value):
        self.text = repr(value)

    def serialize(self):
        return self.text

    @classmethod
    def to_html(cls, data: str):
        return cls._htmlout(
            '<pre class="doc-text"><samp class="doc-out">'
            + escape(data)
            + "</samp></pre>",
            {},
        )


code = CodeRenderer


@register
class Label(Renderer):
    """Wrap a renderer output with an anchor *id* and an optional *caption*.

    The wrapped output keeps its own rendering, runtime, and report files;
    the label only adds a document anchor and a caption around it. Numbering
    and cross references are resolved later by the document collector.
    """

    name = "label"
    version = (1,)
    STYLE = _STYLE

    def __init__(self, inner, id: str, caption=""):
        if not isinstance(inner, Renderer):
            inner = CodeRenderer(inner)
        if not isinstance(id, str) or not _ID.match(id):
            raise ValueError(f"label id must be a valid snakedone id, got {id!r}")
        if not isinstance(caption, str):
            raise TypeError("label caption must be a string")
        self.inner = inner
        self.id = id
        self.caption = caption

    def serialize(self):
        return "\n".join([self.id + " " + repr(self.caption), self.inner.to_snd()])

    @staticmethod
    def from_snd(data: str):
        content = list(split_output(data))
        if len(content) != 2:
            raise ValueError(
                "labelled output must contain a label header and one inner output"
            )
        header, inner = content
        if not isinstance(header, str) or not isinstance(inner, RecordedOutput):
            raise ValueError(
                "labelled output must contain a string header and a renderer output"
            )
        try:
            id, encoded_caption = header.rstrip("\r\n").split(maxsplit=1)
            caption = ast.literal_eval(encoded_caption)
        except (ValueError, SyntaxError) as error:
            raise ValueError("label caption must be a Python string literal") from error
        if not _ID.fullmatch(id):
            raise ValueError(f"label id must be a valid snakedone id, got {id!r}")
        if not isinstance(caption, str):
            raise ValueError("label caption must decode to a string")
        return id, caption, inner

    @classmethod
    def to_html(cls, data: str):
        """Render the wrapped output and place it inside a labelled figure."""
        id, caption, inner = cls.from_snd(data)
        figure = f'<figure class="snakedone-label" id="{id}">' + "{{0}}"
        if caption:
            figure += f"<figcaption>{escape(caption)}</figcaption>"
        figure += "</figure>"
        return cls._htmlout(figure, {}, (inner,))

    @classmethod
    def merge_children(cls, text, child_blocks):
        """Return a new output node with the same renderer and text but new children."""
        block = list(child_blocks)
        if len(block) != 1:
            raise ValueError("labelled output must contain exactly one inner output")
        return text.replace("{{0}}", block[0])


label = Label
