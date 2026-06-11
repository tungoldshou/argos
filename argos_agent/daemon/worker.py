"""RunWorker:单 run 协程,包 AgentLoop + checkpoint + pause/resume + SSE 投(spec §2.11)。

FakeLoop:测试用(可控 step 数 / delay / 异常);真 AgentLoop 由 loop_factory 注入。

run() 协程结构:
  1. mark_running
  2. 调 loop_factory() → loop
  3. async for ev in loop.run(goal, session_id):
       if cancel_requested: break
       if pause_requested at step boundary:
         checkpoint + mark_paused + await pause_event.wait + mark_resumed
       _to_event_dict(ev) → 序列化 + 持久化 + 投 SSE
  5. 异常 → mark_failed(写 run_failure)
  6. CancelledError → mark_cancelled(from-state 动态读)
  7. 自然完成 → mark_completed

typed Event 桥(_to_event_dict):
  · 真 AgentLoop yield protocol.events dataclass → serialize_event() → json → dict
  · FakeLoop / legacy dict → 原样直通(兼容两种形态)
  · 保证落 JSONL store 和 SSE 扇出均为 dict

审批 fail-closed(P3 前过渡):
  daemon 上下文的 ApprovalGate 使用 DaemonApprovalGate 包装器,
  timeout 默认 60 s 后 fail-closed 拒绝,投诚实 error 事件说明原因。
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
import traceback as tb_mod
from pathlib import Path
from typing import AsyncIterator, Any

from argos_agent.daemon.manager import RunManager
import argos_agent.runtime as _runtime

log = logging.getLogger(__name__)

# ── typed Event 桥 ──────────────────────────────────────────────────────

def _to_event_dict(ev: Any) -> dict:
    """typed protocol.events dataclass → dict(落 JSONL + SSE 扇出统一格式)。

    FakeLoop / legacy dict → 原样 copy(向后兼容)。
    dataclass → serialize_event() json → loads → 扁平化(kind 提出顶层)。
    """
    if isinstance(ev, dict):
        return dict(ev)
    # dataclass 判断(frozen=True slots=True 的 protocol.events 类)
    if dataclasses.is_dataclass(ev) and not isinstance(ev, type):
        try:
            from argos_agent.protocol.events import serialize_event
            blob = serialize_event(ev)  # type: ignore[arg-type]
            parsed = json.loads(blob)
            # serialize_event 格式: {"kind": ..., "data": {...}}
            # 扁平化成 {"kind": ..., ...payload...},与 FakeLoop dict 风格一致
            result = {"kind": parsed["kind"]}
            result.update(parsed.get("data", {}))
            return result
        except Exception as exc:  # noqa: BLE001 — 序列化失败安全降级
            log.warning("_to_event_dict: serialize failed (%s), fallback asdict", exc)
            return {**dataclasses.asdict(ev), "kind": getattr(type(ev), "kind", "unknown")}  # type: ignore[arg-type]
    # 其他类型(str 等):最后兜底
    return {"kind": "unknown", "_raw": str(ev)}


# ── daemon 审批 fail-closed 包装 ────────────────────────────────────────

class DaemonApprovalGate:
    """包装真 ApprovalGate,在 daemon 上下文为无交互审批请求加 timeout fail-closed。

    P3 前过渡:daemon 跑的 run 若触发 ApprovalRequest,60s 无响应则自动 deny,
    并投诚实 error 事件("daemon 模式暂无交互审批,已按 fail-closed 拒绝,P3 接通跨进程审批")。
    不许自动放行(护城河铁律)。
    """

    # 和真 ApprovalGate 相同接口的最小子集
    def __init__(self, real_gate: Any, *, timeout_s: float = 60.0,
                 run_id: str = "", manager: "RunManager | None" = None) -> None:
        self._gate = real_gate
        self._timeout_s = timeout_s
        self._run_id = run_id
        self._manager = manager
        # 透传常用属性
        self.level = real_gate.level

    def set_level(self, level: Any) -> None:
        self._gate.set_level(level)
        self.level = level

    def set_workspace(self, ws: Any) -> None:
        self._gate.set_workspace(ws)

    def set_session_id(self, sid: str) -> None:
        self._gate.set_session_id(sid)

    def set_decision_listener(self, fn: Any) -> None:
        self._gate.set_decision_listener(fn)

    def pending(self) -> list:
        return self._gate.pending()

    async def request(self, action: str, args: dict, *, description: str,
                      risk: Any, timeout: float = 60.0,
                      call_id: str | None = None) -> Any:
        """timeout fail-closed:超时 → deny + 投诚实 error 事件。"""
        effective_timeout = min(timeout, self._timeout_s)
        try:
            return await asyncio.wait_for(
                self._gate.request(
                    action, args, description=description, risk=risk,
                    timeout=effective_timeout, call_id=call_id,
                ),
                timeout=effective_timeout + 1.0,  # 给内部超时留 1s 余量
            )
        except asyncio.TimeoutError:
            msg = (
                f"daemon 模式暂无交互审批(action={action!r}),已按 fail-closed 拒绝。"
                "P3 阶段将接通跨进程审批通道。"
            )
            log.warning("DaemonApprovalGate: timeout fail-closed for run %s: %s", self._run_id, msg)
            # 投诚实 error 事件到 SSE
            if self._manager is not None:
                try:
                    await self._manager.fanout(self._run_id, {
                        "kind": "error",
                        "message": msg,
                        "chain": ["ApprovalTimeout", f"action={action!r}"],
                    })
                except Exception:  # noqa: BLE001
                    pass
            # 返回 deny 决定(不自动放行)
            from argos_agent.approval import Decision
            return Decision(kind="deny", reason=msg)

    # 透传审批响应(供 P3 后路径兼容)
    async def respond(self, call_id: str, kind: Any) -> None:
        await self._gate.respond(call_id, kind)

    def approve(self, call_id: str) -> None:
        self._gate.approve(call_id)

    def deny(self, call_id: str) -> None:
        self._gate.deny(call_id)


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
                 registry=None, worktree=None, gate=None,
                 run_stack_close=None):
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
        # per-run ApprovalGate(由 server 注入):components 路径下每 run 独享一个新实例;
        # loop_factory 向后兼容路径下共享 AppComponents.gate。
        # daemon 路径包 DaemonApprovalGate 超时 fail-closed。
        # None = FakeLoop 测试路径,不涉及审批。
        self._gate = gate
        # per-run 清理钩子:RunStack.close() —— 关闭沙箱子进程,不留孤儿。
        # None = 向后兼容路径(loop_factory),不由 worker 负责 sandbox 清理。
        self._run_stack_close = run_stack_close
        # P1 typed event 桥:兼容 dataclass(AgentLoop)和 dict(FakeLoop)两种形态

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
        # 设 per-run runtime context:verify_gate/_run_verify 读 runtime.current()。
        # 必须在驱动 loop 前 set_context,否则 daemon 多 run 下所有 verify 命令都跑在
        # 默认 ~/.argos/verify,完全忽略各 run 自己的 workspace(护城河:verify 三态正确性)。
        if entry.workspace:
            _ws_path = Path(entry.workspace).expanduser().resolve()
        else:
            _ws_path = _runtime._make_default_ctx().workspace
        _rt_ctx = _runtime.RunContext(workspace=_ws_path, verify_dir=_ws_path)
        _rt_token = _runtime.set_context(_rt_ctx)
        try:
            # DaemonApprovalGate 包装:真 gate 存在时加 timeout fail-closed(护城河铁律:不自动放行)。
            if self._gate is not None:
                self._gate.set_workspace(entry.workspace or "")
                self._gate.set_session_id(f"run-{self.run_id}")
                self._gate = DaemonApprovalGate(
                    self._gate, timeout_s=60.0,
                    run_id=self.run_id, manager=self._manager,
                )
            # 1. mark_running
            self._manager.mark_running(self.run_id)
            if self._registry is not None:
                self._registry.mark(run_id=self.run_id, state="running")
            # 2. build loop
            self._loop = self._loop_factory()
            # 3. 拿 pause event
            pause_event = self._manager.pause_event(self.run_id)
            # 4. drive
            async for ev in self._loop.run(entry.goal, session_id=f"run-{self.run_id}"):
                # 取消检测
                if self._manager.is_cancel_requested(self.run_id):
                    break
                # typed Event 桥:dataclass → dict(兼容 FakeLoop dict 直通)
                ev_dict = _to_event_dict(ev)
                ev_kind = ev_dict.get("kind", "")
                # pause 检测:在 step 边界前阻塞
                if ev_kind in ("code_action", "phase_change"):
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
                # 计 step / message + cost(两种形态都走 ev_dict)
                if ev_kind == "code_action":
                    self._step_count += 1
                elif ev_kind == "token_delta":
                    self._message_count += 1
                elif ev_kind == "phase_change":
                    self._current_phase = ev_dict.get("phase", "act")
                elif ev_kind == "cost_update" and self._registry is not None:
                    # 累加 cost 到 registry(cost_usd=None 不累加)
                    try:
                        self._registry.add_cost(
                            run_id=self.run_id,
                            tokens_in_delta=int(ev_dict.get("tokens_in", 0)),
                            tokens_out_delta=int(ev_dict.get("tokens_out", 0)),
                            cost_usd_delta=ev_dict.get("cost_usd"),
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning("worker: cost add failed for %s: %s", self.run_id, e)
                # 序列化 + 持久化 + 投 SSE(统一使用 ev_dict)
                self._event_seq += 1
                ev_dict["_seq"] = self._event_seq
                self._manager.store.append(self.run_id, ev_dict)
                self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
                await self._manager.fanout(self.run_id, ev_dict)
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
            # per-run runtime context 归还(协程退出后 contextvar 恢复到 None)。
            _runtime.reset(_rt_token)
            # per-run sandbox 清理:RunStack.close() 关沙箱子进程,不留孤儿。
            # None = 向后兼容路径(loop_factory),sandbox 由 AppComponents.close 统一清理。
            if self._run_stack_close is not None:
                try:
                    self._run_stack_close()
                except Exception as _e:  # noqa: BLE001
                    log.warning("worker: run_stack_close failed for %s: %s", self.run_id, _e)
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
