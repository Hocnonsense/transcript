"""Render pandas and polars DataFrames using the same Datavzrd configuration."""

import pandas as pd
import polars as pl

from transcript import datavzrd, table

measurements = {
    "sample": ["A", "B", "C", "D"],
    "score": [0.8, 0.3, 0.9, 0.6],
    "count": [10, 25, 40, 15],
}
pandas_frame = pd.DataFrame(measurements)
polars_frame = pl.DataFrame(measurements)

if "transcript.md":
    """
    # Interactive DataFrames

    Both tables use the adjacent `datavzrd.yaml` configuration.
    The Scores view shows bars and a heatmap; the Raw view shows the values.

    ## pandas
    """
    datavzrd(pandas_frame, "datavzrd.yaml")

if "transcript.md":
    """
    ## polars
    """
    datavzrd(polars_frame, "datavzrd.yaml")
    polars_frame.write_csv()

if "transcript.md":
    """
    The exported HTML contains both reports and can be shared as one offline file.
    """
    polars_frame.write_csv()
    print(polars_frame.write_csv())
    polars_frame

if "transcript.md":
    """
    Or you can use the :func:`transcript.table` renderer to simply show a
    static Markdown table.
    """
    table(pandas_frame)
