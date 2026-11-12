"""The canonical ``# transcript:rule`` block: build it and read it back."""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from snakemake.exceptions import WorkflowError

from ..parse import line_offsets, with_marker_text
from .lambdas import _StaticLambda
from .serialize import _entry

if TYPE_CHECKING:
    from .core import Rule

_RULE_MARKER_RE = re.compile(
    r"# transcript:rule(?: (?P<name>[A-Za-z_][A-Za-z0-9_]*):)?"
)


def declarations(rule: Rule, target: str):
    """Return the canonical declarations, each possibly spanning several lines."""
    for container in (rule._input, rule._output, rule._log, rule._params):
        args = [_entry(name, value) for name, value in container._raw_items()]
        if args:
            yield 1, f"{target}.{container._kind}("
            for arg in args:
                yield 2, arg
            yield 1, ")"
    if rule._threads is not None:
        yield 1, f"{target}.threads = {rule._threads}"
    if rule._resources:
        yield 1, f"{target}.resources("
        for key, value in rule._resources.items():
            yield 2, _entry(key, value)
        yield 1, ")"
    if rule._conda is not None:
        yield 1, f"{target}.conda("
        for i, line in rule._conda._item():
            yield i + 1, line
        yield 1, ")"
    if rule._wildcard_state.defaults is not None:
        yield 1, f"{target}.wildcards("
        for key, value in rule._declared_wildcards().items():
            yield 2, _entry(key, value)
        yield 1, ")"


def make_rule_block(rule: Rule, TAB="    "):
    if not rule.edit:
        return
    (start, end), context_source = rule.edit
    if not rule.target:
        raise NameError("transcript.rule() must be assigned to a name")
    prefix = "\n\n" if context_source is None else ""
    if context_source and context_source != rule.target:
        assign = f"{context_source} as "
    else:
        assign = ""
    marker = "# transcript:rule"
    marker_name = "" if rule.name is None else f" {rule.name}:"
    header = f"{prefix}with {assign}{rule.target}:  {marker}{marker_name}"
    body = [f"\n{i * TAB}{line}" for i, line in declarations(rule, rule.target)]
    yield start, end, header + "".join(body or [f"\n{TAB}pass"])


def from_tmd(cls: type[Rule], source: str, filename=None):
    """Rebuild a rule from its canonical ``# transcript:rule`` block."""
    tree = ast.parse(source)
    position = line_offsets(source)
    for node in tree.body:
        if isinstance(node, ast.With) and len(node.items) == 1:
            marker = with_marker_text(source, node, position)[3]
            match = _RULE_MARKER_RE.fullmatch(marker)
            if match:
                self = from_node(cls, node, match["name"])
                if filename is not None:
                    self._filename = str(filename)
                return self
    raise WorkflowError(
        "No # transcript:rule block found. "
        "Please define input/output with transcript.rule() in the document."
    )


def from_node(cls: type[Rule], node: ast.With, name: str | None):
    rule = cls(name)
    with rule:
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                target = statement.targets[0] if len(statement.targets) == 1 else None
                kind = _direct_attribute(target) if target is not None else None
                if kind != "threads":
                    raise WorkflowError(f"unsupported rule declaration: {kind!r}")
                rule.threads = ast.literal_eval(statement.value)
                continue
            if isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Call
            ):
                call = statement.value
                kind = _direct_attribute(call.func)
                declaration = getattr(rule, kind, None) if kind else None
                if not callable(declaration):
                    raise WorkflowError(f"unsupported rule declaration: {kind!r}")

                def read(value):
                    if kind in cls._LAMBDA_AUX and isinstance(value, ast.Lambda):
                        return _StaticLambda.from_node(cls._LAMBDA_AUX[kind], value)
                    return ast.literal_eval(value)

                declaration(
                    *(read(arg) for arg in call.args),
                    **{
                        keyword.arg: read(keyword.value)
                        for keyword in call.keywords
                        if keyword.arg
                    },
                )
    return rule


def _direct_attribute(node):
    """Return ``node``'s attribute name if it is ``<name>.<attr>``."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.attr
    return None
