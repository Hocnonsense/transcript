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

from ..snd import escape_slot
from ._migrate import migrate
from ._records import Record, ReviewIndex, validate

REVIEW_MARKER = "snakedone.review"


def _render_block(records: Sequence[Record], indent: str = "    "):
    """Render the trailing ``if "snakedone.review":`` block for *records*.

    The returned text has no trailing newline; callers place it after the body.
    """
    lines = [json.dumps(record.to_dict(), ensure_ascii=False) for record in records]
    if lines:
        body = ",\n".join(indent + escape_slot(line) for line in lines)
        inner = f"[\n{body}\n{indent}]"
    else:
        inner = "[]"
    return f'if "{REVIEW_MARKER}":\n{indent}"""{inner}"""'


class ReviewBlock(NamedTuple):
    """The trailing ``if "snakedone.review":`` block, if the archive has one."""

    start: int
    end: int
    value: str

    @classmethod
    def find(cls, tree: ast.Module, position: Callable[[int, int], int]):
        """Return the trailing review block, or ``None`` when there is none.

        The marker must be the last top-level statement and its body a single
        string literal holding the records; a block of any other shape is left
        alone as an ordinary ``if`` instead of failing the archive.
        """
        if not tree.body:
            return None
        node = tree.body[-1]
        if not (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Constant)
            and node.test.value == REVIEW_MARKER
            and len(node.body) == 1
        ):
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
        )

    def load(self):
        """Parse and validate the JSON string stored inside the review block.

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
            records = [Record.from_dict(item) for item in data]
            validate(records)
        except (KeyError, TypeError, ValueError) as error:
            warnings.warn(
                f"dropping invalid snakedone.review block: {error}", stacklevel=2
            )
            return ReviewIndex([])
        return ReviewIndex(records).resolve()

    def to_block(self, prev: str, new: str, indent: str = "    "):
        """Return the block text for a body that changed from *prev* to *new*.

        ``None`` keeps an unchanged block as it is;
        an empty string drops it (no records left).
        """
        index = self.load()
        migrated = migrate(index.records, prev, new)
        if not migrated:
            return ""
        if migrated == index.records:
            return None
        return _render_block(migrated, indent)
