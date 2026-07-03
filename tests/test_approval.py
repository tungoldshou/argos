"""Internal documentation."""
import asyncio
import pytest

from argos import approval


@pytest.mark.asyncio
async def test_request_approval_blocks_then_resolves():
    gate = approval.ApprovalGate()
    action = "write_file"
    args = {"path": "x.py"}

    request_task = asyncio.create_task(
        gate.request(action, args, description="写入文件 x.py", risk="low", timeout=0.5)
    )
    await asyncio.sleep(0)

    pending = gate.pending()
    assert len(pending) == 1
    call_id = pending[0].call_id

    gate.respond(call_id, "once")
    result = await request_task
    assert result == approval.Decision(kind="once")


@pytest.mark.asyncio
async def test_always_persists_pattern_allow_rule(tmp_path, monkeypatch):
    """Internal documentation."""
    import argos.permissions.config as pcfg
    pj = tmp_path / "permissions.json"
    monkeypatch.setattr(pcfg, "CONFIG_PATH", pj)
    monkeypatch.setattr(pcfg, "_config", None, raising=False)

    gate = approval.ApprovalGate()
    task = asyncio.create_task(
        gate.request("run_command", {"command": "pytest -q"},
                     description="跑测试", risk="medium", timeout=0.5)
    )
    await asyncio.sleep(0)
    cid = gate.pending()[0].call_id
    assert gate.respond(cid, "always") is True
    await task

    import json
    data = json.loads(pj.read_text(encoding="utf-8"))
    assert any(e.get("tool") == "run_command" and "pytest" in e.get("matcher", "")
               for e in data.get("allow", [])), data

    from argos.permissions.evaluator import evaluate
    cfg = pcfg.load(pj)
    assert evaluate("run_command", {"command": "pytest tests/x.py"},
                    gate_level="confirm", config=cfg, risk="medium").decision == "approve"
    assert evaluate("run_command", {"command": "git status"},
                    gate_level="confirm", config=cfg, risk="medium").decision == "ask"
    pcfg.save_allow_rule("run_command", "rm", path=pj)
    cfg2 = pcfg.load(pj)
    assert evaluate("run_command", {"command": "rm -rf /"},
                    gate_level="confirm", config=cfg2, risk="medium").decision == "deny"


@pytest.mark.asyncio
async def test_ask_listener_fires_for_tool_ask_only():
    """Internal documentation."""
    gate = approval.ApprovalGate()
    seen: list = []
    gate.set_ask_listener(lambda cid, payload: seen.append((cid, payload)))

    task = asyncio.create_task(
        gate.request("write_file", {"path": "x.py"}, description="写文件", risk="low", timeout=0.5)
    )
    await asyncio.sleep(0)
    assert len(seen) == 1, "工具 ask 应触发 ask_listener(让 TUI mount 卡)"
    cid, payload = seen[0]
    assert payload["action"] == "write_file" and payload["args"] == {"path": "x.py"}
    assert cid == gate.pending()[0].call_id
    gate.respond(cid, "once")
    await task

    seen.clear()
    task2 = asyncio.create_task(
        gate.request("write_file", {"path": "y.py"}, description="写文件", risk="low",
                     timeout=0.5, call_id="precid000001")
    )
    await asyncio.sleep(0)
    assert seen == [], "调用方预传 call_id 的 ask 不应触发带外回调(避免和 loop 自投事件重复)"
    gate.respond("precid000001", "once")
    await task2


@pytest.mark.asyncio
async def test_deny_returns_false():
    gate = approval.ApprovalGate()
    request_task = asyncio.create_task(
        gate.request("x", {}, description="x", risk="low", timeout=0.5)
    )
    await asyncio.sleep(0)
    call_id = gate.pending()[0].call_id
    gate.respond(call_id, "deny")
    result = await request_task
    assert result.approved is False


@pytest.mark.asyncio
async def test_timeout_defaults_to_deny():
    gate = approval.ApprovalGate()
    result = await gate.request("x", {}, description="x", risk="low", timeout=0.05)
    assert result.approved is False
    assert "超时" in result.reason


@pytest.mark.asyncio
async def test_session_scope_caches_approval():
    gate = approval.ApprovalGate()
    action = "write_file"
    args = {"path": "x.py"}
    request_task = asyncio.create_task(
        gate.request(action, args, description="写入文件 x.py", risk="low", timeout=0.5)
    )
    await asyncio.sleep(0)
    call_id = gate.pending()[0].call_id
    gate.respond(call_id, "session")
    await request_task

    result = await gate.request(action, args, description="写入文件 x.py", risk="low", timeout=0.5)
    assert result.approved is True
    assert result.kind == "session"


def test_requires_approval_decorator_marks_metadata():
    @approval.requires_approval(description="写入文件 {path}", risk="low")
    def write_file(path: str, content: str) -> str:
        """Internal documentation."""
        return f"wrote {path}"

    assert write_file._approval_required is True
    assert write_file._approval_description == "写入文件 {path}"
    assert write_file._approval_risk == "low"
    assert "默认拒绝" in write_file("a.txt", "x")


def test_decorator_runs_original_when_gate_approves():
    """Internal documentation."""
    @approval.requires_approval(description="写入文件 {path}", risk="low")
    def write_file(path: str, content: str) -> str:
        """Internal documentation."""
        return f"wrote {path}"

    gate = approval.ApprovalGate()

    async def _auto(action, args, *, description, risk, timeout=60.0):
        return approval.Decision(kind="once")

    gate.request = _auto  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        assert write_file("a.txt", "x") == "wrote a.txt"
    finally:
        approval.reset_current_gate(token)


def test_approve_unknown_call_id_is_noop():
    gate = approval.ApprovalGate()
    # respond with deny is the new unified API; also test backward-compat approve/deny
    assert gate.respond("nonexistent", "deny") is False
    assert gate.approve("nonexistent") is False
    assert gate.deny("nonexistent") is False


@pytest.mark.asyncio
async def test_cancel_all_denies_pending():
    gate = approval.ApprovalGate()
    t1 = asyncio.create_task(gate.request("a", {}, description="a", risk="low", timeout=5.0))
    t2 = asyncio.create_task(gate.request("b", {}, description="b", risk="low", timeout=5.0))
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
        """My tool description."""
        return a

    assert my_tool.__name__ == "my_tool"
    assert "My tool description." in (my_tool.__doc__ or "")


def test_decorator_wraps_async_function():
    @approval.requires_approval(description="async 工具", risk="low")
    async def my_async_tool(x: int) -> str:
        return f"ok-{x}"

    import inspect
    assert inspect.iscoroutinefunction(my_async_tool)
    assert getattr(my_async_tool, "_approval_required", False) is True
    assert getattr(my_async_tool, "_approval_description", None) == "async 工具"


@pytest.mark.asyncio
async def test_guarded_call_fail_closed_without_gate():
    ran = {"v": False}
    async def run():
        ran["v"] = True
        return "ok"
    out = await approval.guarded_call("x", {}, run, description="x", risk="low")
    assert "默认拒绝" in out
    assert ran["v"] is False


@pytest.mark.asyncio
async def test_guarded_call_runs_when_approved():
    gate = approval.ApprovalGate()
    async def _auto(action, args, *, description, risk, timeout=60.0):
        return approval.Decision(kind="once")
    gate.request = _auto  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        out = await approval.guarded_call("x", {}, lambda: _say_hi(), description="x", risk="low")
        assert out == "hi"
    finally:
        approval.reset_current_gate(token)


async def _say_hi():
    return "hi"


@pytest.mark.asyncio
async def test_guarded_call_returns_refusal_when_denied():
    gate = approval.ApprovalGate()
    async def _deny(action, args, *, description, risk, timeout=60.0):
        return approval.Decision(kind="deny", reason="太危险")
    gate.request = _deny  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        out = await approval.guarded_call("x", {}, lambda: _say_hi(), description="x", risk="low")
        assert "用户拒绝" in out and "太危险" in out
    finally:
        approval.reset_current_gate(token)


@pytest.mark.asyncio
async def test_gate_pending_respond_same_loop_wakeup():
    """Internal documentation."""
    gate = approval.ApprovalGate()
    token = approval.set_current_gate(gate)
    try:
        task = asyncio.create_task(
            approval.guarded_call("write", {"path": "a.py"}, lambda: _say_hi(),
                                  description="写入 a.py", risk="low")
        )
        for _ in range(500):
            await asyncio.sleep(0.01)
            if gate.pending():
                break
        assert gate.pending(), "工具应已挂起等待审批"
        assert gate.respond(gate.pending()[0].call_id, "once") is True
        result = await asyncio.wait_for(task, timeout=5.0)
        assert result == "hi"
        assert gate.pending() == []
    finally:
        approval.reset_current_gate(token)
