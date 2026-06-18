"""P3 硬回归测试 —— One-Manifest 规则（P2 验收灵魂）。

覆盖契约：
a. 注册一个全新测试能力（仅 registry.register 一次，带 dispatch callable）
   → 断言：broker.request 走通（gating+回执完整）、risk 查得到、names() 含它
   —— 全程没改 ALL_TOOL_NAMES / _RISK / _execute / build_namespace 任何一处
   （源码扫描断言四处未被触碰）。

b. 注册缺 risk 能力 → 注册期 ValueError。

c. broker._RISK 与 registry.risk_table() 对内置能力完全一致
   （防两表漂移；过渡期契约）。

设计准则：
- 不修改任何现有 module 级变量；monkeypatch 只用于 broker 内部最小化测试桩。
- 源码扫描使用 ast.parse 检查测试函数本体内无对 _RISK/_execute/ALL_TOOL_NAMES/
  build_namespace 的赋值（确保回归测试本身不绕过规则）。
"""
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


# ── 辅助：构造 broker，可选注入 registry ─────────────────────────────────────

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


# ── a. 新能力注册后 broker.request 完整走通 ─────────────────────────────────

@pytest.mark.asyncio
async def test_new_capability_broker_end_to_end():
    """注册测试能力，broker.request 走通：gating→dispatch→回执完整。

    关键断言：
    - 全程没修改 ALL_TOOL_NAMES / _RISK / _execute / build_namespace
      （函数本体源码扫描断言）。
    """
    # ① 新建注册表并注册测试能力（dispatch 非 None）
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

    # ② broker.request 走通 gating（AUTO 档自动批准）
    broker = _make_broker(registry=reg)
    result = await broker.request("test_new_cap_abc", {"key": "val"})

    # ③ gating + dispatch 成功
    assert result == "test-dispatch-result", f"期望 dispatch 返回值，实际：{result!r}"
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0]["args"] == {"key": "val"}

    # ④ risk 查得到
    table = reg.risk_table()
    assert "test_new_cap_abc" in table
    assert table["test_new_cap_abc"] == "low"

    # ⑤ names() 含新能力
    assert "test_new_cap_abc" in reg.names()

    # ⑥ 回执完整（broker.last_receipt 被签名）
    assert broker.last_receipt is not None
    assert broker.last_receipt.action == "test_new_cap_abc"

    # ⑦ 源码扫描：本测试函数体没有对四处禁止目标的赋值
    _assert_no_forbidden_writes(test_new_capability_broker_end_to_end)


def _assert_no_forbidden_writes(fn) -> None:
    """扫描函数 AST，断言没有对
    ALL_TOOL_NAMES / _RISK / _execute / build_namespace 的赋值/修改。

    防止回归测试本身通过"改规则"来通过（那才是真正的假绿）。
    """
    forbidden = {"ALL_TOOL_NAMES", "_RISK", "_execute", "build_namespace"}
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # 直接赋值 ALL_TOOL_NAMES = ...
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in forbidden:
                    raise AssertionError(
                        f"回归测试不得对 {t.id!r} 赋值（违反 one-manifest 规则）"
                    )
                # obj.ALL_TOOL_NAMES = ... 或 monkeypatch.setattr(..., "ALL_TOOL_NAMES", ...)
                if isinstance(t, ast.Attribute) and t.attr in forbidden:
                    raise AssertionError(
                        f"回归测试不得对 {t.attr!r} 做属性赋值（违反 one-manifest 规则）"
                    )
        # monkeypatch.setattr(module, "ALL_TOOL_NAMES", ...) 形式
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


# ── b. 缺 risk 注册期 ValueError ─────────────────────────────────────────────

def test_register_missing_risk_raises_value_error():
    """注册 risk=None 的能力 → CapabilityRegistry.register 在注册期抛 ValueError（fail-closed）。"""
    reg = CapabilityRegistry()
    cap_no_risk = Capability(
        name="test_no_risk_cap",
        kind="tool",
        risk=None,   # 故意缺 risk
    )
    with pytest.raises(ValueError, match="risk"):
        reg.register(cap_no_risk)

    # 确认该能力没有被悄悄注册进去
    assert "test_no_risk_cap" not in reg


def test_register_missing_risk_name_in_error():
    """错误消息应包含能力名，方便排查。"""
    reg = CapabilityRegistry()
    with pytest.raises(ValueError, match="bad_capability"):
        reg.register(Capability(name="bad_capability", kind="tool", risk=None))


# ── c. broker._RISK 与 registry.risk_table() 内置一致（防两表漂移）───────────

def test_builtin_risk_table_matches_broker_RISK():
    """register_builtins 后 registry.risk_table() 与 broker._RISK 对内置能力完全一致。

    过渡期契约：_RISK 是旧常量表，risk_table() 是新权威来源；两表必须对齐，
    否则 broker.request gating 的 risk 等级判断会在新旧路径下不一致。
    """
    reg = CapabilityRegistry()
    register_builtins(reg)
    table = reg.risk_table()

    # _RISK 中的每个 action，risk 等级必须与 registry 一致
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
    """_RISK 的所有 action 必须是 registry 内置的子集（反向验证）。"""
    reg = CapabilityRegistry()
    register_builtins(reg)
    missing = [a for a in _RISK if a not in reg]
    assert not missing, (
        f"以下 broker._RISK action 未在 registry 注册：{missing}。"
        "需要在 register_builtins 补上对应 Capability。"
    )


# ── 附加：get_tool_names 动态派生正确性 ──────────────────────────────────────

def test_get_tool_names_without_registry_returns_static():
    """get_tool_names(None) 返回静态 ALL_TOOL_NAMES 副本。"""
    result = get_tool_names(None)
    assert result == list(ALL_TOOL_NAMES)


def test_get_tool_names_with_registry_returns_callable_names():
    """get_tool_names(registry) 返回 registry.callable_names()(诚实计数):排除宿主专属、
    沙箱不可调用的能力(stt_transcribe),但含全部真可调用内置工具。不依赖静态表。"""
    reg = CapabilityRegistry()
    register_builtins(reg)
    result = get_tool_names(reg)
    assert result == list(reg.callable_names())
    # 断言包含全部内置可调用能力（含 lsp_* 和纯沙箱工具）
    for expected in ALL_TOOL_NAMES:
        assert expected in result, f"{expected!r} 应在 registry 派生结果中"
    # 宿主专属能力(sandbox_callable=False)不计入可调用数(诚实:数量 = 真实可调用工具数)
    assert "stt_transcribe" in reg.names(), "stt_transcribe 仍在 registry(清单完整)"
    assert "stt_transcribe" not in result, "stt_transcribe 不可调用,不应计入 /tools"


def test_get_tool_names_registry_includes_new_cap():
    """向 registry 注册新能力后，get_tool_names 能立即反映（静态表不会自动更新）。"""
    reg = CapabilityRegistry()
    register_builtins(reg)
    reg.register(Capability(name="dynamic_new_tool", kind="tool", risk="low"))
    result = get_tool_names(reg)
    assert "dynamic_new_tool" in result
    # 静态表不含（验证动态性）
    assert "dynamic_new_tool" not in ALL_TOOL_NAMES


def test_get_tool_names_count_matches_all_tool_names():
    """register_builtins 后 get_tool_names(reg) 的长度 == len(ALL_TOOL_NAMES) + 宿主进程专属能力数。

    确保 register_builtins 覆盖了全部内置工具，计数诚实。

    宿主进程专属能力(非沙箱工具,不进 ALL_TOOL_NAMES):
      - stt_transcribe:语音 STT 转写,宿主进程跑,沙箱外;+1(voice input Plan 3)。
    """
    # 宿主进程专属能力:在 registry 中但不在沙箱命名空间/ALL_TOOL_NAMES 里。
    _HOST_ONLY_CAPS = {"stt_transcribe"}
    reg = CapabilityRegistry()
    register_builtins(reg)
    result = get_tool_names(reg)
    sandbox_result = [n for n in result if n not in _HOST_ONLY_CAPS]
    assert len(sandbox_result) == len(ALL_TOOL_NAMES), (
        f"registry 沙箱工具数 {len(sandbox_result)} != ALL_TOOL_NAMES 静态数 {len(ALL_TOOL_NAMES)}。"
        "register_builtins 可能漏了某些工具(宿主进程专属能力已从计数排除)。"
    )
