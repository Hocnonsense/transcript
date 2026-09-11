"""Execute one module, evaluating records at their narrative positions."""

import ast
import contextlib
import copy
import io
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .canon import display, text

if TYPE_CHECKING:
    from .parse import AstDocument, DocExpression


def evaluate(record: DocExpression, namespace: dict[str, Any], filename: str):
    tree = ast.parse(record.source, filename=filename)
    ast.increment_lineno(tree, record.line - 1)  # for error reporting

    stream = io.StringIO()
    value = None
    with contextlib.redirect_stdout(stream):
        last = tree.body[-1]
        if isinstance(last, ast.Expr):
            # take the last expression out of the body
            tree.body.pop()
        exec(compile(tree, filename, "exec", dont_inherit=True), namespace)
        if isinstance(last, ast.Expr):
            value = eval(
                compile(
                    ast.Expression(last.value), filename, "eval", dont_inherit=True
                ),
                namespace,
            )
            if value is not None:
                stream.write(display(value))
    captured = stream.getvalue()
    # if value is None and not captured and expression is not None:
    #     print(f"{filename}:{record.line}: warning: record returned None")
    return text(captured) if captured else ""


def _find_last_future_import(tree: ast.Module, prefix_end=0):
    """Find the last future import in the module body, starting from prefix_end."""
    while prefix_end < len(tree.body):
        # find the last future import if any
        node = tree.body[prefix_end]
        if not (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            break
        prefix_end += 1
    return prefix_end


def execute(document: AstDocument, path: Path):
    block_outputs = [[""] * len(block.codes) for block in document.blocks]
    module = types.ModuleType("__main__")
    namespace = module.__dict__
    namespace.update(__file__=str(path), __package__=None)

    def doc_code_runner(index: int):
        # Copy bindings once per string, retaining shared object identities.
        record_namespace = namespace.copy()
        for position, record in enumerate(document.blocks[index].codes):
            block_outputs[index][position] = evaluate(
                record, record_namespace, str(path)
            )

    uname_doc_code_runner = "__snakedone_record_block__"
    while uname_doc_code_runner in document.source:
        uname_doc_code_runner += uname_doc_code_runner
    namespace[uname_doc_code_runner] = doc_code_runner
    by_position = {
        (block.node.lineno, block.node.col_offset): i
        for i, block in enumerate(document.blocks)
        if block.codes
    }

    class Instrument(ast.NodeTransformer):
        def visit_Expr(self, node: ast.Expr):
            index = by_position.get((node.lineno, node.col_offset))
            if index is None:
                return node
            call = ast.Expr(
                ast.Call(
                    func=ast.Name(id=uname_doc_code_runner, ctx=ast.Load()),
                    args=[ast.Constant(index)],
                    keywords=[],
                )
            )
            return [node, ast.copy_location(call, node)]

    # Scan only the legal prefix: an optional docstring, then future imports.
    tree = copy.deepcopy(document.tree)
    has_docstring = ast.get_docstring(tree) is not None

    # region handle running inject of module docstring around future imports
    prefix_end = _find_last_future_import(tree, int(has_docstring))
    module_prefix = tree.body[:prefix_end]
    instrument = Instrument()
    if has_docstring:
        # lazy insert the collect call after the future imports
        transformed = instrument.visit(module_prefix[0])
        if isinstance(transformed, list):
            # The original docstring is already in the preserved prefix.
            module_prefix.extend(transformed[1:])
    # endregion handle running inject of module docstring around future imports

    tree.body = tree.body[prefix_end:]
    instrument.visit(tree)
    tree.body = module_prefix + tree.body
    ast.fix_missing_locations(tree)

    old_main = sys.modules.get("__main__")
    old_path, old_argv = sys.path, sys.argv
    try:
        sys.modules["__main__"] = module
        sys.path = [str(path.parent), *old_path]
        sys.argv = [str(path)]
        exec(compile(tree, str(path), "exec", dont_inherit=True), namespace)
    finally:
        if old_main is not None:
            sys.modules["__main__"] = old_main
        else:
            sys.modules.pop("__main__", None)
        sys.path = old_path
        sys.argv = old_argv
    return block_outputs
