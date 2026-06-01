"""verify 硬门禁的纯逻辑测试 —— 守住核心护城河(不调模型)。

测谎仪自己必须有测试守着。覆盖:验证执行的退出码裁决、防作弊隔离、最终答案判定。
agent loop 级的端到端(bounce/escalate)已用命令行实测过(慢、调模型),这里固化不依赖
模型的关键逻辑,防回归。
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from argos_agent import tools, verify_gate
from argos_agent.verify_gate import (
    VerifyGateMiddleware,
    _is_final_answer,
    _run_verify,
)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    vd = tmp_path / "verify"
    ws.mkdir()
    vd.mkdir()
    for mod in (tools, verify_gate):
        monkeypatch.setattr(mod, "WORKSPACE", ws, raising=False)
        monkeypatch.setattr(mod, "VERIFY_DIR", vd, raising=False)
    return ws, vd


# ── _run_verify:退出码裁决 ───────────────────────────────────────────────────
def test_verify_pass_on_exit_zero(sandbox):
    ws, vd = sandbox
    (ws / "sol.py").write_text("ok = True\n")
    (vd / "check.py").write_text("import sol\nassert sol.ok\nprint('PASS')\n")
    ok, detail = _run_verify("python3 check.py")
    assert ok is True
    assert "exit_code=0" in detail


def test_verify_fail_on_nonzero(sandbox):
    _, vd = sandbox
    (vd / "check.py").write_text("raise SystemExit(1)\n")
    ok, detail = _run_verify("python3 check.py")
    assert ok is False
    assert "exit_code=1" in detail


def test_verify_command_must_be_whitelisted(sandbox):
    ok, detail = _run_verify("curl http://evil.com")
    assert ok is False
    assert "白名单" in detail


# ── 防作弊隔离:agent 改不到评判它的测试 ──────────────────────────────────────
def test_agent_cannot_tamper_verify_file(sandbox):
    """验证物在 VERIFY_DIR,agent 的 write/edit 工具(限定 WORKSPACE)够不到。
    这是堵住"测谎仪被嫌疑人贿赂"漏洞的关键边界。"""
    ws, vd = sandbox
    (vd / "check.py").write_text("raise SystemExit(1)\n")  # 永远失败的测试
    # agent 试图把验证文件改成 pass 来作弊 —— 用它的 write_file 工具(限定 WORKSPACE)。
    # 不管它写什么路径,都落在 WORKSPACE 里,改不到 VERIFY_DIR 的 check.py。
    tools.write_file.invoke({"path": "check.py", "content": "pass"})
    # 隔离区的测试仍是原样、仍失败。
    assert "raise SystemExit(1)" in (vd / "check.py").read_text()
    ok, _ = _run_verify("python3 check.py")
    assert ok is False  # 作弊未遂,验证仍失败


# ── 最终答案判定:决定门禁何时介入 ───────────────────────────────────────────
def test_is_final_answer_true_for_plain_ai_message():
    assert _is_final_answer(AIMessage(content="完成")) is True


def test_is_final_answer_false_when_tool_calls():
    m = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {}, "id": "1"}])
    assert _is_final_answer(m) is False


def test_is_final_answer_false_for_non_ai():
    assert _is_final_answer(HumanMessage(content="x")) is False
    assert _is_final_answer(ToolMessage(content="x", tool_call_id="1")) is False


# ── 门禁状态:无 verify_cmd 时不拦截 ─────────────────────────────────────────
def test_gate_passthrough_without_verify_cmd():
    gate = VerifyGateMiddleware(verify_cmd=None)
    called = {"n": 0}

    def handler(req):
        called["n"] += 1
        return "resp"

    assert gate.wrap_model_call("req", handler) == "resp"
    assert called["n"] == 1  # 直接透传,只调一次
    assert gate.escalated is False
