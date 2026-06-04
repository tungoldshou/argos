"""自建 CodeAct AgentLoop(契约 §3 + spec §3.1-§3.3) —— 替换 LangChain create_agent。

原生 async 全链路直喂 EventBus。四阶段(plan→act→verify→report)不可跳(spec §3.3 L3):
  · plan:出方案(第一次模型输出)。
  · act:CodeAct 执行 —— 抽 Python 代码块 → sandbox.exec_code → CodeResult 回灌,循环。
  · verify:模型称"完成"(无代码块)→ PhaseChange("verify") → verifier.verify → VerifyVerdict。
  · report:全绿或诚实标注"未完整验证";失败 bounce 重生成,超 max_rounds → Escalation。
一份事件三用:每个 Event 既 yield 给调用方,又 store.append_event 持久化。

契约 §9 锁定 + §10 接线(Phase 4 落实):
  锁#1: verify(verify_cmd, attempts=...) -> Verdict,无自建 _Verdict,无 detect_tampering。
  锁#6: LoopConfig.model_tier: ModelTierName, approval_level: ApprovalLevel。
  W1:   PhaseChange("verify") 在 VerifyVerdict 之前发出(enter_phase("verify") 先于 run_verify_gate)。
  W2:   loop 真正调用 Harness —— enter_phase 取代内联 _phase、run_verify_gate 取代内联
         verifier 调用+escalation、accept_receipt 在投 ToolReceipt 前核验回执(§6.5)。
         loop 内不再保留并行的 phase/verify/receipt 逻辑(无死代码/重复)。
  W3:   系统提示走 compose_system(HONESTY_SYSTEM, untrusted=format_untrusted(skills, recall))
         (store 带 recall 时);流式 delta 过 StreamingContextScrubber 再投 TokenDelta。
         无可召回 store → 诚实降级为 HONESTY_SYSTEM only(不假装召回发生过)。

HONESTY CORRECTION(spec HONESTY 规则 1):没配 verify_cmd → Verifier 返 unverifiable(绝不当
passed);Harness 据 "verify_cmd is None" 把它当诚实非阻塞完成(无测任务能收尾,不 bounce),
report 诚实标 NO_TEST_LABEL。配了 verify_cmd 却 unverifiable(篡改/超时)或 failed → bounce/escalate。
目标 <800 行。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from argos_agent.core.harness import Harness
from argos_agent.core.honesty import (
    HONESTY_SYSTEM, StreamingContextScrubber, compose_system, format_untrusted,
)
from argos_agent.core.types import ModelTierName
from argos_agent.tui.events import (
    CodeAction, CodeResult, CostUpdate, Error, Event, EventBus, PhaseChange,
    TokenDelta, ToolReceipt,
)

if TYPE_CHECKING:
    from argos_agent.memory.store import ArgosStore
    from argos_agent.sandbox.backend import SandboxBackend
    from argos_agent.sandbox.broker import CapabilityBroker

# 延迟 import ApprovalLevel 避免循环;用 TYPE_CHECKING 拿类型,运行时懒 import。
try:
    from argos_agent.approval import ApprovalLevel as _ApprovalLevel
    _DEFAULT_APPROVAL_LEVEL: Any = _ApprovalLevel.CONFIRM
except Exception:  # noqa: BLE001
    _DEFAULT_APPROVAL_LEVEL = None  # Phase 4 接线前的极端兜底

_CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

# M8 安全不变量:沙箱 spawn 用【固定空命名空间】—— 绝不把模型输出/外部数据塞进
# namespace["__authorized_imports__"]。smolagents 在 AST 层把 "*" 当 allow-all,
# 若模型能控制 authorized_imports 就能放开任意 import,绕过 AST 限制层(OS 沙箱仍在,
# 但纵深的一层被废)。spawn 一律传这个空 dict 的副本,不接受调用方注入。
_FIXED_SPAWN_NAMESPACE: dict[str, Any] = {}


def extract_code_block(text: str) -> str | None:
    """从模型输出抽第一个 Python 代码块;无则 None。"""
    m = _CODE_BLOCK.search(text)
    if not m:
        return None
    return m.group(1).strip()


class _CollectingBus(EventBus):
    """loop 内部用的录制总线 —— Harness 把 PhaseChange/VerifyVerdict/Escalation emit 到这里,
    loop 调完 Harness 方法后 drain() 取出这些事件,统一走 yield + store.append_event 这条
    "一份事件三用"主路径(故 Harness 不是死代码,且其事件与 loop 直投事件同一条流)。"""

    def __init__(self) -> None:
        super().__init__()
        self._collected: list[Event] = []

    async def emit(self, ev: Event) -> None:  # type: ignore[override]
        self._collected.append(ev)

    def drain(self) -> list[Event]:
        out = self._collected
        self._collected = []
        return out


@dataclass(frozen=True, slots=True)
class LoopConfig:
    """契约 §9 锁#6 — model_tier: ModelTierName, approval_level: ApprovalLevel。"""
    model_tier: ModelTierName = "worker"
    verify_cmd: str | None = None
    max_rounds: int = 3              # verify bounce 上限
    max_steps: int = 40              # CodeAct 步数硬上限(death-spiral 兜底)
    compaction: bool = True
    recall: bool = True              # W3:store 支持 recall 时是否注入召回的 untrusted 段
    # approval_level 默认 ApprovalLevel.CONFIRM(契约 §9 锁#6)。
    approval_level: Any = field(default_factory=lambda: _DEFAULT_APPROVAL_LEVEL)


class AgentLoop:
    """CodeAct 主循环。W2 调 Harness 做阶段门/verify 门/回执核验;W3 注入诚实召回链。"""

    def __init__(
        self,
        *,
        store: "ArgosStore",
        bus: "EventBus",
        sandbox: "SandboxBackend",
        broker: "CapabilityBroker | None",
        model: Any,
        verifier: Any,
        config: LoopConfig,
        workspace: Path | None = None,
        verify_dir: Path | None = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self._sandbox = sandbox
        self._broker = broker
        self._model = model
        self._verifier = verifier
        self._cfg = config
        self._workspace = workspace or Path.home() / ".argos" / "workspace"
        self._verify_dir = verify_dir or Path.home() / ".argos" / "verify"
        self._actions = 0
        self._fail_count = 0
        self._started = 0.0
        self._tok_in = 0        # 累计 token 用量(每步从 model.last_usage 累加,供 CostUpdate)
        self._tok_out = 0
        self._cache_read = 0    # 累计缓存命中 token(成本栏诚实显示,从 model.last_usage 累加)
        # W2:loop 内部录制总线 + Harness。Harness 的 signer 取 broker 的 host signer
        # (同进程,沙箱拿不到),无 broker 时用 verifier 也无回执可验 → 给个一次性 key 占位
        # (无 broker 时 accept_receipt 不会被调用,故 key 不重要)。
        self._hbus = _CollectingBus()
        self._harness = Harness(
            verifier=verifier,
            signer=self._broker.signer if self._broker is not None else _ReceiptSigner(key=b"_no_broker_"),
            bus=self._hbus,
            max_rounds=config.max_rounds,   # bounce 上限以 LoopConfig 为准(loop 拥有 bounce 策略)。
        )

    # ── 只读访问(Phase 6 装配/e2e 核验用;构造参数即这些,属性化是最小暴露)──────────
    @property
    def bus(self) -> "EventBus":
        return self._bus

    @property
    def store(self) -> "ArgosStore":
        return self._store

    @property
    def sandbox(self) -> "SandboxBackend":
        return self._sandbox

    @property
    def broker(self) -> "CapabilityBroker | None":
        return self._broker

    def _reset_run_state(self) -> None:
        self._actions = 0
        self._fail_count = 0
        self._tok_in = 0
        self._tok_out = 0
        self._cache_read = 0
        self._started = time.time()

    async def run(self, goal: str, session_id: str) -> AsyncIterator["Event"]:
        """驱动一次 run。plan→act→verify→report,投并持久化每个 Event(一份事件三用)。

        顶层兜底:捕获 _drive 内任何未处理异常,挖异常链投 Error(spec §3.3 L5)。
        """
        self._reset_run_state()
        # M8:固定空命名空间的副本 —— 模型输出永不经此进入 __authorized_imports__。
        spawn_namespace = dict(_FIXED_SPAWN_NAMESPACE)
        assert "__authorized_imports__" not in spawn_namespace, (
            "M8 安全不变量:loop spawn 的 namespace 绝不可携带 __authorized_imports__"
            "(smolagents 把 '*' 当 allow-all,模型可控会绕过 AST 限制层)。"
        )
        self._sandbox.spawn(workspace=self._workspace, namespace=spawn_namespace)
        try:
            async for ev in self._drive(goal, session_id):
                self._store.append_event(session_id, ev)
                yield ev
        except Exception as e:  # noqa: BLE001
            chain: list[str] = []
            cur: BaseException | None = e
            while cur is not None and len(chain) < 4:
                chain.append(f"{type(cur).__name__}: {cur}")
                cur = cur.__cause__ or cur.__context__
            err = Error(message=str(e), chain=chain)
            self._store.append_event(session_id, err)
            yield err
        finally:
            self._sandbox.close()

    async def _enter_phase(self, phase: str) -> AsyncIterator["Event"]:
        """W2:经 Harness.enter_phase 推进阶段门(强制不可跳),drain 出 PhaseChange 走主路径。"""
        await self._harness.enter_phase(phase, actions=self._actions)  # type: ignore[arg-type]
        for ev in self._hbus.drain():
            yield ev

    def _build_system(self, goal: str) -> str:
        """W3:store 带 recall → compose_system(HONESTY_SYSTEM, untrusted=召回);否则诚实降级
        为 HONESTY_SYSTEM only(不假装召回发生过)。召回失败也降级,不让 run 崩。"""
        if not self._cfg.recall or not hasattr(self._store, "recall"):
            return HONESTY_SYSTEM
        try:
            hits = self._store.recall(goal)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return HONESTY_SYSTEM
        memory_lines = [
            f"- {rec.goal} → {rec.verdict or '?'}（{reason}）" for rec, reason in hits
        ]
        untrusted = format_untrusted(skill_bodies=[], memory_lines=memory_lines)
        return compose_system(HONESTY_SYSTEM, untrusted=untrusted)

    async def _drive(self, goal: str, session_id: str) -> AsyncIterator["Event"]:
        """四阶段驱动(不可跳):plan → act(CodeAct 循环) → verify(门禁) → report。"""
        # 确保 session 行先于任何 event/message 落库(replay/resume 据 session_id 重建;幂等,
        # resume 时已存在则 no-op)。hasattr 守卫:最小 store 替身(无 session 概念)跳过。
        if hasattr(self._store, "ensure_session"):
            self._store.ensure_session(  # type: ignore[attr-defined]
                session_id, title=goal[:80], model=self._cfg.model_tier, system_snapshot="",
            )
        # ── plan ──
        async for ev in self._enter_phase("plan"):
            yield ev
        # 多轮上下文:加载本 session 历史消息线程,再追加本轮 goal(全量重发,spec 已拍板)。
        # get_messages 必须在 append_message(本轮 goal)之前调,否则本轮 goal 会重复一次。
        if hasattr(self._store, "get_messages"):
            messages: list[dict] = self._store.get_messages(session_id)
        else:
            messages = []
        messages.append({"role": "user", "content": goal})
        self._store.append_message(session_id, role="user", content=goal)
        # W3:系统提示在 run 起始算一次(召回的 untrusted 段在安全段之后)。
        system = self._build_system(goal)

        # ── act(CodeAct 循环)──
        async for ev in self._enter_phase("act"):
            yield ev
        step = 0
        report_note = ""   # 收尾时报告里诚实标注(如无测任务"未机检验证")。
        last_verdict: Any = None  # 最后一次 verify 结果,供 report 可见完成行诚实反映结局。
        escalated = False
        while step < self._cfg.max_steps:
            # W3:流式 delta 过 StreamingContextScrubber,防模型把 untrusted 围栏吐回 UI 泄露。
            scrubber = StreamingContextScrubber()
            text = ""
            async for delta in self._model.stream(messages, system=system):
                text += delta
                clean = scrubber.feed(delta)
                if clean:
                    yield TokenDelta(text=clean)
            tail = scrubber.flush()
            if tail:
                yield TokenDelta(text=tail)
            messages.append({"role": "assistant", "content": text})

            # CostUpdate:真 token(从 model.last_usage 累加)+ 真 elapsed,让状态栏/成本表走起来。
            # 单价未知 → cost_usd 置 None(诚实:不编造成本,UI 显 $(N/A)),token 与计时仍如实反映。
            usage = getattr(self._model, "last_usage", None) or {}
            self._tok_in += int(usage.get("input_tokens") or 0)
            self._tok_out += int(usage.get("output_tokens") or 0)
            self._cache_read += int(usage.get("cache_read") or 0)
            yield CostUpdate(
                tokens_in=self._tok_in, tokens_out=self._tok_out,
                cost_usd=None, elapsed_s=time.time() - self._started,
                cache_read=self._cache_read,
            )

            code = extract_code_block(text)
            if code is not None:
                yield CodeAction(code=code, step=step)
                result = self._sandbox.exec_code(code)
                self._actions += 1
                yield CodeResult(
                    step=step, stdout=result.stdout,
                    value_repr=result.value_repr, exc=result.exc, ok=result.ok,
                )
                # I2 + W2(§6.5):只在【本步新签了 Receipt】且【HMAC 核验通过】时投 ToolReceipt。
                # accept_receipt 在投事件前核验回执 —— 伪造/篡改的回执拒投(防谎报工具执行)。
                if self._broker is not None:
                    new_receipt = self._broker.take_receipt()
                    if new_receipt is not None and self._harness.accept_receipt(new_receipt):
                        yield ToolReceipt(receipt=new_receipt)
                messages.append({"role": "user", "content": self._feedback(result)})
                step += 1
                continue

            # 无代码块 → 模型宣布"完成" → 进 verify。
            # W1:先 enter_phase("verify")(投 PhaseChange),再 run_verify_gate(投 VerifyVerdict)。
            async for ev in self._enter_phase("verify"):
                yield ev

            # W2:run_verify_gate 跑 verifier 出三态 Verdict,投 VerifyVerdict;真问题超
            # max_rounds 时它自己投 Escalation。loop 据返回的 verdict 决定 break / bounce。
            verdict = await self._harness.run_verify_gate(
                self._cfg.verify_cmd, attempt=self._fail_count + 1
            )
            last_verdict = verdict
            for ev in self._hbus.drain():
                yield ev

            # Defense-in-depth(Phase 4 #3):verify_cmd is None 时绝不以 passed 收尾 ——
            # 非规范 verifier 可能对无测任务返回 passed;必须走诚实完成路径标 NO_TEST_LABEL。
            if verdict.status == "passed" and self._cfg.verify_cmd is not None:
                break                        # 通过 → 收尾
            if self._harness.is_honest_completion(verdict, verify_cmd=self._cfg.verify_cmd):
                # HONESTY CORRECTION:无测任务的诚实非阻塞完成 —— 收尾,report 标"未机检验证"。
                report_note = "未机检验证 (no test command)"
                break
            # 到这里:failed,或配了 cmd 却 unverifiable(篡改/超时)→ 真问题 → bounce/escalate。
            self._fail_count += 1
            if self._fail_count > self._cfg.max_rounds:
                # 此刻 run_verify_gate 这一轮(attempt = 本次 _fail_count,即 max_rounds+1)已
                # 投出 Escalation —— 二者同一判据(attempt > max_rounds)同轮触发,诚实终止。
                escalated = True
                break
            bounce = (
                f"[Argos 验证门] 你声称完成,但验证 `{self._cfg.verify_cmd}` 未通过/不可信:"
                f"\n{verdict.detail}\n请用工具定位并修复,改完再说完成。"
            )
            messages.append({"role": "user", "content": bounce})
            step += 1

        # ── report ──
        if report_note:
            # 诚实标注挂在 report 的 PhaseChange 之前先记一笔(走持久化主路径)。
            self._store.append_message(
                session_id, role="system", content=f"[report] {report_note}"
            )
        async for ev in self._enter_phase("report"):
            yield ev
        # 可见完成行(诚实反映结局):此前完成只翻 phase + 一条写进 DB 看不见的备注,UI 一片空白
        # 像"没反应"。这里显式打一行,让用户看到本轮真的跑完了及结果。
        if escalated:
            done = "⚠️ 未能在限定轮内通过验证,已如实上报(见上方升级提示)。\n"
        elif report_note:
            done = f"✅ 完成。{report_note}\n"   # 无测任务:诚实标"未机检验证 (no test command)"
        elif last_verdict is not None and getattr(last_verdict, "status", None) == "passed":
            done = "✅ 完成,验证通过(测试/检查全绿)。\n"
        elif last_verdict is not None and getattr(last_verdict, "status", None) != "passed":
            done = "⚠️ 本轮结束:验证未通过/不可信(详见上)。\n"
        else:
            done = "✅ 本轮结束。\n"
        yield TokenDelta(text=done)

    @staticmethod
    def _feedback(result: Any) -> str:
        """把 ExecResult 转成给模型回灌的文本。"""
        if not result.ok:
            return f"[执行异常]\n{result.exc}"
        out = result.stdout
        if result.value_repr:
            out += f"\n[返回值] {result.value_repr}"
        return f"[执行结果]\n{out}" if out.strip() else "[执行完成,无输出]"


# 运行时懒 import(避免顶层与 broker/receipts 形成 import 环;仅无 broker 占位用)。
from argos_agent.tools.receipts import ReceiptSigner as _ReceiptSigner  # noqa: E402
