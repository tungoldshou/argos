"""Internal documentation."""
from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap

import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.capability import Capability, CapabilityRegistry, register_builtins
from argos.sandbox.broker import CapabilityBroker, _RISK
from argos.sandbox.egress import EgressPolicy
from argos.tools import ALL_TOOL_NAMES, get_tool_names
from argos.tools.receipts import ReceiptSigner



def _make_broker(
    registry: CapabilityRegistry | None = None,
    level: ApprovalLevel = ApprovalLevel.AUTO,
) -> CapabilityBroker:
    gate = ApprovalGate(level=level)
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    signer = ReceiptSigner(key=b"one-manifest-test-key")
    return CapabilityBroker(
        gate=gate, egress=egress, signer=signer, registry=registry,
    )



@pytest.mark.asyncio
async def test_new_capability_broker_end_to_end():
    """Internal documentation."""
    reg = CapabilityRegistry()
    dispatch_calls: list[dict] = []

    def _test_dispatch(args: dict, run_ctx) -> str:
        dispatch_calls.append({"args": args, "ctx": run_ctx})
        return "test-dispatch-result"

    reg.register(Capability(
        name="test_new_cap_abc",
        kind="tool",
        risk="low",
        dispatch=_test_dispatch,
    ))

    broker = _make_broker(registry=reg)
    result = await broker.request("test_new_cap_abc", {"key": "val"})

    assert result == "test-dispatch-result", f"期望 dispatch 返回值，实际：{result!r}"
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0]["args"] == {"key": "val"}

    table = reg.risk_table()
    assert "test_new_cap_abc" in table
    assert table["test_new_cap_abc"] == "low"

    assert "test_new_cap_abc" in reg.names()

    assert broker.last_receipt is not None
    assert broker.last_receipt.action == "test_new_cap_abc"

    _assert_no_forbidden_writes(test_new_capability_broker_end_to_end)


def _assert_no_forbidden_writes(fn) -> None:
    """Internal documentation."""
    forbidden = {"ALL_TOOL_NAMES", "_RISK", "_execute", "build_namespace"}
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in forbidden:
                    raise AssertionError(
                        f"回归测试不得对 {t.id!r} 赋值（违反 one-manifest 规则）"
                    )
                if isinstance(t, ast.Attribute) and t.attr in forbidden:
                    raise AssertionError(
                        f"回归测试不得对 {t.attr!r} 做属性赋值（违反 one-manifest 规则）"
                    )
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in ("setattr", "patch", "patch_object")
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in forbidden:
                        raise AssertionError(
                            f"回归测试不得通过 monkeypatch/patch 修改 {arg.value!r}"
                            "（违反 one-manifest 规则）"
                        )



def test_register_missing_risk_raises_value_error():
    """Internal documentation."""
    reg = CapabilityRegistry()
    cap_no_risk = Capability(
        name="test_no_risk_cap",
        kind="tool",
        risk=None,
    )
    with pytest.raises(ValueError, match="risk"):
        reg.register(cap_no_risk)

    assert "test_no_risk_cap" not in reg


def test_register_missing_risk_name_in_error():
    """Internal documentation."""
    reg = CapabilityRegistry()
    with pytest.raises(ValueError, match="bad_capability"):
        reg.register(Capability(name="bad_capability", kind="tool", risk=None))



def test_builtin_risk_table_matches_broker_RISK():
    """Internal documentation."""
    reg = CapabilityRegistry()
    register_builtins(reg)
    table = reg.risk_table()

    for action, expected_risk in _RISK.items():
        assert action in table, (
            f"broker._RISK 中的 {action!r} 在 registry 中不存在 —— 两表漂移！"
        )
        actual_risk = table[action]
        assert actual_risk == expected_risk, (
            f"risk 漂移：{action!r} 在 _RISK={expected_risk!r}，"
            f"registry={actual_risk!r} —— 必须同步修改两处。"
        )


def test_broker_RISK_subset_of_registry():
    """Internal documentation."""
    reg = CapabilityRegistry()
    register_builtins(reg)
    missing = [a for a in _RISK if a not in reg]
    assert not missing, (
        f"以下 broker._RISK action 未在 registry 注册：{missing}。"
        "需要在 register_builtins 补上对应 Capability。"
    )



def test_get_tool_names_without_registry_returns_static():
    """Internal documentation."""
    result = get_tool_names(None)
    assert result == list(ALL_TOOL_NAMES)


def test_get_tool_names_with_registry_returns_callable_names():
    """Internal documentation."""
    reg = CapabilityRegistry()
    register_builtins(reg)
    result = get_tool_names(reg)
    assert result == list(reg.callable_names())
    for expected in ALL_TOOL_NAMES:
        assert expected in result, f"{expected!r} 应在 registry 派生结果中"


def test_get_tool_names_registry_includes_new_cap():
    """Internal documentation."""
    reg = CapabilityRegistry()
    register_builtins(reg)
    reg.register(Capability(name="dynamic_new_tool", kind="tool", risk="low"))
    result = get_tool_names(reg)
    assert "dynamic_new_tool" in result
    assert "dynamic_new_tool" not in ALL_TOOL_NAMES


def test_get_tool_names_count_matches_all_tool_names():
    """Internal documentation."""
    _HOST_ONLY_CAPS: set[str] = set()
    reg = CapabilityRegistry()
    register_builtins(reg)
    result = get_tool_names(reg)
    sandbox_result = [n for n in result if n not in _HOST_ONLY_CAPS]
    assert len(sandbox_result) == len(ALL_TOOL_NAMES), (
        f"registry 沙箱工具数 {len(sandbox_result)} != ALL_TOOL_NAMES 静态数 {len(ALL_TOOL_NAMES)}。"
        "register_builtins 可能漏了某些工具(宿主进程专属能力已从计数排除)。"
    )
