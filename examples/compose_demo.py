"""Arrange several Vega-Lite charts into one panel grid."""

import pandas as pd

from snakedone import compose, label, vegalite

frame = pd.DataFrame(
    {
        "sample": ["A", "B", "C", "D"],
        "score": [0.8, 0.3, 0.9, 0.6],
        "count": [10, 25, 40, 15],
    }
)

score_by_sample = {
    "width": 360,
    "height": 240,
    "mark": "bar",
    "encoding": {
        "x": {"field": "sample", "type": "nominal"},
        "y": {"field": "score", "type": "quantitative"},
    },
}

score_by_count = {
    "width": 360,
    "height": 240,
    "mark": "point",
    "encoding": {
        "x": {"field": "count", "type": "quantitative"},
        "y": {"field": "score", "type": "quantitative"},
    },
}

fig1 = label(vegalite(score_by_sample, frame), "fig1", "Score")

if "snakedone":
    """
    # Composed panel grid

    The first chart is labelled and rendered as a interactive SVG
    """
    fig1

if "snakedone":
    """
    # Composed panel grid

    Four charts share a two-column grid. Each panel keeps its own renderer:
    the second is a labelled static SVG, while the others upgrade to
    interactive charts when the page is online.
    """
    compose(
        fig1,
        vegalite({**score_by_sample, "mark": "tick"}, frame),
        vegalite({**score_by_count, "mark": "area"}, frame),
        vegalite(score_by_count, frame, offline=True),
        ncol=2,
    )
