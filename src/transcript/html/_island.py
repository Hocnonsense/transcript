"""Embed the archive in the exported page and read it back out.

The page carries the archive *without* its trailing review block as a JSON
island, plus the review records in a second island.  The browser runtime reads
the first for the report content and the second for annotations, so the page
stays self-contained and the archive (block re-rendered from the records) can
be recovered without executing the document.
"""

import json
import re

_ISLAND = re.compile(
    r'<script type="application/json" id="transcript-source">(?P<body>.*?)</script>',
    re.DOTALL,
)
_REVIEWS = re.compile(
    r'<script id="transcript-reviews" type="application/json">(?P<body>.*?)</script>',
    re.DOTALL,
)


def source_island(source: str):
    """Return the ``transcript-source`` island embedding *source*."""
    encoded = json.dumps(source, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/json" id="transcript-source">{encoded}</script>'


def _reviews_island(page: str):
    """Return the ``transcript-reviews`` records, or ``None``."""
    from ..review._records import Record

    match = _REVIEWS.search(page)
    if match is None:
        return None
    payload = json.loads(match.group("body"))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        return None
    return [Record.from_dict(item) for item in payload["records"]]


def extract_parts(page: str):
    """Return ``(body, records)`` for an exported page.

    *body* is the embedded archive *without* its review block; *records* are the
    ``transcript-reviews`` records (or ``None`` when the page has no island).
    """
    match = _ISLAND.search(page)
    if match is None:
        raise ValueError("the HTML page has no transcript-source island")
    payload = json.loads(match.group("body"))
    if not isinstance(payload, str):
        raise ValueError("the transcript-source island must be a JSON string")
    return payload, _reviews_island(page)


def extract(page: str):
    """Return the archive embedded in an exported page.

    Raises ``ValueError`` when the page carries no island or the island is not
    the expected JSON string.  The review records kept in the ``reviews`` island
    are rendered back into the archive's trailing review block, stamped with the
    body hash.
    """
    from ..review._block import render_block
    from ..tmd import body_hash

    body, records = extract_parts(page)
    if not records:
        return body
    body = body.rstrip("\n") + "\n"
    return body + "\n" + render_block(records, hash=body_hash(body)) + "\n"
