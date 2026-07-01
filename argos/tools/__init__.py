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
from .shell import ALLOWED_CMDS
from argos.i18n import t

# ── workspace / verify-dir 模块级常量(test_tools.py 会 monkeypatch.setattr 这里) ──────
WORKSPACE: Path = Path(os.environ.get("ARGOS_WORKSPACE",
                                      Path.home() / ".argos" / "workspace")).resolve()
VERIFY_DIR: Path = Path(os.environ.get("ARGOS_VERIFY_DIR",
                                       Path.home() / ".argos" / "verify")).resolve()

# UI 工具数必须等于此列表实长(spec/CLAUDE:禁 seed "60+ tools" 谎报)。
# ⚠️  deprecated:直接引用此静态常量已过时。
#     优先用 get_tool_names(registry) 从 CapabilityRegistry 动态派生(诚实计数来源)。
#     此常量保留为兼容别名,与 registry 注册结果保持一致(顺序与注册顺序对齐)。
ALL_TOOL_NAMES: list[str] = [
    "read_file", "write_file", "edit_file", "search_files",
    "run_command", "web_search", "web_extract", "propose_verify",
    "propose_dom_verify",  # A2 L3 DOM 验证声明（与 propose_verify 同构，结果由 DomProber 判定）
    "propose_gui_verify",  # 2d GUI 验证声明（截图+OCR 独立断言屏上文本，结果由 GuiProber 三态判定）
    "update_plan",
    "propose_workflow",
    # 计算机控制(浏览器)—— broker-gated,host 侧 sync Playwright 专线程执行。
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_screenshot",
    # MCP 外部工具调度入口 —— broker-gated;配了 ~/.argos/mcp.json 才有具体工具可调,
    # 未配时调用诚实报"未配置 MCP"(工具本身始终可调,故计入工具数)。
    "mcp_call",
    # LSP 工具 —— broker-gated,host 侧 LspManager 派发到对应 language server。
    "lsp_definition", "lsp_references", "lsp_hover",
    "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
    # computer use(P6a §10)—— OS 级控制;屏幕/鼠标是全局资源,Seatbelt 关不住;
    # 全部 risk=high + reversible=False + hard CONFIRM(四线管辖)。
    # 单一规范名 = 合法 Python 标识符(下划线):沙箱 ```python 块里 computer_click(...) 才调得动;
    # broker action / _RISK / registry / 回执 / ledger 全用同名(不再有点号/下划线两套)。
    "computer_screenshot", "computer_click", "computer_double_click",
    "computer_type_text", "computer_key", "computer_scroll", "computer_open_app",
]


def get_tool_names(
    registry: "Any | None" = None,
) -> list[str]:
    """返回当前可用工具名列表（诚实计数来源）。

    P3 动态化路径：
    - registry 非 None → 从 registry.names() 派生（权威来源，自动反映注册状态）。
    - registry=None   → 退回静态 ALL_TOOL_NAMES（兼容无 registry 的测试/headless 路径）。

    用法::

        # TUI /tools 命令（诚实计数）
        from argos.tools import get_tool_names
        names = get_tool_names(self._components.registry if self._components else None)

        # hooks/payload 工具名扫描
        names = get_tool_names()  # headless 路径，退静态表
    """
    if registry is not None:
        try:
            # 诚实计数:只数模型在沙箱里【真正可调用】的工具,排除宿主进程专属能力(沙箱外跑、
            # 无命名空间包装)。否则 /tools 报的数 > 真实可调用数,违反诚实铁律。
            return list(registry.callable_names())
        except Exception:   # noqa: BLE001 — 防御性降级，不因 registry 异常崩
            pass
    return list(ALL_TOOL_NAMES)

__all__ = [
    "build_namespace", "build_child_namespace",
    "ALL_TOOL_NAMES", "get_tool_names",
    "ALLOWED_CMDS",
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
            from argos import runtime
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
            from argos import runtime
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

    # computer use(P6a §10)—— broker-gated:host 侧 ComputerExecutor 执行 OS 级操作。
    # 全部 risk=high + reversible=False + hard CONFIRM;
    # Seatbelt 关不住屏幕/鼠标资源,用"审批+Ledger+高 risk"治理。
    def computer_screenshot_gated() -> str:
        return broker.request(action="computer_screenshot", args={})

    def computer_click_gated(x: int, y: int) -> str:
        return broker.request(action="computer_click", args={"x": x, "y": y})

    def computer_double_click_gated(x: int, y: int) -> str:
        return broker.request(action="computer_double_click", args={"x": x, "y": y})

    def computer_type_text_gated(text: str) -> str:
        return broker.request(action="computer_type_text", args={"text": text})

    def computer_key_gated(key: str) -> str:
        return broker.request(action="computer_key", args={"text": key})

    def computer_scroll_gated(x: int, y: int, dy: int = 3) -> str:
        return broker.request(action="computer_scroll", args={"x": x, "y": y, "text": str(dy)})

    def computer_open_app_gated(app: str) -> str:
        return broker.request(action="computer_open_app", args={"app": app})

    # LSP 工具 —— broker-gated:host 侧 LspManager.request(...)
    # 走 broker.action="lsp_*" 派发,host broker._execute 调 manager
    def lsp_definition_gated(file: str, line: int, col: int) -> str:
        return broker.request(action="lsp_definition",
                              args={"file": file, "line": line, "col": col})
    def lsp_references_gated(file: str, line: int, col: int, *, include_declaration: bool = True) -> str:
        return broker.request(action="lsp_references",
                              args={"file": file, "line": line, "col": col,
                                    "include_declaration": include_declaration})
    def lsp_hover_gated(file: str, line: int, col: int) -> str:
        return broker.request(action="lsp_hover",
                              args={"file": file, "line": line, "col": col})
    def lsp_document_symbols_gated(file: str) -> str:
        return broker.request(action="lsp_document_symbols", args={"file": file})
    def lsp_workspace_symbols_gated(query: str) -> str:
        return broker.request(action="lsp_workspace_symbols", args={"query": query})
    def lsp_diagnostics_gated(file: str) -> str:
        return broker.request(action="lsp_diagnostics", args={"file": file})

    # 文件写 —— broker-gated(gate-only):先问 broker 要 host 侧治理裁决(hard-path/密钥/回执),
    # 放行(收到哨兵)后由本包装在【沙箱子进程内】真正落盘(写留在 Seatbelt,Codex 式自动应用)。
    def write_file_gated(path: str, content: str) -> str:
        verdict = broker.request(action="write_file", args={"path": path, "content": content})
        if verdict == files.WRITE_APPROVED_SENTINEL:
            return files.write_file(path, content)
        return verdict

    def edit_file_gated(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
        # content=new 让 evaluator 密钥检测命中替换后的新文本(evaluator 看 content 字段)。
        verdict = broker.request(action="edit_file", args={
            "path": path, "old": old, "new": new,
            "all_occurrences": all_occurrences, "content": new,
        })
        if verdict == files.WRITE_APPROVED_SENTINEL:
            return files.edit_file(path, old, new, all_occurrences)
        return verdict

    return {
        "run_command": run_command_gated,
        "write_file": write_file_gated,
        "edit_file": edit_file_gated,
        "web_search": web_search_gated,
        "web_extract": web_extract_gated,
        "browser_navigate": browser_navigate_gated,
        "browser_snapshot": browser_snapshot_gated,
        "browser_click": browser_click_gated,
        "browser_type": browser_type_gated,
        "browser_screenshot": browser_screenshot_gated,
        "mcp_call": mcp_call_gated,
        # 模型可见名=合法标识符(下划线);wrapper 内部仍发 broker action "computer.*"(点号)。
        "computer_screenshot": computer_screenshot_gated,
        "computer_click": computer_click_gated,
        "computer_double_click": computer_double_click_gated,
        "computer_type_text": computer_type_text_gated,
        "computer_key": computer_key_gated,
        "computer_scroll": computer_scroll_gated,
        "computer_open_app": computer_open_app_gated,
        "lsp_definition": lsp_definition_gated,
        "lsp_references": lsp_references_gated,
        "lsp_hover": lsp_hover_gated,
        "lsp_document_symbols": lsp_document_symbols_gated,
        "lsp_workspace_symbols": lsp_workspace_symbols_gated,
        "lsp_diagnostics": lsp_diagnostics_gated,
    }


def _propose_workflow_pure(spec: dict) -> str:
    """propose_workflow({...}) 登记工作流规格,host 在异步态校验+审批+引擎执行(类似 propose_verify)。

    沙箱内仅给登记回执;真执行在 host(子进程拿不到回调)。
    spec: {name: str, stages: list[dict]}
    """
    name = (spec or {}).get("name", "?") if isinstance(spec, dict) else "?"
    n = len((spec or {}).get("stages", [])) if isinstance(spec, dict) else 0
    return t("tools.propose_workflow.registered", name=name, n=n)


def _propose_verify_pure(command: str) -> str:
    """声明用于验证本次改动的命令(如 'pytest tests/test_x.py')。

    真验证门:沙箱是独立子进程,这里仅给个登记回执;host loop 在 act 循环解析 agent 输出里的
    propose_verify('<cmd>') 登记命令,收尾时由 harness 在隔离 verify_dir 独立运行它(退出码为准),
    agent 碰不到执行 —— 防 agent 篡改评判它的测试作弊。
    """
    return t("tools.propose_verify.registered", command=command)


def _propose_dom_verify_pure(
    url: str,
    selector: str = "body",
    expected_text: str = "",
) -> str:
    """声明用 DOM 探针验证网页改动。

    与 propose_verify 同构：沙箱是独立子进程，这里仅给登记回执；host loop 解析 agent
    输出里的 propose_dom_verify(url=..., selector=..., expected_text=...) 登记 L3 策略，
    收尾时由 DomProber 在 host 侧独立执行（agent 碰不到），以 found/error 三态为准。

    Args:
        url:           要验证的页面 URL（必须 http/https）。
        selector:      CSS 选择器（可选；用于定位目标元素，辅助 expected_text 定位）。
        expected_text: 页面应包含的文本（强烈推荐）；有 expected_text 时走强证据路径
                       可产 passed/failed；无 expected_text 时结果最高为 unverifiable。
    """
    parts = [f"url={url!r}"]
    if selector and selector != "body":
        parts.append(f"selector={selector!r}")
    if expected_text:
        parts.append(f"expected_text={expected_text!r}")
    return t("tools.propose_dom_verify.registered", parts=", ".join(parts))


def _propose_gui_verify_pure(expected_text: str) -> str:
    """声明用 GUI 探针验证电脑控制(OS 级)改动 —— 截图 + 独立 OCR 断言屏上应出现的文本。

    与 propose_verify/propose_dom_verify 同构:沙箱是独立子进程,这里仅给登记回执;host loop
    解析 propose_gui_verify(expected_text=...) 登记策略,收尾时由 GuiProber 在 host 侧截图 + OCR
    独立断言(agent 碰不到),以 passed/failed/unverifiable 三态为准。OCR 用的是与你无关的确定性
    识别(绝不反过来问你"成功没"——那是自证)。OCR/截图不可用 → unverifiable(诚实,不假装成功)。

    Args:
        expected_text: 操作完成后屏幕上应出现的文本(必填;声明式内容断言)。
    """
    return t("tools.propose_gui_verify.registered", expected_text=expected_text)


def _update_plan_pure(todos: list[dict]) -> str:
    """列出/更新任务的子任务清单(真 TODO 拆解,借 Claude Code TodoWrite)。

    沙箱是独立子进程,这里仅给个登记回执;host loop 解析 agent 输出里的
    update_plan([...]) 把 todos 传回 host,yield PlanUpdate 驱动活动栏渲染(类似 propose_verify)。
    todos:[{content, status: pending|in_progress|completed, activeForm}]。
    """
    n = len(todos) if isinstance(todos, list) else 0
    return t("tools.update_plan.registered", n=n)


# ── 沙箱工具 dispatcher(plan-mode 守卫,spec §2.4) ───────────────────────
# 这些模块级函数是沙箱工具的 dispatcher 入口:plan mode 时返错误串不进沙箱;
# act mode 时调底层实现(本地纯沙箱 or 走 broker-gated RPC)。
# build_namespace 仍通过 _make_gated(broker) 给沙箱注入闭包版本(带 broker 引用),
# 这里暴露模块级版本主要是给 dispatcher 拦截 + 单测直接访问用。

def _plan_mode_blocked_msg() -> str:
    return t("tools.plan_mode.blocked")


def run_command_gated(command: str) -> str:
    """dispatcher for run_command。plan mode 拦截(spec §2.4);否则走 broker-gated。"""
    from argos.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _plan_mode_blocked_msg()
    # 模块级直调:broker 须由 build_namespace / build_child_namespace 先注入。
    # 沙箱真正执行走 build_namespace 注入的闭包版本(带 broker),不走这里。
    if _MODULE_BROKER is None:
        return t("tools.broker.uninitialized")
    return _MODULE_BROKER.request(action="run_command", args={"command": command})


def write_file_gated(path: str, content: str) -> str:
    """dispatcher for write_file。plan mode 拦截;否则走 files.write_file。"""
    from argos.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _plan_mode_blocked_msg()
    return files.write_file(path, content)


def edit_file_gated(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
    """dispatcher for edit_file。plan mode 拦截;否则走 files.edit_file。"""
    from argos.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _plan_mode_blocked_msg()
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
        "search_files": files.search_files,
        # write_file/edit_file 已移到 _make_gated(broker-gated gate-only):无 broker 的纯沙箱
        # 命名空间不含写工具(诚实 fail-closed:不能治理就不给写),只读工具仍在。
        "propose_verify": _propose_verify_pure,
        "propose_dom_verify": _propose_dom_verify_pure,  # A2 L3 DOM 验证桩（登记回执，真执行在 host）
        "propose_gui_verify": _propose_gui_verify_pure,  # 2d GUI 验证桩（登记回执，host 侧 GuiProber 断言）
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
    tool_allowlist: "list[str] | tuple[str, ...] | frozenset[str] | None" = None,
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
    if tool_allowlist is not None:
        # 角色白名单是【权威】:命名空间 = 可用工具 ∩ 白名单 → 物理剔除其余(兑现 spec.py:45 的承诺,
        # 此前 build_child_namespace 根本不收 allowlist、从未做交集 → 角色声明与实际工具分叉:
        # explorer 声明只读却拿到 web/浏览器/截屏,reviewer 声明的 run_command 反被 read_only 误剥)。
        # 白名单已编码该角色完整作用域(只读角色的白名单本就不含写工具),故不再叠加 read_only 剥离
        # —— 否则 reviewer 的 run_command 仍会被 read_only 干掉(2026-06-18 排查 #6)。
        allow = set(tool_allowlist)
        for _t in list(ns):
            if _t not in allow:
                ns.pop(_t, None)
    elif read_only:
        # 无角色白名单(旧 tool_scope 派生路径):read 作用域剔除一切会改动文件/系统/外部状态的工具,
        # 真正兑现审批预览里的「只读」承诺(否则显示「只读」但实际仍能写,是审批所见即所跑的假承诺)。
        for _t in ("write_file", "edit_file", "run_command",
                   "browser_click", "browser_type", "mcp_call",
                   # OS 级写动作:read 作用域必须剔除(computer_screenshot 是只读观察,保留)。
                   "computer_click", "computer_double_click", "computer_type_text",
                   "computer_key", "computer_scroll", "computer_open_app"):
            ns.pop(_t, None)
    return ns


# 旧 LangChain `ALL_TOOLS`(带 .invoke() 的 StructuredTool)随 2026-06-05 死栈清理一并移除 ——
# 活引擎走 build_namespace(纯沙箱命名空间),不再需要 LangChain 工具对象。
