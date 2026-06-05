# argos_agent/tui/widgets/code_action.py
"""代码动作块:⏺ header + Syntax(monokai) 高亮代码 + ⎿ 结果(spec §widget 改造)。"""
from __future__ import annotations

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static


class CodeActionBlock(Vertical):
    DEFAULT_CSS = """
    CodeActionBlock {
        border: round $panel;
        border-title-color: $accent;
        padding: 0 1;
        margin: 0 1 1 1;
        height: auto;
    }
    CodeActionBlock #result { color: $text-muted; }
    CodeActionBlock.ok-false #result { color: $error; }
    """
    ok: reactive[bool | None] = reactive(None)

    def __init__(self, *, code: str, step: int) -> None:
        super().__init__()
        self._code = code
        self._step = step
        self.border_title = f"⏺ 代码动作 · step {step}"

    def compose(self) -> ComposeResult:
        yield Static(Syntax(self._code, "python", theme="monokai",
                            line_numbers=False, word_wrap=True), id="code")
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
