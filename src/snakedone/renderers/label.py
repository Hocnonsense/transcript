"""Renderer that wraps another output with a stable id and caption."""

import ast
import re
from collections.abc import Iterable
from html import escape
from logging import warning

from ..output import RecordedOutput, Renderer, split_output
from ..parse import Slot
from . import register

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]*\Z")

_STYLE = """
/* labelled outputs */
.snakedone-label { margin: .5rem 0; }
.snakedone-label > figcaption { margin-top: .25rem; font-size: .9em; color: #888; }
.snakedone-label-repeat-note { margin-left: .5em; white-space: nowrap; }
.snakedone-label-repeat-note code { color: inherit; }
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
    def to_html(cls, slot):
        return cls._htmlout(
            '<pre class="doc-text"><samp class="doc-out">'
            + escape(slot.value)
            + "</samp></pre>",
            {},
        )


code = CodeRenderer


_cache: dict[str, tuple[str, RecordedOutput, int]] | None = None


def set_cache(new=None):
    """Reset the label cache for a new document."""
    global _cache
    old, _cache = _cache, new
    return old


def get_inner(content_iter: Iterable[str | RecordedOutput]):
    content = list(content_iter)
    if len(content) != 1:
        raise ValueError(
            "labelled output must contain exactly one renderer output after the header"
        )
    (inner,) = content
    if not isinstance(inner, RecordedOutput):
        raise ValueError(
            "labelled output must contain a renderer output after the header"
        )
    return inner


def get_cached_inner(
    id: str, caption: str, data: str, content_iter: Iterable[str | RecordedOutput]
):
    assigned_id = id
    i = 0
    found = None
    if _cache is not None:
        while (cached := _cache.get(assigned_id)) is not None:
            if cached[0] == data:
                found = cached
                break
            i += 1
            assigned_id = f"{id}.{i}"
    if found is None:
        inner = get_inner(content_iter)
        if _cache is not None:
            _cache[assigned_id] = (data, inner, 0)
    else:
        inner = found[1]
    if i:
        if found is None:
            warning(f"label {id!r} has different content; using {assigned_id!r}")
        if caption:
            caption += f" (duplicate {i} of label {id})"
        else:
            caption = f"duplicate {i} of label {id}"
    return assigned_id, caption, inner


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

    @classmethod
    def from_snd(cls, slot: Slot):
        """Parse a label, reusing its cached inner output when possible.
        The decoded body is only used as the cache key.
        """
        content_iter = split_output(slot)
        try:
            header = next(content_iter)
        except StopIteration:
            header = None
        if not isinstance(header, str):
            raise ValueError("labelled output must contain a string header")
        try:
            id, encoded_caption = header.rstrip("\r\n").split(maxsplit=1)
            caption = ast.literal_eval(encoded_caption)
        except (ValueError, SyntaxError) as error:
            raise ValueError("label caption must be a Python string literal") from error
        if not _ID.fullmatch(id):
            raise ValueError(f"label id must be a valid snakedone id, got {id!r}")
        if not isinstance(caption, str):
            raise ValueError("label caption must decode to a string")
        return get_cached_inner(id, caption, slot.value, content_iter)

    @classmethod
    def to_html(cls, slot):
        """Render the wrapped output and place it inside a labelled figure."""
        id, caption, inner = cls.from_snd(slot)
        figure = f'<figure class="snakedone-label" data-snd-label="{id}">' + "{{0}}"
        if caption:
            figure += f"<figcaption>{escape(caption)}</figcaption>"
        figure += "</figure>"
        return cls._htmlout(figure, {}, (inner,), boxed=inner.rendered.boxed)

    @classmethod
    def _repeat_html(cls, text: str, id: str, occurrence: int):
        """Return a full repeated occurrence without duplicating its HTML id."""
        opening = f'<figure class="snakedone-label" id="{id}">'
        repeated = (
            '<figure class="snakedone-label snakedone-label-repeat"'
            f' data-snd-label="{id}"'
            f' data-snd-label-occurrence="{occurrence}">'
        )
        if not text.startswith(opening):
            raise ValueError(f"label {id!r} has an invalid rendered wrapper")
        text = repeated + text[len(opening) :]
        label_id = escape(id)
        note = (
            '<span class="snakedone-label-repeat-note">'
            f'<a href="#{label_id}">origin ↩</a></span>'
        )
        if text.endswith("</figcaption></figure>"):  # has label
            return text.replace("</figcaption>", " " + note + "</figcaption>", 1)
        return text.replace("</figure>", f"<figcaption>{note}</figcaption></figure>", 1)

    @classmethod
    def render_node(cls, output, child_blocks):
        """Render the label around its child output."""
        block = list(child_blocks)
        if len(block) != 1:
            raise ValueError("labelled output must contain exactly one inner output")
        match = re.match(
            r'<figure class="snakedone-label" data-snd-label="([^"]+)">',
            output.rendered.text,
        )
        if match is None:
            raise ValueError("labelled output has an invalid figure template")
        id = match.group(1)
        opening = match.group(0)
        text = output.rendered.text.replace(
            opening, f'<figure class="snakedone-label" id="{id}">', 1
        )
        if _cache is not None:
            cached = _cache.get(id)
            if cached is not None:
                data, inner, count = cached
                _cache[id] = (data, inner, count + 1)
                if count:
                    text = cls._repeat_html(text, id, count)
        return text.replace("{{0}}", block[0])


label = Label
