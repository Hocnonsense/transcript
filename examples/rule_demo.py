import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from transcript import image, markdown, rule

metadata = pl.DataFrame(
    {
        "sample": ["A", "B", "C", "D"],
        "score": [0.8, 0.3, 0.9, 0.6],
        "count": [10, 25, 40, 15],
    }
)

r = rule("demo")
with r:
    r.params(
        sample_lower=lambda _: _["sample"].lower(),
    )

r.wildcards(sample="A", feature="score")

if "transcript.md":
    """
    # Rule Demo

    This is a demo of a Snakemake rule that uses wildcards and parameters.
    The rule's input is the `metadata` DataFrame, and the output is a string
    that describes the sample and feature.

    The rule's parameters are derived from the input DataFrame, and the wildcards
    are used to select a specific sample and feature.

    ## Example Output

    The output of this rule for sample "A" and feature "score" is:

    ```
    sample_lower: a, value: 0.8
    ```
    """
    value = metadata.filter(pl.col("sample") == r.wildcards.sample)[
        r.wildcards.feature
    ].item()
    markdown(
        f'The output of this rule for sample "{r.wildcards.sample}"'
        f' and feature "{r.wildcards.feature}" is:'
    )
    print("sample_lower:", r.params.sample_lower, ", value:", value)


def curve(t, n=4000):
    def osc(f, p):
        return 0.5 - 0.5 * np.cos(2 * np.pi * f * t + p)

    m = 3 + int(np.round(13 * osc(0.770, 2.0)))
    n1 = 0.60 + 5.40 * osc(1.618, 0.8)
    n2 = 0.30 + 6.70 * osc(2.414, 4.7)
    n3 = 0.30 + 6.70 * osc(1.313, 5.1)
    rot = 2.4 * t

    th = np.linspace(0, 2 * np.pi, n)
    br = np.abs(np.cos(m * th / 4)) ** n2 + np.abs(np.sin(m * th / 4)) ** n3
    r = br ** (-1 / n1)
    r /= r.max()
    return r * np.cos(th + rot), r * np.sin(th + rot)


def draw(t: float):
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"}, figsize=(8, 8))
    x, y = curve(t)
    c = plt.cm.plasma(t)
    ax.fill(x, y, color=c, alpha=0.12, lw=0)
    ax.plot(x, y, color=c, lw=1.4)
    ax.set(xlim=(-1.05, 1.05), ylim=(-1.05, 1.05), aspect="equal")
    ax.axis("off")
    ax.set_title(f"t = {t:.2f}", fontsize=9)
    return ax


if "transcript.md":
    value = metadata.filter(pl.col("sample") == r.wildcards.sample)[
        r.wildcards.feature
    ].item()
    if value > 1:
        value = 1 / value

    image(draw(value))
