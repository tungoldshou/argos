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

    def __init__(self, *, run_id: str, manager: RunManager, loop_factory):
        self.run_id = run_id
        self._manager = manager
        self._loop_factory = loop_factory
        self._loop = None
        self._event_seq = 0
        self._step_count = 0
        self._message_count = 0
        self._current_phase = "act"
        self._task: asyncio.Task | None = None

    @property
    def event_seq(self) -> int:
        return self._event_seq

    @property
    def current_step(self) -> int:
        return self._step_count

    async def run(self) -> None:
        """worker 入口:running → 完成/失败/取消 之一。"""
        # 从 index 拿 meta 信息
        entry = self._manager.get_run(self.run_id)
        if entry is None:
            log.warning("worker.run: run %s not found", self.run_id)
            return
        # 1. mark_running
        self._manager.mark_running(self.run_id)
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
                        await self._manager.fanout(self.run_id, {
                            "kind": "state_change",
                            "from": "paused",
                            "to": "running",
                            "reason": "user_resume",
                            "ts": time.time(),
                        })
                # 计 step / message
                if isinstance(ev, dict):
                    if ev.get("kind") == "code_action":
                        self._step_count += 1
                    elif ev.get("kind") == "token_delta":
                        self._message_count += 1
                    elif ev.get("kind") == "phase_change":
                        self._current_phase = ev.get("phase", "act")
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
