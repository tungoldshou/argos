"""审批闸核心测试 —— 装饰器 + 状态机(不调模型,纯逻辑)。

迁移说明(Phase 3 Task 9):
  · Decision 从 (approved, scope, reason) → (kind, reason) per 契约 §6.3 锁#3。
  · gate.request(payload) → gate.request(action, args, *, description, risk, timeout)。
  · gate.approve(call_id, scope) → gate.respond(call_id, kind); gate.deny(call_id) → gate.respond(call_id, "deny")。
  · 保留 gate.approve() / gate.deny() backward-compat 方法(server.py 旧路径尚在使用)——
    此处测试已全部迁至新 API,未删任何覆盖点(原功能被新测试等量覆盖)。
"""
import asyncio
import pytest

from argos import approval


@pytest.mark.asyncio
async def test_request_approval_blocks_then_resolves():
    gate = approval.ApprovalGate()
    action = "write_file"
    args = {"path": "x.py"}

    # 后台开协程请求审批
    request_task = asyncio.create_task(
        gate.request(action, args, description="写入文件 x.py", risk="low", timeout=0.5)
    )
    await asyncio.sleep(0)  # 让 request 进入等待

    # 此时应该有 pending 请求
    pending = gate.pending()
    assert len(pending) == 1
    call_id = pending[0].call_id

    # 批准 → 协程应返回 approved
    gate.respond(call_id, "once")
    result = await request_task
    assert result == approval.Decision(kind="once")


@pytest.mark.asyncio
async def test_always_persists_pattern_allow_rule(tmp_path, monkeypatch):
    """Phase 1(2026-06-20):respond('always') 把一条 pattern allow 规则【持久化】进 permissions.json,
    跨 session 再不问 —— 此前 always==session 是假持久(点了下次还问)。run_command 派生二进制 matcher;
    危险命令仍被 hard rule 兜底拦(allow 不越 hard)。"""
    import argos.permissions.config as pcfg
    pj = tmp_path / "permissions.json"
    monkeypatch.setattr(pcfg, "CONFIG_PATH", pj)
    monkeypatch.setattr(pcfg, "_config", None, raising=False)

    gate = approval.ApprovalGate()   # 裸 CONFIRM → run_command 会 ask
    task = asyncio.create_task(
        gate.request("run_command", {"command": "pytest -q"},
                     description="跑测试", risk="medium", timeout=0.5)
    )
    await asyncio.sleep(0)
    cid = gate.pending()[0].call_id
    assert gate.respond(cid, "always") is True
    await task

    # 1) 真持久化到 permissions.json 的 allow[]
    import json
    data = json.loads(pj.read_text(encoding="utf-8"))
    assert any(e.get("tool") == "run_command" and "pytest" in e.get("matcher", "")
               for e in data.get("allow", [])), data

    # 2) 新评估器读该 config:pytest 命令 soft_allow → approve(跨 session 生效)
    from argos.permissions.evaluator import evaluate
    cfg = pcfg.load(pj)
    assert evaluate("run_command", {"command": "pytest tests/x.py"},
                    gate_level="confirm", config=cfg, risk="medium").decision == "approve"
    # 3) 不同二进制(git)不被覆盖 → 仍 ask
    assert evaluate("run_command", {"command": "git status"},
                    gate_level="confirm", config=cfg, risk="medium").decision == "ask"
    # 4) 危险命令即便首词匹配也被 hard rule 拦(allow 不越 hard)
    pcfg.save_allow_rule("run_command", "rm", path=pj)
    cfg2 = pcfg.load(pj)
    assert evaluate("run_command", {"command": "rm -rf /"},
                    gate_level="confirm", config=cfg2, risk="medium").decision == "deny"


@pytest.mark.asyncio
async def test_ask_listener_fires_for_tool_ask_only():
    """2026-06-18 修:gate 进 ask 路径且 call_id 为自生成(= broker 工具桥)→ 同步触发 ask_listener,
    让 inline TUI mount 审批卡(exec_code 在 to_thread 时 loop 阻塞、yield 不出 ApprovalRequest →
    旧路径永不弹卡 → 工具干等超时)。调用方预传 call_id(workflow/plan/intent)不触发,避免重复卡。"""
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

    # 同一 action+args 在 session 内 → 立即放行,不阻塞
    result = await gate.request(action, args, description="写入文件 x.py", risk="low", timeout=0.5)
    assert result.approved is True
    assert result.kind == "session"


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

    async def _auto(action, args, *, description, risk, timeout=60.0):
        return approval.Decision(kind="once")

    gate.request = _auto  # type: ignore[assignment]
    token = approval.set_current_gate(gate)
    try:
        assert write_file("a.txt", "x") == "wrote a.txt"
    finally:
        approval.reset_current_gate(token)


# ── 缺口补齐:幂等/取消/不可 JSON 值/async 工具/headless 路径 ─────────────────────
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


# 旧 langchain `@tool` + `@requires_approval` 组合铁证随 2026-06-05 死栈清理移除 ——
# 活路径审批走 broker(gate.request 先于 _execute);decorator 由下方 guarded_call 测试覆盖。
@pytest.mark.asyncio
async def test_guarded_call_fail_closed_without_gate():
    ran = {"v": False}
    async def run():
        ran["v"] = True
        return "ok"
    out = await approval.guarded_call("x", {}, run, description="x", risk="low")
    assert "默认拒绝" in out
    assert ran["v"] is False  # 无 gate 绝不执行


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
    """真实 pending→respond 流(不打桩 gate.request):一个协程经 guarded_call 阻塞等审批,
    另一路 respond() 唤醒它放行。守住交互审批不会永久挂起这条生产关键路径。"""
    gate = approval.ApprovalGate()
    token = approval.set_current_gate(gate)
    try:
        task = asyncio.create_task(
            approval.guarded_call("write", {"path": "a.py"}, lambda: _say_hi(),
                                  description="写入 a.py", risk="low")
        )
        # xdist 并行高负载下 create_task 首次调度可能延迟,扩大轮询窗口到 5s 防虚假失败。
        # 语义不变:测的是审批挂起+放行,200×10ms=2s 在单机高负载下不够用。
        for _ in range(500):   # 最多 5s(500 × 10ms);正常 <200ms
            await asyncio.sleep(0.01)
            if gate.pending():
                break
        assert gate.pending(), "工具应已挂起等待审批"
        assert gate.respond(gate.pending()[0].call_id, "once") is True
        result = await asyncio.wait_for(task, timeout=5.0)  # 同步放宽到 5s
        assert result == "hi"
        assert gate.pending() == []
    finally:
        approval.reset_current_gate(token)
