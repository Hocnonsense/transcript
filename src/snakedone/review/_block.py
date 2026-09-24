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
from collections.abc import Callable
from typing import NamedTuple

from ..snd import escape_slot
from ._migrate import migrate

REVIEW_MARKER = "snakedone.review"


def _render_block(records: list[dict], indent: str = "    ") -> str:
    """Render the trailing ``if "snakedone.review":`` block for *records*.

    The returned text has no trailing newline; callers place it after the body.
    """
    inner = escape_slot(_dump(records))
    return f'if "{REVIEW_MARKER}":\n{indent}"""{inner}\n{indent}"""'


def _dump(records: list[dict]):
    """Serialize records as the review block's triple-quoted string value."""
    body = json.dumps(records, indent=2, ensure_ascii=False).splitlines()
    if not body:
        body = ["[]"]
    pad = "    "
    return body[0] + "\n" + "\n".join(pad + line for line in body[1:])


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

    def load(self) -> list[dict] | None:
        """Parse the JSON string stored inside the review block.

        Returns ``None`` for a malformed block after warning, so the caller
        keeps the archive as it is instead of failing the render.
        """
        if not self.value.strip():
            return []
        try:
            records = json.loads(self.value)
            if not isinstance(records, list):
                raise ValueError("the snakedone.review block must hold a JSON array")
        except ValueError as error:
            warnings.warn(f"invalid snakedone.review block: {error}", stacklevel=2)
            records = None
        return records

    def to_block(self, prev: str, new: str, indent: str = "    "):
        """Return the block text for a body that changed from *prev* to *new*.

        ``None`` keeps the existing block (unreadable or unchanged records) and
        an empty string drops it (nothing left to record).
        """
        records = self.load()
        if records is None:
            return None
        migrated = migrate(records, prev, new)
        if not migrated:
            return ""
        if migrated == records:
            return None
        return _render_block(migrated, indent)
