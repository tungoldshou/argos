"""Argos 工具注册表(契约 §4)。

本文件同时承担两个职责:
1. 暴露旧 tools.py 的全部符号(ALL_TOOLS 等)供 core/__init__.py / server.py 等使用。
   (原 argos_agent/tools.py 被本包 tools/__init__.py 遮盖后,改在这里维护。)
2. 暴露 build_child_namespace(broker) 供 sandbox/_sandbox_child.py 在沙箱子进程内调用。
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from argos_agent import web as _web
from argos_agent.approval import requires_approval

# ── workspace 牢笼 ──────────────────────────────────────────────────────────
WORKSPACE = Path(os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace")).resolve()

# ── verify 隔离区(关键安全边界)────────────────────────────────────────────
VERIFY_DIR = Path(os.environ.get("ARGOS_VERIFY_DIR", Path.home() / ".argos" / "verify")).resolve()


def _ws() -> Path:
    from argos_agent import runtime
    ctx = runtime.current()
    return ctx.workspace if ctx.project_mode else WORKSPACE


def _vd() -> Path:
    from argos_agent import runtime
    ctx = runtime.current()
    return ctx.verify_dir if ctx.project_mode else VERIFY_DIR


def _safe_path(rel: str) -> Path | None:
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    p = (ws / rel).resolve()
    try:
        p.relative_to(ws)
    except ValueError:
        return None
    return p


@tool
def read_file(path: str) -> str:
    """读取 workspace 内某个文件的内容。path 是相对 workspace 的路径。"""
    p = _safe_path(path)
    if p is None:
        return f"错误:路径 {path!r} 越出 workspace,拒绝访问。"
    if not p.exists():
        return f"错误:文件 {path!r} 不存在。"
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"错误:读取失败 {e}"
    if len(text) > 8000:
        return text[:8000] + f"\n…(文件共 {len(text)} 字符,已截断前 8000)"
    return text


@tool
@requires_approval(description="写入文件 {path}", risk="low")
def write_file(path: str, content: str) -> str:
    """把内容写入 workspace 内某个文件(覆盖)。path 是相对 workspace 的路径。"""
    p = _safe_path(path)
    if p is None:
        return f"错误:路径 {path!r} 越出 workspace,拒绝写入。"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"错误:写入失败 {e}"
    return f"已写入 {path}({len(content)} 字符)。"


def _normalize_ws(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", s).strip()


@tool
@requires_approval(description="编辑文件 {path}", risk="low")
def edit_file(path: str, old: str, new: str) -> str:
    """在 workspace 内某文件里把 old 串替换成 new。先精确唯一匹配;精确找不到时
    做空白归一化的模糊匹配兜底(仍要求唯一)。"""
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
    target = _normalize_ws(old)
    lines = text.splitlines(keepends=True)
    matches = []
    for i in range(len(lines)):
        acc = ""
        for j in range(i, len(lines)):
            acc += lines[j]
            norm = _normalize_ws(acc)
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
    new_segment = new if new.endswith("\n") or j + 1 >= len(lines) else new + "\n"
    new_lines = lines[:i] + [new_segment] + lines[j + 1:]
    p.write_text("".join(new_lines), encoding="utf-8")
    return f"已编辑 {path}(模糊匹配)。"


# shell 白名单:只允许验证类/只读类。
ALLOWED_CMDS = {
    "node", "npm", "pnpm", "npx", "tsc", "eslint", "prettier",
    "python", "python3", "pytest", "ruff", "mypy",
    "cargo", "rustc", "go", "git", "ls", "cat", "grep", "rg", "echo", "pwd",
}

GIT_READONLY_SUBCMDS = {
    "status", "diff", "log", "show", "branch", "ls-files", "rev-parse",
    "describe", "blame", "shortlog", "tag", "rev-list", "cat-file", "show-ref",
}


def _validate_git(parts: list[str]) -> str | None:
    for tok in parts[1:]:
        if tok.startswith("-"):
            return f"错误:git 全局选项 {tok!r} 不被允许(防 `git -c …` 参数注入执行任意命令)。"
        if tok not in GIT_READONLY_SUBCMDS:
            return (
                f"错误:git 子命令 {tok!r} 不被允许。只放行只读子命令:"
                f"{', '.join(sorted(GIT_READONLY_SUBCMDS))}"
                "(push/pull/fetch/clone/remote/config/submodule 等联网或有副作用的被禁)。"
            )
        return None
    return "错误:git 需要一个子命令。"


@tool
@requires_approval(description="执行命令 {command}", risk="medium")
def run_command(command: str) -> str:
    """在 workspace 内运行一条白名单内的命令(验证/构建/测试类),返回退出码+输出。"""
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"错误:命令解析失败 {e}"
    if not parts:
        return "错误:空命令。"
    bin_name = Path(parts[0]).name
    if bin_name not in ALLOWED_CMDS:
        return f"错误:命令 {bin_name!r} 不在白名单。允许:{', '.join(sorted(ALLOWED_CMDS))}"
    if bin_name == "git":
        git_err = _validate_git(parts)
        if git_err:
            return git_err
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            parts, cwd=ws, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "错误:命令超时(60s)。"
    except Exception as e:
        return f"错误:执行失败 {e}"
    out = (r.stdout or "")[-3000:]
    err = (r.stderr or "")[-2000:]
    return f"[exit_code={r.returncode}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}".strip()


_EXTRACT_COMPRESS_THRESHOLD = 6000


@tool
def web_search(query: str, limit: int = 5) -> str:
    """联网搜索,返回若干结果(标题+链接+摘要)。用于查实时信息(天气/新闻/资料)。"""
    res = _web.search(query, limit)
    if not res.get("success"):
        return f"搜索失败:{res.get('error', '未知错误')}"
    results = res.get("results") or []
    if not results:
        return "没有搜到结果。"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n   {r.get('snippet', '')}")
    return "\n".join(lines)


@tool
def web_extract(url: str) -> str:
    """取一个网页的正文内容(已去导航/广告噪声)。"""
    res = _web.extract(url)
    if not res.get("success"):
        return f"取页失败:{res.get('error', '未知错误')}"
    text = res.get("text") or ""
    if len(text) <= _EXTRACT_COMPRESS_THRESHOLD:
        return text or "(页面无可提取正文)"
    try:
        from argos_agent.core import _llm, final_text
        llm = _llm()
        prompt = (
            "下面是一个网页的正文(若已截断会在末尾注明)。请抽取关键事实,并写一个"
            " 200 字以内的中文摘要,丢弃导航/广告/无关噪声。只输出摘要正文,不要前言。\n\n"
            f"正文(已截断,原始 {len(text)} 字符):\n" + text[:20000]
        )
        msg = llm.invoke(prompt)
        summary = final_text(msg) if hasattr(msg, "content") else str(msg)
        if summary.strip():
            return summary.strip()
    except Exception:
        pass
    return text[:8000] + f"\n…(正文共 {len(text)} 字符,已截断;压缩不可用)"


@tool
def search_files(pattern: str, target: str = "content", file_glob: str = "", limit: int = 50) -> str:
    """在 workspace 内搜索:target='content' 用正则搜文件正文(带行号);
    target='files' 按 glob(如 '*.py')找文件名。"""
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    if target == "files":
        cmd = ["rg", "--files", "-g", pattern]
    else:
        cmd = ["rg", "--line-number", "--no-heading"]
        if file_glob:
            cmd += ["-g", file_glob]
        cmd += [pattern]
    try:
        r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "错误:搜索超时(30s)。"
    except Exception as e:  # noqa: BLE001
        return f"错误:搜索失败 {e}"
    out = (r.stdout or "").strip()
    if not out:
        return "没有匹配。"
    lines = out.splitlines()
    if len(lines) > limit:
        return "\n".join(lines[:limit]) + f"\n…(共 {len(lines)} 行,已截断前 {limit})"
    return out


# 暴露给 agent 的工具清单。
ALL_TOOLS = [read_file, write_file, edit_file, run_command, web_search, web_extract, search_files]

# 电脑操控(第 7 步)—— Playwright Python SDK 包成 LangChain tool,接 ALL_TOOLS。
try:
    from argos_agent import playwright_tools
    ALL_TOOLS = list(ALL_TOOLS) + playwright_tools.all_tools()
except Exception as _e:  # noqa: BLE001
    import logging
    logging.getLogger(__name__).warning("playwright_tools unavailable, browser controls disabled: %r", _e)


# ── 沙箱子进程命名空间构造(契约 §4)────────────────────────────────────────
def build_child_namespace(broker: Any) -> dict[str, Any]:
    """【沙箱子进程侧】命名空间:纯沙箱工具原函数 + broker-gated 工具经 _broker 包装。
    Task 7 扩成真版(files 纯沙箱 + shell/web broker-gated)。最小桩先返回空集合让子进程能 init。"""
    return {}
