"""Argos 工具注册表(契约 §4).

工具 = 注入沙箱执行器命名空间的 Python 函数(变量跨 code-action 步骤存活)。
  · 纯沙箱(read_file/write_file/edit_file/search_files):沙箱内直接跑,零审批。
  · broker-gated(run_command/web_search/web_extract[/playwright]):函数体调 _broker.request
    跨进程 RPC 到 host,经审批拨盘 + egress 裁决后执行,结果灌回沙箱。
命名沿用旧 tools.py 函数名,不改名。

旧 LangChain ALL_TOOLS / tool 对象(带 .invoke())仍在本模块暴露供遗留路径
(core/__init__.py / server.py / test_tools.py)使用,Phase 5 接线后可删。
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
    "run_command", "web_search", "web_extract",
]   # + playwright(可选,Phase 5/6 接)

__all__ = [
    "build_namespace", "build_child_namespace",
    "ALL_TOOL_NAMES", "ALLOWED_CMDS", "GIT_READONLY_SUBCMDS",
    "WORKSPACE", "VERIFY_DIR",
    # 遗留路径符号
    "_ws", "_vd", "_safe_path",
    # 旧 LangChain 工具对象(遗留路径使用中,Phase 5 后可删)
    "ALL_TOOLS", "read_file", "write_file", "edit_file", "search_files",
    "run_command", "web_search", "web_extract",
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

    return {
        "run_command": run_command_gated,
        "web_search": web_search_gated,
        "web_extract": web_extract_gated,
    }


def _pure() -> dict[str, Any]:
    return {
        "read_file": files.read_file,
        "write_file": files.write_file,
        "edit_file": files.edit_file,
        "search_files": files.search_files,
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


# ── 旧 LangChain 工具对象(遗留路径:server.py / core/__init__.py / test_tools.py) ──────
# 这些是带 .invoke() 的 LangChain StructuredTool 对象,与新 build_namespace 并列暴露。
# test_tools.py 通过 tools.write_file.invoke(...) 调用,并通过 monkeypatch.setattr(tools, "WORKSPACE")
# 来隔离 workspace。_ws()/_safe_path() 已响应 WORKSPACE 模块属性,故 monkeypatch 生效。

try:
    import os as _os
    import shlex as _shlex
    import subprocess as _subprocess
    from pathlib import Path as _Path

    from langchain_core.tools import tool as _lc_tool

    from argos_agent import web as _web_mod
    from argos_agent.approval import requires_approval as _req_approval

    @_lc_tool
    def read_file(path: str) -> str:  # type: ignore[misc]
        """读取 workspace 内某个文件的内容。path 是相对 workspace 的路径。"""
        p = _safe_path(path)
        if p is None:
            return f"错误:路径 {path!r} 越出 workspace,拒绝访问。"
        if not p.exists():
            return f"错误:文件 {path!r} 不存在。"
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return f"错误:读取失败 {e}"
        if len(text) > 8000:
            return text[:8000] + f"\n…(文件共 {len(text)} 字符,已截断前 8000)"
        return text

    @_lc_tool
    @_req_approval(description="写入文件 {path}", risk="low")
    def write_file(path: str, content: str) -> str:  # type: ignore[misc]
        """把内容写入 workspace 内某个文件(覆盖)。path 是相对 workspace 的路径。"""
        p = _safe_path(path)
        if p is None:
            return f"错误:路径 {path!r} 越出 workspace,拒绝写入。"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return f"错误:写入失败 {e}"
        return f"已写入 {path}({len(content)} 字符)。"

    @_lc_tool
    @_req_approval(description="编辑文件 {path}", risk="low")
    def edit_file(path: str, old: str, new: str) -> str:  # type: ignore[misc]
        """在 workspace 内某文件里把 old 串替换成 new。精确匹配;精确找不到时模糊匹配兜底。"""
        import re as _re
        p = _safe_path(path)
        if p is None:
            return f"错误:路径 {path!r} 越出 workspace,拒绝编辑。"
        if not p.exists():
            return f"错误:文件 {path!r} 不存在。"
        text = p.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 1:
            p.write_text(text.replace(old, new), encoding="utf-8")
            return f"已编辑 {path}。"
        if count > 1:
            return f"错误:old 串多次匹配({count} 次,需唯一),请给更多上下文。"
        # 模糊匹配
        def _norm(s: str) -> str:
            return _re.sub(r"\s+", " ", s).strip()
        target = _norm(old)
        lines_arr = text.splitlines(keepends=True)
        matches: list[tuple[int, int]] = []
        for i in range(len(lines_arr)):
            acc = ""
            for j in range(i, len(lines_arr)):
                acc += lines_arr[j]
                norm = _norm(acc)
                if norm == target:
                    matches.append((i, j))
                    break
                if len(norm) > len(target):
                    break
        if len(matches) == 0:
            return "错误:未找到要替换的内容。"
        if len(matches) > 1:
            return f"错误:old 串模糊匹配了 {len(matches)} 次(需唯一),请给更多上下文。"
        i, j = matches[0]
        new_segment = new if new.endswith("\n") or j + 1 >= len(lines_arr) else new + "\n"
        new_lines = lines_arr[:i] + [new_segment] + lines_arr[j + 1:]
        p.write_text("".join(new_lines), encoding="utf-8")
        return f"已编辑 {path}(模糊匹配)。"

    @_lc_tool
    def search_files(pattern: str, target: str = "content",
                     file_glob: str = "", limit: int = 50) -> str:  # type: ignore[misc]
        """在 workspace 内搜索:target='content' 用正则搜文件正文;target='files' 按 glob。"""
        import sys as _sys
        mod = _sys.modules[__name__]
        ws = getattr(mod, "WORKSPACE", WORKSPACE)
        ws.mkdir(parents=True, exist_ok=True)
        if target == "files":
            cmd = ["rg", "--files", "-g", pattern]
        else:
            cmd = ["rg", "--line-number", "--no-heading"]
            if file_glob:
                cmd += ["-g", file_glob]
            cmd += [pattern]
        try:
            r = _subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=30)
        except _subprocess.TimeoutExpired:
            return "错误:搜索超时(30s)。"
        except Exception as e:  # noqa: BLE001
            return f"错误:搜索失败 {e}"
        out = (r.stdout or "").strip()
        if not out:
            return "没有匹配。"
        lines_list = out.splitlines()
        if len(lines_list) > limit:
            return "\n".join(lines_list[:limit]) + f"\n…(共 {len(lines_list)} 行,已截断前 {limit})"
        return out

    @_lc_tool
    @_req_approval(description="执行命令 {command}", risk="medium")
    def run_command(command: str) -> str:  # type: ignore[misc]
        """在 workspace 内运行一条白名单内的命令(验证/构建/测试类),返回退出码+输出。"""
        from .shell import ALLOWED_CMDS as _AC, GIT_READONLY_SUBCMDS as _GRC, _validate_git
        try:
            parts = _shlex.split(command)
        except ValueError as e:
            return f"错误:命令解析失败 {e}"
        if not parts:
            return "错误:空命令。"
        bin_name = _Path(parts[0]).name
        if bin_name not in _AC:
            return f"错误:命令 {bin_name!r} 不在白名单。允许:{', '.join(sorted(_AC))}"
        if bin_name == "git":
            git_err = _validate_git(parts)
            if git_err:
                return git_err
        ws = _ws()
        ws.mkdir(parents=True, exist_ok=True)
        try:
            r = _subprocess.run(parts, cwd=ws, capture_output=True, text=True, timeout=60)
        except _subprocess.TimeoutExpired:
            return "错误:命令超时(60s)。"
        except Exception as e:  # noqa: BLE001
            return f"错误:执行失败 {e}"
        out = (r.stdout or "")[-3000:]
        err = (r.stderr or "")[-2000:]
        return f"[exit_code={r.returncode}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}".strip()

    @_lc_tool
    def web_search(query: str, limit: int = 5) -> str:  # type: ignore[misc]
        """联网搜索,返回若干结果(标题+链接+摘要)。"""
        from .web import web_search as _ws_fn
        return _ws_fn(query, limit)

    @_lc_tool
    def web_extract(url: str) -> str:  # type: ignore[misc]
        """取一个网页的正文内容(已去导航/广告噪声)。"""
        from .web import web_extract as _we_fn
        return _we_fn(url)

    ALL_TOOLS = [read_file, write_file, edit_file, run_command, web_search, web_extract, search_files]
    try:
        from argos_agent import playwright_tools as _pt
        ALL_TOOLS = list(ALL_TOOLS) + _pt.all_tools()
    except Exception:  # noqa: BLE001
        pass

except ImportError:
    # LangChain 未安装(纯单元测试环境)——遗留工具对象不可用。
    # build_namespace / build_child_namespace 等新 Phase 3 API 仍完全可用。
    ALL_TOOLS = []  # type: ignore[assignment]
