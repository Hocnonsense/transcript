"""Review records stored in the trailing ``snakedone.review`` block.

The package owns the whole feature: :mod:`._block` locates and rewrites the
trailing block, :mod:`._span` holds the ``L``/``C`` coordinate grammar with the
method-based :class:`Span` and :class:`At`, :mod:`._records` the flat record
schema, lookup, and serialization, and :mod:`._migrate` the incremental update
run when an archive is regenerated.
"""

from ._block import ReviewBlock

__all__ = ["ReviewBlock"]
