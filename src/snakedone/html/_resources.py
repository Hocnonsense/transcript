"""Assemble the page assets: styles, report payload, scripts, and CSP."""

import base64
import gzip
import json
from hashlib import sha256
from typing import TypedDict

from ..output import Report
from ._assets import ASSET_SCRIPTS, STYLE

_BROWSER_RENDERERS = {
    "cache": "snakedone-renderers-v1",
    "resources": [
        {
            "name": "markdown-it",
            "type": "script",
            "global": "markdownit",
            "url": "https://cdn.jsdelivr.net/npm/markdown-it@14.1.0/dist/markdown-it.min.js",
            "integrity": (
                "sha384-wLhprpjsmjc/XYIcF+LpMxd8yS1gss6jhevOp6F6zhiIoFK6AmHtm4bG"
                "KtehTani"
            ),
        },
        {
            "name": "highlight.js",
            "type": "script",
            "global": "hljs",
            "url": "https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.12.0/build/highlight.min.js",
            "integrity": (
                "sha384-wjfDDhOPPdjtva8vWBhWeVprSpmxisEu5aYT3q1JyACqXpdKpo3PWZTM"
                "Vq24MBix"
            ),
        },
        {
            "name": "highlight.js-default",
            "type": "style",
            "url": "https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.12.0/build/styles/default.min.css",
            "integrity": (
                "sha384-4Y0nObtF3CbKnh+lpzmAVdAMtQXl+ganWiiv73RcGVdRdfVIya8Cao1"
                "C8ZsVRRDz"
            ),
        },
        {
            "name": "jsdiff",
            "type": "script",
            "global": "Diff",
            "url": "https://cdn.jsdelivr.net/npm/diff@9.0.0/dist/diff.min.js",
            "integrity": (
                "sha384-TvJwlBkfFFd9hmaVfyJyF6lIPjAUL6x01MvObCeUao5yP6QZ6owU6fqw+JQoyRD1"
            ),
        },
    ],
}


def _digest(script: str):
    """Return the CSP ``sha256-`` source that allows an inline script."""
    digest = base64.b64encode(sha256(script.encode()).digest()).decode()
    return f"'sha256-{digest}'"


def _renderer_config():
    encoded = json.dumps(_BROWSER_RENDERERS, separators=(",", ":"))
    return (
        '<script id="snakedone-renderers" type="application/json">'
        + encoded.replace("<", "\\u003c").replace(">", "\\u003e")
        + "</script>"
    )


class _PackagedFile(TypedDict):
    mime: str
    gzip: bool
    content: str


def _package_files(reports: list[Report]):
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


def page_resources(reports: list[Report], origins: list[str], island: str = ""):
    """Return ``(styles, csp, scripts)`` for the exported page.

    styles: map(renderers, .STYLE).
    csp:
      Content-Security-Policy that allows the page to run in a browser
        without any external resources
      defaults + island + report payload + map(renderers, .sources).
    scripts: the core scripts, source island, report payload,
      + map(renderers, .runtime) for renderers that need it.

    a renderer without a runtime never executes in the browser,
      so it contributes no script or CSP source.
    """

    styles = [STYLE]
    runtimes = []
    sources = [*map(_digest, ASSET_SCRIPTS)]
    for renderer in {r.name: r.chunk.renderer for r in reports}.values():
        if renderer.STYLE:
            styles.append(renderer.STYLE)
        if renderer.runtime:
            runtimes.append(renderer.runtime)
            sources.extend(renderer.sources)
    runtime_tags = []
    for runtime in dict.fromkeys(runtimes):
        sources.append(_digest(runtime))
        runtime_tags.append(f"<script>{runtime}</script>")
    if runtime_tags:
        # No runtime means nothing reads the payload; static renderers
        # already emit their final HTML into the report block.
        sources.extend(["data:", "'unsafe-eval'"])
        image_src = "data: blob:"
        payload = (
            '<script id="snakedone-reports" type="application/json">'
            + _package_files(reports)
            + "</script>"
        )
        font_frame_src = " font-src data: blob:; frame-src 'self' data: blob:;"
    else:
        image_src = "data:"
        font_frame_src = payload = ""
    sources.append("blob:")
    script_src = " ".join(dict.fromkeys(sources))
    if origins:
        image_src += " " + " ".join(origins)
    csp = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        f"img-src {image_src};{font_frame_src} "
        f"script-src {script_src}; "
        "connect-src https://cdn.jsdelivr.net; "
        "base-uri 'none'; form-action 'none'"
    )
    scripts = "\n".join(
        part
        for part in (
            island,
            _renderer_config(),
            *(f"<script>{script}</script>" for script in ASSET_SCRIPTS),
            payload,
            *runtime_tags,
        )
        if part
    )
    return "\n".join(dict.fromkeys(styles)), csp, scripts
