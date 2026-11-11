"""Incremental migration of review records across archive rewrites.

Records are immutable facts about a version: a source's ``at`` is a span in
the version it was created in, and its ``cover`` names the region it came from
in the *immediately previous* version plus that version's ``before`` boundary.  A
migration therefore never rewrites an old record.  A live source whose region
moved or changed is frozen (``before`` set, its own text kept in ``source``) and
its new region is appended as live successors, each carrying a ``cover`` back
into the frozen source.  Movement alone is enough to need a successor: without
one the old coordinates could not be mapped forward.

The alignment is character-level: lines are diffed first (cheap and stable for
whole documents) and every replaced block is refined character by character,
so ``cover`` can name a part of an old line.  Records are cut at new-text
newlines, one whole line per record, so a single old span expresses the mapping
exactly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from difflib import SequenceMatcher

from ._records import Record, SourceRecord
from ._span import At, Span, _line, _starts, timestamp

__all__ = ["migrate"]


def _mapped_shift(offset: int, oa: int, ob: int, na: int, nb: int, *, end: bool):
    """Map one offset across a segment, spreading a replacement linearly."""
    if ob == oa:
        return nb if end else na
    if nb == na:
        return na
    if end:
        return na + -((-(offset - oa) * (nb - na)) // (ob - oa))
    return na + ((offset - oa) * (nb - na)) // (ob - oa)


class _Align:
    """The character segments shared by one old/new text pair.

    A segment is ``(old_start, old_stop, new_start, new_stop, equal)``; exact
    runs carry ``equal`` and the gaps are replacements, insertions or
    deletions, spread linearly when a region boundary falls inside one.
    """

    def __init__(self, old_text: str, new_text: str):
        self.old_text = old_text
        self.new_text = new_text
        self.old_starts = _starts(old_text)
        self.new_starts = _starts(new_text)

        segments: list[tuple[int, int, int, int, bool]] = []
        """old_start, old_stop, new_start, new_stop, is_equal"""
        old_previous = new_previous = 0
        for a, b, size in self._matched_blocks():
            if a > old_previous or b > new_previous:
                segments.append((old_previous, a, new_previous, b, False))
            segments.append((a, a + size, b, b + size, True))
            old_previous, new_previous = a + size, b + size
        if old_previous < len(old_text) or new_previous < len(new_text):
            segments.append(
                (old_previous, len(old_text), new_previous, len(new_text), False)
            )
        self.segments = segments
        self.old_segment_starts = [segment[0] for segment in segments]
        self.new_segment_starts = [segment[2] for segment in segments]

    def _matched_blocks(self):
        """Character ranges that correspond exactly between the two texts."""
        old_lines = self.old_text.splitlines()
        new_lines = self.new_text.splitlines()
        matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            oa = self.old_starts[i1]
            ob = self.old_starts[i2]
            na = self.new_starts[j1]
            if tag == "equal":
                yield oa, na, ob - oa
            elif tag == "replace":
                segment_old = self.old_text[oa:ob]
                nb = self.new_starts[j2]
                segment_new = self.new_text[na:nb]
                inner = SequenceMatcher(None, segment_old, segment_new, autojunk=False)
                for a, b, size in inner.get_matching_blocks():
                    if size:
                        yield oa + a, na + b, size

    def old_to_new(self, start: int, stop: int):
        """The new extent of an old character range (a point when deleted)."""
        if stop <= start:
            return None
        first = self.segments[_line(start, self.old_segment_starts)]
        begin = _mapped_shift(start, first[0], first[1], first[2], first[3], end=False)
        last = self.segments[_line(stop - 1, self.old_segment_starts)]
        end = _mapped_shift(stop, last[0], last[1], last[2], last[3], end=True)
        return begin, end

    def new_to_old(self, start: int, stop: int):
        """The old extent a new character range came from, or ``None``."""
        if stop <= start:
            return None
        first = self.segments[_line(start, self.new_segment_starts)]
        begin = _mapped_shift(start, first[2], first[3], first[0], first[1], end=False)
        last = self.segments[_line(stop - 1, self.new_segment_starts)]
        end = _mapped_shift(stop, last[2], last[3], last[0], last[1], end=True)
        return None if end <= begin else (begin, end)

    def insert(self: _Align, offset: int, stamp: str, old_starts: list[int]):
        """Mark a new line with no old counterpart as born at ``stamp``.

        ``cover`` names a zero-length point on the old line it was inserted before,
        so ``cover.time`` records when the line first appeared and the chain ends
        there instead of linking it to an unrelated neighbouring line.
        """
        segment = self.segments[_line(offset, self.new_segment_starts)]
        point = _mapped_shift(
            offset, segment[2], segment[3], segment[0], segment[1], end=False
        )
        return At(Span.empty(_line(point, old_starts), 0), stamp)

    def split(self, new_start: int, new_stop: int):
        """Cut a new character range at newlines, one record per line.

        Returns ``(new_span, old_span)`` pairs; ``old_span`` is ``None`` for an
        inserted line.
        """
        if new_stop <= new_start:
            return
        first = _line(new_start, self.new_starts)
        last = _line(new_stop - 1, self.new_starts)
        for line in range(first, last + 1):
            old_span = self.new_to_old(self.new_starts[line], self.new_starts[line + 1])
            if old_span is not None:
                old_span = Span.from_bound(*old_span, self.old_starts)
            yield Span(line, 0, line + 1, 0), old_span


def migrate(
    records: Sequence[Record],
    old_text: str,
    new_text: str,
    *,
    moment: datetime | None = None,
):
    """Update *records* for a body that changed from *old_text* to *new_text*.

    Old records are never rewritten.  A live source the change leaves alone is
    kept; otherwise it is frozen at the migration moment and its new region is
    appended as live successors linked back through ``cover``.
    Reviews keep the coordinates of the version they were written in.
    """
    if not records:
        return
    if old_text == new_text:
        yield from records
        return

    stamp = timestamp(moment)
    align = _Align(old_text, new_text)
    old_starts = align.old_starts
    new_starts = align.new_starts
    seen: set[int] = set()
    for record in records:
        if not isinstance(record, SourceRecord) or record.before is not None:
            yield record
            continue
        span = Span.parse(record.at)
        start, stop = span.bound(old_starts)
        old_segment = old_text[start:stop]
        extent = align.old_to_new(start, stop)
        if extent == (start, stop) and new_text[start:stop] == old_segment:
            lines = set(span.lines())
            if lines & seen:
                continue  # a duplicate of an earlier live source
            seen |= lines
            yield record
            continue
        yield replace(record, before=stamp, source=old_segment)
        if extent is None:
            continue
        new_start, new_stop = extent
        if new_stop <= new_start:
            # Fully deleted: keep a live zero-length successor at the point so
            # the chain can still be followed to where the region stood.
            at = Span.from_bound(new_start, new_start, new_starts)
            old = Span.from_bound(start, stop, old_starts)
            yield SourceRecord(at=str(at), cover=At(old, stamp))
            continue
        for new_span, old_span in align.split(new_start, new_stop):
            if new_span.start_line in seen:
                continue  # another live source already owns this line
            seen.add(new_span.start_line)
            cover = (
                At(old_span, stamp)
                if old_span is not None
                else align.insert(new_starts[new_span.start_line], stamp, old_starts)
            )
            yield SourceRecord(at=str(new_span), cover=cover)
    for line in range(len(new_starts) - 1):
        if line in seen:
            continue
        if align.new_to_old(new_starts[line], new_starts[line + 1]) is not None:
            continue  # the line came from the old text
        yield SourceRecord(
            at=str(Span(line, 0, line + 1, 0)),
            cover=align.insert(new_starts[line], stamp, old_starts),
        )
