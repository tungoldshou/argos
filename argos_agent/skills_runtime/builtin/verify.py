"""`/verify` skill — 用户显式触发 Verifier.verify 入口(spec §2.3 / D9 / D13)。

**关键澄清(D9 / D13)**:
- `/verify` 是用户从 TUI 输入 slash 命令走的路径。
- 它**直接**调 `Verifier.verify(verify_cmd, attempts=1)`,**不**走 `propose_verify`。
- `propose_verify` 是 agent 从 code block 声明 verify_cmd 走的路径(两条独立路径不混)。
- verify_cmd 来源:`LoopConfig.verify_cmd` 或 `~/.argos/config.json` 全局默认。
  本期 v1 简化:走 `~/.argos/config.json` 全局(下一 v1.1 接 LoopConfig)。"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from argos_agent.core.verify_gate import Verifier
from argos_agent.skills_runtime.analysis import (
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)


# 故意**不**import propose_verify —— 本模块**不**走该路径(D9/D13)。
# 测试通过 patch `propose_verify` 验证该属性。
propose_verify = None  # type: ignore[assignment]


# 简化 v1:全局配置路径(下一 v1.1 接 LoopConfig)
_CONFIG_PATH = Path.home() / ".argos" / "config.json"


def _read_verify_cmd() -> str | None:
    """从 ~/.argos/config.json 读 verify_cmd;不存在 / 解析失败 → None。"""
    try:
        text = _CONFIG_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    cmd = data.get("verify_cmd")
    return cmd if isinstance(cmd, str) and cmd else None


async def run(args: dict, ctx: AnalysisSkillContext) -> AnalysisSkillResult:
    """`/verify` 入口 — 调 Verifier.verify,转 5 态 AnalysisSkillResult。"""
    start_ms = int(time.monotonic() * 1000)
    verify_cmd = _read_verify_cmd()
    verifier = Verifier()
    v = await asyncio.to_thread(verifier.verify, verify_cmd, attempts=1)

    # 优先用 verdict.verify_cmd(verifier 实际跑过的),fallback 到本地的 cmd
    actual_cmd = v.verify_cmd or verify_cmd

    if v.status == "passed":
        verdict = "passed"
        findings: tuple[Finding, ...] = ()
        summary = f"/verify · <1ms · passed\nverify_cmd: {actual_cmd}"
    elif v.status == "failed":
        verdict = "failed"
        findings = (Finding(
            severity="error",
            category="verify",
            file=None, line=None, snippet=None,
            message=v.detail[:200] if v.detail else "verify failed",
            suggestion="fix failing tests / check verify_cmd",
        ),)
        summary = (
            f"/verify · <1ms · failed\n"
            f"verify_cmd: {actual_cmd} · {v.detail or ''}\n"
            f"[1 finding] F-error · verify"
        )
    else:  # unverifiable
        # unverifiable(无论 verify_cmd 是否设置)→ partial(spec §2.3 / 6 态)
        verdict = "partial"
        findings = ()
        summary = f"/verify · partial\nverify_cmd: {actual_cmd} · {v.detail or ''}"
        if not actual_cmd:
            # 提示加在 summary,不进 findings(spec §2.3 unverifiable 例子)
            summary += f"\n(hint: configure verify_cmd in {_CONFIG_PATH})"

    duration_ms = int(time.monotonic() * 1000) - start_ms
    return AnalysisSkillResult(
        summary=summary,
        findings=findings,
        duration_ms=duration_ms,
        errors=(),
        verdict=verdict,  # type: ignore[arg-type]
    )
