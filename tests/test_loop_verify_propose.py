"""批2 Task 8:agent 在 act 阶段 propose_verify(cmd) → harness 在 verify 阶段独立跑该命令。

真验证门:agent 只能【声明】验证命令,真执行在 host 的 verify 阶段(隔离 verify_dir,退出
码为准),agent 碰不到执行 —— 防 agent 篡改评判它的测试作弊。无 propose 时维持现 NO_TEST_LABEL
诚实路径。
"""
from __future__ import annotations

import pytest

from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import EventBus, VerifyVerdict
from tests.test_loop_codeact import FakeStore  # 复用


class _ProposeSandbox:
    """exec_code 时若代码含 propose_verify(...) 模拟把 cmd 回传(经 broker_handler 风格)。"""
    def __init__(self, on_propose): self._on_propose = on_propose
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): pass
    def exec_code(self, code):
        if "propose_verify" in code:
            import re
            m = re.search(r"propose_verify\(['\"](.+?)['\"]\)", code)
            if m: self._on_propose(m.group(1))
        return ExecResult(stdout="ok", value_repr="", exc="")
    def close(self): pass


class _RecordingVerifier:
    def __init__(self): self.ran_cmd = None
    def verify(self, verify_cmd, *, attempts=1):
        self.ran_cmd = verify_cmd
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


def test_propose_verify_rejects_trivial_noop_commands():
    """H1 修复:propose_verify 拒绝 echo/true/ls/pwd/cat 等永远通过的伪验证命令(防假绿)。
    伪命令不登记 → 不产生 verdict.passed,落回"未机检验证"诚实路径;真命令(pytest)正常登记。"""
    from tests.test_loop_codeact import FakeModel
    loop = AgentLoop(store=FakeStore(), bus=EventBus(),
                     sandbox=_ProposeSandbox(lambda c: None), broker=None,
                     model=FakeModel([]), verifier=_RecordingVerifier(),
                     config=LoopConfig(verify_cmd=None))
    for fake in ["echo ok", "true", "ls", "pwd", "cat x.txt", ":", "printf hi"]:
        loop._verify_cmd = None
        loop._on_propose_verify(fake)
        assert loop._verify_cmd is None, f"{fake!r} 不该被当验证命令登记(伪验证)"
    loop._verify_cmd = None
    loop._on_propose_verify("pytest tests/test_x.py")
    assert loop._verify_cmd == "pytest tests/test_x.py"   # 真命令照常登记


@pytest.mark.asyncio
async def test_fake_verify_command_does_not_produce_false_green():
    """H1 端到端回归:模型声明 `echo ok` 当验证 → 被拒不登记 → verify 落 unverifiable(未机检验证),
    绝不报 passed 假绿。修复前 echo 在白名单、跑出 exit 0 → 会误判 passed(本测试即守此回归)。"""
    from tests.test_loop_codeact import FakeModel
    from argos_agent.core.verify_gate import Verifier   # 真 Verifier:verify_cmd=None → unverifiable
    model = FakeModel([
        "```python\npropose_verify('echo ok')\nwrite_file('x.py','x=1')\n```",
        "完成。",
    ])
    loop = AgentLoop(store=FakeStore(), bus=EventBus(), sandbox=_ProposeSandbox(lambda c: None),
                     broker=None, model=model, verifier=Verifier(), config=LoopConfig(verify_cmd=None))
    verdicts = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev.verdict)
    assert verdicts, "应有 verify 裁决"
    assert verdicts[-1].status != "passed", "echo ok 绝不得产生假绿 passed"
    assert verdicts[-1].status == "unverifiable"


@pytest.mark.asyncio
async def test_agent_proposed_cmd_is_run_by_harness():
    verifier = _RecordingVerifier()
    proposed = {}
    sandbox = _ProposeSandbox(lambda cmd: proposed.update(cmd=cmd))
    # 第一段:提议验证命令 + 写代码;第二段:完成。
    from tests.test_loop_codeact import FakeModel
    model = FakeModel([
        "```python\npropose_verify('pytest tests/test_x.py')\nwrite_file('x.py','...')\n```",
        "完成。",
    ])
    loop = AgentLoop(store=FakeStore(), bus=EventBus(), sandbox=sandbox, broker=None,
                     model=model, verifier=verifier, config=LoopConfig(verify_cmd=None))
    # loop 需暴露一个 hook 让 sandbox 把 proposed cmd 传回:见实现(broker_handler 或 namespace 回调)
    verdicts = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev.verdict)
    assert verifier.ran_cmd == "pytest tests/test_x.py", "harness 必须独立跑 agent 提议的命令"
    assert verdicts and verdicts[-1].status == "passed"
