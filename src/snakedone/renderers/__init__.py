"""Registry of snakedone-output renderers.

A renderer turns a recorded snapshot into the files the HTML export embeds.
Renderers register themselves under a stable name, so an archive only stores
that name and the HTML step can dispatch without hardcoding any renderer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..output import RecordedOutput


@runtime_checkable
class Renderer(Protocol):
    """Adapter that validates and builds one kind of recorded output."""

    name: str

    def validate(self, output: RecordedOutput) -> None:
        """Reject snapshots this renderer cannot build."""
        ...

    def build(self, output: RecordedOutput) -> dict[str, tuple[str, bytes]]:
        """Return ``{relative path: (mime, bytes)}`` for the report."""
        ...

    def runtime(self) -> str | None:
        """Return the browser script that serves the embedded report."""
        ...


RENDERERS: dict[str, Renderer] = {}
_LOADED = False


def register(renderer: Renderer) -> Renderer:
    if not renderer.name:
        raise ValueError("renderer name must not be empty")
    if renderer.name in RENDERERS:
        raise ValueError(f"duplicate renderer: {renderer.name}")
    RENDERERS[renderer.name] = renderer
    return renderer


def get(name: str) -> Renderer | None:
    """Return the registered renderer, or ``None`` for an unknown name."""
    return RENDERERS.get(name)


def load() -> None:
    """Import the built-in renderers so they register themselves."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    from . import datavzrd  # noqa: F401
