"""LSP 事件数据类(spec §10.1)。

投 EventBus:
- LspServerEvent:server 生命周期(spawn / ready / crash / disabled / restart)
- LspDiagnosticEvent:diagnostics 数据流(每条 publishDiagnostics 推送一次)

字段完全匹配 spec §10.1;EventKind 类属性 = snake_case 类名,便于 EventBus 路由与 replay。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class LspServerEvent:
    """LSP server 生命周期事件(活动栏 "LSP" 区段 4 态来源)。"""
    kind: str = "lsp_server_event"
    server_name: str = ""
    # status 取值:spawn / ready / crash / disabled / restart / exit
    status: str = ""
    command: str = ""
    exit_code: int | None = None
    elapsed_ms: int = 0
    error: str | None = None
    cwd: str = ""
    timestamp_ms: int = 0


@dataclass(frozen=True, slots=True)
class LspDiagnosticEvent:
    """LSP diagnostics 推送事件(server 推一次 publishDiagnostics → 一次本事件)。"""
    kind: str = "lsp_diagnostic_event"
    server_name: str = ""
    uri: str = ""
    count: int = 0
    severity_counts: Mapping[str, int] = field(default_factory=dict)
    cached: bool = False
    cwd: str = ""
