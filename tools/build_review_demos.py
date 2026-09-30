"""Regenerate the review demo archives and pages.

The trailing ``snakedone.review`` block is data that cannot be derived from the
``.py`` alone, so the demos cannot use the usual ``snakedone <doc>.py`` flow.
This script executes each document for its body, authors the review records
with fixed timestamps, derives ``coveredAt`` from them, and writes each ``.snd``
and ``.html`` next to its ``.py``.

    pixi run demo-review

The timestamps are fixed so a rerun is byte-identical; only edit them when the
demo's narration changes.
"""

from __future__ import annotations

from pathlib import Path

from snakedone.document import parse
from snakedone.review._block import render_block
from snakedone.review._records import ReviewIndex, ReviewRecord, SourceRecord
from snakedone.review._span import At, Span
from snakedone.snd import body_hash, write

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

# The git history of review_history.py, frozen for a deterministic demo.
T1 = "2026-09-01T09:00:00.000Z"  # timeout and retries first reviewed
T2 = "2026-09-05T09:00:00.000Z"  # retries changed to 5
TMID = "2026-09-06T09:00:00.000Z"  # the policy comment spans both lines
T3 = "2026-09-10T09:00:00.000Z"  # timeout changed to 60s
T4 = "2026-09-12T09:00:00.000Z"  # the 60s timeout reviewed, then changed again
T5 = "2026-09-15T09:00:00.000Z"  # timeout changed to 90s
T6 = "2026-09-16T09:00:00.000Z"  # batch size added and reviewed


def body_of(path: Path):
    """Execute *path* and return its archive body (no review block)."""
    document = parse(path.read_text(encoding="utf-8"), str(path))
    blocks, outputs, job = document.execute(path)
    return document.render_snd(blocks, outputs, job)


def line_of(body: str, marker: str):
    """The 0-based line index of the single body line containing *marker*."""
    found = [index for index, text in enumerate(body.splitlines()) if marker in text]
    if len(found) != 1:
        raise ValueError(f"expected one line with {marker!r}, found {found}")
    return found[0]


def whole(line: int):
    """The whole-line span at 0-based *line*."""
    return Span(line, 0, line + 1, 0)


def single_revision_records(body: str):
    """One revision: live annotations covering single lines, a cross-line range,
    and overlapping ranges."""
    sample_line = line_of(body, "draws three samples")
    tolerance_line = line_of(body, "A tolerance of 0.05")
    csv_line = line_of(body, "Results are written to the output directory")
    manifest_line = line_of(body, "A run manifest is written alongside it.")
    sample = whole(sample_line)
    tolerance = whole(tolerance_line)
    csv = whole(csv_line)
    manifest = whole(manifest_line)
    # A cross-line range over both sampling lines; it overlaps the per-line
    # reviews below.
    pair = Span(sample_line, 0, tolerance_line + 1, 0)
    # A partial range inside the sample line; it overlaps the whole-line review.
    phrase = "three samples"
    column = body.splitlines()[sample_line].index(phrase)
    part = Span(sample_line, column, sample_line, column + len(phrase))
    return [
        SourceRecord(at=str(sample)),
        SourceRecord(at=str(tolerance)),
        SourceRecord(at=str(csv)),
        SourceRecord(at=str(manifest)),
        ReviewRecord(
            time=T1, at=str(sample),
            comment="Three samples is a small pilot; watch the spread.",
        ),
        ReviewRecord(
            time=T1, at=str(tolerance),
            edit="A tolerance of 0.01 decides whether a sample is accepted.",
        ),
        ReviewRecord(
            time=T1, at=str(csv),
            edit="Results are written next to the document as a single CSV file.",
            comment="Keep outputs beside the source so they travel together.",
        ),
        ReviewRecord(
            time=T1, at=str(manifest),
            comment="Is the manifest checksummed?",
        ),
        # Cross-line: both sampling lines edited together; it overlaps the
        # sample-only and tolerance-only reviews.
        ReviewRecord(
            time=T1, at=str(pair),
            edit=(
                "The pipeline draws five samples from the input table and"
                " reports the median.\n"
                "A tolerance of 0.01 decides whether a sample is accepted."
            ),
            comment="The sample count and the tolerance are tuned as a pair.",
        ),
        # Partial overlap with the whole-line sample review above.
        ReviewRecord(
            time=T1, at=str(part),
            comment="Which three samples exactly?",
        ),
    ]


def cross_revision_records(body: str):
    """A chain over four revisions, including a partly superseded annotation."""
    timeout = line_of(body, "timeout: 90s")
    retries = line_of(body, "retries: 5")
    batch = line_of(body, "batch size: 100")
    return [
        # timeout: 30s, then 60s, now 90s: three versions of the same line,
        # each successor linked back to the one it replaced.
        SourceRecord(at=str(whole(timeout)), source="    - timeout: 30s\n", before=T3),
        SourceRecord(
            at=str(whole(timeout)), cover=At(whole(timeout), T3),
            source="    - timeout: 60s\n", before=T5,
        ),
        SourceRecord(at=str(whole(timeout)), cover=At(whole(timeout), T5)),
        # retries: 2, superseded earlier (T2).
        SourceRecord(at=str(whole(retries)), source="    - retries: 2\n", before=T2),
        SourceRecord(at=str(whole(retries)), cover=At(whole(retries), T2)),
        # The batch line was added in the last revision: a zero-length cover at
        # T6 records when it appeared, so older versions omit it.
        SourceRecord(
            at=str(whole(batch)), cover=At(Span.empty(batch, 0), T6),
        ),
        ReviewRecord(
            time=T1, at=str(whole(timeout)),
            comment="30s may be tight when the table is large; it has since changed.",
        ),
        ReviewRecord(
            time=T1, at=str(whole(retries)),
            comment="Two retries is plenty, but this line was raised to five.",
        ),
        # Spans the timeout and retry lines: written before the timeout change,
        # so only the timeout half is superseded and only deletion is allowed.
        ReviewRecord(
            time=TMID, at=str(Span(timeout, 0, retries + 1, 0)),
            comment="The retry policy needs a review; timeout and retries interact.",
        ),
        ReviewRecord(
            time=T4, at=str(whole(timeout)),
            comment="60s was reviewed here, then raised to 90s.",
        ),
        ReviewRecord(
            time=T6, at=str(whole(batch)),
            comment="New batch knob; the default looks fine.",
        ),
    ]


def build(stem: str, records_for):
    """Write ``examples/<stem>.snd`` and ``.html`` from authored *records_for*."""
    script = EXAMPLES / f"{stem}.py"
    body = body_of(script).rstrip("\n") + "\n"
    records = ReviewIndex(records_for(body)).records
    archive = body + "\n" + render_block(records, hash=body_hash(body)) + "\n"
    snd = EXAMPLES / f"{stem}.snd"
    write(snd, archive)
    page = parse(archive, str(snd)).render_html(title=stem)
    write(EXAMPLES / f"{stem}.html", page)
    print(f"{stem}: {len(records)} records, {len(page)} bytes of HTML")
    for record in records:
        if isinstance(record, ReviewRecord):
            covered_at = [str(cover) for cover in record.coveredAt or []]
            print(f"  review at {record.at}: coveredAt={covered_at}")


def main():
    build("review_demo", single_revision_records)
    build("review_history", cross_revision_records)


if __name__ == "__main__":
    main()
