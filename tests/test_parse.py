"""Report block parsing, slot reconstruction, and marker placement."""

from transcript.document import parse


def test_if_and_with_are_equivalent():
    if_source = 'if "transcript.md":\n    """md"""\n    value\n'
    with_source = (
        "import transcript\n\n"
        'with transcript.md:  # transcript.md\n    """md"""\n    value\n'
    )
    if_doc = parse(if_source, "a.py").blocks
    with_doc = parse(with_source, "b.py").blocks
    assert len(if_doc) == len(with_doc) == 1
    if_document = parse(if_source, "a.py")
    with_document = parse(with_source, "b.py")
    if_markdown = if_document.blocks[0].markdown
    with_markdown = with_document.blocks[0].markdown
    assert if_markdown is not None and with_markdown is not None
    assert if_document.source[slice(*if_markdown)] == "md"
    assert with_document.source[slice(*with_markdown)] == "md"
    assert len(if_doc[0].statements) == 1
    assert len(with_doc[0].statements) == 1


def test_markdown_and_slots_are_separated():
    source = (
        'if "transcript.md":\n    """md"""\n    first\n'
        '    """\n    one\n    """\n    second\n'
    )
    block = parse(source, "slots.py").blocks[0]
    markdown = block.markdown
    assert markdown is not None
    assert parse(source, "slots.py").source[slice(*markdown)] == "md"
    assert [source[s.start : s.end] for s in block.statements] == ["first", "second"]
    first_slot = block.statements[0].slot
    assert first_slot is not None
    assert first_slot.value == "one\n"
    assert block.statements[1].slot is None


def test_render_removes_empty_slot():
    source = 'if "transcript.md":\n    value = 1\n    """\n    old\n    """\n'
    document = parse(source, "empty.py")
    generated = document.render_tmd(document.blocks, [[""]])
    assert "old" not in generated
