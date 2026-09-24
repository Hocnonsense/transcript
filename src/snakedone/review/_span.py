"""The ``L``/``C`` coordinate grammar shared by review records.

The grammar is 1-based, but :class:`Span` stores 0-based inclusive coordinates
so indexing into Python sequences needs no adjustment.
A range ``A-B`` runs from A's start to B's end,
 and ``+N`` counts N characters from the start;
a bare line ``L5`` means the whole line while ``L5C3`` is a single character.
An ``end_col`` of ``-1`` marks the end of a whole line.
"""

from __future__ import annotations

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
    """A 0-based inclusive character range.

    ``end_col == -1`` marks the end of a whole line, so a bare ``L5``
      and a ``L5-L5`` range are both ``Span(4, 0, 4, -1)``.
    """

    start_line: int
    """0-based line"""
    start_col: int
    """0-based column"""
    end_line: int
    """0-based line"""
    end_col: int
    """0-based column, or -1 for the whole line"""

    def lines(self):
        """
        >>> span = Span(0, 0, 1, -1)
        >>> list(span.lines())
        [0, 1]
        """
        return range(self.start_line, self.end_line + 1)

    @classmethod
    def parse(cls, text: str):
        """Parse a coordinate or range in the ``L/C`` grammar.

        >>> Span.parse("L5")
        Span(start_line=4, start_col=0, end_line=4, end_col=-1)
        >>> Span.parse("L5C3+1")
        Span(start_line=4, start_col=2, end_line=4, end_col=2)
        >>> Span.parse("L5C3+4")
        Span(start_line=4, start_col=2, end_line=4, end_col=5)
        >>> Span.parse("L7-L9")
        Span(start_line=6, start_col=0, end_line=8, end_col=-1)
        >>> Span.parse("L7-L9C1")
        Span(start_line=6, start_col=0, end_line=8, end_col=0)
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
            return cls(line - 1, col - 1, line - 1, col + int(length) - 2)
        start_text, separator, end_text = text.partition("-")
        if not separator:
            line, col = _parse_point(start_text)
            if col is None:
                return cls(line - 1, 0, line - 1, -1)
            return cls(line - 1, col - 1, line - 1, col - 1)
        start_line, start_col = _parse_point(start_text)
        end_line, end_col = _parse_point(end_text)
        return cls(
            start_line - 1,
            (start_col - 1) if start_col is not None else 0,
            end_line - 1,
            (end_col - 1) if end_col is not None else -1,
        )

    def __str__(self):
        """Render a span back into the canonical coordinate grammar.

        >>> str(Span(4, 0, 4, -1))
        'L5'
        >>> str(Span(4, 2, 4, 2))
        'L5C3+1'
        >>> str(Span(4, 2, 4, 5))
        'L5C3+4'
        >>> str(Span(6, 0, 8, 0))
        'L7-L9C1'
        >>> str(Span(6, 1, 8, 0))
        'L7C2-L9C1'
        """
        l1, c1, l2, c2 = self
        if l1 == l2:
            line = l1 + 1
            if c1 == 0 and c2 == -1:
                return f"L{line}"
            return f"L{line}C{c1 + 1}+{c2 - c1 + 1}"
        start = f"L{l1 + 1}"
        if c1 != 0:
            start += f"C{c1 + 1}"
        end = f"L{l2 + 1}"
        if c2 != -1:
            end += f"C{c2 + 1}"
        return f"{start}-{end}"

    def to_span(self, parent: Span):
        """Map a shift (relative to the parent's first line) to absolute coordinates.

        >>> parent = Span.parse("L5C3+4")
        >>> span = Span.parse("L5C4+2")
        >>> shift = span.to_shift(parent)
        >>> shift
        Span(start_line=0, start_col=1, end_line=0, end_col=2)
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
        """

        def check_last(line: str):
            line_length = len(line)
            if self.end_col < 0:
                return line_length
            if self.end_col < line_length:
                return self.end_col + 1

        lines = text.splitlines(keepends=True)
        if self.start_line < 0 or len(lines) <= self.end_line:
            return None
        if self.start_line == self.end_line:
            line = lines[self.start_line]
            end = check_last(line)
            if end is None:
                return None
            return line[self.start_col : end]
        last = lines[self.end_line]
        end = check_last(last)
        if end is None:
            return None
        parts = [
            lines[self.start_line][self.start_col :],
            *lines[self.start_line + 1 : self.end_line],
            last[:end],
        ]
        return "".join(parts)

    def to_record(
        self,
        prev: Span | None = None,
        text: str | None = None,
        expire: str | None = None,
    ):
        """Build a ``source`` record for *at*, changed over *diff_range*."""
        record = {"type": TYPE_SOURCE, "at": str(self)}
        if prev is not None:
            record["diffRange"] = str(prev)
        if expire is not None:
            record["expire"] = expire
            if text is not None:
                record["text"] = text
        return record


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
        At(span=Span(start_line=34, start_col=0, end_line=34, end_col=-1), expired=None)
        >>> At.parse("L35 2026-09-21T10:00:00.000Z").expired
        '2026-09-21T10:00:00.000Z'
        """
        text = text.strip()
        coordinate, _, stamp = text.partition(" ")
        return cls(Span.parse(coordinate), (stamp.strip() or None))

    def __str__(self):
        """
        >>> str(At(Span(34, 0, 34, -1), None))
        'L35'
        >>> str(At(Span(34, 0, 34, -1), "2026-09-21T10:00:00.000Z"))
        'L35 2026-09-21T10:00:00.000Z'
        """
        span = str(self.span)
        return span if self.expired is None else f"{span} {self.expired}"
