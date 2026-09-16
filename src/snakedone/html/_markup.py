"""Helpers that recognize and rewrite online resources in generated markup."""

import re
from urllib.parse import urlsplit

_EXTERNAL_IMAGE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<url>https?://[^)\s]+)\)\s*$")
_EXTERNAL_LINK = re.compile(r'<a href="(https?://[^"]*)"')
_IMAGE_SRC = re.compile(r'<img\b[^>]*\bsrc="(?P<url>https?://[^"]+)"')


def external_image(line: str) -> tuple[str, str] | None:
    """Recognize a Markdown image pointing at an online ``http(s)`` resource."""
    match = _EXTERNAL_IMAGE.match(line.strip())
    if match is None:
        return None
    return match.group("url"), match.group("alt")


def external_links(html: str):
    """Open online links in a new tab, without leaking the referrer."""
    return _EXTERNAL_LINK.sub(
        r'<a href="\1" target="_blank" rel="noopener noreferrer"', html
    )


def image_origins(html: str):
    """Collect the origins of every online image in *html*, for the CSP."""
    origins: set[str] = set()
    for match in _IMAGE_SRC.finditer(html):
        parsed = urlsplit(match.group("url"))
        origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return sorted(origins)
