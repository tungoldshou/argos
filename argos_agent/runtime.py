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

import contextvars
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
    # 受保护目录快照(dir 相对路径 -> {file 相对路径 -> sha256}),用于抓"新增/删除文件"。
    guarded_dirs: dict[str, dict[str, str]] = field(default_factory=dict)


# 默认沙盒上下文(安全兜底)。生产路径每个 run 都会 set_context,这个 default 只在
# 测试/headless 单跑工具时兜底(此时同一时刻只有一个上下文,共享 default 无并发风险)。
# ⚠️ 不变量:default 是【共享可变单例】(RunContext.guarded/guarded_dirs 是 dict)。
#   绝不可在【未 set_context】的情况下调 guard_files()——那会 mutate 这个共享 default,
#   同进程下一次未 set_context 的 detect_tampering() 会读到过期指纹而误报篡改。
#   guard_files/detect_tampering 只在 set_context 之后(server run 路径)调用,此约束才成立。
_DEFAULT_CTX = RunContext(workspace=_DEFAULT_WS.resolve(), verify_dir=_DEFAULT_VERIFY.resolve())
_current_var: contextvars.ContextVar[RunContext] = contextvars.ContextVar(
    "argos_run_context", default=_DEFAULT_CTX,
)


def current() -> RunContext:
    return _current_var.get()


def set_context(ctx: RunContext) -> contextvars.Token:
    """设本上下文(必须在 create_task(pump) 之前调,ContextVar 在建任务那刻被复制进子任务)。"""
    return _current_var.set(ctx)


def reset(token: contextvars.Token) -> None:
    _current_var.reset(token)


def use_sandbox() -> contextvars.Token:
    """切回默认沙盒(强隔离,验证物 agent 够不到)。返回 token,run 结束须 reset。"""
    return set_context(RunContext(workspace=_DEFAULT_WS.resolve(), verify_dir=_DEFAULT_VERIFY.resolve()))


def use_project(project_dir: str) -> contextvars.Token:
    """切到用户项目目录(workspace=verify_dir=该目录)。返回 token,run 结束须 reset。"""
    p = Path(project_dir).expanduser().resolve()
    return set_context(RunContext(workspace=p, verify_dir=p, project_mode=True))


def guard_files(paths: list[str]) -> None:
    """登记需保护的文件/目录,记录内容 sha256。文件 → 单个指纹;目录 → 递归快照(含文件集合,
    以便检测新增)。project 模式下靠'篡改可见 + 硬门禁':改/增/删都判 unverifiable。"""
    ctx = current()
    for rel in paths:
        p = ctx.workspace / rel
        if p.is_dir():
            ctx.guarded_dirs[rel] = {
                str(f.relative_to(ctx.workspace)): _sha256(f)
                for f in sorted(p.rglob("*")) if f.is_file()
            }
        elif p.is_file():
            ctx.guarded[rel] = _sha256(p)


def detect_tampering() -> list[str]:
    """返回被改动过的受保护文件列表(内容变了/被删/新增)。空 = 没动测试,诚实。"""
    ctx = current()
    changed: list[str] = []
    for rel, digest in ctx.guarded.items():
        f = ctx.workspace / rel
        if not f.exists():
            changed.append(rel + "(被删除)")
        elif _sha256(f) != digest:
            changed.append(rel + "(被修改)")
    for drel, snap in ctx.guarded_dirs.items():
        d = ctx.workspace / drel
        now = (
            {str(f.relative_to(ctx.workspace)) for f in d.rglob("*") if f.is_file()}
            if d.is_dir() else set()
        )
        for frel, digest in snap.items():
            f = ctx.workspace / frel
            if not f.exists():
                changed.append(frel + "(被删除)")
            elif _sha256(f) != digest:
                changed.append(frel + "(被修改)")
        for frel in sorted(now - set(snap)):
            changed.append(frel + "(新增)")
    return changed
