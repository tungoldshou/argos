"""Argos 工具注册表(契约 §4).

工具 = 注入沙箱执行器命名空间的 Python 函数(变量跨 code-action 步骤存活)。
  · 纯沙箱(read_file/write_file/edit_file/search_files):沙箱内直接跑,零审批。
  · broker-gated(run_command/web_search/web_extract[/playwright]):函数体调 _broker.request
    跨进程 RPC 到 host,经审批拨盘 + egress 裁决后执行,结果灌回沙箱。
命名沿用旧 tools.py 函数名,不改名。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import files
from .shell import ALLOWED_CMDS, GIT_READONLY_SUBCMDS

# ── workspace / verify-dir 模块级常量(test_tools.py 会 monkeypatch.setattr 这里) ──────
WORKSPACE: Path = Path(os.environ.get("ARGOS_WORKSPACE",
                                      Path.home() / ".argos" / "workspace")).resolve()
VERIFY_DIR: Path = Path(os.environ.get("ARGOS_VERIFY_DIR",
                                       Path.home() / ".argos" / "verify")).resolve()

# UI 工具数必须等于此列表实长(spec/CLAUDE:禁 seed "60+ tools" 谎报)。
ALL_TOOL_NAMES: list[str] = [
    "read_file", "write_file", "edit_file", "search_files",
    "run_command", "web_search", "web_extract", "propose_verify",
    "update_plan",
    # 计算机控制(浏览器)—— broker-gated,host 侧 sync Playwright 专线程执行。
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_screenshot",
]

__all__ = [
    "build_namespace", "build_child_namespace",
    "ALL_TOOL_NAMES", "ALLOWED_CMDS", "GIT_READONLY_SUBCMDS",
    "WORKSPACE", "VERIFY_DIR",
    # workspace 牢笼 helpers(files.py / shell 路径解析共用)
    "_ws", "_vd", "_safe_path",
]


# ── 遗留 workspace / verify-dir helpers(verify_gate.py / test_tools.py 等引用) ─────────
def _ws() -> Path:
    """当前生效 workspace(遗留符号,供 verify_gate.py / 旧路径使用)。
    优先尊重模块级 WORKSPACE(test_tools.py monkeypatch 打这里),
    再查 runtime 上下文覆盖。"""
    import sys
    mod = sys.modules[__name__]
    ws_attr = getattr(mod, "WORKSPACE", None)
    if ws_attr is not None:
        try:
            from argos_agent import runtime
            ctx = runtime.current()
            if ctx.project_mode:
                return ctx.workspace
        except Exception:  # noqa: BLE001
            pass
        return ws_attr
    return files._ws()  # noqa: SLF001


def _vd() -> Path:
    """当前生效 verify 隔离区(遗留符号)。"""
    import sys
    mod = sys.modules[__name__]
    vd_attr = getattr(mod, "VERIFY_DIR", None)
    if vd_attr is not None:
        try:
            from argos_agent import runtime
            ctx = runtime.current()
            if ctx.project_mode:
                return ctx.verify_dir
        except Exception:  # noqa: BLE001
            pass
        return vd_attr
    return VERIFY_DIR


def _safe_path(rel: str) -> Path | None:
    """workspace 路径牢笼(遗留符号)。"""
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    p = (ws / rel).resolve()
    try:
        p.relative_to(ws)
    except ValueError:
        return None
    return p


# ── 新 Phase 3 contract API ──────────────────────────────────────────────────

def _make_gated(broker: Any) -> dict[str, Any]:
    """造 broker-gated 工具包装(契约 §4 broker-call 约定).

    broker 既可是 host 侧 CapabilityBroker(build_namespace),也可是沙箱内 _BrokerStub
    (build_child_namespace) —— 二者都暴露 .request(action, args)。
    """
    def run_command_gated(command: str) -> str:
        return broker.request(action="run_command", args={"command": command})

    def web_search_gated(query: str, limit: int = 5) -> str:
        return broker.request(action="web_search", args={"query": query, "limit": limit})

    def web_extract_gated(url: str) -> str:
        return broker.request(action="web_extract", args={"url": url})

    # 计算机控制(浏览器)—— broker-gated:host 侧 BrowserController 独占线程跑 sync Playwright。
    def browser_navigate_gated(url: str) -> str:
        return broker.request(action="browser_navigate", args={"url": url})

    def browser_snapshot_gated(max_chars: int = 4000) -> str:
        return broker.request(action="browser_snapshot", args={"max_chars": max_chars})

    def browser_click_gated(selector: str) -> str:
        return broker.request(action="browser_click", args={"selector": selector})

    def browser_type_gated(selector: str, text: str) -> str:
        return broker.request(action="browser_type", args={"selector": selector, "text": text})

    def browser_screenshot_gated(path: str = "screenshot.png") -> str:
        return broker.request(action="browser_screenshot", args={"path": path})

    return {
        "run_command": run_command_gated,
        "web_search": web_search_gated,
        "web_extract": web_extract_gated,
        "browser_navigate": browser_navigate_gated,
        "browser_snapshot": browser_snapshot_gated,
        "browser_click": browser_click_gated,
        "browser_type": browser_type_gated,
        "browser_screenshot": browser_screenshot_gated,
    }


def _propose_verify_pure(command: str) -> str:
    """声明用于验证本次改动的命令(如 'pytest tests/test_x.py')。

    真验证门:沙箱是独立子进程,这里仅给个登记回执;host loop 在 act 循环解析 agent 输出里的
    propose_verify('<cmd>') 登记命令,收尾时由 harness 在隔离 verify_dir 独立运行它(退出码为准),
    agent 碰不到执行 —— 防 agent 篡改评判它的测试作弊。
    """
    return f"已登记验证命令:{command}(收尾时由 harness 独立运行,以退出码为准)"


def _update_plan_pure(todos: list[dict]) -> str:
    """列出/更新任务的子任务清单(真 TODO 拆解,借 Claude Code TodoWrite)。

    沙箱是独立子进程,这里仅给个登记回执;host loop 解析 agent 输出里的
    update_plan([...]) 把 todos 传回 host,yield PlanUpdate 驱动活动栏渲染(类似 propose_verify)。
    todos:[{content, status: pending|in_progress|completed, activeForm}]。
    """
    n = len(todos) if isinstance(todos, list) else 0
    return f"已更新任务清单({n} 项,活动栏将渲染进度)。"


def _pure() -> dict[str, Any]:
    return {
        "read_file": files.read_file,
        "write_file": files.write_file,
        "edit_file": files.edit_file,
        "search_files": files.search_files,
        "propose_verify": _propose_verify_pure,
        "update_plan": _update_plan_pure,
    }


def build_namespace(broker: Any) -> dict[str, Any]:
    """【host 侧】注入执行器命名空间的工具字典:纯沙箱原函数 + broker-gated 包装."""
    ns: dict[str, Any] = {}
    ns.update(_pure())
    ns.update(_make_gated(broker))
    return ns


def build_child_namespace(broker: Any) -> dict[str, Any]:
    """【沙箱子进程侧】命名空间:纯沙箱原函数 + 调 _broker(RPC stub)的 broker-gated 包装.

    broker=None 时 broker-gated 工具不注入(纯沙箱单测)。
    """
    ns: dict[str, Any] = {}
    ns.update(_pure())
    if broker is not None:
        ns.update(_make_gated(broker))
    return ns


# 旧 LangChain `ALL_TOOLS`(带 .invoke() 的 StructuredTool)随 2026-06-05 死栈清理一并移除 ——
# 活引擎走 build_namespace(纯沙箱命名空间),不再需要 LangChain 工具对象。
