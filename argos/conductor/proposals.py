"""ProactiveSuggestion + propose() — 主动建议（设计 §9 自治面）。

核心不变量（契约级，构造时断言）：
  requires_confirmation 永远为 True —— 建议永远要用户确认，绝不自动执行。

ProactiveSuggestion 由 ConductorEngine.tick() 产出，
由信任面（TrustFace / ApprovalGate）持有，等用户批准后才转为 create_run()。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from argos.conductor.orders import OrderAction

if TYPE_CHECKING:
    from argos.conductor.orders import StandingOrder


def _new_suggestion_id() -> str:
    """生成新 ProactiveSuggestion ID（uuid4，不含连字符）。"""
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class ProactiveSuggestion:
    """一条主动建议（frozen dataclass — 不可变、可哈希）。

    字段说明：
        id                  唯一 ID
        order_id            来源 StandingOrder.id
        goal                已填充占位符的 goal 字符串（直接传给 AgentLoop.run()）
        reason_human        人话触发原因（供 TUI 展示，如 "定时触发：每天 09:00" 或
                            "文件变化触发：requirements.txt"）
        suggested_at        产出时间（Unix float）
        requires_confirmation  契约字段：**永远为 True**。
                            __post_init__ 断言此条件（构造 False → ValueError）。
        action              恒由来源 StandingOrder.action 决定；"run"（默认，confirm 后
                            create_run）或 "dream"（confirm 后跑 DreamPipeline）
    """
    id: str
    order_id: str
    goal: str
    reason_human: str
    suggested_at: float
    requires_confirmation: bool
    action: OrderAction = "run"   # 带默认值放最后（frozen slots dataclass 规则）

    def __post_init__(self) -> None:
        """契约断言：requires_confirmation 永远为 True（建议永远要确认）。"""
        if not self.requires_confirmation:
            raise ValueError(
                "ProactiveSuggestion.requires_confirmation 必须为 True "
                "（建议永远要用户确认，绝不自动执行）"
            )
        if self.action not in ("run", "dream"):
            raise ValueError(
                f"ProactiveSuggestion.action 必须是 'run' 或 'dream'，收到 {self.action!r}"
            )


def propose(
    order: "StandingOrder",
    context: dict,
    *,
    clock: object = None,
) -> ProactiveSuggestion:
    """从 StandingOrder 和上下文字典产出一条 ProactiveSuggestion。

    参数：
        order       触发的 StandingOrder
        context     模板填充用字典（允许的占位符键：date、path、time 等）
                    goal_template 中的 {key} 会被 context[key] 替换；
                    缺失的键保持原样（不抛错，诚实降级）。
        clock       可注入时钟（调用 clock() 获取 now）；
                    None → 使用 import time; time.time()

    返回：ProactiveSuggestion（requires_confirmation=True 已内嵌）
    """
    import time as _t

    now: float = clock() if callable(clock) else _t.time()

    # 填充 goal_template 占位符（缺失键保持 {key} 原样，不抛 KeyError）
    goal = _safe_format(order.goal_template, context)

    # 构造人话原因
    if order.kind == "schedule":
        reason = f"定时触发（{order.schedule}）：{order.utterance}"
    else:
        triggered_path = context.get("path", order.trigger_glob or "")
        reason = f"文件变化触发（{triggered_path}）：{order.utterance}"

    return ProactiveSuggestion(
        id=_new_suggestion_id(),
        order_id=order.id,
        goal=goal,
        reason_human=reason,
        suggested_at=now,
        requires_confirmation=True,  # 契约值，永远 True
        action=order.action,         # 透传来源 order 的 action（"run" 或 "dream"）
    )


def _safe_format(template: str, context: dict) -> str:
    """安全格式化：缺失键保持 {key} 原样，不抛 KeyError。"""
    import string

    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    try:
        return string.Formatter().vformat(template, (), _SafeDict(context))
    except Exception:  # noqa: BLE001
        # 极端情况（模板语法错误等）：原样返回
        return template
