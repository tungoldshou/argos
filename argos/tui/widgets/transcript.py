# argos/tui/widgets/transcript.py
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

from argos.tui.widgets.thinking import ThinkingIndicator

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
    UserMessage { color: $ink-dim; padding: 0 2; }
    """
    def __init__(self, text: str) -> None:
        # markup=False:用户输入是任意文本,含 `[...]`(列表/正则/类型注解)绝不能被当
        # Rich 控制台 markup 解析 —— 否则非法标签直接崩 TUI(真终端实测:输入带方括号即炸)。
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
        # markup=False:系统/错误/工具行可能含工具输出里的 `[...]`,不可被当 markup 解析(防崩)。
        super().__init__(text, markup=False)
        self.add_class(f"sys-{kind}")


class AssistantMessage(Markdown):
    DEFAULT_CSS = """
    AssistantMessage { background: transparent; margin: 0 0 1 0; padding: 0 2; }
    AssistantMessage .markdown--em { color: $ink-bright; }
    AssistantMessage .markdown-strong { color: $ink-bright; }
    """
    def __init__(self) -> None:
        super().__init__("")
        self.add_class("assistant-msg")
        self._raw = ""

    def feed(self, text: str) -> None:
        self._raw += text
        self.update(strip_code_fences(self._raw))


class Transcript(VerticalScroll):
    """主对话区。流式 token 进 current AssistantMessage;system/user 行与块作为兄弟挂入。

    DEFAULT_CSS 为 Transcript 本身设 $stream 底色(与右栏 $well 靠色差分栏,无需竖线)。
    """
    DEFAULT_CSS = """
    Transcript { background: $stream; }
    """

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

    def _stick_to_bottom(self) -> None:
        """仅当用户已停在(或几乎停在)底部时才跟随到底——否则保留用户的滚动位置。
        修复"滚不动":此前每个流式 token / 每条系统行都无条件 scroll_end,用户向上翻历史
        会被下一个事件即时拽回底部,体感=滚动条失效。判据:距底 ≤2 行算"在底部跟随"。"""
        if self.max_scroll_y - self.scroll_offset.y <= 2:
            self.scroll_end(animate=False)

    async def user_line(self, text: str) -> None:
        self.finalize_response()
        # 非首条用户输入前插一条虚线分隔,把对话切成可读的"回合"(Task 14)。
        if self._lines and self.is_attached:
            from textual.widgets import Rule
            await self.mount(Rule(line_style="dashed"))
        self._lines.append(f"› {text}")
        if self.is_attached:
            await self.mount(UserMessage(text))
            self.scroll_end(animate=False)   # 用户刚提交新目标 → 无条件跳到底看自己的输入

    async def append_token(self, text: str) -> None:
        if self._current is None:
            for sp in self.query(ThinkingIndicator):
                await sp.remove()
            self._current = AssistantMessage()
            if self.is_attached:
                await self.mount(self._current)
        self._current.feed(text)
        if self.is_attached:
            self._stick_to_bottom()

    def finalize_response(self) -> None:
        """当前流式段落定:记入 _lines,清 current 指针 → 下个 token 起新气泡。"""
        if self._current is not None:
            self._lines.append(strip_code_fences(self._current._raw))
            self._current = None

    async def append_line(self, text: str, *, kind: str = "system") -> None:
        self.finalize_response()
        self._lines.append(text)
        # 未挂载到 app 时(单测里 ArgosApp.__new__ 绕开 __init__)只更新 _lines,
        # 跳过视觉 mount —— 这样 rendered_text 仍可断言,生产路径(widgets 必挂)不受影响。
        if self.is_attached:
            await self.mount(SystemLine(text, kind=kind))
            self._stick_to_bottom()

    async def mount_block(self, widget) -> None:
        self.finalize_response()
        if not self.is_attached:
            return
        await self.mount(widget)
        self._stick_to_bottom()

    async def show_thinking(self, label: str = "思考中…") -> None:
        self.finalize_response()
        if not self.is_attached:
            return
        await self.mount(ThinkingIndicator(label))
        self._stick_to_bottom()

    async def clear(self) -> None:        # /clear 用:移除所有消息
        await self.remove_children()
        self._current = None
        self._lines.clear()
