"""Executable Python documents with recorded outputs."""

from .execute import report
from .renderers.compose import compose
from .renderers.datavzrd import datavzrd
from .renderers.label import code, label
from .renderers.markdown import Markdown
from .renderers.vegalite import vegalite

__all__ = ["Markdown", "code", "compose", "datavzrd", "label", "report", "vegalite"]
