"""Internal documentation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import files
from .shell import ALLOWED_CMDS
from argos.i18n import t

WORKSPACE: Path | None = None
VERIFY_DIR: Path | None = None


def _config_root() -> Path:
    from argos import config
    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()

ALL_TOOL_NAMES: list[str] = [
    "read_file", "write_file", "edit_file", "search_files",
    "run_command", "web_search", "web_extract", "propose_verify",
    "propose_dom_verify",
    "propose_gui_verify",
    "update_plan",
    "propose_workflow",
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_screenshot",
    "mcp_call",
    "lsp_definition", "lsp_references", "lsp_hover",
    "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
    "computer_screenshot", "computer_click", "computer_double_click",
    "computer_type_text", "computer_key", "computer_scroll", "computer_open_app",
]


def get_tool_names(
    registry: "Any | None" = None,
) -> list[str]:
    """Internal documentation."""
    if registry is not None:
        try:
            return list(registry.callable_names())
        except Exception:   # noqa: BLE001
            pass
    return list(ALL_TOOL_NAMES)

__all__ = [
    "build_namespace", "build_child_namespace",
    "ALL_TOOL_NAMES", "get_tool_names",
    "ALLOWED_CMDS",
    "WORKSPACE", "VERIFY_DIR",
    "_ws", "_vd", "_safe_path",
    "run_command_gated", "write_file_gated", "edit_file_gated",
]


def _ws() -> Path:
    """Internal documentation."""
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
    """Internal documentation."""
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
    try:
        from argos import runtime
        ctx = runtime.current()
        if ctx.project_mode:
            return ctx.verify_dir
    except Exception:  # noqa: BLE001
        pass
    return Path(os.environ.get("ARGOS_VERIFY_DIR") or (_config_root() / "verify")).expanduser().resolve()


def _safe_path(rel: str) -> Path | None:
    """Internal documentation."""
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    p = (ws / rel).resolve()
    try:
        p.relative_to(ws)
    except ValueError:
        return None
    return p



def _make_gated(broker: Any) -> dict[str, Any]:
    """Internal documentation."""
    def run_command_gated(command: str) -> str:
        return broker.request(action="run_command", args={"command": command})

    def web_search_gated(query: str, limit: int = 5) -> str:
        return broker.request(action="web_search", args={"query": query, "limit": limit})

    def web_extract_gated(url: str) -> str:
        return broker.request(action="web_extract", args={"url": url})

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

    def mcp_call_gated(server: str, tool: str, arguments: dict | None = None) -> str:
        return broker.request(action="mcp_call",
                              args={"server": server, "tool": tool, "arguments": arguments or {}})

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

    def write_file_gated(path: str, content: str) -> str:
        verdict = broker.request(action="write_file", args={"path": path, "content": content})
        if verdict == files.WRITE_APPROVED_SENTINEL:
            return files.write_file(path, content)
        return verdict

    def edit_file_gated(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
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
    """Internal documentation."""
    name = (spec or {}).get("name", "?") if isinstance(spec, dict) else "?"
    n = len((spec or {}).get("stages", [])) if isinstance(spec, dict) else 0
    return t("tools.propose_workflow.registered", name=name, n=n)


def _propose_verify_pure(command: str) -> str:
    """Internal documentation."""
    return t("tools.propose_verify.registered", command=command)


def _propose_dom_verify_pure(
    url: str,
    selector: str = "body",
    expected_text: str = "",
) -> str:
    """Internal documentation."""
    parts = [f"url={url!r}"]
    if selector and selector != "body":
        parts.append(f"selector={selector!r}")
    if expected_text:
        parts.append(f"expected_text={expected_text!r}")
    return t("tools.propose_dom_verify.registered", parts=", ".join(parts))


def _propose_gui_verify_pure(expected_text: str) -> str:
    """Internal documentation."""
    return t("tools.propose_gui_verify.registered", expected_text=expected_text)


def _update_plan_pure(todos: list[dict]) -> str:
    """Internal documentation."""
    n = len(todos) if isinstance(todos, list) else 0
    return t("tools.update_plan.registered", n=n)



def _plan_mode_blocked_msg() -> str:
    return t("tools.plan_mode.blocked")


def run_command_gated(command: str) -> str:
    """Internal documentation."""
    from argos.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _plan_mode_blocked_msg()
    if _MODULE_BROKER is None:
        return t("tools.broker.uninitialized")
    return _MODULE_BROKER.request(action="run_command", args={"command": command})


def write_file_gated(path: str, content: str) -> str:
    """Internal documentation."""
    from argos.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _plan_mode_blocked_msg()
    return files.write_file(path, content)


def edit_file_gated(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
    """Internal documentation."""
    from argos.core.plan_mode import is_plan_mode
    if is_plan_mode():
        return _plan_mode_blocked_msg()
    return files.edit_file(path, old, new, all_occurrences)


_MODULE_BROKER: Any = None


def _set_module_broker(broker: Any) -> None:
    """Internal documentation."""
    global _MODULE_BROKER
    _MODULE_BROKER = broker


def _pure() -> dict[str, Any]:
    return {
        "read_file": files.read_file,
        "search_files": files.search_files,
        "propose_verify": _propose_verify_pure,
        "propose_dom_verify": _propose_dom_verify_pure,
        "propose_gui_verify": _propose_gui_verify_pure,
        "update_plan": _update_plan_pure,
        "propose_workflow": _propose_workflow_pure,
    }


def build_namespace(broker: Any) -> dict[str, Any]:
    """Internal documentation."""
    _set_module_broker(broker)
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
    """Internal documentation."""
    ns: dict[str, Any] = {}
    ns.update(_pure())
    if broker is not None:
        _set_module_broker(broker)
        ns.update(_make_gated(broker))
    if not allow_workflow:
        ns.pop("propose_workflow", None)
    if tool_allowlist is not None:
        allow = set(tool_allowlist)
        for _t in list(ns):
            if _t not in allow:
                ns.pop(_t, None)
    elif read_only:
        for _t in ("write_file", "edit_file", "run_command",
                   "browser_click", "browser_type", "mcp_call",
                   "computer_click", "computer_double_click", "computer_type_text",
                   "computer_key", "computer_scroll", "computer_open_app"):
            ns.pop(_t, None)
    return ns
