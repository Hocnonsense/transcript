"""Portable bitmap renderer snapshots."""

import base64
import json

import pytest

from transcript import bitmap, image
from transcript.output import RecordedOutput, split_output

from ..conftest import slot_of


def snapshot(output):
    lines = output.to_tmd().splitlines()
    return json.loads("\n".join(lines[1:-1]))


def test_bitmap_file_round_trips(tmp_path):
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1Pe"
        "AAAADElEQVR4nGNQcGgAAAFkAOHHE8n2AAAAAElFTkSuQmCC"
    )
    path = tmp_path / "pixel.png"
    path.write_bytes(png)

    output = bitmap(path)
    data = snapshot(output)
    restored = list(split_output(slot_of(output.to_tmd())))

    assert data == {
        "alt": "pixel.png",
        "data": base64.b64encode(png).decode("ascii"),
        "mime": "image/png",
    }
    assert len(restored) == 1 and isinstance(restored[0], RecordedOutput)
    assert 'class="transcript-bitmap"' in restored[0].rendered.text
    assert 'width="1" height="1" style="--image-ratio:1.0"' in restored[0].rendered.text


def test_image_accepts_static_bitmaps():
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1Pe"
        "AAAADElEQVR4nGNQcGgAAAFkAOHHE8n2AAAAAElFTkSuQmCC"
    )
    assert snapshot(image(png, alt="pixel")) == snapshot(bitmap(png, alt="pixel"))


def test_image_accepts_plt_plot_result():
    plt = pytest.importorskip("matplotlib.pyplot")
    figure = plt.figure()
    try:
        output = image(plt.plot([0, 1], [0, 1]), alt="rising line")
    finally:
        plt.close(figure)

    data = snapshot(output)
    assert data["mime"] == "image/png"
    assert data["alt"] == "rising line"
    assert base64.b64decode(data["data"]).startswith(b"\x89PNG\r\n\x1a\n")


def test_bitmap_rejects_non_bitmap_file(tmp_path):
    path = tmp_path / "image.svg"
    path.write_text("<svg/>", encoding="utf-8")
    with pytest.raises(ValueError, match="supports PNG"):
        bitmap(path)
