"""Renderer for static bitmaps and Matplotlib plot snapshots."""

import base64
import json
import struct
from html import escape
from io import BytesIO
from pathlib import Path

from ..output import Renderer
from . import register

_STYLE = """
/* portable bitmap snapshots */
.snakedone-bitmap { display: block; max-width: 100%; height: auto; margin: .5rem auto; }
.snakedone-bitmap[style] {
  width: min(100%, calc(50vh * var(--image-ratio)));
}
"""


def _image_type(data: bytes):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if (
        len(data) >= 24
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        and data[12:16] == b"IHDR"
    ):
        width, height = struct.unpack(">II", data[16:24])
        if width and height:
            return width, height
    return None


def _matplotlib_figure(value):
    """Return the Figure behind a Figure, Axes, Artist, or artist sequence."""
    if callable(getattr(value, "savefig", None)):
        return value
    if isinstance(value, (list, tuple)) and value:
        figures = [_matplotlib_figure(item) for item in value]
        if any(figure is None for figure in figures):
            return None
        if any(figure is not figures[0] for figure in figures[1:]):
            raise ValueError("bitmap plot objects must belong to one figure")
        return figures[0]
    get_figure = getattr(value, "get_figure", None)
    return get_figure() if callable(get_figure) else None


def bitmap(source, *, alt: str = ""):
    """Snapshot a bitmap file or IO for portable HTML output.

    ``source`` may be a PNG, JPEG, GIF, or WebP path, bytes-like, or binary IO.
    """
    return Bitmap(source, alt=alt)


def image(source, *, alt: str = ""):
    """Snapshot a static bitmap source or render a Matplotlib plot.

    In addition to every source accepted by :func:`bitmap`, ``source`` may be
    a Matplotlib ``Figure``, ``Axes``, artist, or the artist sequence returned
    by ``plt.plot``.
    """
    figure = _matplotlib_figure(source)
    if figure is not None:
        stream = BytesIO()
        figure.savefig(stream, format="png", bbox_inches="tight")
        source = stream.getvalue()
        alt = alt or "Matplotlib plot"
    return Bitmap(source, alt=alt)


@register
class Bitmap(Renderer):
    """Registered renderer for :func:`snakedone.bitmap` snapshots."""

    name = "bitmap"
    version = (1,)
    STYLE = _STYLE

    def __init__(self, source, *, alt: str = ""):
        if not isinstance(alt, str):
            raise TypeError("bitmap alt text must be a string")
        if isinstance(source, (str, Path)):
            path = Path(source)
            data = path.read_bytes()
            default_alt = path.name
        elif isinstance(source, (bytes, bytearray, memoryview)):
            data = bytes(source)
            default_alt = ""
        else:
            read = getattr(source, "read", None)
            if not callable(read):
                raise TypeError("bitmap requires a path, bytes, or binary IO")
            data = read()
            if not isinstance(data, bytes):
                raise TypeError("bitmap IO must return bytes")
            name = getattr(source, "name", "")
            default_alt = Path(name).name if isinstance(name, (str, Path)) else ""
        mime = _image_type(data)
        if mime is None:
            raise ValueError("bitmap supports PNG, JPEG, GIF, and WebP images")
        self.mime = mime
        self.data = data
        self.alt = alt or default_alt

    def serialize(self):
        return json.dumps(
            {
                "mime": self.mime,
                "data": base64.b64encode(self.data).decode("ascii"),
                "alt": self.alt,
            },
            sort_keys=True,
            separators=(",", ":"),  # eliminate whitespace
        )

    @classmethod
    def to_html(cls, data: str):
        try:
            snapshot = json.loads(data)
            mime = snapshot["mime"]
            encoded = snapshot["data"]
            alt = snapshot["alt"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ValueError("bitmap data must be a valid snapshot") from error
        if not isinstance(mime, str) or not isinstance(encoded, str):
            raise ValueError("bitmap snapshot must contain string image data")
        if not isinstance(alt, str):
            raise ValueError("bitmap snapshot alt text must be a string")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError("bitmap snapshot contains invalid base64") from error
        if _image_type(raw) != mime:
            raise ValueError("bitmap snapshot MIME type does not match its data")
        uri = f"data:{mime};base64,{encoded}"
        dimensions = _png_dimensions(raw)
        size = ""
        if dimensions is not None:
            width, height = dimensions
            size = (
                f' width="{width}" height="{height}"'
                f' style="--image-ratio:{width / height}"'
            )
        image = (
            f'<img class="snakedone-bitmap" src="{uri}"'
            + size
            + f' alt="{escape(alt, quote=True)}">'
        )
        return cls._htmlout(image, boxed=False)
