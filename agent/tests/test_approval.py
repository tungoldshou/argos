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
    # 装饰器不能破坏原函数可调用性
    assert write_file("a.txt", "x") == "wrote a.txt"
