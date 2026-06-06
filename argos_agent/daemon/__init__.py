"""daemon 模块入口。

暴露 start() / stop() / status() / RunManager 单例。

#5a 范围:
  · RunStore / StateIndex / 7 状态机
  · RunManager(单例;events fan-out;pause/resume 协调)
  · HTTP/SSE server(daemon 进程入口)
  · Worker 协程(包 AgentLoop)

公开 API:
  · start() → 启 HTTP server + 写 PID
  · stop() → 优雅:所有 running 改 suspended + 关 server
  · status() → dict(uptime, runs, sessions)
"""
from __future__ import annotations

# re-export 关键类,便于 from argos_agent.daemon import RunManager, RunStore, ...
from argos_agent.daemon.store import CorruptionError, RunStore  # noqa: F401
from argos_agent.daemon.index import IndexEntry, StateIndex  # noqa: F401
from argos_agent.daemon.state_machine import (  # noqa: F401
    ALLOWED, RUN_ID_RE, STATES, TERMINAL_STATES,
    InvalidTransition, read_state, transition,
)
from argos_agent.daemon.events import RunCheckpoint, RunFailure, RunMeta  # noqa: F401
