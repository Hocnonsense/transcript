"""Render recorded documents as HTML without executing their Python code."""

import base64
import binascii
import gzip
import json
import re
import struct
import textwrap
from collections.abc import Callable
from hashlib import sha256
from html import escape

from .output import RecordedOutput, split_output
from .parse import AstDocument
from .renderers import get

STYLE = """
:root { color-scheme: light dark; }
body { max-width: 860px; margin: 3rem auto; padding: 0 1.25rem 0 3rem;
       font: 17px/1.65 system-ui, sans-serif; }
h1, h2, h3 { line-height: 1.25; }
a { color: #3984c6; }
pre { padding: 1rem; overflow-x: auto; border: 1px solid #8885;
      border-radius: .4rem; line-height: 1.5; }
code { font-family: ui-monospace, monospace; font-size: .9em; }
.module-docstring { display: flow-root; }
.doctest { margin: .3rem 0; }
.doctest-code { margin: 0; padding: 0; border-left: 3px solid #3984c6;
                font: .9em/1.5 ui-monospace, monospace; }
.doc-code, .doc-out { display: block; min-width: fit-content;
                      font: inherit; padding: 0 1rem; }
.doc-code { padding-top: .65rem; background: #f1f5f9; color: #172033; }
.doc-out { min-width: 0; padding-bottom: .65rem; }
.doc-code + .doc-out { padding-top: .35rem; }
.doc-code:only-child { padding-bottom: .65rem; }
.doc-out:only-child { padding-top: .65rem; }
.snakedone-report { margin: .5rem 0 1rem; border: 1px solid #8885;
                    border-radius: .4rem; overflow: hidden; }
.doc-text { margin: 0; padding: 0; border: 0; border-radius: 0;
            font: inherit; }
@media (prefers-color-scheme: dark) {
  .doc-code { background: #202b3b; color: #e5eaf1; }
}
.script-block { position: relative; margin: 0; padding: 0; border: 0; }
.script-block:not([open]) { height: 0; }
.script-toggle { position: absolute; left: -2.25rem; top: 0;
                 width: 1.75rem; height: 1.75rem; display: grid;
                 place-items: center; cursor: pointer; list-style: none;
                 color: #3984c6; border-radius: .25rem; line-height: 1;
                 font: 700 .8rem/1 ui-monospace, monospace; }
.script-toggle::-webkit-details-marker { display: none; }
.script-toggle:hover, .script-block[open] > .script-toggle { background: #3984c622; }
.script-toggle:focus-visible { outline: 2px solid #3984c6; outline-offset: 2px; }
.script-block[open] { display: flow-root; }
.script-block[open] > .script-toggle {
  position: sticky; top: .5rem; left: auto; z-index: 1;
  margin-left: -2.25rem; margin-bottom: -1.75rem;
}
.script-code { margin: 0 0 1.5rem; }
img { max-width: 100%; height: auto; }
main img { display: block; margin: .35rem auto; max-height: 50vh;
           object-fit: contain; cursor: zoom-in; }
.recorded-image { width: min(100%, calc(50vh * var(--image-ratio))); }
main img.image-expanded { width: 100%; max-height: none; cursor: zoom-out; }
main img:focus-visible { outline: 2px solid #3984c6; outline-offset: 2px; }
blockquote { margin-left: 0; padding-left: 1rem; border-left: 3px solid #8885; }
table { border-collapse: collapse; }
th, td { border: 1px solid #8885; padding: .35rem .7rem; }
@media print {
  body { max-width: none; margin: 0; padding: 0; }
  .script-toggle { display: none !important; }
}
"""

IMAGE_SCRIPT = """
document.querySelectorAll('main img').forEach(image => {
  image.tabIndex = 0;
  image.setAttribute('role', 'button');
  image.setAttribute('aria-pressed', 'false');
  image.title = 'Click to expand to text width';
  function toggleImage() {
    const expanded = image.classList.toggle('image-expanded');
    image.setAttribute('aria-pressed', String(expanded));
    image.title = expanded
      ? 'Click to restore preview' : 'Click to expand to text width';
  }
  image.addEventListener('click', toggleImage);
  image.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleImage();
    }
  });
});
"""


def _png_image(line: str) -> tuple[str, int, int] | None:
    """Recognize a PNG data URI
    return its URI, width, and height."""
    uri = line.strip()
    if uri.startswith("![](") and uri.endswith(")"):
        uri = uri[4:-1]
    prefix = "data:image/png;base64,"
    if not uri.startswith(prefix):
        return None
    try:
        payload = base64.b64decode(uri[len(prefix) :], validate=True)
    except ValueError, binascii.Error:
        return None
    if (
        len(payload) < 33
        or not payload.startswith(b"\x89PNG\r\n\x1a\n")
        or payload[12:16] != b"IHDR"
    ):
        return None
    width, height = struct.unpack(">II", payload[16:24])
    return (uri, width, height) if width and height else None


Report = tuple[str, dict[str, tuple[str, bytes]]]


def _output_html(
    code_html: str,
    output: str,
    reports: list[Report],
    report_cache: dict[bytes, dict[str, tuple[str, bytes]]],
):
    parts: list[str] = []
    blocks: list[str] = []
    code_block = '<code class="doc-code">' + code_html.removesuffix("\n") + "</code>"

    def flush_text():
        nonlocal code_block
        output_block = (
            '<samp class="doc-out">' + "".join(parts) + "</samp>" if parts else ""
        )
        if code_block or output_block:
            blocks.append(
                '<pre class="doc-text">' + code_block + output_block + "</pre>"
            )
        parts.clear()
        code_block = ""

    for chunk in split_output(output):
        if isinstance(chunk, RecordedOutput):
            flush_text()
            renderer = get(chunk.renderer)
            assert renderer is not None  # split_output only yields known renderers
            index = len(reports)
            key = sha256(chunk.to_text().encode()).digest()
            if key not in report_cache:
                report_cache[key] = renderer.build(chunk)
            reports.append((chunk.renderer, report_cache[key]))
            blocks.append(
                '<div class="doc-out"><div class="snakedone-report"'
                f' data-snakedone-report="report-{index}"'
                f' data-snakedone-renderer="{escape(chunk.renderer, quote=True)}"'
                "></div></div>"
            )
            continue
        for line in chunk.splitlines(keepends=True):
            png = _png_image(line)
            if png is None:
                parts.append(escape(line))
            else:
                uri, width, height = png
                parts.append(
                    f'<img class="recorded-image" src="{escape(uri, quote=True)}"'
                    f' width="{width}" height="{height}"'
                    f' style="--image-ratio: {width / height}"'
                    f' alt="Recorded PNG ({width} × {height} pixels)">'
                )
    if blocks:
        flush_text()
        return '<div class="doctest-code">' + "".join(blocks) + "</div>"
    output_block = (
        '<samp class="doc-out">' + "".join(parts) + "</samp>" if parts else ""
    )
    return '<pre class="doctest-code">' + code_block + output_block + "</pre>"


def _reports_payload(reports: list[Report]) -> str:
    """Encode report files so they cannot terminate the surrounding script.

    Identical files (for example the shared Datavzrd bundle) are stored once.
    """
    pool: dict[str, dict[str, str | bool]] = {}
    registry: dict[str, dict[str, str]] = {}
    for index, (_, files) in enumerate(reports):
        entry: dict[str, str] = {}
        for name, (mime, data) in files.items():
            digest = sha256(mime.encode() + b"\0" + data).hexdigest()
            if digest not in pool:
                compressed = gzip.compress(data, compresslevel=9, mtime=0)
                payload = compressed if len(compressed) < len(data) else data
                pool[digest] = {
                    "mime": mime,
                    "gzip": payload is compressed,
                    "content": base64.b64encode(payload).decode("ascii"),
                }
            entry[name] = digest
        registry[f"report-{index}"] = entry
    encoded = json.dumps({"pool": pool, "reports": registry}, sort_keys=True)
    return encoded.replace("<", "\\u003c").replace(">", "\\u003e")


def _script_html(source: str, highlight_python: Callable[[str], str]):
    """Hide the source code of a script block behind a toggle button in HTML."""
    # Semicolons between adjacent document expressions are only separators.
    if not source.strip(" \t\r\n\f;"):
        return ""
    return (
        '<details class="script-block">'
        '<summary class="script-toggle" aria-label="Toggle script block"'
        ' title="Show or hide script"><span aria-hidden="true">&lt;/&gt;</span>'
        '</summary><pre class="script-code"><code class="language-python">'
        + highlight_python(source.strip("\r\n")).removesuffix("\n")
        + "</code></pre></details>"
    )


def get_position(text: str):
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def position(line: int, column: int):
        # AST columns use UTF-8 bytes, whereas source slicing uses characters.
        return offsets[line - 1] + len(lines[line - 1].encode()[:column].decode())

    return position


def render(document: AstDocument, *, title: str = "snakedone document"):
    try:
        from markdown_it import MarkdownIt
        from pygments import highlight, lexers
        from pygments.formatters import HtmlFormatter
    except ImportError as error:
        raise RuntimeError(
            'HTML export requires: pip install "snakedone[html]"'
        ) from error

    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    lexer = lexers.PythonLexer(stripnl=False, ensurenl=False)
    formatter = HtmlFormatter(nowrap=True, style="default")
    selectors = ":is(.doc-code, .script-code)"
    highlight_style = formatter.get_style_defs(selectors)
    dark_style = HtmlFormatter(style="native").get_style_defs(selectors)

    def highlight_python(source: str) -> str:
        return highlight(source, lexer, formatter)

    position = get_position(document.source)
    parts: list[str] = []
    reports: list[Report] = []
    report_cache: dict[bytes, dict[str, tuple[str, bytes]]] = {}

    cursor = 0
    for block in document.blocks:
        # Use the entire expression span, including any grouping parentheses.
        node = block.node
        assert node.end_lineno is not None and node.end_col_offset is not None
        start = position(node.lineno, node.col_offset)
        end = position(node.end_lineno, node.end_col_offset)
        script = _script_html(document.source[cursor:start], highlight_python)
        if script:
            parts.append(script)
        cursor = end
        parts.append('<section class="module-docstring">')
        prose_end = block.codes[0].source_start if block.codes else len(block.content)
        prose = textwrap.dedent(block.content[:prose_end]).strip()
        if prose:
            parts.append('<div class="doc-md">' + markdown.render(prose) + "</div>")
        for index, record in enumerate(block.codes):
            end = (
                block.codes[index + 1].source_start
                if index + 1 < len(block.codes)
                else len(block.content)
            )
            output = block.content[record.source_end : end]
            # Remove only the archive's structural indentation and prompt escape.
            if record.indent:
                output = "".join(
                    line.removeprefix(record.indent)
                    for line in output.splitlines(keepends=True)
                )
            output = re.sub(r"^([^\S\n]*)\\>>> ", r"\1>>> ", output, flags=re.MULTILINE)
            parts.append(
                '<section class="doctest">'
                + _output_html(
                    highlight_python(record.source), output, reports, report_cache
                )
                + "</section>"
            )
        parts.append("</section>")

    script = _script_html(document.source[cursor:], highlight_python)
    if script:
        parts.append(script)
    body = "\n".join(parts)
    image_hash = base64.b64encode(sha256(IMAGE_SCRIPT.encode()).digest()).decode()
    sources = [f"'sha256-{image_hash}'"]
    image_src = "data:"
    font_src = ""
    frame_src = ""
    tail = ""
    if reports:
        runtimes: list[str] = []
        seen: set[str] = set()
        for renderer_name, _ in reports:
            if renderer_name in seen:
                continue
            seen.add(renderer_name)
            renderer = get(renderer_name)
            assert renderer is not None
            source = renderer.runtime()
            if not source:
                raise RuntimeError(
                    f"Renderer {renderer_name!r} has no offline HTML runtime"
                )
            runtimes.append(source)
            digest = base64.b64encode(sha256(source.encode()).digest()).decode()
            sources.append(f"'sha256-{digest}'")
        sources.extend(["blob:", "data:"])
        # Vega evaluates plot expressions, which needs string compilation.
        sources.append("'unsafe-eval'")
        image_src = "data: blob:"
        font_src = " font-src data: blob:;"
        frame_src = " frame-src 'self' data: blob:;"
        tail = (
            '<script id="snakedone-reports" type="application/json">'
            + _reports_payload(reports)
            + "</script>\n"
            + "\n".join(f"<script>{source}</script>" for source in runtimes)
        )
    script_src = " ".join(sources)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
 content="default-src 'none'; style-src 'unsafe-inline'; img-src {image_src};{font_src}
 script-src {script_src};{frame_src} base-uri 'none'; form-action 'none'">
<title>{escape(title)}</title>
<style>
{highlight_style}
@media (prefers-color-scheme: dark) {{ {dark_style} }}
{STYLE}
</style>
</head>
<body><main>
{body}
</main>
<script>{IMAGE_SCRIPT}</script>
{tail}
</body>
</html>
"""
