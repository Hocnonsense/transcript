"""The ``snakedone.review`` record model: schema, lookup, and serialization.

An archive may end with a plain-Python review block: an ``if
"snakedone.review":`` whose body is a single triple-quoted JSON array.  The
block is an ordinary ``if`` whose body is one JSON string, so it stays valid
Python with no dependencies and is ignored when the document runs.

Records are flat.  A ``source`` versions a run of lines (``at``) whose actual
change is ``diffRange``; a ``review`` carries an absolute range plus the time
its comment was last edited.  The version a review reads is derived from its
``time`` (see :func:`expire_at`): the source whose ``expire`` is the earliest
one strictly after that time, treating a live source as expiring at infinity.
There is no explicit parent link and no version chain to maintain.
"""

from __future__ import annotations

from datetime import datetime

from ._span import TYPE_REVIEW, TYPE_SOURCE, Span, parse_time

__all__ = ["expire_at", "validate"]


def validate(records: list[dict]):
    """Check the record invariants and raise :class:`ValueError` on violation."""
    ids: set[str] = set()
    for record in records:
        kind = record.get("type")
        if kind == TYPE_SOURCE:
            Span.parse(record["at"])
            if "diffRange" in record:
                Span.parse(record["diffRange"])
            expire = record.get("expire")
            if expire is None:
                if "text" in record:
                    raise ValueError("a live source must not carry text")
            else:
                parse_time(expire)
                if not isinstance(record.get("text"), str):
                    raise ValueError("an expired source must carry its text")
        elif kind == TYPE_REVIEW:
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("a review needs a non-empty id")
            if identifier in ids:
                raise ValueError(f"duplicate review id: {identifier}")
            ids.add(identifier)
            parse_time(record["time"])
            Span.parse(record["at"])
            expire_at = record.get("expireAt")
            if expire_at is not None:
                if not isinstance(expire_at, dict):
                    raise ValueError("expireAt must map ranges to timestamps")
                for key, value in expire_at.items():
                    Span.parse(key)
                    parse_time(value)
        else:
            raise ValueError(f"unknown review record type: {kind!r}")


def _live_at(records: list[dict], line: int, moment: datetime):
    """The source whose version was live at *moment* on *line*.

    Among the sources covering the line that had not expired yet, the one that
    expired first is the version then current; a live source counts as expiring
    at infinity.  Returns ``None`` when no source covers the line.
    """
    best_key: tuple[bool, datetime | None] | None = None
    best: dict | None = None
    for record in records:
        if record.get("type") != TYPE_SOURCE:
            continue
        span = Span.parse(record["at"])
        if line < span.start_line or line > span.end_line:
            continue
        expire = record.get("expire")
        if expire is not None and parse_time(expire) <= moment:
            continue
        key = (expire is None, parse_time(expire) if expire else None)
        if best_key is None or key < best_key:
            best_key, best = key, record
    return best


def expire_at(records: list[dict], review: dict):
    """Derive a review's ``expireAt`` map from its ``time`` and the sources.

    Each contiguous run of lines that shares the same source version maps to
    that source's ``expire``; a run still on the live version is omitted.
    """
    span = Span.parse(review["at"])
    moment = parse_time(review["time"])
    result: dict[str, str] = {}
    start: int | None = None
    current: str | None = None
    for line in span.lines():
        source = _live_at(records, line, moment)
        expire = None if source is None else source.get("expire")
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
