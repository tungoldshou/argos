"""MCP 客户端纯逻辑测试 —— 配置/分类/套闸/降级(不连真 MCP server)。"""
import json
import pytest

from argos_agent import mcp_client


def test_load_config_writes_defaults_when_missing(tmp_path):
    cfg_path = tmp_path / "mcp.json"
    cfg = mcp_client.load_config(cfg_path)
    # 缺文件 → 写入默认安全集并返回
    assert cfg_path.exists()
    assert "chrome-devtools" in cfg["servers"]
    assert "filesystem" in cfg["servers"]
    assert "github" in cfg["servers"]
    # github 默认 disabled(需 token 才开,免无 token 噪音)
    assert cfg["servers"]["github"]["enabled"] is False
    assert cfg["servers"]["chrome-devtools"]["enabled"] is True


def test_load_config_reads_existing(tmp_path):
    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(json.dumps({"servers": {"x": {"command": "echo", "args": [], "enabled": True}}}), encoding="utf-8")
    cfg = mcp_client.load_config(cfg_path)
    assert list(cfg["servers"].keys()) == ["x"]


def test_load_config_malformed_falls_back_to_defaults(tmp_path):
    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text("{ not json", encoding="utf-8")
    cfg = mcp_client.load_config(cfg_path)
    # 坏文件 → 不崩,退回默认集(诚实可用 > 崩)
    assert "filesystem" in cfg["servers"]


import asyncio
from langchain_core.tools import StructuredTool
from argos_agent import approval


def _fake_tool(name="do_thing", metadata=None):
    # 用一个具名 str 参数,避免 **kwargs 让 langchain args_schema 推断出空/严格 schema
    # 而拒绝 .ainvoke 的入参(测试稳定性)。
    async def _coro(arg: str = "") -> str:
        return f"ran {name} arg={arg}"
    t = StructuredTool.from_function(
        coroutine=_coro, name=name, description=f"{name} desc",
    )
    t.metadata = metadata or {}
    return t


# 注:metadata 形状用 Task 1 探针确认的真实平铺形(readOnlyHint/destructiveHint 直接在顶层)。
def test_classify_readonly_hint_not_gated():
    t = _fake_tool(metadata={"readOnlyHint": True, "destructiveHint": None})
    needs, risk = mcp_client.classify(t, {})
    assert needs is False


def test_classify_whitelist_not_gated():
    t = _fake_tool(name="list_directory")  # 无注解,但在白名单里 → 放行(兜底路径)
    needs, risk = mcp_client.classify(t, {"read_only_tools": ["list_directory"]})
    assert needs is False


def test_classify_unknown_is_failclosed_gated():
    t = _fake_tool(name="delete_everything", metadata={})  # 无注解 → fail-closed
    needs, risk = mcp_client.classify(t, {})
    assert needs is True
    assert risk in ("medium", "high")


def test_classify_destructive_is_high_risk():
    t = _fake_tool(metadata={"readOnlyHint": False, "destructiveHint": True})
    needs, risk = mcp_client.classify(t, {})
    assert needs is True and risk == "high"


def test_classify_effectful_nondestructive_is_medium():
    # 如 create_directory/move_file:readOnlyHint=false 且 destructiveHint=false → 套审批 medium
    t = _fake_tool(name="move_file", metadata={"readOnlyHint": False, "destructiveHint": False})
    needs, risk = mcp_client.classify(t, {})
    assert needs is True and risk == "medium"


@pytest.mark.asyncio
async def test_gate_mcp_tool_failclosed_without_gate():
    t = _fake_tool(name="navigate")
    gated = mcp_client.gate_mcp_tool(t, "medium", "chrome-devtools")
    # 保名/保描述
    assert gated.name == "navigate"
    out = await gated.ainvoke({"arg": "x"})
    assert "默认拒绝" in out  # 无 gate → 不执行原工具


@pytest.mark.asyncio
async def test_gate_mcp_tool_forwards_when_approved():
    t = _fake_tool(name="navigate")
    gated = mcp_client.gate_mcp_tool(t, "medium", "chrome-devtools")
    gate = approval.ApprovalGate()
    async def _auto(payload, timeout=60.0):
        # 弹窗 payload 应带来源 + 真实工具名
        assert payload["tool"] == "navigate"
        assert payload["source"] == "mcp:chrome-devtools"
        return approval.Decision(approved=True, scope="once")
    gate.request = _auto  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        out = await gated.ainvoke({"arg": "x"})
        assert "ran navigate" in out  # 批准 → 转发到原工具
    finally:
        approval.reset_current_gate(token)
