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
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .output import RecordedOutput, split_output

if TYPE_CHECKING:
    from .document import AstDocument

STYLE = """
:root { color-scheme: light dark; }
body { max-width: 860px; margin: 3rem auto; padding: 0 1.25rem 0 3rem;
       font: 17px/1.65 system-ui, sans-serif; }
h1, h2, h3 { line-height: 1.25; }
a { color: #3984c6; }
code { font-family: ui-monospace, monospace; font-size: .9em; }
blockquote { margin-left: 0; padding-left: 1rem; border-left: 3px solid #8885; }
table { border-collapse: collapse; }
th, td { border: 1px solid #8885; padding: .35rem .7rem; }

/* bordered boxes */
.script-code, .doctest-code, .snakedone-report {
  border: 1px solid #8885; border-radius: .4rem;
}

/* scripts */
.script-block { position: relative; margin: 0; padding: 0; border: 0; }
.script-block[open] { display: flow-root; }
.script-block:not([open]) { height: 0; }
.script-code { margin: 0 0 1.5rem; padding: 1rem; overflow-x: auto;
               line-height: 1.5; }
.script-toggle { position: absolute; left: -2.25rem; top: 0;
                 width: 1.75rem; height: 1.75rem; display: grid;
                 place-items: center; cursor: pointer; list-style: none;
                 color: #3984c6; border-radius: .25rem; line-height: 1;
                 font: 700 .8rem/1 ui-monospace, monospace; }
.script-toggle::-webkit-details-marker { display: none; }
.script-toggle:focus-visible { outline: 2px solid #3984c6; outline-offset: 2px; }
.script-toggle:hover, .script-block[open] > .script-toggle { background: #3984c622; }
.script-block[open] > .script-toggle {
  position: sticky; top: .5rem; left: auto; z-index: 1;
  margin-left: -2.25rem; margin-bottom: -1.75rem;
}

/* docstring and code records */
.module-docstring { display: flow-root; }
.doctest { margin: .3rem 0; }
.doctest-code { overflow: hidden; border-left: 3px solid #3984c6;
                font: .9em/1.5 ui-monospace, monospace; }
.doc-text { margin: 0; overflow-x: auto; font: inherit; }
.doc-code, .doc-out { display: block; padding: 0 1rem; font: inherit; }
.doc-code { min-width: fit-content; padding-top: .65rem;
            background: #f1f5f9; color: #172033; }
.doc-out { padding-bottom: .65rem; }
.doc-code + .doc-out { padding-top: .35rem; }
.doc-code:only-child { padding-bottom: .65rem; }
.doc-out:only-child { padding-top: .65rem; }
.snakedone-report { margin: .5rem 0 1rem; overflow: hidden; }

/* img */
img { max-width: 100%; height: auto; }
main img { display: block; margin: .35rem auto; max-height: 50vh;
           object-fit: contain; cursor: zoom-in; }
.recorded-image { width: min(100%, calc(50vh * var(--image-ratio))); }
main img.image-expanded { width: 100%; max-height: none; cursor: zoom-out; }
main img:focus-visible { outline: 2px solid #3984c6; outline-offset: 2px; }

@media (prefers-color-scheme: dark) {
  .doc-code { background: #202b3b; color: #e5eaf1; }
}
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


_EXTERNAL_IMAGE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<url>https?://[^)\s]+)\)\s*$")
_EXTERNAL_LINK = re.compile(r'<a href="(https?://[^"]*)"')
_IMAGE_SRC = re.compile(r'<img\b[^>]*\bsrc="(?P<url>https?://[^"]+)"')


def _external_image(line: str) -> tuple[str, str] | None:
    """Recognize a Markdown image pointing at an online ``http(s)`` resource."""
    match = _EXTERNAL_IMAGE.match(line.strip())
    if match is None:
        return None
    return match.group("url"), match.group("alt")


def _external_links(html: str):
    """Open online links in a new tab, without leaking the referrer."""
    return _EXTERNAL_LINK.sub(
        r'<a href="\1" target="_blank" rel="noopener noreferrer"', html
    )


def _image_origins(html: str):
    """Collect the origins of every online image in *html*, for the CSP."""
    origins: set[str] = set()
    for match in _IMAGE_SRC.finditer(html):
        parsed = urlsplit(match.group("url"))
        origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return sorted(origins)


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


class Report:
    """A report to embed in the HTML output.

    The report is identified by its *renderer* name and a unique *id*.
    The *files* dictionary maps file names to ``(mime, data)`` pairs.
    """

    def __init__(self, chunk: RecordedOutput, id: str):
        self.chunk = chunk
        self.id = id
        if self.files and not chunk.renderer.runtime:
            raise RuntimeError(
                f"Renderer {self.name!r} has report files but no offline HTML runtime"
            )

    @property
    def name(self):
        return self.chunk.renderer.name

    @property
    def files(self):
        return self.chunk.files

    @property
    def block(self):
        return (
            '<div class="doc-out"><div class="snakedone-report"'
            f' data-snakedone-report="{self.id}"'
            f' data-snakedone-renderer="{self.name}">'
            f"{self.chunk.text}</div></div>"
        )


def _output_html(
    code_html: str,
    output: str,
    reports: list[Report],
):
    parts: list[str] = []
    blocks: list[str] = []
    code_block = '<code class="doc-code">' + code_html.removesuffix("\n") + "</code>"

    def flush_text():
        nonlocal code_block
        if parts:
            code_block += f'<samp class="doc-out">{"".join(parts)}</samp>'
            parts.clear()
        elif not code_block:
            return
        blocks.append(f'<pre class="doc-text">{code_block}</pre>')
        code_block = ""

    for chunk in split_output(output):
        if isinstance(chunk, RecordedOutput):
            flush_text()
            report = Report(chunk, f"report-{len(reports)}")
            reports.append(report)
            blocks.append(report.block)
            continue
        for line in str(chunk).splitlines(keepends=True):
            png = _png_image(line)
            if png is not None:
                uri, width, height = png
                parts.append(
                    f'<img class="recorded-image" src="{escape(uri, quote=True)}"'
                    f' width="{width}" height="{height}"'
                    f' style="--image-ratio: {width / height}"'
                    f' alt="Recorded PNG ({width} × {height} pixels)">'
                )
                continue
            external = _external_image(line)
            if external is not None:
                url, alt = external
                parts.append(
                    f'<img src="{escape(url, quote=True)}"'
                    f' alt="{escape(alt, quote=True)}" loading="lazy">'
                )
                continue
            parts.append(escape(line))
    flush_text()
    return f'<div class="doctest-code">{"".join(blocks)}</div>'


def _reports_payload(reports: list[Report]):
    """Encode report files so they cannot terminate the surrounding script.

    Identical files (for example the shared Datavzrd bundle) are stored once.
    """
    pool: dict[str, dict[str, str | bool]] = {}
    registry: dict[str, dict[str, str]] = {}
    for reporter in reports:
        entry: dict[str, str] = {}
        for name, (mime, data) in reporter.files.items():
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
        registry[reporter.id] = entry
    encoded = json.dumps({"pool": pool, "reports": registry}, sort_keys=True)
    return encoded.replace("<", "\\u003c").replace(">", "\\u003e")


def _page_resources(reports: list[Report], origins: list[str]):
    """Return ``(styles, csp, scripts)`` for the exported page.

    Styles from every renderer are collected;
    scripts, the report payload, and CSP sources only collected
      from renderers that ship a runtime,
    since a renderer without one never executes in the browser.
    """

    image_hash = base64.b64encode(sha256(IMAGE_SCRIPT.encode()).digest()).decode()
    styles = [STYLE]
    runtimes = []
    sources = [f"'sha256-{image_hash}'"]
    for renderer in {r.name: r.chunk.renderer for r in reports}.values():
        if renderer.STYLE:
            styles.append(renderer.STYLE)
        if renderer.runtime:
            runtimes.append(renderer.runtime)
            sources.extend(renderer.sources)
    scripts = []
    for runtime in dict.fromkeys(runtimes):
        digest = base64.b64encode(sha256(runtime.encode()).digest()).decode()
        sources.append(f"'sha256-{digest}'")
        scripts.append(f"<script>{runtime}</script>")
    if scripts:
        # No runtime means nothing reads the payload; static renderers
        # already emit their final HTML into the report block.
        sources.extend(["blob:", "data:", "'unsafe-eval'"])
        image_src = "data: blob:"
        script = (
            '<script id="snakedone-reports" type="application/json">'
            + _reports_payload(reports)
            + "</script>\n"
            + "\n".join(scripts)
        )
        font_frame_src = " font-src data: blob:; frame-src 'self' data: blob:;"
    else:
        image_src = "data:"
        font_frame_src = script = ""
    script_src = " ".join(dict.fromkeys(sources))
    if origins:
        image_src += " " + " ".join(origins)
    csp = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        f"img-src {image_src};{font_frame_src} "
        f"script-src {script_src}; "
        "base-uri 'none'; form-action 'none'"
    )
    return "\n".join(dict.fromkeys(styles)), csp, script


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


def render(self: AstDocument, *, title: str = "snakedone document") -> str:
    """Render recorded content as offline HTML without executing the document."""
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

    position = self.position
    parts: list[str] = []
    reports: list[Report] = []

    cursor = 0
    for block in self.blocks:
        node = block.node
        assert node.end_lineno is not None and node.end_col_offset is not None
        start = position(node.lineno, node.col_offset)
        end = position(node.end_lineno, node.end_col_offset)
        script = _script_html(self.source[cursor:start], highlight_python)
        if script:
            parts.append(script)
        cursor = end
        parts.append('<section class="module-docstring">')
        prose = textwrap.dedent(block.markdown).strip()
        if prose:
            rendered = _external_links(markdown.render(prose))
            parts.append('<div class="doc-md">' + rendered + "</div>")
        for statement in block.statements:
            code = self.source[statement.start : statement.end]
            output = self.slot_output(statement)
            parts.append(
                '<section class="doctest">'
                + _output_html(highlight_python(code), output, reports)
                + "</section>"
            )
        parts.append("</section>")

    script = _script_html(self.source[cursor:], highlight_python)
    if script:
        parts.append(script)
    body = "\n".join(parts)
    style, csp, tail = _page_resources(reports, origins=_image_origins(body))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>{escape(title)}</title>
<style>
{highlight_style}
@media (prefers-color-scheme: dark) {{ {dark_style} }}
{style}
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
