"""A Python document recording text, a CSV table, and a base64 PNG."""

import base64
import csv
import io
import json
import struct
import zlib
from pathlib import Path


class RangeIndex:
    name = None


class MiniTable:
    """Small duck-typed table; pandas is not required."""

    index = RangeIndex()

    def __init__(self, label: str, value: int):
        self.label = label
        self.value = value

    def to_csv(self, *, index: bool, lineterminator: str):
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator=lineterminator)
        writer.writerow(([""] if index else []) + ["label", "value"])
        writer.writerow(([0] if index else []) + [self.label, self.value])
        return stream.getvalue()


def png_data_uri(red: int):
    """Encode a deterministic one-pixel RGB PNG using only the stdlib."""

    def chunk(kind: bytes, payload: bytes):
        body = kind + payload
        return (
            struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes([0, red, 64, 128])))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


data = json.loads(Path(__file__).with_name("data.json").read_text(encoding="utf-8"))
message = f"Sample: {data['label']}"
table = MiniTable(data["label"], data["value"])
image_source = {"red": data["red"], "green": 64, "blue": 128}
picture = f"![]({png_data_uri(image_source['red'])})"

"""
The following records archive a string, a table, and an inline image.
>>> message
"""

"""
## Measurements

The table below contains the original values, without hidden statistics.

>>> table
"""

"""
## Image

This tiny image is encoded directly from its RGB source data.

>>> image_source

>>> print(picture)
"""

"""
This Markdown paragraph follows the final record and must remain unchanged.
"""
