"""Render pandas and polars DataFrames as static and interactive charts."""

import pandas as pd
import polars as pl

from snakedone import vegalite

measurements = {
    "sample": ["A", "B", "C", "D"],
    "score": [0.8, 0.3, 0.9, 0.6],
    "count": [10, 25, 40, 15],
}
pandas_frame = pd.DataFrame(measurements)
polars_frame = pl.DataFrame(measurements)

if "snakedone":
    """
    # Vega-Lite charts

    The pandas chart is a pure static SVG built from the adjacent
    `vegalite.yaml`; the polars chart upgrades to an interactive scatter from
    an inline specification when the page is online (hover a point for its
    recorded values).

    ## pandas (offline)
    """
    vegalite(pandas_frame, "vegalite.yaml", offline=True)

config_dict = {
    "width": 500,
    "height": 300,
    "mark": "point",
    "encoding": {
        "x": {"field": "sample", "type": "nominal"},
        "y": {"field": "score", "type": "quantitative"},
        "tooltip": [
            {"field": "sample", "type": "nominal"},
            {"field": "score", "type": "quantitative"},
            {"field": "count", "type": "quantitative"},
        ],
    },
}

if "snakedone":
    """
    ## polars (interactive)
    """
    vegalite(polars_frame, config_dict)
