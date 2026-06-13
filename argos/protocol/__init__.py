"""argos.protocol — 内核/客户端共享协议层(v6 P0 搬家)。

本包是 ACP（Argos Client Protocol）的 Python 定义：
- events.py    : 全部 Event dataclass 族 + 序列化/反序列化 ABI（从 tui/events.py 搬入）
- envelope.py  : EventEnvelope 帧格式（v6 P0 新增）

兼容约定：
- argos/tui/events.py 仍可用作兼容 shim（37 个测试文件 + TUI 内部不需要修改）
- 新代码请 import argos.protocol.events
"""
