"""纯沙箱 file 工具(契约 §4):read_file/write_file/edit_file/search_files。

裸 Python 函数(注入沙箱命名空间,变量跨 code-action 存活)。安全沿用旧 tools.py:
  · 路径牢笼在 workspace 内,越界返错误串(不抛异常,模型自纠 —— ReAct)。
  · 写在沙箱内额外受 Seatbelt OS 牢笼(纵深);越界写双重挡(路径解析 + OS)。
工作目录:project 模式用 runtime 覆盖,否则用模块级默认(测试 monkeypatch WORKSPACE)。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

WORKSPACE = Path(os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace")).resolve()


def _ws() -> Path:
    """当前生效 workspace:project 模式用 runtime,否则用模块默认(沿用旧 tools._ws)。"""
    try:
        from argos_agent import runtime
        ctx = runtime.current()
        return ctx.workspace if ctx.project_mode else WORKSPACE
    except Exception:  # noqa: BLE001 —— runtime 未就位(早期阶段)退回模块默认
        return WORKSPACE


def _safe_path(rel: str) -> Path | None:
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    p = (ws / rel).resolve()
    try:
        p.relative_to(ws)
    except ValueError:
        return None
    return p


def read_file(path: str) -> str:
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


def write_file(path: str, content: str) -> str:
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


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


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
    matches: list[tuple[int, int]] = []
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
