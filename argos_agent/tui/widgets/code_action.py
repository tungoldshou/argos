"""CodeActionBlock:CodeAct 核心可视化(spec §4.1/§4.2)——代码块 + 可折叠输出(stdout/返回值/异常)。"""
from __future__ import annotations

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static


class CodeActionBlock(Vertical):
    """一步 code-action。set_result 灌入执行结果后展开输出区并标记成功/失败。"""

    ok: reactive[bool | None] = reactive(None)
    collapsed: reactive[bool] = reactive(True)

    def __init__(self, code: str, step: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.code = code
        self.step = step
        self.output_text: str = ""

    def compose(self) -> ComposeResult:
        yield Static(self._code_header(), id="ca-header")
        yield Static(Syntax(self.code, "python", theme="ansi_dark", word_wrap=True), id="ca-code")
        yield Static("", id="ca-output")

    def _code_header(self) -> str:
        return f"┌ code-action ▸ python  (step {self.step})"

    def set_result(self, *, stdout: str, value_repr: str, exc: str, ok: bool) -> None:
        """code_result 到达:拼输出文本,展开,标记 ok。"""
        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if value_repr:
            parts.append(f"→ {value_repr}")
        if exc:
            parts.append(f"✗ {exc}")
        self.output_text = "\n".join(parts) if parts else "(no output)"
        self.ok = ok
        self.collapsed = False

    def watch_collapsed(self, collapsed: bool) -> None:
        if not self.is_mounted:
            return
        out = self.query_one("#ca-output", Static)
        prefix = "└ ▸ output:" if not collapsed else "└ ▸ output: …"
        body = "" if collapsed else self.output_text
        out.update(f"{prefix}\n{body}" if body else prefix)

    def watch_ok(self, ok: bool | None) -> None:
        if not self.is_mounted or ok is None:
            return
        self.query_one("#ca-header", Static).update(
            self._code_header() + ("  ✓" if ok else "  ✗")
        )
