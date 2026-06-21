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
import os
import time
import traceback as tb_mod
from pathlib import Path
from typing import AsyncIterator, Any

from argos.daemon.manager import RunManager
from argos.daemon.state_machine import TERMINAL_STATES
import argos.runtime as _runtime
from argos.i18n import t as _t

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
            from argos.protocol.events import serialize_event
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
    """包装真 ApprovalGate,实现 P3 跨进程审批通道。

    设计:
    · request() 挂起时将 call_id 登记在 _pending_call_ids 集合,
      外部可经 respond(call_id, kind) 立即 resolve —— 这是 P3 跨进程审批的核心路由点。
    · respond() 直接转发到内层 ApprovalGate.respond(),该方法 resolve 对应 Future。
    · 无人响应满 timeout_s → deny + 投诚实 error 事件落 SSE(fail-closed,铁律不自动放行)。
    · timeout_s 可经 create_run 参数 approval_timeout_s 配置(默认 60s)。
    """

    def __init__(self, real_gate: Any, *, timeout_s: float = 60.0,
                 run_id: str = "", manager: "RunManager | None" = None) -> None:
        self._gate = real_gate
        self._timeout_s = timeout_s
        self._run_id = run_id
        self._manager = manager
        # 当前挂起等待外部响应的 call_id 集合(供 server 路由查找用)
        self._pending_call_ids: set[str] = set()
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

    def has_pending_call(self, call_id: str) -> bool:
        """call_id 是否在本 run 的挂起审批中(供 server 路由鉴别)。"""
        return call_id in self._pending_call_ids

    async def request(self, action: str, args: dict, *, description: str,
                      risk: Any, timeout: float = 60.0,
                      call_id: str | None = None) -> Any:
        """P3 跨进程审批主路:挂起等外部 respond 或超时 fail-closed。

        挂起期间 call_id 登记在 _pending_call_ids;外部调 respond() 立即 resolve;
        满 timeout_s 仍无响应 → deny + 诚实 error 事件(护城河:不自动放行)。
        """
        import uuid as _uuid
        if call_id is None:
            call_id = _uuid.uuid4().hex[:12]
        import time as _time
        from argos.approval import Decision as _Decision
        # effective_timeout:DaemonApprovalGate 自己的超时上限
        effective_timeout = min(timeout, self._timeout_s)
        self._pending_call_ids.add(call_id)
        try:
            # 步骤1:启动内层 gate.request() 协程并让它运行到挂起点
            # (内层在 await asyncio.wait_for(fut, ...) 前同步登记 _pending[call_id])
            # asyncio.sleep(0) 让协程运行到挂起点,保证后续 respond() 能找到该 call_id。
            inner_coro = self._gate.request(
                action, args, description=description, risk=risk,
                # 传极大超时给内层:由我们外层来控制超时,避免内层抢先 deny 导致 error 事件丢失
                timeout=effective_timeout * 2,
                call_id=call_id,
            )
            inner_task = asyncio.ensure_future(inner_coro)
            await asyncio.sleep(0)  # 让内层跑到 _pending[call_id] 注册点

            # 步骤2:内层已注册 _pending,安全投 SSE 扇出
            if self._manager is not None:
                try:
                    await self._manager.fanout(self._run_id, {
                        "kind": "approval_request",
                        "call_id": call_id,
                        "action": action,
                        "args": args,
                        "description": description,
                        "risk": str(risk) if not isinstance(risk, str) else risk,
                        "run_id": self._run_id,
                        "ts": _time.time(),
                    })
                except Exception:  # noqa: BLE001 — 扇出失败不阻塞审批主路
                    pass

            # 步骤3:等内层 task 完成,用 effective_timeout 控制超时
            try:
                return await asyncio.wait_for(
                    asyncio.shield(inner_task),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                inner_task.cancel()
                try:
                    await inner_task
                except (asyncio.CancelledError, Exception):
                    pass
                # 清理内层 _pending 残留
                self._gate.deny(call_id)
                # 超时 fail-closed:投诚实 error 事件(持久化 + SSE)
                msg = _t(
                    "daemon.srv.approval_timeout",
                    action=action,
                    run_id=self._run_id,
                    call_id=call_id,
                )
                log.warning("DaemonApprovalGate timeout fail-closed: %s", msg)
                if self._manager is not None:
                    try:
                        error_ev = {
                            "kind": "error",
                            "message": msg,
                            "chain": ["ApprovalTimeout", f"action={action!r}",
                                      f"call_id={call_id!r}"],
                        }
                        self._manager.store.append(self._run_id, error_ev)
                        await self._manager.fanout(self._run_id, error_ev)
                    except Exception:  # noqa: BLE001
                        pass
                return _Decision(kind="deny", reason=msg)
        finally:
            self._pending_call_ids.discard(call_id)

    def respond(self, call_id: str, kind: Any) -> bool:
        """P3 审批响应入口:外部(server)将 call_id + kind 路由到此处即立即 resolve。

        返回 True = 成功 resolve;False = call_id 未知(已超时/不存在)。
        内层 ApprovalGate.respond() 处理 Future resolve + session 缓存语义。
        """
        return self._gate.respond(call_id, kind)

    def approve(self, call_id: str) -> None:
        """backward-compat。"""
        self._gate.approve(call_id)

    def deny(self, call_id: str) -> None:
        """backward-compat。"""
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
                 run_stack_close=None, approval_timeout_s: float = 60.0,
                 ledger_store=None, snapshot=None, attachments=None):
        self.run_id = run_id
        self._manager = manager
        self._loop_factory = loop_factory
        self._loop = None
        self._event_seq = 0
        self._step_count = 0
        self._message_count = 0
        self._current_phase = "act"
        self._task: asyncio.Task | None = None
        # 看门狗:ARGOS_RUN_TIMEOUT_S 超时 → 硬取消卡死的 loop(opt-in,默认关)。
        self._watchdog: asyncio.Task | None = None
        # #5b 扩展(向后兼容,None 时 noop)
        self._registry = registry
        self._worktree = worktree
        # per-run ApprovalGate(由 server 注入):components 路径下每 run 独享一个新实例;
        # loop_factory 向后兼容路径下共享 AppComponents.gate。
        # daemon 路径包 DaemonApprovalGate 超时 fail-closed。
        # None = FakeLoop 测试路径,不涉及审批。
        self._gate = gate
        # P3:跨进程审批超时(可通过 create_run approval_timeout_s 参数配置)。
        self._approval_timeout_s = approval_timeout_s
        # per-run 清理钩子:RunStack.close() —— 关闭沙箱子进程,不留孤儿。
        # None = 向后兼容路径(loop_factory),不由 worker 负责 sandbox 清理。
        self._run_stack_close = run_stack_close
        # P3b §6 行为账本:LedgerStore + run 起点快照(undo_token)
        # None = 向后兼容路径(测试/FakeLoop),不落账本。
        self._ledger_store = ledger_store
        self._snapshot = snapshot         # RunSnapshot | None(run 起点快照,undo_token 来源)
        self._attachments = list(attachments or [])  # 图片附件(create_run body base64 解码而来)→ loop.run
        self._ledger_seq = 0              # 本 run 账本条目顺序号(从 1 起)
        # P1 typed event 桥:兼容 dataclass(AgentLoop)和 dict(FakeLoop)两种形态

    @property
    def event_seq(self) -> int:
        return self._event_seq

    @property
    def current_step(self) -> int:
        return self._step_count

    @property
    def gate(self) -> "DaemonApprovalGate | None":
        """P3:返回本 run 当前的 DaemonApprovalGate(或 None 若无审批门禁)。
        server 经此属性把 approval_response 路由到正确 run 的 gate.respond()。
        注意:run() 启动后 self._gate 才被替换为 DaemonApprovalGate;
        启动前返回原始 gate 对象(None 或真 gate)。
        """
        return self._gate  # type: ignore[return-value]

    def request_hard_cancel(self) -> bool:
        """硬取消:直接 cancel 包装 run() 的 asyncio task,在 await 点(如卡住的 model stream)
        抛 CancelledError 立即中断。区别于 manager.request_cancel 的 set-flag —— 后者只在事件
        边界轮询生效,无法中断阻塞中的 stream(用户取消后可继续跑 ~5min,打脸"可控")。
        worker.run() 的 except CancelledError + finally 负责标 cancelled 并收尾(释放 slot/
        worktree/registry),故硬中断是安全的。返回是否真触发(task 存在且未完成)。"""
        t = self._task
        if t is not None and not t.done():
            t.cancel()
            return True
        return False

    async def run(self) -> None:
        """worker 入口:running → 完成/失败/取消 之一。

        终态收尾(#5b §9.3):
          · release semaphore slot
          · worktree cleanup
          · registry.cleanup(标终态 + 缩 max_history)
        """
        # 自持包装本协程的 task,供 request_hard_cancel 硬中断卡住的 stream(set-flag 边界轮询不够)。
        self._task = asyncio.current_task()
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
        # P0 防假绿:daemon 的 verify_dir==workspace(测试与解同目录),必须 project_mode=True——
        # 这是唯一让 loop 起始 guard_project_tests 快照既有测试、detect_tampering 在 verify 时通电
        # 的开关(runtime.guard_project_tests 对 project_mode=False 直接返 0)。否则 agent 在
        # workspace 改自己的测试、verify 跑被改后的测试 → 假绿且不可见(篡改检测整条死掉)。
        _rt_ctx = _runtime.RunContext(workspace=_ws_path, verify_dir=_ws_path, project_mode=True)
        _rt_token = _runtime.set_context(_rt_ctx)
        try:
            # 看门狗:仅当 ARGOS_RUN_TIMEOUT_S 设定(>0)才启;超时硬取消卡死的 loop。
            self._watchdog = self._maybe_start_watchdog()
            # DaemonApprovalGate 包装:真 gate 存在且尚未包装时加 timeout fail-closed。
            # P3:timeout_s 来自 create_run approval_timeout_s 参数(默认 60s),支持可配。
            # 已是 DaemonApprovalGate(测试预包装路径)则跳过,避免双重包装。
            if self._gate is not None and not isinstance(self._gate, DaemonApprovalGate):
                self._gate.set_workspace(entry.workspace or "")
                self._gate.set_session_id(f"run-{self.run_id}")
                self._gate = DaemonApprovalGate(
                    self._gate, timeout_s=self._approval_timeout_s,
                    run_id=self.run_id, manager=self._manager,
                )
            elif self._gate is not None:
                # 已包装:只更新 workspace/session(不再重建)
                self._gate.set_workspace(entry.workspace or "")
                self._gate.set_session_id(f"run-{self.run_id}")
            # 1. mark_running
            self._manager.mark_running(self.run_id)
            if self._registry is not None:
                self._registry.mark(run_id=self.run_id, state="running")
            # 2. build loop
            self._loop = self._loop_factory()
            # 3. 拿 pause event
            pause_event = self._manager.pause_event(self.run_id)
            # 4. drive
            # 仅在真有图片附件时传 attachments kwarg → 无附件路径调用签名与改造前逐字一致
            # (测试/演示用的精简 FakeLoop 们无需都改 run 签名,零回归)。
            _run_kwargs = {"attachments": self._attachments} if self._attachments else {}
            async for ev in self._loop.run(entry.goal, session_id=f"run-{self.run_id}",
                                           **_run_kwargs):
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
                # 序列化 + 持久化 + 投 SSE(统一使用 ev_dict)。_seq 由 store 集中领号(唯一单调,
                # 跨 worker/manager 两条写入路径一致 → 客户端按 _seq 续传不错位);用返回值更新 index。
                self._event_seq = self._manager.store.append(self.run_id, ev_dict)
                self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
                await self._manager.fanout(self.run_id, ev_dict)
                # P3b §6 行为账本:ToolReceipt 事件 → LedgerEntry 落盘 + 广播
                if ev_kind == "tool_receipt" and self._ledger_store is not None:
                    await self._maybe_append_ledger(ev_dict)
                # A3:FileDiff 事件 → 文件改动账本条目(文件粒度 undo 来源)
                elif ev_kind == "file_diff" and self._ledger_store is not None:
                    await self._maybe_append_ledger_for_file_diff(ev_dict)
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
            # 看门狗收尾:正常结束则取消(避免孤儿 sleep task)。
            if self._watchdog is not None:
                self._watchdog.cancel()
                self._watchdog = None
            # 终态广播:run 此刻必为终态 → fanout 一条 state_change,让 SSE 订阅者立即醒来
            # 关流(免等 server 2s keepalive tick)。fanout 仅 put_nowait 不挂起,取消中调用安全。
            await self._emit_terminal_signal()
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

    def _maybe_start_watchdog(self) -> "asyncio.Task | None":
        """opt-in 看门狗:ARGOS_RUN_TIMEOUT_S 秒后硬取消本 run(防真·死循环/卡死 stream)。

        默认关闭(未设/<=0/非法 → None,不启)。这是墙钟上限,不区分暂停时间 —— 仅供"宁可
        误杀也不永挂"的运行环境显式开启;交互式默认场景靠 SSE 终态关流(B1)自愈即可。
        """
        raw = os.environ.get("ARGOS_RUN_TIMEOUT_S", "").strip()
        if not raw:
            return None
        try:
            timeout_s = float(raw)
        except ValueError:
            return None
        if timeout_s <= 0:
            return None
        return asyncio.create_task(self._watchdog_timer(timeout_s))

    async def _watchdog_timer(self, timeout_s: float) -> None:
        """睡 timeout_s 后硬取消 run;被 finally cancel(正常结束)则静默退出。"""
        try:
            await asyncio.sleep(timeout_s)
        except asyncio.CancelledError:
            return
        log.warning(
            "worker: run %s 超过看门狗超时 %.1fs,硬取消", self.run_id, timeout_s
        )
        self.request_hard_cancel()

    async def _emit_terminal_signal(self) -> None:
        """run 收尾时广播终态 state_change → SSE 订阅者立即醒来关流(B1 的即时性补充)。

        run 此刻应已是终态(completed/failed/cancelled);非终态(防御性)则跳过。
        fail-soft:广播失败仅 log,不阻断收尾。
        """
        try:
            entry = self._manager.index.get(self.run_id)
            state = entry.state if entry is not None else None
            if state not in TERMINAL_STATES:
                return
            await self._manager.fanout(self.run_id, {
                "kind": "state_change",
                "from": "running",
                "to": state,
                "reason": "terminal",
                "ts": time.time(),
            })
        except Exception as e:  # noqa: BLE001
            log.warning("worker: 终态广播失败 for %s: %s", self.run_id, e)

    async def _maybe_append_ledger(self, ev_dict: dict) -> None:
        """P3b §6:从 tool_receipt 事件 dict 构建 LedgerEntry 并落盘 + 广播 LedgerEntryEvent。

        fail-soft:任何错误 log warning + 不抛(账本丢失不阻断主流程)。
        """
        try:
            from argos.ledger.builder import build_entry
            from argos.protocol.events import LedgerEntryEvent

            # receipt 可能是 dict(序列化后)或 Receipt dataclass
            receipt_data = ev_dict.get("receipt") or {}
            if not isinstance(receipt_data, dict):
                # 已是 dataclass:转 dict
                import dataclasses as _dc
                receipt_data = _dc.asdict(receipt_data)  # type: ignore[arg-type]

            if not receipt_data.get("action"):
                return  # 无效 receipt,跳过

            # 构建最小 receipt-like 对象(鸭子类型:build_entry 只读 .action/.ts/.sig)
            class _FakeReceipt:
                def __init__(self, d: dict) -> None:
                    self.action = str(d.get("action", ""))
                    self.ts = float(d.get("ts", 0.0))
                    self.sig = str(d.get("sig", ""))

            fake_receipt = _FakeReceipt(receipt_data)

            # undo_token = run 起点快照 tar 路径(str);无快照 → None
            undo_token: str | None = None
            if self._snapshot is not None:
                try:
                    snap_path = self._snapshot.tar_path
                    if snap_path.exists():
                        undo_token = str(snap_path)
                except Exception:  # noqa: BLE001
                    pass

            self._ledger_seq += 1
            entry = build_entry(
                receipt=fake_receipt,
                run_id=self.run_id,
                seq=self._ledger_seq,
                args={},           # v1:args 不随 receipt 广播,用空 dict 生成保守人话
                undo_token=undo_token,
            )
            # 落盘
            self._ledger_store.append(entry)  # type: ignore[union-attr]

            # 广播 LedgerEntryEvent(SSE 扇出)
            le_ev = LedgerEntryEvent(
                ts=entry.ts,
                run_id=entry.run_id,
                seq=entry.seq,
                action=entry.action,
                summary_human=entry.summary_human,
                risk=entry.risk,
                reversible=entry.reversible,
                undo_state=entry.undo_state,
            )
            from argos.protocol.events import serialize_event
            import json as _json
            parsed = _json.loads(serialize_event(le_ev))
            le_dict = {"kind": parsed["kind"]}
            le_dict.update(parsed.get("data", {}))
            # ledger 事件从主事件计数器领号(与所有 SSE 事件同一单调序列):
            # 偏移方案(event_seq + ledger_seq)会与后续常规事件撞号,照样破坏 since=N 游标。
            self._event_seq += 1
            le_dict["_seq"] = self._event_seq
            self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
            self._manager.store.append(self.run_id, le_dict)
            await self._manager.fanout(self.run_id, le_dict)
        except Exception as e:  # noqa: BLE001 — 账本路径必须不挂主任务
            log.warning("worker: ledger append failed for %s: %s", self.run_id, e)

    async def _maybe_append_ledger_for_file_diff(self, ev_dict: dict) -> None:
        """A3:从 file_diff 事件构建文件改动 LedgerEntry 并落盘 + 广播。

        LedgerEntry 字段语义:
          action        = "file_diff"
          summary_human = 确定性模板 "修改了 {basename}(+{added}/-{removed})"
          reversible    = "yes"(有 run 起点快照时)/"unknown"(无快照)
          undo_token    = "file:{rel_path}"(文件粒度 undo 令牌,含前缀以区分 run 级 undo_token)

        fail-soft:任何错误 log warning + 不抛(账本丢失不阻断主流程)。
        """
        try:
            from argos.ledger.entry import LedgerEntry
            from argos.protocol.events import LedgerEntryEvent
            import os
            import time as _time

            path_str: str = str(ev_dict.get("path", ""))
            added: int = int(ev_dict.get("added", 0))
            removed: int = int(ev_dict.get("removed", 0))

            if not path_str:
                return  # 无路径,跳过

            basename = os.path.basename(path_str) or path_str

            # undo_token = "file:{rel_path}";有快照时 reversible=yes,无快照 unknown
            undo_token: str | None = None
            reversible = "unknown"
            if self._snapshot is not None:
                try:
                    snap_path = self._snapshot.tar_path
                    if snap_path.exists():
                        undo_token = f"file:{path_str}"
                        reversible = "yes"
                except Exception:  # noqa: BLE001
                    pass

            undo_state = "available" if reversible == "yes" else "impossible"
            # summary_human:确定性模板
            if added or removed:
                summary = _t("daemon.srv.ledger_modified_diff",
                             basename=basename, added=added, removed=removed)
            else:
                summary = _t("daemon.srv.ledger_modified", basename=basename)

            self._ledger_seq += 1
            entry = LedgerEntry(
                ts=_time.time(),
                run_id=self.run_id,
                seq=self._ledger_seq,
                action="file_diff",
                summary_human=summary,
                risk="low",
                reversible=reversible,  # type: ignore[arg-type]
                undo_token=undo_token,
                receipt_sig="",
                undo_state=undo_state,  # type: ignore[arg-type]
            )
            # 落盘
            self._ledger_store.append(entry)  # type: ignore[union-attr]

            # 广播 LedgerEntryEvent(SSE 扇出)
            from argos.protocol.events import serialize_event
            import json as _json
            le_ev = LedgerEntryEvent(
                ts=entry.ts,
                run_id=entry.run_id,
                seq=entry.seq,
                action=entry.action,
                summary_human=entry.summary_human,
                risk=entry.risk,
                reversible=entry.reversible,
                undo_state=entry.undo_state,
            )
            parsed = _json.loads(serialize_event(le_ev))
            le_dict = {"kind": parsed["kind"]}
            le_dict.update(parsed.get("data", {}))
            # 从主事件计数器领号(保 _seq 单调唯一,与 test_ledger_seq_unique 纪律一致)
            self._event_seq += 1
            le_dict["_seq"] = self._event_seq
            self._manager.index.upsert(self.run_id, last_event_seq=self._event_seq)
            self._manager.store.append(self.run_id, le_dict)
            await self._manager.fanout(self.run_id, le_dict)
        except Exception as e:  # noqa: BLE001 — 账本路径必须不挂主任务
            log.warning("worker: file_diff ledger append failed for %s: %s", self.run_id, e)

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
            from argos.learning.hook import on_run_completed
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
                candidates_root=Path(os.path.expanduser("~/.argos/learning/candidates")),
                workspace=(getattr(entry, "workspace", "") or None),
                runner_factory=None,   # worker 不持有 EvalRunner;hook 跳过 promote 仅产候选
                tasks=[],              # 同上
            )
        except Exception as e:  # noqa: BLE001 — learning 路径必须不挂主任务
            log.warning("worker: learning hook failed for %s: %s", self.run_id, e)
