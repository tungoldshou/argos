"""审批闸 —— 工具调用前同步等用户决定,默认 deny。

架构选择:用工具自声明(@requires_approval)而非黑盒 middleware,原因:
  · 工具自己最清楚自己副作用的语义,弹窗能展示'人类可读描述'(如"将写入 app.py")。
  · 与 LangChain 解耦,LangChain 升级不破坏审批层。
  · 1 个工具 1 个声明,比'全局按名字拦截'更精确。
  · 弹窗是可选 UI:headless / 测试 / agent loop 模式可注入自己的 ApprovalGate。

Phase 3 Task 9 迁移(契约 §6.3 锁#3):
  · Decision: (approved, scope) → (kind: DecisionKind, reason) frozen dataclass;approved 改为 property。
  · ApprovalLevel: 新增 OBSERVE/PROPOSE/CONFIRM/AUTO 四档枚举。
  · ApprovalGate.request: 新签名 request(action, args, *, description, risk, timeout)。
  · ApprovalGate.respond: 新方法,对应旧 approve()+deny();旧方法保留 backward-compat。
  · guarded_call: 新签名 guarded_call(action, args, run, *, description, risk, timeout)。
"""
from __future__ import annotations

import asyncio
import contextvars
import enum
import functools
import inspect
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal


RiskLevel = Literal["low", "medium", "high"]
DecisionKind = Literal["deny", "once", "session", "always"]


class ApprovalLevel(enum.Enum):
    OBSERVE = "observe"   # 只看,不执行副作用
    PROPOSE = "propose"   # 出方案待批
    CONFIRM = "confirm"   # 逐个批(默认)
    AUTO = "auto"         # 放手(YOLO;TUI 头部亮红 ⏻)


@dataclass(frozen=True, slots=True)
class Decision:
    """契约 §6.3 锁#3:kind 字段 + approved property,无 scope 字段。"""
    kind: DecisionKind               # deny | once | session | always
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.kind != "deny"


@dataclass
class _Pending:
    call_id: str
    payload: dict[str, Any]
    created_at: float  # 留作 UI 排序/超时提示用,目前未消费
    future: asyncio.Future[Decision]
    # future 绑定在「创建它的那个事件循环」上。被审批的工具可能跑在 langchain 的执行线程
    # (有自己的 loop),而 approve/deny 来自主 loop —— 跨 loop 直接 set_result 不会唤醒
    # 工具所在的 loop。记下该 loop,统一用 call_soon_threadsafe 调度,两种情况都对。
    loop: asyncio.AbstractEventLoop


def _resolve(fut: asyncio.Future, decision: "Decision") -> None:
    """在 future 所属 loop 上安全收尾:可能已超时/取消,先查 done 再 set。"""
    if not fut.done():
        fut.set_result(decision)


@dataclass
class _SessionApproval:
    """session-scope 缓存:同一 payload 整个 session 都被默许。"""
    payload_hash: str
    approved_at: float


def _hash_payload(payload: dict[str, Any]) -> str:
    """稳定 hash —— 顺序无关,便于同 payload 命中缓存。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


class ApprovalGate:
    """每个 session 一个实例。契约 §6.3:level 拨盘 + respond 速选(1=deny 2=once 3=session 4=always)。
    保留旧的跨 loop 唤醒、超时 fail-closed、session 缓存语义。
    旧 approve()/deny() 方法保留 backward-compat(server.py 旧路径使用中)。"""

    def __init__(self, level: ApprovalLevel = ApprovalLevel.CONFIRM) -> None:
        self.level = level
        self._pending: dict[str, _Pending] = {}
        self._session_approvals: dict[str, _SessionApproval] = {}

    def set_level(self, level: ApprovalLevel) -> None:
        self.level = level

    def pending(self) -> list[_Pending]:
        return list(self._pending.values())

    async def request(self, action: str, args: dict[str, Any], *, description: str,
                      risk: RiskLevel, timeout: float = 60.0) -> Decision:
        """阻塞等用户决定(契约 §6.3 签名)。
        AUTO 档 → 立即 once 放行;OBSERVE 档 → 立即 deny(只看不动手);
        session 缓存命中 → 立即放行;否则挂起等 respond,超时 fail-closed deny。"""
        if self.level is ApprovalLevel.AUTO:
            return Decision(kind="once", reason="AUTO 档放手")
        if self.level is ApprovalLevel.OBSERVE:
            return Decision(kind="deny", reason="OBSERVE 档:只看不执行副作用")
        payload = {"action": action, "args": args}
        key = _hash_payload(payload)
        if self._session_approvals.get(key) is not None:
            return Decision(kind="session", reason="session 已批准")
        call_id = uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Decision] = loop.create_future()
        self._pending[call_id] = _Pending(
            call_id=call_id, payload={**payload, "description": description, "risk": risk},
            created_at=time.time(), future=fut, loop=loop,
        )
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(call_id, None)
            return Decision(kind="deny", reason="审批超时,默认拒绝")

    def respond(self, call_id: str, decision: DecisionKind) -> bool:
        """TUI ApprovalModal 速选(1=deny 2=once 3=session 4=always)回灌。
        session/always 把 payload 加进 session 缓存(always 在本 session 内等价 session)。"""
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        if decision in ("session", "always"):
            payload = {"action": p.payload.get("action"), "args": p.payload.get("args")}
            key = _hash_payload(payload)
            self._session_approvals[key] = _SessionApproval(
                payload_hash=key, approved_at=time.time(),
            )
        self._settle(p, Decision(kind=decision))
        return True

    # ── backward-compat: 旧 approve()/deny() —— server.py 使用中,勿删 ──────────
    def approve(self, call_id: str, scope: Literal["once", "session"] = "once") -> bool:
        """backward-compat:把 scope 映射到新 respond。server.py 旧路径使用中。"""
        kind: DecisionKind = "session" if scope == "session" else "once"
        return self.respond(call_id, kind)

    def deny(self, call_id: str, reason: str = "") -> bool:
        """backward-compat:对应新 respond(call_id, "deny")。server.py 旧路径使用中。"""
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        self._settle(p, Decision(kind="deny", reason=reason))
        return True

    def cancel_all(self) -> int:
        """session 终止时调用,把所有挂着的请求以 deny 收尾(避免挂死)。"""
        n = 0
        for p in list(self._pending.values()):
            self._settle(p, Decision(kind="deny", reason="session 终止"))
            n += 1
        self._pending.clear()
        return n

    @staticmethod
    def _settle(p: _Pending, decision: "Decision") -> None:
        """把 decision 投递到 future 所属 loop。跨 loop 用 call_soon_threadsafe 唤醒;
        loop 已关闭(run 早退后才来的迟到决定)则安全忽略。"""
        try:
            p.loop.call_soon_threadsafe(_resolve, p.future, decision)
        except RuntimeError:
            pass  # event loop is closed


def requires_approval(description: str, risk: RiskLevel = "medium") -> Callable:
    """装饰器:标记该工具调用前需用户审批。description 里的 {arg_name} 会被替换。
    工具本体用字符串返回错误(同其他工具约定),让模型看到并换路,而不抛异常。"""

    def deco(fn: Callable) -> Callable:
        # 用 inspect 拿参数名,这样 _serialize_args 能闭包到 fn
        try:
            sig = inspect.signature(fn)
            param_names = list(sig.parameters.keys())
            var_positional = {n for n, p in sig.parameters.items()
                              if p.kind == inspect.Parameter.VAR_POSITIONAL}
            var_keyword = {n for n, p in sig.parameters.items()
                           if p.kind == inspect.Parameter.VAR_KEYWORD}
        except Exception:
            param_names = []
            var_positional = set()
            var_keyword = set()

        def _serialize(args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            extra_pos: list[Any] = []
            for i, a in enumerate(args):
                if i < len(param_names) and param_names[i] in var_positional:
                    extra_pos.append(a)
                    continue
                if i < len(param_names) and param_names[i] not in var_keyword:
                    key = param_names[i]
                else:
                    extra_pos.append(a)
                    continue
                try:
                    json.dumps(a)
                    out[key] = a
                except (TypeError, ValueError):
                    out[key] = repr(a)
            if extra_pos:
                try:
                    json.dumps(extra_pos)
                    out["*args"] = extra_pos
                except (TypeError, ValueError):
                    out["*args"] = repr(extra_pos)
            extra_kw: dict[str, Any] = {}
            for k, v in kwargs.items():
                if k in var_keyword:
                    extra_kw[k] = v
                    continue
                try:
                    json.dumps(v)
                    out[k] = v
                except (TypeError, ValueError):
                    out[k] = repr(v)
            if extra_kw:
                out["**kwargs"] = extra_kw
            return out

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> str:
            gate = _current_gate()
            if gate is None:
                # 无 gate 上下文(测试 / headless)→ fail-closed 拒绝,绝不放行
                return "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
            tool_name = getattr(fn, "__name__", str(fn))
            serialized_args = _serialize(args, kwargs)
            decision = await gate.request(
                tool_name, serialized_args,
                description=description,
                risk=risk,
            )
            if not decision.approved:
                return (
                    f"用户拒绝执行该操作({decision.reason or '未提供原因'})。"
                    f"请尝试其他做法或向用户解释为什么需要它。"
                )
            return await _call_original(fn, args, kwargs)

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> str:
            gate = _current_gate()
            if gate is None:
                return "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
            if asyncio.iscoroutinefunction(fn):
                return "错误:同步工具包装器收到了异步调用路径,这是内部错误。"
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False
            if in_loop:
                return "错误:同步工具不能在事件循环中等待审批,请改用异步版本。"
            return asyncio.run(async_wrapper(*args, **kwargs))

        # functools.wraps 已复制 __name__/__doc__/__wrapped__ —— __wrapped__ 让
        # inspect.signature(wrapper) 透传原签名,langchain @tool 才能建出正确的 args schema
        # (否则模型看到的是 (*args, **kwargs) 而非具名参数)。
        wrapper = async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper
        wrapper._approval_required = True  # type: ignore[attr-defined]
        wrapper._approval_description = description  # type: ignore[attr-defined]
        wrapper._approval_risk = risk  # type: ignore[attr-defined]
        return wrapper

    return deco


# ── gate 上下文(per-session,ContextVar 避免并发污染)──────────────────────────
_current_gate_var: contextvars.ContextVar["ApprovalGate | None"] = contextvars.ContextVar(
    "argos_approval_gate", default=None,
)


def set_current_gate(gate: "ApprovalGate | None") -> contextvars.Token:
    return _current_gate_var.set(gate)


def reset_current_gate(token: contextvars.Token) -> None:
    _current_gate_var.reset(token)


def _current_gate() -> "ApprovalGate | None":
    return _current_gate_var.get()


async def guarded_call(
    action: str,
    args: dict[str, Any],
    run: Callable[[], Any],
    *,
    description: str,
    risk: RiskLevel,
    timeout: float = 60.0,
) -> Any:
    """审批守卫(装饰器与 MCP 工具包装共用,契约 §6.3 新签名):
    · 无 gate 上下文 → fail-closed 返回拒绝串;
    · gate 拒绝 → 返回拒绝串(模型看到换路,不抛异常);
    · 批准 → await run()(run 是个返回 awaitable 的零参可调用)。"""
    gate = _current_gate()
    if gate is None:
        return "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
    decision = await gate.request(action, args, description=description, risk=risk, timeout=timeout)
    if not decision.approved:
        return (
            f"用户拒绝执行该操作({decision.reason or '未提供原因'})。"
            f"请尝试其他做法或向用户解释为什么需要它。"
        )
    return await run()


async def _call_original(fn: Callable, args: tuple, kwargs: dict[str, Any]) -> Any:
    """调用原工具(同步/异步都支持)。"""
    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res
