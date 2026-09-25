"""Embed the archive's review records into the exported page.

The page already carries the full ``.snd`` (including the trailing review
block) as the ``snakedone-source`` island.  This module adds a second island
with the *parsed* records plus the block's character offsets, so the browser
runtime can render annotations and rewrite the block when the user exports the
page without parsing Python.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ._navigate import Entry

if TYPE_CHECKING:
    from ..review._block import ReviewBlock


def to_page(review: ReviewBlock | None):
    """Return the review entries and island for *document*."""
    entries: list[Entry] = []
    if review is None:
        payload = {"records": [], "start": None, "end": None}
        return entries, _reviews_island(payload)
    records = review.load()
    for record in records:
        if record.get("type") != "review":
            continue
        identifier = record.get("id", "review")
        text = record.get("body") or record.get("text") or str(identifier)
        entries.append(Entry.review(str(text), f"snd-review-{identifier}"))
    payload = {"records": records, "start": review.start, "end": review.end}
    return entries, _reviews_island(payload)


def _reviews_island(payload: dict):
    """Return the ``snakedone-reviews`` JSON island for *document*."""
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        '<script id="snakedone-reviews" type="application/json">'
        + encoded
        + "</script>"
    )
