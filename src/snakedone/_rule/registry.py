"""Transient per-execution rule state, free of the optional snakemake dependency.

The values live in ``ContextVar``\\ s so that concurrent executions in one
process (threads or asyncio tasks) cannot clobber each other.  A plain global
would be shared by every execution.

This module is imported by :mod:`snakedone.execute` on every run, so
``_rule/__init__.py`` must not import :mod:`snakedone._rule.core`: importing
this module has to stay independent of the optional ``snakemake`` extra.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Rule

_current: ContextVar[Rule | None] = ContextVar("snakedone_rule", default=None)
_wildcards: ContextVar[dict[str, str] | None] = ContextVar(
    "snakedone_wildcards", default=None
)


def current():
    return _current.get()


def set_current(value: Rule | None = None):
    """Set the rule declared by the current document."""
    _current.set(value)


def wildcards():
    """CLI wildcard overrides for the current execution, or ``{}`` outside one."""
    return _wildcards.get() or {}


def executing():
    """Whether the document executor is driving the current execution."""
    return _wildcards.get() is not None


class Execution:
    def __init__(self, wildcards: dict[str, str] | None):
        self.wildcards = dict(wildcards or {})

    def __enter__(self):
        self.token = (_wildcards.set(self.wildcards), _current.set(None))

    def __exit__(self, exc_type, exc, tb):
        _wildcards.reset(self.token[0])
        _current.reset(self.token[1])
