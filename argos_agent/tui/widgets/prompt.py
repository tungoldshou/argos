"""多行输入框 PromptArea + slash 命令菜单 SlashMenu(取代单行 Input)。

为什么不再用 Input:
  · Input 只能单行;用户要多行输入(贴代码、写多行目标)。
  · TextArea 是真多行编辑器;默认 Enter 插入换行,这里覆盖为「Enter 提交」。

换行怎么打(终端无关,不依赖 Kitty / Shift+Enter —— 本项目禁用了 Kitty 协议、修过输入 bug,
不能赌修饰键能被识别):
  · 行尾打反斜杠 `\\` 再回车 = 续行:去掉反斜杠、插入真换行、继续编辑(readline/shell 同款 idiom)。
  · 直接粘贴多行文本:原样进入(粘贴不是逐键 Enter)。
高度随行数自增长(1..8 行),超出内部滚动。
"""
from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea


class PromptArea(TextArea):
    """主输入框。Enter 提交;反斜杠续行;Tab 在 slash 输入时补全到首个匹配命令。"""

    class Submitted(Message):
        """整段提交(Enter,且非续行、非空)。app 据此起 run / 分发 slash。"""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    DEFAULT_CSS = """
    PromptArea { height: auto; max-height: 8; }
    """

    def __init__(self, **kwargs) -> None:
        # soft_wrap:长行折行不横向滚动;无行号;tab_behavior=focus 让我们能在 _on_key 接管 Tab 做补全;
        # compact:去掉编辑器的额外 gutter/留白,贴近"一行输入框"观感。
        super().__init__(
            soft_wrap=True, show_line_numbers=False, tab_behavior="focus", compact=True, **kwargs
        )

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            text = self.text
            if text.endswith("\\"):
                # 行尾反斜杠 → 续行:替换成真换行,光标移到末尾继续输入。
                self.load_text(text[:-1] + "\n")
                self.move_cursor(self.document.end)
                return
            stripped = text.strip()
            if stripped:
                self.post_message(self.Submitted(stripped))
                self.clear()
            return
        if event.key == "tab":
            from argos_agent.tui.commands import match_commands

            matches = match_commands(self.text)
            if matches:
                # slash 补全:Tab 直接补到首个匹配命令(`/he` → `/help `)。
                event.stop()
                event.prevent_default()
                self.load_text(f"/{matches[0][0]} ")
                self.move_cursor(self.document.end)
                return
            # 非 slash:交还默认(焦点切换),不拦。
        await super()._on_key(event)


class SlashMenu(Static):
    """slash 命令提示菜单:输入以 / 开头且未带参数时,列出匹配命令 + 说明(首项标 ▸,Tab 补全)。
    非聚焦、纯提示 —— 满足"打 / 能看到有哪些命令";继续输入收窄,Tab 补全首项,Enter 跑完整命令。"""

    DEFAULT_CSS = """
    SlashMenu {
        display: none;
        height: auto; max-height: 10;
        margin: 0 1; padding: 0 1;
        background: $surface; border: round $primary; color: $foreground;
    }
    """

    def __init__(self, **kwargs) -> None:
        # markup=False:命令说明是定值,但统一关 markup 与全 TUI 一致(防任意文本里的 `[...]` 崩)。
        super().__init__("", markup=False, **kwargs)

    def show_matches(self, matches: list[tuple[str, str]]) -> None:
        """有匹配则渲染并显示;无匹配则隐藏(诚实:不在非 slash / 无匹配时占屏)。"""
        if not matches:
            self.display = False
            return
        lines = [f"{'▸' if i == 0 else ' '} /{name:<8} {desc}" for i, (name, desc) in enumerate(matches)]
        lines.append("  ↹ Tab 补全 · ↵ 回车执行")
        self.update("\n".join(lines))
        self.display = True

    def hide(self) -> None:
        self.display = False
