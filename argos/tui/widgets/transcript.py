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

from argos.i18n import t
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

    # 节流间隔(finding #31):每 40ms 刷新一次,避免每 token 都全量 re-render(O(n²))。
    _FLUSH_INTERVAL_MS: int = 40

    def __init__(self) -> None:
        super().__init__("")
        self.add_class("assistant-msg")
        self._raw = ""           # 已积累全文
        self._pending = False    # 有未刷新增量待 flush

    def feed(self, text: str) -> None:
        """积累流式 token(finding #31:不再逐 token 调 Markdown.update)。

        首个 token 同步触发一次 update(让用户立刻看到内容),之后靠 set_interval
        定时刷新。定时器在 on_mount 里注册,使用 _pending 标志避免空刷。
        """
        first_token = not self._raw   # 首 token 前 _raw 为空
        self._raw += text
        self._pending = True
        if first_token:
            # 首 token 立即渲染,让用户不感知延迟
            self._flush()

    def _flush(self) -> None:
        """将当前 _raw 渲染到 Markdown 组件(幂等,可重入)。"""
        if not self._pending:
            return
        self._pending = False
        self.update(strip_code_fences(self._raw))

    def on_mount(self) -> None:
        """挂载后启动周期 flush 定时器(finding #31)。"""
        self.set_interval(self._FLUSH_INTERVAL_MS / 1000.0, self._flush)


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
        # 防御:上面的 await(sp.remove / mount)会让出事件循环,期间并发的 finalize_response()
        # (show_thinking / append_line / mount_block 都会调,清 self._current=None)可能把它清空 →
        # 直接 self._current.feed 会 'NoneType' has no attribute 'feed' 崩掉整个 TUI worker
        # (2026-06-18 真机:工具修好后模型 streaming 走得更远才暴露此潜伏竞态)。重建后再喂。
        if self._current is None:
            self._current = AssistantMessage()
            if self.is_attached:
                await self.mount(self._current)
        target = self._current   # 局部引用:即便重建后再被并发清空,也喂进有效气泡而非 None
        if target is not None:
            target.feed(text)
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

    async def show_thinking(self, label: str | None = None) -> None:
        self.finalize_response()
        if not self.is_attached:
            return
        await self.mount(ThinkingIndicator(label if label is not None else t("core2.transcript.thinking")))
        self._stick_to_bottom()

    async def clear(self) -> None:        # /clear 用:移除所有消息
        await self.remove_children()
        self._current = None
        self._lines.clear()
