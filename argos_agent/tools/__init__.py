"""Argos 工具注册表(契约 §4)。纯沙箱工具 vs broker-gated 二分。

本文件先放最小桩(Task 6/7 用 Edit 扩成真版:files 纯沙箱 + shell/web broker-gated)。"""
from __future__ import annotations

from typing import Any


def build_child_namespace(broker: Any) -> dict[str, Any]:
    """【沙箱子进程侧】命名空间:纯沙箱工具原函数 + broker-gated 工具经 _broker 包装。
    Task 6/7 扩成真版。最小桩先返回空集合让子进程能 init。"""
    return {}
