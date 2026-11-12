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
    """
    ```transcript-output datavzrd=1
    {
      "config": {
        "default-view": "scores",
        "name": "DataFrame measurements",
        "views": {
          "raw": {
            "dataset": "data",
            "desc": "Original values without column plots."
          },
          "scores": {
            "dataset": "data",
            "desc": "Scores as bars and counts as a heatmap.",
            "page-size": 2,
            "render-table": {
              "columns": {
                "count": {
                  "plot": {
                    "heatmap": {
                      "color-scheme": "blues",
                      "scale": "linear"
                    }
                  }
                },
                "score": {
                  "plot": {
                    "bars": {
                      "domain": [
                        0,
                        1
                      ],
                      "scale": "linear"
                    }
                  },
                  "precision": 2
                }
              }
            }
          }
        }
      },
      "csv": "sample,score,count\\nA,0.8,10\\nB,0.3,25\\nC,0.9,40\\nD,0.6,15\\n"
    }
    ```
    """

if "transcript.md":
    """
    ## polars
    """
    datavzrd(polars_frame, "datavzrd.yaml")
    """
    ```transcript-output datavzrd=1
    {
      "config": {
        "default-view": "scores",
        "name": "DataFrame measurements",
        "views": {
          "raw": {
            "dataset": "data",
            "desc": "Original values without column plots."
          },
          "scores": {
            "dataset": "data",
            "desc": "Scores as bars and counts as a heatmap.",
            "page-size": 2,
            "render-table": {
              "columns": {
                "count": {
                  "plot": {
                    "heatmap": {
                      "color-scheme": "blues",
                      "scale": "linear"
                    }
                  }
                },
                "score": {
                  "plot": {
                    "bars": {
                      "domain": [
                        0,
                        1
                      ],
                      "scale": "linear"
                    }
                  },
                  "precision": 2
                }
              }
            }
          }
        }
      },
      "csv": "sample,score,count\\nA,0.8,10\\nB,0.3,25\\nC,0.9,40\\nD,0.6,15\\n"
    }
    ```
    """
    polars_frame.write_csv()
    """
    'sample,score,count\\nA,0.8,10\\nB,0.3,25\\nC,0.9,40\\nD,0.6,15\\n'
    """

if "transcript.md":
    """
    The exported HTML contains both reports and can be shared as one offline file.
    """
    polars_frame.write_csv()
    """
    'sample,score,count\\nA,0.8,10\\nB,0.3,25\\nC,0.9,40\\nD,0.6,15\\n'
    """
    print(polars_frame.write_csv())
    """
    sample,score,count
    A,0.8,10
    B,0.3,25
    C,0.9,40
    D,0.6,15
    """
    polars_frame
    """
    shape: (4, 3)
    ┌────────┬───────┬───────┐
    │ sample ┆ score ┆ count │
    │ ---    ┆ ---   ┆ ---   │
    │ str    ┆ f64   ┆ i64   │
    ╞════════╪═══════╪═══════╡
    │ A      ┆ 0.8   ┆ 10    │
    │ B      ┆ 0.3   ┆ 25    │
    │ C      ┆ 0.9   ┆ 40    │
    │ D      ┆ 0.6   ┆ 15    │
    └────────┴───────┴───────┘
    """

if "transcript.md":
    """
    Or you can use the :func:`transcript.table` renderer to simply show a
    static Markdown table.
    """
    table(pandas_frame)
    """
    ```transcript-output markdown=1
    | sample | score | count |
    | --- | --- | --- |
    | A | 0.8 | 10 |
    | B | 0.3 | 25 |
    | C | 0.9 | 40 |
    | D | 0.6 | 15 |
    ```
    """
