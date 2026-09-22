"""Static CSS and JavaScript shipped with every exported page.

The assets live as ordinary ``.css``/``.js`` files beside this module so they
keep their own syntax and tooling; this package only reads them back into the
strings the exporters embed.
"""

from importlib.resources import files

__all__ = [
    "ASSET_SCRIPTS",
    "IMAGE_SCRIPT",
    "ISLAND_SCRIPT",
    "NAVIGATE_SCRIPT",
    "RENDER_SCRIPT",
    "STYLE",
]


def _asset(name: str):
    """Read a packaged asset, preferring its generated minified sibling.

    ``tools/minify_assets.py`` writes the ``*.min.*`` files (``pixi run minify``
    or the wheel build hook); falling back to the readable source keeps a tree
    without them working.
    """
    root = files(__package__)
    stem, suffix = name.rsplit(".", 1)
    minified = root.joinpath(f"{stem}.min.{suffix}")
    chosen = minified if minified.is_file() else root.joinpath(name)
    return chosen.read_text(encoding="utf-8")


STYLE = _asset("style.css")
IMAGE_SCRIPT = _asset("image.js")
NAVIGATE_SCRIPT = _asset("navigate.js")
RENDER_SCRIPT = _asset("render.js")
ISLAND_SCRIPT = _asset("island.js")

ASSET_SCRIPTS = (IMAGE_SCRIPT, NAVIGATE_SCRIPT, ISLAND_SCRIPT, RENDER_SCRIPT)
