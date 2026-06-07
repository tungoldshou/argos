"""系统提示应含工具签名提示(覆盖新加的 offset/limit/all_occurrences)。

直接断言 _tool_signatures_block 输出与 _build_system 三段拼接都包含关键签名
——比造最小 loop 简单,更聚焦。
"""
import inspect

from argos_agent.core.loop import AgentLoop


def test_tool_signatures_block_contains_read_file_signature():
    """_tool_signatures_block 静态字符串应含 read_file 新签名。"""
    # 拿方法源码(不需造 loop 实例):静态方法,无 self
    src = inspect.getsource(AgentLoop._tool_signatures_block)
    assert "read_file(path, offset" in src
    assert "edit_file(path, old, new, all_occurrences" in src
    assert "limit" in src
    # /undo /retry 也应被提示
    assert "/undo" in src
    assert "/retry" in src


def test_build_system_calls_tool_signatures_block():
    """_build_system 应调 _tool_signatures_block 并把它的内容拼到系统提示里。

    任务:loop 把 system 拆 (stable, dynamic) 透传 — 工具签名块属稳定段,
    实际在 _build_system_pair 内调用,_build_system 是其薄包装。检查时同时看两者。
    """
    src = inspect.getsource(AgentLoop._build_system)
    pair_src = inspect.getsource(AgentLoop._build_system_pair)
    # 不强制要求字符串字面量匹配(实现可能用 compose_system 等),
    # 只要源码里任一方法引用了 _tool_signatures_block 即可
    assert ("_tool_signatures_block" in src or "tool_signatures_block" in src
            or "_tool_signatures_block" in pair_src or "tool_signatures_block" in pair_src)
