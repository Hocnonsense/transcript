"""Render recorded documents as HTML without executing their Python code."""

import base64
import binascii
import gzip
import io
import json
import re
import struct
import textwrap
import tokenize
from collections.abc import Callable
from hashlib import sha256
from html import escape, unescape
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .output import RecordedOutput, Report, split_output

if TYPE_CHECKING:
    from .document import AstDocument

STYLE = """
:root { color-scheme: light dark; --unit: 1.25rem; --body-max: 860px;
        --side: 15rem; --side-rail: 2.25rem; }
body { margin: 0; font: 17px/1.65 system-ui, sans-serif; }
.page { max-width: 860px; margin: 3rem auto; padding: 0 1.25rem 0 3rem; }
/* The body and sidebar share one centered grid. The sidebar keeps the same
   top-right position at every width; only the body's reservation changes, so
   nothing jumps. Below the breakpoint it floats over the body instead. */
.page--sidebar { display: grid; grid-template-columns: minmax(0, 1fr) auto;
                 gap: var(--unit); margin: 3rem auto;
                 padding: 0 var(--unit);
                 max-width: calc(var(--body-max) + var(--side) + 3 * var(--unit)); }
.page--sidebar > main { grid-area: 1 / 1; max-width: var(--body-max); }
.page--sidebar > .sidebar { grid-area: 1 / 2; }
.sidebar { position: sticky; top: 3rem; align-self: start; z-index: 20;
           width: var(--side); max-height: calc(100vh - 6rem);
           overflow-y: auto; box-sizing: border-box;
           padding-right: .75rem; border-right: 1px solid #8885;
           font-size: .9rem; transition: width .2s ease; }
.sidebar-tabs { display: flex; gap: .25rem; margin-bottom: .5rem; }
.sidebar-tab { display: flex; align-items: center; flex: 1; min-width: 0;
               border-bottom: 2px solid transparent; }
.sidebar-tab[data-active="true"] { border-bottom-color: #3984c6; }
.sidebar-tab-body { flex: 1; min-width: 0; padding: .15rem .25rem;
                    background: none; border: 0; cursor: pointer;
                    color: #888; font: inherit; text-align: left;
                    white-space: nowrap; overflow: hidden;
                    text-overflow: ellipsis; }
.sidebar-tab[data-active="true"] .sidebar-tab-body {
  color: inherit; font-weight: 600; }
.sidebar-tab-toggle { flex: none; width: 1.4rem; height: 1.4rem; display: grid;
                      place-items: center; background: none; border: 0;
                      cursor: pointer; border-radius: .25rem;
                      font: 700 .9rem/1 ui-monospace, monospace; }
.sidebar-tab-toggle[aria-pressed="true"] { color: #3984c6; }
.sidebar-tab-toggle[aria-pressed="false"] { color: #888; }
.sidebar-tab-toggle:hover { background: #3984c622; }
.sidebar-tab-body:focus-visible, .sidebar-tab-toggle:focus-visible {
  outline: 2px solid #3984c6; outline-offset: 2px; }
/* Nothing open: a compact bordered box of vertical tabs, same at every width. */
.sidebar[data-collapsed="true"] { top: 3rem; width: var(--side-rail);
                                  height: auto; max-height: calc(100vh - 6rem);
                                  padding: .4rem .2rem;
                                  border: 1px solid #8885; border-radius: .4rem;
                                  background: canvas; box-shadow: none; }
.sidebar[data-collapsed="true"] .sidebar-list { display: none; }
.sidebar[data-collapsed="true"] .sidebar-tabs { flex-direction: column; gap: .3rem;
                                                margin-bottom: 0; }
.sidebar[data-collapsed="true"] .sidebar-tab { flex: none; border-bottom: 0;
                                               border-left: 2px solid transparent; }
.sidebar[data-collapsed="true"] .sidebar-tab-toggle { display: none; }
.sidebar[data-collapsed="true"] .sidebar-tab-body { flex: none; padding: .4rem .1rem;
                                                    writing-mode: vertical-rl; }
.sidebar ol { list-style: none; margin: 0; padding: 0; }
.sidebar li { margin: .1rem 0; }
.sidebar a { display: block; padding: .1rem .5rem; color: inherit;
             text-decoration: none; border-left: 2px solid transparent; }
.sidebar a:hover { color: #3984c6; border-left-color: #3984c6; }
.sidebar .toc-l1 a { font-weight: 600; }
.sidebar .toc-l2 a { padding-left: 1.25rem; }
.sidebar .toc-l3 a { padding-left: 2rem; }
.sidebar .toc-l4 a, .sidebar .toc-l5 a, .sidebar .toc-l6 a { padding-left: 2.75rem; }
.sidebar .toc-label a { padding-left: 1.25rem; }
.sidebar .toc-label a::before { content: "◆ "; color: #888; font-size: .7em;
                                vertical-align: .15em; }
h1, h2, h3 { line-height: 1.25; }
a { color: #3984c6; }
code { font-family: ui-monospace, monospace; font-size: .9em; }
blockquote { margin-left: 0; padding-left: 1rem; border-left: 3px solid #8885; }
table { border-collapse: collapse; }
th, td { border: 1px solid #8885; padding: .35rem .7rem; }

/* bordered boxes */
.script-code, .doctest-code {
  border: 1px solid #8885; border-radius: .4rem;
}

/* scripts */
.script-block { position: relative; margin: 0; padding: 0; border: 0; }
.script-block[open] { display: flow-root; }
.script-block:not([open]) { height: 0; }
.script-code { margin: 0 0 1.5rem; padding: 1rem; overflow-x: auto;
               line-height: 1.5; }
/* The toggle lives in the left gutter, whose width is the layout unit, so it
   never takes space from the body. */
.script-toggle { position: absolute; left: calc(-1 * var(--unit)); top: 0;
                 width: var(--unit); height: var(--unit); display: grid;
                 place-items: center; cursor: pointer; list-style: none;
                 color: #3984c6; border-radius: .25rem; line-height: 1;
                 font: 700 .6rem/1 ui-monospace, monospace; }
.script-toggle::-webkit-details-marker { display: none; }
.script-toggle:focus-visible { outline: 2px solid #3984c6; outline-offset: 2px; }
.script-toggle:hover, .script-block[open] > .script-toggle { background: #3984c622; }
.script-block[open] > .script-toggle {
  position: sticky; top: .5rem; left: auto; z-index: 1;
  margin-left: calc(-1 * var(--unit)); margin-bottom: calc(-1 * var(--unit));
}

/* docstring and code records */
.module-docstring { display: flow-root; }
.doctest-code { position: relative; margin: .3rem 0; overflow: hidden;
                border-left: 3px solid #3984c6;
                font: .9em/1.5 ui-monospace, monospace; }
.doctest-code[data-boxed] { overflow: visible; }
.doctest-code[data-boxed="false"] {
  margin: 0; border: 0; border-radius: 0;
}
.doctest-code[data-boxed="false"] > .doc-text { display: none; }
.output-box-toggle { position: absolute; left: calc(-1 * var(--unit)); top: .3rem;
                     width: var(--unit); height: var(--unit); cursor: pointer;
                     color: #3984c6; border: 0; border-radius: .25rem;
                     background: transparent;
                     font: 700 .6rem/1 ui-monospace, monospace; }
.output-box-toggle:hover { background: #3984c622; }
.output-box-toggle:focus-visible { outline: 2px solid #3984c6; outline-offset: 2px; }
.doc-text { margin: 0; overflow-x: auto; font: inherit; }
.doc-code, .doc-out { display: block; padding: 0 1rem; font: inherit; }
.doc-code { min-width: fit-content; padding-top: .65rem;
            background: #f1f5f9; color: #172033; }
.doc-line { position: relative; display: block; padding-left: 4ch; }
.doc-line::before { position: absolute; left: 0; content: "... ";
                    user-select: none; -webkit-user-select: none; }
.doc-line:first-child::before { content: ">>> "; }
.doc-line.multiline-string::before { content: ""; }
.doc-out { padding-bottom: .65rem; }
.doc-code + .doc-out { padding-top: .35rem; }
.doc-code:only-child { padding-bottom: .65rem; }
.doc-out:only-child { padding-top: .65rem; }

/* img */
img { max-width: 100%; height: auto; }
main img { display: block; margin: .35rem auto; max-height: 50vh;
           object-fit: contain; cursor: zoom-in; }
.recorded-image { width: min(100%, calc(50vh * var(--image-ratio))); }
main img.image-expanded { width: 100%; max-height: none; cursor: zoom-out; }
main img:focus-visible { outline: 2px solid #3984c6; outline-offset: 2px; }

@media (max-width: 920px) {
  /* Below the body's limit the sidebar floats over the text instead of taking
     a column, so the body uses the full width and the sidebar starts closed.
     Its top-right position is unchanged, so it does not jump. */
  .page--sidebar { display: block; }
  .page--sidebar > main { margin: 0 auto; }
  /* A collapsed box sits between the body and the right edge, so the body
     yields its width; an opened panel just floats over the body. */
  .page--sidebar:has(.sidebar[data-collapsed="true"]) > main {
    margin-left: 0;
    margin-right: calc(var(--side-rail) + var(--unit)); }
  .sidebar { position: fixed; top: 3rem; right: var(--unit); left: auto;
             background: canvas; color: canvastext;
             border: 1px solid #8885; border-radius: .4rem;
             box-shadow: -2px 0 12px #0002; }
}
@media (prefers-color-scheme: dark) {
  .doc-code { background: #202b3b; color: #e5eaf1; }
}
@media print {
  .page { max-width: none; margin: 0; padding: 0; }
  .page--sidebar { display: block; }
  .sidebar { display: none; }
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

document.querySelectorAll('.doctest-code[data-boxed]').forEach(block => {
  const toggle = block.querySelector(':scope > .output-box-toggle');
  if (!toggle) return;
  function setBoxed(boxed) {
    block.dataset.boxed = String(boxed);
    toggle.setAttribute('aria-expanded', String(boxed));
    toggle.title = boxed ? 'Hide code and frame' : 'Show code and frame';
  }
  toggle.addEventListener('click', () => setBoxed(block.dataset.boxed !== 'true'));
  setBoxed(block.dataset.boxed === 'true');
});
"""

# One merged list holds every anchor in document order. A tab's toggle adds or
# removes its type from the list; the tab body isolates that type. Types are
# discovered from the markup, so a future "reference" tab needs no change here.
SIDEBAR_SCRIPT = """
document.querySelectorAll('.sidebar').forEach(sidebar => {
  const tabs = Array.from(sidebar.querySelectorAll('.sidebar-tab'));
  const list = sidebar.querySelector('.sidebar-list');
  if (!list || tabs.length < 2) return;
  const entries = Array.from(list.querySelectorAll('[data-snakedone-type]'));
  function enabled() {
    return list.dataset.snakedoneShow.split(/\\s+/).filter(Boolean);
  }
  function setEnabled(names) {
    list.dataset.snakedoneShow = names.join(' ');
    entries.forEach(entry => {
      entry.hidden = !names.includes(entry.dataset.snakedoneType);
    });
    tabs.forEach(tab => {
      const on = names.includes(tab.dataset.snakedoneType);
      tab.dataset.active = String(on);
      const toggle = tab.querySelector('.sidebar-tab-toggle');
      toggle.setAttribute('aria-pressed', String(on));
      toggle.firstElementChild.textContent = on ? '\\u2212' : '+';
    });
    sidebar.dataset.collapsed = String(names.length === 0);
  }
  tabs.forEach(tab => {
    const type = tab.dataset.snakedoneType;
    tab.querySelector('.sidebar-tab-toggle').addEventListener('click', () => {
      const names = enabled();
      setEnabled(names.includes(type)
        ? names.filter(name => name !== type) : [...names, type]);
    });
    tab.querySelector('.sidebar-tab-body').addEventListener('click', () => {
      setEnabled([type]);
    });
  });
  // Below M + 3u the sidebar floats over the text, so it opens automatically
  // above that width and starts collapsed below it. The same breakpoint also
  // lets a click on the page collapse the floating sidebar again.
  const narrow = window.matchMedia('(max-width: 920px)');
  const firstType = tabs[0].dataset.snakedoneType;
  function sync(event) {
    setEnabled(event.matches ? [] : [firstType]);
  }
  sync(narrow);
  narrow.addEventListener('change', sync);
  document.addEventListener('click', event => {
    if (narrow.matches && !sidebar.contains(event.target)) setEnabled([]);
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


def _output_html(
    code_html: str,
    output: str,
    reports: list[Report],
    ireport: str,
    multiline_string_lines: set[int] | None = None,
):
    parts: list[str] = []
    blocks: list[str] = []
    code_lines = code_html.removesuffix("\n").split("\n")
    multiline_string_lines = multiline_string_lines or set()
    prompted_code = "".join(
        '<span class="doc-line'
        + (" multiline-string" if lineno in multiline_string_lines else "")
        + f'">{line}</span>'
        for lineno, line in enumerate(code_lines, start=1)
    )
    code_block = '<code class="doc-code">' + prompted_code + "</code>"

    def flush_text():
        nonlocal code_block
        if parts:
            code_block += f'<samp class="doc-out">{"".join(parts)}</samp>'
            parts.clear()
        elif not code_block:
            return
        blocks.append(f'<pre class="doc-text">{code_block}</pre>')
        code_block = ""

    report_rendered = False
    for ichunk, chunk in enumerate(split_output(output)):
        if isinstance(chunk, RecordedOutput):
            flush_text()
            report_rendered = True
            report = chunk.to_report(f"{ireport}-{ichunk}", reports)
            boxed = report.boxed
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
    content = "".join(blocks)
    if not report_rendered:
        return f'<div class="doctest-code">{content}</div>'
    boxed = ichunk != 0 or report.boxed
    expanded = str(boxed).lower()
    toggle = (
        '<button class="output-box-toggle" type="button"'
        f' aria-label="Show or hide code and frame" aria-expanded="{expanded}">'
        '<span aria-hidden="true">&lt;/&gt;</span></button>'
    )
    return f'<div class="doctest-code" data-boxed="{expanded}">{toggle}{content}</div>'


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

    styles = [STYLE]
    runtimes = []
    sources = [
        "'sha256-" + base64.b64encode(sha256(script.encode()).digest()).decode() + "'"
        for script in (IMAGE_SCRIPT, SIDEBAR_SCRIPT)
    ]
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


def _multiline_string_lines(source: str):
    """Return physical lines inside multiline strings after their first line."""
    string_interior_lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING and token.start[0] != token.end[0]:
            string_interior_lines.update(range(token.start[0] + 1, token.end[0] + 1))
    return string_interior_lines


_SLUG_STRIP = re.compile(r"[^\w\- ]+", re.UNICODE)
_SLUG_SEPARATOR = re.compile(r"[\s\-]+")


def _slug(text: str):
    """Turn heading text into a URL fragment, keeping unicode letters."""
    return _SLUG_SEPARATOR.sub("-", _SLUG_STRIP.sub("", text.lower())).strip("-")


_ANCHOR = re.compile(
    r'<h(?P<level>[1-6])(?: id="(?P<existing>[^"]+)")?>(?P<inner>.*?)</h(?P=level)>'
    r'|<figure class="snakedone-label" id="(?P<label>[^"]+)">',
    re.DOTALL,
)
_LABEL_ANCHOR = re.compile(r'<figure class="snakedone-label" id="([^"]+)">')
_TAG = re.compile(r"<[^>]+>")


def _plain_text(html: str) -> str:
    """Flatten inline HTML to the text shown in the sidebar."""
    return unescape(_TAG.sub("", html)).strip()


def _label_caption(body: str, start: int):
    """Return the caption of the label figure opening at *start*, if any.

    The caption must belong to this figure, so captions of nested labels are
    skipped while scanning for the matching ``</figure>``.
    """
    depth = 0
    cursor = start
    while cursor < len(body):
        if body.startswith("<figure", cursor):
            depth += 1
            cursor += len("<figure")
        elif body.startswith("</figure>", cursor):
            depth -= 1
            cursor += len("</figure>")
            if depth == 0:
                break
        elif depth == 1 and body.startswith("<figcaption>", cursor):
            end = body.find("</figcaption>", cursor)
            if end == -1:
                break
            opening = len("<figcaption>")
            return _plain_text(body[cursor + opening : end])
        else:
            cursor += 1
    return ""


def _anchors(body: str):
    """Assign heading ids and collect every anchor in document order.

    Working on the assembled body means headings produced by any renderer,
    including the Markdown renderer, share one namespace. Each entry is
    ``(kind, level, text, slug)`` with *kind* ``"heading"`` or ``"label"``;
    label ids are reserved so a heading never steals their anchor, and a label
    takes the level of the heading it follows so headings stay primary when
    both types are shown together.
    """
    seen: dict[str, int] = dict.fromkeys(
        (match.group(1) for match in _LABEL_ANCHOR.finditer(body)), 1
    )
    entries: list[tuple[str, int, str, str]] = []
    pieces: list[str] = []
    cursor = 0
    heading_level = 0
    for match in _ANCHOR.finditer(body):
        pieces.append(body[cursor : match.start()])
        cursor = match.end()
        label = match.group("label")
        if label is not None:
            text = _label_caption(body, match.start()) or label
            entries.append(("label", min(heading_level + 1, 6), text, label))
            pieces.append(match.group(0))
            continue
        level = int(match.group("level"))
        inner = match.group("inner")
        text = _plain_text(inner)
        slug = match.group("existing")
        if slug is None:
            base = _slug(text) or f"section-{len(entries)}"
            count = seen.get(base, 0)
            seen[base] = count + 1
            slug = base if count == 0 else f"{base}-{count}"
        else:
            seen[slug] = seen.get(slug, 0) + 1
        heading_level = level
        entries.append(("heading", level, text, slug))
        pieces.append(f'<h{level} id="{escape(slug, quote=True)}">{inner}</h{level}>')
    pieces.append(body[cursor:])
    return "".join(pieces), entries


_MINUS = "\u2212"

# Anchor kinds mapped to their sidebar type and tab title, in tab order. A new
# kind (for example a future "reference") only needs an entry here and a marker
# in the sidebar CSS; the script discovers types from the markup.
_ANCHOR_TYPES = {"heading": ("contents", "Contents"), "label": ("labels", "Labels")}


def _sidebar_items(entries: list[tuple[str, int, str, str]], shown: set[str]):
    """Render one merged list, hiding the types that are not currently shown."""
    items: list[str] = []
    for kind, level, text, slug in entries:
        name = _ANCHOR_TYPES[kind][0]
        hidden = "" if name in shown else " hidden"
        # Labels are a flat type, so they all share one indent instead of
        # following the level of whatever heading happens to precede them.
        css = f"toc-heading toc-l{level}" if kind == "heading" else "toc-label"
        items.append(
            f'<li class="{css}" data-snakedone-type="{name}"{hidden}>'
            f'<a href="#{escape(slug, quote=True)}">{escape(text)}</a></li>'
        )
    return "".join(items)


def _sidebar_html(entries: list[tuple[str, int, str, str]]):
    """Build the sidebar from the collected anchors.

    One list holds every anchor in document order. Each type gets a tab whose
    body isolates that type and whose toggle adds or removes it; with several
    types shown, the list stays merged and headings keep their nesting. The
    list may be empty, which collapses the sidebar to its vertical tabs.
    """
    if not entries:
        return ""
    present = {kind for kind, *_ in entries}
    types = [
        (name, title)
        for kind, (name, title) in _ANCHOR_TYPES.items()
        if kind in present
    ]
    shown = {types[0][0]}
    items = _sidebar_items(entries, shown)
    tabs = "".join(
        f'<div class="sidebar-tab" data-snakedone-type="{name}"'
        f' data-active="{str(name in shown).lower()}">'
        f'<button class="sidebar-tab-body" type="button">{title}</button>'
        f'<button class="sidebar-tab-toggle" type="button"'
        f' aria-pressed="{str(name in shown).lower()}"'
        f' aria-label="Add or remove {title}">'
        f'<span aria-hidden="true">{_MINUS if name in shown else "+"}</span>'
        "</button></div>"
        for name, title in types
    )
    return (
        '<nav class="sidebar" aria-label="Document outline" data-collapsed="false">'
        f'<div class="sidebar-tabs">{tabs}</div>'
        f'<ol class="sidebar-list" data-snakedone-show="{" ".join(sorted(shown))}">'
        f"{items}</ol></nav>"
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
    for iblock, block in enumerate(self.blocks):
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
        for istatement, statement in enumerate(block.statements):
            line_start = self.source.rfind("\n", 0, statement.start) + 1
            line_end = self.source.find("\n", statement.end)
            if line_end == -1:
                line_end = len(self.source)
            physical_code = self.source[line_start:line_end]
            multiline_string_lines = _multiline_string_lines(physical_code)
            indent = self.source[line_start : statement.start]
            code = "".join(
                line if lineno in multiline_string_lines else line.removeprefix(indent)
                for lineno, line in enumerate(
                    physical_code.splitlines(keepends=True), start=1
                )
            )
            output = self.slot_output(statement)
            parts.append(
                _output_html(
                    highlight_python(code),
                    output,
                    reports,
                    f"report-{iblock}-{istatement}",
                    multiline_string_lines,
                )
            )
        parts.append("</section>")

    script = _script_html(self.source[cursor:], highlight_python)
    if script:
        parts.append(script)
    body, entries = _anchors("\n".join(parts))
    sidebar = _sidebar_html(entries)
    style, csp, tail = _page_resources(reports, _image_origins(body))
    page_class = "page page--sidebar" if sidebar else "page"

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
<body><div class="{page_class}">
{sidebar}
<main>
{body}
</main>
</div>
<script>{IMAGE_SCRIPT}</script>
<script>{SIDEBAR_SCRIPT}</script>
{tail}
</body>
</html>
"""
