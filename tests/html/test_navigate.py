"""The generated report page carries a merged outline and label navigate."""

from pathlib import Path

from transcript.html._navigate import anchors

from ..conftest import run_cli


def export(tmp_path: Path, markdown: str):
    path = tmp_path / "report.py"
    path.write_text(
        'if "transcript.md":\n    """\n' + markdown + '\n    """\n', encoding="utf-8"
    )
    result = run_cli(path, "--html")
    assert result.returncode == 0, result.stderr
    return path.with_suffix(".html").read_text(encoding="utf-8")


def test_anchors_share_one_namespace_across_parts():
    body, entries = anchors(
        [
            "<h1>Repeat</h1>",
            '<figure class="transcript-label" id="repeat-1">'
            "<figcaption>Result</figcaption></figure>",
            "<h2>Repeat</h2>",
            '<h3 id="repeat-1">Explicit</h3>',
        ]
    )

    assert '<h1 id="repeat">Repeat</h1>' in body
    assert '<h2 id="repeat-2">Repeat</h2>' in body
    assert '<h3 id="repeat-1-1">Explicit</h3>' in body
    assert entries == [
        ("heading", 1, "Repeat", "repeat"),
        ("label", 2, "Result", "repeat-1"),
        ("heading", 2, "Repeat", "repeat-2"),
        ("heading", 3, "Explicit", "repeat-1-1"),
    ]


def test_headings_get_anchors_and_a_navigate_on_the_right(tmp_path: Path):
    html = export(
        tmp_path,
        "# Overview\n\n## Detail\n\n### Deep\n",
    )
    assert '<div class="doc-md" data-tmd-span=' in html
    assert "data-tmd-span=" in html
    assert '<h1 id="overview">' not in html
    assert '<nav class="navigate"' not in html


def test_duplicate_headings_get_unique_ids(tmp_path: Path):
    html = export(tmp_path, "## Repeat\n\n## Repeat\n\n## Repeat\n")
    assert html.count('class="doc-md"') == 1
    assert '<h2 id="repeat">' not in html


def test_navigate_text_is_plain_and_keeps_unicode(tmp_path: Path):
    html = export(tmp_path, "# *Detail* `code`\n\n## 中文标题\n")
    assert '<div class="doc-md" data-tmd-span=' in html
    assert '<a href="#detail-code">Detail code</a>' not in html
    assert '<h2 id="中文标题">' not in html


def test_document_without_headings_has_no_navigate(tmp_path: Path):
    html = export(tmp_path, "Just prose, no records.\n")
    assert '<nav class="navigate"' not in html
    assert '<div class="page">' in html
    assert '<div class="page page--navigate">' not in html


def labelled(tmp_path: Path):
    path = tmp_path / "labels.py"
    path.write_text(
        "from transcript import label\n\n"
        "value = 7\n\n"
        'if "transcript.md":\n'
        '    """\n'
        "    # Section\n\n"
        "    See [figure](#fig-1).\n"
        '    """\n'
        '    label(value, "fig-1", "Figure one")\n'
        '    label(value, "fig-2")\n',
        encoding="utf-8",
    )
    result = run_cli(path, "--html")
    assert result.returncode == 0, result.stderr
    return path.with_suffix(".html").read_text(encoding="utf-8")


def test_both_types_merge_into_one_list_with_tabs(tmp_path: Path):
    html = labelled(tmp_path)
    assert (
        '<nav class="navigate" aria-label="Document outline"'
        ' data-collapsed="false">' in html
    )
    assert (
        '<button class="navigate-tab-body" type="button">Contents</button>' not in html
    )
    assert '<button class="navigate-tab-body" type="button">Labels</button>' in html
    assert (
        '<div class="navigate-tab" data-tmd-type="contents" data-active="true">'
        not in html
    )
    assert (
        '<div class="navigate-tab" data-tmd-type="labels" data-active="true">' in html
    )
    assert '<ol class="navigate-list" data-tmd-show="labels">' in html
    assert (
        '<li class="toc-label" data-tmd-type="labels">'
        '<a href="#fig-1">Figure one</a></li>' in html
    )
    assert (
        '<li class="toc-label" data-tmd-type="labels">'
        '<a href="#fig-2">fig-2</a></li>' in html
    )
    assert 'aria-pressed="true" aria-label="Add or remove Labels"' in html
    assert '<figure class="transcript-label" id="fig-1">' in html


def test_markdown_renderer_output_renders_in_the_browser(tmp_path: Path):
    # A markdown() heading is not server-rendered; the island keeps its source
    # so the runtime can render it and join the outline. The label that wraps
    # it is still server-rendered and stays in the outline.
    path = tmp_path / "markdown_label.py"
    path.write_text(
        "from transcript import label, markdown\n\n"
        'if "transcript.md":\n'
        '    """\n'
        "    # Section\n"
        '    """\n'
        '    label(markdown("## Quality decision\\n\\n'
        'Sample A passed."), "decision")\n',
        encoding="utf-8",
    )
    result = run_cli(path, "--html")
    assert result.returncode == 0, result.stderr
    html = path.with_suffix(".html").read_text(encoding="utf-8")
    assert '<h2 id="quality-decision">Quality decision</h2>' not in html
    assert 'data-tmd-renderer="markdown"' in html
    assert "transcript-output markdown" in html
    assert '<figure class="transcript-label" id="decision">' in html
    assert (
        '<li class="toc-label" data-tmd-type="labels">'
        '<a href="#decision">decision</a></li>' in html
    )
