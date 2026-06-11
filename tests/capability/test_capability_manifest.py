"""Capability manifest 值对象测试（§5 能力模型）。

覆盖：
- 正常构造（各字段默认值）
- 冻结不可变（frozen dataclass）
- name 空串拒绝
- kind 非法值拒绝
- visibility 非法值拒绝
- egress_hosts 默认为空 tuple
- dispatch=None 合法（内置能力占位）
- dispatch 可赋可调用
"""
from __future__ import annotations

import dataclasses
import pytest

from argos_agent.capability.manifest import Capability


# ------------------------------------------------------------------
# 辅助工厂
# ------------------------------------------------------------------

def _cap(**kwargs) -> Capability:
    """带默认值的 Capability 工厂，便于各 test 只覆写关心的字段。"""
    defaults = dict(
        name="web_search",
        kind="tool",
        risk="low",
    )
    defaults.update(kwargs)
    return Capability(**defaults)


# ------------------------------------------------------------------
# 正常构造 + 默认值
# ------------------------------------------------------------------

def test_basic_construction():
    """最小字段构造成功，默认值符合规范。"""
    cap = _cap()
    assert cap.name == "web_search"
    assert cap.kind == "tool"
    assert cap.risk == "low"
    assert cap.reversible is None
    assert cap.egress_hosts == ()
    assert cap.schema is None
    assert cap.verify_hint == ""
    assert cap.visibility == "all"
    assert cap.dispatch is None


def test_full_construction():
    """所有字段都能正确赋值。"""
    def _exec(**kw):
        return "result"

    cap = Capability(
        name="run_command",
        kind="tool",
        risk="high",
        reversible=False,
        egress_hosts=("example.com",),
        schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
        verify_hint="exit code 0 = passed",
        visibility="developer",
        dispatch=_exec,
    )
    assert cap.name == "run_command"
    assert cap.risk == "high"
    assert cap.reversible is False
    assert cap.egress_hosts == ("example.com",)
    assert cap.schema is not None
    assert cap.verify_hint == "exit code 0 = passed"
    assert cap.visibility == "developer"
    assert cap.dispatch is _exec


def test_risk_none_allowed_in_manifest():
    """manifest 本身允许 risk=None（注册期才被 registry fail-closed 拦截）。"""
    cap = _cap(risk=None)
    assert cap.risk is None


def test_reversible_can_be_true_false_or_none():
    """reversible 三态：True / False / None 都合法。"""
    assert _cap(reversible=True).reversible is True
    assert _cap(reversible=False).reversible is False
    assert _cap(reversible=None).reversible is None


# ------------------------------------------------------------------
# 不可变性
# ------------------------------------------------------------------

def test_frozen_immutable():
    """frozen=True：任何字段赋值都应抛 FrozenInstanceError。"""
    cap = _cap()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cap.name = "other"  # type: ignore[misc]


def test_frozen_egress_hosts_tuple():
    """egress_hosts 是 tuple（不可变），不是 list。"""
    cap = _cap(egress_hosts=("api.openai.com", "duckduckgo.com"))
    assert isinstance(cap.egress_hosts, tuple)


# ------------------------------------------------------------------
# 构造期校验 fail-closed
# ------------------------------------------------------------------

def test_empty_name_rejected():
    """name 为空串时 __post_init__ 抛 ValueError。"""
    with pytest.raises(ValueError, match="name"):
        _cap(name="")


def test_whitespace_only_name_rejected():
    """name 全为空白字符时拒绝。"""
    with pytest.raises(ValueError, match="name"):
        _cap(name="   ")


def test_invalid_kind_rejected():
    """kind 非法值抛 ValueError。"""
    with pytest.raises(ValueError, match="kind"):
        _cap(kind="unknown_kind")  # type: ignore[arg-type]


def test_invalid_visibility_rejected():
    """visibility 非法值抛 ValueError。"""
    with pytest.raises(ValueError, match="visibility"):
        _cap(visibility="admin")  # type: ignore[arg-type]


# ------------------------------------------------------------------
# 各 kind / visibility 合法值枚举
# ------------------------------------------------------------------

@pytest.mark.parametrize("kind", [
    "tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin",
])
def test_all_valid_kinds(kind):
    """每个合法 kind 都能注册。"""
    cap = _cap(kind=kind)
    assert cap.kind == kind


@pytest.mark.parametrize("vis", ["all", "developer"])
def test_all_valid_visibility(vis):
    """两种合法 visibility 都能设置。"""
    cap = _cap(visibility=vis)
    assert cap.visibility == vis


# ------------------------------------------------------------------
# dispatch
# ------------------------------------------------------------------

def test_dispatch_callable():
    """dispatch 可以是任何可调用对象。"""
    called = []

    def handler(**kw):
        called.append(kw)
        return "ok"

    cap = _cap(dispatch=handler)
    result = cap.dispatch(cmd="echo hi")
    assert result == "ok"
    assert called == [{"cmd": "echo hi"}]


def test_dispatch_none_is_default():
    """dispatch=None 表示由 broker 既有路径处理（内置能力）。"""
    cap = _cap()
    assert cap.dispatch is None
