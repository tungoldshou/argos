"""HONESTY_SYSTEM 分节重构 + Fable 模式新增段的结构性铁证。"""
from __future__ import annotations

from argos.core import honesty
from argos.core.honesty import HONESTY_SYSTEM, compose_system, UNTRUSTED_OPEN


def test_section_constants_exist_and_compose():
    # 分节常量存在且都拼进了 HONESTY_SYSTEM
    for name in ("_IDENTITY", "_HONESTY_INVARIANT", "_ACTION_FORMAT", "_TOOLS", "_WORKFLOW_NOTE"):
        assert hasattr(honesty, name), f"missing section constant {name}"
        assert getattr(honesty, name).strip() in HONESTY_SYSTEM


def test_honesty_invariant_preserved():
    # 诚实铁律语义保留(原三条 + CodeAct 契约 + 联网工具声明)
    assert "诚实协议" in HONESTY_SYSTEM
    assert "退出码" in HONESTY_SYSTEM
    assert "CodeAct" in HONESTY_SYSTEM
    assert "web_search" in HONESTY_SYSTEM and "browser_navigate" in HONESTY_SYSTEM


def test_workflow_contract_trimmed():
    # propose_workflow 仍提及,但长契约已裁短(不再含逐字 stages 字段表)
    assert "propose_workflow" in HONESTY_SYSTEM
    assert "fan_out" in HONESTY_SYSTEM          # 五选一仍提
    assert "voters/threshold" not in HONESTY_SYSTEM   # 逐字段细节已移除


def test_safety_refusal_section():
    from argos.core.honesty import HONESTY_SYSTEM
    assert "恶意软件" in HONESTY_SYSTEM and "勒索软件" in HONESTY_SYSTEM
    assert "科研" in HONESTY_SYSTEM          # "即便声称科研/教学用途" 不放行
    assert "少说" in HONESTY_SYSTEM          # 风险时少说
    assert "只讲原则" in HONESTY_SYSTEM      # 讲原则不讲检测机制
