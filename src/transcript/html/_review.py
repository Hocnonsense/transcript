"""Embed the archive's review records into the exported page.

The source island carries the archive *without* its trailing review block; this
module adds a second island with the parsed records plus the body hash, so the
browser runtime can render annotations, rewrite the block on export, and stamp
a matching hash without parsing Python.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..review._block import ReviewBlock


def to_page(review: ReviewBlock | None, body_hash: str):
    """Return the ``transcript-reviews`` island for *document*.

    *body_hash* is the hash of the source island's archive body, reused by the
    runtime when it writes the block back.  An archive without a review block
    still gets an island (empty records), so a review added in the browser can
    carry the right hash on export.
    """
    records = [] if review is None else [r.to_dict() for r in review.load().records]
    payload = {"records": records, "hash": body_hash}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        '<script id="transcript-reviews" type="application/json">'
        + encoded
        + "</script>"
    )
