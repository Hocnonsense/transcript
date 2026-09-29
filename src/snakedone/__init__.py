"""Executable Python documents with recorded outputs."""

from .execute import report
from .renderers.bitmap import bitmap, image
from .renderers.compose import compose
from .renderers.datavzrd import datavzrd
from .renderers.label import code, label
from .renderers.markdown import markdown
from .renderers.table import table
from .renderers.vegalite import vegalite

__all__ = [
    "markdown",
    "bitmap",
    "code",
    "compose",
    "datavzrd",
    "image",
    "label",
    "report",
    "rule",
    "table",
    "vegalite",
]


def rule(name=None):
    """Declare this document's Snakemake rule.

    Requires the optional ``snakemake`` extra, imported on first call so that
    ``import snakedone`` stays dependency-free.
    """
    from ._rule.core import rule as declare

    return declare(name)
