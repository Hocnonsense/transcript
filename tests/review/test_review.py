"""Review records: coordinate grammar, the trailing block, and migration."""

import json
import re
from pathlib import Path

import pytest

from transcript.document import parse
from transcript.review._block import (
    REVIEW_MARKER,
    ReviewBlock,
    ReviewSource,
    migrated_block,
    render_block,
)
from transcript.review._records import ReviewRecord, SourceRecord
from transcript.review._span import Span
from transcript.tmd import body_hash

from ..conftest import run_cli

STAMP = "2026-09-24T12:00:00.000Z"


def review_record(time, at, **extra):
    """Build a review record like the frontend would when it exports the page."""
    return ReviewRecord(time=time, at=str(at), **extra)


def test_span_grammar_round_trips():
    for text in ("L5", "L5C3+1", "L5C3+4", "L7-L9", "L7-L9C1", "L5C3+0", "L1C1+0"):
        assert str(Span.parse(text)) == text
    assert str(Span.parse("L5C3")) == "L5C3+1"
    assert str(Span.parse("L7C1-L9C1")) == "L7-L9C1"
    with pytest.raises(ValueError):
        Span.parse("5")


def test_review_block_is_located_only_as_the_last_statement():
    trailing = (
        f'if "transcript.md":\n    """md"""\n    1\n\n'
        f'if "{REVIEW_MARKER}":\n    """[]"""\n'
    )
    document = parse(trailing, "r.tmd.py")
    assert document.review is not None
    assert document.review.load().records == []
    assert document.source_without_review == trailing[: document.review.start]

    leading = (
        f'if "{REVIEW_MARKER}":\n    """[]"""\n\n'
        'if "transcript.md":\n    """md"""\n    1\n'
    )
    assert parse(leading, "r.tmd.py").review is None

    source = (
        f'if "transcript.md":\n    """md"""\n    1\n\n'
        f'if "{REVIEW_MARKER}":\n    1 + 1\n'
    )
    assert parse(source, "r.tmd.py").review is None


def test_a_damaged_block_is_dropped_not_frozen():
    block = ReviewBlock(0, 0, "{not json")
    with pytest.warns(UserWarning):
        records = block.load().records
    assert records == []
    assert migrated_block("a\n", ReviewSource("a\n", records)) == ""


def test_an_invalid_record_drops_the_whole_block():
    value = json.dumps(
        [
            {"type": "source", "at": "L2"},
            {"type": "review", "at": "L2"},
            {"type": "review", "time": STAMP, "at": "L2", "comment": "ok"},
        ]
    )
    block = ReviewBlock(0, 0, value)
    with pytest.warns(UserWarning):
        assert block.load().records == []


def test_render_block_escapes_text_that_closes_the_literal():
    records = [
        SourceRecord(
            at="L2",
            source='    """\n    1\n    """',
            before="2026-09-24T12:00:00.000Z",
        )
    ]
    source = 'if "transcript.md":\n    """md"""\n\n' + render_block(records)
    document = parse(source, "escaped.tmd.py")
    assert document.review is not None
    assert document.review.load().records == records


ARCHIVE = (
    "value = 7\n"
    "\n"
    'if "transcript.md":\n'
    '    """\n'
    "    # Analysis\n"
    '    """\n'
    "    value\n"
    "\n"
    'if "transcript.review":\n'
    '    """[\n'
    "    {\n"
    '      "type": "source",\n'
    '      "at": "L7",\n'
    '      "cover": "L7@2026-09-24T09:00:00.000Z"\n'
    "    },\n"
    "    {\n"
    '      "type": "review",\n'
    '      "time": "2026-09-24T09:30:00.000Z",\n'
    '      "at": "L7",\n'
    '      "comment": "check"\n'
    "    }\n"
    '    ]"""\n'
)


def test_overwrite_preserves_an_unchanged_review_block(tmp_path: Path):
    archive = tmp_path / "doc.tmd.py"
    archive.write_text(ARCHIVE, encoding="utf-8")
    assert run_cli(archive, "--overwrite").returncode == 0
    document = parse(archive.read_text(encoding="utf-8"), str(archive))
    assert document.review is not None
    records = document.review.load().records
    reviews = [r for r in records if isinstance(r, ReviewRecord)]
    assert len(reviews) == 1
    assert reviews[0].at == "L7"
    assert any(isinstance(r, SourceRecord) for r in records)


def test_html_extracts_back_to_the_same_archive(tmp_path: Path):
    archive = tmp_path / "doc.tmd.py"
    archive.write_text(ARCHIVE, encoding="utf-8")
    page = tmp_path / "doc.html"
    assert run_cli(archive, "-o", str(page), "--overwrite").returncode == 0
    extracted = tmp_path / "copy.tmd.py"
    assert run_cli(page, "-o", str(extracted)).returncode == 0

    original = parse(archive.read_text(encoding="utf-8"), str(archive))
    copy = parse(extracted.read_text(encoding="utf-8"), str(extracted))
    assert copy.source_without_review == original.source_without_review
    assert original.review is not None
    assert copy.review is not None
    assert copy.review.load().records == original.review.load().records
    # The source island carries no review block, so its body is the archive.
    page_text = page.read_text(encoding="utf-8")
    island = re.search(
        r'<script type="application/json" id="transcript-source">(.*?)</script>',
        page_text,
        re.S,
    )
    assert island is not None
    assert "transcript.review" not in json.loads(island.group(1))


def test_html_embeds_the_review_island_and_sidebar():
    html = parse(ARCHIVE, "doc.tmd.py").render_html(title="doc")
    match = re.search(
        r'<script id="transcript-reviews" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    body = ARCHIVE[: ARCHIVE.index('if "transcript.review')]
    assert payload["hash"] == body_hash(body)
    reviews = [r for r in payload["records"] if r["type"] == "review"]
    assert len(reviews) == 1
    assert "id" not in reviews[0]
    assert "transcript-reviews" in html
    # The trailing block itself is not rendered as a script region.
    main = html.split("<main>", 1)[1].split("</main>", 1)[0]
    assert "transcript.review" not in main


CHANGING = (
    "import json\n"
    "import pathlib\n"
    "\n"
    'data = json.loads(pathlib.Path(__file__).with_name("data.json").read_text())\n'
    "\n"
    'if "transcript.md":\n'
    '    """\n'
    "    # Analysis\n"
    '    """\n'
    '    data["value"]\n'
)


def test_overwrite_bounds_the_source_of_a_changed_output(tmp_path: Path):
    (tmp_path / "data.json").write_text('{"value": 1}', encoding="utf-8")
    archive = tmp_path / "doc.tmd.py"
    archive.write_text(CHANGING, encoding="utf-8")
    assert run_cli(archive, "--overwrite").returncode == 0

    document = parse(archive.read_text(encoding="utf-8"), str(archive))
    slot = document.blocks[0].statements[0].slot
    assert slot is not None
    source = archive.read_text(encoding="utf-8")
    span = Span(
        source[: slot.literal[0]].count("\n"),
        0,
        source[: slot.literal[1] - 1].count("\n") + 1,
        0,
    )
    records = [
        SourceRecord(at=str(span)),
        review_record("2026-09-24T09:00:00.000Z", span, comment="watch this value"),
    ]
    archive.write_text(
        source.rstrip("\n") + "\n\n" + render_block(records), encoding="utf-8"
    )

    (tmp_path / "data.json").write_text('{"value": 2}', encoding="utf-8")
    assert run_cli(archive, "--overwrite").returncode == 0

    rebuilt = parse(archive.read_text(encoding="utf-8"), str(archive))
    assert rebuilt.review is not None
    migrated = rebuilt.review.load().records
    frozen = [
        record
        for record in migrated
        if isinstance(record, SourceRecord) and record.before is not None
    ]
    assert len(frozen) == 1
    assert frozen[0].source is not None
    assert any(
        isinstance(record, SourceRecord) and record.before is None
        for record in migrated
    )


def hashed_archive(body: str, records):
    """An archive whose review block records the hash of *body*."""
    body = body.rstrip("\n") + "\n"
    return body + "\n" + render_block(records, hash=body_hash(body)) + "\n"


TRANSFER = (
    "value = 1\n\n"
    'if "transcript.md":\n'
    '    """\n'
    "    # Title\n\n"
    "    Line one.\n"
    "    Line two.\n"
    '    """\n'
    "    value\n"
)


def test_py_overwrite_preserves_the_existing_archive_annotations(tmp_path: Path):
    path = tmp_path / "doc.py"
    path.write_text(TRANSFER, encoding="utf-8")
    assert run_cli(path, "--overwrite").returncode == 0

    archive = tmp_path / "doc.tmd.py"
    before = archive.read_text(encoding="utf-8")
    line = next(
        index
        for index, text in enumerate(before.splitlines(), 1)
        if text == "    Line two."
    )
    records = [
        SourceRecord(at=str(Span(line - 1, 0, line, 0))),
        review_record(
            "2026-09-24T09:00:00.000Z", Span(line - 1, 0, line, 0), comment="two"
        ),
    ]
    archive.write_text(
        before.rstrip("\n") + "\n\n" + render_block(records) + "\n", encoding="utf-8"
    )

    edited = path.read_text(encoding="utf-8").replace(
        "    Line one.", "    New line.\n    Line one."
    )
    path.write_text(edited, encoding="utf-8")
    assert run_cli(path, "--overwrite").returncode == 0

    rebuilt = parse(archive.read_text(encoding="utf-8"), str(archive))
    assert rebuilt.review is not None
    reviews = rebuilt.review.load().reviews
    assert [review.comment for review in reviews] == ["two"]


def test_overwrite_drops_annotations_when_the_archive_body_was_edited(tmp_path: Path):
    path = tmp_path / "doc.py"
    path.write_text(TRANSFER, encoding="utf-8")
    assert run_cli(path, "--overwrite").returncode == 0

    archive = tmp_path / "doc.tmd.py"
    before = archive.read_text(encoding="utf-8")
    line = next(
        index
        for index, text in enumerate(before.splitlines(), 1)
        if text == "    Line two."
    )
    records = [
        SourceRecord(at=str(Span(line - 1, 0, line, 0))),
        review_record(
            "2026-09-24T09:00:00.000Z", Span(line - 1, 0, line, 0), comment="two"
        ),
    ]
    # The block's hash describes the unedited body; editing the body behind its
    # back makes the recorded coordinates untrustworthy.
    archive.write_text(
        hashed_archive(before.rstrip("\n"), records).replace(
            "    Line two.", "    Line 2."
        ),
        encoding="utf-8",
    )

    assert run_cli(archive, "--overwrite").returncode == 0
    assert parse(archive.read_text(encoding="utf-8"), str(archive)).review is None


def transfer_archive(tmp_path: Path):
    """Generate a document and return ``(script, archive, records)``."""
    path = tmp_path / "doc.py"
    path.write_text(TRANSFER, encoding="utf-8")
    assert run_cli(path, "--overwrite").returncode == 0
    archive = tmp_path / "doc.tmd.py"
    before = archive.read_text(encoding="utf-8")
    line = next(
        index
        for index, text in enumerate(before.splitlines(), 1)
        if text == "    Line two."
    )
    records = [
        SourceRecord(at=str(Span(line - 1, 0, line, 0))),
        review_record(
            "2026-09-24T09:00:00.000Z", Span(line - 1, 0, line, 0), comment="two"
        ),
    ]
    return path, archive, records


def test_overwrite_keeps_an_unchanged_hashed_block(tmp_path: Path):
    path, archive, records = transfer_archive(tmp_path)
    before = archive.read_text(encoding="utf-8")
    hashed = hashed_archive(before, records)
    archive.write_text(hashed, encoding="utf-8")

    assert run_cli(archive, "--overwrite").returncode == 0
    assert archive.read_text(encoding="utf-8") == hashed


def test_explicit_previous_with_a_stale_hash_errors(tmp_path: Path):
    path, archive, records = transfer_archive(tmp_path)
    before = archive.read_text(encoding="utf-8")
    stale = hashed_archive(before, records).replace("    Line two.", "    Line 2.")
    previous = tmp_path / "reviewed.tmd.py"
    previous.write_text(stale, encoding="utf-8")

    result = run_cli(path, "--overwrite", "--previous", str(previous))
    assert result.returncode == 2
    assert "hash does not match" in result.stderr
    # Refusing to transfer must not touch the target archive.
    assert archive.read_text(encoding="utf-8") == before


def test_py_overwrite_drops_a_stale_target_block(tmp_path: Path):
    path, archive, records = transfer_archive(tmp_path)
    before = archive.read_text(encoding="utf-8")
    archive.write_text(
        hashed_archive(before, records).replace("    Line two.", "    Line 2."),
        encoding="utf-8",
    )

    # With no explicit --previous the stale target block is dropped, not moved.
    result = run_cli(path, "--overwrite")
    assert result.returncode == 0
    assert "hash mismatch" in result.stderr
    assert parse(archive.read_text(encoding="utf-8"), str(archive)).review is None


def test_explicit_previous_overrides_the_input_block(tmp_path: Path):
    _path, archive, records = transfer_archive(tmp_path)
    body = archive.read_text(encoding="utf-8")
    span = Span.parse(records[1].at)
    stamp = records[1].time
    archive.write_text(
        hashed_archive(
            body,
            [records[0], review_record(stamp, span, comment="own")],
        ),
        encoding="utf-8",
    )
    previous = tmp_path / "prev.tmd.py"
    previous.write_text(
        hashed_archive(
            body,
            [records[0], review_record(stamp, span, comment="given")],
        ),
        encoding="utf-8",
    )

    result = run_cli(archive, "--overwrite", "--previous", str(previous))
    assert result.returncode == 0, result.stderr
    rebuilt = parse(archive.read_text(encoding="utf-8"), str(archive))
    assert rebuilt.review is not None
    assert [review.comment for review in rebuilt.review.load().reviews] == ["given"]


def test_no_own_block_inherits_from_the_existing_target(tmp_path: Path):
    _path, archive, records = transfer_archive(tmp_path)
    body = archive.read_text(encoding="utf-8")
    span = Span.parse(records[1].at)
    out = tmp_path / "out.tmd.py"
    out.write_text(
        hashed_archive(
            body,
            [records[0], review_record(records[1].time, span, comment="kept")],
        ),
        encoding="utf-8",
    )
    plain = tmp_path / "plain.tmd.py"
    plain.write_text(body, encoding="utf-8")

    result = run_cli(plain, "-o", str(out), "--overwrite")
    assert result.returncode == 0, result.stderr
    rebuilt = parse(out.read_text(encoding="utf-8"), str(out))
    assert rebuilt.review is not None
    assert [review.comment for review in rebuilt.review.load().reviews] == ["kept"]


def test_cli_previous_transfers_annotations_from_a_page(tmp_path: Path):
    path = tmp_path / "doc.py"
    path.write_text(TRANSFER, encoding="utf-8")
    assert run_cli(path, "--overwrite").returncode == 0

    archive = tmp_path / "doc.tmd.py"
    before = archive.read_text(encoding="utf-8")
    line = next(
        index
        for index, text in enumerate(before.splitlines(), 1)
        if text == "    Line two."
    )
    records = [
        SourceRecord(at=str(Span(line - 1, 0, line, 0))),
        review_record(
            "2026-09-24T09:00:00.000Z", Span(line - 1, 0, line, 0), comment="two"
        ),
    ]
    archive.write_text(
        before.rstrip("\n") + "\n\n" + render_block(records) + "\n", encoding="utf-8"
    )
    page = tmp_path / "reviewed.html"
    assert run_cli(archive, "-o", str(page)).returncode == 0

    edited = path.read_text(encoding="utf-8").replace(
        "    Line one.", "    New line.\n    Line one."
    )
    path.write_text(edited, encoding="utf-8")
    assert run_cli(path, "--overwrite", "--previous", str(page)).returncode == 0

    rebuilt = parse(archive.read_text(encoding="utf-8"), str(archive))
    assert rebuilt.review is not None
    reviews = rebuilt.review.load().reviews
    assert [review.comment for review in reviews] == ["two"]


def test_html_extract_folds_an_edited_reviews_island(tmp_path: Path):
    archive = tmp_path / "doc.tmd.py"
    archive.write_text(ARCHIVE, encoding="utf-8")
    page = tmp_path / "doc.html"
    assert run_cli(archive, "-o", str(page)).returncode == 0

    text = page.read_text(encoding="utf-8")
    island = re.search(
        r'(<script id="transcript-reviews" type="application/json">)(.*?)(</script>)',
        text,
        re.S,
    )
    assert island is not None
    payload = json.loads(island.group(2))
    payload["records"].append(
        {"type": "review", "at": "L7", "time": STAMP, "comment": "added"}
    )
    page.write_text(
        text[: island.start(2)]
        + json.dumps(payload).replace("<", "\\u003c")
        + text[island.end(2) :],
        encoding="utf-8",
    )

    extracted = tmp_path / "extracted.tmd.py"
    assert run_cli(page, "-o", str(extracted)).returncode == 0
    parsed = parse(extracted.read_text(encoding="utf-8"), str(extracted))
    assert parsed.review is not None
    assert any(review.comment == "added" for review in parsed.review.load().reviews)
