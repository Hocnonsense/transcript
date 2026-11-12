import os
import subprocess
from pathlib import Path

import pytest

from transcript.document import parse
from transcript.parse import Slot, _string_interior
from transcript.tmd import _slot_literal

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: requires optional tools or slow rendering"
    )


def pytest_addoption(parser):
    parser.addoption(
        "--slow",
        action="store_true",
        default=False,
        help="run tests marked slow (Datavzrd exports and Vega-Lite SVG rendering)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--slow"):
        return
    skip = pytest.mark.skip(reason="slow; pass --slow to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


def slot_of(text: str):
    """Build an archive-shaped slot whose decoded value is *text* (test helper)."""
    literal = _slot_literal(text, "")
    start, end = _string_interior(literal, (0, len(literal)))
    if start < end and literal[start] == "\n":
        start += 1
    return Slot(literal[start:end], start, "", (0, len(literal)))


def run_cli(path: Path, *args: str, seed: str = "0"):
    env = {**os.environ, "PYTHONHASHSEED": seed}
    return subprocess.run(
        ["transcript", str(path), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def run_source(tmp_path: Path, source: str, name: str = "document.py"):
    """Write *source*, execute it, and return its outputs and archive text."""
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    document = parse(source, str(path))
    blocks, outputs, job = document.execute(path)
    return outputs, document.render_tmd(blocks, outputs, job)


def expected_outputs(path: Path):
    """Map each recorded statement's source to its archived output slot."""

    source = path.read_text(encoding="utf-8")
    document = parse(source, str(path))
    result: dict[str, str] = {}
    for block in document.blocks:
        for statement in block.statements:
            result[source[statement.start : statement.end]] = (
                statement.slot.value if statement.slot is not None else ""
            )
    return result
