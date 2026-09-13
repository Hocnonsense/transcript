"""Executable Python documents with recorded outputs."""

from .execute import report
from .renderers.datavzrd import datavzrd

__all__ = ["datavzrd", "report"]
