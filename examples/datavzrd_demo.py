"""Render pandas and polars DataFrames using the same Datavzrd configuration."""

import pandas as pd
import polars as pl

from snakedone import datavzrd

measurements = {
    "sample": ["A", "B", "C", "D"],
    "score": [0.8, 0.3, 0.9, 0.6],
    "count": [10, 25, 40, 15],
}
pandas_frame = pd.DataFrame(measurements)
polars_frame = pl.DataFrame(measurements)

if "snakedone":
    """
    # Interactive DataFrames

    Both tables use the adjacent `datavzrd.yaml` configuration.
    The Scores view shows bars and a heatmap; the Raw view shows the values.

    ## pandas
    """
    datavzrd(pandas_frame, "datavzrd.yaml")

if "snakedone":
    """
    ## polars
    """
    datavzrd(polars_frame, "datavzrd.yaml")
    polars_frame.write_csv()

if "snakedone":
    """
    The exported HTML contains both reports and can be shared as one offline file.
    """
    polars_frame.write_csv()
    polars_frame
