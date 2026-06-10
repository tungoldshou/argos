# argos_agent/tui/widgets/code_action.py
"""代码动作块(TUI v2 spec §3.1):扁平无边框,Claude Code 式。

⏺ python · step N      ← 橙 ⏺ + muted 标签
  <syntax 高亮代码>      ← 2 空格缩进;>8 行折叠为头 6 行 + "… +N 行"
  ⎿ ✓ 结果              ← ✓ muted / ✗ 红;>12 行折叠
"""
from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

_ACCENT = "#E0AF68"
_MUTED = "#565F89"
_CODE_MAX = 8    # 超过则折叠
_CODE_HEAD = 6   # 折叠时保留的头部行数


class CodeActionBlock(Vertical):
    DEFAULT_CSS = """
    CodeActionBlock { height: auto; margin: 0 1 1 1; }
    CodeActionBlock #code { padding: 0 0 0 2; }
    CodeActionBlock #code-fold { color: $text-muted; padding: 0 0 0 2; }
    CodeActionBlock #result { color: $text-muted; padding: 0 0 0 2; }
    CodeActionBlock.ok-false #result { color: $error; }
    """
    ok: reactive[bool | None] = reactive(None)

    def __init__(self, *, code: str, step: int) -> None:
        super().__init__()
        self._code = code
        self._step = step

    def compose(self) -> ComposeResult:
        header = Text.assemble(("⏺ ", f"bold {_ACCENT}"), (f"python · step {self._step}", _MUTED))
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
        yield Static("⎿ 运行中…", id="result", markup=False)

    def set_result(self, *, stdout: str, value_repr: str, exc: str, ok: bool) -> None:
        self.ok = ok
        body = exc if (not ok and exc) else (stdout or "")
        if value_repr:
            body += f"\n[返回值] {value_repr}"
        text = body.strip() or ("完成,无输出" if ok else "执行异常")
        # 折叠长输出(头尾各留,中间省略)
        lines = text.splitlines()
        if len(lines) > 12:
            text = "\n".join(lines[:8]) + f"\n… +{len(lines) - 8} 行"
        self.query_one("#result", Static).update(f"⎿ {'✓' if ok else '✗'} {text}")

    def watch_ok(self, value: bool | None) -> None:
        self.set_class(value is False, "ok-false")
