"""The rule's declared containers (input/output/log/params) and wildcard view."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

from snakemake.exceptions import WorkflowError
from snakemake.io import get_wildcard_names

try:  # Snakemake >= 9.16
    from snakemake.iocontainers import Namedlist
except ImportError:  # Snakemake 9.x before the module split
    from snakemake.io import Namedlist  # type: ignore

from .lambdas import _StaticLambda
from .wildcards import _iter_str, _matches

if TYPE_CHECKING:
    from .core import Rule

_MISSING = object()


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
