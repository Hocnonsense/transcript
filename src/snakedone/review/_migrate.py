"""Incremental migration of review records across archive rewrites.

The archive body (with the review block removed) is compared line by line
against the newly rendered body.  A live ``source`` whose lines changed is
expired at the migration moment and keeps the old text; the changed new lines
get a fresh live source.  Every source's coordinates and every review's ``at``
move with the diff; a record whose lines no longer exist is dropped, taking its
reviews with it.  ``expireAt`` is derived, so a review whose range moved drops
its stale map.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

from ._records import Record, ReviewRecord, SourceRecord
from ._span import Span, timestamp

__all__ = ["migrate"]

_DIFF = tuple[Literal["replace", "delete", "insert", "equal"], int, int, int, int]


def diff(old_text: str, new_text: str) -> list[_DIFF]:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    return matcher.get_opcodes()


def _line_diff(line: int, opcodes: list[_DIFF]):
    """Map a 0-based old line to a 0-based new line, or ``None`` if deleted."""
    for tag, i1, i2, j1, j2 in opcodes:
        if not (i1 <= line < i2):
            continue
        offset = line - i1
        if tag == "equal":
            return j1 + offset
        if tag == "delete" or j2 <= j1:
            # replace / insert: clamp into the available new range
            break
        return j1 + min(offset, j2 - j1 - 1)


def map_diffs(span: Span, opcodes: list[_DIFF]):
    start = _line_diff(span.start_line, opcodes)
    end = _line_diff(span.end_line, opcodes)
    if start is None or end is None:
        return None
    if end < start:
        end = start
    if span.end_line != span.start_line and end == start:
        return Span(start, 0, start, -1)
    return Span(start, span.start_col, end, span.end_col)


def changed(opcodes: list[_DIFF], span: Span):
    """Whether any old line in *span* is not part of an equal block."""
    lines = set(span.lines())
    for tag, i1, i2, _, _ in opcodes:
        if tag == "equal":
            continue
        if lines & set(range(i1, i2)):
            return True
    return False


def _changed_lines(opcodes: list[_DIFF], span: Span):
    lines = set(span.lines())
    result: set[int] = set()
    for tag, i1, i2, _, _ in opcodes:
        if tag != "equal":
            result |= lines & set(range(i1, i2))
    return result


def _merge(runs: list[tuple[Span, Span]]):
    """Merge overlapping or adjacent new spans, unioning their previous spans."""
    merged: list[tuple[Span, Span]] = []
    for new, prev in sorted(runs, key=lambda item: item[0].start_line):
        if merged and new.start_line <= merged[-1][0].end_line + 1:
            last_new, last_prev = merged[-1]
            merged[-1] = (
                Span(last_new.start_line, 0, max(last_new.end_line, new.end_line), -1),
                Span(
                    min(last_prev.start_line, prev.start_line),
                    0,
                    max(last_prev.end_line, prev.end_line),
                    -1,
                ),
            )
        else:
            merged.append((new, prev))
    return merged


def migrate(
    records: Sequence[Record],
    old_text: str,
    new_text: str,
    *,
    moment: datetime | None = None,
) -> list[Record]:
    """Update *records* for a body that changed from *old_text* to *new_text*."""
    if not records:
        return []
    opcodes = diff(old_text, new_text)
    if all(tag == "equal" for tag, _, _, _, _ in opcodes):
        return list(records)
    stamp = timestamp(moment)
    kept: list[Record] = []
    fresh: list[tuple[Span, Span]] = []
    for record in records:
        if not isinstance(record, SourceRecord):
            kept.append(record)
            continue
        span = Span.parse(record.at)
        mapped = map_diffs(span, opcodes)
        if mapped is None:
            continue
        updated = replace(record, at=str(mapped))
        if record.diffRange is not None:
            diff_range = map_diffs(Span.parse(record.diffRange), opcodes)
            if diff_range is not None:
                updated = replace(updated, diffRange=str(diff_range))
        touched_lines = _changed_lines(opcodes, span)
        if record.expire is None and touched_lines:
            text = span.extract(old_text)
            updated = replace(
                updated, expire=stamp, source="" if text is None else text
            )
            run = Span(min(touched_lines), 0, max(touched_lines), -1)
            fresh_span = map_diffs(run, opcodes)
            if fresh_span is not None:
                fresh.append((fresh_span, run))
        kept.append(updated)
    for new_span, prev in _merge(fresh):
        kept.append(SourceRecord.of(new_span, prev=prev))
    result: list[Record] = []
    for record in kept:
        if not isinstance(record, ReviewRecord):
            result.append(record)
            continue
        mapped = map_diffs(Span.parse(record.at), opcodes)
        if mapped is None:
            continue
        updated = replace(record, at=str(mapped))
        if record.at != updated.at:
            updated = replace(updated, expireAt=None)
        result.append(updated)
    return result
