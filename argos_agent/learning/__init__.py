"""learning 子包 — 让 Argos 越用越准。

只存"被验证过的":passed run 触发 distill + A/B 晋升;failed/unverifiable run 只产
reflection 进 memory(供下次重试参考),绝不升级成技能。后台、非阻塞,失败诚实降级。
"""
from __future__ import annotations

__all__ = [
    "distiller",
    "promotion_gate",
    "reflection",
    "hook",
]
