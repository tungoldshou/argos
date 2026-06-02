"""MCP 插座 —— 按 ~/.argos/mcp.json 连 stdio MCP server,工具套审批闸后并进 ALL_TOOLS。

设计见 docs/superpowers/specs/2026-06-02-mcp-socket-design.md。要点:
  · 逐 server 连接,任一失败优雅降级(标 disconnected,其余照常),绝不崩 sidecar。
  · 工具分类 fail-closed:只读放行,有副作用/未知一律过审批闸(approval.py)。
  · import 期无副作用;真正连接在 server 启动钩子里调 ensure_loaded()。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
