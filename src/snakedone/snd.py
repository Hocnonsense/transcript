"""Update decoded record strings and emit physical multiline literals."""

import ast
import os
import re
import tempfile
import textwrap
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .parse import AstDocument


def render_output(output: str, indent: str):
    processed = re.sub(r"^([^\S\n]*)>>> ", r"\1\\>>> ", output, flags=re.MULTILINE)
    return textwrap.indent(processed, indent)


def render(document: AstDocument, outputs: list[list[str]]):
    edits: list[tuple[int, int, str]] = []
    for block, outputblock in zip(document.blocks, outputs):
        if not block.codes:
            continue
        content_edits: list[tuple[int, int, str]] = []
        for (code, nextcode), output in zip(pairwise(block.codes), outputblock):
            replacement = render_output(output, code.indent)
            content_edits.append((code.source_end, nextcode.source_start, replacement))
        lastcode = block.codes[-1]
        replacement = render_output(outputblock[-1], lastcode.indent)
        content_edits.append((lastcode.source_end, len(block.content), replacement))

        content = block.content
        for start, end, replacement in reversed(content_edits):
            content = content[:start] + replacement + content[end:]
        if block.raw:
            if block.quote in content:
                raise ValueError("output closes a raw document string")
        else:
            # Encode literal backslashes, but leave decoded newlines as newlines.
            # A triple-quoted literal only needs quotes escaped when they would
            # close it, so ordinary JSON and prose stay readable in the archive.
            quote = block.quote[0]
            content = content.replace("\\", "\\\\")
            content = re.sub(
                f"(?:{re.escape(quote)}{{3,}}|{re.escape(quote)}+$)",
                lambda match: match.group().replace(quote, "\\" + quote),
                content,
            )
        literal = block.prefix + block.quote + content + block.quote
        edits.append((block.source_start, block.source_end, literal))

    result = document.source
    for start, end, replacement in reversed(edits):
        result = result[:start] + replacement + result[end:]
    result = result.rstrip("\n") + "\n"
    ast.parse(result)  # Never publish a non-Python archive.
    return result


def write(path: Path, source: str):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(source)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
