"""The ``L``/``C`` coordinate grammar shared by review records.

The grammar is 1-based, but :class:`Span` stores 0-based half-open positions
(``[start, end)``) so it matches Python slicing.  A range ``A-B`` runs from A's
start to B's end; ``+N`` counts N characters from the start; a bare line ``L5``
means the whole line (up to the next line's start) while ``L5C3`` is a single
character.  A zero-length point is ``L5C3+0`` and is stored as ``start == end``.
"""

from __future__ import annotations

import bisect
from datetime import UTC, datetime
from typing import NamedTuple

TYPE_SOURCE = "source"
TYPE_REVIEW = "review"


def _parse_point(text: str):
    if not text.startswith("L"):
        raise ValueError(f"invalid coordinate: {text!r}")
    line_text, column_mark, column_text = text.strip()[1:].partition("C")
    return int(line_text), (int(column_text) if column_mark else None)


class Span(NamedTuple):
    """A 0-based half-open character range ``[start, end)``.

    A whole line ``L5`` is ``Span(4, 0, 5, 0)`` (ending at the next line's
    start); a zero-length point ``L5C3+0`` is ``Span(4, 2, 4, 2)``.
    """

    start_line: int
    """0-based line"""
    start_col: int
    """0-based column"""
    end_line: int
    """0-based exclusive line"""
    end_col: int
    """0-based exclusive column"""

    def lines(self):
        """
        >>> list(Span.parse("L1-L2").lines())
        [0, 1]
        >>> list(Span.parse("L5C3+1").lines())
        [4]
        >>> list(Span.parse("L5C3+0").lines())
        []
        """
        if (self.start_line, self.start_col) >= (self.end_line, self.end_col):
            return range(0)
        last = self.end_line if self.end_col > 0 else self.end_line - 1
        return range(self.start_line, last + 1)

    @classmethod
    def empty(cls, line: int, col: int):
        """A zero-length point at 0-based *line*/*col*, written ``LxCc+0``.

        >>> Span.empty(1, 0)
        Span(start_line=1, start_col=0, end_line=1, end_col=0)
        >>> str(Span.empty(2, 3))
        'L3C4+0'
        """
        return cls(line, col, line, col)

    @classmethod
    def parse(cls, text: str):
        """Parse a coordinate or range in the ``L/C`` grammar.

        >>> Span.parse("L5")
        Span(start_line=4, start_col=0, end_line=5, end_col=0)
        >>> Span.parse("L5C3+1")
        Span(start_line=4, start_col=2, end_line=4, end_col=3)
        >>> Span.parse("L5C3+4")
        Span(start_line=4, start_col=2, end_line=4, end_col=6)
        >>> Span.parse("L5C3+0")
        Span(start_line=4, start_col=2, end_line=4, end_col=2)
        >>> Span.parse("L1C1+0")
        Span(start_line=0, start_col=0, end_line=0, end_col=0)
        >>> Span.parse("L7-L9")
        Span(start_line=6, start_col=0, end_line=9, end_col=0)
        >>> Span.parse("L7-L9C1")
        Span(start_line=6, start_col=0, end_line=8, end_col=1)
        >>> Span.parse("L7C1-L9C1") == Span.parse("L7-L9C1")
        True
        >>> Span.parse("L5+2")
        Traceback (most recent call last):
            ...
        ValueError: invalid coordinate: 'L5+2'
        >>> Span.parse("5")
        Traceback (most recent call last):
            ...
        ValueError: invalid coordinate: '5'
        """
        text = text.strip()
        if "+" in text:
            point, length = text.split("+", 1)
            line, col = _parse_point(point)
            if col is None:
                raise ValueError(f"invalid coordinate: {text!r}")
            return cls(line - 1, col - 1, line - 1, col - 1 + int(length))
        start_text, separator, end_text = text.partition("-")
        if not separator:
            line, col = _parse_point(start_text)
            if col is None:
                return cls(line - 1, 0, line, 0)
            return cls(line - 1, col - 1, line - 1, col)
        start_line, start_col = _parse_point(start_text)
        end_line, end_col = _parse_point(end_text)
        return cls(
            start_line - 1,
            (start_col - 1) if start_col is not None else 0,
            end_line if end_col is None else end_line - 1,
            end_col if end_col is not None else 0,
        )

    def __str__(self):
        """Render a span back into the canonical coordinate grammar.

        >>> str(Span(4, 0, 5, 0))
        'L5'
        >>> str(Span(4, 2, 4, 3))
        'L5C3+1'
        >>> str(Span(4, 2, 4, 6))
        'L5C3+4'
        >>> str(Span.empty(4, 2))
        'L5C3+0'
        >>> str(Span(6, 0, 9, 0))
        'L7-L9'
        >>> str(Span(6, 0, 8, 1))
        'L7-L9C1'
        >>> str(Span(6, 1, 8, 1))
        'L7C2-L9C1'
        """
        l1, c1, l2, c2 = self
        if l1 == l2:
            return f"L{l1 + 1}C{c1 + 1}+{c2 - c1}"
        if c1 == c2 == 0 and l2 == l1 + 1:
            return f"L{l1 + 1}"
        start = f"L{l1 + 1}"
        if c1 != 0:
            start += f"C{c1 + 1}"
        end = f"L{l2}" if c2 == 0 else f"L{l2 + 1}C{c2}"
        return f"{start}-{end}"

    def to_span(self, parent: Span):
        """Map a shift (relative to the parent's first line) to absolute coordinates.

        >>> parent = Span.parse("L5C3+4")
        >>> span = Span.parse("L5C4+2")
        >>> shift = span.to_shift(parent)
        >>> shift
        Span(start_line=0, start_col=1, end_line=0, end_col=3)
        >>> shift.to_span(parent) == span
        True
        """

        def line(relative: int):
            return parent.start_line + relative

        def column(relative_line: int, column: int):
            return (parent.start_col if relative_line == 0 else 0) + column

        return Span(
            line(self.start_line),
            column(self.start_line, self.start_col),
            line(self.end_line),
            column(self.end_line, self.end_col),
        )

    def to_shift(self, parent: Span):
        """Invert :func:`to_span` for a span inside the parent region."""

        def line(absolute: int):
            return absolute - parent.start_line

        def column(absolute_line: int, column: int):
            offset = parent.start_col if absolute_line == parent.start_line else 0
            return column - offset

        return Span(
            line(self.start_line),
            column(self.start_line, self.start_col),
            line(self.end_line),
            column(self.end_line, self.end_col),
        )

    def extract(self, text: str):
        """Return the substring this span selects, or ``None`` when out of range.

        >>> text = "one\\ntwo\\nthree\\n"
        >>> Span.parse("L2").extract(text)
        'two\\n'
        >>> Span.parse("L2C2+1").extract(text)
        'w'
        >>> Span.parse("L1-L2").extract(text)
        'one\\ntwo\\n'
        >>> Span.parse("L9").extract(text) is None
        True
        >>> Span.parse("L2C2+0").extract(text)
        ''
        """
        starts = _starts(text)
        if not 0 <= self.start_line < len(starts):
            return None
        if not 0 <= self.end_line < len(starts):
            return None
        start = starts[self.start_line] + self.start_col
        end = starts[self.end_line] + self.end_col
        if start < 0 or start > end or end > len(text):
            return None
        return text[start:end]

    def bound(self, starts: list[int]):
        """The half-open character range a span selects."""
        length = starts[-1]
        if self.start_line >= len(starts) or self.end_line >= len(starts):
            return length, length
        start = starts[self.start_line] + self.start_col
        stop = starts[self.end_line] + self.end_col
        return start, min(stop, length)

    @classmethod
    def from_bound(cls, start: int, stop: int, starts: list[int]):
        """The span naming a half-open character range (whole lines when it fits)."""
        first = _line(start, starts)
        if stop <= start:
            return cls.empty(first, start - starts[first])
        last = _line(stop, starts)
        if start == starts[first] and stop == starts[last] and last > first:
            return cls(first, 0, last, 0)
        return cls(first, start - starts[first], last, stop - starts[last])


def _line(offset: int, starts: list[int]):
    return max(bisect.bisect_right(starts, offset) - 1, 0)


def _starts(text: str):
    """The character offset at which each line begins."""
    index = 0
    starts = [index]
    for index, char in enumerate(text, 1):
        if char == "\n":
            starts.append(index)
    if starts[-1] != index:
        starts.append(index)
    return starts


def timestamp(moment: datetime | None = None):
    """Return an ISO-8601 UTC timestamp with milliseconds and a ``Z`` suffix."""
    moment = datetime.now(UTC) if moment is None else moment
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_time(value: str):
    """Parse an ISO-8601 record timestamp, accepting a trailing ``Z``."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class At(NamedTuple):
    """A span with an optional expiry timestamp."""

    span: Span
    expired: str | None = None

    @classmethod
    def parse(cls, text: str):
        """Split an ``at`` value into its span and optional expiry timestamp.

        >>> At.parse("L35")
        At(span=Span(start_line=34, start_col=0, end_line=35, end_col=0), expired=None)
        >>> At.parse("L35 2026-09-21T10:00:00.000Z").expired
        '2026-09-21T10:00:00.000Z'
        """
        text = text.strip()
        coordinate, _, stamp = text.partition(" ")
        return cls(Span.parse(coordinate), (stamp.strip() or None))

    def __str__(self):
        """
        >>> str(At(Span(34, 0, 35, 0), None))
        'L35'
        >>> str(At(Span(34, 0, 35, 0), "2026-09-21T10:00:00.000Z"))
        'L35 2026-09-21T10:00:00.000Z'
        """
        span = str(self.span)
        return span if self.expired is None else f"{span} {self.expired}"
