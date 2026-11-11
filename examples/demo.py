"""A Python document recording text, bitmap images, and a DataFrame table."""

import json
import struct
import zlib
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from transcript import image


def png_bytes(red: int):
    """Encode a deterministic one-pixel RGB PNG using only the stdlib."""

    def chunk(kind: bytes, payload: bytes):
        body = kind + payload
        return (
            struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes([0, red, 64, 128])))
        + chunk(b"IEND", b"")
    )


def matplotlib_plot(value):
    plt.figure(figsize=(6, 3))
    plot = plt.plot([0, 1, 2], [0, value, 0], marker="o")
    plt.title("Sample plot")
    plt.xlabel("Step")
    plt.ylabel("Value")
    return plot


data = json.loads(Path(__file__).with_name("data.json").read_text(encoding="utf-8"))
message = f"Sample: {data['label']}"

if "transcript":
    """
    The following records archive a string, a table, and an inline image.
    """
    message

image_source = {"red": data["red"], "green": 64, "blue": 128}

if "transcript":
    """
    ## Image

    This tiny image is encoded directly from its RGB source data.
    """
    image_source
    image(png_bytes(image_source["red"]), alt="A one-pixel RGB sample")


if "transcript":
    """
    ## Matplotlib plot

    The plot is rendered as a PNG and embedded directly in the archive.
    """
    image(matplotlib_plot(data["value"]), alt="A line plot of the sample value")

table = pd.DataFrame([data], columns=["label", "value"])

if "transcript":
    """
    ## Interactive table

    The measurements are archived a second time as a Datavzrd snapshot.
    Opening the exported HTML turns this table into a sortable, filterable report.
    """
    table

if "transcript":
    """
    This Markdown paragraph follows the final record and must remain unchanged.
    """
