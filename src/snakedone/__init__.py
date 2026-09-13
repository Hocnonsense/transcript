"""Executable Python documents with recorded outputs."""

from .renderers.datavzrd import datavzrd

__all__ = ["datavzrd", "report"]


class _Report:
    """Plain context manager for ``with snakedone.report:`` report blocks."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


report = _Report()
