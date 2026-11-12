"""Render recorded documents as HTML without executing their Python code.

The implementation is split by responsibility:

- :mod:`~transcript.html._assets`     packaged static CSS and JavaScript
- :mod:`~transcript.html._markup`     online image/link recognition and rewriting
- :mod:`~transcript.html._output`     statement code, outputs, and script blocks
- :mod:`~transcript.html._navigate`   anchors and the document outline
- :mod:`~transcript.html._island`     the embedded archive and its extraction
- :mod:`~transcript.html._resources`  styles, report payload, scripts, and CSP
- :mod:`~transcript.html.page`        assembles the final page
"""

from ._island import extract, extract_parts
from .page import render

__all__ = ["extract", "extract_parts", "render"]
