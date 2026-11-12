"""Render pandas or polars DataFrames as GitHub-flavored Markdown tables.

``table()`` is a thin convenience over the :func:`transcript.markdown` renderer.
"""

import csv
from io import StringIO

from ..output import dataframe_csv
from .markdown import markdown


def _escape(text: str):
    """Escape a value for one Markdown table cell (line breaks become spaces)."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def table(frame):
    """Record a pandas or polars DataFrame as a basic Markdown table."""
    rows = list(csv.reader(StringIO(dataframe_csv(frame))))
    if not rows:
        raise ValueError("table expects a DataFrame with a header row")
    header, *body = rows
    if len(header) > 1 and not header[0]:
        header[0] = "index"
    lines = ["| " + " | ".join(_escape(cell) for cell in header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in body:
        if len(row) != len(header):
            raise ValueError("table rows must match the number of columns")
        lines.append("| " + " | ".join(_escape(cell) for cell in row) + " |")
    return markdown("\n".join(lines))
