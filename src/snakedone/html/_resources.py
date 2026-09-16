"""Assemble the page assets: styles, report payload, scripts, and CSP."""

import base64
import gzip
import json
from hashlib import sha256
from typing import TypedDict

from ..output import Report
from .assets import IMAGE_SCRIPT, NAVIGATE_SCRIPT, STYLE


class _PackagedFile(TypedDict):
    mime: str
    gzip: bool
    content: str


def _package_files(reports: list[Report]) -> str:
    """Package files in a JSON object with:
    - pool: dict[file_fingerprint, _PackagedFile]
    - reports: dict[name, file_fingerprint]

    Identical files (for example the shared Datavzrd bundle) are dereplicated.
    Encode so they cannot terminate the surrounding script.
    """

    pool: dict[str, _PackagedFile] = {}
    registry: dict[str, dict[str, str]] = {}
    for reporter in reports:
        entry: dict[str, str] = {}
        for name, (mime, data) in reporter.files.items():
            file_fingerprint = sha256(mime.encode() + b"\0" + data).hexdigest()
            if file_fingerprint not in pool:
                compressed = gzip.compress(data, compresslevel=9, mtime=0)
                payload = min(compressed, data, key=len)
                pool[file_fingerprint] = {
                    "mime": mime,
                    "gzip": payload is compressed,
                    "content": base64.b64encode(payload).decode("ascii"),
                }
            entry[name] = file_fingerprint
        registry[reporter.id] = entry
    encoded = json.dumps({"pool": pool, "reports": registry}, sort_keys=True)
    return encoded.replace("<", "\\u003c").replace(">", "\\u003e")


def page_resources(reports: list[Report], origins: list[str]):
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
        for script in (IMAGE_SCRIPT, NAVIGATE_SCRIPT)
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
            + _package_files(reports)
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
