"""Declare the Snakemake rule interface of a document.

A document declares one rule with ``with snakedone.rule() as r:`` and then
assigns or calls ``r.input`` / ``r.output`` / ``r.log`` / ``r.params``.  The
containers are a small declaration collector, not Snakemake's ``Namedlist``:
their semantics differ (declaration, validation, and wildcard resolution on
read).  Declarations are collected while the document runs;
:mod:`snakedone.snd` writes them back into a canonical ``# snakedone:rule``
block.
"""

from __future__ import annotations

import ast
import dis
import json
import math
import re
import sys
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, overload

from snakemake.common import get_input_function_aux_params
from snakemake.exceptions import WorkflowError
from snakemake.io import (
    apply_wildcards,
    contains_wildcard,
    get_wildcard_names,
    regex_from_filepattern,
)
from snakemake.resources import Resources

# from snakemake.script import Snakemake

try:  # Snakemake >= 9.16
    from snakemake.iocontainers import Namedlist, Wildcards
except ImportError:  # Snakemake 9.x before the module split
    from snakemake.io import Namedlist, Wildcards  # type: ignore

from . import _registry
from .parse import line_offsets, with_marker_text

_RULE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_RULE_MARKER_RE = re.compile(r"# snakedone:rule(?: (?P<name>[A-Za-z_][A-Za-z0-9_]*):)?")
_MISSING = object()


@dataclass(frozen=True)
class _StaticLambda:
    source: str | None
    aux: frozenset[str]
    function: Callable | None = field(compare=False, repr=False)

    def evaluate(self, wildcards: Wildcards, context: dict[str, Callable]):
        """Apply Snakemake's recursive callable convention in local execution."""
        function = self.function
        if function is None:
            raise WorkflowError("a statically read lambda cannot be evaluated")
        unavailable = self.aux - context.keys()
        if unavailable:
            raise WorkflowError(
                "interactive lambda context does not provide: "
                + ", ".join(sorted(unavailable))
            )
        aux_params = {
            name: resolve()
            for name, resolve in get_input_function_aux_params(
                function, context
            ).items()
        }
        result: Any = function
        for _ in range(10):
            if not callable(result):
                return result
            result = result(wildcards, **aux_params)
            if isinstance(result, types.GeneratorType):
                result = list(result)
        raise WorkflowError("lambda returned a callable 10 times")

    @classmethod
    def from_runtime(cls, cand_argnames: frozenset[str], function: Callable):
        """Retain a callable declared without a document AST index (REPL/plain run)."""
        auxiliary = get_input_function_aux_params(
            function, dict.fromkeys(cand_argnames)
        ).keys()
        return cls(None, frozenset(auxiliary), function)

    @classmethod
    def from_node(
        cls,
        cand_argnames: frozenset[str],
        node: ast.Lambda,
        function: Callable | None = None,
    ):
        """Validate and retain a self-contained Snakemake rule function."""
        where = f"lambda on line {node.lineno}"
        if any(isinstance(child, ast.NamedExpr) for child in ast.walk(node.body)):
            raise WorkflowError(f"{where} cannot contain an assignment expression")
        if any(isinstance(child, ast.Lambda) for child in ast.walk(node.body)):
            raise WorkflowError(f"{where} cannot contain another lambda")

        args = node.args
        positional = [*args.posonlyargs, *args.args]
        if not positional:
            raise WorkflowError(
                f"{where} must take wildcards as its first positional parameter"
            )
        if len(args.posonlyargs) > 1:
            raise WorkflowError(
                f"{where} auxiliary parameters cannot be positional-only"
            )
        if args.vararg is not None or args.kwarg is not None:
            raise WorkflowError(f"{where} cannot use *args or **kwargs")

        auxiliary = {arg.arg for arg in positional[1:]} | {
            arg.arg for arg in args.kwonlyargs
        }
        unknown = auxiliary - cand_argnames
        if unknown:
            raise WorkflowError(
                f"{where} has unsupported parameters: " + ", ".join(sorted(unknown))
            )
        defaults = [*args.defaults, *(value for value in args.kw_defaults if value)]
        try:
            for default in defaults:
                ast.literal_eval(default)
        except (ValueError, SyntaxError, TypeError) as exc:
            raise WorkflowError(f"{where} defaults must be literals") from exc

        source = ast.unparse(node)
        code = compile(ast.parse(source, mode="eval"), "<rule lambda>", "eval")
        external = {
            instruction.argval
            for child in _code_objects(code)
            for instruction in dis.get_instructions(child)
            if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}
        }
        if external:
            raise WorkflowError(
                f"{where} cannot access external names: " + ", ".join(sorted(external))
            )
        return cls(source, frozenset(auxiliary), function)


def _code_objects(code: types.CodeType):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from _code_objects(value)


def _matches(pattern, value):
    """Whether *value* matches the wildcard *pattern* (snakemake semantics)."""
    if pattern == value:
        return True
    if not isinstance(pattern, str) or not isinstance(value, str):
        return False
    if not contains_wildcard(pattern):
        return False
    return re.match(regex_from_filepattern(pattern), value) is not None


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


class DeclaredList:
    """An ordered, named declaration of paths or params.

    Declarations made inside the rule block are collected in a Snakemake
    ``Namedlist``; declarations made after it are appended to ``_later`` and
    merged after the block entries when read or serialized.  Path values
    resolve through the owning rule when read.
    """

    def __init__(self, rule: Rule, kind: str, *, is_path=True):
        self._rule = rule
        self._kind = kind
        self._is_path = is_path
        self._named: Namedlist | None = None
        self._later: list[tuple[str | None, Any]] = []

    @overload
    def __call__(self, *args) -> Namedlist: ...

    @overload
    def __call__(self, **kwargs) -> Namedlist: ...

    @overload
    def __call__(self, *nargs, **kwargs) -> None: ...

    def __call__(self, *nargs, **kwargs):
        _coerce = self._coerce
        _nargs = (_coerce(value) for value in nargs)
        _kwargs = ((name, _coerce(value)) for name, value in kwargs.items())
        if self._rule.with_declare:
            if self._named is None:
                self._named = Namedlist()
            for value in _nargs:
                self._named.append(value)
            for name, value in _kwargs:
                self._named.append(value)
                self._named._add_name(name)
            later, self._later = self._later, []
            for name, value in later:
                self._add_kwargs(name, value) if name else self._add_nargs(value)
            return
        if nargs:
            if kwargs:
                raise WorkflowError(
                    "named and anonymous entries can only be mixed"
                    " in the rule declaration"
                )
            return Namedlist(self._resolve(self._add_nargs(value)) for value in _nargs)
        return Namedlist(
            fromdict={
                name: self._resolve(self._add_kwargs(name, value))
                for name, value in _kwargs
            }
        )

    def __setattr__(self, name: str, value):
        if name[:1] == "_":
            object.__setattr__(self, name, value)
        else:
            if self._rule.with_declare is True:
                raise WorkflowError(
                    "parameter setting can only be outside the rule declaration"
                )
            self._add_kwargs(name, self._coerce(value))

    def __getattribute__(self, name):
        if name[:1] != "_":
            value = self._raw(name)
            if value is not _MISSING:
                return self._resolve(value)
        return object.__getattribute__(self, name)

    def __setitem__(self, key: str, value):
        if self._rule.with_declare is True:
            raise WorkflowError(
                "parameter setting can only be outside the rule declaration"
            )
        if isinstance(key, str):
            self._add_kwargs(key, self._coerce(value))
        else:
            raise WorkflowError(
                f"{self._kind} only supports name assignment, got {key!r}"
            )

    def __getitem__(self, key: str | int):
        if isinstance(key, str):
            value = self._raw(key)
            if value is _MISSING:
                raise WorkflowError(f"{self._kind}.{key} is not declared")
            return self._resolve(value)
        if isinstance(key, int) and not isinstance(key, bool):
            items = list(self._raw_items())
            return self._resolve(items[key][1])
        raise WorkflowError(f"{self._kind} key must be a name or index, got {key!r}")

    def __iter__(self):
        for _, value in self._raw_items():
            yield self._resolve(value)

    def __len__(self):
        return sum(1 for _ in self._raw_items())

    def __contains__(self, name: str):
        return self._raw(name) is not _MISSING

    def _raw_items(self):
        """Yield ``(name, value)``: block entries first, then later additions."""
        named = self._named
        if named is not None:
            index_to_name = {index: name for name, (index, _) in named._names.items()}
            for index, value in enumerate(named):
                yield index_to_name.get(index), value
        yield from self._later

    def _raw(self, name: str):
        named = self._named
        if named is not None and name in named._names:
            return named[named._names[name][0]]
        for existing_name, value in self._later:
            if existing_name == name:
                return value
        return _MISSING

    def _remove_named(self, name: str):
        """Drop a block entry after execution (internal use)."""
        named = self._named
        if named is None or name not in named._names:
            self._later = [(n, v) for n, v in self._later if n != name]
            return
        index = named._names[name][0]
        names = {i: n for n, (i, _) in named._names.items() if n != name}
        rebuilt = Namedlist()
        for i, item in enumerate(named):
            if i == index:
                continue
            rebuilt.append(item)
            if i in names:
                rebuilt._add_name(names[i])
        self._named = rebuilt

    @property
    def _coerce(self):
        """Accept anything string-like from callers; store the canonical value."""
        if self._kind == "input":
            return self._validate_input
        return str if self._is_path else self._validate_param

    def _validate_input(self, value):
        """Input coercion: retain strings and wildcard-only lambdas."""
        value_ = self._validate_lambda(value)
        if value_ is None:
            return str(value)
        return value_

    def _validate_param(self, value):
        """Params coercion: retain literals and self-contained lambdas."""
        value_ = self._validate_lambda(value)
        if value_ is None:
            try:
                if ast.literal_eval(repr(value)) == value:
                    return value
            except ValueError, SyntaxError, TypeError:
                pass
            raise WorkflowError(
                f"{self._kind} value must be a literal or a self-contained lambda, "
                f"got {value!r}"
            )
        return value_

    def _validate_lambda(self, value):
        """retain self-contained lambdas or None"""
        if isinstance(value, _StaticLambda):
            return value
        if callable(value):
            return self._rule._declare_lambda(self._kind, value)
        return None

    def _add_kwargs(self, name: str, value):
        return self._rule._add_out_of_block(self, name, value)

    def _add_nargs(self, value):
        return self._rule._add_out_of_block(self, None, value)

    @classmethod
    def _reserved(cls, name: str):
        """Whether *name* collides with a container or ``Namedlist`` attribute."""
        return hasattr(cls, name) or hasattr(Namedlist, name)

    def _new_kwarg(self, name: str, value):
        """Validate a named declaration; return whether it is new."""
        if self._reserved(name):
            raise WorkflowError(f"{self._kind}.{name} is reserved for internal use")
        existing = self._raw(name)
        if existing is _MISSING:
            return True
        if _matches(existing, value):
            return False
        raise WorkflowError(
            f"{self._kind}.{name} is already declared as {existing!r}, not {value!r}"
        )

    def _new_narg(self, value):
        """Validate an anonymous declaration; return whether it is new."""
        items = list(self._raw_items())
        for _, existing in items:
            if _matches(existing, value):
                return False
        if any(name is not None for name, _ in items):
            raise WorkflowError(
                f"{self._kind}: an anonymous entry cannot follow a named entry"
            )
        return True

    def _resolve(self, value):
        if isinstance(value, _StaticLambda):
            if self._kind == "input":
                return self._rule._run_input_lambda(value)
            return self._rule._run_param_lambda(value)
        if self._is_path:
            return Path(self._rule.resolve(value))
        if isinstance(value, str):
            return self._rule.resolve(value)
        if isinstance(value, list):
            return [
                self._rule.resolve(item) if isinstance(item, str) else item
                for item in value
            ]
        return value

    def _all_wildcards(self):
        """Return every wildcard name used by *container*'s path patterns."""
        names: set[str] = set()
        for _, value in self._raw_items():
            for pattern in _iter_str(value):
                names |= get_wildcard_names(pattern)
        return names

    def _entries(self):
        for name, value in self._raw_items():
            yield _entry(name, value)


class _WildcardsView:
    """The rule's wildcards: call to declare defaults, read to get values.

    ``r.wildcards(sample="s1")`` records the defaults exactly once, while
    ``r.wildcards.sample`` and ``r.wildcards["sample"]`` read the effective
    value: declared defaults, then inferred captures, then ``--wildcards``.
    """

    def __init__(self, rule: Rule):
        self._rule: Rule
        object.__setattr__(self, "_rule", rule)

    def __call__(self, **defaults: str):
        return self._rule._declare_wildcards(**defaults)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._rule.resolve("{" + name + "}")

    def __getitem__(self, name: str):
        if not isinstance(name, str):
            raise WorkflowError("wildcards key must be a name")
        return getattr(self, name)

    def __contains__(self, name: str):
        return name in self._rule._effective_wildcards()


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
        self._wildcards: dict[str, str] | None = None
        self._wildcards_view = _WildcardsView(self)
        self._inferred: dict[str, str] = {}
        """inferred wildcards from input patterns"""
        self._filename: str | None = getattr(
            sys.modules.get("__main__"), "__file__", None
        )
        self._lambdas: dict[tuple[int, int], ast.Lambda] | None = None
        self.edit: tuple[int, int, str | None] | None = None
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
        if not _registry.executing():
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
        if self._wildcards is None:
            pass
        elif self._wildcards == candidate:
            return self._wildcards
        else:
            raise WorkflowError("wildcards can only be declared once")
        containers = (self._input, self._output, self._log, self._params)
        snapshot = (
            dict(self._inferred),
            self._wildcards,
            [list(c._later) for c in containers],
        )
        try:
            declared = self._declared_wildcards()
            for name, value in candidate.items():
                if name in declared and declared[name] != value:
                    raise WorkflowError(
                        f"wildcard {name!r} is {declared[name]!r}, not {value!r}"
                    )
            self._wildcards = candidate
            self._apply_declared_defaults()
        except BaseException:
            self._inferred, self._wildcards = snapshot[0], snapshot[1]
            for container, saved in zip(containers, snapshot[2]):
                container._later = saved
            raise
        return self._wildcards

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
        return self._inferred | (self._wildcards or {})

    def _effective_wildcards(self, override: dict[str, str] | None = None):
        """Runtime wildcard values: declared, registry, then *override*.

        The registry holds the live ``ExecutionScope`` values.  *override* lets a
        caller outside the scope (the CLI after execution) supply the same
        ``--wildcards`` values it passed to ``execute``; it wins over the
        registry but never feeds back into inference or the declaration.
        """
        if override is None:
            override = _registry.wildcards()
        return self._declared_wildcards() | override

    def _record(self, captured: dict[str, str]):
        """Remember captures, rejecting values that contradict declared ones."""
        declared = self._declared_wildcards()
        for name, value in captured.items():
            if name in declared and declared[name] != value:
                raise WorkflowError(
                    f"wildcard {name!r} is {declared[name]!r}, not {value!r}"
                )
        self._inferred.update(captured)

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
                        self._record(captured)
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
        snapshot = (dict(self._inferred), list(container._later))
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
            self._inferred, container._later = snapshot
            raise

    def _declarations(self, target: str):
        """Return the canonical declarations, each possibly spanning several lines."""
        for container in (self._input, self._output, self._log, self._params):
            args = [_entry(name, value) for name, value in container._raw_items()]
            if args:
                yield 1, f"{target}.{container._kind}("
                for arg in args:
                    yield 2, arg
                yield 1, ")"
        if self._threads is not None:
            yield 1, f"{target}.threads = {self._threads}"
        if self._resources:
            yield 1, f"{target}.resources("
            for key, value in self._resources.items():
                yield 2, _entry(key, value)
            yield 1, ")"
        if self._conda is not None:
            yield 1, f"{target}.conda("
            for i, line in self._conda._item():
                yield i + 1, line
            yield 1, ")"
        if self._wildcards is not None:
            yield 1, f"{target}.wildcards("
            for key, value in self._declared_wildcards().items():
                yield 2, _entry(key, value)
            yield 1, ")"

    def make_rule_block(self, TAB="    "):
        if not self.edit:
            return
        start, end, context_source = self.edit
        if not self.target:
            raise NameError("snakedone.rule() must be assigned to a name")
        prefix = "\n\n" if context_source is None else ""
        if context_source and context_source != self.target:
            assign = f"{context_source} as "
        else:
            assign = ""
        marker = "# snakedone:rule"
        marker_name = "" if self.name is None else f" {self.name}:"
        header = f"{prefix}with {assign}{self.target}:  {marker}{marker_name}"
        body = [f"\n{i * TAB}{line}" for i, line in self._declarations(self.target)]
        yield start, end, header + "".join(body or [f"\n{TAB}pass"])

    @classmethod
    def from_snd(cls, source: str, declared_src=None):
        """Rebuild a rule from its canonical ``# snakedone:rule`` block."""
        tree = ast.parse(source)
        position = line_offsets(source)
        for node in tree.body:
            if isinstance(node, ast.With) and len(node.items) == 1:
                marker = with_marker_text(source, node, position)[3]
                match = _RULE_MARKER_RE.fullmatch(marker)
                if match:
                    self = cls._from_node(node, match["name"])
                    if declared_src is not None:
                        self._filename = str(declared_src)
                    return self
        raise WorkflowError(
            "No # snakedone:rule block found. "
            "Please define input/output with snakedone.rule() in the document."
        )

    _LAMBDA_AUX = {
        "input": frozenset(),
        "params": frozenset({"input", "output", "log", "threads", "resources"}),
    }

    @classmethod
    def _from_node(cls, node: ast.With, name: str | None):
        rule = cls(name)
        with rule:
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    target = (
                        statement.targets[0] if len(statement.targets) == 1 else None
                    )
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
        if Path(ret[1]).suffix not in (".snd", ".html"):
            raise WorkflowError(f"document target {ret[1]!r} must end in .snd or .html")
        return ret

    @smk_target_document.setter
    def smk_target_document(self, value: tuple[str, dict[str, str] | None]):
        """Replace or drop the document declaration after execution.

        Used by the CLI to reconcile the recorded document with ``-o``.  This is
        the only path allowed to change the declaration outside the rule block.
        """
        text, wildcards = value
        pattern = _placeholderize(text, self._effective_wildcards(wildcards))
        if pattern == text:
            pattern = None  # a concrete -o cannot be recorded as a pattern
        if pattern is not None and Path(pattern).suffix not in (".snd", ".html"):
            raise WorkflowError(
                f"document target {pattern!r} must end in .snd or .html"
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
        name = self._name
        if "document" in self._input:
            raise WorkflowError("input.document is preserved in the rule declaration")
        inputs = [*self._input._raw_items()]
        if self._filename is not None:
            document = self._filename
            inputs.append(("document", document))
            if not name:
                name = _rule_name(Path(document).stem)
        if name:
            lines = [f"rule {name}:"]
        else:
            lines = ["rule:"]
        lines.extend(_block("input", inputs, TAB))
        lines.extend(_block("output", self._output._raw_items(), TAB))
        lines.extend(_block("log", self._log._raw_items(), TAB))
        lines.extend(_block("params", self._params._raw_items(), TAB))
        if self._threads is not None:
            lines.append(f"{TAB}threads: {self._threads}")
        lines.extend(_block("resources", self._resources.items(), TAB))
        if conda_path is not None:
            lines.append(f"{TAB}conda:")
            lines.append(f"{TAB}{TAB}{_literal(str(conda_path))}")
        wildcards = " ".join(
            f"--wildcards {item}={{wildcards.{item}:q}}"
            for item in sorted(self.wildcard_names())
        )
        parts = ["snakedone", "{input.document:q}"]
        target_document = self.smk_target_document
        if target_document is not None:
            kind, _ = target_document
            parts.extend(("-o", f"{{{kind}.document:q}}"))
        if wildcards:
            parts.append(wildcards)
        lines.append(f"{TAB}shell:")
        lines.append(f"{TAB}{TAB}{_literal(' '.join(parts))}")
        return "\n".join(lines) + "\n"


def _rule_name(name: str):
    """Replace characters that Snakemake does not accept in a rule name."""
    if re.search(r"[A-Za-z0-9_]", name) is None:
        return "snakedone_document"
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name)
    return "_" + name if name[0].isdigit() else name


def _direct_attribute(node):
    """Return ``node``'s attribute name if it is ``<name>.<attr>``."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.attr
    return None


def _block(keyword: str, entries: Iterable[tuple], TAB="    "):
    entries = iter(entries)
    for k, v in entries:
        break
    else:
        return
    yield f"{TAB}{keyword}:"
    tab2 = TAB * 2
    yield f"{tab2}{_entry(k, v)}"
    for k, v in entries:
        yield f"{tab2}{_entry(k, v)}"


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


def rule(name: str | None = None):
    """Create and register the document's single rule."""
    if _registry.current() is not None:
        raise WorkflowError("snakedone.rule() can only be called once per document")
    declared = Rule(name)
    if _registry.executing():
        _registry.set_current(declared)
    return declared
