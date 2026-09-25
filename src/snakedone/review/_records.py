"""The ``snakedone.review`` record model: schema, lookup, and serialization.

An archive may end with a plain-Python review block: an ``if
"snakedone.review":`` whose body is a single triple-quoted JSON array.  The
block is an ordinary ``if`` whose body is one JSON string, so it stays valid
Python with no dependencies and is ignored when the document runs.

Records are objects: :class:`SourceRecord` versions a run of lines (``at``)
whose actual change is ``diffRange``; :class:`ReviewRecord` carries an absolute
range plus the time its comment was written.  The version a review reads is
derived from its ``time`` (:meth:`ReviewIndex.exec_expire`): the source whose
``expire`` is the earliest one strictly after that time, treating a live source
as expiring at infinity.  There is no explicit parent link and no version chain
to maintain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import ClassVar

from ._span import TYPE_REVIEW, TYPE_SOURCE, Span, parse_time

__all__ = ["Record", "ReviewIndex", "ReviewRecord", "SourceRecord", "validate"]


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
    """A run of source lines (``at``) and the version it superseded."""

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
        if self.expire is None:
            if self.source is not None:
                raise ValueError("a live source must not carry source")
        else:
            parse_time(self.expire)
            if not isinstance(self.source, str):
                raise ValueError("an expired source must carry its source")


def _expiry(source: SourceRecord):
    """Sort key placing a live source (no ``expire``) after expired ones."""
    return (source.expire is None, source.expire or "")


@dataclass
class ReviewRecord(Record):
    """A range plus the time its comment was last edited."""

    TYPE: ClassVar[str] = TYPE_REVIEW

    time: str
    edit: str | None = None
    comment: str | None = None
    expireAt: dict[str, str] | None = None

    def validate(self):
        parse_time(self.time)
        Span.parse(self.at)
        if self.expireAt is None:
            return
        if not isinstance(self.expireAt, dict):
            raise ValueError("expireAt must map ranges to timestamps")
        for key, value in self.expireAt.items():
            Span.parse(key)
            parse_time(value)


def validate(records: Sequence[Record]):
    """Check the record invariants and raise :class:`ValueError` on violation."""
    for record in records:
        record.validate()


class ReviewIndex:
    """The parsed records of a review block, indexed for lookup.

    The original order is kept in :attr:`records` (the serialization source);
    :attr:`sources` and :attr:`reviews` partition it, and
    :attr:`sources_by_line` answers which version covered a line.  The index is
    rebuilt on every load, never stored: coordinates are remapped together with
    the sources when an archive is migrated.
    """

    def __init__(self, records: Sequence[Record]):
        self.records = list(records)
        self.sources: list[SourceRecord] = []
        self.reviews: list[ReviewRecord] = []
        self.sources_by_line: dict[int, list[SourceRecord]] = {}
        for record in self.records:
            if isinstance(record, SourceRecord):
                self.sources.append(record)
                for line in Span.parse(record.at).lines():
                    self.sources_by_line.setdefault(line, []).append(record)
            elif isinstance(record, ReviewRecord):
                self.reviews.append(record)
        for bucket in self.sources_by_line.values():
            bucket.sort(key=_expiry)

    def resolve(self):
        """Derive each review's ``expireAt`` from its ``time`` and the sources."""
        for review in self.reviews:
            review.expireAt = self.exec_expire(review)
        return self

    def exec_expire(self, review: ReviewRecord):
        """Derive a review's ``expireAt`` map from its ``time`` and the sources.

        Each contiguous run of lines that shares the same source version maps to
        that source's ``expire``; a run still on the live version is omitted.
        """
        span = Span.parse(review.at)
        moment = parse_time(review.time)
        result: dict[str, str] = {}
        start: int | None = None
        current: str | None = None
        for line in span.lines():
            source = self._live_at(line, moment)
            expire = None if source is None else source.expire
            if start is None:
                start, current = line, expire
            elif expire == current:
                continue
            else:
                if current is not None:
                    result[str(Span(start, 0, line - 1, -1))] = current
                start, current = line, expire
        if start is not None and current is not None:
            result[str(Span(start, 0, span.end_line, -1))] = current
        return result

    def _live_at(self, line: int, moment: datetime):
        """The source whose version was live at *moment* on *line*.

        The versions covering a line are kept sorted by ``expire`` (a live
        source last), so the first one not yet expired at *moment* is the
        version then current.  Returns ``None`` when no source covers the line.
        """
        for source in self.sources_by_line.get(line, ()):
            if source.expire is None or parse_time(source.expire) > moment:
                return source
        return None
