"""Vega-Lite snapshots and their static SVG rendering."""

import datetime
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from transcript import vegalite

from ..conftest import EXAMPLES, expected_outputs, run_cli

SPEC = {
    "mark": "bar",
    "encoding": {
        "x": {"field": "sample", "type": "nominal"},
        "y": {"field": "score", "type": "quantitative"},
    },
}

requires_vegalite = pytest.mark.skipif(
    importlib.util.find_spec("vl_convert") is None,
    reason="vl-convert-python is not installed",
)


@pytest.fixture
def pandas():
    return pytest.importorskip("pandas")


def archive_body(output):
    lines = output.to_tmd().splitlines(keepends=True)
    assert lines[0].startswith("```transcript-output")
    return "".join(lines[1:-1]).removesuffix("\n")


def body(output) -> dict:
    return json.loads(archive_body(output))


@pytest.mark.parametrize("backend", ["pandas", "polars"])
def test_dataframe_snapshots_round_trip(backend: str):
    module = pytest.importorskip(backend)
    frame = module.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})
    data = body(vegalite(SPEC, frame))
    assert data == {
        **SPEC,
        "width": 800,
        "height": 450,
        "data": {
            "values": [
                {"sample": "A", "score": 0.8},
                {"sample": "B", "score": 0.3},
            ]
        },
    }


def test_author_supplied_data_is_preserved_without_a_data_argument():
    spec = {
        **SPEC,
        "data": {"name": "source"},
        "datasets": {"source": [{"sample": "A", "score": 1.0}]},
    }
    assert body(vegalite(spec)) == {
        **spec,
        "width": 800,
        "height": 450,
    }


def test_missing_values_become_null_and_dates_are_iso(pandas):
    frame = pandas.DataFrame(
        {"t": [datetime.date(2020, 1, 1)], "v": [float("nan")], "flag": [True]}
    )
    data = body(vegalite(SPEC, frame))["data"]["values"]
    assert data == [{"t": "2020-01-01", "v": None, "flag": True}]


def test_relative_yaml_spec_uses_the_working_directory(
    tmp_path: Path, pandas, monkeypatch
):
    yaml = pytest.importorskip("yaml")
    (tmp_path / "chart.yaml").write_text(yaml.safe_dump(SPEC), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    frame = pandas.DataFrame({"sample": ["A"], "score": [1.0]})
    assert body(vegalite("chart.yaml", frame)) == {
        **SPEC,
        "width": 800,
        "height": 450,
        "data": {"values": [{"sample": "A", "score": 1.0}]},
    }


def test_json_spec_file_needs_no_yaml(tmp_path: Path, pandas):
    path = tmp_path / "chart.json"
    path.write_text(json.dumps(SPEC), encoding="utf-8")
    data = body(vegalite(path, pandas.DataFrame({"sample": ["A"], "score": [1.0]})))
    assert data == {
        **SPEC,
        "width": 800,
        "height": 450,
        "data": {"values": [{"sample": "A", "score": 1.0}]},
    }


def test_explicit_size_is_preserved(pandas):
    spec = {**SPEC, "width": 640, "height": 360}
    data = body(vegalite(spec, pandas.DataFrame({"sample": ["A"], "score": [1.0]})))
    assert data["width"] == 640
    assert data["height"] == 360


@pytest.mark.slow
def test_demo_archive_records_offline_and_interactive_snapshots(
    tmp_path: Path, monkeypatch
):
    for name in ("vegalite_demo.py", "vegalite.yaml"):
        shutil.copyfile(EXAMPLES / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "vegalite_demo.py"
    result = run_cli(source)
    assert result.returncode == 0, result.stderr
    records = expected_outputs(source.with_suffix(".tmd.py"))
    offline = next(v for k, v in records.items() if "offline=True" in k)
    interactive = next(v for k, v in records.items() if "config_dict" in k)
    assert offline.startswith("```transcript-output vegalite_offline=1\n")
    assert interactive.startswith("```transcript-output vegalite_interactive=1\n")
    values = [
        {"count": 10, "sample": "A", "score": 0.8},
        {"count": 25, "sample": "B", "score": 0.3},
        {"count": 40, "sample": "C", "score": 0.9},
        {"count": 15, "sample": "D", "score": 0.6},
    ]
    offline_spec = json.loads("\n".join(offline.splitlines()[1:-1]))
    assert offline_spec["mark"] == "bar"
    assert (offline_spec["width"], offline_spec["height"]) == (400, 250)
    assert offline_spec["data"]["values"] == values
    interactive_spec = json.loads("\n".join(interactive.splitlines()[1:-1]))
    assert interactive_spec["mark"] == "point"
    assert (interactive_spec["width"], interactive_spec["height"]) == (500, 300)
    assert interactive_spec["data"]["values"] == values


@pytest.mark.slow
@requires_vegalite
def test_demo_html_export_embeds_offline_svg_and_interactive_spec(
    tmp_path: Path, monkeypatch
):
    for name in ("vegalite_demo.py", "vegalite.yaml"):
        shutil.copyfile(EXAMPLES / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "vegalite_demo.py"
    result = run_cli(source, "--html")
    assert result.returncode == 0, result.stderr
    html = source.with_suffix(".html").read_text(encoding="utf-8")
    assert html.count("<svg") >= 2
    assert html.count('data-state="offline"') >= 2
    assert 'class="transcript-vegalite-spec"' in html
    assert "https://cdn.jsdelivr.net/npm/vega-embed@6" in html
    assert "'unsafe-eval'" in html
