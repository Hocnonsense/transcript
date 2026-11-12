"""The exported page embeds the archive and can export it back as ``.tmd.py``."""

import json
from pathlib import Path

from transcript.html import extract
from transcript.html._island import source_island

from ..conftest import run_cli

SOURCE = (
    'if "transcript.md":\n'
    '    """\n'
    "    # A <tag> and a closing </script>\n"
    '    """\n'
    '    "<not html>"\n'
)


def test_island_round_trips_the_raw_source():
    page = f"<html><body>{source_island(SOURCE)}</body></html>"
    assert extract(page) == SOURCE


def test_island_escapes_a_closing_script_tag():
    island = source_island("</script><b>")
    assert "</script>" not in island[: island.rindex("</script>")]
    assert "\\u003c/script" in island
    assert extract(f"<body>{island}</body>") == "</script><b>"


def test_export_embeds_offsets_and_extracts_the_archive(tmp_path: Path):
    path = tmp_path / "report.py"
    path.write_text(SOURCE, encoding="utf-8")
    result = run_cli(path, "--html")
    assert result.returncode == 0, result.stderr

    page = path.with_suffix(".html").read_text(encoding="utf-8")
    assert 'data-tmd-span="' in page
    assert "Export .tmd.py" in page

    archive = path.with_suffix(".tmd.py").read_text(encoding="utf-8")
    assert extract(page) == archive

    extracted = tmp_path / "extracted.tmd.py"
    result = run_cli(path.with_suffix(".html"), "-o", str(extracted))
    assert result.returncode == 0, result.stderr
    assert extracted.read_text(encoding="utf-8") == archive


def test_island_is_a_json_string():
    island = source_island("x")
    body = island[island.index(">") + 1 : island.rindex("</script>")]
    assert json.loads(body) == "x"
