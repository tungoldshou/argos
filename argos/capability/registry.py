"""CapabilityRegistry —— 能力注册/检索/聚合（契约 §5 能力模型）。

设计约束：
- 单事件循环假设（与仓库现状一致），无外部锁。
- register() fail-closed 双重门：
    1. risk 为 None → 注册期 ValueError（不允许风险未声明的能力进注册表）。
    2. 重名 → 注册期 ValueError（能力名是全局唯一字符串契约）。
- 所有检索方法返回不可变视图（tuple / frozenset），外部不得持有内部 dict 引用。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from argos.core.types import RiskLevel
from argos.i18n import t

if TYPE_CHECKING:
    from argos.capability.manifest import Capability, KindName, VisibilityName


class CapabilityRegistry:
    """能力注册表（Argos v6 §5）。

    线程/并发安全：单 event loop 假设（与仓库现状一致）；不引锁。

    使用示例::

        registry = CapabilityRegistry()
        registry.register(Capability(name="web_search", kind="tool", risk="low", ...))
        cap = registry.get("web_search")        # → Capability
        table = registry.risk_table()           # → {"web_search": "low", ...}
        hosts = registry.egress_hosts()         # → frozenset[str]（所有声明出网主机）
    """

    def __init__(self) -> None:
        # _caps：name → Capability，注册后不可变（frozen dataclass）
        self._caps: dict[str, "Capability"] = {}

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------

    def register(self, cap: "Capability") -> None:
        """注册一个能力 manifest。

        fail-closed 规则：
        1. cap.risk 为 None → ValueError（风险等级必须显式声明）。
        2. 同名已注册 → ValueError（能力名全局唯一）。

        Args:
            cap: 待注册的 Capability。

        Raises:
            ValueError: risk 未声明或名称重复。
        """
        if cap.risk is None:
            raise ValueError(t("cap.registry.register_no_risk", name=cap.name))
        if cap.name in self._caps:
            raise ValueError(t("cap.registry.register_duplicate", name=cap.name))
        self._caps[cap.name] = cap

    # ------------------------------------------------------------------
    # 读操作（返回不可变视图）
    # ------------------------------------------------------------------

    def get(self, name: str) -> "Capability":
        """按名称查找 Capability。

        Args:
            name: broker action 名（即 Capability.name）。

        Returns:
            对应的 Capability。

        Raises:
            KeyError: 未注册。
        """
        try:
            return self._caps[name]
        except KeyError:
            raise KeyError(t("cap.registry.not_found", name=name)) from None

    def names(self) -> tuple[str, ...]:
        """返回所有已注册能力名（按注册顺序，Python 3.7+ dict 有序）。"""
        return tuple(self._caps.keys())

    def callable_names(self) -> tuple[str, ...]:
        """返回【模型在沙箱里真正可调用】的能力名（排除 sandbox_callable=False 的宿主专属
        能力）。/tools 据此诚实计数(数量 = 真实可调用工具数)。"""
        return tuple(n for n, c in self._caps.items() if c.sandbox_callable)

    def by_kind(self, kind: "KindName") -> tuple["Capability", ...]:
        """返回指定 kind 的所有能力（按注册顺序）。"""
        return tuple(c for c in self._caps.values() if c.kind == kind)

    def risk_table(self) -> dict[str, RiskLevel]:
        """返回 name → RiskLevel 的快照字典（副本，外部修改不影响注册表）。

        注册期已保证 risk 非 None，此处类型断言安全。
        """
        return {name: cap.risk for name, cap in self._caps.items()}  # type: ignore[return-value]

    def egress_hosts(self) -> frozenset[str]:
        """聚合所有能力声明的出网主机（union），返回 frozenset。"""
        result: set[str] = set()
        for cap in self._caps.values():
            result.update(cap.egress_hosts)
        return frozenset(result)

    def visible_names(self, role: "VisibilityName") -> tuple[str, ...]:
        """按角色过滤可见能力名。

        Args:
            role: "all"（普通用户）或 "developer"（开发者）。
                  developer 可见"all"和"developer"两类；
                  all 只可见 visibility="all" 的能力。

        Returns:
            对该角色可见的能力名元组（按注册顺序）。
        """
        if role == "developer":
            # 开发者看全部
            return tuple(self._caps.keys())
        # 普通用户只看 visibility="all"
        return tuple(
            name for name, cap in self._caps.items() if cap.visibility == "all"
        )

    def __len__(self) -> int:
        return len(self._caps)

    def __contains__(self, name: object) -> bool:
        return name in self._caps
