"""Review records stored in the trailing ``snakedone.review`` block.

The package owns the whole feature: :mod:`._block` locates, rewrites, and
migrates the trailing block, :mod:`._span` holds the ``L``/``C`` coordinate
grammar with the method-based :class:`Span`, :mod:`._records`
the flat record schema, lookup, and serialization, :mod:`._migrate` the
incremental update run when an archive is regenerated, and :mod:`load` reads a
review source from an archive or exported page and chooses one.
"""

from ._block import ReviewBlock

__all__ = ["ReviewBlock"]
