"""Execute a document statement by statement, capturing report output."""

import ast
import io
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

from .canon import text
from .parse import parse_block

if TYPE_CHECKING:
    from .parse import AstDocument, ReportBlock


_FUTURE_FLAGS = 0
for _name in __import__("__future__").all_feature_names:
    _FUTURE_FLAGS |= getattr(__import__("__future__"), _name).compiler_flag


def _report_singleton():
    from . import report

    return report


class ExecutionScope:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.old_main = sys.modules.get("__main__")
        self.old_path, self.old_argv = sys.path, sys.argv
        module = types.ModuleType("__main__")
        filename = str(self.path)
        namespace = module.__dict__
        namespace.update(__file__=filename, __package__=None)
        sys.modules["__main__"] = module
        sys.path = [str(self.path.parent), *self.old_path]
        sys.argv = [str(self.path)]
        return namespace

    def __exit__(self, exc_type, exc, tb):
        if self.old_main is not None:
            sys.modules["__main__"] = self.old_main
        else:
            sys.modules.pop("__main__", None)
        sys.path = self.old_path
        sys.argv = self.old_argv


def execute(document: AstDocument, path: Path):
    """
    Run top-level statements in order
    capture blocks whose CM is the report.
    """
    filename = str(path)
    # collect future flags and send to each compile cell
    future_flags = (
        compile(document.tree, filename, "exec", dont_inherit=True).co_flags
        & _FUTURE_FLAGS
    )
    hack_name = "__snakedone__name"
    while hack_name in document.source:
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
    report_singleton = _report_singleton()
    outputs: list[list[str]] = []
    blocks: list[ReportBlock] = []
    with ExecutionScope(path) as namespace:
        for i, node in enumerate(document.tree.body):
            if i not in document.regions:
                exec_statement(node)
                continue
            if TYPE_CHECKING:
                node = document.regions[i].node
            if isinstance(node, ast.With):
                context = eval_expression(node.items[0].context_expr)
                if context is not report_singleton:
                    with_normal(context, node)
                    continue
                optional_vars = node.items[0].optional_vars
            else:
                context = report_singleton
                optional_vars = None
            blocks.append(parse_block(document.regions[i], document.position))
            outputs.append(with_snakedone(context, blocks[-1], optional_vars))
    if failures:
        raise failures[0]
    return blocks, outputs
