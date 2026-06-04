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
    def spawn(self, *, workspace, namespace): pass
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
