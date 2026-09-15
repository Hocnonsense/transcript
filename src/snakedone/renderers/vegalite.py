"""Vega-Lite renderer: snapshot DataFrames as SVG or upgraded charts."""

import json
from collections.abc import Mapping

from ..output import Renderer
from . import ConfigType, jsonify, load_spec, register

_CDN = [
    "https://cdn.jsdelivr.net/npm/vega@6",
    "https://cdn.jsdelivr.net/npm/vega-lite@6.4",
    "https://cdn.jsdelivr.net/npm/vega-embed@6",
]

_DEFAULT_WIDTH = 800
_DEFAULT_HEIGHT = 450

_STYLE = """
/* static and interactive Vega-Lite charts */
.snakedone-chart { margin: .5rem 0; text-align: center; }
.snakedone-chart svg { display: block; margin: 0 auto; max-width: 100%; height: auto; }
/* The action menu reserves 38px on the right; nudge back to true center. */
.snakedone-chart .vega-embed.has-actions { transform: translateX(19px); }
.snakedone-status { display: block; width: max-content; margin: .15rem 0 0 auto;
                    padding: .1rem .5rem;
                    font: .72rem/1.5 ui-monospace, monospace; color: #888;
                    border: 1px solid #8884; border-radius: 999px; }
.snakedone-status[data-state="rendering"] { color: #b8860b; border-color: #b8860b66; }
.snakedone-status[data-state="interactive"] { color: #3984c6; border-color: #3984c666; }
"""

# A status hint next to every chart: ``offline`` (static preview), ``rendering``
# (loading the runtime), ``interactive`` (the dynamic chart is live).
_STATUS = (
    '<span class="snakedone-status" data-state="offline" role="status">'
    "offline</span>"
)

# The report starts from the static preview and upgrades it to an interactive
# chart once the Vega runtime is available. Offline (or with JavaScript
# disabled) the preview stays, so the report keeps working without a network.
_LOADER_SCRIPT = """
(function () {
  const charts = [];
  document.querySelectorAll('script.snakedone-vegalite-spec').forEach(node => {
    charts.push({ node: node, container: node.parentElement });
  });
  if (!charts.length) return;
  const sources = __SOURCES__;
  const dark = window.matchMedia('(prefers-color-scheme: dark)');
  const darkConfig = {
    background: 'transparent',
    axis: {
      domainColor: '#888', gridColor: '#3a3a3a', tickColor: '#888',
      labelColor: '#d5d5d5', titleColor: '#d5d5d5',
    },
    legend: {labelColor: '#d5d5d5', titleColor: '#d5d5d5'},
    title: {color: '#d5d5d5'},
    view: {stroke: '#888'},
  };
  function setState(container, state) {
    const status = container.querySelector('.snakedone-status');
    if (status) {
      status.dataset.state = state;
      status.textContent = state;
    }
  }
  charts.forEach(chart => setState(chart.container, 'rendering'));
  function load(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }
  function upgrade() {
    charts.forEach(chart => {
      const node = chart.node;
      const preview = chart.container.querySelector('.snakedone-preview');
      const target = document.createElement('div');
      const spec = JSON.parse(node.textContent);
      const config = dark.matches ? darkConfig : {background: 'transparent'};
      vegaEmbed(target, spec, {renderer: 'svg', config}).then(
        () => {
          if (preview) preview.replaceWith(target);
          else node.before(target);
          node.remove();
          setState(chart.container, 'interactive');
        },
        () => {
          setState(chart.container, 'offline');
        },
      );
    });
  }
  sources
    .reduce((chain, src) => chain.then(() => load(src)), Promise.resolve())
    .then(upgrade)
    .catch(() => charts.forEach(chart => setState(chart.container, 'offline')));
})();
""".replace("__SOURCES__", json.dumps(_CDN))


def _records(rows):
    """Export pandas or polars rows through their public methods, without imports."""
    if callable(getattr(rows, "to_dicts", None)):
        rows = rows.to_dicts()
    elif callable(getattr(rows, "to_dict", None)) and hasattr(rows, "columns"):
        rows = rows.to_dict(orient="records")
    if not isinstance(rows, list):
        raise TypeError("DataFrame record export must return a list")
    return jsonify(rows, context="Vega-Lite output")


def vegalite(data, spec: ConfigType, *, offline: bool = False):
    """Record a DataFrame for Vega-Lite rendering during HTML export.

    ``spec`` is a Vega-Lite specification mapping or a ``.json``/YAML filename.
    snakedone manages the chart data: the recorded rows are bound to the
    top-level ``data``, so the spec must not depend on its own ``data`` or
    ``datasets``. Relative filenames are resolved against the current working
    directory, like any Python file read.

    By default the chart is a static preview that a browser upgrades to an
    interactive chart (tooltips, zoom, action menu) once the Vega runtime can
    be loaded from a CDN; a status hint next to the chart shows whether it is
    ``offline``, ``rendering``, or ``interactive``. ``offline=True`` keeps the
    chart a pure static SVG: no dynamic rendering, no CDN, and the report keeps
    its strict Content Security Policy.
    """
    spec = load_spec(spec)
    if not isinstance(spec, Mapping):
        raise TypeError("Vega-Lite spec must be a mapping or a JSON/YAML filename")
    snapshot = jsonify(spec, context="Vega-Lite output")
    snapshot.pop("data", None)
    snapshot.pop("datasets", None)
    snapshot.setdefault("width", _DEFAULT_WIDTH)
    snapshot.setdefault("height", _DEFAULT_HEIGHT)
    snapshot["data"] = {"values": _records(data)}
    return (VegaliteOffline if offline else VegaliteInteractive)(snapshot)


class _VegaliteBase(Renderer):
    """Shared snapshot handling for the static and interactive renderers."""

    version = (1,)
    STYLE = _STYLE

    def __init__(self, spec):
        self._validate(spec)
        self.spec = spec

    def serialize(self):
        """Return the spec and data records serialized as JSON."""
        return json.dumps(self.spec, sort_keys=True, indent=2, allow_nan=False)

    @classmethod
    def _validate(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Vega-Lite output data must be a mapping")

    @classmethod
    def _svg(cls, parsed: dict):
        try:
            import vl_convert
        except ImportError as error:
            raise RuntimeError(
                'Vega-Lite HTML export requires: pip install "snakedone[vegalite]"'
            ) from error
        # Keep Vega-Lite's default white background: a transparent preview
        # would render dark text invisible on the report's dark color scheme.
        return vl_convert.vegalite_to_svg(parsed, allowed_base_urls=[])


@register
class VegaliteOffline(_VegaliteBase):
    """Render a snapshot to a static SVG chart during HTML export."""

    name = "vegalite_offline"

    @classmethod
    def to_html(cls, data: str):
        """Render stored data to a static SVG chart with no report files."""
        parsed = json.loads(data)
        cls._validate(parsed)
        return cls._htmlout(
            '<div class="snakedone-chart"><div class="snakedone-frame">'
            f"{cls._svg(parsed)}{_STATUS}</div></div>",
            {},
        )


@register
class VegaliteInteractive(_VegaliteBase):
    """Show a static preview and upgrade it online to an interactive chart."""

    name = "vegalite_interactive"

    @classmethod
    def to_html(cls, data: str):
        """Return the static preview plus the spec the browser runtime embeds."""
        parsed = json.loads(data)
        cls._validate(parsed)
        body = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        body = body.replace("<", "\\u003c")
        return cls._htmlout(
            '<div class="snakedone-chart">'
            f'<div class="snakedone-preview">{cls._svg(parsed)}</div>'
            f"{_STATUS}"
            '<script type="application/json" class="snakedone-vegalite-spec">'
            f"{body}</script></div>",
            {},
        )

    runtime = _LOADER_SCRIPT
    """Return the loader that upgrades previews when the CDN is reachable."""

    sources = ["https://cdn.jsdelivr.net"]
    """Allow the Vega runtime scripts from the jsDelivr CDN."""
