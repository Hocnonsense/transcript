"""Helpers that recognize and rewrite online resources in generated markup.

Includes scanning Markdown source for online images, whose origins must be
allowed by the CSP even though the Markdown itself is rendered in the browser.
"""

import re
from urllib.parse import urlsplit

_EXTERNAL_IMAGE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<url>https?://[^)\s]+)\)\s*$")
_IMAGE_SRC = re.compile(r'<img\b[^>]*\bsrc="(?P<url>https?://[^"]+)"')
# Markdown prose is rendered in the browser, so its images never reach the
# server-built body. Scan the source to still allow their origins in the CSP:
# inline ``![alt](url)`` and reference definitions ``[label]: url``.
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*(?P<url>https?://[^)\s]+)")
_MARKDOWN_REFERENCE = re.compile(
    r"^[ \t]*\[[^\]]+\]:[ \t]*(?P<url>https?://\S+)", re.MULTILINE
)


def _origin(url: str):
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def external_image(line: str) -> tuple[str, str] | None:
    """Recognize a Markdown image pointing at an online ``http(s)`` resource."""
    match = _EXTERNAL_IMAGE.match(line.strip())
    if match is None:
        return None
    return match.group("url"), match.group("alt")


def image_origins(html: str):
    """Collect the origins of every online image in *html*, for the CSP."""
    return sorted({_origin(match.group("url")) for match in _IMAGE_SRC.finditer(html)})


def markdown_image_origins(text: str):
    """Collect the origins of every online image a Markdown *text* can render.

    Complements :func:`image_origins`: the report's Markdown is rendered by the
    browser runtime, so its images are absent from the server-built HTML and
    their hosts must still be allowed by the page's Content-Security-Policy.
    """
    origins: set[str] = set()
    for pattern in (_MARKDOWN_IMAGE, _MARKDOWN_REFERENCE):
        origins.update(_origin(match.group("url")) for match in pattern.finditer(text))
    return sorted(origins)
