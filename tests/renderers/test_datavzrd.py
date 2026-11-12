"""Datavzrd snapshots and their single-file offline HTML rendering."""

import json
import shutil
from pathlib import Path

import pytest

from transcript import datavzrd


@pytest.fixture
def pandas():
    return pytest.importorskip("pandas")


requires_datavzrd = pytest.mark.skipif(
    shutil.which("datavzrd") is None,
    reason="the datavzrd executable is not installed",
)


def archive_body(output):
    lines = output.to_tmd().splitlines(keepends=True)
    assert lines[0].startswith("```transcript-output")
    return "".join(lines[1:-1]).removesuffix("\n")


def body(output):
    return json.loads(archive_body(output))


@pytest.mark.parametrize("backend", ["pandas", "polars"])
def test_dataframe_snapshots_round_trip(backend: str):
    module = pytest.importorskip(backend)
    frame = module.DataFrame({"sample": ["A", "B"], "score": [0.8, 0.3]})
    output = datavzrd(frame)
    data = body(output)
    assert data["csv"] == "sample,score\nA,0.8\nB,0.3\n"
    assert data["config"] == {
        "default-view": "results",
        "views": {"results": {"dataset": "data"}},
    }


def test_infer_config_reads_polars_schema():
    pl = pytest.importorskip("polars")
    frame = pl.DataFrame({"label": ["x"], "score": [0.5], "ok": [True]})
    columns = datavzrd.infer_config(frame)
    columns = columns["views"]["results"]["render-table"]["columns"]
    assert columns["label"]["plot"]["pills"]
    assert columns["score"]["plot"]["bars"] == {}
    assert columns["ok"]["plot"]["pills"]


def test_omitted_config_keeps_defaults_and_accepts_inferred_config(pandas):
    frame = pandas.DataFrame(
        {"label": ["x"], "score": [0.5], "count": [1], "ok": [True]}
    )
    plain = datavzrd(frame)
    assert "render-table" not in body(plain)["config"]["views"]["results"]

    inferred = datavzrd(frame, datavzrd.infer_config(frame))
    columns = body(inferred)["config"]["views"]["results"]["render-table"]["columns"]
    pills = {"plot": {"pills": {"color-scheme": "category20"}}}
    bars = {"plot": {"bars": {}}}
    assert columns == {"label": pills, "score": bars, "count": bars, "ok": pills}


def test_single_view_opens_directly_and_multiple_views_keep_the_overview(pandas):
    single = datavzrd(pandas.DataFrame({"value": [1]}))
    assert body(single)["config"]["default-view"] == "results"
    multiple = datavzrd(
        pandas.DataFrame({"value": [1]}),
        {"views": {"a": {"dataset": "data"}, "b": {"dataset": "data"}}},
    )
    assert "default-view" not in body(multiple)["config"]


def test_snapshot_copies_the_author_config(pandas):
    config = {"views": {"results": {"dataset": "data"}}}
    output = datavzrd(pandas.DataFrame({"value": [1]}), config)
    config["views"]["results"]["dataset"] = "mutated"
    assert body(output)["config"]["views"]["results"]["dataset"] == "data"


def test_relative_yaml_config_uses_the_working_directory(
    tmp_path: Path, pandas, monkeypatch
):
    (tmp_path / "table.yaml").write_text(
        "views:\n  results:\n    dataset: data\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    output = datavzrd(pandas.DataFrame({"value": [1]}), "table.yaml")
    assert body(output)["config"]["views"]["results"]["dataset"] == "data"
