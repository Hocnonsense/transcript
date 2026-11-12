"""Regression tests for report block edge cases."""

import ast
from pathlib import Path

from transcript.document import parse

from .conftest import run_cli, run_source


def test_slot_follows_a_trailing_comment(tmp_path: Path):
    source = (
        'if "transcript.md":\n    """\n    section\n    """\n'
        "    print(1)  # explanation\n"
    )
    path = tmp_path / "comment.py"
    path.write_text(source, encoding="utf-8")
    assert run_cli(path).returncode == 0
    target = path.with_suffix(".tmd.py")
    generated = target.read_text(encoding="utf-8")
    ast.parse(generated)
    assert "print(1)  # explanation" in generated
    assert run_cli(target, "--overwrite").returncode == 0
    assert target.read_text(encoding="utf-8") == generated


def test_marker_recognizes_a_with_block():
    document = parse(
        "value = 2\n\nwith something:  # transcript.md\n    value\n", "marker.py"
    )
    assert len(document.regions) == 1
    region = next(iter(document.regions.values()))
    assert region.marker
    block = region.parse_block(document.source, document.position)
    assert isinstance(block.node, ast.With)


def test_identity_confirms_unmarked_aliases(tmp_path: Path):
    source = (
        "from transcript import md\nimport transcript\n\n"
        "value = 2\n\n"
        "with md:\n    value\n\n"
        "alias = transcript.md\n\n"
        "with alias:\n    value + 1\n"
    )
    outputs, rendered = run_source(tmp_path, source)
    assert outputs == [["2\n"], ["3\n"]]
    assert "with md:  # transcript.md" in rendered
    assert "with alias:  # transcript.md" in rendered


def test_marker_requires_a_comment_token():
    document = parse(
        "from contextlib import nullcontext\n\n"
        'with nullcontext("# transcript.md"):\n    value\n',
        "false.py",
    )
    assert not any(region.marker for region in document.regions.values())
    suffix = parse("with something:  # transcript.md-other\n    pass\n", "suffix.py")
    assert not any(region.marker for region in suffix.regions.values())
