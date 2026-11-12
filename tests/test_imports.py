"""Core imports and document execution do not require optional dependencies."""

import subprocess
import sys
from pathlib import Path


def test_core_imports_without_site_packages():
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])

import transcript
import transcript.cli
from transcript.document import parse
from transcript.execute import md
from transcript.renderers import get

assert transcript.md is md
assert get("datavzrd") is not None
assert not {"markdown_it", "pygments", "yaml"} & sys.modules.keys()
document = parse(
    "import transcript\\nwith transcript.md:  # transcript.md\\n    2 + 3\\n",
    "test.py",
)
blocks, outputs, _ = document.execute(Path("test.py"))
assert outputs == [["5\\n"]]
assert "5" in document.render_tmd(blocks, outputs)

html = document.render_html()
assert 'class="doc-code" data-tmd-span=' in html
assert not {"markdown_it", "pygments", "yaml"} & sys.modules.keys()

try:
    transcript.datavzrd(object(), "config.yaml")
except ValueError as error:
    assert 'Invalid Datavzrd configuration' in str(error)
else:
    raise AssertionError("A missing configuration should be rejected")
""",
            str(Path(__file__).resolve().parents[1] / "src"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
