"""ApprovalDecision 事件 dataclass(投 EventBus,spec §2.7)。

事件约定(任务:6 个 events.py 一致性):
- 复用 `argos.protocol.events.EventBus`(全局唯一总线;本模块不重新定义)
- 每个事件 dataclass 含 `kind` 类属性(类名 snake_case;EventBus 路由 + replay 依赖)
- `kind` 不参与 dataclass 字段;`asdict()` 不序列化它(其他 4 个领域 events.py 沿用此约定)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DecisionType = Literal["approved", "denied", "asked"]
ByType = Literal["rule", "allowlist", "denylist", "asklist", "level", "user", "secret"]


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """approval 决策事件(投 TUI EventBus + audit log 复用字段)。"""
    tool: str
    args: str
    decision: DecisionType        # approved | denied | asked
    trigger: str                  # 标签:hard_rule:<n> / soft_allow:<m> / ...
    by: ByType
    rule_name: str | None = None
    secret_pattern: str | None = None
    risk: str = "medium"
    session_id: str = ""

    # 类属性(不参与 dataclass 字段;asdict 不序列化)
    kind = "approval_decision"
