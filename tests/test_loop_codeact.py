"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig, extract_code_block
from argos.core.verify_gate import Verdict
from argos.sandbox.backend import ExecResult
from argos.tui.events import (
    CodeAction, CodeResult, PhaseChange, TokenDelta, VerifyVerdict,
)


def test_extract_code_block():
    txt = "先想想\n```python\nx = read_file('a.txt')\nprint(x)\n```\n结束"
    assert extract_code_block(txt) == "x = read_file('a.txt')\nprint(x)"
    terminal_log = "故事里有一段日志\n```\nremote: hooks/pre-receive: line 1: Killed\n```\n结束"
    assert extract_code_block(terminal_log) is None
    assert extract_code_block("没有代码块") is None


class FakeModel:
    """Internal documentation."""
    def __init__(self, scripts: list[str]):
        self._scripts = scripts
        self._i = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        text = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        for ch in text:
            yield ch


class FakeSandbox:
    def __init__(self):
        self.spawned = False
        self.codes: list[str] = []
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False):
        self.spawned = True
    def exec_code(self, code):
        self.codes.append(code)
        return ExecResult(stdout="ran ok", value_repr="", exc="")
    def close(self):
        pass


class FakeVerifier:
    """Internal documentation."""
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
    from argos.tui.events import EventBus
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=FakeModel(scripts), verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=5),
    )


@pytest.mark.asyncio
async def test_loop_runs_code_and_emits_events():
    scripts = [
        "我来读文件\n```python\nwrite_file('a.txt','hi')\n```",
        "完成了。",
    ]
    loop = _loop(scripts)
    kinds = []
    async for ev in loop.run("写个文件", "sess1"):
        kinds.append(ev.kind)
    assert "code_action" in kinds
    assert "code_result" in kinds
    assert "phase_change" in kinds


@pytest.mark.asyncio
async def test_loop_ignores_non_python_markdown_fences():
    scripts = [
        "这是纯对话里的日志:\n```\nremote: hooks/pre-receive: line 1: Killed\n```",
    ]
    loop = _loop(scripts)
    events = []
    async for ev in loop.run("讲个故事", "sess1"):
        events.append(ev)
    assert not any(isinstance(ev, CodeAction) for ev in events)
    assert loop._sandbox.codes == []


@pytest.mark.asyncio
async def test_loop_waits_when_reply_asks_confirmation_before_code_action():
    text = (
        "允许我跑 web_search / web_extract 吗？确认了的话我就开干。\n"
        "```python\n"
        "result = web_search('Claude Code skill 65% token reduction trending github')\n"
        "print(result)\n"
        "```"
    )
    model = FakeModel([text, "SHOULD NOT BE CALLED"])
    loop = _loop_with(model)
    events = [ev async for ev in loop.run("你抓了吗？", "sess1")]
    assert not any(isinstance(ev, CodeAction) for ev in events)
    assert not any(isinstance(ev, CodeResult) for ev in events)
    assert loop._sandbox.codes == []
    assert model._i == 1


@pytest.mark.asyncio
async def test_phases_in_order_and_complete():
    scripts = ["```python\nwrite_file('a.txt','x')\n```", "完成。"]
    loop = _loop(scripts)
    phases = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)
    assert phases[0] == "plan"
    assert "act" in phases
    assert phases[-1] == "report"
    assert phases.index("plan") < phases.index("act") < phases.index("report")


@pytest.mark.asyncio
async def test_verify_phase_emitted_before_verdict():
    """Internal documentation."""
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
    if verdicts:
        assert verify_phase_idx is not None, "缺 PhaseChange('verify')"
        assert verify_phase_idx < verdict_idx, "PhaseChange('verify') 必须在 VerifyVerdict 之前(W1)"




@pytest.mark.asyncio
async def test_conversational_turn_skips_verify_ceremony():
    """Internal documentation."""
    loop = _loop(["你好！我是 Argos，有什么可以帮你的？"])
    events = []
    async for ev in loop.run("你好", "s"):
        events.append(ev)
    assert not [e for e in events if isinstance(e, VerifyVerdict)], "对话轮不该投验证判决"
    tokens = "".join(e.text for e in events if isinstance(e, TokenDelta))
    assert "未机检验证" not in tokens, f"对话轮不该显示未机检验证完成行,实际:{tokens!r}"
    assert "本轮结束" not in tokens, f"对话轮不该显示任务完成行,实际:{tokens!r}"
    phases = [e.phase for e in events if isinstance(e, PhaseChange)]
    assert phases[0] == "plan" and phases[-1] == "report"


@pytest.mark.asyncio
async def test_engineering_turn_still_runs_verify_gate():
    """Internal documentation."""
    scripts = ["```python\nwrite_file('a.txt','hi')\n```", "完成了。"]
    loop = _loop(scripts)
    events = []
    async for ev in loop.run("写个文件", "s"):
        events.append(ev)
    assert [e for e in events if isinstance(e, VerifyVerdict)], "工程改动必须投验证判决(护城河)"


@pytest.mark.asyncio
async def test_explicit_verify_cmd_turn_runs_gate_even_without_changes():
    """Internal documentation."""
    loop = _loop(["我看看就好。"], verify_cmd="echo ok")
    events = []
    async for ev in loop.run("检查一下", "s"):
        events.append(ev)
    assert [e for e in events if isinstance(e, VerifyVerdict)], "声明了 verify_cmd 必须投判决"




class _FakeModelWithUsage(FakeModel):
    """Internal documentation."""
    def __init__(self, scripts):
        super().__init__(scripts)
        self.last_usage = {"input_tokens": 100, "output_tokens": 50}


class _RealisticVerifier:
    """Internal documentation."""
    def verify(self, verify_cmd, *, attempts=1):
        if verify_cmd is None:
            return Verdict.unverifiable(detail="(无 verify_cmd,未做机检验证)", tampered=[], attempts=attempts)
        return Verdict.passed(detail="[exit_code=0]", verify_cmd=verify_cmd, attempts=attempts)


def _loop_with(model, verify_cmd=None, verifier=None):
    from argos.tui.events import EventBus
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=verifier or _RealisticVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=5),
    )


@pytest.mark.asyncio
async def test_loop_emits_costupdate_with_real_tokens_and_elapsed():
    """Internal documentation."""
    from argos.tui.events import CostUpdate
    model = _FakeModelWithUsage(["```python\nx=1\n```", "完成。"])
    loop = _loop_with(model)
    costs = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, CostUpdate):
            costs.append(ev)
    assert costs, "真 loop 必须发 CostUpdate(否则状态栏永久 0)"
    last = costs[-1]
    assert last.tokens_out >= 50, "应累计真实 output token"
    assert last.tokens_in >= 100, "应累计真实 input token"
    assert last.elapsed_s >= 0.0, "elapsed 必须是真实计时(让 ⏱ 走起来)"
    assert last.cost_usd is None, "无单价表时诚实置 None(UI 显 $(N/A)),不编造成本"
    assert last.context_used >= 100, "应带当前窗口占用(输入侧 token,供上下文用量条)"


@pytest.mark.asyncio
async def test_loop_estimates_context_when_provider_omits_usage():
    """Internal documentation."""
    from argos.tui.events import CostUpdate

    model = FakeModel(["```python\nx=1\n```", "完成。"])
    model.last_usage = {}
    loop = _loop_with(model)

    costs = []
    async for ev in loop.run("检查 context", "s"):
        if isinstance(ev, CostUpdate):
            costs.append(ev)

    assert costs
    assert costs[-1].context_used > 0


class _FakeModelWithTier(_FakeModelWithUsage):
    """Internal documentation."""
    def __init__(self, scripts, model_name):
        super().__init__(scripts)
        self.tier = type("_T", (), {"model": model_name})()


@pytest.mark.asyncio
async def test_cost_computed_for_known_pricing_model():
    """Internal documentation."""
    from argos.tui.events import CostUpdate
    model = _FakeModelWithTier(["```python\nx=1\n```", "完成。"], "MiniMax-M2")
    loop = _loop_with(model)
    costs = [ev for ev in [e async for e in loop.run("g", "s")] if isinstance(ev, CostUpdate)]
    assert costs and costs[-1].cost_usd is not None and costs[-1].cost_usd > 0,\
        "已知定价模型应算出真实正成本(token>0),而非恒 None"


@pytest.mark.asyncio
async def test_cost_none_for_unknown_model_not_fake_zero():
    """Internal documentation."""
    from argos.tui.events import CostUpdate
    model = _FakeModelWithTier(["```python\nx=1\n```", "完成。"], "No-Such-Model-9000")
    loop = _loop_with(model)
    costs = [ev for ev in [e async for e in loop.run("g", "s")] if isinstance(ev, CostUpdate)]
    assert costs and all(ev.cost_usd is None for ev in costs),\
        "未知模型单价 → 全程 None,绝不显假 $0.000"


@pytest.mark.asyncio
async def test_loop_emits_visible_completion_line_no_test():
    """Internal documentation."""
    model = FakeModel(["```python\nwrite_file('a.txt','x')\n```", "完成。"])
    loop = _loop_with(model, verify_cmd=None)
    texts = [ev.text for ev in [e async for e in loop.run("g", "s")]
             if isinstance(ev, TokenDelta)]
    from argos.i18n import t as _t
    assert texts, "应有 TokenDelta"
    assert _t("loop.report_note.no_test") in texts[-1], "末尾应有可见完成行含无测标注"
    # legacy zh assertion (also covered via _t lookup above)
    assert "no test command" in texts[-1], "末尾应诚实标注 no test command"


@pytest.mark.asyncio
async def test_loop_completion_line_says_verified_when_passed():
    """Internal documentation."""
    model = FakeModel(["```python\nx=1\n```", "完成。"])
    loop = _loop_with(model, verify_cmd="echo ok")
    texts = [ev.text for ev in [e async for e in loop.run("g", "s")]
             if isinstance(ev, TokenDelta)]
    from argos.i18n import t as _t
    assert texts and _t("loop.done.verified") in "".join(texts), "通过的任务完成行应含验证通过标注"


def test_codeact_contract_in_honesty_system():
    """Internal documentation."""
    from argos.core.honesty import HONESTY_SYSTEM
    assert "```python" in HONESTY_SYSTEM, "必须给出 ```python 围栏示例/要求"
    assert "JSON" in HONESTY_SYSTEM and "never as JSON" in HONESTY_SYSTEM, "必须明确禁止 JSON 工具调用"
    assert "Wrong (never runs)" in HONESTY_SYSTEM, "必须含 JSON 反例(never runs)"
    assert "write_file(path, content)" in HONESTY_SYSTEM, "应文档化工具的 Python 函数签名"


@pytest.mark.asyncio
async def test_no_action_bounces_not_completes():
    """Internal documentation."""
    model = FakeModel(["我来修这几处。", "```python\nwrite_file('a','b')\n```", "完成。"])
    loop = _loop_with(model, verify_cmd=None)
    actions = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, CodeAction):
            actions.append(ev)
    assert len(actions) >= 1, "应在第二段真执行代码,而非首段纯文字就收尾"


@pytest.mark.asyncio
async def test_no_action_nudges_research_promise_not_three_turns():
    """Internal documentation."""
    model = FakeModel([
        "好，我们看一下今天 trending 列表里那个 Claude Code skill 的详情，定位到仓库读 README。",
        "```python\nprint(web_search('Claude Code skill 65% token reduction trending github'))\n```",
        "完成。",
    ])
    loop = _loop_with(model, verify_cmd=None)
    events = [ev async for ev in loop.run("节省token那个skill的具体实现看看", "s")]
    assert any(isinstance(ev, CodeAction) for ev in events)
    assert loop._sandbox.codes == [
        "print(web_search('Claude Code skill 65% token reduction trending github'))"
    ]
    assert model._i >= 2


@pytest.mark.asyncio
async def test_conversational_reply_completes_without_nudge():
    """Internal documentation."""
    from argos.tui.events import EventBus

    class _HonestVerifier:
        def verify(self, vc, *, attempts=1):
            if vc is None:
                return Verdict.unverifiable(detail="(no test command)", tampered=[], attempts=attempts)
            return Verdict.passed(detail="[exit=0]", verify_cmd=vc, attempts=attempts)

    model = FakeModel(["你好！我是 Argos，请问有什么可以帮你？"])
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=_HonestVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=5),
    )
    phases: list[str] = []
    async for ev in loop.run("你好", "s"):
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)
    assert model._i == 1, (
        f"实质对话答复应一轮收尾(不催),实际调模型 {model._i} 次"
    )
    assert "verify" in phases and phases[-1] == "report"


@pytest.mark.asyncio
async def test_conversation_does_not_infer_verify_strategy(monkeypatch):
    """Internal documentation."""
    from argos.tui.events import EventBus

    called = {"n": 0}

    def _spy_pick(self, goal):
        called["n"] += 1
        return "pytest -q"

    monkeypatch.setattr(AgentLoop, "_pick_strategy_cmd", _spy_pick)

    class _HonestVerifier:
        def verify(self, vc, *, attempts=1):
            return Verdict.unverifiable(detail="(no test command)", tampered=[], attempts=attempts)

    model = FakeModel(["你好！我是 Argos，请问有什么可以帮你？"])
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=_HonestVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=5),
    )
    phases: list[str] = []
    async for ev in loop.run("你好", "s"):
        if isinstance(ev, PhaseChange):
            phases.append(ev.phase)
    assert called["n"] == 0, "对话(made_changes=False)绝不该推断 verify 策略(否则被推断 pytest→bounce)"
    assert model._i == 1, f"对话应一轮收尾,实际 {model._i} 次"
    assert phases[-1] == "report", f"对话应诚实收尾到 report(NO_TEST),实际 {phases}"


@pytest.mark.asyncio
async def test_max_steps_exhaustion_still_walks_phase_gate():
    """Internal documentation."""
    model = FakeModel(["```python\nwrite_file('a','b')\n```"])
    from argos.tui.events import EventBus
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=2),
    )
    phases: list[str] = []
    try:
        async for ev in loop.run("g", "s"):
            if isinstance(ev, PhaseChange):
                phases.append(ev.phase)
    except ValueError as e:
        pytest.fail(f"harness 阶段门在 max_steps 耗尽时炸了:{e}")
    assert "verify" in phases, f"补齐后 verify 必须被投出,实际 phases={phases}"
    assert phases[-1] == "report", f"最后一阶段必须是 report,实际 phases={phases}"
    assert phases.index("verify") < phases.index("report"),\
        f"verify 必须在 report 之前,实际 phases={phases}"


@pytest.mark.asyncio
async def test_max_steps_bailout_runs_verify_not_just_phase_change():
    """Internal documentation."""
    from argos.tui.events import EventBus
    model = FakeModel(["```python\nwrite_file('a','b')\n```"])
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd="echo ok", max_steps=2),
    )
    verdicts: list[VerifyVerdict] = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev)
    assert len(verdicts) == 1, (
        f"max_steps bailout 必须真跑一次 verify(投 1 个 VerifyVerdict),"
        f"实际 verdicts={verdicts}"
    )
    assert verdicts[0].verdict.status == "passed", (
        f"FakeVerifier 恒返 passed,bailout 后仍应得 passed,实际 status="
        f"{verdicts[0].verdict.status}"
    )


@pytest.mark.asyncio
async def test_max_steps_bailout_without_verify_cmd_honest_completion():
    """Internal documentation."""
    from argos.tui.events import EventBus
    model = FakeModel(["```python\nwrite_file('a','b')\n```"])
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=FakeVerifier(),
        config=LoopConfig(verify_cmd=None, max_steps=2),
    )
    verdicts: list[VerifyVerdict] = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, VerifyVerdict):
            verdicts.append(ev)
    assert len(verdicts) == 1, (
        f"无 verify_cmd 时 bailout 仍要投 1 个 VerifyVerdict(unverifiable),"
        f"实际 verdicts={verdicts}"
    )


# ── i18n EN locale: completion line surfaces in English ──────────────────────


@pytest.mark.asyncio
async def test_loop_completion_line_en_no_test(monkeypatch):
    """ARGOS_LANG=en: no-test completion line renders English ('unverified')."""
    monkeypatch.setenv("ARGOS_LANG", "en")
    from argos.i18n import _catalog
    _catalog.cache_clear()
    try:
        model = FakeModel(["```python\nwrite_file('a.txt','x')\n```", "Done."])
        loop = _loop_with(model, verify_cmd=None)
        texts = [ev.text for ev in [e async for e in loop.run("g", "s")]
                 if isinstance(ev, TokenDelta)]
        full = "".join(texts)
        assert "unverified" in full, f"EN no-test label should say 'unverified', got: {full[-200:]!r}"
        assert "no test command" in full, f"EN label should contain 'no test command', got: {full[-200:]!r}"
    finally:
        _catalog.cache_clear()


@pytest.mark.asyncio
async def test_loop_completion_line_en_verified(monkeypatch):
    """ARGOS_LANG=en: verified completion line renders English ('verification passed')."""
    monkeypatch.setenv("ARGOS_LANG", "en")
    from argos.i18n import _catalog
    _catalog.cache_clear()
    try:
        model = FakeModel(["```python\nx=1\n```", "Done."])
        loop = _loop_with(model, verify_cmd="echo ok")
        texts = [ev.text for ev in [e async for e in loop.run("g", "s")]
                 if isinstance(ev, TokenDelta)]
        full = "".join(texts)
        assert "verification passed" in full, (
            f"EN verified label should say 'verification passed', got: {full[-200:]!r}"
        )
    finally:
        _catalog.cache_clear()



def test_clamp_feedback_passes_short_through():
    from argos.core.loop import _clamp_feedback
    assert _clamp_feedback("hello world") == "hello world"


def test_clamp_feedback_head_tail_truncates_large():
    from argos.core.loop import _clamp_feedback, _FEEDBACK_MAX_CHARS
    big = "A" * 8000 + "B" * 8000
    out = _clamp_feedback(big)
    assert len(out) < len(big), "大输出必须被截断"
    assert out.startswith("A") and out.rstrip().endswith("B"), "首尾都应保留"
    assert "elided" in out, "应有省略标记(ASCII,无 i18n 泄漏)"
    assert len(out) <= _FEEDBACK_MAX_CHARS + 64


def test_feedback_clamps_pathological_stdout():
    from argos.core.loop import AgentLoop
    class _R:
        ok = True; stdout = "X" * 50000; value_repr = ""; exc = None
    fb = AgentLoop._feedback(_R())
    assert len(fb) < 20000, "病态大 stdout 回灌必须被截断"
    assert "elided" in fb
