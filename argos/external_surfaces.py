"""沙箱外执行面警告(#9)。

lsp / hooks / mcp 三个子系统在 OS 沙箱(Seatbelt)【外】以子进程运行用户控制的代码/命令 ——
它们读 ~/.argos/{lsp,hooks,mcp}.json,启动 language server / 生命周期钩子 / MCP server。
这些是 user-controlled code,不受 Seatbelt 网络与写入约束。

CLAUDE.md 承诺 "warned at startup";此模块兑现:装配时检测用户是否配置了这些 surface,
非空则发警告,诚实告知信任边界(不假装一切都在沙箱里)。
"""
from __future__ import annotations

from pathlib import Path

# 三个沙箱外子系统的 config 文件名 → 人话警告(用户配了 = 有沙箱外执行面)。
_SURFACES: tuple[tuple[str, str], ...] = (
    ("hooks.json", "hooks(~/.argos/hooks.json):生命周期钩子在沙箱外运行你配置的命令"),
    ("lsp.json", "lsp(~/.argos/lsp.json):language server 在沙箱外作为子进程运行"),
    ("mcp.json", "mcp(~/.argos/mcp.json):MCP server 在沙箱外作为子进程运行"),
)


def external_surface_warnings(argos_dir: Path | None = None) -> list[str]:
    """返回用户已配置的沙箱外执行面警告列表(空 = 没配任何外部 surface)。

    检测 ~/.argos/{hooks,lsp,mcp}.json 是否存在:存在 = 用户显式配置了在沙箱外运行的子进程
    (language server / 生命周期钩子 / MCP server)。这些是 user-controlled code,不受
    Seatbelt 约束 —— 诚实告知,绝不假装它们也在沙箱里。

    argos_dir:配置目录(测试可注入;默认 ~/.argos)。
    """
    base = argos_dir if argos_dir is not None else (Path.home() / ".argos")
    out: list[str] = []
    for filename, message in _SURFACES:
        if (base / filename).exists():
            out.append(message)
    return out
