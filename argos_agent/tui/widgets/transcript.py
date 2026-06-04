# argos_agent/tui/widgets/transcript.py
"""主对话区:VerticalScroll + 可挂载消息 widget(spec §聊天渲染架构)。

替换旧 RichLog:
  · UserMessage:暗灰 '› ' 前缀;
  · AssistantMessage(Markdown):亮白,流式 update,剥代码围栏(代码在 CodeActionBlock);
  · SystemLine:系统/错误/完成等单行,按 kind 着色;
  · 结构化块(CodeActionBlock/DiffView/VerdictBadge)经 mount_block 作为兄弟挂入。
rendered_text 聚合纯文本供测试断言(替代旧 _flushed/buffer)。
"""
from __future__ import annotations

import re

from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static

from argos_agent.tui.widgets.thinking import ThinkingIndicator

_FENCE_BLOCK = re.compile(r"```[^\n]*\n.*?```\n?", re.DOTALL)  # 连吃闭围栏后的换行,块间塌缩干净


def strip_code_fences(text: str) -> str:
    """剥掉 ```...``` 完整块 + 尾部未闭合的 ```(流式中途)。"""
    text = _FENCE_BLOCK.sub("", text)
    idx = text.rfind("```")
    if idx != -1:
        text = text[:idx]
    return text.strip("\n")


class UserMessage(Static):
    DEFAULT_CSS = """
    UserMessage { color: $text-muted; padding: 0 1; }
    """
    def __init__(self, text: str) -> None:
        super().__init__(f"› {text}")
        self.add_class("user-msg")


class SystemLine(Static):
    DEFAULT_CSS = """
    SystemLine { padding: 0 1; }
    SystemLine.sys-error { color: $error; }
    SystemLine.sys-escalation { color: $warning; }
    SystemLine.sys-done { color: $success; }
    SystemLine.sys-system { color: $text-muted; }
    """
    def __init__(self, text: str, *, kind: str = "system") -> None:
        super().__init__(text)
        self.add_class(f"sys-{kind}")


class AssistantMessage(Markdown):
    DEFAULT_CSS = """
    AssistantMessage { background: transparent; margin: 0 0 1 0; padding: 0 1; }
    """
    def __init__(self) -> None:
        super().__init__("")
        self.add_class("assistant-msg")
        self._raw = ""

    def feed(self, text: str) -> None:
        self._raw += text
        self.update(strip_code_fences(self._raw))


class Transcript(VerticalScroll):
    """主对话区。流式 token 进 current AssistantMessage;system/user 行与块作为兄弟挂入。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.can_focus = False               # 不抢输入框焦点(滚动用鼠标/PageUp)
        self._current: AssistantMessage | None = None
        self._lines: list[str] = []          # 已落定文本(供 rendered_text)

    @property
    def rendered_text(self) -> str:
        parts = list(self._lines)
        if self._current is not None:
            parts.append(strip_code_fences(self._current._raw))
        return "\n".join(p for p in parts if p)

    async def user_line(self, text: str) -> None:
        self.finalize_response()
        # 非首条用户输入前插一条虚线分隔,把对话切成可读的"回合"(Task 14)。
        if self._lines:
            from textual.widgets import Rule
            await self.mount(Rule(line_style="dashed"))
        self._lines.append(f"› {text}")
        await self.mount(UserMessage(text))
        self.scroll_end(animate=False)

    async def append_token(self, text: str) -> None:
        if self._current is None:
            for sp in self.query(ThinkingIndicator):
                await sp.remove()
            self._current = AssistantMessage()
            await self.mount(self._current)
        self._current.feed(text)
        self.scroll_end(animate=False)

    def finalize_response(self) -> None:
        """当前流式段落定:记入 _lines,清 current 指针 → 下个 token 起新气泡。"""
        if self._current is not None:
            self._lines.append(strip_code_fences(self._current._raw))
            self._current = None

    async def append_line(self, text: str, *, kind: str = "system") -> None:
        self.finalize_response()
        self._lines.append(text)
        await self.mount(SystemLine(text, kind=kind))
        self.scroll_end(animate=False)

    async def mount_block(self, widget) -> None:
        self.finalize_response()
        await self.mount(widget)
        self.scroll_end(animate=False)

    async def show_thinking(self, label: str = "思考中…") -> None:
        self.finalize_response()
        await self.mount(ThinkingIndicator(label))
        self.scroll_end(animate=False)

    async def clear(self) -> None:        # /clear 用:移除所有消息
        await self.remove_children()
        self._current = None
        self._lines.clear()
