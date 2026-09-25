"""Read a review source from an archive or page, and choose one.

A ``.snd`` or exported page is folded into a :class:`ReviewSource`;
:func:`reference_source` then picks one by priority and
:func:`~snakedone.review._block.migrated_block` migrates it onto a new body.
The records themselves and the block grammar live in :mod:`._block`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..document import parse
from ..html import extract_parts
from ..snd import body_hash
from ._block import ReviewSource, migrated_block, render_block

if TYPE_CHECKING:
    from ..document import AstDocument


def document_source(document: AstDocument):
    """The document's own review block as a :class:`ReviewSource`, or ``None``."""
    if document.review is None:
        return None
    return ReviewSource.of(document.review, document.source)


def read_source(path: Path):
    """Read *path* (a ``.snd`` or exported page) as a :class:`ReviewSource`.

    Returns ``None`` when it carries no review block.  A page is unfolded into
    its body and records first, then stamped with the body hash.
    """
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".html":
        body, records = extract_parts(text)
        if not records:
            return None
        hash = body_hash(body)
        return ReviewSource(body, records, hash, render_block(records, hash=hash))
    return document_source(parse(text, str(path)))


def _reference_source(document: AstDocument, target: Path, previous: Path | None):
    """Pick the review source by priority.

    An explicit ``--previous`` wins (it may hold the authoritative annotations
    even when the document carries its own, possibly stale, block).  Otherwise
    the document's own block is used, otherwise an already existing target.
    """
    if previous is not None:
        return read_source(previous)
    own = document_source(document)
    if own is not None:
        return own
    return read_source(target) if target.exists() else None


def review_block(document: AstDocument, target: Path, previous: Path | None, body: str):
    """Return the review block to append to *body*, or ``""`` when none applies."""
    source = _reference_source(document, target, previous)
    return "" if source is None else migrated_block(body, source)
