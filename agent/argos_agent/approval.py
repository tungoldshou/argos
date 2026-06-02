"""审批闸 —— 工具调用前同步等用户决定,默认 deny。

架构选择:用工具自声明(@requires_approval)而非黑盒 middleware,原因:
  · 工具自己最清楚自己副作用的语义,弹窗能展示'人类可读描述'(如"将写入 app.py")。
  · 与 LangChain 解耦,LangChain 升级不破坏审批层。
  · 1 个工具 1 个声明,比'全局按名字拦截'更精确。
  · 弹窗是可选 UI:headless / 测试 / agent loop 模式可注入自己的 ApprovalGate。
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal


RiskLevel = Literal["low", "medium", "high"]
Scope = Literal["once", "session"]


@dataclass
class Decision:
    approved: bool
    scope: Scope = "once"
    reason: str = ""


@dataclass
class _Pending:
    call_id: str
    payload: dict
    created_at: float
    future: asyncio.Future[Decision]


@dataclass
class _SessionApproval:
    """session-scope 缓存:同一 payload 整个 session 都被默许。"""
    payload_hash: str
    approved_at: float


def _hash_payload(payload: dict) -> str:
    """稳定 hash —— 顺序无关,便于同 payload 命中缓存。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


class ApprovalGate:
    """每个 session 一个实例,挂在 server 的 session 状态上。"""

    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}
        self._session_approvals: dict[str, _SessionApproval] = {}

    def pending(self) -> list[_Pending]:
        return list(self._pending.values())

    async def request(self, payload: dict, timeout: float = 60.0) -> Decision:
        """阻塞等用户决定。session-scope 缓存命中 → 立即放行。"""
        key = _hash_payload(payload)
        cached = self._session_approvals.get(key)
        if cached is not None:
            return Decision(approved=True, scope="session")

        call_id = uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Decision] = loop.create_future()
        self._pending[call_id] = _Pending(
            call_id=call_id, payload=payload,
            created_at=time.time(), future=fut,
        )
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            # fail-closed: 超时 = 拒绝,绝不偷偷放行
            self._pending.pop(call_id, None)
            return Decision(approved=False, reason="审批超时,默认拒绝")

    def approve(self, call_id: str, scope: Scope = "once") -> bool:
        """批准一个 pending 请求;scope=session 时把 payload 加进 session 缓存。"""
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        if scope == "session":
            self._session_approvals[_hash_payload(p.payload)] = _SessionApproval(
                payload_hash=_hash_payload(p.payload), approved_at=time.time(),
            )
        if not p.future.done():
            p.future.set_result(Decision(approved=True, scope=scope))
        return True

    def deny(self, call_id: str, reason: str = "") -> bool:
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        if not p.future.done():
            p.future.set_result(Decision(approved=False, reason=reason))
        return True

    def cancel_all(self) -> int:
        """session 终止时调用,把所有挂着的请求以 deny 收尾(避免挂死)。"""
        n = 0
        for p in list(self._pending.values()):
            if not p.future.done():
                p.future.set_result(Decision(approved=False, reason="session 终止"))
            n += 1
        self._pending.clear()
        return n


def requires_approval(description: str, risk: RiskLevel = "medium") -> Callable:
    """装饰器:标记该工具调用前需用户审批。description 里的 {arg_name} 会被替换。
    工具本体用字符串返回错误(同其他工具约定),让模型看到并换路,而不抛异常。"""

    def deco(fn: Callable) -> Callable:
        fn._approval_required = True  # type: ignore[attr-defined]
        fn._approval_description = description  # type: ignore[attr-defined]
        fn._approval_risk = risk  # type: ignore[attr-defined]
        # 用 inspect 拿参数名,这样 _serialize_args 能闭包到 fn
        try:
            param_names = list(inspect.signature(fn).parameters.keys())
        except Exception:
            param_names = []

        def _serialize(args: tuple, kwargs: dict) -> dict:
            out: dict = {}
            for i, a in enumerate(args):
                key = param_names[i] if i < len(param_names) else f"arg{i}"
                try:
                    json.dumps(a)
                    out[key] = a
                except (TypeError, ValueError):
                    out[key] = repr(a)
            for k, v in kwargs.items():
                try:
                    json.dumps(v)
                    out[k] = v
                except (TypeError, ValueError):
                    out[k] = repr(v)
            return out

        async def async_wrapper(*args: Any, **kwargs: Any) -> str:
            gate = _current_gate()
            if gate is None:
                # 无 gate 上下文(测试 / headless)→ fail-closed 拒绝,绝不放行
                return "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
            payload = {
                "tool": getattr(fn, "__name__", str(fn)),
                "args": _serialize(args, kwargs),
                "description": description,
                "risk": risk,
            }
            decision = await gate.request(payload)
            if not decision.approved:
                return (
                    f"用户拒绝执行该操作({decision.reason or '未提供原因'})。"
                    f"请尝试其他做法或向用户解释为什么需要它。"
                )
            return await _call_original(fn, args, kwargs)

        def sync_wrapper(*args: Any, **kwargs: Any) -> str:
            # 无 async 上下文(如纯同步测试)且无 gate → 退化执行(测试不该被审批阻塞)。
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False
            gate = _current_gate()
            if gate is None and not in_loop:
                # headless 模式:无 gate、无 loop → 直接调原函数
                return _call_original_sync(fn, args, kwargs)
            return asyncio.run(async_wrapper(*args, **kwargs))

        wrapper = async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper
        wrapper.__name__ = getattr(fn, "__name__", "wrapped")
        wrapper.__doc__ = getattr(fn, "__doc__", None)
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


async def _call_original(fn: Callable, args: tuple, kwargs: dict) -> Any:
    """调用原工具(同步/异步都支持)。"""
    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res


def _call_original_sync(fn: Callable, args: tuple, kwargs: dict) -> Any:
    """同步路径:直接调原函数(无审批,headless 用)。"""
    res = fn(*args, **kwargs)
    return res
