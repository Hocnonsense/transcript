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

if TYPE_CHECKING:
    from ..review._block import ReviewBlock


def to_page(review: ReviewBlock | None) -> str:
    """Return the ``snakedone-reviews`` island for *document*, or ``""``.

    Without a review block there is nothing to embed: the browser defaults to no
    records and no block offsets.  A present but empty block still emits an
    island, so its offsets can strip the (invalid) block on export.
    """
    if review is None:
        return ""
    records = [record.to_dict() for record in review.load().records]
    payload = {"records": records, "start": review.start, "end": review.end}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        '<script id="snakedone-reviews" type="application/json">'
        + encoded
        + "</script>"
    )
