"""Compiled CSS and JavaScript shipped with every exported page.

The authored TypeScript and CSS live in ``src/frontend``. The frontend build
writes the minified assets beside this module. This package only reads those
generated files back into the strings the exporter embeds.
"""

from importlib.resources import files

__all__ = ["ASSET_SCRIPTS", "SCRIPT", "STYLE"]


def _asset(name: str):
    """Read one compiled frontend asset packaged beside this module."""
    return files(__package__).joinpath(name).read_text(encoding="utf-8")


STYLE = _asset("style.min.css")
SCRIPT = _asset("snakedone.min.js")

ASSET_SCRIPTS = (SCRIPT,)
