"""Canonical literal serialization for rule declarations and fragments."""

from __future__ import annotations

import json

from snakemake.exceptions import WorkflowError

from .lambdas import _StaticLambda


def _literal(value):
    """Serialize a static value, using canonical double quotes for strings."""
    if isinstance(value, _StaticLambda):
        if value.source is None:
            raise WorkflowError(
                "a lambda declared outside a document cannot be "
                "serialized; run the document with snakedone"
            )
        return value.source
    return json.dumps(value) if isinstance(value, str) else repr(value)


def _entry(name: str | None, value):
    value = _literal(value)
    return f"{name}={value}," if name else f"{value},"
