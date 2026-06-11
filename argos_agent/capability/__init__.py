"""能力注册表包（Argos v6 §5 能力模型）。

公开 API：
    Capability                   — 能力 manifest 冻结值对象
    CapabilityRegistry           — 注册/检索/聚合能力
    KindName                     — kind 字面类型别名
    VisibilityName               — visibility 字面类型别名
    register_builtins            — 向 registry 注册所有内置能力（含全部工具）并可选热更新 egress
    register_builtin_capabilities — 同 register_builtins（P3 规格入口名）

from argos_agent.capability import Capability, CapabilityRegistry, register_builtins
"""
from __future__ import annotations

from argos_agent.capability.manifest import Capability, KindName, VisibilityName
from argos_agent.capability.registry import CapabilityRegistry
from argos_agent.capability.builtins import register_builtins, register_builtin_capabilities

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "KindName",
    "VisibilityName",
    "register_builtins",
    "register_builtin_capabilities",
]
