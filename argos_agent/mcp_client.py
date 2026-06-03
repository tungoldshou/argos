"""MCP 插座 —— 按 ~/.argos/mcp.json 连 stdio MCP server,工具套审批闸后并进 ALL_TOOLS。

设计见 docs/superpowers/specs/2026-06-02-mcp-socket-design.md。要点:
  · 逐 server 连接,任一失败优雅降级(标 disconnected,其余照常),绝不崩 sidecar。
  · 工具分类 fail-closed:只读放行,有副作用/未知一律过审批闸(approval.py)。
  · import 期无副作用;真正连接在 server 启动钩子里调 ensure_loaded()。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from . import approval
from .approval import RiskLevel

CONFIG_PATH = Path(os.environ.get("ARGOS_MCP_CONFIG", Path.home() / ".argos" / "mcp.json"))

# 默认安全集(dev:靠本机 node/npx)。chrome-devtools + filesystem 默认开;
# github 含在集里但默认关(需用户填 token 才连,免无 token 连接失败噪音)。
def _default_config() -> dict[str, Any]:
    return {
        "servers": {
            "chrome-devtools": {
                "command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"],
                "transport": "stdio", "enabled": True, "trust": "builtin",
                "desc": "浏览器自动化:导航/快照/点击/填表",
            },
            "filesystem": {
                "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home() / ".argos" / "workspace")],
                "transport": "stdio", "enabled": True, "trust": "builtin",
                "desc": "读写 workspace 内文件",
                "read_only_tools": ["read_file", "read_text_file", "list_directory", "directory_tree", "search_files", "get_file_info", "list_allowed_directories"],
            },
            "github": {
                "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
                "transport": "stdio", "enabled": False, "trust": "builtin",
                "desc": "GitHub 只读:issues/PR/仓库(需填 token 开启)",
                "read_only_tools": ["search_repositories", "get_file_contents", "list_issues", "get_issue", "list_pull_requests", "get_pull_request"],
            },
        }
    }


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """读 mcp.json;缺文件 → 写默认集并返回;坏文件 → 退回默认集(不崩)。"""
    if not path.exists():
        cfg = _default_config()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # 写不进去也返回默认(只读环境)
        return cfg
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return _default_config()


def _annotations(tool: BaseTool) -> dict[str, Any]:
    """挖出 MCP 工具的注解(readOnlyHint/destructiveHint)。
    实测(Task 1 探针,langchain-mcp-adapters 0.2.2 + 官方 filesystem server)注解**平铺在
    tool.metadata 顶层**,如 {"readOnlyHint": true, "destructiveHint": null, ...}。
    个别版本可能嵌在 metadata["annotations"] 下,故两处都看;读不到 → 空 → 走 fail-closed。"""
    md = getattr(tool, "metadata", None) or {}
    flat = {k: md[k] for k in ("readOnlyHint", "destructiveHint") if k in md}
    if flat:
        return flat
    nested = md.get("annotations")
    return nested if isinstance(nested, dict) else {}


def classify(tool: BaseTool, server_cfg: dict[str, Any]) -> tuple[bool, RiskLevel]:
    """返回 (是否需审批, 风险)。只读放行;有副作用/未知 fail-closed 套审批。"""
    ann = _annotations(tool)
    if ann.get("readOnlyHint") is True:
        return (False, "low")
    if tool.name in (server_cfg.get("read_only_tools") or []):
        return (False, "low")
    risk: RiskLevel = "high" if ann.get("destructiveHint") is True else "medium"
    return (True, risk)


def gate_mcp_tool(tool: BaseTool, risk: RiskLevel, server_name: str) -> BaseTool:
    """把一个 MCP 工具包成"先审批再执行"的等价工具,保名/保描述/保 args schema。"""
    async def _gated(**kwargs: Any) -> Any:
        return await approval.guarded_call(
            tool.name,
            dict(kwargs),
            lambda: tool.ainvoke(kwargs),
            description=f"经 MCP {server_name} 执行 {tool.name}",
            risk=risk,
        )

    return StructuredTool.from_function(
        coroutine=_gated,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )


_CONNECT_TIMEOUT = 25.0  # npx -y 首次拉包可能慢,给宽点;超时即降级


def _client_conn(cfg: dict[str, Any]) -> dict[str, Any]:
    """从 mcp.json 的 server 配置抽出 MultiServerMCPClient 需要的连接字段。"""
    conn: dict[str, Any] = {
        "command": cfg["command"],
        "args": cfg.get("args", []),
        "transport": cfg.get("transport", "stdio"),
    }
    if cfg.get("env"):
        conn["env"] = cfg["env"]
    return conn


async def load_mcp_tools(config: dict[str, Any]) -> tuple[list, list[dict[str, Any]]]:
    """逐 server 连接:成功 → 工具分类套闸并入合集;失败/超时 → 降级标 disconnected。
    返回 (工具合集, 每个 server 的状态)。任一 server 出问题绝不影响其余。"""
    tools_out: list = []
    status_out: list[dict[str, Any]] = []
    servers = (config or {}).get("servers", {})
    for name, cfg in servers.items():
        base = {
            "name": name,
            "transport": cfg.get("transport", "stdio"),
            "trust": cfg.get("trust", "builtin"),
            "desc": cfg.get("desc", ""),
        }
        if not cfg.get("enabled", False):
            status_out.append({**base, "status": "disabled", "tools": 0})
            continue
        try:
            client = MultiServerMCPClient({name: _client_conn(cfg)})
            raw = await asyncio.wait_for(client.get_tools(), timeout=_CONNECT_TIMEOUT)
            gated = []
            for t in raw:
                needs, risk = classify(t, cfg)
                gated.append(gate_mcp_tool(t, risk, name) if needs else t)
            tools_out.extend(gated)
            status_out.append({**base, "status": "connected", "tools": len(gated)})
        except Exception as e:  # noqa: BLE001 — 任何连接异常都降级,不许掀翻其余 server
            status_out.append({**base, "status": "disconnected", "tools": 0, "error": str(e)[:200]})
    return tools_out, status_out


# ── 进程级缓存:启动连一次,后续读缓存(import 期不连)──────────────────────────
_MCP_TOOLS: list = []
_MCP_STATUS: list[dict[str, Any]] = []
_loaded = False
_load_lock = asyncio.Lock()


async def ensure_loaded() -> None:
    """幂等:首次调用连接并缓存;后续直接返回。server 启动钩子与端点都可安全调。"""
    global _loaded, _MCP_TOOLS, _MCP_STATUS
    if _loaded:
        return
    async with _load_lock:
        if _loaded:
            return
        cfg = load_config()
        _MCP_TOOLS, _MCP_STATUS = await load_mcp_tools(cfg)
        _loaded = True


def mcp_tools() -> list:
    return list(_MCP_TOOLS)


def server_status() -> list[dict[str, Any]]:
    return list(_MCP_STATUS)
