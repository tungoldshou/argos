"""审批闸核心测试 —— 装饰器 + 状态机(不调模型,纯逻辑)。"""
import asyncio
import pytest

from argos_agent import approval


@pytest.mark.asyncio
async def test_request_approval_blocks_then_resolves():
    gate = approval.ApprovalGate()
    payload = {"tool": "write_file", "args": {"path": "x.py"}}

    # 后台开协程请求审批
    request_task = asyncio.create_task(gate.request(payload, timeout=0.5))
    await asyncio.sleep(0)  # 让 request 进入等待

    # 此时应该有 pending 请求
    pending = gate.pending()
    assert len(pending) == 1
    call_id = pending[0].call_id
    assert pending[0].payload == payload

    # 批准 → 协程应返回 approved
    gate.approve(call_id, scope="once")
    result = await request_task
    assert result == approval.Decision(approved=True, scope="once")


@pytest.mark.asyncio
async def test_deny_returns_false():
    gate = approval.ApprovalGate()
    request_task = asyncio.create_task(gate.request({"tool": "x"}, timeout=0.5))
    await asyncio.sleep(0)
    call_id = gate.pending()[0].call_id
    gate.deny(call_id, reason="太危险")
    result = await request_task
    assert result.approved is False
    assert result.reason == "太危险"


@pytest.mark.asyncio
async def test_timeout_defaults_to_deny():
    gate = approval.ApprovalGate()
    result = await gate.request({"tool": "x"}, timeout=0.05)
    assert result.approved is False
    assert "超时" in result.reason


@pytest.mark.asyncio
async def test_session_scope_caches_approval():
    gate = approval.ApprovalGate()
    payload = {"tool": "write_file", "args": {"path": "x.py"}}
    request_task = asyncio.create_task(gate.request(payload, timeout=0.5))
    await asyncio.sleep(0)
    call_id = gate.pending()[0].call_id
    gate.approve(call_id, scope="session")
    await request_task

    # 同一 payload 在 session 内 → 立即放行,不阻塞
    result = await gate.request(payload, timeout=0.5)
    assert result.approved is True
    assert result.scope == "session"


def test_requires_approval_decorator_marks_metadata():
    @approval.requires_approval(description="写入文件 {path}", risk="low")
    def write_file(path: str, content: str) -> str:
        """写入文件"""
        return f"wrote {path}"

    assert write_file._approval_required is True
    assert write_file._approval_description == "写入文件 {path}"
    assert write_file._approval_risk == "low"
    # fail-closed:无 gate 上下文 → 默认拒绝(绝不偷偷放行),返回错误字符串而非抛异常
    assert "默认拒绝" in write_file("a.txt", "x")


def test_decorator_runs_original_when_gate_approves():
    """装饰器不破坏原函数:装一个自动批准 gate,调用应跑到真实实现。"""
    @approval.requires_approval(description="写入文件 {path}", risk="low")
    def write_file(path: str, content: str) -> str:
        """写入文件"""
        return f"wrote {path}"

    gate = approval.ApprovalGate()

    async def _auto(payload, timeout=60.0):
        return approval.Decision(approved=True, scope="once")

    gate.request = _auto  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        assert write_file("a.txt", "x") == "wrote a.txt"
    finally:
        approval.reset_current_gate(token)


# ── 缺口补齐:幂等/取消/不可 JSON 值/async 工具/headless 路径 ─────────────────────
def test_approve_unknown_call_id_is_noop():
    gate = approval.ApprovalGate()
    assert gate.approve("nonexistent") is False
    assert gate.deny("nonexistent") is False


@pytest.mark.asyncio
async def test_cancel_all_denies_pending():
    gate = approval.ApprovalGate()
    t1 = asyncio.create_task(gate.request({"tool": "a"}, timeout=5.0))
    t2 = asyncio.create_task(gate.request({"tool": "b"}, timeout=5.0))
    await asyncio.sleep(0)
    assert len(gate.pending()) == 2
    n = gate.cancel_all()
    assert n == 2
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1.approved is False and "session" in r1.reason
    assert r2.approved is False
    assert gate.pending() == []


def test_decorator_preserves_name_and_docstring():
    @approval.requires_approval(description="x", risk="low")
    def my_tool(a: str) -> str:
        """我的工具说明"""
        return a

    assert my_tool.__name__ == "my_tool"
    assert "我的工具说明" in (my_tool.__doc__ or "")


def test_decorator_wraps_async_function():
    @approval.requires_approval(description="async 工具", risk="low")
    async def my_async_tool(x: int) -> str:
        return f"ok-{x}"

    import inspect
    assert inspect.iscoroutinefunction(my_async_tool)
    # 标记属性也应在 wrapper 上
    assert getattr(my_async_tool, "_approval_required", False) is True
    assert getattr(my_async_tool, "_approval_description", None) == "async 工具"
