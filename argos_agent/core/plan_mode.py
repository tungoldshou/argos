"""Plan mode 核心(spec §2.1-§2.2)。

包含:
- `PlanModeError`:plan mode 期间调用沙箱工具抛
- `PlanExitDecision`:4 选项审批结果(frozen dataclass)
- `set_plan_mode` / `is_plan_mode`:模块级 plan mode 状态(供沙箱工具 dispatcher 守卫)
- `EnterPlanMode` / `ExitPlanMode`:模式切换 host 端入口
- `PlanRenderer`:plan 阶段产出 → user-facing markdown
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class PlanModeError(Exception):
    """plan mode 期间调用沙箱工具抛。"""


PlanExitAction = Literal["approve_start", "approve_accept_edits", "keep_planning", "refine"]
_VALID_ACTIONS = ("approve_start", "approve_accept_edits", "keep_planning", "refine")


_plan_mode_active: bool = False  # 模块级 plan mode 状态(MVP 简化)


def set_plan_mode(active: bool) -> None:
    """设置模块级 plan mode 状态(由 EnterPlanMode / ExitPlanMode 调用)。"""
    global _plan_mode_active
    _plan_mode_active = active


def is_plan_mode() -> bool:
    """返回当前 plan mode 状态(供沙箱工具 dispatcher 守卫)。"""
    return _plan_mode_active


@dataclass(frozen=True)
class PlanExitDecision:
    """`ExitPlanMode` 工具的 4 选项审批结果。"""
    action: PlanExitAction
    feedback: str | None = None

    def __post_init__(self):
        if self.action not in _VALID_ACTIONS:
            raise ValueError(
                f"PlanExitDecision.action 必须是 {_VALID_ACTIONS} 之一,收到 {self.action!r}"
            )


def EnterPlanMode(loop) -> str:
    """切到 plan-only 模式(等用户审批后 ExitPlanMode 继续)。

    Args:
        loop: AgentLoop 实例(只需 `_busy` / `mode` / `_emit_phase` 3 个属性)

    Returns:
        用户可见消息(成功/错误)
    """
    if getattr(loop, "_busy", False):
        return "错误:当前 run 正在跑,请先 Esc 打断,再 /plan。"
    if getattr(loop, "mode", "act") == "plan":
        return "已在 plan mode。"
    loop.mode = "plan"
    set_plan_mode(True)  # 模块级标记(供沙箱工具 dispatcher 守卫)
    # emit PhaseChange 事件(给前端,标题/边缘光变色)
    if hasattr(loop, "_emit_phase"):
        loop._emit_phase("plan")
    return "已切到 plan mode。"



def ExitPlanMode(loop, action: str, feedback: str | None = None) -> str:
    """退出 plan mode,根据 action 决定下一步。

    Args:
        loop: AgentLoop 实例(只需 `mode` / `_plan_decision` / `_plan_decision_event` 属性)
        action: 4 选项之一(approve_start / approve_accept_edits / keep_planning / refine)
        feedback: 仅 refine 时用(不能为空)

    Returns:
        用户可见消息

    不变量(spec §2.5 铁证 + 防 Refine→Approve 静默兜底 bug):
    校验失败 → 返错误串 + mode/decision/event 全部不动(让 caller 知道失败真发生了)。
    校验成功 → mode 切回 act + 存 decision + 【主动 set _plan_decision_event】唤醒 loop 的 await。
    历史上 TUI 端在 ExitPlanMode 失败后仍 set event,导致 loop 的 `_plan_decision is None`
    兜底成 `approve_start` —— 用户点 Refine 被静默改成 Approve。现在由本函数原子地
    "校验-切 mode-存 decision-唤醒 await"一次完成,caller 不需记忆设 event。
    """
    if getattr(loop, "mode", "act") != "plan":
        return "错误:当前不在 plan mode。"
    if action == "refine" and not (feedback and feedback.strip()):
        return "错误:refine 需要 feedback。"
    try:
        decision = PlanExitDecision(action=action, feedback=feedback)
    except ValueError as e:
        return f"错误:{e}"
    loop.mode = "act"
    set_plan_mode(False)  # 模块级清掉
    loop._plan_decision = decision
    # 主动唤醒 loop 的 await(无 event 属性 = 非 loop 路径,例如单测 stub,跳过)。
    ev = getattr(loop, "_plan_decision_event", None)
    if ev is not None:
        ev.set()
    return f"已退出 plan mode,action={action}。"


class PlanRenderer:
    """把 plan 阶段产出拼成 user-facing markdown plan 文档(spec §2.3)。"""

    @staticmethod
    def render(
        goal: str,
        todos: list[dict],
        tool_calls: list[dict],
        risks: list[str] | None = None,
    ) -> str:
        """拼 markdown plan 文档。"""
        title = goal.strip()[:50] + ("..." if len(goal.strip()) > 50 else "")
        lines = [f"# Plan: {title}", ""]

        # 任务分解
        lines.append("## 任务分解")
        if todos:
            for t in todos:
                step = t.get("step", "?")
                desc = t.get("description", "")
                tool = t.get("tool", "")
                tool_part = f"(tool: {tool})" if tool else ""
                lines.append(f"- [ ] **step {step}**: {desc} {tool_part}")
        else:
            lines.append("- (无具体任务分解)")
        lines.append("")

        # 涉及文件(从 tool_calls 抽)
        files = set()
        for tc in tool_calls:
            if tc.get("tool") in ("write_file", "edit_file", "read_file"):
                p = tc.get("args", {}).get("path")
                if p:
                    files.add(p)
        if files:
            lines.append("## 涉及文件")
            for f in sorted(files):
                lines.append(f"- `{f}`")
            lines.append("")

        # 风险
        if risks:
            lines.append("## 风险")
            for r in risks:
                lines.append(f"- {r}")
            lines.append("")

        # 工具调用序列
        if tool_calls:
            lines.append("## 工具调用序列")
            for tc in tool_calls:
                tool = tc.get("tool", "?")
                args = tc.get("args", {})
                args_str = ", ".join(f"{k}={v!r}" for k, v in args.items()) if args else ""
                lines.append(f"- `{tool}({args_str})`")
            lines.append("")

        # 审批
        lines.extend([
            "## 审批",
            "请选择下一步:",
            "- ✅ **Approve and start** — 全权限,继续 act",
            "- ✏️ **Approve and accept edits** — 写/编辑工具自动批,其他按现有审批",
            "- 🔄 **Keep planning** — 继续 plan 阶段",
            "- 📝 **Refine with feedback** — 提供补充上下文后重新 plan",
        ])
        return "\n".join(lines)
