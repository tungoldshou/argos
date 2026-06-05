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
    "propose_workflow",
    # 计算机控制(浏览器)—— broker-gated,host 侧 sync Playwright 专线程执行。
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_screenshot",
    # MCP 外部工具调度入口 —— broker-gated;配了 ~/.argos/mcp.json 才有具体工具可调,
    # 未配时调用诚实报"未配置 MCP"(工具本身始终可调,故计入工具数)。
    "mcp_call",
]

__all__ = [
    "build_namespace", "build_child_namespace",
    "ALL_TOOL_NAMES", "ALLOWED_CMDS", "GIT_READONLY_SUBCMDS",
    "WORKSPACE", "VERIFY_DIR",
    # workspace 牢笼 helpers(files.py / shell 路径解析共用)
    "_ws", "_vd", "_safe_path",
    # 沙箱工具 dispatcher(plan-mode 守卫) —— 供 dispatcher 层拦截 + 测试直接访问
    "run_command_gated", "write_file_gated", "edit_file_gated",
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

    # MCP 外部工具 —— broker-gated:host 侧 McpManager 转发到配置的 stdio server。
    def mcp_call_gated(server: str, tool: str, arguments: dict | None = None) -> str:
        return broker.request(action="mcp_call",
                              args={"server": server, "tool": tool, "arguments": arguments or {}})

    return {
        "run_command": run_command_gated,
        "web_search": web_search_gated,
        "web_extract": web_extract_gated,
        "browser_navigate": browser_navigate_gated,
        "browser_snapshot": browser_snapshot_gated,
        "browser_click": browser_click_gated,
        "browser_type": browser_type_gated,
        "browser_screenshot": browser_screenshot_gated,
        "mcp_call": mcp_call_gated,
    }


def _propose_workflow_pure(spec: dict) -> str:
    """propose_workflow({...}) 登记工作流规格,host 在异步态校验+审批+引擎执行(类似 propose_verify)。

    沙箱内仅给登记回执;真执行在 host(子进程拿不到回调)。
    spec: {name: str, stages: list[dict]}
    """
    name = (spec or {}).get("name", "?") if isinstance(spec, dict) else "?"
    n = len((spec or {}).get("stages", [])) if isinstance(spec, dict) else 0
    return f"[已登记工作流「{name}」:{n} 个 stage,待审批后执行]"


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


# ── 沙箱工具 dispatcher(plan-mode 守卫,spec §2.4) ───────────────────────
# 这些模块级函数是沙箱工具的 dispatcher 入口:plan mode 时返错误串不进沙箱;
# act mode 时调底层实现(本地纯沙箱 or 走 broker-gated RPC)。
# build_namespace 仍通过 _make_gated(broker) 给沙箱注入闭包版本(带 broker 引用),
# 这里暴露模块级版本主要是给 dispatcher 拦截 + 单测直接访问用。

_PLAN_MODE_BLOCKED_MSG = "错误:plan mode 不允许调沙箱工具(请先 ExitPlanMode 退出)。"


def run_command_gated(command: str) -> str:
    """dispatcher for run_command。plan mode 拦截(spec §2.4);否则走 broker-gated。"""
    from argos_agent.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _PLAN_MODE_BLOCKED_MSG
    # 模块级直调:broker 须由 build_namespace / build_child_namespace 先注入。
    # 沙箱真正执行走 build_namespace 注入的闭包版本(带 broker),不走这里。
    if _MODULE_BROKER is None:
        return "错误:broker 未初始化(模块级 dispatcher 仅供 plan_mode 单测直调)。"
    return _MODULE_BROKER.request(action="run_command", args={"command": command})


def write_file_gated(path: str, content: str) -> str:
    """dispatcher for write_file。plan mode 拦截;否则走 files.write_file。"""
    from argos_agent.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _PLAN_MODE_BLOCKED_MSG
    return files.write_file(path, content)


def edit_file_gated(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
    """dispatcher for edit_file。plan mode 拦截;否则走 files.edit_file。"""
    from argos_agent.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _PLAN_MODE_BLOCKED_MSG
    return files.edit_file(path, old, new, all_occurrences)


# 模块级 broker 引用 —— build_namespace / build_child_namespace 注入,
# 供模块级 run_command_gated dispatcher 直调(plan_mode 单测用)。
_MODULE_BROKER: Any = None


def _set_module_broker(broker: Any) -> None:
    """注入模块级 broker 引用(由 build_namespace / build_child_namespace 调)。"""
    global _MODULE_BROKER
    _MODULE_BROKER = broker


def _pure() -> dict[str, Any]:
    return {
        "read_file": files.read_file,
        "write_file": files.write_file,
        "edit_file": files.edit_file,
        "search_files": files.search_files,
        "propose_verify": _propose_verify_pure,
        "update_plan": _update_plan_pure,
        "propose_workflow": _propose_workflow_pure,
    }


def build_namespace(broker: Any) -> dict[str, Any]:
    """【host 侧】注入执行器命名空间的工具字典:纯沙箱原函数 + broker-gated 包装."""
    _set_module_broker(broker)  # 供模块级 run_command_gated dispatcher 直调
    ns: dict[str, Any] = {}
    ns.update(_pure())
    ns.update(_make_gated(broker))
    return ns


def build_child_namespace(
    broker: Any,
    *,
    allow_workflow: bool = True,
    read_only: bool = False,
) -> dict[str, Any]:
    """【沙箱子进程侧】命名空间:纯沙箱原函数 + 调 _broker(RPC stub)的 broker-gated 包装.

    broker=None 时 broker-gated 工具不注入(纯沙箱单测)。
    allow_workflow=True(默认):父 agent 保留 propose_workflow,否则沙箱里调它会 NameError。
    allow_workflow=False:子 agent spawn 时传入,深度护栏去掉 propose_workflow,工作流深度恒为 1。
    read_only=True:tool_scope=read 强制只读 —— 剔除一切会改动文件/系统/外部状态的工具,
    兑现审批预览里的「只读」承诺。子 agent 保留:read_file/search_files/web_search/web_extract/
    browser_navigate/browser_snapshot/browser_screenshot/propose_verify/update_plan。
    """
    ns: dict[str, Any] = {}
    ns.update(_pure())
    if broker is not None:
        _set_module_broker(broker)  # 供模块级 run_command_gated dispatcher 直调
        ns.update(_make_gated(broker))
    # 深度护栏:工作流深度恒为 1 —— 只有子 agent(allow_workflow=False)才去掉 propose_workflow;
    # 父 agent(默认 True)必须保留它,否则在沙箱里调 propose_workflow 会 NameError。
    if not allow_workflow:
        ns.pop("propose_workflow", None)
    # 只读作用域强制:tool_scope=read 的子 agent 剔除一切会改动文件/系统/外部状态的工具,
    # 真正兑现审批预览里的「只读」承诺(否则显示「只读」但实际仍能写,是审批所见即所跑的假承诺)。
    if read_only:
        for _t in ("write_file", "edit_file", "run_command",
                   "browser_click", "browser_type", "mcp_call"):
            ns.pop(_t, None)
    return ns


# 旧 LangChain `ALL_TOOLS`(带 .invoke() 的 StructuredTool)随 2026-06-05 死栈清理一并移除 ——
# 活引擎走 build_namespace(纯沙箱命名空间),不再需要 LangChain 工具对象。
