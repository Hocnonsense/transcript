"""The rule's conda environment declaration."""

from __future__ import annotations

from snakemake.exceptions import WorkflowError

from .serialize import _literal


def _string_list(value):
    """Accept a string or a list of strings; return a canonical list."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise WorkflowError("value must be a string or a list of strings")
    return list(value)


class Conda:
    def __init__(self, dependencies=(), *, pip=(), channels=("conda-forge",)):
        if pip and not dependencies:
            dependencies = "pip"
        if not dependencies:
            raise WorkflowError("at least one dependency must be declared")
        self.dependencies = _string_list(dependencies)
        self.pip = _string_list(pip)
        self.channels = _string_list(channels)

    def _item(self):
        for key in ("dependencies", "pip", "channels"):
            value = getattr(self, key)
            if value:
                yield 1, f"{key}=["
                for item in value:
                    yield 2, f"{_literal(item)},"
                yield 1, "],"

    def to_yaml(self):
        """Serialize a conda-style environment mapping without a YAML dependency."""
        lines = ["channels:"]
        for channel in self.channels:
            lines.append(f"  - {channel}")
        lines.append("dependencies:")
        for dependency in self.dependencies:
            lines.append(f"  - {dependency}")
        pip = self.pip
        if pip:
            lines.append("  - pip:")
            lines.extend(f"      - {item}" for item in pip)
        return "\n".join(lines) + "\n"
