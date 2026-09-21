"""Static CSS and JavaScript shipped with every exported page.

The assets live as ordinary ``.css``/``.js`` files beside this module so they
keep their own syntax and tooling; this package only reads them back into the
strings the exporters embed.
"""

from importlib.resources import files

__all__ = ["IMAGE_SCRIPT", "NAVIGATE_SCRIPT", "STYLE"]


def _asset(name: str) -> str:
    """Read a packaged asset as text."""
    return files(__package__).joinpath(name).read_text(encoding="utf-8")


STYLE = _asset("style.css")
IMAGE_SCRIPT = _asset("image.js")
NAVIGATE_SCRIPT = _asset("navigate.js")
