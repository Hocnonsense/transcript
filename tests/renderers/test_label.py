"""Label wrappers and dynamic nested renderer assets."""

import textwrap

import pytest

from transcript import label, markdown
from transcript.cli import tmd2html
from transcript.document import parse
from transcript.output import Rendered, Renderer
from transcript.renderers import RENDERERS
from transcript.renderers.label import set_cache

from ..conftest import slot_of


class Inner(Renderer):
    name = "inner_test"
    version = (1,)
    STYLE = ".inner-test { color: red; }"
    runtime = "window.innerTest = true;"
    sources = ["https://inner.example.test"]

    def __init__(self, text="x"):
        self.text = text

    def serialize(self):
        return self.text

    @classmethod
    def to_html(cls, slot):
        return Rendered(
            f'<span class="inner-test">{slot.value}</span>',
            {"index.html": ("text/html", b"<p>inner</p>")},
        )


def register(monkeypatch):
    monkeypatch.setitem(RENDERERS, Inner.name, Inner)


@pytest.fixture
def label_cache():
    previous = set_cache({})
    try:
        yield
    finally:
        set_cache(previous)


def fence_source(output):
    fence = output.to_tmd().replace("\\", "\\\\")
    return (
        'if "transcript.md":\n'
        '    """\n    section\n    """\n'
        "    value\n"
        '    """\n' + textwrap.indent(fence, "    ") + '    """\n'
    )


def test_label_serializes_an_inner_reference(monkeypatch):
    register(monkeypatch)
    text = label(Inner("hello"), "fig1", caption="Cap").to_tmd()
    assert text.startswith("````transcript-output label=1\nfig1 'Cap'\n")
    assert "```transcript-output inner_test=1\nhello\n```" in text


def test_label_falls_back_to_the_outer_code_representation():
    output = label({"answer": "<42>"}, "result")
    assert output.serialize() == (
        "result ''\n```transcript-output code=1\n{'answer': '<42>'}\n```\n"
    )

    html = parse(fence_source(output), "r.tmd.py").render_html()
    assert '<pre class="doc-text"><samp class="doc-out">' in html
    assert "{&#x27;answer&#x27;: &#x27;&lt;42&gt;&#x27;}" in html
    assert "<42>" not in html
    assert 'data-tmd-renderer="code"' in html


def test_label_pins_the_inner_version(monkeypatch):
    register(monkeypatch)
    output = label(Inner("hello"), "fig1")
    data = output.serialize().replace("inner_test=1", "inner_test=2")
    with pytest.raises(ValueError, match="renderer output after the header"):
        type(output).to_html(slot_of(data))


def test_label_preserves_its_rendered_child(monkeypatch):
    register(monkeypatch)
    output = label(Inner("hello"), "fig1")
    rendered = type(output).to_html(slot_of(output.serialize()))
    assert isinstance(rendered, Rendered)
    assert len(rendered.children) == 1
    assert rendered.children[0].renderer is Inner


def test_repeated_label_reuses_the_cached_inner_output(monkeypatch, label_cache):
    calls = 0

    class CountingInner(Inner):
        name = "cached_counting_inner_test"

        @classmethod
        def to_html(cls, slot):
            nonlocal calls
            calls += 1
            return super().to_html(slot)

    monkeypatch.setitem(RENDERERS, CountingInner.name, CountingInner)
    output = label(CountingInner("hello"), "fig1")

    html = parse(fence_source(output) + fence_source(output), "r.tmd.py").render_html()

    assert calls == 1
    assert html.count('<span class="inner-test">hello</span>') == 2


def test_markdown_can_reference_a_label(monkeypatch):
    register(monkeypatch)
    source = fence_source(label(Inner("hello"), "fig1", "Result"))
    source = source.replace("section", "See [the result](#fig1).")
    html = parse(source, "r.tmd.py").render_html()
    assert '<div class="doc-md" data-tmd-span=' in html
    assert '<a href="#fig1">the result</a>' not in html
    assert '<figure class="transcript-label" id="fig1">' in html


def test_markdown_can_jump_to_a_labelled_heading():
    output = label(markdown("## Result title\n\nDetails."), "result-title")
    source = fence_source(output).replace(
        "section", "Jump to [the result title](#result-title)."
    )
    html = parse(source, "r.tmd.py").render_html()
    assert '<div class="doc-md" data-tmd-span=' in html
    assert '<a href="#result-title">the result title</a>' not in html
    assert '<figure class="transcript-label" id="result-title">' in html
    figure = html.split('<figure class="transcript-label" id="result-title">', 1)[1]
    assert 'data-tmd-renderer="markdown"' in figure.split("</figure>", 1)[0]
    assert "<h2" not in html  # the heading is rendered in the browser


def test_caption_round_trips_from_repr_to_string(monkeypatch):
    register(monkeypatch)
    caption = "first line\n'quoted' & <tag>"
    output = label(Inner("hello"), "fig1", caption=caption)
    assert repr(caption) in output.serialize()

    html = parse(fence_source(output), "r.tmd.py").render_html()
    expected = (
        "<figcaption>first line\n&#x27;quoted&#x27; &amp; &lt;tag&gt;</figcaption>"
    )
    assert expected in html
    assert repr(caption) not in html


def test_nested_labels_assign_distinct_report_ids(monkeypatch):
    register(monkeypatch)
    output = label(label(Inner("deep"), "inner1"), "outer1")
    html = parse(fence_source(output), "r.tmd.py").render_html()
    assert html.count('data-tmd-report="') == 3
    assert html.count('data-tmd-renderer="label"') == 2
    assert 'data-tmd-renderer="inner_test"' in html
    assert 'id="outer1"' in html and 'id="inner1"' in html


def test_identical_label_is_rendered_again_as_a_reference_to_the_first(
    monkeypatch, label_cache
):
    register(monkeypatch)
    output = label(Inner("hello"), "fig1", "Result")
    source = fence_source(output)
    source = source + fence_source(output)

    html = parse(source, "r.tmd.py").render_html()

    assert html.count('<span class="inner-test">hello</span>') == 2
    assert html.count('id="fig1"') == 1
    assert 'data-tmd-label="fig1"' in html
    assert 'data-tmd-label-occurrence="1"' in html
    assert '<a href="#fig1">↩</a>' in html


def test_identical_label_without_caption_gets_a_repeat_caption(
    monkeypatch, label_cache
):
    register(monkeypatch)
    output = label(Inner("hello"), "fig1")
    html = parse(fence_source(output) + fence_source(output), "r.tmd.py").render_html()

    assert '<figcaption><span class="transcript-label-repeat-note">' in html


def test_same_label_id_with_different_content_is_renamed(
    monkeypatch, label_cache, caplog
):
    register(monkeypatch)
    first = label(Inner("first"), "fig1")
    second = label(Inner("second"), "fig1")
    source = fence_source(first) + fence_source(second) + fence_source(second)

    html = parse(source, "r.tmd.py").render_html()

    assert html.count('id="fig1"') == 1
    assert html.count('id="fig1.1"') == 1
    assert 'data-tmd-label="fig1.1"' in html
    assert "duplicate 1 of label fig1" in html
    assert caplog.messages == ["label 'fig1' has different content; using 'fig1.1'"]


def test_cli_warns_and_renames_different_content_with_the_same_label(tmp_path, caplog):
    first = label(markdown("first"), "result")
    second = label(markdown("second"), "result")
    archive = tmp_path / "duplicate.tmd.py"
    target = tmp_path / "duplicate.html"
    archive.write_text(fence_source(first) + fence_source(second), encoding="utf-8")

    assert tmd2html(archive, target) == 0

    html = target.read_text(encoding="utf-8")
    assert 'id="result"' in html
    assert 'id="result.1"' in html
    assert "duplicate 1 of label result" in html
    assert caplog.messages == ["label 'result' has different content; using 'result.1'"]


def test_label_rejects_invalid_input():
    with pytest.raises(ValueError, match="valid transcript id"):
        label(Inner(), "1 bad id")
    with pytest.raises(TypeError, match="caption"):
        label(Inner(), "fig1", caption=3)  # type: ignore[arg-type]
