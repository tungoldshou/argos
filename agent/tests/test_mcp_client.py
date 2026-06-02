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
