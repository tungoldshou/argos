"""HookFired 事件 dataclass(投到 EventBus,供 TUI 活动栏渲染)。

不持久化(spec §2.4:只为活动栏实时显示;重放不还原 hook trace)。
TUI 走 `isinstance(ev, HookFired)` 派发。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HookFired:
    """单个 hook 触发结果(每次 fire 一个 hook = 一个事件;并行 N hook = N 事件)。

    `kind` 是 EventKind 联合的判别字段(类属性,与其他事件类一致);tui/events.py
    用它路由。
    """
    event_name: str            # PreToolUse / PostToolUse / ...
    command: str               # 原始 command 串(展示用)
    success: bool              # True=exit 0,False=非 0/超时/未找到
    returncode: int | None
    elapsed_ms: int            # 跑完耗时(ms,给活动栏显)
    timed_out: bool = False
    not_found: bool = False
    stop_reason: str | None = None
    error: str | None = None    # 异常信息(未找到 / OS 错误)
    stdout: str = ""           # 原始 stdout(给上层聚合用;活动栏只显 status)

    # 类属性(不参与 dataclass 字段;asdict 不会序列化)
    kind = "hook_fired"
