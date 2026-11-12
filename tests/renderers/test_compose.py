"""Composed panel grids and their nested renderer assets."""

import textwrap

import pytest

from transcript import compose, label, markdown
from transcript.document import parse
from transcript.output import Renderer
from transcript.renderers.compose import Compose


def fence_source(output: Renderer):
    fence = output.to_tmd().replace("\\", "\\\\")
    return (
        'if "transcript.md":\n'
        '    """\n    section\n    """\n'
        "    value\n"
        '    """\n' + textwrap.indent(fence, "    ") + '    """\n'
    )


def test_compose_renders_a_grid_and_collects_panel_assets():
    output = compose(
        label(markdown("## One\n\nFirst."), "one", "One"),
        label(3, "three", "Three"),
        ncol=3,
    )
    assert output.to_tmd().startswith('`````transcript-output compose=1\n{"ncol":3}\n')
    html = parse(fence_source(output), "r.tmd.py").render_html()
    assert '<div class="transcript-compose" style="--transcript-cols:3">' in html
    assert html.count('<figure class="transcript-panel">') == 2
    assert '<span class="transcript-panel-label">(B)</span>' in html
    assert ".transcript-compose" in html
    # The label keeps a contrasting chip as a fallback, and a runtime adapts it
    # to the chart behind it (pick black/white and compress its luminance).
    assert "background: Canvas" in html
    assert "color-mix(in srgb, Canvas 65%, transparent)" in html
    assert "padding: 0" in html
    assert ".transcript-label-caption-header" in html
    assert "order: -1" in html
    assert html.count("background: none; color: CanvasText") == 2
    assert "getImageData" in html
    for renderer in ("compose", "label", "code", "markdown"):
        assert f'data-tmd-renderer="{renderer}"' in html


def test_compose_falls_back_to_the_code_renderer():
    output = compose({"answer": 42}, ncol=1)
    assert "{'answer': 42}" in output.serialize()
    html = parse(fence_source(output), "r.tmd.py").render_html()
    assert 'data-tmd-renderer="code"' in html
    assert "{&#x27;answer&#x27;: 42}" in html


def test_compose_substitutes_every_panel_template():
    # Regression: render_node read the removed RecordedOutput.text attribute.
    output = compose(1, 2, labels=False)
    html = parse(fence_source(output), "r.tmd.py").render_html()
    assert "{{0}}" not in html
    assert '<samp class="doc-out">1</samp>' in html
    assert "{{1}}" not in html
    assert '<samp class="doc-out">2</samp>' in html
    # test labels=False
    assert '"labels":false' in output.serialize()
    html = parse(fence_source(output), "r.tmd.py").render_html()
    assert 'class="transcript-panel-label"' not in html


@pytest.mark.parametrize(
    "config,message",
    [
        ({"ncol": 0}, "positive integer"),
        ({"ncol": True}, "positive integer"),
        ({"labels": "yes"}, "boolean"),
        ({"cols": 2}, "unknown fields"),
    ],
)
def test_compose_rejects_invalid_headers(config, message):
    with pytest.raises(ValueError, match=message):
        Compose([1], config)
