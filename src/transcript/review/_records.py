"""The ``transcript.review`` record model: schema, lookup, and serialization.

An archive may end with a plain-Python review block: an ``if
"transcript.review":`` whose body is a single triple-quoted JSON array.  The
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

from ._span import TYPE_REVIEW, TYPE_SOURCE, At, Span, parse_time

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
        return target._from_dict(kwargs)


@dataclass
class SourceRecord(Record):
    """One whole source line (``at``) and the region it replaced.

    ``at`` always is span of complete line(s).
    ``source`` is the superseded content of the record.
    ``cover`` is ``"span@stamp"`` for the region in the *immediately previous*
    version that this line corresponds to, or ``None`` for the first version.
    The stamp is that previous version's ``before`` boundary.

    Cutting a migration at new-text newlines keeps every record line-sized,
    so one old span expresses the line-to-line mapping exactly.
    """

    TYPE: ClassVar[str] = TYPE_SOURCE

    source: str | None = None
    cover: At | None = None
    before: str | None = None

    def validate(self):
        Span.parse(self.at)
        if self.cover is not None:
            if not isinstance(self.cover, At):
                raise ValueError("cover must be an At")
            self.cover.validate()
        if self.before is not None:
            parse_time(self.before)
            if not isinstance(self.source, str):
                raise ValueError("a superseded source must carry its source")

    def to_dict(self):
        data = super().to_dict()
        if self.cover is not None:
            data["cover"] = str(self.cover)
        return data

    @classmethod
    def _from_dict(cls, data: dict):
        if "cover" in data:
            data["cover"] = At.parse(data["cover"])
        return cls(**data)


def _before(source: SourceRecord):
    """Sort key placing a live source (no ``before``) after superseded ones.
    old first, live the last.
    """
    return (source.before is None, source.before or "")


@dataclass
class ReviewRecord(Record):
    """A range plus the time its comment was last edited."""

    TYPE: ClassVar[str] = TYPE_REVIEW

    time: str
    edit: str | None = None
    comment: str | None = None
    coveredAt: list[At] | None = None
    """Derived on load from ``time`` and the sources, then serialized:
    ``"span@stamp"`` for each range of ``at`` superseded by a later version.
    It is refreshed whenever written into the ``.tmd.py``,
    html only reads it (at most to verify)."""

    def validate(self):
        parse_time(self.time)
        Span.parse(self.at)
        if self.coveredAt is not None:
            if not isinstance(self.coveredAt, list):
                raise ValueError("coveredAt must be a list of At values")
            for cover in self.coveredAt:
                if not isinstance(cover, At):
                    raise ValueError("coveredAt must be a list of At values")
                cover.validate()

    def to_dict(self):
        data = super().to_dict()
        if self.coveredAt is not None:
            data["coveredAt"] = [str(entry) for entry in self.coveredAt]
        return data

    @classmethod
    def _from_dict(cls, data: dict):
        if "coveredAt" in data:
            data["coveredAt"] = [At.parse(cover) for cover in data["coveredAt"]]
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
            bucket.sort(key=_before)
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
        covered_at: list[At] = []
        start: int | None = None
        current: str | None = None
        for line in span.lines():
            source = self._live_at(line, moment)
            before = None if source is None else source.before
            if start is None:  # the first line of review
                start, current = line, before
            elif before == current:
                continue
            else:  # zone of current ends, record the span
                if current is not None:
                    covered_at.append(At(Span(start, 0, line, 0), current))
                start, current = line, before
        if start is not None and current is not None:
            covered_at.append(At(Span(start, 0, line + 1, 0), current))
        return covered_at

    def _live_at(self, line: int, moment: datetime):
        """The source whose version was live at *moment* on *line*.

        Find a line in the history: the first one whose boundary follows *moment*,
        skipping a source that had not appeared yet.  A source's birth is the
        stamp of the zero-length ``cover`` an insertion carries; ``None`` means it
        has always existed.  Returns ``None`` when no source covers the line.
        """
        for source in self.sources_by_line.get(line, ()):
            if source.cover is not None and parse_time(source.cover.time) > moment:
                continue
            if source.before is None or parse_time(source.before) > moment:
                return source
