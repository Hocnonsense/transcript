"""Execute a document statement by statement, capturing report output."""

import __future__ as future

import ast

# import builtins
import io
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

from ._rule import registry
from .parse import ReportBlock, span

if TYPE_CHECKING:
    from .document import AstDocument

_FUTURE_FLAGS = 0
for _name in future.all_feature_names:
    _FUTURE_FLAGS |= getattr(future, _name).compiler_flag


def text(value: str):
    """Normalize captured output to LF endings with a single trailing newline."""
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


class ExecutionScope:
    def __init__(self, path: Path, wildcards: dict[str, str] | None = None):
        self.path = path
        self.wildcards = dict(wildcards or {})

    def __enter__(self):
        filename = str(self.path)
        self.registry_scope = registry.Execution(self.wildcards)
        self.registry_scope.__enter__()
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
        self.registry_scope.__exit__(exc_type, exc, tb)


class _Report:
    """Plain context manager for ``with transcript.report:`` report blocks."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


report = _Report()


def execute(self: AstDocument, path: Path, wildcards: dict[str, str] | None = None):
    """Execute statements in order and capture dynamically identified reports."""

    filename = str(path)
    # collect future flags and send to each compile cell
    future_flags = (
        compile(self.tree, filename, "exec", dont_inherit=True).co_flags & _FUTURE_FLAGS
    )
    hack_name = "__transcript__name"
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

        # def displayhook(value):
        #     from .renderers.vegalite import is_altair_chart, vegalite

        #     if is_altair_chart(value):
        #         setattr(builtins, "_", value)
        #         print(repr(vegalite(value)))
        #     else:
        #         old_displayhook(value)

        # old_displayhook = sys.displayhook
        # sys.displayhook = displayhook
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
            # sys.displayhook = old_displayhook
        captured = stream.getvalue()
        return text(captured) if captured else ""

    def with_transcript(context, block: ReportBlock, optional_vars=None):
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
    rule_not_set = True

    with ExecutionScope(path, wildcards) as namespace:
        for i, node in enumerate(self.tree.body):
            if i not in self.regions:
                exec_statement(node)
                if rule_not_set:
                    rule_not_set = check_namespace(self, node, namespace)
                continue
            if isinstance(node, ast.With):
                context = eval_expression(node.items[0].context_expr)
                if context is not report:
                    if context is registry.current():
                        if TYPE_CHECKING:
                            context = registry.current()
                            assert context is not None
                        context.set_lambdas(node)
                    with_normal(context, node)
                    job = registry.current()
                    if context is job and job is not None:
                        rule_s, rule_e = span(node.items[0].context_expr, self.position)
                        job.edit = span(node, self.position), self.source[rule_s:rule_e]
                        if not rule_not_set:
                            if not job.target:
                                raise NameError(
                                    "Cannot trace the declared rule, please define "
                                    "it as a global variable"
                                )
                            if namespace[job.target] is not job:
                                # old name lost, try to find the new one
                                rule_not_set = True
                        if rule_not_set:
                            optional_vars = node.items[0].optional_vars
                            if not isinstance(optional_vars, ast.Name):
                                raise NameError(
                                    "transcript.rule() must be assigned `as` a name "
                                    "in the `with` statement"
                                )
                            job.target = optional_vars.id
                            rule_not_set = False
                    continue
                optional_vars = node.items[0].optional_vars
            else:
                context = report
                optional_vars = None
            blocks.append(self.regions[i].parse_block(self.source, self.position))
            outputs.append(with_transcript(context, blocks[-1], optional_vars))
            if rule_not_set:
                rule_not_set = check_namespace(self, node, namespace)
        job = registry.current()
    if failures:
        raise failures[0]
    return blocks, outputs, job


def check_namespace(self: AstDocument, node: ast.stmt, namespace: dict):
    """Find the variable bound to the rule and record its archive insertion.

    Return whether the rule is still unset.
    """
    job = registry.current()
    if job is None:
        return True
    for name, value in namespace.items():
        if value is job:
            _, end = span(node, self.position)
            newline = self.source.find("\n", end)
            if newline == -1:
                newline = len(self.source)
            job.target = name
            job.edit = (newline, newline), None
            return False
    return False
