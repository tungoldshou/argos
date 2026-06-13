"""run_skill 编排(spec §2.1 / §2.6 / §3)。

职责:
- 校验 skill name 在 registry(unknown → verdict=skipped)
- 校验 args(parameters_schema strict:reject unknown keys;path / timeout / top 三类)
- 校验 path 在 ctx.workspace 内 + 存在
- 按 requires_approval + approval_level 决定是否走 ApprovalGate(本期 v1 简化:仅读不接,见 D13)
- asyncio.wait_for timeout,默认 60s
- skill 抛异常 → verdict=partial + errors 留 traceback
- timeout → verdict=skipped + errors 含 'interrupted by timeout' + 已收集 findings 保留
- 跑前/后各投 1 条 SkillRunStart / SkillRunEnd(event_bus 注入,默认 None → 不投)
- findings > 100 → trunc 到 100 + 1 条 info(spec §3)

**关键约束**:
- `requires_approval=True` 的 skill(本期仅 /verify)走 auto 路径(同 `Verifier.verify` 不弹审批,见 D13)
- approval_level = "confirm" + requires_approval=True → 弹 modal(spec D13 v1.1 实接,本期简化返 passed 通过)
- path 校验走 host Seatbelt 文件访问(对位 LSP 模式)"""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from pathlib import Path
from typing import Any, Mapping

from argos.skills_runtime.analysis import (
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos.skills_runtime import registry
from argos.skills_runtime.events import SkillRunEnd, SkillRunStart

# 默认 60s timeout(spec D11)
DEFAULT_TIMEOUT_S: float = 60.0

# findings trunc 上限(spec §3)
MAX_FINDINGS: int = 100

# 已知 args keys(spec schema.py 三类 schema 共有 + 各自有)
_KNOWN_ARG_KEYS: frozenset[str] = frozenset({"path", "timeout", "top"})


class _NullEventBus:
    """测试 / 无 bus 时用:emit 是 no-op。"""
    async def emit(self, ev: object) -> None:
        return None


def _validate_args(skill_name: str, args: Mapping[str, object]) -> str | None:
    """strict 模式:仅允许已知 keys。返 None = ok;非 None = 错误 msg。"""
    extras = set(args.keys()) - _KNOWN_ARG_KEYS
    if extras:
        return f"invalid args for skill {skill_name!r}: unknown keys {sorted(extras)}"
    if "timeout" in args:
        t = args["timeout"]
        if not isinstance(t, int) or t < 1 or t > 600:
            return f"invalid args: timeout {t!r} 必须在 1-600"
    if "top" in args:
        n = args["top"]
        if not isinstance(n, int) or n < 1 or n > 100:
            return f"invalid args: top {n!r} 必须在 1-100"
    return None


def _validate_path(
    args: Mapping[str, object], ctx: AnalysisSkillContext,
) -> tuple[str | None, str | None]:
    """path 校验:返 (error_msg, resolved_relpath_or_None)。"""
    raw = args.get("path")
    if raw is None:
        return None, None   # 无 path = 用默认(workspace 根)
    if not isinstance(raw, str) or not raw:
        return "path must be a non-empty string", None
    p = Path(raw)
    if p.is_absolute():
        return f"path outside workspace: {raw} (must be relative)", None
    # 拼到 workspace 解析
    resolved = (ctx.workspace / p).resolve()
    try:
        resolved.relative_to(ctx.workspace.resolve())
    except ValueError:
        return f"path outside workspace: {raw}", None
    if not resolved.exists():
        return f"path not found: {raw}", None
    return None, str(p)


def _trunc_findings(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """>100 条 → trunc 到 100 + 1 info 提示(spec §3)。"""
    if len(findings) <= MAX_FINDINGS:
        return findings
    truncated_count = len(findings) - MAX_FINDINGS
    return findings[:MAX_FINDINGS] + (
        Finding(
            severity="info",
            category="config",
            message=f"{truncated_count} more findings truncated; re-run with --limit N (v1.1)",
        ),
    )


async def run_skill(
    name: str,
    args: Mapping[str, object],
    ctx: AnalysisSkillContext,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    event_bus: Any = None,
) -> AnalysisSkillResult:
    """统一 skill 入口(spec §2.1)。

    Returns:
        AnalysisSkillResult(verdict / findings / errors / summary / duration_ms)。
    """
    start_ms = int(time.monotonic() * 1000)
    bus = event_bus or _NullEventBus()

    # 1. skill name 校验
    skill = registry.get(name)
    if skill is None:
        return AnalysisSkillResult(
            summary=f"unknown skill: {name}",
            findings=(),
            duration_ms=0,
            errors=(f"unknown skill: {name}",),
            verdict="skipped",
        )

    # 2. args 校验
    err = _validate_args(name, args)
    if err is not None:
        return AnalysisSkillResult(
            summary=err, findings=(), duration_ms=0, errors=(err,), verdict="skipped",
        )

    # 3. path 校验
    path_err, relpath = _validate_path(args, ctx)
    if path_err is not None:
        return AnalysisSkillResult(
            summary=path_err, findings=(), duration_ms=0, errors=(path_err,), verdict="skipped",
        )

    # 4. 投 SkillRunStart
    await bus.emit(SkillRunStart(
        skill_name=name, args=dict(args), cwd=str(ctx.workspace),
        timestamp_ms=start_ms,
    ))

    # 5. 实际跑 skill(spec D13:requires_approval=True 走 auto 路径,本期不实接 modal)
    try:
        effective_args = dict(args)
        if relpath is not None:
            effective_args["path"] = relpath
        # asyncio.wait_for timeout
        result = await asyncio.wait_for(
            skill.run(effective_args, ctx), timeout=timeout_s,
        )
        # findings trunc
        result = AnalysisSkillResult(
            summary=result.summary,
            findings=_trunc_findings(result.findings),
            duration_ms=result.duration_ms,
            errors=result.errors,
            verdict=result.verdict,
            raw=result.raw,
        )
    except asyncio.TimeoutError:
        duration_ms = int(time.monotonic() * 1000) - start_ms
        result = AnalysisSkillResult(
            summary=f"interrupted by timeout ({timeout_s}s)",
            findings=(),
            duration_ms=duration_ms,
            errors=(f"interrupted by timeout ({timeout_s}s)",),
            verdict="skipped",
        )
    except Exception as e:  # noqa: BLE001
        duration_ms = int(time.monotonic() * 1000) - start_ms
        tb = traceback.format_exc()
        result = AnalysisSkillResult(
            summary=f"skill {name!r} raised: {type(e).__name__}: {e}",
            findings=(),
            duration_ms=duration_ms,
            errors=(tb,),
            verdict="partial",
        )

    # 6. 投 SkillRunEnd
    end_ms = int(time.monotonic() * 1000)
    await bus.emit(SkillRunEnd(
        skill_name=name,
        verdict=result.verdict,
        duration_ms=end_ms - start_ms,
        finding_count=len(result.findings),
        error_count=len(result.errors),
        cwd=str(ctx.workspace),
        timestamp_ms=end_ms,
    ))

    return result
