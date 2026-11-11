"""Recognize online resources in Markdown rendered by the browser."""

import re
from urllib.parse import urlsplit

_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*(?P<url>https?://[^)\s]+)")
_MARKDOWN_REFERENCE = re.compile(
    r"^[ \t]*\[[^\]]+\]:[ \t]*(?P<url>https?://\S+)", re.MULTILINE
)


def _origin(url: str):
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def markdown_image_origins(text: str):
    """Return the origins of every online image a Markdown *text* can render.

    Markdown is rendered in the browser, so its images never reach the server
    HTML; their hosts still have to be allowed by the page's CSP.
    """
    origins: set[str] = set()
    for pattern in (_MARKDOWN_IMAGE, _MARKDOWN_REFERENCE):
        origins.update(_origin(match.group("url")) for match in pattern.finditer(text))
    return sorted(origins)
