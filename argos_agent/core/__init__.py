"""Argos core:类型基石 / 自建 CodeAct loop / 5 层 harness / 模型分档。

生产引擎入口在 `core.loop.AgentLoop`(自建 CodeAct,直连 Anthropic 兼容端)。
旧 LangChain create_agent 路径(server.py/worker.py/planner 仍引用)已隔离到
`core._legacy_agent`,经下方 PEP 562 __getattr__ **懒加载** —— 导入 core 子模块
(如 `core.loop`)不再在顶层触发 `import langchain`,故打包后的单 binary
(已 exclude langchain)能正常起;langchain 只在真访问旧符号时才加载。
"""
from __future__ import annotations

from typing import Any

# HONESTY_SYSTEM canonical 在 core/honesty.py;此处重导出保持向后兼容(server.py 等)。
from argos_agent.core.honesty import HONESTY_SYSTEM  # noqa: F401


def final_text(message: Any) -> str:
    """从最终 AIMessage 抽纯文本。推理模型(如 MiniMax)的 content 可能是
    [{type:'thinking',...}, {type:'text', text:'...'}] —— 只取 text,丢 thinking。
    (不依赖 langchain,纯 duck-typing,故留在包 __init__ 供 planner 等直接用。)"""
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


def __getattr__(name: str):
    """PEP 562 懒加载:旧 LangChain 路径符号(build_agent_with_gate / MemoryRecallMiddleware /
    _llm / RECALL_* …)按需从 _legacy_agent 取 —— 只在真访问时才 import langchain。
    导入 core 子模块本身不触发,保证打包 binary 不需要 langchain。

    用 importlib.import_module(非 `from ... import`):后者会经 importlib 的 fromlist
    hasattr(core, '_legacy_agent') 再次回调本 __getattr__ → 无限递归。显式排除子模块名
    与 dunder,让 `import core._legacy_agent` 走正常导入路径。"""
    if name.startswith("__") or name == "_legacy_agent":
        raise AttributeError(name)
    import importlib
    legacy = importlib.import_module("argos_agent.core._legacy_agent")
    try:
        return getattr(legacy, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
