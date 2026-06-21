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

from rich.style import Style
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import Static, TextArea

from argos.i18n import t as _t
from argos.input.attachments import ImageAttachment, extract_image_paths, load_from_path

_PASTE_THRESHOLD = 10000  # >10000 字符的粘贴折成占位 chip(对齐 Claude Code)

# Rich Text 层无法引用 CSS $token 名,直接用 hex 值(与 theme.py 对应 token 保持同步)
_EYE        = "#D9A85C"   # $eye:▸ 选中光标 / 选中项名
_INK_DIM    = "#7E869C"   # $ink-dim:说明文字
_INK_FAINT  = "#525A73"   # $ink-faint:键提示行
_INK_BRIGHT = "#ECEEF5"   # $ink-bright:选中项名 bold
_RAISE_2    = "#23263A"   # $raise-2:二级浮起 — slash 菜单选中行底色块


class PromptArea(TextArea):
    """主输入框。Enter 提交;反斜杠续行;菜单可见时 ↑/↓/Tab/Enter 走 slash 菜单选择。"""

    class Submitted(Message):
        """整段提交(Enter,且非续行、非空)。app 据此起 run / 分发 slash。
        attachments:提交时从粘贴/图片侧缓冲展开出的图片附件(默认空 = 纯文本提交)。"""

        def __init__(self, text: str, attachments: list | None = None) -> None:
            self.text = text
            self.attachments: list = list(attachments or [])
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
        # 粘贴管线侧缓冲:占位 token → 全文 / 图片附件(提交时展开)。
        self._paste_store: dict[str, str] = {}
        self._image_store: dict[str, ImageAttachment] = {}
        self._paste_seq: int = 0
        self._image_seq: int = 0
        # 历史导航状态(#20):_history_idx=-1 = "当前草稿",>0 = 回溯到历史第 N 条。
        # _draft 临时保存浏览历史时的未提交草稿,方便 ↓ 回到最新状态。
        self._history_idx: int = -1
        self._draft: str = ""

    def _make_paste_token(self, text: str) -> str | None:
        """超长粘贴 → 生成占位 token 并存全文;否则 None(调用方原样内联)。"""
        if len(text) <= _PASTE_THRESHOLD:
            return None
        self._paste_seq += 1
        lines = text.count("\n")
        token = _t("tui.prompt.paste_token", n=self._paste_seq, lines=lines)
        self._paste_store[token] = text
        return token

    def register_image(self, att: ImageAttachment) -> str:
        """登记一张图片附件,返回占位 token([图片 #N])。供 app 的 Ctrl+V 动作调用。"""
        self._image_seq += 1
        token = _t("tui.prompt.image_token", n=self._image_seq)
        self._image_store[token] = att
        return token

    def _expand_submission(self, text: str) -> tuple[str, list[ImageAttachment]]:
        """提交时展开:粘贴占位符 → 全文;图片占位符 + 文本里的图片路径 → 附件列表。
        图片占位符从文本中剔除(不进 goal 文本)。非法图片/读不了 → 诚实跳过。"""
        out_text = text
        for token, full in self._paste_store.items():
            out_text = out_text.replace(token, full)
        attachments: list[ImageAttachment] = []
        for token, att in self._image_store.items():
            if token in out_text:
                attachments.append(att)
                out_text = out_text.replace(token, "")
        # 文本里直接写/拖进来的图片文件路径(attachments.load_from_path 用 ValueError 表非法)
        for path in extract_image_paths(out_text):
            try:
                attachments.append(load_from_path(path))
            except (ValueError, OSError):
                pass  # 非图/读不了:诚实跳过(不附),文本保留路径原样
        return out_text.strip(), attachments

    def _get_app_history(self) -> list[str]:
        """从宿主 App 取输入历史列表(最新在末尾);测试单挂时返空列表。"""
        try:
            return list(self.app._input_history)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — 测试单挂/无 app
            return []

    def _navigate_history(self, direction: str, history: list[str]) -> None:
        """↑ 向前(更旧)浏览历史;↓ 向后(更新 / 回草稿)。

        状态机:
          _history_idx == -1  → 当前"最新草稿"状态(未浏览历史)
          _history_idx == 0   → 最旧那条历史
          _history_idx == N-1 → 最新那条历史(N = len(history))
        """
        n = len(history)
        if n == 0:
            return
        if direction == "up":
            if self._history_idx == -1:
                # 首次向上:保存当前草稿,跳到最新历史条目
                self._draft = self.text
                self._history_idx = n - 1
            elif self._history_idx > 0:
                self._history_idx -= 1
            # 已在最旧处不再移动
            self._refill(history[self._history_idx])
        else:  # down
            if self._history_idx == -1:
                return  # 已在草稿态,无处再向下
            if self._history_idx < n - 1:
                self._history_idx += 1
                self._refill(history[self._history_idx])
            else:
                # 到达最新条目之后 → 回草稿
                self._history_idx = -1
                self._refill(self._draft)
                self._draft = ""

    def _refill(self, text: str) -> None:
        """用 text 替换编辑器内容并把光标移到末尾。"""
        self.load_text(text)
        self.move_cursor(self.document.end)

    def reset_history_nav(self) -> None:
        """提交或 clear 后重置历史导航状态。由 App 在提交后调用。"""
        self._history_idx = -1
        self._draft = ""

    def _menu(self) -> "SlashMenu | None":
        try:
            return self.app.query_one("#slash-menu", SlashMenu)
        except Exception:  # noqa: BLE001 — 测试单挂 PromptArea 时无菜单
            return None

    async def _on_paste(self, event: events.Paste) -> None:
        """拦括号粘贴:超长 → 占位 chip + 侧缓冲;否则原样内联。
        全程自己 insert + stop,完全接管粘贴行为(不依赖 TextArea 默认 _on_paste)。"""
        event.stop()
        event.prevent_default()
        token = self._make_paste_token(event.text)
        self.insert(token if token is not None else event.text)

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "space" and not self.text:
            # 空输入框按空格 = 语音开关(对齐 spec §6.1);有字时空格正常输入。
            event.stop()
            event.prevent_default()
            self.post_message(self.VoiceToggle())
            return
        menu = self._menu()
        menu_active = menu is not None and menu.display and menu.has_matches
        if event.key in ("up", "down"):
            if menu_active:
                event.stop()
                event.prevent_default()
                menu.move(-1 if event.key == "up" else 1)
                return
            # slash 菜单未开:↑/↓ 走输入历史导航(#20)
            history = self._get_app_history()
            if history:
                event.stop()
                event.prevent_default()
                self._navigate_history(event.key, history)
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
                    self.reset_history_nav()
                    self.clear()
                    return
            stripped = text.strip()
            if stripped:
                expanded, attachments = self._expand_submission(stripped)
                if expanded or attachments:
                    self.post_message(self.Submitted(expanded, attachments))
                    self._paste_store.clear()
                    self._image_store.clear()
                    self.reset_history_nav()
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

        选中行:▸ $eye bold + 名 $ink-bright bold + 整行底色 $raise-2;
        其余:无前缀 + 名 $ink-dim,无底色。
        说明文字 $ink-dim;键提示行 $ink-faint。
        """
        t = Text()
        for i, (name, desc) in enumerate(self._matches):
            cur = i == self._cursor
            if cur:
                # 整行(前缀 + 命令名 + 描述)都带 $raise-2 底色块,对齐设计「选中行高亮块」
                t.append("▸ ", style=Style(color=_EYE, bgcolor=_RAISE_2, bold=True))
                t.append(f"/{name:<16}", style=Style(color=_INK_BRIGHT, bgcolor=_RAISE_2, bold=True))
                t.append(f" {desc}", style=Style(color=_INK_DIM, bgcolor=_RAISE_2))
            else:
                t.append("  ", style=None)
                t.append(f"/{name:<16}", style=_INK_DIM)
                t.append(f" {desc}", style=_INK_DIM)
            t.append("\n")
        t.append(_t("tui.slash_menu.nav_hint"), style=_INK_FAINT)
        self.update(t)

    def hide(self) -> None:
        self.display = False
