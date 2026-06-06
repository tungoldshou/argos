"""SandboxBackend 协议 + ExecResult 值对象(契约 §5)。

后端可插拔(对冲 Seatbelt 弃用,spec §6.3):seatbelt.py(MVP) / bubblewrap / (roadmap)Apple
Containerization。AgentLoop 只依赖本协议,换后端零改动。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ExecResult:
    """一次 code-action 的执行结果(契约 §5)。"""
    stdout: str
    value_repr: str          # 末尾表达式返回值 repr,无则 ""
    exc: str                 # 异常文本(含类型),无则 ""

    @property
    def ok(self) -> bool:
        return self.exc == ""


@runtime_checkable
class SandboxBackend(Protocol):
    """持久 Python 命名空间子进程的抽象边界。"""

    def spawn(self, *, workspace: Path, namespace: dict[str, Any]) -> None:
        """起持久命名空间子进程(Seatbelt profile 包着),注入工具函数。"""
        ...

    def exec_code(self, code: str) -> ExecResult:
        """执行一段代码;命名空间变量跨调用存活。"""
        ...

    def close(self) -> None:
        """收尾子进程。"""
        ...
