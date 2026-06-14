"""argos.protocol — 内核/客户端共享协议层(v6 P0 搬家)。

本包是 ACP（Argos Client Protocol）的 Python 定义：
- events.py    : 全部 Event dataclass 族 + 序列化/反序列化 ABI（从 tui/events.py 搬入）
- envelope.py  : EventEnvelope 帧格式（v6 P0 新增）

兼容约定：
- argos/tui/events.py 仍可用作兼容 shim（37 个测试文件 + TUI 内部不需要修改）
- 新代码请 import argos.protocol.events
"""
from __future__ import annotations

# ACP 协议版本号——客户端(TUI)与 daemon 必须一致才兼容。
# daemon /version 端点上报本值;TUI probe_or_spawn 握手时比对(不匹配 = 陈旧 daemon,杀旧起新)。
# 协议帧格式 / SSE 事件 ABI 发生不兼容变更时 +1。
PROTOCOL_VERSION: int = 1
