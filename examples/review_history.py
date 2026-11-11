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

if "transcript":
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

if "transcript":
    """
    ## Configuration

    - timeout: 90s
    - retries: 5
    - log level: info
    - batch size: 100
    """

if "transcript":
    """
    The timeout and retry lines are annotated; the log level is not.
    """
