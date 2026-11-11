"""Static validation and local evaluation of declared input/params lambdas."""

from __future__ import annotations

import ast
import dis
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from snakemake.common import get_input_function_aux_params
from snakemake.exceptions import WorkflowError

if TYPE_CHECKING:
    from snakemake.iocontainers import Wildcards


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
