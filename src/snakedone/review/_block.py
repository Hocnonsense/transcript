"""Locate and rewrite the trailing ``if "snakedone.review":`` block.

The marker lives here rather than in :mod:`snakedone.parse` so the parser has
no dependency on the review feature: :func:`snakedone.document.parse` asks the
review package for the block after locating the report regions.  The block is
serialized as JSON (:func:`snakedone.review._records.dump`) and escaped for a
``\"\"\"`` literal by :func:`snakedone.snd.escape_slot`.
"""

from __future__ import annotations

import ast
import json
import warnings
from collections.abc import Callable, Sequence
from typing import NamedTuple

from ..snd import body_hash, escape_slot
from ._migrate import migrate
from ._records import Record, ReviewIndex

REVIEW_MARKER = "snakedone.review"


def render_block(records: Sequence[Record], indent: str = "    ", hash: str = ""):
    """Render the trailing ``if "snakedone.review":`` block for *records*.

    *hash* is the ``body_hash`` of the body the block follows; when given it is
    carried in the marker (``snakedone.review=<hash>``) so a later read can tell
    whether the body still matches.  The returned text has no trailing newline;
    callers place it after the body.
    """
    lines = [json.dumps(record.to_dict(), ensure_ascii=False) for record in records]
    if lines:
        body = ",\n".join(indent + escape_slot(line) for line in lines)
        inner = f"[\n{body}\n{indent}]"
    else:
        inner = "[]"
    marker = REVIEW_MARKER if not hash else f"{REVIEW_MARKER}={hash}"
    return f'if "{marker}":\n{indent}"""{inner}"""'


class ReviewBlock(NamedTuple):
    """The trailing ``if "snakedone.review":`` block, if the archive has one."""

    start: int
    end: int
    value: str
    hash: str = ""
    """The ``body_hash`` recorded in the marker, or ``""`` for a legacy block."""

    @classmethod
    def find(cls, tree: ast.Module, position: Callable[[int, int], int]):
        """Return the trailing review block, or ``None`` when there is none.

        The marker must be the last top-level statement and its body a single
        string literal holding the records; a block of any other shape is left
        alone as an ordinary ``if`` instead of failing the archive.  The marker
        may carry the body hash after ``=``; without it the block is legacy and
        is migrated without verification.
        """
        if not tree.body:
            return None
        node = tree.body[-1]
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Constant)
            and isinstance(node.test.value, str)
            and len(node.body) == 1
        ):
            return None
        marker: str = node.test.value
        if marker == REVIEW_MARKER:
            hash = ""
        elif marker.startswith(REVIEW_MARKER + "="):
            hash = marker[len(REVIEW_MARKER) + 1 :]
        else:
            return None
        statement = node.body[0]
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            return None
        assert node.end_lineno is not None and node.end_col_offset is not None
        return cls(
            position(node.lineno, node.col_offset),
            position(node.end_lineno, node.end_col_offset),
            statement.value.value,
            hash,
        )

    def load(self):
        """Parse and validate the block's records into a :class:`ReviewIndex`.

        A block that cannot be parsed or validated is dropped entirely after a
        warning: a damaged review is never preserved, which would freeze it, and
        the drop is never silent.  A whole block is dropped if any record is
        invalid.
        """
        if not self.value.strip():
            return ReviewIndex([])
        try:
            data = json.loads(self.value)
            if not isinstance(data, list):
                raise ValueError("the snakedone.review block must hold a JSON array")
            return ReviewIndex(Record.from_dict(item) for item in data)
        except (KeyError, TypeError, ValueError) as error:
            warnings.warn(
                f"dropping invalid snakedone.review block: {error}", stacklevel=2
            )
            return ReviewIndex([])


class ReviewSource(NamedTuple):
    """A review block together with the archive body it was recorded against.

    It is the one value the CLI needs to carry annotations across a re-render:
    *body* is the archive text before the block, *records* its parsed records,
    *hash* the body hash recorded in the marker (``""`` for legacy), and
    *block* the original block text, kept verbatim when nothing moves.
    """

    body: str
    records: Sequence[Record]
    hash: str = ""
    block: str = ""

    @classmethod
    def of(cls, review: ReviewBlock, source: str):
        """Build a source from a located block and the archive text it sits in."""
        return cls(
            source[: review.start],
            review.load().records,
            review.hash,
            source[review.start : review.end],
        )

    @property
    def stale(self):
        """Whether the block no longer matches the body it describes."""
        return bool(self.hash) and body_hash(self.body) != self.hash


def migrated_block(new: str, source: ReviewSource, indent: str = "    "):
    """Return the block to append to *new*, migrating *source*'s records.

    A stale source or an empty record set drops the block (returning ``""``);
    an unchanged body keeps ``source.block`` verbatim; otherwise the records are
    migrated onto *new* and rendered with its hash (an unchanged record set still
    needs the new hash when the body moved).
    """
    if source.stale:
        warnings.warn(
            "dropping snakedone.review block: archive body hash mismatch",
            stacklevel=2,
        )
        return ""
    if not source.records:
        return ""
    records = list(migrate(source.records, source.body, new))
    if not records:
        return ""
    if records == source.records and body_hash(new) == source.hash:
        return source.block
    return render_block(records, indent, hash=body_hash(new))
