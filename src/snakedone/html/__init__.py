"""Render recorded documents as HTML without executing their Python code.

The implementation is split by responsibility:

- :mod:`~snakedone.html._assets`     packaged static CSS and JavaScript
- :mod:`~snakedone.html._markup`     online image/link recognition and rewriting
- :mod:`~snakedone.html._output`     statement code, outputs, and script blocks
- :mod:`~snakedone.html._navigate`   anchors and the document outline
- :mod:`~snakedone.html._resources`  styles, report payload, scripts, and CSP
- :mod:`~snakedone.html.page`        assembles the final page
"""

from .page import render

__all__ = ["render"]
