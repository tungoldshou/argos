"""Phase 3:AgentLoop CodeAct 主循环(FakeModel+FakeSandbox)。
抽代码块→exec→回灌→投事件;阶段门 plan→act→verify→report 不可跳。"""
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
    assert extract_code_block("没有代码块") is None


class FakeModel:
    """按脚本逐 run 出 text。每次 stream 返回脚本的下一段。"""
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
    from argos.tui.events import EventBus
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


# ── 人性化:对话轮不走验证门,工程轮照走(2026-06-16 用户反馈)──────────────────


@pytest.mark.asyncio
async def test_conversational_turn_skips_verify_ceremony():
    """纯对话(无代码块、没改任何东西、无 verify_cmd)→ 像 Claude Code 一样直接答复:
    不投 VerifyVerdict、不显示"完成。未机检验证"。验证门是给工程改动的护城河,闲聊不该走。"""
    loop = _loop(["你好！我是 Argos，有什么可以帮你的？"])   # 一段纯文字,无 ```python
    events = []
    async for ev in loop.run("你好", "s"):
        events.append(ev)
    assert not [e for e in events if isinstance(e, VerifyVerdict)], "对话轮不该投验证判决"
    tokens = "".join(e.text for e in events if isinstance(e, TokenDelta))
    assert "未机检验证" not in tokens, f"对话轮不该显示未机检验证完成行,实际:{tokens!r}"
    assert "本轮结束" not in tokens, f"对话轮不该显示任务完成行,实际:{tokens!r}"
    # 四阶段铁律仍守:plan→…→report 都在(只是 verify 静默)。
    phases = [e.phase for e in events if isinstance(e, PhaseChange)]
    assert phases[0] == "plan" and phases[-1] == "report"


@pytest.mark.asyncio
async def test_engineering_turn_still_runs_verify_gate():
    """改了代码(write_file → made_changes=True)→ 仍走完整验证门(护城河分毫不减):必有 VerifyVerdict。"""
    scripts = ["```python\nwrite_file('a.txt','hi')\n```", "完成了。"]
    loop = _loop(scripts)   # verify_cmd=None,但 made_changes=True → 非对话轮 → 仍投判决
    events = []
    async for ev in loop.run("写个文件", "s"):
        events.append(ev)
    assert [e for e in events if isinstance(e, VerifyVerdict)], "工程改动必须投验证判决(护城河)"


@pytest.mark.asyncio
async def test_explicit_verify_cmd_turn_runs_gate_even_without_changes():
    """用户显式声明了 verify_cmd → 即使本轮没改东西也照走验证门(用户声明压倒对话判别)。"""
    loop = _loop(["我看看就好。"], verify_cmd="echo ok")   # 无代码块,但有显式 verify_cmd
    events = []
    async for ev in loop.run("检查一下", "s"):
        events.append(ev)
    assert [e for e in events if isinstance(e, VerifyVerdict)], "声明了 verify_cmd 必须投判决"


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
    from argos.tui.events import EventBus
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=FakeSandbox(),
        broker=None, model=model, verifier=verifier or _RealisticVerifier(),
        config=LoopConfig(verify_cmd=verify_cmd, max_steps=5),
    )


@pytest.mark.asyncio
async def test_loop_emits_costupdate_with_real_tokens_and_elapsed():
    """回归:真 loop 每步发 CostUpdate(真 token 累计 + 真 elapsed)。否则状态栏/成本表死值 0,
    用户以为'没反应'。FakeLoop 之外此前从不发 CostUpdate(本轮修复点)。"""
    from argos.tui.events import CostUpdate
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
    assert last.context_used >= 100, "应带当前窗口占用(输入侧 token,供上下文用量条)"


class _FakeModelWithTier(_FakeModelWithUsage):
    """带 tier.model 的 FakeModel —— 验证 cost 接入 PRICING 表后真算成本。"""
    def __init__(self, scripts, model_name):
        super().__init__(scripts)
        self.tier = type("_T", (), {"model": model_name})()


@pytest.mark.asyncio
async def test_cost_computed_for_known_pricing_model():
    """回归:成本接入定价表后,已知模型(MiniMax-M2 在 PRICING)应算出真实正成本,
    不再恒 $(N/A)。此前 cost_usd 硬编码 None → 即便模型在表里也永远 N/A(bug)。"""
    from argos.tui.events import CostUpdate
    model = _FakeModelWithTier(["```python\nx=1\n```", "完成。"], "MiniMax-M2")
    loop = _loop_with(model)
    costs = [ev for ev in [e async for e in loop.run("g", "s")] if isinstance(ev, CostUpdate)]
    assert costs and costs[-1].cost_usd is not None and costs[-1].cost_usd > 0, \
        "已知定价模型应算出真实正成本(token>0),而非恒 None"


@pytest.mark.asyncio
async def test_cost_none_for_unknown_model_not_fake_zero():
    """诚实:未知单价模型 → cost_usd 回退 None(UI 显 $(N/A)),
    而非 cost_of 对未知模型返回的 0.0(那会显失真的恒 $0.000)。"""
    from argos.tui.events import CostUpdate
    model = _FakeModelWithTier(["```python\nx=1\n```", "完成。"], "No-Such-Model-9000")
    loop = _loop_with(model)
    costs = [ev for ev in [e async for e in loop.run("g", "s")] if isinstance(ev, CostUpdate)]
    assert costs and all(ev.cost_usd is None for ev in costs), \
        "未知模型单价 → 全程 None,绝不显假 $0.000"


@pytest.mark.asyncio
async def test_loop_emits_visible_completion_line_no_test():
    """回归:无 verify_cmd 但【真改了东西】的工程任务,诚实完成("未机检验证")必须在 transcript
    可见(此前只写进 DB,UI 一片空白)。注:脚本用 write_file(made_changes=True)才是工程任务 —
    纯执行/读问答(不改文件)现在按对话轮直接答复、不显示完成判决行(2026-06-16 人性化)。"""
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
    """配了 verify_cmd 且通过 → 可见完成行说'验证通过'。"""
    model = FakeModel(["```python\nx=1\n```", "完成。"])
    loop = _loop_with(model, verify_cmd="echo ok")
    texts = [ev.text for ev in [e async for e in loop.run("g", "s")]
             if isinstance(ev, TokenDelta)]
    from argos.i18n import t as _t
    assert texts and _t("loop.done.verified") in "".join(texts), "通过的任务完成行应含验证通过标注"


def test_codeact_contract_in_honesty_system():
    """回归:HONESTY_SYSTEM 必须含明确 CodeAct 契约(强制 ```python 围栏 + 禁 JSON 工具调用)。
    实测:缺这段时 MiniMax-M3 吐 JSON 工具调用 → extract_code_block 抽不到 → agent 对编码任务恒为 no-op。"""
    from argos.core.honesty import HONESTY_SYSTEM
    assert "```python" in HONESTY_SYSTEM, "必须给出 ```python 围栏示例/要求"
    assert "JSON" in HONESTY_SYSTEM and "silently never runs" in HONESTY_SYSTEM, "必须明确禁止 JSON 工具调用"
    assert "write_file(path, content)" in HONESTY_SYSTEM, "应文档化工具的 Python 函数签名"


@pytest.mark.asyncio
async def test_no_action_bounces_not_completes():
    """模型纯文字宣布完成、0 个代码动作 → 不得进 verify/收尾,应 bounce 催它真做。"""
    # 第一段:纯文字(无代码块,0 action);第二段才给代码块;第三段完成。
    model = FakeModel(["我来修这几处。", "```python\nwrite_file('a','b')\n```", "完成。"])
    loop = _loop_with(model, verify_cmd=None)  # _loop_with 见本文件
    actions = []
    async for ev in loop.run("g", "s"):
        if isinstance(ev, CodeAction):
            actions.append(ev)
    assert len(actions) >= 1, "应在第二段真执行代码,而非首段纯文字就收尾"


@pytest.mark.asyncio
async def test_conversational_reply_completes_without_nudge():
    """聪明催(2026-06-14):实质对话答复(无代码块、不含'将做/完成'措辞)→ 一轮收尾,不催第二轮。

    回归对照 test_no_action_bounces_not_completes:'我来修这几处。'(含'我来')仍催;
    本测试'你好…'实质答复不催 → 模型只被调一次,直接进 verify/report。

    用规范 verifier(无 verify_cmd → unverifiable,同真 Verifier 行为 verify_gate.py:72)——
    本文件的 FakeVerifier 对 None 返 passed 不规范,会让无测任务误走 bounce。
    """
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
    """对话/纯读(made_changes=False)→ 绝不推断 verify 策略。

    真机 bug(2026-06-14):'你好'在有 pyproject/tests 的项目里被 _pick_strategy_cmd 推断成
    pytest → verify FAILED(no tests ran)→ bounce → 模型被迫'找测试',把一句问候变成跑
    pytest+翻目录的任务。修:策略推断加 made_changes 守卫(只对真改过代码的任务推断)。
    """
    from argos.tui.events import EventBus

    called = {"n": 0}

    def _spy_pick(self, goal):
        called["n"] += 1
        return "pytest -q"  # 模拟在 argos 项目里被推断出 pytest

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
    """回归(2026-06-09):max_steps 耗尽、模型从未说'完成'时,while 自然退出落到
    enter_phase('report')。harness 此时仍停在 act(idx=1)→ 跳到 report(idx=3)曾
    触发 ValueError('阶段不可跳'),被 best_of_n 1/3 候选踩中。

    修法:while 后补一次惰性 enter_phase('verify') 让 phase_idx 推进到 2,再 report 不跳。
    本测试断言:不抛 ValueError,且 verify/report 阶段都被投出。
    """
    # 模型死循环:有代码块但永远不说完成(只有一个脚本,FakeModel 在末位反复发同一段)。
    # max_steps=2 强制 while 在第二次循环后退出。
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
    # 必含 verify 与 report(无论是否真做了 verify),且 verify 在 report 之前。
    assert "verify" in phases, f"补齐后 verify 必须被投出,实际 phases={phases}"
    assert phases[-1] == "report", f"最后一阶段必须是 report,实际 phases={phases}"
    assert phases.index("verify") < phases.index("report"), \
        f"verify 必须在 report 之前,实际 phases={phases}"


@pytest.mark.asyncio
async def test_max_steps_bailout_runs_verify_not_just_phase_change():
    """回归(2026-06-09):max_steps 耗尽时,补齐段不仅投 PhaseChange("verify"),
    还必须真跑 run_verify_gate 投出 VerifyVerdict。

    之前 bug:补齐只 enter_phase("verify"),不 run_verify_gate → last_verdict=None →
    bridge 的 winner.verdict=None → bench 把任务记为 failed(0% pass@1)。
    真 TB 任务 csv-to-parquet 跑 N=1 1/1 候选就是这么被错算的(模型 40 步耗尽,
    实际产物是 csv→parquet 真写出来了,应有机会通过 verify,但旧逻辑直接 bail 不验)。

    修法:补齐段复用正常 verify 路径(enter_phase + run_verify_gate + last_verdict=...)。
    本测试断言:有 verify_cmd 时,VerifyVerdict 事件必须被投出,status="passed"。
    """
    from argos.tui.events import EventBus
    # 模型死循环写代码但永远不说完成;verify_cmd 配了 → 真应该跑 verify。
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
    """回归(2026-06-09):max_steps 耗尽 + verify_cmd=None 时,bailout 后跑 verify
    仍要触发诚实完成(unverifiable + is_honest_completion=True → 报告 NO_TEST)。

    模型没改代码 / 没声明 verify:不算失败,只是"无测任务" → 收尾诚实标 NO_TEST。
    """
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
    # FakeVerifier 没配 verify_cmd 也返 passed → 但 Harness.is_honest_completion
    # 只判 verify_cmd is None + unverifiable。这里 FakeVerifier 没区分是 FakeVerifier
    # 的弱点(它把 None 也当 passed)—— 我们只断言"事件被投出"。


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
    # 真实 Verifier 在 verify_cmd=None 时返 unverifiable,见 test_loop_runs_code_and_emits_events。
