"""Embed the archive in the exported page and read it back out.

The page carries the raw ``.snd`` text as a JSON island.  The browser runtime
reads that text and slices the report blocks out of it using the character
offsets recorded on each block, so the page stays self-contained and the
archive can be recovered without executing the document.
"""

import json
import re

_ISLAND = re.compile(
    r'<script type="application/json" id="snakedone-source">(?P<body>.*?)</script>',
    re.DOTALL,
)


def source_island(source: str):
    """Return the ``snakedone-source`` island embedding *source*."""
    encoded = json.dumps(source, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/json" id="snakedone-source">{encoded}</script>'


def extract(page: str):
    """Return the archive embedded in an exported page.

    Raises ``ValueError`` when the page carries no island or the island is not
    the expected JSON string.
    """
    match = _ISLAND.search(page)
    if match is None:
        raise ValueError("the HTML page has no snakedone-source island")
    payload = json.loads(match.group("body"))
    if not isinstance(payload, str):
        raise ValueError("the snakedone-source island must be a JSON string")
    return payload
