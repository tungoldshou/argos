# argos/tui/widgets/thinking.py
"""Thinking indicator glyph cycle from the README and 01-act design source."""
from __future__ import annotations

import time

from textual.widgets import Static

from argos.i18n import t

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class ThinkingIndicator(Static):
    """Internal documentation."""

    DEFAULT_CSS = """
    ThinkingIndicator { color: $eye; padding: 0 2; }
    """

    def __init__(self, label: str | None = None, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._label = label if label is not None else t("core2.thinking.label")
        self._frame = 0
        self._timer = None
        self._t0 = time.monotonic()

    def on_mount(self) -> None:
        self._t0 = time.monotonic()
        self._timer = self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        """Internal documentation."""
        self._frame = (self._frame + 1) % len(_FRAMES)
        self.refresh()

    def render(self) -> str:
        """Internal documentation."""
        elapsed = int(time.monotonic() - self._t0)
        suffix = f" {elapsed}s" if elapsed >= 1 else ""
        glyph = _FRAMES[self._frame]
        return f"{glyph} {self._label}{suffix}"

    @property
    def renderable(self) -> str:
        """Internal documentation."""
        return self.render()

    def set_label(self, label: str) -> None:
        """Internal documentation."""
        self._label = label
        self.refresh()
