"""Registry of snakedone-output renderers.

A renderer owns one recorded output kind in both directions:

- An instance wraps a Python object (``self.obj``); ``to_snd`` serializes it and
  ``repr`` returns the ``snakedone-output`` fence stored in ``.snd``.
- The class validates and renders stored text: ``to_html`` returns the HTML that
  fills a report slot together with the files the browser runtime embeds.

Rendering is stateless, so ``to_html`` and ``runtime`` are class methods and the
registry stores renderer classes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Renderer(Protocol):
    """Adapter that serializes, validates, and renders one kind of output."""

    name: str
    version: tuple[int, ...] | None = None

    def __init__(self):
        """Wrap the Python object this renderer serializes."""
        ...

    def __repr__(self):
        return self.to_snd().removesuffix("\n")

    def to_snd(self) -> str:
        """Serialize ``self.obj`` into a ``snakedone-output`` fence."""
        ...

    @classmethod
    def to_html(cls, data: str) -> tuple[str, dict[str, tuple[str, bytes]]]:
        """Validate stored *data* and return ``(html, files)``."""
        ...

    @classmethod
    def runtime(cls) -> str | None:
        """Return the browser script that serves the embedded report."""
        ...


RENDERERS: dict[str, type[Renderer]] = {}


def register(renderer: type[Renderer]):
    if not renderer.name:
        raise ValueError("renderer name must not be empty")
    if renderer.name in RENDERERS:
        raise ValueError(f"duplicate renderer: {renderer.name}")
    RENDERERS[renderer.name] = renderer
    return renderer


def get(name: str) -> type[Renderer] | None:
    """Return the registered renderer class, or ``None`` for an unknown name."""
    return RENDERERS.get(name)
