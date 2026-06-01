"""每次 run 的运行时配置 —— workspace 与 verify 隔离区,可按 run 覆盖。

懂技术用户的真实场景:让 agent 在【我自己的项目目录】干活、跑【我自己的测试】验证,
而不是锁死在 ~/.argos 沙盒。所以 workspace 要能按 run 指向用户项目。

设计:用一个进程内的上下文对象持当前 run 的路径,工具与 verify 在调用时读它。
默认仍是 ~/.argos 沙盒(安全兜底);显式传 project_dir 时切到用户项目。

诚实的安全边界(关键,直面之前修过的"测谎仪被贿赂"漏洞):
  · 沙盒模式(默认):验证物在独立 VERIFY_DIR,agent 够不到 —— 强隔离,适合不可信任务。
  · 项目模式(用户自己的项目):用户的测试就在项目里,agent 技术上能改 —— 此时隔离
    做不到,改用【篡改可见】:记录验证相关文件的指纹,agent 若改动它们,run 结束时
    在事件里【显著标红警告】。用户拥有自己的 repo,他需要的是"看得见 agent 动没动测试",
    而不是"绝对改不了"。绝不静默放过 —— 那才是不诚实。
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_WS = Path(os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace"))
_DEFAULT_VERIFY = Path(os.environ.get("ARGOS_VERIFY_DIR", Path.home() / ".argos" / "verify"))


def _sha256(path: Path) -> str:
    """文件内容的 sha256 十六进制摘要 —— 防篡改指纹(替代可被 touch 绕过的 mtime/size)。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class RunContext:
    """当前 run 的路径与模式。"""
    workspace: Path
    verify_dir: Path
    # project 模式 = 在用户自己的项目里干活(测试在项目内,用篡改可见而非隔离)。
    project_mode: bool = False
    # 受保护文件指纹(project 模式下,验证相关文件的内容 sha256,用于检测篡改)。
    guarded: dict[str, str] = field(default_factory=dict)


# 进程内当前上下文(单 run 串行执行,够用;并发场景未来再隔离)。
_current = RunContext(workspace=_DEFAULT_WS.resolve(), verify_dir=_DEFAULT_VERIFY.resolve())


def current() -> RunContext:
    return _current


def use_sandbox() -> RunContext:
    """切回默认沙盒(强隔离,验证物 agent 够不到)。"""
    global _current
    _current = RunContext(workspace=_DEFAULT_WS.resolve(), verify_dir=_DEFAULT_VERIFY.resolve())
    return _current


def use_project(project_dir: str) -> RunContext:
    """切到用户项目目录。验证就在项目里跑(verify_dir=项目根)。"""
    p = Path(project_dir).expanduser().resolve()
    global _current
    _current = RunContext(workspace=p, verify_dir=p, project_mode=True)
    return _current


def guard_files(paths: list[str]) -> None:
    """登记需保护的文件(通常是测试文件),记录内容 sha256。project 模式下 agent 技术上能改它们,
    所以靠'篡改可见 + 硬门禁':run 内验证时对比指纹,改动了就判 unverifiable。"""
    ctx = _current
    for rel in paths:
        f = ctx.workspace / rel
        if f.exists() and f.is_file():
            ctx.guarded[rel] = _sha256(f)


def detect_tampering() -> list[str]:
    """返回被改动过的受保护文件列表(内容 sha256 变了)。空 = 没动测试,诚实。"""
    ctx = _current
    changed: list[str] = []
    for rel, digest in ctx.guarded.items():
        f = ctx.workspace / rel
        if not f.exists():
            changed.append(rel + "(被删除)")
            continue
        if _sha256(f) != digest:
            changed.append(rel + "(被修改)")
    return changed
