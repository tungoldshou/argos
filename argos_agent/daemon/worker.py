"""RunWorker:单 run 协程,包 AgentLoop + checkpoint + pause/resume + SSE 投(spec §2.11)。

FakeLoop:测试用(可控 step 数 / delay / 异常);真 AgentLoop 由 loop_factory 注入。

run() 协程结构:
  1. mark_running
  2. 调 loop_factory() → loop
  3. async for ev in loop.run(goal, session_id):
       if cancel_requested: break
       if pause_requested at step boundary:
         checkpoint + mark_paused + await pause_event.wait + mark_resumed
       append to store + fanout
  5. 异常 → mark_failed(写 run_failure)
  6. CancelledError → mark_cancelled(from-state 动态读)
  7. 自然完成 → mark_completed
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback as tb_mod
from typing import AsyncIterator

from argos_agent.daemon.manager import RunManager

log = logging.getLogger(__name__)


class FakeLoop:
    """可控 fake loop:yield N 步 token_delta/code_action/code_result → 收尾。"""

    def __init__(self, *, steps: int = 5, delay_s: float = 0.0):
        self._steps = steps
        self._delay = delay_s

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        for i in range(self._steps):
            if self._delay:
                await asyncio.sleep(self._delay)
            yield {"kind": "token_delta", "text": f"step {i}", "step": i}
            yield {"kind": "code_action", "code": f"# step {i}", "step": i}
            yield {"kind": "code_result", "stdout": "", "value_repr": "", "exc": "", "ok": True, "step": i}
        yield {"kind": "verify_verdict",
               "verdict": {"status": "passed", "reason": "fake"}}


class RunWorker:
    """单 run 协程宿主。"""

    def __init__(self, *, run_id: str, manager: RunManager, loop_factory,
                 registry=None, worktree=None):
        self.run_id = run_id
        self._manager = manager
        self._loop_factory = loop_factory
        self._loop = None
        self._event_seq = 0
        self._step_count = 0
        self._message_count = 0
        self._current_phase = "act"
        self._task: asyncio.Task | None = None
        # #5b 扩展(向后兼容,None 时 noop)
        self._registry = registry
        self._worktree = worktree

    @property
    def event_seq(self) -> int:
        return self._event_seq

    @property
    def current_step(self) -> int:
        return self._step_count

    async def run(self) -> None:
        """worker 入口:running → 完成/失败/取消 之一。

        终态收尾(#5b §9.3):
          · release semaphore slot
          · worktree cleanup
          · registry.cleanup(标终态 + 缩 max_history)
        """
        # 从 index 拿 meta 信息
        entry = self._manager.get_run(self.run_id)
        if entry is None:
            log.warning("worker.run: run %s not found", self.run_id)
            return
        # 1. mark_running
        self._manager.mark_running(self.run_id)
        if self._registry is not None:
            self._registry.mark(run_id=self.run_id, state="running")
        try:
            # 2. build loop
            self._loop = self._loop_factory()
            # 3. 拿 pause event
            pause_event = self._manager.pause_event(self.run_id)
            # 4. drive
            async for ev in self._loop.run(entry.goal, session_id=f"run-{self.run_id}"):
                # 取消检测
                if self._manager.is_cancel_requested(self.run_id):
                    break
                # pause 检测:在 step 边界前阻塞
                if isinstance(ev, dict) and ev.get("kind") in ("code_action", "phase_change"):
                    if not pause_event.is_set():
                        # 写 checkpoint + state_change + 阻塞
                        self._manager.mark_paused(
                            self.run_id, last_step=self._step_count,
                            msg_count=self._message_count, last_event_seq=self._event_seq,
                        )
                        if self._registry is not None:
                            self._registry.mark(run_id=self.run_id, state="paused")
                        await self._manager.fanout(self.run_id, {
                            "kind": "state_change",
                            "from": "running",
                            "to": "paused",
                            "reason": "user_esc",
                            "ts": time.time(),
                        })
                        await pause_event.wait()
                        # resume
                        self._manager.mark_resumed(self.run_id)
                        if self._registry is not None:
                            self._registry.mark(run_id=self.run_id, state="running")
                        await self._manager.fanout(self.run_id, {
                            "kind": "state_change",
                            "from": "paused",
                            "to": "running",
                            "reason": "user_resume",
                            "ts": time.time(),
                        })
                # 计 step / message + cost
                if isinstance(ev, dict):
                    kind = ev.get("kind")
                    if kind == "code_action":
                        self._step_count += 1
                    elif kind == "token_delta":
                        self._message_count += 1
                    elif kind == "phase_change":
                        self._current_phase = ev.get("phase", "act")
                    elif kind == "cost_update" and self._registry is not None:
                        # 累加 cost 到 registry(cost_usd=None 不累加)
                        try:
                            self._registry.add_cost(
                                run_id=self.run_id,
                                tokens_in_delta=int(ev.get("tokens_in", 0)),
                                tokens_out_delta=int(ev.get("tokens_out", 0)),
                                cost_usd_delta=ev.get("cost_usd"),
                            )
                        except Exception as e:  # noqa: BLE001
                            log.warning("worker: cost add failed for %s: %s", self.run_id, e)
                # 序列化 + 持久化 + 投 SSE
                ev = dict(ev)
                self._event_seq += 1
                ev["_seq"] = self._event_seq
                self._manager.store.append(self.run_id, ev)
                self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
                await self._manager.fanout(self.run_id, ev)
            # 5. 完成(若非终态)
            cur = self._manager.index.get(self.run_id)
            if cur is not None and cur.state not in ("completed", "failed", "cancelled"):
                if self._manager.is_cancel_requested(self.run_id):
                    self._manager.mark_cancelled(self.run_id)
                else:
                    self._manager.mark_completed(self.run_id)
            # learning hook(任务):收尾处异步触发,passed → distill+promote,失败 → reflection。
            # 后台非阻塞 + try/except 兜底:不阻断主任务,失败诚实降级(spec 2026-06-07 任务)。
            await self._maybe_run_learning_hook(entry)
        except asyncio.CancelledError:
            # from-state 动态读:可能是 paused / running / pending
            cur = self._manager.index.get(self.run_id)
            if cur is not None and cur.state not in ("completed", "failed", "cancelled"):
                self._manager.mark_cancelled(self.run_id)
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("worker.run exception: %s", e)
            cur = self._manager.index.get(self.run_id)
            if cur is not None and cur.state not in ("completed", "failed", "cancelled"):
                self._manager.mark_failed(
                    self.run_id, error=str(e), error_type=type(e).__name__,
                    traceback=tb_mod.format_exc(), step=self._step_count,
                )
        finally:
            # #5b 终态收尾:release slot + worktree cleanup + registry cleanup
            await self._post_terminal_cleanup()

    async def _post_terminal_cleanup(self) -> None:
        """终态后清理:registry.slot 释放 + worktree + registry 缩 cap。

        失败静默:run 已写状态机,cleanup 是 best-effort。
        """
        try:
            cur = self._manager.index.get(self.run_id)
            if cur is None:
                return
            terminal = cur.state in ("completed", "failed", "cancelled", "suspended")
            if not terminal:
                return
            if self._worktree is not None:
                try:
                    self._worktree.cleanup(self.run_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("worker: worktree cleanup failed: %s", e)
            if self._registry is not None:
                try:
                    await self._registry.cleanup(
                        run_id=self.run_id, terminal_state=cur.state,
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("worker: registry cleanup failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.warning("worker: post_terminal_cleanup failed for %s: %s", self.run_id, e)

    async def _maybe_run_learning_hook(self, entry) -> None:
        """收尾后异步跑 learning hook(任务:从 verified 轨迹提炼技能)。

        - 读 store 最后一条 verify_verdict 拿 verdict_status(决定 passed vs failed 分支)
        - passed → on_run_completed(verdict_status="passed", ...) → distill + promote
        - failed/cancelled/无 verdict → 走 reflection 路径
        - 任何异常 → log warning,不抛(主任务已收尾,绝不让 learning 拖挂)
        """
        try:
            from argos_agent.learning.hook import on_run_completed
            import os
            from pathlib import Path

            verdict_status = "failed"
            verify_cmd: str | None = None
            # E4 防火墙:必须把 verdict.self_verified 也透传到 hook,否则 hook 看不到
            # 防火墙信号,会把 self_verified=True 的 passed 误判为用户级通过,触发
            # distill/promote(reward-hacking 死亡螺旋)。默认 False 安全(行为不变)。
            self_verified: bool = False
            try:
                events = list(self._manager.store.replay(self.run_id))
                for ev in events:
                    if isinstance(ev, dict) and ev.get("kind") == "verify_verdict":
                        v = ev.get("verdict") or {}
                        if isinstance(v, dict):
                            verdict_status = v.get("status", verdict_status) or verdict_status
                            verify_cmd = v.get("verify_cmd") or verify_cmd
                            self_verified = bool(v.get("self_verified", False))
            except Exception:  # noqa: BLE001
                pass

            store_dir = self._manager.store.runs_dir()
            skills_root = Path(os.path.expanduser("~/.argos/skills"))

            await on_run_completed(
                run_id=self.run_id,
                store_dir=store_dir,
                goal=getattr(entry, "goal", "") or "",
                verify_cmd=verify_cmd,
                verdict_status=verdict_status,
                self_verified=self_verified,
                skills_root=skills_root,
                runner_factory=None,   # worker 不持有 EvalRunner;hook 跳过 promote 仅产候选
                tasks=[],              # 同上
            )
        except Exception as e:  # noqa: BLE001 — learning 路径必须不挂主任务
            log.warning("worker: learning hook failed for %s: %s", self.run_id, e)
