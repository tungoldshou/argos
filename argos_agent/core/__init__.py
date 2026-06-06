"""Argos core:类型基石 / 自建 CodeAct loop / 5 层 harness / 模型分档。

生产引擎入口在 `core.loop.AgentLoop`(自建 CodeAct,直连 Anthropic 兼容端)。
整包 framework-free —— 不依赖 langchain/langgraph;唯一外部执行器是 smolagents
(沙箱 LocalPythonExecutor),故打包后的单 binary 不需要旧栈。
"""
from __future__ import annotations

from typing import Any

# HONESTY_SYSTEM canonical 在 core/honesty.py;此处重导出保持包级可达。
from argos_agent.core.honesty import HONESTY_SYSTEM  # noqa: F401


def final_text(message: Any) -> str:
    """从最终 message 抽纯文本。推理模型(如 MiniMax)的 content 可能是
    [{type:'thinking',...}, {type:'text', text:'...'}] —— 只取 text,丢 thinking。
    纯 duck-typing,不依赖任何框架。"""
    c = getattr(message, "content", message)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(parts)
    return str(c)


def text_delta(chunk: Any) -> str:
    """从流式 message chunk 抽 text 增量(丢 thinking)。同 final_text 的同源策略。"""
    c = getattr(chunk, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""
