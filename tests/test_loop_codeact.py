"""Phase 3:AgentLoop CodeAct 主循环(FakeModel+FakeSandbox)。
抽代码块→exec→回灌→投事件;阶段门 plan→act→verify→report 不可跳。"""
from __future__ import annotations

import pytest

from argos_agent.core.loop import AgentLoop, LoopConfig, extract_code_block
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import (
    CodeAction, CodeResult, PhaseChange, TokenDelta, VerifyVerdict,
)


def test_extract_code_block():
    txt = "先想想\n```python\nx = read_file('a.txt')\nprint(x)\n```\n结束"
    assert extract_code_block(txt) == "x = read_file('a.txt')\nprint(x)"
    assert extract_code_block("没有代码块") is None


class FakeModel:
    """按脚本逐 run 出 text。每次 stream 返回脚本的下一段。"""
    def __init__(self, scripts: list[str]):
        self._scripts = scripts
        self._i = 0

    async def stream(self, messages, *, system):
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class FakeSandbox:
    def __init__(self):
        self.spawned = False
        self.codes: list[str] = []
    def spawn(self, *, workspace, namespace):
        self.spawned = True
    def exec_code(self, code):
        self.codes.append(code)
        return ExecResult(stdout="ran ok", value_repr="", exc="")
    def close(self):
        pass


class FakeVerifier:
    """契约 §9 锁#1 canonical 签名: verify(verify_cmd, *, attempts=1) -> Verdict"""
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


class FakeStore:
    def __init__(self):
        self.events = []
    def append_event(self, sid, ev):
        self.events.append(ev)
    def append_message(self, sid, *, role, content, tool_calls_json="", token_count=0):
        return "m0"


def _loop(scripts, verify_cmd=None):
    from argos_agent.tui.events import EventBus
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=5),
    )


@pytest.mark.asyncio
async def test_loop_runs_code_and_emits_events():
    # 第一段含代码块,第二段宣布完成(无代码块)。
    scripts = [
        "我来读文件\n```python\nwrite_file('a.txt','hi')\n```",
        "完成了。",
    ]
    loop = _loop(scripts)
    kinds = []
    async for ev in loop.run("写个文件", "sess1"):
        kinds.append(ev.kind)
    # 必含:phase_change(plan/act/.../report) + code_action + code_result
    assert "code_action" in kinds
    assert "code_result" in kinds
    assert "phase_change" in kinds


@pytest.mark.asyncio
async def test_phases_in_order_and_complete():
    scripts = ["```python\nwrite_file('a.txt','x')\n```", "完成。"]
    loop = _loop(scripts)
    phases = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)
    # 四阶段不可跳:plan 必在 act 之前,report 必在最后。
    assert phases[0] == "plan"
    assert "act" in phases
    assert phases[-1] == "report"
    assert phases.index("plan") < phases.index("act") < phases.index("report")


@pytest.mark.asyncio
async def test_verify_phase_emitted_before_verdict():
    """W1: PhaseChange("verify") 必须在 VerifyVerdict 之前。"""
    scripts = ["```python\nx=1\n```", "完成。"]
    loop = _loop(scripts, verify_cmd="echo ok")
    events = []
    async for ev in loop.run("g", "s"):
        events.append(ev)
    phase_changes = [e for e in events if isinstance(e, PhaseChange)]
    verdicts = [e for e in events if isinstance(e, VerifyVerdict)]
    verify_phase_idx = next(
        (i for i, e in enumerate(events) if isinstance(e, PhaseChange) and e.phase == "verify"), None
    )
    verdict_idx = next(
        (i for i, e in enumerate(events) if isinstance(e, VerifyVerdict)), None
    )
    # VerifyVerdict 存在时,PhaseChange("verify") 必须在它之前。
    if verdicts:
        assert verify_phase_idx is not None, "缺 PhaseChange('verify')"
        assert verify_phase_idx < verdict_idx, "PhaseChange('verify') 必须在 VerifyVerdict 之前(W1)"


# ── 反馈接线回归(本轮修复:真模式"回车像没反应"根因)────────────────────────────


class _FakeModelWithUsage(FakeModel):
    """带真 token 用量的 FakeModel —— 模拟 ModelClient.stream 抓到的 last_usage。"""
    def __init__(self, scripts):
        super().__init__(scripts)
        self.last_usage = {"input_tokens": 100, "output_tokens": 50}


class _RealisticVerifier:
    """镜像真 Verifier 的无测契约:verify_cmd is None → unverifiable(无机检命令真跑过,
    绝不当 passed);配了 cmd → passed。让 is_honest_completion 在无测任务上正确触发。"""
    def verify(self, verify_cmd, *, attempts=1):
        if verify_cmd is None:
            return Verdict.unverifiable(detail="(无 verify_cmd,未做机检验证)", tampered=[], attempts=attempts)
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


def _loop_with(model, verify_cmd=None, verifier=None):
    from argos_agent.tui.events import EventBus
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=verifier or _RealisticVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=5),
    )


@pytest.mark.asyncio
async def test_loop_emits_costupdate_with_real_tokens_and_elapsed():
    """回归:真 loop 每步发 CostUpdate(真 token 累计 + 真 elapsed)。否则状态栏/成本表死值 0,
    用户以为'没反应'。FakeLoop 之外此前从不发 CostUpdate(本轮修复点)。"""
    from argos_agent.tui.events import CostUpdate
    model = _FakeModelWithUsage(["```python\nx=1\n```", "完成。"])
    loop = _loop_with(model)
    costs = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, CostUpdate):
            costs.append(ev)
    assert costs, "真 loop 必须发 CostUpdate(否则状态栏永久 0)"
    last = costs[-1]
    # 两次模型调用(code 步 + 完成步)累计:out=50×2=100, in=100×2=200。
    assert last.tokens_out >= 50, "应累计真实 output token"
    assert last.tokens_in >= 100, "应累计真实 input token"
    assert last.elapsed_s >= 0.0, "elapsed 必须是真实计时(让 ⏱ 走起来)"
    assert last.cost_usd is None, "无单价表时诚实置 None(UI 显 $(N/A)),不编造成本"


@pytest.mark.asyncio
async def test_loop_emits_visible_completion_line_no_test():
    """回归:无 verify_cmd 的诚实完成必须在 transcript 可见(此前只写进 DB,UI 一片空白)。"""
    model = FakeModel(["```python\nx=1\n```", "完成。"])
    loop = _loop_with(model, verify_cmd=None)
    texts = [ev.text for ev in [e async for e in loop.run("g", "s")]
             if isinstance(ev, TokenDelta)]
    assert texts, "应有 TokenDelta"
    assert "完成" in texts[-1], "末尾应有可见完成行"
    assert "未机检验证" in texts[-1], "无测任务应诚实标注未机检验证"


@pytest.mark.asyncio
async def test_loop_completion_line_says_verified_when_passed():
    """配了 verify_cmd 且通过 → 可见完成行说'验证通过'。"""
    model = FakeModel(["```python\nx=1\n```", "完成。"])
    loop = _loop_with(model, verify_cmd="echo ok")
    texts = [ev.text for ev in [e async for e in loop.run("g", "s")]
             if isinstance(ev, TokenDelta)]
    assert texts and "验证通过" in texts[-1], "通过的任务完成行应明示验证通过"


def test_codeact_contract_in_honesty_system():
    """回归:HONESTY_SYSTEM 必须含明确 CodeAct 契约(强制 ```python 围栏 + 禁 JSON 工具调用)。
    实测:缺这段时 MiniMax-M3 吐 JSON 工具调用 → extract_code_block 抽不到 → agent 对编码任务恒为 no-op。"""
    from argos_agent.core.honesty import HONESTY_SYSTEM
    assert "```python" in HONESTY_SYSTEM, "必须给出 ```python 围栏示例/要求"
    assert "JSON" in HONESTY_SYSTEM and "不会被执行" in HONESTY_SYSTEM, "必须明确禁止 JSON 工具调用"
    assert "write_file(path, content)" in HONESTY_SYSTEM, "应文档化工具的 Python 函数签名"
