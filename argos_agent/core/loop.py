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

Plan mode spec §2.5:EnterPlanMode 切到 plan mode 后,plan 阶段产出 → 拼 markdown → 投
`PlanRendered` 事件 → 挂起 `_plan_decision_event` 等 TUI 弹 PlanModal 决策 → ExitPlanMode
写 `_plan_decision` + set event 唤醒 loop → 4 分支(approve_start / approve_accept_edits /
keep_planning / refine)处理。approve_accept_edits 临时切 `approval_level` 到 ACCEPT_EDITS
(act 阶段完了在 _reset_run_state / 阶段门里恢复)。

HONESTY CORRECTION(spec HONESTY 规则 1):没配 verify_cmd → Verifier 返 unverifiable(绝不当
passed);Harness 据 "verify_cmd is None" 把它当诚实非阻塞完成(无测任务能收尾,不 bounce),
report 诚实标 NO_TEST_LABEL。配了 verify_cmd 却 unverifiable(篡改/超时)或 failed → bounce/escalate。
目标 <800 行。
"""
from __future__ import annotations

import asyncio
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from argos_agent.core.harness import Harness
from argos_agent.core.honesty import (
    HONESTY_SYSTEM, StreamingContextScrubber, compose_system, format_untrusted,
)
from argos_agent.core.plan_mode import PlanExitDecision, PlanRenderer
from argos_agent.core.types import ModelTierName
from argos_agent.tui.events import (
    CodeAction, CodeResult, CostUpdate, Error, Event, EventBus, PhaseChange,
    PlanRendered, PlanUpdate, TokenDelta, ToolReceipt,
)
from argos_agent import hooks as _hooks
from argos_agent.hooks.payload import (
    build_post_payload, build_pre_payload, build_session_start_payload,
    build_stop_payload, extract_tool_names,
)
from argos_agent.hooks.events import HookFired

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

# 真验证门:从模型【代码块文本】里抓 propose_verify('<cmd>') 的命令参数(host 侧解析)。
# 沙箱是独立子进程(Seatbelt),host 回调无法注入其命名空间 —— 故 host 在 act 循环里解析
# agent 输出登记验证命令;沙箱内的 propose_verify() 工具仅给个登记回执(真执行在 host verify 阶段)。
_PROPOSE_VERIFY = re.compile(r"propose_verify\(\s*['\"](.+?)['\"]\s*\)")

# H1 防假绿:这些命令【永远通过、什么都不验证】,弱模型可声明它们(如 `echo ok`)骗过 verify 门
# 报"已验证通过"。propose_verify 一律拒登记这类伪命令 → 落回"未机检验证"诚实路径,不产生假绿。
_TRIVIAL_VERIFY_BINS = frozenset({
    "echo", "true", "false", ":", "ls", "pwd", "cat", "printf", "head", "tail",
    "yes", "whoami", "date", "env", "sleep", "test", "[", "dirname", "basename",
})

# 真 TODO 拆解:从模型代码块文本里抓 update_plan([{...}, ...]) 的列表字面量(host 侧解析,
# 同 propose_verify 路径 —— 沙箱独立子进程,host 解析 agent 输出把 todos 传回再 yield PlanUpdate)。
# 非贪婪不行(列表内有嵌套括号/逗号),故抓最外层 ([...]) 用括号配平在 _extract_plan 里做。
_UPDATE_PLAN = re.compile(r"update_plan\(", re.DOTALL)

# 紧跟现有 _UPDATE_PLAN 模式:抓 propose_workflow({...}) 的 dict 字面量实参(host 侧解析,
# 沙箱独立子进程拿不到回调)。括号配平 + ast.literal_eval(只认字面量,绝不 eval 任意表达式)。
_PROPOSE_WORKFLOW = re.compile(r"propose_workflow\(", re.DOTALL)

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


def extract_plan_todos(text: str) -> list[dict] | None:
    """从模型输出抽最后一次 update_plan([...]) 的 todos 列表字面量;无/解析失败则 None。

    括号配平扫描(列表内含嵌套 {}/逗号/字符串,正则非贪婪做不到),取实参子串后 ast.literal_eval
    —— 只认字面量(防注入,绝不 eval 任意表达式)。取【最后一次】调用反映 agent 最新状态。
    """
    import ast
    last: list[dict] | None = None
    for m in _UPDATE_PLAN.finditer(text):
        i = m.end()                       # 紧随 '(' 之后
        depth = 1
        in_str: str | None = None
        esc = False
        j = i
        while j < len(text) and depth > 0:
            ch = text[j]
            if in_str is not None:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
            elif ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        if depth != 0:
            continue                      # 括号没配平(截断/跨段)→ 跳过
        arg = text[i:j - 1].strip()       # 去掉收尾的 ')'
        try:
            val = ast.literal_eval(arg)
        except (ValueError, SyntaxError):
            continue
        if isinstance(val, list):
            last = [d for d in val if isinstance(d, dict)]
    return last


def extract_workflow_spec(text: str) -> dict | None:
    """从模型输出抽最后一次 propose_workflow({...}) 的规格字面量;无/解析失败/非 dict → None。

    括号配平扫描(dict 内含嵌套 []/{}/ 字符串,正则非贪婪做不到),取实参子串后 ast.literal_eval
    —— 只认字面量(防注入,绝不 eval 任意表达式)。取【最后一次】调用反映 agent 最新状态。
    """
    import ast
    last: dict | None = None
    for m in _PROPOSE_WORKFLOW.finditer(text):
        i = m.end()                       # 紧随 '(' 之后
        depth = 1
        in_str: str | None = None
        esc = False
        j = i
        while j < len(text) and depth > 0:
            ch = text[j]
            if in_str is not None:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
            elif ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        if depth != 0:
            continue                      # 括号没配平(截断/跨段)→ 跳过
        arg = text[i:j - 1].strip()       # 去掉收尾的 ')'
        try:
            val = ast.literal_eval(arg)
        except (ValueError, SyntaxError):
            continue
        if isinstance(val, dict):
            last = val
    return last


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


def _env_context(workspace: Path) -> str:
    """运行环境块(可信安全段的一部分):把 cwd/OS/日期前置喂给模型,免得它为了回答
    "在哪个目录"之类的事实去现场跑 os.getcwd()/pwd(对齐 Claude Code 的 environment 块)。"""
    import platform
    from datetime import date
    return (
        "\n\n【运行环境】\n"
        f"- 工作目录(相对路径都相对它解析):{workspace}\n"
        f"- 操作系统:{platform.system()} {platform.machine()}\n"
        f"- 今天日期:{date.today().isoformat()}\n"
        "以上为已知事实,无需用代码现场探测(如 os.getcwd / pathlib.Path.cwd / pwd)。"
    )


@dataclass(frozen=True, slots=True)
class LoopConfig:
    """契约 §9 锁#6 — model_tier: ModelTierName, approval_level: ApprovalLevel。"""
    model_tier: ModelTierName = "default"
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
        allow_workflow: bool = True,
        read_only: bool = False,
        workflow_engine_factory: Callable[[], object] | None = None,
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
        self._allow_workflow = allow_workflow  # 子 agent spawn 时传 False,深度护栏去 propose_workflow
        self._read_only = read_only  # tool_scope=read 时传 True,剔除写工具兑现「只读」承诺
        # 工作流引擎工厂:None=未接入(诚实回错,不崩 run);非 None=act 段抓到 propose_workflow 后
        # 在异步态校验+审批+异步跑引擎+结果回灌(每次提议 new 一个引擎,RAII 不复用状态)。
        self._workflow_engine_factory = workflow_engine_factory
        self._actions = 0
        self._fail_count = 0
        self._started = 0.0
        # 真验证门:agent 在 act 阶段用 propose_verify('<cmd>') 声明验证命令(初值取 LoopConfig.verify_cmd
        # 到可变实例字段)。verify 阶段 harness 在隔离 verify_dir 独立跑【这个】命令(退出码为准),
        # agent 碰不到执行 —— 防 agent 篡改评判它的测试作弊。无 propose 维持 NO_TEST_LABEL 诚实路径。
        self._verify_cmd: str | None = config.verify_cmd
        self._verify_rejected: str | None = None   # H1:被拒的伪验证命令,供 act 循环回灌一次反馈
        # 真 TODO 拆解:agent 用 update_plan([...]) 列/更子任务清单。loop 解析后存这里,
        # 变化才 yield PlanUpdate(去重),并把摘要回灌进 messages(锚机制,防长任务丢目标)。
        self._todos: list[dict] = []
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
        # Plan mode spec §2.1:默认 act,EnterPlanMode 切到 plan,ExitPlanMode 切回 act。
        # 沙箱工具 dispatcher 后续 Task 会读 loop.mode 抛 PlanModeError(留接口,本 Task 不接线)。
        self.mode: str = "act"
        # Plan mode spec §2.5:plan 阶段模型产出后,投 PlanRendered 事件 + 挂起等用户决策。
        # TUI 弹 PlanModal → 用户选 4 选项 → ExitPlanMode 写 _plan_decision + set event
        # 唤醒本 loop 的 await。_approval_level_override 是 approve_accept_edits 的临时
        # approval_level 切换点(act 阶段完了在 _reset_run_state / 阶段门里恢复)。
        self._plan_decision_event: asyncio.Event = asyncio.Event()
        self._plan_decision: PlanExitDecision | None = None
        self._approval_level_override: Any = None

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
        self._verify_cmd = self._cfg.verify_cmd   # 每轮回到配置初值,上轮 propose 不跨轮泄漏
        self._verify_rejected = None
        self._todos = []                          # 每轮清空,上轮 todos 不跨轮泄漏
        self._tok_in = 0
        self._tok_out = 0
        self._cache_read = 0
        self._started = time.time()
        # Plan mode spec §2.5:每轮新 run 重置 _plan_decision + 换新 Event(防上轮残留)。
        # _approval_level_override 恢复 None(approve_accept_edits 的临时切换仅本轮 act 段有效)。
        self._plan_decision = None
        self._plan_decision_event = asyncio.Event()
        self._approval_level_override = None

    def _on_propose_verify(self, cmd: str) -> bool:
        """agent 调 propose_verify('<cmd>') 时登记验证命令(host 侧;真执行在 verify 阶段)。

        H1 防假绿:拒绝 echo/true/ls/pwd/cat 等【永远通过、什么都不验证】的伪命令 —— 否则弱模型
        可声明 `echo ok` 让 verify 门返 passed 谎报"已验证通过"。伪命令不登记 → 落回"未机检验证"
        的诚实路径(而非假绿)。返回是否登记成功(False=被拒,供调用方回灌反馈)。"""
        cmd = (cmd or "").strip()
        if not cmd:
            return False
        try:
            bin_name = Path(shlex.split(cmd)[0]).name
        except (ValueError, IndexError):
            return False
        if bin_name in _TRIVIAL_VERIFY_BINS:
            self._verify_rejected = cmd   # 供 act 循环回灌一句"这不是验证命令"
            return False
        self._verify_cmd = cmd
        return True

    @staticmethod
    def _todos_summary(todos: list[dict]) -> str:
        """把当前 todos 摘成一行行的进度文本(回灌 messages 的锚,防长任务丢目标)。"""
        glyph = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}
        done = sum(1 for t in todos if t.get("status") == "completed")
        lines = [f"[Argos 任务清单 {done}/{len(todos)}]"]
        for t in todos:
            mark = glyph.get(t.get("status", "pending"), "[ ]")
            lines.append(f"{mark} {t.get('content', '')}")
        return "\n".join(lines)

    async def run(self, goal: str, session_id: str) -> AsyncIterator["Event"]:
        """驱动一次 run。plan→act→verify→report,投并持久化每个 Event(一份事件三用)。

        顶层兜底:捕获 _drive 内任何未处理异常,挖异常链投 Error(spec §3.3 L5)。
        """
        self._reset_run_state()
        # 拍 workspace 快照(供 /undo 还原);失败不阻断 run,仅 _last_snapshot = None 走"/undo
        # 不可用"诚实降级路径。延迟 import 避免 core.snapshot ↔ runtime 之间未来的循环风险。
        self._last_snapshot = None
        try:
            from argos_agent.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
            tar_path = SNAPSHOT_ROOT / f"{session_id}-{int(time.time() * 1000)}.tar"
            self._last_snapshot = RunSnapshot.take(self._workspace, tar_path)
        except Exception:  # noqa: BLE001 — 诚实:拍快照失败 = /undo 不可用,run 照常进行
            pass
        # M8:固定空命名空间的副本 —— 模型输出永不经此进入 __authorized_imports__。
        spawn_namespace = dict(_FIXED_SPAWN_NAMESPACE)
        assert "__authorized_imports__" not in spawn_namespace, (
            "M8 安全不变量:loop spawn 的 namespace 绝不可携带 __authorized_imports__"
            "(smolagents 把 '*' 当 allow-all,模型可控会绕过 AST 限制层)。"
        )
        self._sandbox.spawn(workspace=self._workspace, namespace=spawn_namespace,
                            allow_workflow=self._allow_workflow,
                            read_only=self._read_only)
        # 头号护城河洞修复:project_mode 下 verify_dir==workspace,agent 技术上能改"评判自己的
        # 测试"。run 起始(agent 动手前)快照既有测试指纹 → detect_tampering 见改/删即判篡改,
        # verify 据此判 unverifiable(诚实)。沙箱模式靠 VERIFY_DIR 隔离,guard_project_tests 自返 0。
        # 与 propose_verify 时机无关(快照早于任何 agent 动作)→ 堵"先改弱测试再声明"那条绕过。
        try:
            from argos_agent import runtime
            runtime.guard_project_tests()
        except Exception:  # noqa: BLE001 — 守护快照失败不阻断 run(诚实降级:此 run 无篡改检测)
            pass
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

    def _tool_signatures_block(self) -> str:
        """工具签名提示(本 PR 新增 3 工具的签名,模型调用时不会因签名漂移跑错)。

        spec §2.3.3:跟 _env_context 同位置(HONESTY 之后、untrusted 之前)。
        顺序锁死——若改了位置,先看 spec §12.1。
        """
        return (
            "\n\n## 工具签名速查(本会话新签名)\n"
            "- read_file(path, offset: int = 0, limit: int | None = None)\n"
            "  · offset=起始行号(0-based),limit=读多少行(None=读到 EOF)\n"
            "- edit_file(path, old, new, all_occurrences: bool = False)\n"
            "  · all_occurrences=False(默认)=唯一匹配;True=替换全部(上限 1000 处)\n"
            "· 沙箱命令 /undo 还原本轮 run 起点的文件改动(不发)\n"
            "· 沙箱命令 /retry 重发本会话最后一条 user 消息(忙时先 Esc)\n"
        )

    def _build_system(self, goal: str) -> str:
        """系统提示三段接线(顺序锁死,spec §12.1):
          · 安全段 = HONESTY_SYSTEM + 结构化任务契约(命中时注入我们自己的可信 checklist,
            便宜模型对齐形式约定的护城河;非结构化任务不注入)。
          · untrusted 段 = 召回的 skills(社区/导入,围栏隔离防注入) + 任务记忆。
        skills 召回零模型兜底、不依赖 store;memory 召回需 store.recall。任一失败都诚实降级
        (不假装召回发生过),绝不让 run 崩。"""
        # ── 安全段:运行环境块(cwd/OS/日期前置,免得模型现场探目录)+ 结构化工程任务契约 ──
        # spec §2.3.3:_tool_signatures_block 跟 _env_context 同位置(HONESTY 之后、untrusted 之前)
        safe = (
            HONESTY_SYSTEM
            + _env_context(self._workspace)
        )
        # #9 T6:<memory_context> 段(spec §5.3)— CLAUDE.md / AGENTS.md + 4 tier 召回
        try:
            from argos_agent.memory import auto as _mem_auto
            _mem_block = _mem_auto._memory_context_block(
                workspace=self._workspace,
                project_id=_mem_auto.project_id_for(self._workspace),
                session_id=None,
            )
            if _mem_block:
                safe = safe + "\n\n" + _mem_block
        except Exception:  # noqa: BLE001 — 记忆模块故障不阻塞 run
            pass
        safe = safe + self._tool_signatures_block()
        try:
            from argos_agent import contracts
            _dom, contract_text = contracts.contract_for(goal)
            if contract_text:
                safe = safe + contract_text
        except Exception:  # noqa: BLE001 — 契约分类失败不影响主流程
            pass

        # ── 安全段:可用 MCP 工具清单(配了 ~/.argos/mcp.json 才注入;默认零预配 → 空,不注入)──
        try:
            from argos_agent import mcp_native
            mcp_summary = mcp_native.get_manager().tools_summary()
            if mcp_summary:
                safe = safe + "\n\n" + mcp_summary
        except Exception:  # noqa: BLE001 — MCP 连接/读取失败诚实降级为无 MCP
            pass

        if not self._cfg.recall:
            return safe

        # ── untrusted 段:skills(独立于 store,零模型兜底) + memory(需 store.recall)──
        skill_bodies: list[str] = []
        try:
            from argos_agent import skills as _skills
            skill_bodies = [
                f"## 技能:{s.name}\n{s.description}\n\n{s.body.strip()}"
                for s in _skills.recall(goal)
            ]
        except Exception:  # noqa: BLE001 — skill 召回失败诚实降级为无 skill
            skill_bodies = []

        memory_lines: list[str] = []
        if hasattr(self._store, "recall"):
            try:
                hits = self._store.recall(goal)  # type: ignore[attr-defined]
                memory_lines = [
                    f"- {rec.goal} → {rec.verdict or '?'}（{reason}）" for rec, reason in hits
                ]
            except Exception:  # noqa: BLE001
                memory_lines = []

        untrusted = format_untrusted(skill_bodies=skill_bodies, memory_lines=memory_lines)
        return compose_system(safe, untrusted=untrusted)

    async def _drive(self, goal: str, session_id: str) -> AsyncIterator["Event"]:
        """四阶段驱动(不可跳):plan → act(CodeAct 循环) → verify(门禁) → report。"""
        # 确保 session 行先于任何 event/message 落库(replay/resume 据 session_id 重建;幂等,
        # resume 时已存在则 no-op)。hasattr 守卫:最小 store 替身(无 session 概念)跳过。
        if hasattr(self._store, "ensure_session"):
            self._store.ensure_session(  # type: ignore[attr-defined]
                session_id, title=goal[:80], model=self._cfg.model_tier, system_snapshot="",
            )
        # ── hooks: SessionStart(spec §2.5 触发点表)──────────────────
        from argos_agent import config as _config
        try:
            tier_name = _config.active_tier().name
        except Exception:  # noqa: BLE001
            tier_name = "default"
        ss_payload = build_session_start_payload(
            session_id=session_id, cwd=str(self._workspace), model_tier=tier_name,
        )
        ss_result = await _hooks.fire("SessionStart", ss_payload,
                                      cwd=self._workspace, session_id=session_id)
        for h in ss_result.per_hook:
            yield HookFired(event_name="SessionStart", command=h.command,
                            success=h.success, returncode=h.returncode,
                            elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                            not_found=h.not_found, stop_reason=h.stop_reason,
                            error=h.error)
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

        # Plan mode spec §2.5:plan 模式 → plan 子循环(可多轮 keep_planning/refine)。
        # 退出条件:approve_start / approve_accept_edits。子循环里:流式模型一次 → 拼 markdown
        # → 投 PlanRendered → 挂起 _plan_decision_event 等 TUI 弹 PlanModal 决策。
        # ExitPlanMode 会把 _plan_decision 写好 + set event 唤醒 await(见 _plan_decision_event.set)。
        if self.mode == "plan":
            async for ev in self._run_plan_phase_loop(goal, messages, system):
                yield ev

        # ── act(CodeAct 循环)──
        async for ev in self._enter_phase("act"):
            yield ev
        step = 0
        report_note = ""   # 收尾时报告里诚实标注(如无测任务"未机检验证")。
        last_verdict: Any = None  # 最后一次 verify 结果,供 report 可见完成行诚实反映结局。
        escalated = False
        noaction_nudged = False   # 0 动作守卫:只催一轮,催过后第二次无代码块允许纯文字收尾(防死循环)。
        made_changes = False      # H2:本轮是否真发生过写操作(write_file/edit_file)。
        verify_nudged = False     # H2:改了代码却没声明验证 → 只催一轮(防误催纯读/无限催)。
        compactions = 0           # 上下文压缩次数上限,防压缩仍溢出时无限重试。
        text = ""                 # 在 while 外初始化:max_steps=0 等边界下收尾仍能安全 text.strip()
        while step < self._cfg.max_steps:
            # W3:流式 delta 过 StreamingContextScrubber,防模型把 untrusted 围栏吐回 UI 泄露。
            scrubber = StreamingContextScrubber()
            text = ""
            try:
                async for delta in self._model.stream(messages, system=system):
                    text += delta
                    clean = scrubber.feed(delta)
                    if clean:
                        yield TokenDelta(text=clean)
            except Exception as e:  # noqa: BLE001 — 上下文溢出 → 压缩重试;其余异常上抛给 run() 顶层兜底。
                from argos_agent.core.recovery import classify_error
                ce = classify_error(e)
                if (ce.should_compress and self._cfg.compaction and compactions < 3
                        and hasattr(self._store, "compact_messages")):
                    compactions += 1
                    self._store.compact_messages(session_id, keep_recent=5)   # type: ignore[attr-defined]
                    messages = self._store.get_messages(session_id)           # 重载压缩后线程(含本轮 goal)
                    continue   # 重试本 step(不 step+=1)
                raise
            tail = scrubber.flush()
            if tail:
                yield TokenDelta(text=tail)
            messages.append({"role": "assistant", "content": text})

            # 真验证门:抓本段里 agent 声明的验证命令(propose_verify('<cmd>')),登记到 _verify_cmd。
            # verify 阶段 harness 独立跑它(退出码为准);agent 碰不到执行 → 防篡改测试作弊。
            for m in _PROPOSE_VERIFY.finditer(text):
                self._on_propose_verify(m.group(1))
            # H1:声明了伪验证命令(echo/ls/pwd 等)→ 已拒登记,回灌一次让模型改用真命令。
            if self._verify_rejected is not None:
                messages.append({"role": "user", "content":
                    f"[Argos 验证门] `{self._verify_rejected}` 不是有效的验证命令(它永远通过、什么都不验证)。"
                    "propose_verify 需要真正能判定对错的测试/编译/lint 命令(如 pytest、cargo test、"
                    "ruff、mypy、tsc)。若此项目确实无可机检验证,就别声明、直接说明情况。"})
                self._verify_rejected = None

            # 真 TODO 拆解:抓本段里 agent 的 update_plan([...]) 子任务清单。变化才 yield PlanUpdate
            # (去重,不刷屏);活动栏据此渲染进度。同 propose_verify:host 侧解析(沙箱进程拿不到回调)。
            new_todos = extract_plan_todos(text)
            if new_todos is not None and new_todos != self._todos:
                self._todos = new_todos
                yield PlanUpdate(todos=new_todos)

            # CostUpdate:真 token(从 model.last_usage 累加)+ 真 elapsed,让状态栏/成本表走起来。
            usage = getattr(self._model, "last_usage", None) or {}
            self._tok_in += int(usage.get("input_tokens") or 0)
            self._tok_out += int(usage.get("output_tokens") or 0)
            self._cache_read += int(usage.get("cache_read") or 0)
            # 上下文窗口占用 = 本次调用【输入侧】token(input + cache),是【当前窗口】真实占用
            # (对齐 Claude Code 口径),与上面 _tok_in 的【会话累计】是两个不同的数,不可混。
            context_used = (int(usage.get("input_tokens") or 0)
                            + int(usage.get("cache_read") or 0)
                            + int(usage.get("cache_creation") or 0))
            # 成本:用已就绪的定价表算【会话累计】成本(此前硬编码 None → 永远 $(N/A) 是 bug)。
            # 模型不在 PRICING(用户自带模型且未配单价)→ 回退 None,UI 诚实显 $(N/A),
            # 而非 cost_of 对未知模型返回的 0.0(那会让 $(N/A) 变成失真的恒 $0.000)。
            from argos_agent.core.observability import PRICING, cost_of
            _tier = getattr(self._model, "tier", None)
            model_name = getattr(_tier, "model", "") if _tier is not None else ""
            _sc = cost_of({"input_tokens": self._tok_in, "output_tokens": self._tok_out}, model=model_name)
            cost = _sc.cost_usd if model_name in PRICING else None
            yield CostUpdate(
                tokens_in=self._tok_in, tokens_out=self._tok_out,
                cost_usd=cost, elapsed_s=time.time() - self._started,
                cache_read=self._cache_read, context_used=context_used,
            )

            code = extract_code_block(text)
            if code is not None:
                # ── PreToolUse hook fire(spec §2.5)────────────────
                tool_names = extract_tool_names(code)
                pre_payload = build_pre_payload(
                    session_id=session_id, cwd=str(self._workspace),
                    code=code, tool_names=tool_names,
                )
                pre_result = await _hooks.fire(
                    "PreToolUse", pre_payload,
                    cwd=self._workspace, session_id=session_id,
                )
                for h in pre_result.per_hook:
                    yield HookFired(event_name="PreToolUse", command=h.command,
                                    success=h.success, returncode=h.returncode,
                                    elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                                    not_found=h.not_found, stop_reason=h.stop_reason,
                                    error=h.error)
                # PreToolUse 阻塞:任一 fail 且非 timeout → 拒,反喂(spec D4 / §2.5)
                if not pre_result.success and not pre_result.timed_out:
                    reason = pre_result.stop_reason or "(无理由)"
                    messages.append({"role": "user", "content":
                        f"[Argos Hook] PreToolUse 工具调用被 hook 拒绝:"
                        f"\n{reason}\n请调整方案后再试,或与用户沟通。"})
                    step += 1
                    continue   # 不调 exec_code,走下一轮
                yield CodeAction(code=code, step=step)
                result = self._sandbox.exec_code(code)
                self._actions += 1
                # H2:记录本轮是否真发生写操作(host 侧解析代码块,同 propose_verify 路径)。
                # 用于"改了代码却没声明验证"的一次性催促,纯读/问答任务不触发。
                if "write_file(" in code or "edit_file(" in code:
                    made_changes = True
                # ── LSP didChange 触发点(spec §2.8)─────────────────────
                # 沙箱内 tools/files.py 一行不动;host loop 在 sandbox.exec_code
                # **成功后**(result.ok)解析 code 块抽 write_file/edit_file → 调
                # lsp_manager.sync_file_sync(走单例后台 loop,best-effort 失败不抛)。
                if result.ok:
                    try:
                        from argos_agent import lsp as _lsp
                        from argos_agent.lsp.trigger import (
                            extract_file_writes, extract_file_paths,
                        )
                        _lsp_mgr = _lsp.get_manager()
                        if _lsp_mgr is not None:
                            # 写过的 path:用 model 抽的 content(若 write_file 抓得)
                            written: dict[str, str] = {
                                p: c for p, c in extract_file_writes(code)
                            }
                            # edit_file 后:用 workspace 实际最新内容(覆盖 model 抽)
                            for rel_path in extract_file_paths(code):
                                if rel_path in written:
                                    continue
                                abs_p = self._workspace / rel_path
                                if abs_p.exists():
                                    try:
                                        written[rel_path] = abs_p.read_text(
                                            encoding="utf-8", errors="replace",
                                        )
                                    except OSError:  # noqa: PERF203
                                        pass
                            from argos_agent.lsp.manager import sync_file_sync
                            for rel_path, content in written.items():
                                abs_p = self._workspace / rel_path
                                sync_file_sync(_lsp_mgr, str(abs_p), content, timeout=3.0)
                    except Exception as _lsp_exc:  # noqa: BLE001
                        log.debug("LSP trigger skipped: %s", _lsp_exc)
                yield CodeResult(
                    step=step, stdout=result.stdout,
                    value_repr=result.value_repr, exc=result.exc, ok=result.ok,
                )
                # ── PostToolUse hook fire(spec §2.5)───────────────
                post_payload = build_post_payload(
                    session_id=session_id, cwd=str(self._workspace),
                    code=code, tool_names=extract_tool_names(code),
                    stdout=result.stdout, value_repr=result.value_repr,
                    exc=result.exc, ok=result.ok,
                )
                post_result = await _hooks.fire(
                    "PostToolUse", post_payload,
                    cwd=self._workspace, session_id=session_id,
                )
                for h in post_result.per_hook:
                    yield HookFired(event_name="PostToolUse", command=h.command,
                                    success=h.success, returncode=h.returncode,
                                    elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                                    not_found=h.not_found, stop_reason=h.stop_reason,
                                    error=h.error)
                # PostToolUse 非 0 不阻塞(只 warn),continue 不受影响
                # I2 + W2(§6.5):只在【本步新签了 Receipt】且【HMAC 核验通过】时投 ToolReceipt。
                # accept_receipt 在投事件前核验回执 —— 伪造/篡改的回执拒投(防谎报工具执行)。

                # #9 T5:auto-capture tool repeat fail(同 tool ≥3 次失败 → 记)
                if not result.ok and result.exc:
                    try:
                        from argos_agent.memory import auto as _mem_auto
                        from argos_agent.memory.auto import project_id_for as _pid
                        _tool_names = extract_tool_names(code)
                        for _t in _tool_names:
                            _mem_auto.capture_event(
                                "tool_repeat_fail",
                                project_id=_pid(self._workspace),
                                tool=_t,
                                error=str(result.exc)[:200],
                            )
                    except Exception:  # noqa: BLE001
                        pass
                elif result.ok:
                    # 成功一次:同 tool 的失败计数清零(避免下次的真 fail 因累计误触)
                    try:
                        from argos_agent.memory import auto as _mem_auto
                        from argos_agent.memory.auto import (
                            project_id_for as _pid,
                            _reset_tool_fail_counter as _rst,
                        )
                        for _t in extract_tool_names(code):
                            _rst(_pid(self._workspace), _t)
                    except Exception:  # noqa: BLE001
                        pass

                if self._broker is not None:
                    new_receipt = self._broker.take_receipt()
                    if new_receipt is not None and self._harness.accept_receipt(new_receipt):
                        yield ToolReceipt(receipt=new_receipt)
                # 工作流提议:agent 本段调了 propose_workflow({...}) → 异步态校验+审批+引擎执行+结果回灌。
                raw_spec = extract_workflow_spec(text)
                if raw_spec is not None:
                    async for ev in self._run_workflow(raw_spec, messages):
                        yield ev
                    step += 1
                    continue   # 工作流结果已作为 feedback 回灌,跳过常规 exec feedback
                feedback = self._feedback(result)
                if self._todos:
                    # 锚机制:每个 act step 把当前 todos 摘要回灌(随执行结果一起),
                    # 防长任务在多步后丢失目标/漏更状态。
                    feedback += "\n\n" + self._todos_summary(self._todos)
                messages.append({"role": "user", "content": feedback})
                step += 1
                continue

            # 无代码块。但若整轮还没有任何动作(_actions==0),说明模型只是口头说说没真做
            # —— 不得当"完成"收尾(防"说了没做"伪完成)。回灌催促,继续要它真执行。
            # 只催一轮(noaction_nudged 兜底):催过后第二次仍无代码块,允许它作为纯文字答复
            # 收尾(纯问答如"你好"本就无需动作;避免无限催促,max_steps 再兜底)。
            if self._actions == 0 and not noaction_nudged:
                noaction_nudged = True
                messages.append({"role": "user", "content":
                    "你还没有产出任何 ```python 代码动作就停了。如果要做事,请输出代码块真正执行;"
                    "如果确认无需任何动作即可回答,请直接给出最终答复(我会据此收尾)。"})
                step += 1
                continue

            # H2:改了代码却没声明【有效】验证命令 → 回灌一次催促它声明真验证(测试/编译/lint),
            # 再宣布完成。只催一轮(verify_nudged 兜底):仍不声明则照常走诚实"未机检验证"收尾,
            # 不无限催;纯读/问答任务(made_changes=False)不触发,避免误催。
            if made_changes and self._verify_cmd is None and not verify_nudged:
                verify_nudged = True
                messages.append({"role": "user", "content":
                    "你改动了代码但没有声明验证命令。请用 `propose_verify('<测试/编译/lint 命令>')` "
                    "声明如何机检本次改动(如 pytest、cargo test、ruff、mypy、tsc),我会独立运行它以退出码为准。"
                    "若此项目确实无可机检验证,直接说明即可(我会如实标'未机检验证'收尾)。"})
                step += 1
                continue

            # 有过动作(或已催过一轮)→ 模型宣布"完成" → 进 verify。
            # W1:先 enter_phase("verify")(投 PhaseChange),再 run_verify_gate(投 VerifyVerdict)。
            async for ev in self._enter_phase("verify"):
                yield ev

            # W2:run_verify_gate 跑 verifier 出三态 Verdict,投 VerifyVerdict;真问题超
            # max_rounds 时它自己投 Escalation。loop 据返回的 verdict 决定 break / bounce。
            verdict = await self._harness.run_verify_gate(
                self._verify_cmd, attempt=self._fail_count + 1
            )
            last_verdict = verdict
            for ev in self._hbus.drain():
                yield ev

            # #9 T5:auto-capture verify fail(失败命令 + stderr hash + 200 字 snippet)
            if verdict.status == "failed" and self._verify_cmd:
                try:
                    from argos_agent.memory import auto as _mem_auto
                    from argos_agent.memory.auto import project_id_for as _pid
                    import hashlib as _hl
                    _snip = (verdict.detail or "")[:200]
                    _mem_auto.capture_event(
                        "verify_fail",
                        project_id=_pid(self._workspace),
                        cmd=self._verify_cmd,
                        stderr_hash=_hl.sha1(_snip.encode()).hexdigest()[:16],
                        stderr_snippet=_snip,
                    )
                except Exception:  # noqa: BLE001
                    pass

            # Defense-in-depth(Phase 4 #3):verify_cmd is None 时绝不以 passed 收尾 ——
            # 非规范 verifier 可能对无测任务返回 passed;必须走诚实完成路径标 NO_TEST_LABEL。
            if verdict.status == "passed" and self._verify_cmd is not None:
                break                        # 通过 → 收尾
            if self._harness.is_honest_completion(verdict, verify_cmd=self._verify_cmd):
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
                f"[Argos 验证门] 你声称完成,但验证 `{self._verify_cmd}` 未通过/不可信:"
                f"\n{verdict.detail}\n请用工具定位并修复,改完再说完成。"
            )
            messages.append({"role": "user", "content": bounce})
            step += 1

        # 跨轮上下文:把本轮【最终 assistant 回答】持久化(get_messages 跨轮还原时带回)。
        # 否则历史只剩单边 user goal、agent 记不住自己上轮答了啥 → "好的/继续"接不上。
        # 只存最终答(非每个 act 步):内部代码步是 scratch,产物已落盘可 read_file 回看,
        # 跨轮上下文保持精简;增长由 compaction(批3)兜底。
        # 关键修复:即使最终段为空(模型用空 turn 宣布完成、或答复被 scrubber 清空),也必须落
        # 一条占位 assistant —— 否则本轮历史只剩单边 user(goal),连续多轮会在 DB 堆出
        # [user, user, user...],模型看不出是独立任务、也记不住自己做过啥(=用户看到的"没串上下文")。

        # #9 T5:auto-capture escalation / run_success(escalation 在 run 末尾,capture 一次)
        try:
            from argos_agent.memory import auto as _mem_auto
            from argos_agent.memory.auto import project_id_for as _pid
            if escalated:
                _mem_auto.capture_event(
                    "escalation_decision",
                    project_id=_pid(self._workspace),
                    reason="max_rounds_exceeded",
                    user_reply="escalated",
                )
            elif not report_note and step >= 5:
                # run_success:passed 且 ≥5 步 → 记 goal + key_cmd
                _mem_auto.capture_event(
                    "run_success",
                    project_id=_pid(self._workspace),
                    goal=(self._user_goal or "")[:120],
                    steps=step,
                    key_cmd=(self._verify_cmd or "")[:120],
                )
        except Exception:  # noqa: BLE001
            pass

        persisted = text.strip()
        if not persisted:
            if escalated:
                persisted = "(本轮结束:未通过验证,已上报)"
            elif report_note:
                persisted = f"(本轮完成:{report_note})"
            else:
                persisted = "(本轮完成)"
        self._store.append_message(session_id, role="assistant", content=persisted)

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
        # ── Stop hook fire(spec §2.5)───────────────────────
        stop_payload = build_stop_payload(
            session_id=session_id, cwd=str(self._workspace),
            goal=goal, verdict_status=(last_verdict.status
                if last_verdict is not None else "unknown"),
            actions=self._actions, elapsed_s=time.time() - self._started,
            escalated=escalated,
        )
        stop_result = await _hooks.fire(
            "Stop", stop_payload,
            cwd=self._workspace, session_id=session_id,
        )
        for h in stop_result.per_hook:
            yield HookFired(event_name="Stop", command=h.command,
                            success=h.success, returncode=h.returncode,
                            elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                            not_found=h.not_found, stop_reason=h.stop_reason,
                            error=h.error)
        # Stop 非 0 不阻塞
        yield TokenDelta(text=done)

    async def _run_workflow(self, raw_spec: dict, messages: list) -> "AsyncIterator[Event]":
        """校验 spec → WorkflowProposed(预览)→ 审批(await gate,异步态不死锁)→ 引擎异步跑 →
        WorkflowDone → 结果作 feedback 回灌 parent。校验失败/被拒/无引擎 → 诚实回错,不崩 run。"""
        from argos_agent.tui.events import WorkflowProposed, WorkflowDone
        from argos_agent.workflow.result import render_preview
        from argos_agent.workflow.spec import WorkflowSpecError, parse_spec
        import uuid as _uuid
        if self._workflow_engine_factory is None:
            messages.append({"role": "user", "content": "[工作流引擎未接入,无法编排;请单线程继续。]"})
            return
        try:
            spec = parse_spec(raw_spec)
        except WorkflowSpecError as e:
            messages.append({"role": "user", "content": f"[工作流被拒:规格非法 — {e}。请修正或单线程继续。]"})
            return
        preview = render_preview(spec)
        call_id = _uuid.uuid4().hex[:12]
        yield WorkflowProposed(name=spec.name, description=spec.description,
                               preview=preview, call_id=call_id)
        gate = self._broker.gate if self._broker is not None else None
        if gate is not None:
            decision = await gate.request("run_workflow", {"name": spec.name},
                                          description=preview, risk="high",
                                          timeout=120.0, call_id=call_id)
            if not decision.approved:
                messages.append({"role": "user", "content": "[工作流被拒,单线程继续。]"})
                return
        engine = self._workflow_engine_factory()
        async for ev in engine.run(spec):
            yield ev
        result = engine.last_result
        synth = result.synthesis if result else "(工作流无结果)"
        notes = result.notes if result else ()
        yield WorkflowDone(name=spec.name, synthesis=synth, notes=notes)
        summary = f"[工作流「{spec.name}」结果]\n{synth}"
        if notes:
            summary += "\n注记:" + " / ".join(notes)
        messages.append({"role": "user", "content": summary})

    # ── Plan mode (spec §2.5) ──────────────────────────────────────────
    async def _run_plan_phase_loop(
        self, goal: str, messages: list[dict], system: str,
    ) -> "AsyncIterator[Event]":
        """Plan mode 子循环:流式模型一次 → 拼 markdown → 投 PlanRendered → 挂起等决策。

        退出条件:approve_start / approve_accept_edits(均跳出,后者切 _approval_level_override)。
        子循环条件:keep_planning(同 goal 再来一轮) / refine(feedback 注入 messages 再来一轮)。
        注:PlanUpdate (todos) 也在每个 plan 轮内同步 yield,活动栏进度随 plan 更新。
        """
        while True:
            async for ev in self._plan_phase_round(goal, messages, system):
                yield ev
            # 挂起等 TUI 弹 PlanModal 决策 —— ExitPlanMode 会 set event 唤醒。
            await self._plan_decision_event.wait()
            decision = self._plan_decision
            if decision is None:
                # 边界防御:正常路径 ExitPlanMode 必写 _plan_decision;None 时按 approve 兜底,
                # 不让 loop 永远挂死(诚实:host 异常应走"默许继续"而非崩 run)。
                decision = PlanExitDecision(action="approve_start")
            if decision.action == "approve_start":
                # 跳出子循环 → _drive 继续走 act 阶段。
                return
            if decision.action == "approve_accept_edits":
                # 临时切 approval_level 到 ACCEPT_EDITS(act 阶段完了在 _reset_run_state 恢复)。
                from argos_agent.approval import ApprovalLevel
                self._approval_level_override = ApprovalLevel.ACCEPT_EDITS
                return
            if decision.action == "keep_planning":
                # 再来一轮 plan 子循环:重置 event + decision(否则下次 await 立即返)。
                self._plan_decision = None
                self._plan_decision_event = asyncio.Event()
                continue
            if decision.action == "refine":
                # feedback 注入 messages 作 user message,重置 event + decision,再来一轮。
                feedback_text = (decision.feedback or "").strip()
                if feedback_text:
                    messages.append({"role": "user", "content": feedback_text})
                self._plan_decision = None
                self._plan_decision_event = asyncio.Event()
                continue
            # 未知 action(spec 锁 4 选项,此路径防御性兜底)→ 按 approve_start 跳出,不挂死。
            return

    async def _plan_phase_round(
        self, goal: str, messages: list[dict], system: str,
    ) -> "AsyncIterator[Event]":
        """单轮 plan:流式模型一次 + 抓 update_plan todos + 拼 markdown 投 PlanRendered。

        不跑代码块 —— plan 模式沙箱工具 dispatcher 抛 PlanModeError(同 e2e),若模型非要在
        plan 阶段塞代码块,执行会被挡,我们仍继续走完 plan(诚实:不假装 plan 阶段执行了写)。
        """
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

        # 抓 update_plan([...]) → PlanUpdate 事件(活动栏任务进度)。
        new_todos = extract_plan_todos(text)
        if new_todos is not None and new_todos != self._todos:
            self._todos = new_todos
            yield PlanUpdate(todos=new_todos)

        # CostUpdate 同步一轮(让成本栏在 plan 阶段也走起来)。
        usage = getattr(self._model, "last_usage", None) or {}
        self._tok_in += int(usage.get("input_tokens") or 0)
        self._tok_out += int(usage.get("output_tokens") or 0)
        self._cache_read += int(usage.get("cache_read") or 0)
        from argos_agent.core.observability import PRICING, cost_of
        _tier = getattr(self._model, "tier", None)
        model_name = getattr(_tier, "model", "") if _tier is not None else ""
        _sc = cost_of({"input_tokens": self._tok_in, "output_tokens": self._tok_out}, model=model_name)
        cost = _sc.cost_usd if model_name in PRICING else None
        yield CostUpdate(
            tokens_in=self._tok_in, tokens_out=self._tok_out,
            cost_usd=cost, elapsed_s=time.time() - self._started,
            cache_read=self._cache_read,
            context_used=(int(usage.get("input_tokens") or 0)
                          + int(usage.get("cache_read") or 0)
                          + int(usage.get("cache_creation") or 0)),
        )

        # 拼 markdown → 投 PlanRendered 事件(TUI 弹 PlanModal 用此渲染)。
        # 工具调用序列在 plan 阶段空(plan 模式不执行);involves files 段也空,等 act 后回填。
        plan_md = PlanRenderer.render(
            goal=goal, todos=list(self._todos), tool_calls=[],
        )
        yield PlanRendered(plan_md=plan_md)

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
