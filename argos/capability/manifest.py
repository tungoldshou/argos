"""Capability manifest 值对象（契约 §5 能力模型，v6 设计文档 §5）。

设计约束：
- 冻结 dataclass（frozen=True, slots=True）—— 不可变，线程/事件循环安全。
- risk 字段强制声明：None 或缺失在构造后的校验中 fail-closed（CapabilityRegistry.register
  负责在注册期拒绝，manifest 本身允许 None 以支持「已知 dispatch=None 的 stub」在测试中构造）。
- dispatch 为 None 表示"由 broker 既有路径执行的内置能力"；注册表可存储，但调用时由 broker 自行分发。
- 单事件循环假设（与仓库现状一致），无需额外锁。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from argos.core.types import RiskLevel
from argos.i18n import t

# kind 合法值（§5 列举；lsp/plugin 是开发者能力，对普通用户 visibility=developer）
KindName = Literal["tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin"]

# 可见性：all = 所有用户；developer = 仅开发者（LSP/plugin 等）
VisibilityName = Literal["all", "developer"]


@dataclass(frozen=True, slots=True)
class Capability:
    """单个能力的声明清单。

    字段说明：
        name          — 与 broker action 字符串一一对应（字符串契约沿用）。
        kind          — 能力类别，见 KindName。
        risk          — 强制声明（低/中/高）；CapabilityRegistry.register 在 None 时 fail-closed。
        reversible    — True=可撤销; False=不可逆; None=未知。喂给 Ledger / 审批文案。
        egress_hosts  — 声明此能力需出网的 host 列表；EgressPolicy 热更新用。
        schema        — 入参 JSONSchema（边界校验；None=未声明）。
        verify_hint   — 该能力产物的机检建议（喂验证梯子 L2/L3；空串=无提示）。
        visibility    — "all" 对所有用户可见；"developer" 仅开发者可见（LSP 等）。
        dispatch      — host 侧执行 Callable；None=由 broker 既有路径（if/elif）处理的内置能力。
        sandbox_callable — True=模型在沙箱命名空间里有可调用包装（绝大多数工具）；
                       False=宿主进程专属能力（如 stt_transcribe 语音转写，沙箱外跑、模型调不动）。
                       /tools 计数据此排除不可调用能力，兑现"数量 = 真实可调用工具数"的诚实承诺。
    """
    name: str
    kind: KindName
    risk: RiskLevel | None  # None 仅用于测试 stub；注册期被 registry fail-closed 拦截
    reversible: bool | None = None
    egress_hosts: tuple[str, ...] = field(default_factory=tuple)
    schema: dict[str, Any] | None = None
    verify_hint: str = ""
    visibility: VisibilityName = "all"
    dispatch: Callable[..., Any] | None = None
    sandbox_callable: bool = True

    def __post_init__(self) -> None:
        """基础不变式：name 不可为空串。"""
        if not self.name or not self.name.strip():
            raise ValueError(t("cap.manifest.empty_name"))
        if self.kind not in (
            "tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin"
        ):
            raise ValueError(t("cap.manifest.invalid_kind", kind=self.kind))
        if self.visibility not in ("all", "developer"):
            raise ValueError(t("cap.manifest.invalid_visibility", visibility=self.visibility))
