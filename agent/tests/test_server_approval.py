"""审批闸的服务端端到端铁证 —— 真实跑通 approval_request 事件 + /approve 处理器。

不打桩 gate:用一个 FakeAgent,它的 astream 在工具步真正 `await write_file.ainvoke(...)`,
于是审批闸真的会阻塞;_run_stream 的并发监视任务把 approval_request 推进事件流;我们一收到
就调真正的 /approve 处理器解除阻塞,工具落地、run 收尾。这正是生产里 langgraph →
ToolNode → .ainvoke 的形状。

为什么直接驱动 _run_stream 而非走 httpx:httpx 的 ASGITransport 会把流式响应整体缓冲,
没法「边读流边并发 POST」,工具只能干等到 60s 超时。直接消费 async 生成器才是真增量流,
且仍调用真实的 approve_call 处理器(只是不过 HTTP),整条生成器+监视+gate+端点都被覆盖。
"""
import json

import pytest
from fastapi.testclient import TestClient

from argos_agent import runtime, server, tools


@pytest.fixture(autouse=True)
def _reset_server_state(tmp_path, monkeypatch):
    """每个用例:把 workspace 指到临时目录,清掉会话/全局单飞标志,回沙盒态。"""
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    server.SESSIONS.clear()
    server._RUN_ACTIVE = False
    runtime.use_sandbox()
    yield tmp_path
    server.SESSIONS.clear()
    server._RUN_ACTIVE = False


class _FakeAgent:
    """模拟 langgraph agent.astream 的形状:产 tool_call → 真跑工具(触发审批)→ tool_result → 定稿。"""

    async def astream(self, _inp, stream_mode=None):
        from langchain_core.messages import AIMessage, ToolMessage

        ai = AIMessage(
            content="",
            tool_calls=[{
                "name": "write_file",
                "args": {"path": "a.txt", "content": "hi"},
                "id": "call1", "type": "tool_call",
            }],
        )
        yield ("values", {"messages": [ai]})
        # 工具真正执行 —— 经 @requires_approval 包装会阻塞等审批,直到 /approve。
        result = await tools.write_file.ainvoke({"path": "a.txt", "content": "hi"})
        tm = ToolMessage(content=result, tool_call_id="call1")
        yield ("values", {"messages": [ai, tm]})
        yield ("values", {"messages": [ai, tm, AIMessage(content="已完成。")]})


def _parse(raw: str) -> tuple[str, dict]:
    event = ""
    data: dict = {}
    for line in raw.splitlines():
        if line.startswith("event:"):
            event = line.split("event:", 1)[1].strip()
        elif line.startswith("data:"):
            data = json.loads(line.split("data:", 1)[1].strip())
    return event, data


async def _drive(decision: str) -> tuple[list, dict | None]:
    """消费 _run_stream;一见 approval_request 就调真正的 approve_call 处理器按 decision 回应。"""
    gen = server._run_stream("写个文件")
    frames: list[tuple[str, dict]] = []
    session_id = None
    approve_resp = None
    try:
        async for raw in gen:
            event, data = _parse(raw)
            frames.append((event, data))
            if event == "session":
                session_id = data["session_id"]
            elif event == "approval_request":
                body = server.ApproveRequest(
                    call_id=data["call_id"], decision=decision,
                    scope="once", reason="测试拒绝",
                )
                approve_resp = server.approve_call(session_id, body)
    finally:
        await gen.aclose()
    return frames, approve_resp


@pytest.mark.asyncio
async def test_approve_unblocks_tool_and_completes(monkeypatch, _reset_server_state):
    tmp_path = _reset_server_state
    monkeypatch.setattr(server, "build_agent_with_gate", lambda **kw: (_FakeAgent(), None))
    frames, approve_resp = await _drive("approve")

    kinds = [e for e, _ in frames]
    assert "approval_request" in kinds, f"应收到 approval_request,实得 {kinds}"
    ar = next(d for e, d in frames if e == "approval_request")
    assert ar["tool"] == "write_file"
    assert ar["description"] == "写入文件 {path}"
    assert ar["risk"] == "low"
    assert ar["args"]["path"] == "a.txt"
    assert approve_resp == {"ok": True}

    tool_results = [d["content"] for e, d in frames if e == "tool_result"]
    assert any("已写入" in c for c in tool_results), f"approve 后工具应真执行,实得 {tool_results}"
    done = next(d for e, d in frames if e == "done")
    assert done["resolved"] is True
    # 文件真被写到临时 workspace
    assert (tmp_path / "a.txt").read_text() == "hi"


@pytest.mark.asyncio
async def test_deny_refuses_and_skips_side_effect(monkeypatch, _reset_server_state):
    tmp_path = _reset_server_state
    monkeypatch.setattr(server, "build_agent_with_gate", lambda **kw: (_FakeAgent(), None))
    frames, approve_resp = await _drive("deny")

    assert approve_resp == {"ok": True}  # deny 成功命中了挂起项
    tool_results = [d["content"] for e, d in frames if e == "tool_result"]
    assert any("用户拒绝" in c for c in tool_results), f"deny 后工具应返回拒绝串,实得 {tool_results}"
    # 关键:被拒 → 没有副作用,文件不该存在
    assert not (tmp_path / "a.txt").exists()


@pytest.mark.asyncio
async def test_disconnect_after_session_frame_releases_run_active(monkeypatch, _reset_server_state):
    """客户端在 session→start 窗口断开:GeneratorExit 从首帧 yield 抛出,_RUN_ACTIVE 必须
    被 finally 释放,否则全局单飞标志永久泄漏、死锁后续所有 run。"""
    monkeypatch.setattr(server, "build_agent_with_gate", lambda **kw: (_FakeAgent(), None))
    assert server._RUN_ACTIVE is False
    gen = server._run_stream("写个文件")
    first = await gen.__anext__()  # session 帧
    assert "session" in first
    assert server._RUN_ACTIVE is True  # 已进入一轮
    await gen.aclose()  # 模拟客户端在收到 session 后立即断开
    assert server._RUN_ACTIVE is False, "断开后 _RUN_ACTIVE 必须释放"


def test_approve_unknown_session_returns_404():
    client = TestClient(server.app)
    r = client.post("/run/does-not-exist/approve",
                    json={"call_id": "x", "decision": "approve"})
    assert r.status_code == 404


def test_approve_bad_decision_returns_400():
    st = server.SessionState(session_id="sess1")
    server.SESSIONS["sess1"] = st
    try:
        client = TestClient(server.app)
        r = client.post("/run/sess1/approve",
                        json={"call_id": "x", "decision": "maybe"})
        assert r.status_code == 400
    finally:
        server.SESSIONS.pop("sess1", None)
