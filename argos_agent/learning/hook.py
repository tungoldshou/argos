"""learning hook:在 daemon worker 收尾处异步触发,passed 走 distill+promote,失败走 reflection。

设计要点:
- async 函数,接 store 路径 / run_id / 状态;返 None(caller 不依赖)。
- 整体 try/except 兜底:任何异常被 log 掉,不返给 caller(主任务绝不被学习路径拖挂)。
- 路径读取:不依赖 daemon RunStore(测试用临时 JSONL);store_dir 直接读 JSONL。
- 候选→晋升调用 promotion_gate(同 model_tier 跑 A/B;test 场景 caller 传 fake runner)。

调用契约(供 daemon worker 收尾处):
  await learning.hook.on_run_completed(
      run_id=...,
      store_dir=<daemon runs dir>,
      goal=...,
      verify_cmd=...,
      verdict_status="passed" | "failed" | "unverifiable",
      skills_root=~/.argos/skills,
      runner_factory=lambda: ...,
      tasks=[...],
  )
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)


# ── 内部:宽松事件读取(同 distiller 风格,不走 store.replay 的 run_meta 守卫) ──
def _read_events(store_dir: Path, run_id: str) -> list[dict]:
    p = Path(store_dir) / f"{run_id}.jsonl"
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# ── 内部:为 distill 造一个最小 store 协议对象(避免依赖 RunStore) ──
@dataclass
class _MiniStore:
    runs_dir: Path

    def replay(self, run_id: str) -> Iterable[dict]:
        return iter(_read_events(self.runs_dir, run_id))


async def on_run_completed(
    *,
    run_id: str,
    store_dir: Path,
    goal: str,
    verify_cmd: str | None,
    verdict_status: str,
    skills_root: Path,
    runner_factory: Callable[[], Any] | None = None,
    tasks: list | None = None,
) -> None:
    """daemon worker 收尾处调用。异步,无返回值,失败诚实降级。

    决策:
    - verdict_status="passed" → distill + promotion_gate
    - 其他 → reflection(失败教训存 memory)
    """
    if verdict_status == "passed":
        await _on_passed(
            run_id=run_id, store_dir=store_dir,
            goal=goal, verify_cmd=verify_cmd,
            skills_root=skills_root,
            runner_factory=runner_factory, tasks=tasks or [],
        )
    else:
        await _on_failed(
            run_id=run_id, store_dir=store_dir,
            goal=goal, verify_cmd=verify_cmd,
            verdict_status=verdict_status,
            skills_root=skills_root,
        )


async def _on_passed(
    *,
    run_id: str, store_dir: Path, goal: str, verify_cmd: str | None,
    skills_root: Path, runner_factory: Callable[[], Any] | None,
    tasks: list,
) -> None:
    """passed 路径:distill → promotion_gate。"""
    try:
        from argos_agent.learning import distiller, promotion_gate

        # distill 临时用 mini store(避免依赖 RunStore 严格契约)
        mini_store = _MiniStore(runs_dir=Path(store_dir))
        cand = distiller.distill_run_to_skill(
            run_id=run_id, store=mini_store,
            goal=goal, verify_cmd=verify_cmd,
            skills_root=skills_root,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("learning: distill failed for %s: %s", run_id, e)
        return

    if cand is None:
        # 没产出(没 code_action / store 读不到)→ 不晋升,但也不当失败
        return

    if not tasks or runner_factory is None:
        # 无语料 / 无 runner → 候选已产,但不晋升(诚实:无 A/B 证据不写盘)
        return

    try:
        runner = runner_factory()
        promotion_gate.promote(
            candidate=cand, tasks=tasks, runner=runner,
            skills_root=skills_root,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("learning: promote failed for %s: %s", run_id, e)
        return


async def _on_failed(
    *,
    run_id: str, store_dir: Path, goal: str, verify_cmd: str | None,
    verdict_status: str, skills_root: Path,
) -> None:
    """失败 / 不可验证路径:写 reflection,**不**调 distill,不写 skills/。"""
    try:
        from argos_agent.learning.reflection import reflect_failure
        reflect_failure(
            run_id=run_id, store_dir=Path(store_dir),
            goal=goal, verify_cmd=verify_cmd,
            verdict_status=verdict_status,
            skills_root=skills_root,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("learning: reflect_failure failed for %s: %s", run_id, e)
