"""`/security-review` skill 编排(3 pass 顺序跑,任一 pass 失败不阻断,spec §2.4)。"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable

from argos_agent.skills_runtime.analysis import (
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos_agent.skills_runtime.builtin.security_review.audit import audit_dependencies
from argos_agent.skills_runtime.builtin.security_review.permission import (
    scan_file_for_permission_issues,
)
from argos_agent.skills_runtime.builtin.security_review.secrets import (
    scan_file_for_secrets,
)


def _run_pass_secrets(target: Path, ctx: AnalysisSkillContext) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    workspace = ctx.workspace
    for f in _walk_files(target):
        try:
            relpath = str(f.relative_to(workspace))
        except ValueError:
            relpath = f.name
        findings.extend(scan_file_for_secrets(f, relpath=relpath, workspace=workspace))
    return tuple(findings)


def _run_pass_audit(target: Path, ctx: AnalysisSkillContext) -> tuple[Finding, ...]:
    return audit_dependencies(target, rel_workspace=ctx.workspace)


def _run_pass_permission(target: Path, ctx: AnalysisSkillContext) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    workspace = ctx.workspace
    for f in _walk_files(target):
        try:
            relpath = str(f.relative_to(workspace))
        except ValueError:
            relpath = f.name
        findings.extend(scan_file_for_permission_issues(f, relpath=relpath, workspace=workspace))
    return tuple(findings)


# 可被测试 monkeypatch 替换
_PASSES: list[tuple[str, Callable[[Path, AnalysisSkillContext], tuple[Finding, ...]]]] = [
    ("secrets", _run_pass_secrets),
    ("audit", _run_pass_audit),
    ("permission", _run_pass_permission),
]

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _walk_files(root: Path) -> list[Path]:
    """列 root 下所有文件(限深 8 层防 FS 暴)。"""
    if root.is_file():
        return [root]
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".argos"}
    files: list[Path] = []
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        if depth > 8:
            continue
        try:
            for entry in d.iterdir():
                if entry.is_dir():
                    if entry.name not in skip_dirs:
                        stack.append((entry, depth + 1))
                elif entry.is_file():
                    files.append(entry)
        except OSError:
            continue
    return files


def _dedup(findings: list[Finding]) -> list[Finding]:
    """同 (file, line, category, message) 四元组去重(spec D12)。"""
    seen: set[tuple] = set()
    out: list[Finding] = []
    for f in findings:
        key = (f.file, f.line, f.category, f.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _sort_findings(findings: list[Finding]) -> list[Finding]:
    """error > warning > info;同 severity 按 file:line 排序(spec §2.4 排序)。"""
    return sorted(findings, key=lambda f: (
        _SEVERITY_ORDER.get(f.severity, 9),
        f.file or "",
        f.line or 0,
    ))


def _summarize(verdict: str, findings: list[Finding], errors: list[str], duration_ms: int) -> str:
    n = len(findings)
    parts = [
        f"/security-review · {duration_ms/1000:.1f}s · {verdict} · 3 passes",
        f"[{n} finding{'s' if n != 1 else ''}]",
    ]
    for f in findings[:5]:
        loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or "(workspace)")
        parts.append(f"  F-{f.severity} · {f.category} · {loc} · {f.message}")
    if n > 5:
        parts.append(f"  ... and {n-5} more")
    if errors:
        parts.append(f"  errors: {len(errors)}")
    return "\n".join(parts)


async def run(args: dict, ctx: AnalysisSkillContext) -> AnalysisSkillResult:
    """`/security-review` 入口 — 3 pass 顺序跑(spec §2.4 / D5 / D12)。"""
    start_ms = int(time.monotonic() * 1000)
    path_arg = args.get("path")
    workspace = ctx.workspace
    if path_arg:
        target = workspace / path_arg
        if not target.exists():
            target = workspace
    else:
        target = workspace
    all_findings: list[Finding] = []
    errors: list[str] = []
    for pass_name, pass_fn in _PASSES:
        try:
            pass_findings = await asyncio.to_thread(pass_fn, target, ctx)
            all_findings.extend(pass_findings)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{pass_name}: {type(e).__name__}: {e}")
    # dedup + sort
    findings = _sort_findings(_dedup(all_findings))
    # verdict(spec D5 防假绿):任何 error finding → failed;errors 非空 + 0 finding → partial
    has_error = any(f.severity == "error" for f in findings)
    if has_error:
        verdict = "failed"
    elif errors and not findings:
        verdict = "partial"
    elif errors:
        verdict = "failed"
    elif not findings:
        verdict = "passed"
    else:
        verdict = "failed"
    duration_ms = int(time.monotonic() * 1000) - start_ms
    summary = _summarize(verdict, findings, errors, duration_ms)
    return AnalysisSkillResult(
        summary=summary,
        findings=tuple(findings),
        duration_ms=duration_ms,
        errors=tuple(errors),
        verdict=verdict,  # type: ignore[arg-type]
    )
