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
      self_verified=bool,           # E4 防火墙:True 时绝不进 distill/promote
      skills_root=~/.argos/skills,
      candidates_root=Path | None,  # 候选落盘区(None=不落盘,兼容旧 caller)
      workspace=str | None,         # 源 run 的项目目录(A/B 取证用)
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
    self_verified: bool = False,
    skills_root: Path,
    candidates_root: Path | None = None,
    workspace: str | None = None,
    runner_factory: Callable[[], Any] | None = None,
    tasks: list | None = None,
) -> None:
    """daemon worker 收尾处调用。异步,无返回值,失败诚实降级。

    决策(E4 防火墙):
    - status=="passed" 且 **非** self_verified → distill + promotion_gate(用户级)
    - status=="passed" 且 self_verified=True     → 走 reflection 降级
      (reward-hacking 防火墙:绝不让"自验证通过"触发技能蒸馏/晋升)
    - 其他状态 → reflection(失败教训存 memory)

    candidates_root:候选落盘区路径。None = 不落盘(向后兼容);传入时无 runner 的
      passed run 产物会落盘到此目录,供 Dream 夜间整合使用。
    workspace:源 run 的项目工作目录,随候选落盘用于 A/B 取证。
    """
    is_user_pass = (verdict_status == "passed") and not self_verified
    if is_user_pass:
        await _on_passed(
            run_id=run_id, store_dir=store_dir,
            goal=goal, verify_cmd=verify_cmd,
            skills_root=skills_root,
            candidates_root=candidates_root,
            workspace=workspace,
            runner_factory=runner_factory, tasks=tasks or [],
        )
    else:
        # 含 status==passed 但 self_verified=True(防火墙)与所有非 passed
        await _on_failed(
            run_id=run_id, store_dir=store_dir,
            goal=goal, verify_cmd=verify_cmd,
            verdict_status=verdict_status,
            self_verified=self_verified,
            skills_root=skills_root,
        )


async def _on_passed(
    *,
    run_id: str, store_dir: Path, goal: str, verify_cmd: str | None,
    skills_root: Path,
    candidates_root: Path | None,
    workspace: str | None,
    runner_factory: Callable[[], Any] | None,
    tasks: list,
) -> None:
    """passed 路径:distill → promotion_gate。"""
    try:
        from argos.learning import distiller, promotion_gate

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
        # 无语料 / 无 runner → 不晋升,但候选落盘进候选区(Dream 夜间整合的材料;
        # 修复:此前直接丢弃,生产路径学习闭环断电)
        if candidates_root is not None:
            try:
                from argos.learning import candidates as _cands
                _cands.save_candidate(
                    cand, root=candidates_root, source_run=run_id,
                    workspace=workspace, goal=goal,
                )
            except Exception as e:  # noqa: BLE001 — 学习路径不挂主任务
                log.warning("learning: 候选落盘失败 %s: %s", run_id, e)
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
    verdict_status: str,
    self_verified: bool = False,
    skills_root: Path,
) -> None:
    """失败 / 不可验证 / **self_verified 降级** 路径:写 reflection,
    **不**调 distill,不写 skills/。
    """
    try:
        from argos.learning.reflection import reflect_failure
        reflect_failure(
            run_id=run_id, store_dir=Path(store_dir),
            goal=goal, verify_cmd=verify_cmd,
            verdict_status=verdict_status,
            self_verified=self_verified,
            skills_root=skills_root,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("learning: reflect_failure failed for %s: %s", run_id, e)
