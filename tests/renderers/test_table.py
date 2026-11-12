"""Markdown tables built from pandas or polars DataFrames."""

from pathlib import Path

import pytest

from transcript import label, table

from ..conftest import run_cli


@pytest.fixture
def pandas():
    return pytest.importorskip("pandas")


def archive_body(output):
    lines = output.to_tmd().splitlines(keepends=True)
    assert lines[0].startswith("```transcript-output markdown=1")
    return "".join(lines[1:-1]).removesuffix("\n")


def test_dataframe_becomes_a_markdown_table():
    module = pytest.importorskip("polars")
    frame = module.DataFrame(
        {"sample": ["A", "B"], "score": [0.8, 0.3], "ok": [True, False]}
    )
    output = table(frame)
    assert output.name == "markdown"
    assert archive_body(output) == (
        "| sample | score | ok |\n"
        "| --- | --- | --- |\n"
        "| A | 0.8 | true |\n"
        "| B | 0.3 | false |"
    )


def test_pipes_backslashes_and_newlines_are_escaped(pandas):
    frame = pandas.DataFrame({"v": ["a|b", "c\\d", "e\nf"]})
    assert archive_body(table(frame)) == (
        "| v |\n| --- |\n| a\\|b |\n| c\\\\d |\n| e f |"
    )


def test_plain_range_index_is_dropped(pandas):
    assert archive_body(table(pandas.DataFrame({"score": [1, 2]}))) == (
        "| score |\n| --- |\n| 1 |\n| 2 |"
    )


def test_unnamed_non_default_index_is_filled(pandas):
    frame = pandas.DataFrame({"score": [1, 2]}, index=pandas.Index([10, 20]))
    assert archive_body(table(frame)) == (
        "| index | score |\n| --- | --- |\n| 10 | 1 |\n| 20 | 2 |"
    )


def test_label_wraps_the_table_with_a_caption(pandas):
    archived = label(table(pandas.DataFrame({"v": [1]})), "scores", "Scores").to_tmd()
    assert "transcript-output label=1" in archived.splitlines()[0]
    assert "transcript-output markdown=1" in archived


def test_non_dataframe_is_rejected():
    with pytest.raises(TypeError, match="pandas or polars DataFrame"):
        table([1, 2, 3])


def test_html_export_archives_markdown_for_the_browser(tmp_path: Path, pandas):
    path = tmp_path / "report.py"
    path.write_text(
        '"""Markdown table."""\n'
        "import pandas as pd\n"
        "from transcript import table\n\n"
        'frame = pd.DataFrame({"sample": ["A"], "score": [1.0]})\n\n'
        'if "transcript.md":\n    """\n    Markdown table.\n    """\n'
        "    table(frame)\n",
        encoding="utf-8",
    )
    result = run_cli(path, "--html")
    assert result.returncode == 0, result.stderr
    archive = path.with_suffix(".tmd.py").read_text(encoding="utf-8")
    assert "```transcript-output markdown=1" in archive
    assert "| sample | score |" in archive
    document = path.with_suffix(".html").read_text(encoding="utf-8")
    assert 'data-tmd-renderer="markdown"' in document
    assert 'id="transcript-source"' in document
