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

from argos.i18n import t

_DEFAULT_WS = Path(os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace"))
_DEFAULT_VERIFY = Path(os.environ.get("ARGOS_VERIFY_DIR", Path.home() / ".argos" / "verify"))

# 沙箱外文件快照剪枝目录(纯剪枝名集合,被 snapshot.py 复用);
# 与 guard_project_tests 内的 _SKIP_DIRS 是兄弟集合(VCS/虚拟环境/缓存/构建产物)。
# 必须剪构建产物/依赖/索引:大项目若不剪,每次 run 起点拍快照会 tar 数 GB、阻塞十几秒
# (2026-06-14 真机:workspace 5.2G,take 卡 11.4s tar 3.6GB,构建产物/依赖占大头),
# 且每轮一个 GB 级快照会爆盘。这些都是生成物(可重建),undo 无需还原 → 剪掉安全且必要。
SNAPSHOT_PRUNE_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv", "env",
    "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".argo-snapshots",
    # 构建产物 / 索引 / 工具缓存(生成物,可重建;漏剪 = 快照数 GB + 起步卡十几秒):
    "dist", "build", "target", ".next", ".nuxt", ".tox", ".codegraph", ".gradle",
})


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
    # plan mode 状态 —— per-run(取代模块级 _plan_mode_active,并发 run 互不干扰)。
    # EnterPlanMode / ExitPlanMode 同时写 loop.mode(TUI 可读)和此字段(沙箱工具 dispatcher 读)。
    plan_mode: bool = False


# contextvar 默认值设为 None;get_current() 在未 set_context 时惰性返回新副本,
# 杜绝并发 run 通过共享可变 default 互相污染 guarded/guarded_dirs 状态。
# 旧的 _DEFAULT_CTX 共享单例已废弃(原 docstring 自己警告过 mutation 风险)。
_current_var: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "argos_run_context", default=None,
)


def _make_default_ctx() -> RunContext:
    """每次调用返回新的兜底上下文副本 —— 独立 guarded dict,绝不共享可变状态。"""
    return RunContext(workspace=_DEFAULT_WS.resolve(), verify_dir=_DEFAULT_VERIFY.resolve())


def current() -> RunContext:
    ctx = _current_var.get()
    if ctx is None:
        # 写回 contextvar,确保同一协程后续调用(guard_files → detect_tampering)
        # 拿到同一个对象而不是每次新副本(minior 修:防篡改指纹丢失路径)。
        ctx = _make_default_ctx()
        _current_var.set(ctx)
    return ctx


def set_context(ctx: RunContext) -> "contextvars.Token[RunContext | None]":
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
            changed.append(rel + t("core2.runtime.deleted"))
        elif _sha256(f) != digest:
            changed.append(rel + t("core2.runtime.modified"))
    for drel, snap in ctx.guarded_dirs.items():
        d = ctx.workspace / drel
        now = (
            {str(f.relative_to(ctx.workspace)) for f in d.rglob("*") if f.is_file()}
            if d.is_dir() else set()
        )
        for frel, digest in snap.items():
            f = ctx.workspace / frel
            if not f.exists():
                changed.append(frel + t("core2.runtime.deleted"))
            elif _sha256(f) != digest:
                changed.append(frel + t("core2.runtime.modified"))
        for frel in sorted(now - set(snap)):
            changed.append(frel + t("core2.runtime.added"))
    return changed


# 测试文件发现模式(常见语言)+ 跳过的重目录(不下钻,防大 repo 卡顿)。
_TEST_GLOBS = (
    "test_*.py", "*_test.py", "*_spec.py", "conftest.py",
    "*.test.ts", "*.test.tsx", "*.test.js", "*.spec.ts", "*.spec.js",
    "*_test.go", "*_spec.rb", "test_*.rb",
)
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
    ".next", "target", ".argos", ".idea", ".vscode",
})


def guard_project_tests(*, cap: int = 2000) -> int:
    """头号护城河洞修复:project_mode 下 verify 与 agent 共享目录(verify_dir==workspace),
    agent 技术上能改"评判自己的测试"。run 起始(agent 动手前)快照工作区里【既有】的单个
    测试文件指纹 —— 之后 `detect_tampering` 见它们被改/删即判篡改,verify 据此判 unverifiable
    (诚实:不替偷改测试的结果担保通过)。

    只登记【既有单个文件】(非目录)是关键:agent 之后【写新测试】不算篡改(TDD 合法,
    诚实协议自己鼓励先写测试);只有【改/删既有测试】才被抓。沙箱模式靠 VERIFY_DIR 隔离,
    无需此守 → 直接返 0。返回登记的文件数。"""
    ctx = current()
    if not ctx.project_mode:
        return 0
    from fnmatch import fnmatch
    rels: list[str] = []
    for root, dirs, files in os.walk(ctx.workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]   # 原地剪枝,不下钻重目录
        for fn in files:
            if any(fnmatch(fn, g) for g in _TEST_GLOBS):
                rels.append(os.path.relpath(os.path.join(root, fn), ctx.workspace))
                if len(rels) >= cap:
                    break
        if len(rels) >= cap:
            break
    if rels:
        guard_files(rels)
    return len(rels)
