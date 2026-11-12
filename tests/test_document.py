"""Document semantics, checked through the public command only."""

from pathlib import Path

from .conftest import run_cli


def test_syntax_error_is_found_before_code_execution(tmp_path: Path):
    path = tmp_path / "analysis.py"
    marker = tmp_path / "executed"
    path.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        'if "transcript.md":\n    1 +\n',
        encoding="utf-8",
    )
    result = run_cli(path)
    assert result.returncode == 2
    assert "syntax" in result.stderr.lower()
    assert not marker.exists()
    assert not path.with_suffix(".tmd.py").exists()
