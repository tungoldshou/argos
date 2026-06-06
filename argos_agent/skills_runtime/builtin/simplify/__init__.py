"""`/simplify` skill 编排(3 pass 顺序跑,spec §2.5)。"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from argos_agent.skills_runtime.analysis import (
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos_agent.skills_runtime.builtin.simplify.complexity import (
    detect_complex_functions,
)
from argos_agent.skills_runtime.builtin.simplify.dead_code import detect_dead_code
from argos_agent.skills_runtime.builtin.simplify.duplication import (
    detect_duplicates,
)

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_DEFAULT_TOP = 10


def _sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (
        _SEVERITY_ORDER.get(f.severity, 9),
        f.file or "",
        f.line or 0,
    ))


def _summarize(verdict: str, findings: list[Finding], top: int, duration_ms: int) -> str:
    n = len(findings)
    parts = [
        f"/simplify · {duration_ms/1000:.1f}s · {verdict} · 3 passes",
        f"[top {min(n, top)} of {n} findings]" if n else "[0 findings]",
    ]
    for i, f in enumerate(findings[:top], 1):
        loc = f"{f.file}:{f.line}" if f.file and f.line else (f.file or "(workspace)")
        parts.append(f"  {i}. {f.category} · {f.severity} · {loc} · {f.message}")
    return "\n".join(parts)


async def run(args: dict, ctx: AnalysisSkillContext) -> AnalysisSkillResult:
    """`/simplify` 入口 — 3 pass 顺序跑(同 §2.4 失败不阻断)。"""
    start_ms = int(time.monotonic() * 1000)
    path_arg = args.get("path")
    top = int(args.get("top", _DEFAULT_TOP))  # type: ignore[arg-type]
    workspace = ctx.workspace
    if path_arg:
        target = workspace / path_arg
    else:
        target = workspace
    all_findings: list[Finding] = []
    errors: list[str] = []
    for pass_name, pass_fn in [
        ("duplicate", detect_duplicates),
        ("complexity", detect_complex_functions),
        ("dead_code", detect_dead_code),
    ]:
        try:
            pass_findings = await asyncio.to_thread(pass_fn, target)
            all_findings.extend(pass_findings)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{pass_name}: {type(e).__name__}: {e}")
    sorted_findings = _sort_findings(all_findings)
    top_findings = sorted_findings[:top]
    if errors and not top_findings:
        verdict = "partial"
    elif top_findings:
        verdict = "failed"
    else:
        verdict = "passed"
    duration_ms = int(time.monotonic() * 1000) - start_ms
    summary = _summarize(verdict, top_findings, top, duration_ms)
    return AnalysisSkillResult(
        summary=summary,
        findings=tuple(top_findings),
        duration_ms=duration_ms,
        errors=tuple(errors),
        verdict=verdict,  # type: ignore[arg-type]
    )
