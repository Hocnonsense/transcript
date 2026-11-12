"""CLI boundaries for archived DataFrames and offline HTML export."""

import json
import shutil
from pathlib import Path

import pytest

from transcript.output import RecordedOutput, split_output

from ..conftest import EXAMPLES, expected_outputs, run_cli, slot_of

requires_datavzrd = pytest.mark.skipif(
    shutil.which("datavzrd") is None,
    reason="the datavzrd executable is not installed",
)
pytestmark = pytest.mark.slow
PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+a6n0AAAAASUVORK5CYII="
)


@requires_datavzrd
@pytest.mark.parametrize("backend", ["pandas", "polars"])
def test_archive_exports_after_original_inputs_are_removed(
    tmp_path: Path, backend: str, monkeypatch
):
    pytest.importorskip(backend)
    yaml = pytest.importorskip("yaml")
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "analysis.py"
    data_path = tmp_path / "input.csv"
    config_path = tmp_path / "table.yaml"
    csv = "sample,score,count\nA,0.8,10\nB,0.3,25\nC,0.9,40\nD,0.6,15\n"
    data_path.write_text(csv, encoding="utf-8")
    shutil.copyfile(EXAMPLES / "datavzrd.yaml", config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    source.write_text(
        "from pathlib import Path\n"
        "from base64 import b64decode\n"
        f"import {backend} as frames\n"
        "from transcript import datavzrd, image\n"
        'frame = frames.read_csv(Path(__file__).with_name("input.csv"))\n'
        f'picture = b64decode("{PNG}")\n'
        '\nif "transcript.md":\n'
        '    """\n    section\n    """\n'
        '    print("stream-before")\n'
        '    image(picture, alt="pixel")\n'
        '    print("stream-between")\n'
        '    datavzrd(frame, "table.yaml")\n',
        encoding="utf-8",
    )
    generated = run_cli(source)
    assert generated.returncode == 0, generated.stderr
    archive = source.with_suffix(".tmd.py")
    before = archive.read_bytes()
    combined = "".join(expected_outputs(archive).values())
    before_text, picture, middle_text, snapshot = list(split_output(slot_of(combined)))
    assert before_text == "stream-before\n"
    assert isinstance(picture, RecordedOutput)
    assert picture.renderer.name == "bitmap"
    assert middle_text == "stream-between\n"
    assert isinstance(snapshot, RecordedOutput)
    lines = combined.splitlines(keepends=True)
    start = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("```transcript-output datavzrd")
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("```"))
    stored = json.loads("".join(lines[start + 1 : end]).removesuffix("\n"))
    assert stored["csv"] == csv
    assert stored["config"] == config
    for path, flags in ((source, ("--diff",)), (archive, ())):
        compared = run_cli(path, *flags, seed="random")
        assert compared.returncode == 0, compared.stderr
        assert compared.stdout == ""
        assert archive.read_bytes() == before

    for path in (source, data_path, config_path):
        path.unlink()
    target = tmp_path / "shared" / "report.html"
    exported = run_cli(archive, "--html", "-o", str(target))
    assert exported.returncode == 0, exported.stderr
    assert archive.read_bytes() == before
    assert {path.name for path in target.parent.iterdir()} == {"report.html"}
    html = target.read_text(encoding="utf-8")
    stream = html[html.index('<samp class="doc-out">') :]
    positions = [
        stream.index(marker)
        for marker in (
            "stream-before\n",
            f'src="data:image/png;base64,{PNG}"',
            "stream-between\n",
            'data-tmd-report="report-0-3-0"',
        )
    ]
    assert positions == sorted(positions)
    marker = 'id="transcript-reports" type="application/json">'
    start = html.index(marker) + len(marker)
    payload = json.loads(html[start : html.index("</script>", start)])
    files = next(files for files in payload["reports"].values() if files)
    assert any(name.startswith("scores/") and name.endswith(".html") for name in files)
    assert any(name.startswith("raw/") and name.endswith(".html") for name in files)
