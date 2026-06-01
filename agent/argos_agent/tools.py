"""Argos agent 的工具系统 —— 给智能体真正的手脚:读/写/编辑文件、跑命令。

安全是第一原则(产品的"诚实/安全"哲学,也呼应 Anthropic 的工具设计准则:
工具要自包含、错误作为数据返回让模型自纠、绝不信任 LLM 生成的路径/命令):
  · 所有文件路径被牢笼在一个 workspace 根目录内,越界直接拒绝(防 LLM 写到任意位置)。
  · shell 命令走白名单(只允许验证类/只读类命令),禁止 rm/curl/sudo 等。
  · 错误不抛异常,而是作为字符串返回给模型 —— 让它看到失败并自我修正(ReAct 的核心)。
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from langchain_core.tools import tool

# ── workspace 牢笼 ──────────────────────────────────────────────────────────
# 默认 ~/.argos/workspace;可由环境变量覆盖(Tauri 注入)。agent 的文件工具只能动这里。
# 注:实际生效的 workspace 由 runtime.current() 决定(支持按 run 切到用户项目目录);
# 这两个模块级常量是【默认/兜底值】,也是测试 monkeypatch 的锚点。
WORKSPACE = Path(os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace")).resolve()

# ── verify 隔离区(关键安全边界)────────────────────────────────────────────
# 验证物(测试文件等)放这里,【在 workspace 之外】,agent 的 write/edit 工具够不到 ——
# 否则 agent 能改评判它的测试来作弊(实测:它真把"不可能通过"的检查文件改成 pass 了)。
# 测谎仪绝不能让嫌疑人能改。verify 命令在这个目录里跑(见 verify_gate),它能 import
# workspace 里 agent 写的解,但 agent 改不到这里的测试。
VERIFY_DIR = Path(os.environ.get("ARGOS_VERIFY_DIR", Path.home() / ".argos" / "verify")).resolve()


def _ws() -> Path:
    """当前生效的 workspace:project 模式用 runtime 覆盖,否则用模块级默认(测试可 monkeypatch)。"""
    from . import runtime
    ctx = runtime.current()
    return ctx.workspace if ctx.project_mode else WORKSPACE


def _vd() -> Path:
    """当前生效的 verify 目录:同 _ws 逻辑。"""
    from . import runtime
    ctx = runtime.current()
    return ctx.verify_dir if ctx.project_mode else VERIFY_DIR


def _safe_path(rel: str) -> Path | None:
    """把相对路径解析到 workspace 内;越界(.. 逃逸/绝对路径外)返回 None。"""
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
    # 输出预算:大文件截断,提示用 offset(防爆 context)。
    if len(text) > 8000:
        return text[:8000] + f"\n…(文件共 {len(text)} 字符,已截断前 8000)"
    return text


@tool
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


@tool
def edit_file(path: str, old: str, new: str) -> str:
    """在 workspace 内某文件里把 old 串替换成 new(必须唯一匹配一次)。"""
    p = _safe_path(path)
    if p is None:
        return f"错误:路径 {path!r} 越出 workspace,拒绝编辑。"
    if not p.exists():
        return f"错误:文件 {path!r} 不存在。"
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return f"错误:未找到要替换的内容。"
    if count > 1:
        return f"错误:old 串匹配了 {count} 次(需唯一),请给更多上下文。"
    p.write_text(text.replace(old, new), encoding="utf-8")
    return f"已编辑 {path}。"


# shell 白名单:只允许验证类/只读类。绝不允许 rm/curl/wget/sudo/mv 等有副作用或外联的。
ALLOWED_CMDS = {
    "node", "npm", "pnpm", "npx", "tsc", "eslint", "prettier",
    "python", "python3", "pytest", "ruff", "mypy",
    "cargo", "rustc", "go", "git", "ls", "cat", "grep", "rg", "echo", "pwd",
}


@tool
def run_command(command: str) -> str:
    """在 workspace 内运行一条白名单内的命令(验证/构建/测试类),返回退出码+输出。
    这是 Argos 的确定性 verify 落点:退出码是地面真值,模型无法对它撒谎。
    禁止 rm/curl/sudo 等有副作用或外联的命令。"""
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"错误:命令解析失败 {e}"
    if not parts:
        return "错误:空命令。"
    bin_name = Path(parts[0]).name
    if bin_name not in ALLOWED_CMDS:
        return f"错误:命令 {bin_name!r} 不在白名单。允许:{', '.join(sorted(ALLOWED_CMDS))}"
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
    # 退出码摆在最前 —— 这是 verify 的 ground truth。
    return f"[exit_code={r.returncode}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}".strip()


# 暴露给 agent 的工具清单。
ALL_TOOLS = [read_file, write_file, edit_file, run_command]
