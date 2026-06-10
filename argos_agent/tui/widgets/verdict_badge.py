"""VerdictBadge:三态 verify 行(TUI v2 spec §3.2,契约 §6.1 fail-closed)。

▌ verify passed / ▌ verify FAILED / ▌ 无法验证 —— 扁平行,▌ 与正文同状态色。
"无法验证"绝不显成 passed(不变量 §12.5);self-verified 的 passed 降黄、显式标注(E4 防火墙)。
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from argos_agent.core.types import Verdict, VerdictStatus

_LABEL = {"passed": "verify passed", "failed": "verify FAILED", "unverifiable": "无法验证"}


class VerdictBadge(Static):
    """show(verdict) 后渲染对应三态行。三态着色色相分明(诚实硬约束)。"""

    DEFAULT_CSS = """
    VerdictBadge { padding: 0 1; margin: 0 0 1 0; height: auto; }
    VerdictBadge.verdict-passed       { color: $success; }
    VerdictBadge.verdict-failed       { color: $error; text-style: bold; }
    VerdictBadge.verdict-unverifiable { color: $warning; }
    VerdictBadge.verdict-self         { color: $warning; }
    """

    status: reactive[VerdictStatus | None] = reactive(None)

    def __init__(self, **kwargs) -> None:
        # markup=False:verdict.detail 是 verify/pytest 真实输出(常含 `[...]`:断言 repr、
        # 参数化用例名、列表),不可被当 Rich markup 解析,否则崩 TUI。
        super().__init__("", markup=False, **kwargs)
        self.render_text: str = ""

    def watch_status(self, value: str) -> None:
        # 三态各自独占一个 class，切换时清掉另两态——色相绝不混淆(passed绝不显成 failed/unverifiable)。
        for s in ("passed", "failed", "unverifiable"):
            self.set_class(value == s, f"verdict-{s}")

    def show(self, verdict: Verdict) -> None:
        label = _LABEL[verdict.status]
        cmd = verdict.verify_cmd or "—"
        # E4 防火墙:self_verified=True 的 passed 必须显式标 "self-verified" 而非裸 "verify",
        # 颜色降为 warning(黄),绝不冒充"用户级"绿。
        if verdict.status == "passed" and getattr(verdict, "self_verified", False):
            self.render_text = (
                f"▌ self-verified (较弱:系统自造测试;非用户级 verify): {cmd} → {verdict.detail}"
            )
            for s in ("passed", "failed", "unverifiable"):
                self.set_class(False, f"verdict-{s}")
            self.set_class(True, "verdict-self")
            self.status = verdict.status  # 仍触发 watch 走色相基础
            self.set_class(False, "verdict-passed")  # watch 会重挂 passed,显式压掉(黄不冒充绿)
            self.update(self.render_text)
            return
        self.set_class(False, "verdict-self")
        if verdict.status == "unverifiable" and verdict.tampered:
            self.render_text = f"▌ {label}: 受保护文件被改 {verdict.tampered} — {verdict.detail}"
        else:
            self.render_text = f"▌ {label}: {cmd} → {verdict.detail}"
        self.status = verdict.status  # 触发 watch
        self.update(self.render_text)
