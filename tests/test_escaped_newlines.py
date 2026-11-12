"""Archived output slots are escaped so the archive stays valid Python."""

from pathlib import Path

import pytest

from .conftest import expected_outputs, run_cli


@pytest.mark.parametrize(
    "output",
    [
        '{"a": "b"}',
        'trailing"',
        'trailing""',
        'trailing"""',
        'contains """ triple',
        "mixed 'single' and \"double\"",
        'backslash\\n and quote"',
    ],
)
def test_output_is_escaped_and_archive_reruns(tmp_path: Path, output: str) -> None:
    path = tmp_path / "quotes.py"
    path.write_text(
        f"output = {output!r}\n\n"
        'if "transcript.md":\n    """\n    section\n    """\n'
        "    print(output, end='')\n",
        encoding="utf-8",
    )
    assert run_cli(path).returncode == 0
    target = path.with_suffix(".tmd.py")
    assert expected_outputs(target)["print(output, end='')"] == output + "\n"
    assert run_cli(target).returncode == 0
    assert run_cli(target, "--overwrite").returncode == 0


def test_physical_newlines_in_output(tmp_path: Path) -> None:
    path = tmp_path / "lines.py"
    path.write_text(
        'if "transcript.md":\n    """\n    section\n    """\n'
        "    [print(i) for i in (1, 2)]\n"
    )
    assert run_cli(path).returncode == 0
    target = path.with_suffix(".tmd.py")
    assert expected_outputs(target) == {
        "[print(i) for i in (1, 2)]": "1\n2\n[None, None]\n"
    }
    assert run_cli(target).returncode == 0
