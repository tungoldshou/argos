"""reflection:失败/不可验证 run 写一条 task_reflection 进 memory(供下次重试参考)。

绝不调 distill,绝不写 skills/。失败诚实降级:memory 写失败 → 吞掉,不抛。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def reflect_failure(
    *,
    run_id: str,
    store_dir: Path,
    goal: str,
    verify_cmd: str | None,
    verdict_status: str,
    skills_root: Path | None = None,  # 显式声明,接住但**不写**(防误用)
) -> None:
    """把失败 run 的关键信息写进 memory(复用 memory.auto.capture_event)。

    失败模式:
    - store 读不到(run 还没落盘 / 已被清)→ 仍写一条"无可读 store"reflection
    - memory 写失败 → 吞掉,绝不让主任务挂
    - 显式不调 distill,绝不写 skills_root 任何内容
    """
    snippet: str = ""
    try:
        from argos_agent.daemon.store import RunStore
        rs = RunStore(runs_dir=store_dir)
        # 抽最后一条非 meta event 的 detail
        last_code_result = None
        for ev in rs.replay(run_id):
            if ev.get("kind") == "code_result" and not ev.get("ok", True):
                last_code_result = ev
                break
        if last_code_result:
            snippet = (last_code_result.get("exc") or "")[:200]
    except Exception:  # noqa: BLE001 — 读不到就空 snippet
        snippet = "(store unreadable)"

    try:
        from argos_agent.memory.auto import capture_event as _capture
        _capture(
            "task_reflection",
            run_id=run_id,
            goal=(goal or "")[:120],
            verify_cmd=(verify_cmd or "")[:120] if verify_cmd else None,
            verdict=verdict_status,
            last_exc_snippet=snippet or None,
        )
    except Exception:  # noqa: BLE001 — memory 写失败不阻断(诚实降级)
        pass
