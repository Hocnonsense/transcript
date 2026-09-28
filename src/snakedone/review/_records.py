"""The ``snakedone.review`` record model: schema, lookup, and serialization.

An archive may end with a plain-Python review block: an ``if
"snakedone.review":`` whose body is a single triple-quoted JSON array.  The
block is an ordinary ``if`` whose body is one JSON string, so it stays valid
Python with no dependencies and is ignored when the document runs.

Records are objects: :class:`SourceRecord` versions a run of lines (``at``) and
points back to the region it replaced (``cover``);
:class:`ReviewRecord` carries a range plus the time its comment was written.
Records are immutable: each names coordinates in the version it was made for,
and the ``cover`` pointers form a chain the history view walks.  A review's
``coveredAt`` entries are derived from its ``time`` and the sources
(:meth:`ReviewIndex.covered_at`) and refreshed on every load.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import datetime
from typing import ClassVar

from ._span import TYPE_REVIEW, TYPE_SOURCE, Span, parse_time

__all__ = ["Cover", "Record", "ReviewIndex", "ReviewRecord", "SourceRecord"]


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
        return target._from_dict(kwargs)


@dataclass(frozen=True)
class Cover:
    """A source span paired with the version stamp that covered it."""

    span: Span
    stamp: str

    def validate(self):
        if not isinstance(self.span, Span) or not isinstance(self.stamp, str):
            raise ValueError("cover must pair a Span with a timestamp")
        parse_time(self.stamp)

    def __str__(self):
        return f"{self.span}@{self.stamp}"

    @classmethod
    def parse(cls, text: str):
        """Parse one archive ``span@stamp`` value."""
        if not isinstance(text, str):
            raise ValueError("cover must be a span@stamp string")
        span, separator, stamp = text.partition("@")
        if not separator or not span or not stamp or "@" in stamp:
            raise ValueError("cover must be a span@stamp string")
        return cls(Span.parse(span), stamp)


@dataclass
class SourceRecord(Record):
    """One whole source line (``at``) and the region it replaced.

    ``at`` always is span of complete line(s).
    ``source`` is the superseded content of the record.
    ``cover`` is ``"span@stamp"`` for the region in the *immediately previous*
    version that this line corresponds to, or ``None`` for the first version.
    The stamp is that previous version's ``expire``.

    Cutting a migration at new-text newlines keeps every record line-sized,
    so one old span expresses the line-to-line mapping exactly.
    """

    TYPE: ClassVar[str] = TYPE_SOURCE

    source: str | None = None
    cover: Cover | None = None
    expire: str | None = None

    def validate(self):
        Span.parse(self.at)
        if self.cover is not None:
            if not isinstance(self.cover, Cover):
                raise ValueError("cover must be a Cover")
            self.cover.validate()
        if self.expire is not None:
            parse_time(self.expire)
            if not isinstance(self.source, str):
                raise ValueError("an expired source must carry its source")

    def to_dict(self):
        data = super().to_dict()
        if self.cover is not None:
            data["cover"] = str(self.cover)
        return data

    @classmethod
    def _from_dict(cls, data: dict):
        if "cover" in data:
            data["cover"] = Cover.parse(data["cover"])
        return cls(**data)


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
    coveredAt: list[Cover] | None = None
    """Derived on load from ``time`` and the sources, then serialized:
    ``"span@stamp"`` for each range of ``at`` superseded by a later version.
    It is refreshed whenever written into the ``.snd``,
    html only reads it (at most to verify)."""

    def validate(self):
        parse_time(self.time)
        Span.parse(self.at)
        if self.coveredAt is not None:
            if not isinstance(self.coveredAt, list):
                raise ValueError("coveredAt must be a list of Cover values")
            for cover in self.coveredAt:
                if not isinstance(cover, Cover):
                    raise ValueError("coveredAt must be a list of Cover values")
                cover.validate()

    def to_dict(self):
        data = super().to_dict()
        if self.coveredAt is not None:
            data["coveredAt"] = [str(entry) for entry in self.coveredAt]
        return data

    @classmethod
    def _from_dict(cls, data: dict):
        if "coveredAt" in data:
            data["coveredAt"] = [Cover.parse(cover) for cover in data["coveredAt"]]
        return cls(**data)


class ReviewIndex:
    """The parsed records of a review block, indexed for lookup.

    The original order is kept in :attr:`records` (the serialization source);
    :attr:`sources` and :attr:`reviews` partition it, and
    :attr:`sources_by_line` groups sources by the line they cover so a review's
    ``coveredAt`` can be derived.  The index is rebuilt on every load, never
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
            review.coveredAt = self.covered_at(review) or None

    def covered_at(self, review: ReviewRecord):
        """Derive a review's ``coveredAt`` entries from its creation version.

        Each contiguous run of lines that shares the same source version becomes
        one ``span@stamp`` value; a run still on the live version is omitted.
        """
        span = Span.parse(review.at)
        moment = parse_time(review.time)
        covered_at: list[Cover] = []
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
                    covered_at.append(Cover(Span(start, 0, line, 0), current))
                start, current = line, expire
        if start is not None and current is not None:
            covered_at.append(Cover(Span(start, 0, line + 1, 0), current))
        return covered_at

    def _live_at(self, line: int, moment: datetime):
        """The source whose version was live at *moment* on *line*.

        Find a line in the history: the first one not yet expired at *moment*.
        Returns ``None`` when no source covers the line.
        """
        for source in self.sources_by_line.get(line, ()):
            if source.expire is None or parse_time(source.expire) > moment:
                return source
