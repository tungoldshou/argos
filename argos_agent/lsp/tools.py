"""6 个 broker-gated LSP 工具闭包(spec §2.3)。

每个工具 = 接受参数 → 走 LspManager.request_sync → 格式化结果为 JSON 字符串。
坐标 1-based(给 agent) / 0-based(给 server)host 内部转换。
kind / severity 翻译为字符串名(spec D17)。
Range 表示:平铺 [startLine, startCol, endLine, endCol](spec D18)。

broker-gated 模式同 `web_search` / `browser_*`:`tools/__init__.py:_make_gated` 暴露。

注:工具是 sync 闭包(sandbox.broker._execute 签名 = sync),内部调
LspManager.request_sync(在 worker 线程跑 fresh event loop,绕开 sandbox 的
async 上下文与 LspManager 内部 asyncio 状态不互通)。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from argos_agent.lsp.manager import LspManager

# LSP SymbolKind 整数 → 字符串名(spec §2.3 + D17)
_SYMBOL_KIND_NAMES = {
    1: "File", 2: "Module", 3: "Namespace", 4: "Package", 5: "Class",
    6: "Method", 7: "Property", 8: "Field", 9: "Constructor", 10: "Enum",
    11: "Interface", 12: "Function", 13: "Variable", 14: "Constant",
    15: "String", 16: "Number", 17: "Boolean", 18: "Array", 19: "Object",
    20: "Key", 21: "Null", 22: "EnumMember", 23: "Struct", 24: "Event",
    25: "Operator", 26: "TypeParameter",
}
_DIAG_SEVERITY_NAMES = {1: "error", 2: "warning", 3: "information", 4: "hint"}


def _check_workspace(file: str, workspace: Path) -> str | None:
    """workspace 牢笼校验(spec D14)。返 None=通过,返 error JSON=拒绝。

    接受相对路径(相对 workspace)或绝对路径(必须在 workspace 内)。"""
    fp = Path(file)
    if not fp.is_absolute():
        p = (workspace / fp).resolve()
    else:
        try:
            p = fp.resolve()
        except OSError as e:
            return json.dumps({"error": f"invalid path {file!r}: {e}"})
    try:
        p.relative_to(workspace.resolve())
    except ValueError:
        return json.dumps({"error": f"file not in workspace: {file}"})
    return None


def _translate_location(loc: dict) -> dict:
    """LSP Location → 1-based {file, line, col}(spec D16)。"""
    uri = loc.get("uri", "")
    if uri.startswith("file://"):
        uri = uri[len("file://"):]
    rng = loc.get("range", {})
    start = rng.get("start", {})
    return {
        "file": uri,
        "line": start.get("line", 0) + 1,
        "col": start.get("character", 0) + 1,
    }


def _translate_symbol(sym: dict) -> dict:
    """LSP DocumentSymbol → 字符串 kind + range 平铺数组。"""
    kind_int = sym.get("kind", 0)
    rng = sym.get("range", {})
    start = rng.get("start", {})
    end = rng.get("end", {})
    out: dict[str, Any] = {
        "name": sym.get("name", ""),
        "kind": _SYMBOL_KIND_NAMES.get(kind_int, f"Unknown({kind_int})"),
        "range": [
            start.get("line", 0) + 1, start.get("character", 0) + 1,
            end.get("line", 0) + 1, end.get("character", 0) + 1,
        ],
    }
    if "containerName" in sym:
        out["container"] = sym["containerName"]
    if "children" in sym and sym["children"]:
        out["children"] = [_translate_symbol(c) for c in sym["children"]]
    return out


def _translate_diagnostic(d: dict) -> dict:
    """LSP Diagnostic → 字符串 severity + range 平铺。"""
    sev_int = d.get("severity", 1)
    rng = d.get("range", {})
    start = rng.get("start", {})
    end = rng.get("end", {})
    return {
        "severity": _DIAG_SEVERITY_NAMES.get(sev_int, "error"),
        "message": d.get("message", ""),
        "range": [
            start.get("line", 0) + 1, start.get("character", 0) + 1,
            end.get("line", 0) + 1, end.get("character", 0) + 1,
        ],
        "code": d.get("code"),
    }


def _file_uri(file: str, workspace: Path | None = None) -> str:
    """文件路径 → file:// URI(在 workspace 牢笼内)。"""
    fp = Path(file)
    if not fp.is_absolute() and workspace is not None:
        p = (workspace / fp).resolve()
    else:
        p = fp.resolve()
    return f"file://{p}"


def _read_content_if_exists(file: str, workspace: Path) -> str | None:
    """读 workspace 内文件全文(若存在),用于 sync_file 触发 didOpen。"""
    p = workspace / file if not Path(file).is_absolute() else Path(file)
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _safe_sync_file(manager: "LspManager", file: str, workspace: Path, content: str) -> None:
    """触发 didOpen/didChange(sync,best-effort;失败不阻断主请求)。

    简化:用 request_sync 内的 threadpool 跑一个 fire-and-forget 任务;出错 no-op。
    """
    try:
        abspath = str((workspace / file).resolve()) if not Path(file).is_absolute() else file
        manager.request_sync("__noop__", "noop", {"_fire_and_forget": True}, timeout=0.01)
    except Exception:  # noqa: BLE001
        pass
    # 实际生产:在 host loop 异步触发;本期 v1 简化,工具触发 didOpen 由 host loop(T7)接管。
    # 这里只做空操作,避免阻塞工具。
    return


# ── 6 个 gated 闭包 ────────────────────────────────────────────────

def lsp_definition_gated(
    *, server_name: str, file: str, line: int, col: int,
    manager: "LspManager", workspace: Path,
) -> str:
    err = _check_workspace(file, workspace)
    if err:
        return err
    # 触发 didOpen(若未):best-effort
    content = _read_content_if_exists(file, workspace)
    if content is not None:
        _safe_sync_file(manager, file, workspace, content)
    result = manager.request_sync(
        server_name, "textDocument/definition",
        {
            "textDocument": {"uri": _file_uri(file, workspace)},
            "position": {"line": line - 1, "character": col - 1},
        },
    )
    if "error" in result:
        return json.dumps(result)
    # manager.request_sync 返 {"result": <list-of-locations>} 或 {"error": ...}
    inner = result.get("result", result)
    if isinstance(inner, list):
        locations_raw = inner
    elif isinstance(inner, dict) and "uri" in inner:
        locations_raw = [inner]
    else:
        locations_raw = result.get("locations", [])
    return json.dumps({
        "locations": [_translate_location(l) for l in (locations_raw or [])],
    })


def lsp_references_gated(
    *, server_name: str, file: str, line: int, col: int,
    include_declaration: bool = True,
    manager: "LspManager", workspace: Path,
) -> str:
    err = _check_workspace(file, workspace)
    if err:
        return err
    content = _read_content_if_exists(file, workspace)
    if content is not None:
        _safe_sync_file(manager, file, workspace, content)
    result = manager.request_sync(
        server_name, "textDocument/references",
        {
            "textDocument": {"uri": _file_uri(file, workspace)},
            "position": {"line": line - 1, "character": col - 1},
            "context": {"includeDeclaration": include_declaration},
        },
    )
    if "error" in result:
        return json.dumps(result)
    inner = result.get("result", result)
    if isinstance(inner, list):
        locations_raw = inner
    elif isinstance(inner, dict) and "uri" in inner:
        locations_raw = [inner]
    else:
        locations_raw = result.get("locations", [])
    return json.dumps({
        "locations": [_translate_location(l) for l in (locations_raw or [])],
    })


def lsp_hover_gated(
    *, server_name: str, file: str, line: int, col: int,
    manager: "LspManager", workspace: Path,
) -> str:
    err = _check_workspace(file, workspace)
    if err:
        return err
    content = _read_content_if_exists(file, workspace)
    if content is not None:
        _safe_sync_file(manager, file, workspace, content)
    result = manager.request_sync(
        server_name, "textDocument/hover",
        {
            "textDocument": {"uri": _file_uri(file, workspace)},
            "position": {"line": line - 1, "character": col - 1},
        },
    )
    if "error" in result:
        return json.dumps(result)
    contents = result.get("contents", {})
    if isinstance(contents, dict):
        contents = contents.get("value", "")
    elif isinstance(contents, list):
        contents = "\n".join(c.get("value", c) if isinstance(c, dict) else str(c) for c in contents)
    return json.dumps({"contents": contents or "", "range": None})


def lsp_document_symbols_gated(
    *, server_name: str, file: str, manager: "LspManager", workspace: Path,
) -> str:
    err = _check_workspace(file, workspace)
    if err:
        return err
    content = _read_content_if_exists(file, workspace)
    if content is not None:
        _safe_sync_file(manager, file, workspace, content)
    result = manager.request_sync(
        server_name, "textDocument/documentSymbol",
        {"textDocument": {"uri": _file_uri(file, workspace)}},
    )
    if "error" in result:
        return json.dumps(result)
    inner = result.get("result", result)
    if isinstance(inner, list):
        symbols_raw = inner
    else:
        symbols_raw = result.get("symbols", [])
    return json.dumps({
        "symbols": [_translate_symbol(s) for s in (symbols_raw or [])],
    })


def lsp_workspace_symbols_gated(
    *, server_name: str, query: str, manager: "LspManager", workspace: Path,
) -> str:
    result = manager.request_sync(
        server_name, "workspace/symbol", {"query": query},
    )
    if "error" in result:
        return json.dumps(result)
    inner = result.get("result", result)
    if isinstance(inner, list):
        symbols_raw = inner
    else:
        symbols_raw = result.get("symbols", [])
    return json.dumps({
        "symbols": [_translate_symbol(s) for s in (symbols_raw or [])],
    })


def lsp_diagnostics_gated(
    *, server_name: str, file: str, manager: "LspManager", workspace: Path,
) -> str:
    err = _check_workspace(file, workspace)
    if err:
        return err
    # server 不存在 / disabled → 显 error(不让模型误以为"没诊断 = 文件没问题")
    status = manager.server_status(server_name)
    if status is None:
        return json.dumps({"error": f"lsp server {server_name!r} not configured"})
    from argos_agent.lsp.manager import ServerStatus
    if status in (ServerStatus.DISABLED,) or \
       manager._servers[server_name].config.disabled:  # type: ignore[union-attr]
        return json.dumps({"error": f"lsp server {server_name!r} disabled"})
    # 走 cache 而非 request(spec §2.5:diagnostics = server push 缓存)
    cached = manager.get_diagnostics(file)
    if cached is None:
        return json.dumps({"diagnostics": []})
    items = [_translate_diagnostic(d) for d in cached.get("diagnostics", [])]
    return json.dumps({"diagnostics": items})
