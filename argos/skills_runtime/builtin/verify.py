"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from argos.core.verify_gate import Verifier
from argos.i18n import t
from argos.skills_runtime.analysis import (
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)


propose_verify = None  # type: ignore[assignment]


def _config_path() -> Path:
    from argos import config as C
    return Path(C.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / "config.json"


def _read_verify_cmd() -> str | None:
    """Internal documentation."""
    try:
        text = _config_path().read_text(encoding="utf-8")
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
    """Internal documentation."""
    start_ms = int(time.monotonic() * 1000)
    verify_cmd = _read_verify_cmd()
    verifier = Verifier()
    v = await asyncio.to_thread(verifier.verify, verify_cmd, attempts=1)

    actual_cmd = v.verify_cmd or verify_cmd

    if v.status == "passed":
        verdict = "passed"
        findings: tuple[Finding, ...] = ()
        if getattr(v, "self_verified", False):
            summary = t("verify.skill.self_verified_summary", cmd=actual_cmd)
        else:
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
        verdict = "partial"
        findings = ()
        summary = f"/verify · partial\nverify_cmd: {actual_cmd} · {v.detail or ''}"
        if not actual_cmd:
            summary += f"\n(hint: configure verify_cmd in {_config_path()})"

    duration_ms = int(time.monotonic() * 1000) - start_ms
    return AnalysisSkillResult(
        summary=summary,
        findings=findings,
        duration_ms=duration_ms,
        errors=(),
        verdict=verdict,  # type: ignore[arg-type]
    )
