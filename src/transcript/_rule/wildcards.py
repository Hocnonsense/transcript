"""Wildcard matching, name extraction and value placeholdization."""

from __future__ import annotations

import re

from snakemake.exceptions import WorkflowError
from snakemake.io import contains_wildcard, regex_from_filepattern


class WildcardState:
    """One rule's wildcard bookkeeping.

    Three layers are kept apart: ``defaults`` declared with
    ``r.wildcards(...)``, ``inferred`` captures learned from input patterns,
    and ``job`` (the runtime ``--wildcards`` of the execution that created the
    rule).  ``declared`` is the script-side view used for inference and
    consistency checks; ``effective`` adds the job values only for resolution
    and lambda evaluation.
    """

    def __init__(self, job: dict[str, str] | None = None):
        self.defaults: dict[str, str] | None = None
        self.inferred: dict[str, str] = {}
        self.job: dict[str, str] = dict(job or {})

    def declared(self) -> dict[str, str]:
        """Script-side wildcard values: inferred captures plus declared defaults."""
        return self.inferred | (self.defaults or {})

    def effective(self, override: dict[str, str] | None = None) -> dict[str, str]:
        """Runtime values: declared, then the job's, then *override*."""
        if override is None:
            override = self.job
        return self.declared() | override

    def conflict(self, captured: dict[str, str]):
        """Return the first capture that contradicts a declared value, if any."""
        declared = self.declared()
        for name, value in captured.items():
            if name in declared and declared[name] != value:
                return name, value
        return None


def _matches(pattern, value):
    """Whether *value* matches the wildcard *pattern* (snakemake semantics)."""
    if pattern == value:
        return True
    if not isinstance(pattern, str) or not isinstance(value, str):
        return False
    if not contains_wildcard(pattern):
        return False
    return re.match(regex_from_filepattern(pattern), value) is not None


def _iter_str(value):
    """Return the string leaves of a declaration value (paths or params)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield item


def _match_wildcards(pattern: str, value: str) -> dict[str, str] | None:
    """Return the wildcards captured when *value* matches *pattern*."""
    match = re.match(regex_from_filepattern(pattern), value)
    captured = match.groupdict() if match else {}
    return captured or None


def _placeholderize(value: str, wildcards: dict[str, str]):
    """Replace known wildcard values in *value* with their placeholders.

    A single left-to-right scan keeps the replacement well-defined when values
    overlap or form a cycle.  At each position the longest value wins, so with
    ``a="sth", b="sth2"`` the value ``"sth2.tsv"`` becomes ``"{b}.tsv"`` rather
    than ``"{a}2.tsv"``; because inserted placeholders are never rescanned,
    ``ext="csv", csv="ext"`` maps ``"csv.ext"`` to ``"{ext}.{csv}"`` instead of
    corrupting the placeholder.  If two wildcards share a value that actually
    occurs in *value*, the substitution is ambiguous and is rejected.
    """
    by_value: dict[str, list[str]] = {}
    for name, text in wildcards.items():
        if text:
            by_value.setdefault(text, []).append(name)
    if not by_value:
        return value
    alternation = re.compile(
        "|".join(re.escape(text) for text in sorted(by_value, key=len, reverse=True))
    )
    result: list[str] = []
    i = 0
    while i < len(value):
        match = alternation.match(value, i)
        if match is None:
            result.append(value[i])
            i += 1
            continue
        names = by_value[match.group(0)]
        if len(names) > 1:
            raise WorkflowError(
                "wildcards " + ", ".join(sorted(names)) + " share the value "
                f"{match.group(0)!r}; cannot infer a unique pattern"
            )
        result.append("{" + names[0] + "}")
        i = match.end()
    return "".join(result)
