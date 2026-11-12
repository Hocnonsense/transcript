"""CLI acceptance tests: generate, compare, and overwrite real documents."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import EXAMPLES, expected_outputs, run_cli

TABLE = "table"
PICTURE = 'image(png_bytes(image_source["red"]), alt="A one-pixel RGB sample")'
PLOT = 'image(matplotlib_plot(data["value"]), alt="A line plot of the sample value")'


@pytest.fixture
def document(tmp_path: Path):
    for name in ("demo.py", "data.json"):
        shutil.copyfile(EXAMPLES / name, tmp_path / name)
    return tmp_path / "demo.py"


def change_input(path: Path, field: str, value: str | int):
    data_path = path.with_name("data.json")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data[field] = value
    data_path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def test_generate_python_document_with_text_image_and_table(document: Path):
    source_before = document.read_bytes()
    result = run_cli(document, "--html")
    assert result.returncode == 0, result.stderr
    target = document.with_suffix(".tmd.py")
    assert target.is_file()
    assert document.read_bytes() == source_before
    raw = target.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
    records = expected_outputs(target)
    assert set(records) == {
        "message",
        "image_source",
        PICTURE,
        PLOT,
        TABLE,
    }
    assert records["message"] == "'Sample: baseline'\n"
    assert "baseline" in records[TABLE] and "7" in records[TABLE]
    assert "'red': 32" in records["image_source"]
    html = document.with_suffix(".html").read_text(encoding="utf-8")
    for code in (PICTURE, PLOT):
        data = json.loads("\n".join(records[code].splitlines()[1:-1]))
        assert data["mime"] == "image/png"
        assert f'src="data:image/png;base64,{data["data"]}"' in html
    for script in (document, target):
        plain = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, check=False
        )
        assert plain.returncode == 0, plain.stderr


def test_diff_then_overwrite(document: Path):
    assert run_cli(document).returncode == 0
    target = document.with_suffix(".tmd.py")
    before = target.read_bytes()
    source_before = document.read_bytes()
    old_records = expected_outputs(target)
    change_input(document, "value", 19)

    comparison = run_cli(document, "--diff")
    assert comparison.returncode == 1, comparison.stderr
    assert "--- " in comparison.stdout and "+++ " in comparison.stdout
    assert "@@" in comparison.stdout
    assert target.read_bytes() == before
    assert not target.with_suffix(".archive.new").exists()

    update = run_cli(document)
    assert update.returncode == 0, update.stderr
    assert target.read_bytes() != before
    assert document.read_bytes() == source_before
    new_records = expected_outputs(target)
    assert {key for key in old_records if old_records[key] != new_records[key]} == {
        PLOT,
        TABLE,
    }
    assert "19" in new_records[TABLE]
    diff_lines = comparison.stdout.splitlines()
    assert any(
        line.startswith("-") and "baseline" in line and "7" in line
        for line in diff_lines
    )
    assert any(
        line.startswith("+") and "baseline" in line and "19" in line
        for line in diff_lines
    )

    unchanged = run_cli(document, "--diff")
    assert unchanged.returncode == 0, unchanged.stderr
    assert unchanged.stdout == ""


def test_archive_diff_is_self_contained(document: Path):
    assert run_cli(document).returncode == 0
    target = document.with_suffix(".tmd.py")
    before = target.read_bytes()
    document.unlink()  # The archive must not depend on the original .py file.
    result = run_cli(target, "--diff")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert target.read_bytes() == before
    change_input(target, "value", 19)
    result = run_cli(target, "--diff")
    assert result.returncode == 1, result.stderr
    removed = [line for line in result.stdout.splitlines() if line.startswith("-")]
    added = [line for line in result.stdout.splitlines() if line.startswith("+")]
    assert any("baseline" in line and "7" in line for line in removed)
    assert any("baseline" in line and "19" in line for line in added)
    assert target.read_bytes() == before


def test_explicit_overwrite_updates_an_archive(document: Path):
    assert run_cli(document).returncode == 0
    target = document.with_suffix(".tmd.py")
    before = target.read_bytes()
    change_input(target, "value", 19)

    result = run_cli(target, "--overwrite")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert target.read_bytes() != before
    assert "19" in expected_outputs(target)[TABLE]
    comparison = run_cli(target, "--diff")
    assert comparison.returncode == 0, comparison.stderr
    assert comparison.stdout == ""


def test_diff_and_overwrite_are_mutually_exclusive(document: Path):
    before = document.read_bytes()
    result = run_cli(document, "--diff", "--overwrite")
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
    assert result.stdout == ""
    assert document.read_bytes() == before
    assert not document.with_suffix(".tmd.py").exists()


def test_missing_source_reports_file_not_found(tmp_path: Path):
    document = tmp_path / "missing.py"
    result = run_cli(document)
    assert result.returncode == 1
    assert "FileNotFoundError" in result.stderr
    assert str(document) in result.stderr
    assert result.stdout == ""
    assert not document.with_suffix(".tmd.py").exists()


def test_repeated_generation_is_byte_identical(document: Path):
    outputs: list[bytes] = []
    for seed in ("0", "1", "random"):
        result = run_cli(document, seed=seed)
        assert result.returncode == 0, result.stderr
        outputs.append(document.with_suffix(".tmd.py").read_bytes())
    assert outputs[0] == outputs[1] == outputs[2]
    assert str(document.parent).encode() not in outputs[0]


def test_execution_failure_never_writes_partial_output(document: Path):
    assert run_cli(document, "--html").returncode == 0
    target = document.with_suffix(".tmd.py")
    html = document.with_suffix(".html")
    before = target.read_bytes(), html.read_bytes()
    document.write_text(
        document.read_text(encoding="utf-8") + '\nraise RuntimeError("broken input")\n',
        encoding="utf-8",
    )
    source_before = document.read_bytes()
    result = run_cli(document, "--html")
    assert result.returncode == 2
    assert "broken input" in result.stderr
    assert (target.read_bytes(), html.read_bytes()) == before
    assert document.read_bytes() == source_before
    assert not target.with_suffix(".archive.new").exists()


def test_combined_export_diff_gates_html_and_creates_missing_archive(tmp_path: Path):
    source = tmp_path / "diff.py"
    source.write_text('if "transcript.md":\n    1\n', encoding="utf-8")
    assert run_cli(source, "--html", "--diff").returncode == 0
    archive = source.with_suffix(".tmd.py")
    html = source.with_suffix(".html")
    before = archive.read_bytes(), html.read_bytes()
    source.write_text('if "transcript.md":\n    2\n', encoding="utf-8")
    result = run_cli(source, "--html", "--diff")
    assert result.returncode == 1
    assert "@@" in result.stdout
    assert (archive.read_bytes(), html.read_bytes()) == before
    assert run_cli(archive, "--html", "--overwrite").returncode == 0


def test_output_paths_use_the_logical_stem(tmp_path: Path):
    source = tmp_path / "doc.py"
    source.write_text('if "transcript.md":\n    1\n', encoding="utf-8")

    result = run_cli(source, "-o", str(tmp_path / "report.py"))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "report.tmd.py").is_file()
    assert not (tmp_path / "report.py.tmd.py").exists()
    assert not (tmp_path / "report.py").exists()

    result = run_cli(source, "--html", "-o", str(tmp_path / "report.tmd.py"))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "report.tmd.py").is_file()
    assert (tmp_path / "report.html").is_file()
    assert not (tmp_path / "report.tmd.html").exists()
