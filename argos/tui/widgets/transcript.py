# argos/tui/widgets/transcript.py
"""Internal documentation."""
from __future__ import annotations

import re

from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static

from argos.i18n import t
from argos.tui.widgets.thinking import ThinkingIndicator

_FENCE_BLOCK = re.compile(r"```[^\n]*\n.*?```\n?", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Internal documentation."""
    text = _FENCE_BLOCK.sub("", text)
    idx = text.rfind("```")
    if idx != -1:
        text = text[:idx]
    return text.strip("\n")


class UserMessage(Static):
    DEFAULT_CSS = """
    UserMessage { color: $ink; padding: 0 2; }
    """
    def __init__(self, text: str) -> None:
        super().__init__(f"› {text}", markup=False)
        self.add_class("user-msg")


class SystemLine(Static):
    DEFAULT_CSS = """
    SystemLine { padding: 0 2; }
    SystemLine.sys-error { color: $fail; }
    SystemLine.sys-escalation { color: $unverif; }
    SystemLine.sys-done { color: $pass; }
    SystemLine.sys-system { color: $ink-faint; }
    """
    def __init__(self, text: str, *, kind: str = "system") -> None:
        super().__init__(text, markup=False)
        self.add_class(f"sys-{kind}")


class AssistantMessage(Markdown):
    DEFAULT_CSS = """
    AssistantMessage { background: transparent; margin: 0 0 1 0; padding: 0 2; }
    AssistantMessage .markdown--em { color: $ink-bright; }
    AssistantMessage .markdown-strong { color: $ink-bright; }
    """

    _FLUSH_INTERVAL_MS: int = 40

    def __init__(self) -> None:
        super().__init__("")
        self.add_class("assistant-msg")
        self._raw = ""
        self._pending = False

    def feed(self, text: str) -> None:
        """Internal documentation."""
        first_token = not self._raw
        self._raw += text
        self._pending = True
        if first_token:
            self._flush()

    def _flush(self) -> None:
        """Internal documentation."""
        if not self._pending:
            return
        self._pending = False
        self.update(strip_code_fences(self._raw))

    def on_mount(self) -> None:
        """Internal documentation."""
        self.set_interval(self._FLUSH_INTERVAL_MS / 1000.0, self._flush)


class Transcript(VerticalScroll):
    """Internal documentation."""
    DEFAULT_CSS = """
    Transcript { background: $stream; }
    Transcript Rule { color: $hairline-lit; }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.can_focus = True
        self._current: AssistantMessage | None = None
        self._lines: list[str] = []
        self._anchored_once: bool = False

    @property
    def rendered_text(self) -> str:
        parts = list(self._lines)
        if self._current is not None:
            parts.append(strip_code_fences(self._current._raw))
        return "\n".join(p for p in parts if p)

    def _ensure_anchored(self) -> None:
        """Internal documentation."""
        if self.is_attached and not self._anchored_once:
            self._anchored_once = True
            self.anchor()

    async def user_line(self, text: str) -> None:
        self.finalize_response()
        if self._lines and self.is_attached:
            from textual.widgets import Rule
            await self.mount(Rule(line_style="dashed"))
        self._lines.append(f"› {text}")
        if self.is_attached:
            await self.mount(UserMessage(text))
            self._anchored_once = True
            self.anchor()

    async def append_token(self, text: str) -> None:
        if self._current is None:
            for sp in self.query(ThinkingIndicator):
                await sp.remove()
            self._current = AssistantMessage()
            if self.is_attached:
                await self.mount(self._current)
        if self._current is None:
            self._current = AssistantMessage()
            if self.is_attached:
                await self.mount(self._current)
        target = self._current
        if target is not None:
            target.feed(text)
        self._ensure_anchored()

    def finalize_response(self) -> None:
        """Internal documentation."""
        if self._current is not None:
            self._lines.append(strip_code_fences(self._current._raw))
            self._current = None

    async def append_line(self, text: str, *, kind: str = "system") -> None:
        self.finalize_response()
        self._lines.append(text)
        if self.is_attached:
            await self.mount(SystemLine(text, kind=kind))
            self._ensure_anchored()

    async def mount_block(self, widget) -> None:
        self.finalize_response()
        if not self.is_attached:
            return
        await self.mount(widget)
        self._ensure_anchored()

    async def show_thinking(self, label: str | None = None) -> None:
        self.finalize_response()
        if not self.is_attached:
            return
        await self.mount(ThinkingIndicator(label if label is not None else t("core2.transcript.thinking")))
        self._ensure_anchored()

    async def clear(self) -> None:
        await self.remove_children()
        self._current = None
        self._anchored_once = False
        self.anchor(False)
        self._lines.clear()
