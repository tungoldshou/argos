# argos/tui/widgets/code_action.py
"""代码动作块(TUI v2 spec §3.1):扁平无边框,Claude Code 式。

⏺ python · step N      ← 橙 ⏺ + muted 标签
  <syntax 高亮代码>      ← 2 空格缩进;>8 行折叠为头 6 行 + "… +N 行"
  └ ◕ 结果              ← ◕ 阅毕眼 $pass / ◉ 红瞳 $fail;>12 行折叠
"""
from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

# theme.py 同源颜色常量,仅供 Rich Text.assemble() 用(Rich style 无法引用 CSS 变量)
_EYE = "#D9A85C"     # = $eye:金系主强调
_INK_DIM = "#7E869C" # = $ink-dim:次要文字/元信息/step 号
_CODE_MAX = 8    # 超过则折叠
_CODE_HEAD = 6   # 折叠时保留的头部行数


class CodeActionBlock(Vertical):
    """代码动作块(spec §4.4):扁平无边框,$raise 底色浮起,⏺ 标头 + Syntax + 结果行。

    结果行 ok=True → `└ ◕ 执行完成`(◕ 阅毕眼,$pass);
           ok=False → `└ ◉ FileNotFoundError`(◉ 红瞳,$fail)。
    """
    DEFAULT_CSS = """
    CodeActionBlock { height: auto; margin: 0 0 1 0; background: $raise; padding: 0 2; }
    CodeActionBlock #code { padding: 0 0 0 2; }
    CodeActionBlock #code-fold { color: $ink-ghost; padding: 0 0 0 2; }
    CodeActionBlock #result { color: $ink-faint; padding: 0 0 0 2; }
    CodeActionBlock.ok-false #result { color: $fail; }
    """
    ok: reactive[bool | None] = reactive(None)

    def __init__(self, *, code: str, step: int) -> None:
        super().__init__()
        self._code = code
        self._step = step

    def compose(self) -> ComposeResult:
        # ⏺ 用 $eye 金色;标签用 $ink-dim(Rich style 不能引用 CSS 变量,直接用同源 hex)
        header = Text.assemble(("⏺ ", f"bold {_EYE}"), (f"python · step {self._step}", _INK_DIM))
        yield Static(header, id="header")
        lines = self._code.splitlines()
        shown = self._code
        folded = 0
        if len(lines) > _CODE_MAX:
            shown = "\n".join(lines[:_CODE_HEAD])
            folded = len(lines) - _CODE_HEAD
        yield Static(Syntax(shown, "python", theme="monokai",
                            line_numbers=False, word_wrap=True), id="code")
        if folded:
            yield Static(f"… +{folded} 行", id="code-fold", markup=False)
        # markup=False:结果区显工具/命令真实输出(value_repr/stdout 常含 `[...]`,如
        # 浏览器返回 `已点击 "input[value='x']"`)—— 绝不能当 Rich markup 解析,否则崩 TUI。
        yield Static("└ 运行中…", id="result", markup=False)

    def set_result(self, *, stdout: str, value_repr: str, exc: str, ok: bool) -> None:
        """填入执行结果。ok=True → ◕ 阅毕眼;ok=False → ◉ 红瞳。"""
        self.ok = ok
        body = exc if (not ok and exc) else (stdout or "")
        if value_repr:
            body += f"\n[返回值] {value_repr}"
        text = body.strip() or ("执行完成" if ok else "执行异常")
        # 折叠长输出(头尾各留,中间省略)
        lines = text.splitlines()
        if len(lines) > 12:
            text = "\n".join(lines[:8]) + f"\n… +{len(lines) - 8} 行"
        # ◕ 阅毕眼(ok=True,$pass);◉ 红瞳(ok=False,$fail)
        glyph = "◕" if ok else "◉"
        self.query_one("#result", Static).update(f"└ {glyph} {text}")

    def watch_ok(self, value: bool | None) -> None:
        self.set_class(value is False, "ok-false")
