"""Execution semantics: real namespace and per-statement capture."""

import subprocess
import sys
from pathlib import Path

from .conftest import run_source


def test_statements_run_in_module_namespace(tmp_path: Path):
    source = (
        'value = 1\n\nif "transcript.md":\n    """\n    section\n    """\n'
        "    value = 9\n"
        "    value\n\n"
        "assert value == 9\n"
    )
    outputs, _ = run_source(tmp_path, source)
    assert outputs == [["", "9\n"]]


def test_per_statement_stdout_capture(tmp_path: Path):
    source = (
        'if "transcript.md":\n    """\n    section\n    """\n'
        '    print("a")\n'
        "    1 + 1\n"
        '    print("b")\n'
    )
    outputs, _ = run_source(tmp_path, source)
    assert outputs == [["a\n", "2\n", "b\n"]]


def test_plain_python_runs_report_blocks(tmp_path: Path):
    source = (
        "import transcript\n\nvalue = 2\n\n"
        'with transcript.md:\n    """\n    section\n    """\n    value\n'
    )
    path = tmp_path / "scope.py"
    path.write_text(source, encoding="utf-8")
    plain = subprocess.run(
        [sys.executable, str(path)], capture_output=True, text=True, check=False
    )
    assert plain.returncode == 0, plain.stderr
