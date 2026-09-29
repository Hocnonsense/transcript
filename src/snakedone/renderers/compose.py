"""Renderer that arranges several outputs in a panel grid."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..output import RecordedOutput, Renderer, split_output
from ..parse import Slot
from . import register
from .label import CodeRenderer

_DEFAULT_NCOL = 2

_STYLE = """
/* composed panel grids */
.snakedone-compose { display: grid; margin: .5rem 0 1rem; gap: .75rem;
                     align-items: start;
                     grid-template-columns: repeat(var(--snakedone-cols, 2),
                                                  minmax(0, 1fr)); }
.snakedone-compose > .snakedone-panel { position: relative; margin: 0;
                                        min-width: 0; }
.snakedone-compose .snakedone-chart { margin: 0; }
.snakedone-compose .snakedone-label { margin: 0; }
.snakedone-compose .snakedone-label-caption-header {
  display: flex; flex-direction: column;
}
.snakedone-compose .snakedone-label-caption-header > figcaption {
  order: -1; margin: 0 0 .25rem;
}
.snakedone-panel-label { position: absolute; top: 0; left: 0; z-index: 1;
                         padding: 0; border-radius: .125rem;
                         background: Canvas;
                         background: color-mix(in srgb, Canvas 65%, transparent);
                         color: CanvasText;
                         font-weight: 700; line-height: 1;
                         pointer-events: none; }
.snakedone-panel-label-inline { position: static; margin-right: .35em;
                                background: none; color: CanvasText;
                                line-height: inherit; }
.snakedone-panel-label-header { position: static; display: block;
                                width: max-content; margin-bottom: .25rem;
                                background: none; color: CanvasText;
                                font-size: .9em; line-height: 1.65; }
@media (max-width: 640px) {
  .snakedone-compose { grid-template-columns: minmax(0, 1fr); }
}
"""


def _panel_letter(index: int) -> str:
    """Return spreadsheet-style letters: 0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _validate_config(config: Mapping):
    """Return a normalized grid configuration or raise ``ValueError``."""
    if set(config) - {"ncol", "labels"}:
        raise ValueError("compose header has unknown fields")
    ncol = config.get("ncol", _DEFAULT_NCOL)
    if isinstance(ncol, bool) or not isinstance(ncol, int) or ncol < 1:
        raise ValueError("compose ncol must be a positive integer")
    labels = config.get("labels", True)
    if not isinstance(labels, bool):
        raise ValueError("compose labels must be a boolean")
    return {"ncol": ncol, "labels": labels}


def compose(*panels, ncol: int = _DEFAULT_NCOL, labels: bool = True):
    """Arrange several outputs in a panel grid during HTML export.

    Each *panel* is a renderer output, usually a chart wrapped by
    :func:`~snakedone.vegalite` or :func:`~snakedone.label`; ordinary values
    fall back to the ``code`` renderer. ``ncol`` sets the number of grid
    columns. Panels fill row by row and share the same column widths, and the
    grid collapses to one column on narrow screens.

    Each panel is tagged ``(A)``, ``(B)``, ... in reading order unless
    ``labels=False``.

    Composed panels keep their own rendering, runtime, and report files, so a
    compose can nest inside another compose or a label. This first version only
    lays panels out; it does not align axes or merge their scales.
    """
    if not panels:
        raise ValueError("compose needs at least one panel")
    return Compose(list(panels), {"ncol": ncol, "labels": labels})


@register
class Compose(Renderer):
    """Registered renderer for :func:`snakedone.compose` snapshots."""

    name = "compose"
    version = (1,)
    STYLE = _STYLE

    def __init__(self, panels: Sequence, config: Mapping):
        config_ = _validate_config(config)
        self.panels = [
            panel if isinstance(panel, Renderer) else CodeRenderer(panel)
            for panel in panels
        ]
        if not self.panels:
            raise ValueError("compose needs at least one panel")
        self.config = config_

    def serialize(self):
        """Return the JSON header followed by one nested fence per panel."""
        config = self.config
        if config["labels"]:
            # ``labels`` defaults to true, so leave it out of the archive.
            config = {key: value for key, value in config.items() if key != "labels"}
        header = json.dumps(config, sort_keys=True, separators=(",", ":"))
        parts = [header, *(panel.to_snd() for panel in self.panels)]
        return "\n".join(part.rstrip("\n") for part in parts) + "\n"

    @classmethod
    def from_snd(cls, slot: Slot):
        """Split stored *slot* into its grid configuration and panel outputs."""
        content = [
            chunk
            for chunk in split_output(slot)
            if not (isinstance(chunk, str) and not chunk.strip())
        ]
        if len(content) < 2:
            raise ValueError("composed output needs a header and at least one panel")
        header, *panels = content
        if not isinstance(header, str):
            raise ValueError("composed output must start with a configuration header")
        if not all(isinstance(panel, RecordedOutput) for panel in panels):
            raise ValueError("composed output panels must be renderer outputs")
        try:
            config = json.loads(header)
        except json.JSONDecodeError as error:
            raise ValueError("composed output header must be JSON") from error
        if not isinstance(config, dict):
            raise ValueError("composed output header must be a JSON object")
        return _validate_config(config), panels

    @classmethod
    def to_html(cls, slot):
        """Render a CSS grid whose cells are the composed panel reports."""
        config, panels = cls.from_snd(slot)
        cells = "".join(
            '<figure class="snakedone-panel">'
            + (
                f'<span class="snakedone-panel-label">({_panel_letter(index)})</span>'
                if config["labels"]
                else ""
            )
            + "{{"
            + str(index)
            + "}}</figure>"
            for index in range(len(panels))
        )
        style = f' style="--snakedone-cols:{config["ncol"]}"'
        return cls._htmlout(
            f'<div class="snakedone-compose"{style}>{cells}</div>', {}, tuple(panels)
        )

    @classmethod
    def render_node(cls, output, child_blocks):
        """Render the grid after substituting each rendered panel."""
        text = output.rendered.text
        for index, block in enumerate(child_blocks):
            text = text.replace("{{" + str(index) + "}}", block)
        return text

    runtime = Path(__file__).with_name("compose_runtime.js").read_text(encoding="utf-8")
