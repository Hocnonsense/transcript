"""A document reviewed across four revisions.

Open ``review_history.html`` and click a review badge: the read view stacks the
versions of the reviewed range, newest at the bottom, marks each boundary's
insertions and deletions in its own colour, and drops the reviews written
against that version between the rows.

The review block records where each annotation sits and which revision of the
text it was written against. An annotation whose range is only partly
superseded cannot be edited: its recorded text no longer matches the current
document, so there is nothing coherent to edit. It can only be deleted.
"""

if "transcript.md":
    """
    ## Revisions

    The configuration below changed three times while it was being reviewed:

    - `retries` went from 2 to 5;
    - `timeout` went from 30s to 60s, and later to 90s;
    - `batch size` was added at the end.

    Annotations from earlier revisions are kept, so the configuration carries a
    short history: a comment on a line that has since changed is *fully
    superseded*; a comment spanning two lines, only one of which changed, is
    *partly superseded* and can no longer be edited, only deleted.
    """

if "transcript.md":
    """
    ## Configuration

    - timeout: 90s
    - retries: 5
    - log level: info
    - batch size: 100
    """

if "transcript.md":
    """
    The timeout and retry lines are annotated; the log level is not.
    """

if "transcript.review=sha256:2078ee290652d5f406892202557cb5161a713ff884133438c676f306952f639a":
    """[
    {"type": "source", "at": "L34", "source": "    - timeout: 30s\\n", "before": "2026-09-10T09:00:00.000Z"},
    {"type": "source", "at": "L34", "source": "    - timeout: 60s\\n", "cover": "L34@2026-09-10T09:00:00.000Z", "before": "2026-09-15T09:00:00.000Z"},
    {"type": "source", "at": "L34", "cover": "L34@2026-09-15T09:00:00.000Z"},
    {"type": "source", "at": "L35", "source": "    - retries: 2\\n", "before": "2026-09-05T09:00:00.000Z"},
    {"type": "source", "at": "L35", "cover": "L35@2026-09-05T09:00:00.000Z"},
    {"type": "source", "at": "L37", "cover": "L37C1+0@2026-09-16T09:00:00.000Z"},
    {"type": "review", "at": "L34", "time": "2026-09-01T09:00:00.000Z", "comment": "30s may be tight when the table is large; it has since changed.", "coveredAt": ["L34@2026-09-10T09:00:00.000Z"]},
    {"type": "review", "at": "L35", "time": "2026-09-01T09:00:00.000Z", "comment": "Two retries is plenty, but this line was raised to five.", "coveredAt": ["L35@2026-09-05T09:00:00.000Z"]},
    {"type": "review", "at": "L34-L35", "time": "2026-09-06T09:00:00.000Z", "comment": "The retry policy needs a review; timeout and retries interact.", "coveredAt": ["L34@2026-09-10T09:00:00.000Z"]},
    {"type": "review", "at": "L34", "time": "2026-09-12T09:00:00.000Z", "comment": "60s was reviewed here, then raised to 90s.", "coveredAt": ["L34@2026-09-15T09:00:00.000Z"]},
    {"type": "review", "at": "L37", "time": "2026-09-16T09:00:00.000Z", "comment": "New batch knob; the default looks fine."}
    ]"""
