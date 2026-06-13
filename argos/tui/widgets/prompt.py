"""多行输入框 PromptArea + slash 命令菜单 SlashMenu(TUI v2 spec §6.1)。

为什么不再用 Input:
  · Input 只能单行;用户要多行输入(贴代码、写多行目标)。
  · TextArea 是真多行编辑器;默认 Enter 插入换行,这里覆盖为「Enter 提交」。

换行怎么打(终端无关,不依赖 Kitty / Shift+Enter —— 本项目禁用了 Kitty 协议、修过输入 bug,
不能赌修饰键能被识别):
  · 行尾打反斜杠 `\\` 再回车 = 续行:去掉反斜杠、插入真换行、继续编辑(readline/shell 同款 idiom)。
  · 直接粘贴多行文本:原样进入(粘贴不是逐键 Enter)。
高度随行数自增长(1..8 行),超出内部滚动。

slash 菜单导航(TUI v2):菜单可见时 ↑/↓ 移动 ▸ 高亮,Tab/Enter 补全/执行【选中项】
(不再只能补第一项);Esc 收起(app 级 Esc 已有此分支)。
"""
from __future__ import annotations

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea

# Rich Text 层无法引用 CSS $token 名,直接用 hex 值(与 theme.py 对应 token 保持同步)
_EYE        = "#D9A85C"   # $eye:▸ 选中光标 / 选中项名
_INK_DIM    = "#7E869C"   # $ink-dim:说明文字
_INK_FAINT  = "#525A73"   # $ink-faint:键提示行
_INK_BRIGHT = "#ECEEF5"   # $ink-bright:选中项名 bold


class PromptArea(TextArea):
    """主输入框。Enter 提交;反斜杠续行;菜单可见时 ↑/↓/Tab/Enter 走 slash 菜单选择。"""

    class Submitted(Message):
        """整段提交(Enter,且非续行、非空)。app 据此起 run / 分发 slash。"""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    class VoiceToggle(Message):
        """空框按空格:请求 app 开/停录音。app 在 on_prompt_area_voice_toggle 处理。"""

    DEFAULT_CSS = """
    PromptArea { height: auto; max-height: 8; background: $well; }
    """

    def __init__(self, **kwargs) -> None:
        # soft_wrap:长行折行不横向滚动;无行号;tab_behavior=focus 让我们能在 _on_key 接管 Tab 做补全;
        # compact:去掉编辑器的额外 gutter/留白,贴近"一行输入框"观感。
        super().__init__(
            soft_wrap=True, show_line_numbers=False, tab_behavior="focus", compact=True, **kwargs
        )

    def _menu(self) -> "SlashMenu | None":
        try:
            return self.app.query_one("#slash-menu", SlashMenu)
        except Exception:  # noqa: BLE001 — 测试单挂 PromptArea 时无菜单
            return None

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "space" and not self.text:
            # 空输入框按空格 = 语音开关(对齐 spec §6.1);有字时空格正常输入。
            event.stop()
            event.prevent_default()
            self.post_message(self.VoiceToggle())
            return
        menu = self._menu()
        menu_active = menu is not None and menu.display and menu.has_matches
        if menu_active and event.key in ("up", "down"):
            event.stop()
            event.prevent_default()
            menu.move(-1 if event.key == "up" else 1)
            return
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            text = self.text
            if text.endswith("\\"):
                # 行尾反斜杠 → 续行:替换成真换行,光标移到末尾继续输入。
                self.load_text(text[:-1] + "\n")
                self.move_cursor(self.document.end)
                return
            if menu_active:
                # 菜单可见:Enter 执行【选中】命令(文本是裸 /前缀 → 替换为选中项再提交)。
                sel = menu.selected()
                if sel is not None:
                    self.post_message(self.Submitted(f"/{sel}"))
                    self.clear()
                    return
            stripped = text.strip()
            if stripped:
                self.post_message(self.Submitted(stripped))
                self.clear()
            return
        if event.key == "tab":
            if menu_active:
                # slash 补全:Tab 补到【选中】命令(默认首项,↑↓ 可改)。
                sel = menu.selected()
                if sel is not None:
                    event.stop()
                    event.prevent_default()
                    self.load_text(f"/{sel} ")
                    self.move_cursor(self.document.end)
                    return
            # 非 slash:交还默认(焦点切换),不拦。
        await super()._on_key(event)


class SlashMenu(Static):
    """slash 命令提示菜单:输入以 / 开头且未带参数时,列出匹配命令 + 说明。
    ▸ 高亮当前选中项(↑↓ 移动,Tab 补全,Enter 执行);非聚焦,由 PromptArea 转发按键。"""

    DEFAULT_CSS = """
    SlashMenu {
        display: none;
        height: auto; max-height: 10;
        margin: 0 2; padding: 0 1;
        background: $raise; border: round $hairline-lit;
    }
    SlashMenu .menu-selected {
        background: $raise-2;
        color: $ink-bright;
        text-style: bold;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self._matches: list[tuple[str, str]] = []
        self._cursor = 0

    @property
    def has_matches(self) -> bool:
        return bool(self._matches)

    def selected(self) -> str | None:
        """当前 ▸ 选中的命令名(无匹配 → None)。"""
        if not self._matches:
            return None
        return self._matches[self._cursor][0]

    def move(self, delta: int) -> None:
        """↑↓ 移动选中项(循环);由 PromptArea 转发调用。"""
        if not self._matches:
            return
        self._cursor = (self._cursor + delta) % len(self._matches)
        self._render_items()

    def show_matches(self, matches: list[tuple[str, str]]) -> None:
        """有匹配则渲染并显示;无匹配则隐藏(诚实:不在非 slash / 无匹配时占屏)。
        匹配集变化时光标回到首项(避免越界/错位)。"""
        if matches != self._matches:
            self._cursor = 0
        self._matches = list(matches)
        if not self._matches:
            self.display = False
            return
        self._render_items()
        self.display = True

    def _render_items(self) -> None:
        """渲染 slash 菜单条目。

        选中行:▸ $eye bold + 名 $ink-bright bold;其余:无前缀 + 名 $ink-dim。
        说明文字 $ink-dim;键提示行 $ink-faint。
        """
        t = Text()
        for i, (name, desc) in enumerate(self._matches):
            cur = i == self._cursor
            if cur:
                t.append("▸ ", style=f"bold {_EYE}")
                t.append(f"/{name:<16}", style=f"bold {_INK_BRIGHT}")
            else:
                t.append("  ", style=None)
                t.append(f"/{name:<16}", style=_INK_DIM)
            t.append(f" {desc}", style=_INK_DIM)
            t.append("\n")
        t.append("  ↑↓ 选择 · ↹ 补全 · ↵ 执行", style=_INK_FAINT)
        self.update(t)

    def hide(self) -> None:
        self.display = False
