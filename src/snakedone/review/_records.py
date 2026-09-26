"""The ``snakedone.review`` record model: schema, lookup, and serialization.

An archive may end with a plain-Python review block: an ``if
"snakedone.review":`` whose body is a single triple-quoted JSON array.  The
block is an ordinary ``if`` whose body is one JSON string, so it stays valid
Python with no dependencies and is ignored when the document runs.

Records are objects: :class:`SourceRecord` versions a run of lines (``at``) and
maps each part back to the region it replaced (``newOlds``);
:class:`ReviewRecord` carries a range plus the time its comment was written.
Records are immutable: each names coordinates in the version it was made for,
and the ``newOlds`` pointers form a chain the history view walks.  A review's
``expireAt`` is derived from its ``time`` and the sources
(:meth:`ReviewIndex.exec_expire`) and refreshed on every load.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import datetime
from typing import ClassVar

from ._span import TYPE_REVIEW, TYPE_SOURCE, Span, parse_time

__all__ = ["Record", "ReviewIndex", "ReviewRecord", "SourceRecord"]


@dataclass
class Record:
    """Base class for the flat records in the review block.

    Subclasses are dataclasses.  :meth:`to_dict` emits the JSON object, skipping
    unset fields, and :meth:`from_dict` rebuilds the right subclass from JSON.
    """

    TYPE: ClassVar[str]
    at: str

    def to_dict(self):
        """Return the JSON object for this record, dropping unset fields."""
        data: dict = {"type": self.TYPE}
        for item in fields(self):
            key = item.name
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data

    def validate(self):
        """Raise :class:`ValueError` when the record violates its invariants."""

    @classmethod
    def from_dict(cls, data: dict):
        """Rebuild a record from its JSON object, rejecting unknown fields."""
        if not isinstance(data, dict):
            raise ValueError(f"a review record must be a JSON object: {data!r}")
        kind: str = data["type"]
        if kind == TYPE_SOURCE:
            target = SourceRecord
        elif kind == TYPE_REVIEW:
            target = ReviewRecord
        else:
            raise ValueError(f"unknown review record type: {kind!r}")
        kwargs = {}
        for item in fields(target):
            key = item.name
            if key in data:
                kwargs[key] = data[key]
        if data.keys() - kwargs.keys() - {"type"}:
            raise ValueError(f"unknown fields in review record: {data!r}")
        return target(**kwargs)


@dataclass
class SourceRecord(Record):
    """One whole source line (``at``) and the region it replaced.

    ``diffRange`` is the span in the *immediately previous* version that this
    whole line corresponds to (``None`` for an inserted line).  Cutting a
    migration at new-text newlines keeps every record line-sized, so a single
    old span expresses the line-to-line mapping exactly.  It belongs to that
    fixed previous version and is never remapped again; ``source`` is this
    record's own text (the superseded content).
    """

    TYPE: ClassVar[str] = TYPE_SOURCE

    source: str | None = None
    diffRange: str | None = None
    expire: str | None = None

    @classmethod
    def of(
        cls,
        span: Span,
        *,
        prev: Span | None = None,
        source: str | None = None,
        expire: str | None = None,
    ):
        """Build the record for *span*, changed over *prev*, expired at *expire*."""
        diffRange = None if prev is None else str(prev)
        return cls(at=str(span), source=source, diffRange=diffRange, expire=expire)

    def validate(self):
        Span.parse(self.at)
        if self.diffRange is not None:
            Span.parse(self.diffRange)
        if self.expire is not None:
            parse_time(self.expire)
            if not isinstance(self.source, str):
                raise ValueError("an expired source must carry its source")


def _expiry(source: SourceRecord):
    """Sort key placing a live source (no ``expire``) after expired ones.
    old first, live the last.
    """
    return (source.expire is None, source.expire or "")


@dataclass
class ReviewRecord(Record):
    """A range plus the time its comment was last edited."""

    TYPE: ClassVar[str] = TYPE_REVIEW

    time: str
    edit: str | None = None
    comment: str | None = None
    expireAt: dict[str, str] | None = None
    """Derived on load from ``time`` and the sources, then serialized:
    the ranges of ``at`` that a later version superseded, mapped to when.
    It is refreshed whenever written into the ``.snd``,
    html only reads it (at most to verify)."""

    def validate(self):
        parse_time(self.time)
        Span.parse(self.at)


class ReviewIndex:
    """The parsed records of a review block, indexed for lookup.

    The original order is kept in :attr:`records` (the serialization source);
    :attr:`sources` and :attr:`reviews` partition it, and
    :attr:`sources_by_line` groups sources by the line they cover so a review's
    ``expireAt`` can be derived.  The index is rebuilt on every load, never
    stored.
    """

    def __init__(self, records: Iterable[Record]):
        self.records = list(records)
        self.sources: list[SourceRecord] = []
        self.reviews: list[ReviewRecord] = []
        self.sources_by_line: dict[int, list[SourceRecord]] = {}
        for record in self.records:
            record.validate()
            if isinstance(record, SourceRecord):
                self.sources.append(record)
                for line in Span.parse(record.at).lines():
                    self.sources_by_line.setdefault(line, []).append(record)
            elif isinstance(record, ReviewRecord):
                self.reviews.append(record)
        for bucket in self.sources_by_line.values():
            bucket.sort(key=_expiry)
        for record in self.reviews:
            missing = set(Span.parse(record.at).lines()) - self.sources_by_line.keys()
            if missing:
                raise ValueError(
                    f"review at {record.at} is not covered by a source"
                    f" (lines {sorted(missing)})"
                )
        for review in self.reviews:
            review.expireAt = self.exec_expire(review) or None  # discard when to_dict

    def exec_expire(self, review: ReviewRecord):
        """Derive a review's ``expireAt`` map from its ``time`` and the sources.

        Each contiguous run of lines that shares the same source version maps to
        that source's ``expire``; a run still on the live version is omitted.
        """
        span = Span.parse(review.at)
        moment = parse_time(review.time)
        line_expire_at: dict[str, str] = {}
        start: int | None = None
        current: str | None = None
        for line in span.lines():
            source = self._live_at(line, moment)
            expire = None if source is None else source.expire
            if start is None:  # the first line of review
                start, current = line, expire
            elif expire == current:
                continue
            else:  # zone of current ends, record the span
                if current is not None:
                    line_expire_at[str(Span(start, 0, line, 0))] = current
                start, current = line, expire
        if start is not None and current is not None:
            line_expire_at[str(Span(start, 0, line + 1, 0))] = current
        return line_expire_at

    def _live_at(self, line: int, moment: datetime):
        """The source whose version was live at *moment* on *line*.

        Find a line in the history: the first one not yet expired at *moment*.
        Returns ``None`` when no source covers the line.
        """
        for source in self.sources_by_line.get(line, ()):
            if source.expire is None or parse_time(source.expire) > moment:
                return source
