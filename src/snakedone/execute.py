"""Execute a document statement by statement, capturing report output."""

import __future__ as future

import ast
import io
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

from .parse import ReportBlock

if TYPE_CHECKING:
    from .document import AstDocument

_FUTURE_FLAGS = 0
for _name in future.all_feature_names:
    _FUTURE_FLAGS |= getattr(future, _name).compiler_flag


def text(value: str):
    """Normalize captured output to LF endings with a single trailing newline."""
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


class ExecutionScope:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        filename = str(self.path)
        self.old_path, self.old_argv = sys.path, sys.argv
        sys.path = [str(self.path.parent), *self.old_path]
        sys.argv = [filename]
        module = types.ModuleType("__main__")
        self.old_main = sys.modules.get("__main__")
        sys.modules["__main__"] = module
        namespace = module.__dict__
        namespace.update(__file__=filename, __package__=None)
        return namespace

    def __exit__(self, exc_type, exc, tb):
        if self.old_main is not None:
            sys.modules["__main__"] = self.old_main
        else:
            sys.modules.pop("__main__", None)
        sys.path = self.old_path
        sys.argv = self.old_argv


class _Report:
    """Plain context manager for ``with snakedone.report:`` report blocks."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


report = _Report()


def execute(self: AstDocument, path: Path):
    """Execute statements in order and capture dynamically identified reports."""

    filename = str(path)
    # collect future flags and send to each compile cell
    future_flags = (
        compile(self.tree, filename, "exec", dont_inherit=True).co_flags & _FUTURE_FLAGS
    )
    hack_name = "__snakedone__name"
    while hack_name in self.source:
        hack_name += hack_name

    def eval_expression(node: ast.expr):
        return eval(
            compile(
                ast.Expression(node),
                filename,
                "eval",
                flags=future_flags,
                dont_inherit=True,
            ),
            namespace,
        )

    def exec_statement(node: ast.stmt):
        return exec(
            compile(
                ast.Module(body=[node], type_ignores=[]),
                filename,
                "exec",
                flags=future_flags,
                dont_inherit=True,
            ),
            namespace,
        )

    def run_captured(node: ast.stmt):
        stream = io.StringIO()
        old = sys.stdout
        sys.stdout = stream
        try:
            exec(
                compile(
                    ast.Interactive(body=[node]),
                    filename,
                    "single",
                    flags=future_flags,
                    dont_inherit=True,
                ),
                namespace,
            )
        except BaseException as exc:
            failures.append(exc)
            raise
        finally:
            sys.stdout = old
        captured = stream.getvalue()
        return text(captured) if captured else ""

    def with_snakedone(context, block: ReportBlock, optional_vars=None):
        with context as entered:
            if optional_vars is not None:
                # bind the entered context manager to the `with ... as` target
                namespace[hack_name] = entered
                assignment = ast.Assign(
                    targets=[optional_vars],
                    value=ast.Name(id=hack_name, ctx=ast.Load()),
                )
                ast.fix_missing_locations(assignment)
                exec_statement(assignment)
                del namespace[hack_name]
            return [run_captured(statement.node) for statement in block.statements]

    def with_normal(context, node: ast.With):
        namespace[hack_name] = context
        rebuilt = ast.With(
            items=[
                ast.withitem(
                    context_expr=ast.Name(id=hack_name, ctx=ast.Load()),
                    optional_vars=node.items[0].optional_vars,
                )
            ],
            body=node.body,
            type_comment=node.type_comment,
        )
        ast.fix_missing_locations(rebuilt)
        exec_statement(rebuilt)
        del namespace[hack_name]

    failures: list[BaseException] = []
    outputs: list[list[str]] = []
    blocks: list[ReportBlock] = []
    with ExecutionScope(path) as namespace:
        for i, node in enumerate(self.tree.body):
            if i not in self.regions:
                exec_statement(node)
                continue
            if TYPE_CHECKING:
                node = self.regions[i].node
            if isinstance(node, ast.With):
                context = eval_expression(node.items[0].context_expr)
                if context is not report:
                    with_normal(context, node)
                    continue
                optional_vars = node.items[0].optional_vars
            else:
                context = report
                optional_vars = None
            blocks.append(self.regions[i].parse_block(self.position))
            outputs.append(with_snakedone(context, blocks[-1], optional_vars))
    if failures:
        raise failures[0]
    return blocks, outputs
