"""Label ordinary Python values and rich outputs with stable document anchors.

Jump to the [measurements](#sample-a) or the
[quality decision](#sample-a-decision).
"""

from pathlib import Path

from snakedone import Markdown, label

measurements = {"sample": "A", "score": 0.8, "passed": True}

if "snakedone":
    """
    # Labelled outputs

    Ordinary Python values use the same code representation as an unwrapped
    expression while gaining a stable anchor and caption. Continue to the
    [quality decision](#sample-a-decision).
    """
    label(measurements, "sample-a", "Sample A measurements")


readme = Path(__file__).parent.parent / "README.md"

if "snakedone":
    Markdown(readme.read_text(encoding="utf-8"))


if "snakedone":
    """
    The [measurements above](#sample-a) use the fallback renderer. A label can
    also wrap another renderer without changing its presentation.
    """
    label(
        Markdown("## Quality decision\n\nSample A passed the quality threshold."),
        "sample-a-decision",
    )
