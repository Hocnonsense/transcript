"""Archive protocol boundaries and snapshot execution."""

import json
import logging

import pytest

from transcript import datavzrd, markdown
from transcript.output import RecordedOutput, Rendered, Renderer, split_output
from transcript.renderers import RENDERERS

from .conftest import slot_of


class Frame:
    def write_csv(self, **kwargs):
        return "value\n1\n"


def snapshot(config=None):
    return datavzrd(Frame(), config)


def body(text: str) -> dict:
    lines = text.splitlines(keepends=True)
    assert lines[0].startswith("```transcript-output")
    return json.loads("".join(lines[1:-1]).removesuffix("\n"))


def fence_text(renderer: str, data, constraint: str = "") -> str:
    return f"```transcript-output {renderer}{constraint}\n{json.dumps(data)}\n```\n"


def rendered(text: str):
    chunks = list(split_output(slot_of(text)))
    assert len(chunks) == 1 and isinstance(chunks[0], RecordedOutput)
    return chunks[0]


def test_markdown_renderer_round_trip_and_uses_longer_outer_fence():
    output = markdown("# Result\n\n```python\nanswer = 42\n```")
    archived = output.to_tmd()
    assert archived.startswith("````transcript-output markdown=1\n")
    restored = rendered(archived)
    assert restored.renderer.name == "markdown"
    # The server keeps the source only; the browser renders it from the island.
    assert restored.rendered.text == ""
    assert restored.rendered.boxed is False


def test_markdown_renderer_requires_string_content():
    with pytest.raises(TypeError, match="must be a string"):
        markdown(42)  # type: ignore[arg-type]


def test_mixed_stream_preserves_unknown_and_incompatible_blocks():
    recorded = snapshot()
    unknown_renderer = fence_text("future", {})
    unsupported_version = fence_text("datavzrd", {}, constraint=">3")
    before = "before\n" + unknown_renderer + unsupported_version
    chunks = list(split_output(slot_of(before + recorded.to_tmd() + "after\n")))
    assert chunks[0] == "before\n"
    assert chunks[1] == unknown_renderer
    assert chunks[2] == unsupported_version
    assert isinstance(chunks[3], RecordedOutput)
    assert chunks[4] == "after\n"


def test_plain_text_is_yielded_before_the_following_renderer_is_validated(
    monkeypatch,
):
    calls = 0

    class LazyRenderer(Renderer):
        name = "lazy_test"

        @classmethod
        def to_html(cls, slot):
            nonlocal calls
            calls += 1
            return Rendered(slot.value, {})

    monkeypatch.setitem(RENDERERS, LazyRenderer.name, LazyRenderer)
    chunks = split_output(
        slot_of("header\n```transcript-output lazy_test\nbody\n```\n")
    )

    assert next(chunks) == "header\n"
    assert calls == 0
    assert isinstance(next(chunks), RecordedOutput)
    assert calls == 1


@pytest.mark.parametrize(
    "text,message",
    [
        ("```transcript-output datavzrd=1\n{}\n", "Incomplete"),
        ("```transcript-output datavzrd=1\ninvalid\n```\n", "JSON mapping"),
        ("```transcript-output datavzrd=1\n{}\n```\n", "CSV string content"),
        (fence_text("datavzrd", None), "mapping"),
        (
            fence_text("datavzrd", {"csv": "value\n1\n", "config": []}),
            "config must be a mapping",
        ),
        (fence_text("datavzrd", {}), "CSV string content"),
        (fence_text("datavzrd", {"csv": 123, "config": {}}), "CSV string content"),
    ],
)
def test_invalid_archive_blocks_stay_readable_text(caplog, text: str, message: str):
    with caplog.at_level(logging.WARNING):
        assert list(split_output(slot_of(text))) == [text]
    assert message in caplog.text


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "a/b",
        "a\\b",
        "a?b",
        "a#b",
        "%2e%2e",
        "foo:bar",
        "a\nb",
        "a\x7fb",
        "a\x85b",
        " leading",
    ],
)
def test_view_names_cannot_change_native_url_resolution(name: str):
    with pytest.raises(ValueError, match="plain directory names"):
        snapshot({"views": {name: {"dataset": "data"}}})


def test_internal_spaces_unicode_and_option_like_names_remain_valid():
    output = snapshot(
        {
            "views": {
                "my 表格": {
                    "dataset": "data",
                    "render-table": {"columns": {"value": {"display-mode": "detail"}}},
                },
                "render-plot": {"dataset": "data"},
            },
            "default-view": "my 表格",
        }
    )
    assert isinstance(rendered(output.to_tmd()), RecordedOutput)


@pytest.mark.parametrize("data", [None, "text", [1, "two"], {"key": True}])
def test_renderer_defines_its_data_structure(monkeypatch, data):
    text = json.dumps(data)

    class CustomRenderer(Renderer):
        name = "custom"

        def __init__(self, py_obj):
            self.obj = py_obj

        def serialize(self):
            return json.dumps(self.obj)

        @classmethod
        def to_html(cls, slot):
            return Rendered(f"<custom>{slot.value}</custom>", {})

        @classmethod
        def runtime(cls):
            return None

    monkeypatch.setitem(RENDERERS, "custom", CustomRenderer)
    output = CustomRenderer(data)
    assert output.to_tmd().startswith("```transcript-output custom\n")
    restored = rendered(output.to_tmd())
    assert restored.rendered.text == f"<custom>{text}</custom>"


def test_closing_fence_must_repeat_the_opening_indent(caplog):
    text = "```transcript-output future=1\nbody\n    ```\n"
    with caplog.at_level(logging.WARNING):
        assert list(split_output(slot_of(text))) == [text]
    assert "Incomplete" in caplog.text


def test_indented_fence_with_matching_close_is_recognized():
    text = "    ```transcript-output code=1\n    value\n    ```\n"
    chunks = list(split_output(slot_of(text)))
    assert len(chunks) == 1 and isinstance(chunks[0], RecordedOutput)
