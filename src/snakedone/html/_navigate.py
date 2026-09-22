"""Build the document outline navigate from the assembled HTML body."""

import re
from html import escape, unescape
from typing import NamedTuple

_SLUG_STRIP = re.compile(r"[^\w\- ]+", re.UNICODE)
_SLUG_SEPARATOR = re.compile(r"[\s\-]+")


def _slug(text: str):
    """Turn heading text into a URL fragment, keeping unicode letters.
    >>> _slug("Hello, world!")
    "hello-world"
    """
    return _SLUG_SEPARATOR.sub("-", _SLUG_STRIP.sub("", text.lower())).strip("-")


_LABEL_ANCHOR = re.compile(r'<figure class="snakedone-label" id="(?P<label>[^"]+)">')
_ANCHOR = re.compile(
    r'<h(?P<level>[1-6])(?: id="(?P<existing>[^"]+)")?>(?P<inner>.*?)</h(?P=level)>'
    r"|" + _LABEL_ANCHOR.pattern,
    re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")


def _plain_text(html: str):
    """Flatten inline HTML to the text shown in the navigate."""
    return unescape(_TAG.sub("", html)).strip()


def _get_label_caption(body: str, start: int):
    """Return the caption of the label figure opening at *start*, if any.

    The caption must belong to this figure, so captions of nested labels are
    skipped while scanning for the matching ``</figure>``.
    """
    depth = 0
    while start != -1:
        if body.startswith("<figure", start):
            depth += 1
            start += len("<figure")
        elif body.startswith("</figure>", start):
            depth -= 1
            start += len("</figure>")
            if depth == 0:
                break
        elif depth == 1 and body.startswith("<figcaption>", start):
            end = body.find("</figcaption>", start)
            if end == -1:
                break
            opening = len("<figcaption>")
            return _plain_text(body[start + opening : end])
        else:
            start = body.find("<", start + 1)


def anchors(parts: list[str]):
    """Assign heading ids and collect every anchor in document order.

    Headings produced by any renderer, including the Markdown renderer, share
    one namespace across all parts. Each entry is
    ``(kind, level, text, slug)`` with *kind* ``"heading"`` or ``"label"``;
    label ids are reserved so a heading never steals their anchor, and a label
    takes the level of the heading it follows so headings stay primary when
    both types are shown together.
    """
    # record all label first, so duplicated title ids will be renamed
    seen: dict[str, int] = dict.fromkeys(
        (
            match.group("label")
            for part in parts
            for match in _LABEL_ANCHOR.finditer(part)
        ),
        0,
    )
    entries: list[Entry] = []
    pieces: list[str] = []
    level = 0
    for part in parts:
        cursor = 0
        for match in _ANCHOR.finditer(part):
            pieces.append(part[cursor : match.start()])
            cursor = match.end()
            label: str | None = match.group("label")
            if label is not None:
                text = _get_label_caption(part, match.start()) or label
                entries.append(Entry.label(level, text, label))
                pieces.append(match.group(0))
                continue
            level = int(match.group("level"))
            inner = match.group("inner")
            text = _plain_text(inner)
            slug = match.group("existing") or _slug(text) or f"section-{len(entries)}"
            if slug in seen:
                base = slug
                count = seen[slug]
                while slug in seen:
                    count += 1
                    slug = f"{base}-{count}"
                seen[base] = count
            seen[slug] = 0
            entries.append(Entry.heading(level, text, slug))
            pieces.append(
                f'<h{level} id="{escape(slug, quote=True)}">{inner}</h{level}>'
            )
        pieces.append(part[cursor:])
        pieces.append("\n")
    return "".join(pieces), entries


class Entry(NamedTuple):
    kind: str
    level: int
    text: str
    slug: str

    @classmethod
    def label(cls, level: int, text: str, slug: str):
        return cls("label", min(level + 1, 6), text, slug)

    @classmethod
    def heading(cls, level: int, text: str, slug: str):
        return cls("heading", level, text, slug)

    def render(self, shown: set[str]):
        name = self._TYPES[self.kind][0]
        hidden = "" if name in shown else " hidden"
        # Labels are a flat type, so they all share one indent instead of
        # following the level of whatever heading happens to precede them.
        css = (
            f"toc-heading toc-l{self.level}" if self.kind == "heading" else "toc-label"
        )
        return (
            f'<li class="{css}" data-snd-type="{name}"{hidden}>'
            f'<a href="#{escape(self.slug, quote=True)}">{escape(self.text)}</a></li>'
        )

    _TYPES = {"heading": ("contents", "Contents"), "label": ("labels", "Labels")}
    """
    Anchor kinds mapped to their navigate type and tab title, in tab order.
    A new kind (for example a future "reference") only needs an entry here
    and a marker in the navigate CSS; the script discovers types from the markup.
    """


_EYE_PATH = (
    '<path d="M1.5 8s2.4-4 6.5-4 6.5 4 6.5 4-2.4 4-6.5 4S1.5 8 1.5 8Z"/>'
    '<circle cx="8" cy="8" r="2"/>'
)
_EYE = (
    '<span class="navigate-eye" aria-hidden="true">'
    f'<svg class="navigate-eye-open" viewBox="0 0 16 16">{_EYE_PATH}</svg>'
    f'<svg class="navigate-eye-closed" viewBox="0 0 16 16">{_EYE_PATH}'
    '<path d="M2.5 2.5l11 11"/></svg>'
    "</span>"
)


def navigate_html(entries: list[Entry]):
    """Build the navigate from the collected anchors.

    One list holds every anchor in document order. Each type gets a tab whose
    body isolates that type and whose toggle adds or removes it; with several
    types shown, the list stays merged and headings keep their nesting. The
    list may be empty, which collapses the navigate to its vertical tabs.
    """
    if not entries:
        return "page", ""
    present = {kinds.kind for kinds in entries}
    types = [
        (name, title) for kind, (name, title) in Entry._TYPES.items() if kind in present
    ]
    shown = {types[0][0]}
    items = "".join(entry.render(shown) for entry in entries)
    tabs = "".join(
        f'<div class="navigate-tab" data-snd-type="{name}"'
        f' data-active="{str(name in shown).lower()}">'
        f'<button class="navigate-tab-body" type="button">{title}</button>'
        f'<button class="navigate-tab-toggle" type="button"'
        f' aria-pressed="{str(name in shown).lower()}"'
        f' aria-label="Add or remove {title}">'
        f"{_EYE}"
        "</button></div>"
        for name, title in types
    )
    return "page page--navigate", (
        '<nav class="navigate" aria-label="Document outline" data-collapsed="false">'
        f'<div class="navigate-tabs">{tabs}</div>'
        f'<ol class="navigate-list" data-snd-show="{" ".join(sorted(shown))}">'
        f"{items}</ol></nav>"
    )
