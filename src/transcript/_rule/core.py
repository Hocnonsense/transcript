"""Declare the Snakemake rule interface of a document.

A document declares one rule with ``with transcript.rule() as r:`` and then
assigns or calls ``r.input`` / ``r.output`` / ``r.log`` / ``r.params``.  The
containers are a small declaration collector, not Snakemake's ``Namedlist``:
their semantics differ (declaration, validation, and wildcard resolution on
read).  Declarations are collected while the document runs;
:mod:`transcript._rule.archive` writes them back into a canonical ``# transcript:rule``
block.
"""

from __future__ import annotations

import ast
import math
import sys
from collections.abc import Callable
from pathlib import Path

from snakemake.exceptions import WorkflowError
from snakemake.io import apply_wildcards, get_wildcard_names
from snakemake.resources import Resources

try:  # Snakemake >= 9.16
    from snakemake.iocontainers import Namedlist, Wildcards
except ImportError:  # Snakemake 9.x before the module split
    from snakemake.io import Namedlist, Wildcards  # type: ignore

from . import archive, registry, snakefile
from .conda import Conda
from .container import _MISSING, DeclaredList, _WildcardsView
from .lambdas import _StaticLambda
from .wildcards import WildcardState, _iter_str, _match_wildcards, _placeholderize


def _is_document_target(path: str):
    """Whether *path* names an archive (``.tmd.py``) or an HTML report."""
    return path.endswith(".tmd.py") or Path(path).suffix == ".html"


class Rule:
    """One document's Snakemake interface."""

    def __init__(self, name: str | None = None):
        if name is not None and not (isinstance(name, str) and name.isidentifier()):
            raise WorkflowError(f"invalid rule name: {name!r}")
        self._name = name
        self._input = DeclaredList(self, "input")
        self._output = DeclaredList(self, "output")
        self._log = DeclaredList(self, "log")
        self._params = DeclaredList(self, "params", is_path=False)
        self._threads: int | None = None
        self._resources: dict[str, int | float | str] = {}
        self._conda: Conda | None = None
        self._wildcard_state = WildcardState(registry.wildcards())
        self._wildcards_view = _WildcardsView(self)
        self._filename: str | None = getattr(
            sys.modules.get("__main__"), "__file__", None
        )
        self._lambdas: dict[tuple[int, int], ast.Lambda] | None = None
        self.edit: tuple[tuple[int, int], str | None] | None = None
        self.target: str | None = None
        self.with_declare: bool | None = None
        """``None`` before entering, ``True`` while inside, ``False`` after."""

    def __enter__(self):
        if self.with_declare is not None:
            raise WorkflowError("a rule context can only be entered once")
        self.with_declare = True
        return self

    def __exit__(self, *exc):
        self.with_declare = False
        self._lambdas = None
        if exc[0] is None:
            self._check_wildcards()
        return False

    def set_lambdas(self, node: ast.With):
        """Index the block's lambda nodes by body position for source recovery."""
        self._lambdas = {
            (child.body.lineno, child.body.col_offset): child
            for statement in node.body
            for child in ast.walk(statement)
            if isinstance(child, ast.Lambda)
        }

    def _declare_lambda(self, kind: str, value: Callable):
        """Wrap a declared callable, keeping the block-only rule for documents."""
        if not registry.executing():
            return _StaticLambda.from_runtime(self._LAMBDA_AUX[kind], value)
        node = self._lambda_node(value)
        if node is None:
            raise WorkflowError(f"{kind} lambda must be declared inside the rule block")
        return _StaticLambda.from_node(self._LAMBDA_AUX[kind], node, value)

    def _lambda_node(self, value: Callable):
        """Return the source AST node of a lambda declared in the block."""
        nodes = self._lambdas
        if nodes is None or not hasattr(value, "__code__"):
            return None
        code = value.__code__
        if code.co_filename != self._filename or code.co_name != "<lambda>":
            return None
        positions = {
            (line, column)
            for line, _, column, _ in code.co_positions()
            if line is not None and column is not None
        }
        matches = [node for position, node in nodes.items() if position in positions]
        return matches[0] if len(matches) == 1 else None

    @property
    def name(self):
        return self._name

    @property
    def input(self):
        return self._input

    @property
    def output(self):
        return self._output

    @property
    def log(self):
        return self._log

    @property
    def params(self):
        return self._params

    @property
    def threads(self):
        """The rule's default thread request (1 when undeclared)."""
        return self._threads or 1

    @threads.setter
    def threads(self, value: int):
        """Declare the rule's default thread request (idempotent)."""
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise WorkflowError("threads must be a positive integer")
        if self._threads is None:
            self._threads = value
        elif self._threads != value:
            raise WorkflowError(f"threads is already declared as {self._threads}")

    def resources(self, **values: int | float | str):
        """Merge static default resource requests into this rule.

        This is different from params/input/output/log,
        because it should not set as casual as those in the script.
        """
        for name, value in values.items():
            if not name.isidentifier():
                raise WorkflowError(f"invalid resource name: {name!r}")
            if name in {"_cores", "_nodes"}:
                raise WorkflowError(f"resource {name!r} is managed by Snakemake")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float, str))
                or isinstance(value, (int, float))
                and (value < 0 or not math.isfinite(value))
            ):
                raise WorkflowError(
                    f"resource {name!r} must be a non-negative number or string"
                )
            if name in self._resources and self._resources[name] != value:
                raise WorkflowError(
                    f"resource {name!r} is already declared as "
                    f"{self._resources[name]!r}"
                )
        merged = self._resources | values
        try:
            Resources.from_mapping(merged)
        except (TypeError, ValueError, WorkflowError) as exc:
            raise WorkflowError(str(exc)) from exc
        self._resources.update(values)
        return dict(self._resources)

    def conda(self, dependencies=(), *, pip=(), channels=("conda-forge",)):
        """Declare the conda environment once: channels, dependencies and pip."""
        if self._conda is not None:
            raise WorkflowError("conda is already declared")
        self._conda = Conda(dependencies, pip=pip, channels=channels)
        return self._conda

    @property
    def wildcards(self):
        """Call to declare defaults; read attributes for effective values."""
        return self._wildcards_view

    def _declare_wildcards(self, **defaults: str):
        """Record the interactive defaults; declare only one distinct set.

        Declaring defaults is the one sanctioned point where already-collected
        out-of-block literals may be upgraded to patterns: a new default value
        turns a matching literal into its pattern.  A default that contradicts an
        inferred value is an error.
        """
        for value in defaults.values():
            if not isinstance(value, str):
                raise WorkflowError("wildcard defaults must be strings")
        candidate = dict(defaults)
        if self._wildcard_state.defaults is None:
            pass
        elif self._wildcard_state.defaults == candidate:
            return self._wildcard_state.defaults
        else:
            raise WorkflowError("wildcards can only be declared once")
        containers = (self._input, self._output, self._log, self._params)
        snapshot = (
            dict(self._wildcard_state.inferred),
            self._wildcard_state.defaults,
            [list(c._later) for c in containers],
        )
        try:
            declared = self._declared_wildcards()
            for name, value in candidate.items():
                if name in declared and declared[name] != value:
                    raise WorkflowError(
                        f"wildcard {name!r} is {declared[name]!r}, not {value!r}"
                    )
            self._wildcard_state.defaults = candidate
            self._apply_declared_defaults()
        except BaseException:
            (
                self._wildcard_state.inferred,
                self._wildcard_state.defaults,
            ) = snapshot[0], snapshot[1]
            for container, saved in zip(containers, snapshot[2]):
                container._later = saved
            raise
        return self._wildcard_state.defaults

    def resolve(self, pattern: str, override: dict[str, str] | None = None):
        """Substitute the effective wildcards into a declared path pattern."""
        return apply_wildcards(pattern, self._effective_wildcards(override))

    def _resolved_paths(self, container: DeclaredList):
        resolved = Namedlist()
        for name, value in container._raw_items():
            start = len(resolved)
            item = container._resolve(value)
            if isinstance(item, list):
                resolved.extend(str(path) for path in item)
            else:
                resolved.append(str(item))
            if name:
                resolved._set_name(
                    name, start, end=len(resolved) if isinstance(item, list) else None
                )
        return resolved

    def _evaluate_function(self, value: _StaticLambda, context: dict[str, Callable]):
        """Apply Snakemake's recursive callable convention in local execution."""
        wildcards = Wildcards(fromdict=self._effective_wildcards())
        return value.evaluate(wildcards, context)

    def _run_input_lambda(self, value: _StaticLambda):
        result = self._evaluate_function(value, {})
        scalar = isinstance(result, (str, Path))
        if scalar:
            items = [result]
        else:
            try:
                items = list(result)
            except TypeError as exc:
                raise WorkflowError(
                    "input lambda must return a path or an iterable of paths"
                ) from exc
        if not all(isinstance(item, (str, Path)) for item in items):
            raise WorkflowError(
                "input lambda must return a path or an iterable of paths"
            )
        paths = [Path(self.resolve(str(item))) for item in items]
        return paths[0] if scalar else paths

    def _run_param_lambda(self, value: _StaticLambda):
        """Evaluate a params lambda with the context Snakemake makes available."""
        return self._evaluate_function(
            value,
            {
                "input": lambda: self._resolved_paths(self._input),
                "output": lambda: self._resolved_paths(self._output),
                "log": lambda: self._resolved_paths(self._log),
                "threads": lambda: self._threads,
                "resources": lambda: self._resources,
            },
        )

    def _declared_wildcards(self):
        """Script-side wildcard values: inferred captures plus declared defaults."""
        return self._wildcard_state.declared()

    def _effective_wildcards(self, override: dict[str, str] | None = None):
        """Runtime wildcard values: declared, then the job's, then *override*.

        The rule captures the job wildcards of the execution that created it
        (the ``--wildcards`` values passed to ``execute``).  Callers outside that
        execution, such as the CLI after ``execute`` returns, read them back from
        the rule instead of re-supplying ``--wildcards``.
        """
        return self._wildcard_state.effective(override)

    def _placeholderize(self, container: DeclaredList, value, *, record=True):
        """Infer a wildcard pattern for a concrete out-of-block *value*.

        Only the value's own list is searched, and only script-side wildcard
        values take part; CLI overrides never affect inference.
        """
        if not isinstance(value, str) or get_wildcard_names(value):
            return value
        for _, declared in container._raw_items():
            for pattern in _iter_str(declared):
                captured = _match_wildcards(pattern, value)
                if captured is not None:
                    if record:
                        self._wildcard_state.record(captured)
                    return pattern
        return _placeholderize(value, self._declared_wildcards())

    def _infer_value(self, container: DeclaredList, value, *, record=True):
        """Infer patterns for an out-of-block declaration value."""
        if not container._is_path and isinstance(value, list):
            return [
                (
                    self._placeholderize(container, item, record=record)
                    if isinstance(item, str)
                    else item
                )
                for item in value
            ]
        return self._placeholderize(container, value, record=record)

    def _check_resolve(self, value):
        """Reject an out-of-block value that the effective wildcards cannot resolve."""
        for pattern in _iter_str(value):
            apply_wildcards(pattern, self._effective_wildcards())

    def _check_stable_inference(self, container: DeclaredList | None = None):
        """Reject an out-of-block value that a later declaration would rewrite.

        Inference is fixed at declaration time.  A new same-list pattern (or a
        new default) that would change an already-accepted literal is ambiguous,
        so it is reported instead of silently rewriting history.
        """
        if container is None:
            containers = [self._input, self._output, self._log, self._params]
        else:
            containers = [container]
        for current in containers:
            for _, stored in current._later:
                if isinstance(stored, _StaticLambda):
                    continue
                fresh = self._infer_value(current, stored, record=False)
                if fresh != stored:
                    raise WorkflowError(
                        f"{current._kind} value {stored!r} was declared before the "
                        f"matching pattern {fresh!r}; declare the pattern first, or "
                        "put the literal inside the rule block to keep it fixed"
                    )

    def _apply_declared_defaults(self):
        """Upgrade out-of-block literals now that new default values are known."""
        containers = (self._input, self._output, self._log, self._params)
        for container in containers:
            container._later = [
                (name, self._infer_value(container, value))
                for name, value in container._later
            ]
        self._check_wildcards()
        for container in containers:
            for _, value in container._later:
                self._check_resolve(value)

    def _add_out_of_block(self, container: DeclaredList, name: str | None, value):
        """Infer, validate, and only then commit an out-of-block declaration."""
        if name == "document" and container._kind in ("output", "log"):
            raise WorkflowError("document can only be declared inside the rule block")
        snapshot = (dict(self._wildcard_state.inferred), list(container._later))
        try:
            value = self._infer_value(container, value)
            is_new = (
                container._new_kwarg(name, value)
                if name is not None
                else container._new_narg(value)
            )
            if is_new:
                container._later.append((name, value))
                self._check_stable_inference(container)
                self._check_resolve(value)
                self._check_wildcards()
            return value
        except BaseException:
            self._wildcard_state.inferred, container._later = snapshot
            raise

    def make_rule_block(self, TAB="    "):
        return archive.make_rule_block(self, TAB)

    @classmethod
    def from_tmd(cls, source: str, filename=None):
        """Rebuild a rule from its canonical ``# transcript:rule`` block."""
        return archive.from_tmd(cls, source, filename)

    _LAMBDA_AUX = {
        "input": frozenset(),
        "params": frozenset({"input", "output", "log", "threads", "resources"}),
    }

    def wildcard_names(self):
        """Return the wildcard names shared by the output and log patterns."""
        return self._output._all_wildcards() | self._log._all_wildcards()

    def _check_wildcards(self, containers=None):
        """Output/log patterns share one wildcard set; input may use a subset.

        *containers* limits the input/params subset check to those containers
        (incremental use); the default checks every container.
        """
        patterns = [
            (container._kind, name, get_wildcard_names(pattern))
            for container in (self._output, self._log)
            for name, pattern in container._raw_items()
        ]
        if not patterns:
            return
        defined = patterns[0][2]
        for kind, name, names in patterns:
            if names != defined:
                raise WorkflowError(
                    f"{kind} {name or 'entry'} uses wildcards {sorted(names)}, "
                    f"but output/log share {sorted(defined)}"
                )
        scope = (self._input, self._params) if containers is None else containers
        unknown = set()
        for container in scope:
            if container._kind in ("input", "params"):
                unknown |= container._all_wildcards()
        unknown -= defined
        if unknown:
            raise WorkflowError(
                "wildcards "
                + ", ".join(sorted(unknown))
                + " are used by input/params but not defined by output/log"
            )

    @property
    def smk_target_document(self):
        """Return ``(kind, pattern)`` for the declared document, or ``None``."""
        output_target = self._output._raw("document")
        log_target = self._log._raw("document")
        if output_target is _MISSING:
            if log_target is _MISSING:
                return
            ret = "log", str(log_target)
        elif log_target is _MISSING:
            ret = "output", str(output_target)
        else:
            raise WorkflowError("document can only be declared in either output or log")
        if not _is_document_target(ret[1]):
            raise WorkflowError(
                f"document target {ret[1]!r} must end in .tmd.py or .html"
            )
        return ret

    @smk_target_document.setter
    def smk_target_document(self, text: str):
        """Replace or drop the document declaration after execution.

        Used by the CLI to reconcile the recorded document with ``-o``.  This is
        the only path allowed to change the declaration outside the rule block.
        """
        pattern = _placeholderize(text, self._effective_wildcards())
        if pattern == text:
            pattern = None  # a concrete -o cannot be recorded as a pattern
        if pattern is not None and not _is_document_target(pattern):
            raise WorkflowError(
                f"document target {pattern!r} must end in .tmd.py or .html"
            )
        for container in (self._output, self._log):
            if "document" in container:
                container._remove_named("document")
                if pattern is not None:
                    container._later.append(("document", pattern))
                self._check_wildcards()
                return
        if pattern is not None:
            self._output._later.append(("document", pattern))
            self._check_wildcards()

    def make_snakemake_rule(self, conda_path: Path | None = None, TAB="    "):
        """Return the Snakefile rule text for this declaration."""
        return snakefile.make_snakemake_rule(self, conda_path, TAB)


def rule(name: str | None = None):
    """Create and register the document's single rule."""
    if registry.current() is not None:
        raise WorkflowError("transcript.rule() can only be called once per document")
    job = Rule(name)
    if registry.executing():
        registry.set_current(job)
    return job
