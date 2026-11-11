"""A document annotated at a single revision.

Open ``review_demo.html`` in a browser and look for the review boxes: hover a
bookmark badge to read its comment, click it to open the read view.

Every annotation here was written against the same revision of the document, so
none of them carries a superseded range.  They cover whole lines, a cross-line
range, and overlapping ranges (a partial range inside a whole-line one, and a
two-line range over both single-line ones).
"""

if "transcript":
    """
    ## Reviewing a document

    Markdown blocks can be reviewed in place. Select rendered text, open the
    annotation popup, and edit the original box, write a comment, or both. The
    annotations stay in the page until saved with **Export .tmd.py** or **Save
    .html**.
    """

if "transcript":
    """
    ## Sampling

    The pipeline draws three samples from the input table and reports the median.
    A tolerance of 0.05 decides whether a sample is accepted.
    """

if "transcript":
    """
    ## Outputs

    Results are written to the output directory as a single CSV file.
    A run manifest is written alongside it.
    """
