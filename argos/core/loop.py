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
import hashlib
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from argos.core.harness import Harness
from argos.core.honesty import (
    HONESTY_SYSTEM, StreamingContextScrubber, compose_system, format_untrusted,
)
from argos.core.plan_mode import PlanExitDecision, PlanRenderer
from argos.core.types import ModelTierName, TRIVIAL_VERIFY_BINS
from argos.protocol.events import (
    CodeAction, CodeResult, CostUpdate, Escalation, Error, Event, PhaseChange,
    MemoryRecallEvent, PlanDecisionRequest, PlanRendered, PlanUpdate,
    TokenDelta, ToolReceipt,
)
from argos.protocol.events import EventBus
from argos import hooks as _hooks
from argos.i18n import is_error_result, t as _i18n_t
from argos.hooks.payload import (
    build_post_payload, build_pre_payload, build_session_start_payload,
    build_stop_payload, extract_tool_names,
)
from argos.hooks.events import HookFired

if TYPE_CHECKING:
    from argos.memory.store import ArgosStore
    from argos.sandbox.backend import SandboxBackend
    from argos.sandbox.broker import CapabilityBroker

# 延迟 import ApprovalLevel 避免循环;用 TYPE_CHECKING 拿类型,运行时懒 import。
try:
    from argos.approval import ApprovalLevel as _ApprovalLevel
    _DEFAULT_APPROVAL_LEVEL: Any = _ApprovalLevel.CONFIRM
except Exception:  # noqa: BLE001
    _DEFAULT_APPROVAL_LEVEL = None  # Phase 4 接线前的极端兜底

_CODE_BLOCK = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

# 真验证门:从模型【代码块文本】里抓 propose_verify('<cmd>') 的命令参数(host 侧解析)。
# 沙箱是独立子进程(Seatbelt),host 回调无法注入其命名空间 —— 故 host 在 act 循环里解析
# agent 输出登记验证命令;沙箱内的 propose_verify() 工具仅给个登记回执(真执行在 host verify 阶段)。
# (?:[a-zA-Z]+)? 容忍 f/r/b 等字符串前缀,以【检测】f-string verify(propose_verify(f'...'))——
# 过去完全失配 → 验证命令静默丢失。抓到后 _on_propose_verify 检测 {} 占位再诚实拒(#11)。
_PROPOSE_VERIFY = re.compile(r"propose_verify\(\s*(?:[a-zA-Z]+)?['\"](.+?)['\"]\s*\)")

# A2 Major-2 修正:propose_dom_verify(url=..., selector=..., expected_text=...) host 侧解析。
# 与 propose_verify 同构:沙箱内调用仅返回登记回执,真断言在 host verify 阶段由 DomProber 执行。
# 捕获三个关键字参数(都可选);只有 url 合法（http/https）才登记,selector/expected_text 可省略。
# url 校验:拒 file:// 等非 http(s) 协议;selector/expected_text 各不超过 500 字符（防滥用）。
_PROPOSE_DOM_VERIFY = re.compile(
    r"propose_dom_verify\s*\(([^)]*)\)",
    re.DOTALL,
)
_DOM_KW_URL = re.compile(r"""url\s*=\s*['"]([^'"]+)['"]""")
_DOM_KW_SEL = re.compile(r"""selector\s*=\s*['"]([^'"]+)['"]""")
_DOM_KW_EXP = re.compile(r"""expected_text\s*=\s*['"]([^'"]+)['"]""")
# 2d GUI 验证:propose_gui_verify(expected_text=...) host 侧解析(与 propose_dom_verify 同构)。
# 沙箱内调用仅返回登记回执;真断言在 host verify 阶段由 GuiProber 截图+OCR 独立执行。
_PROPOSE_GUI_VERIFY = re.compile(r"propose_gui_verify\s*\(([^)]*)\)", re.DOTALL)
_GUI_KW_EXP = re.compile(r"""expected_text\s*=\s*['"]([^'"]+)['"]""")
# 反平凡 expected_text:过短的断言(如单字符 'e')几乎必命中任意屏幕 OCR,会被用来伪造 passed
# (agent 同时选断言又控屏)。最小长度门槛(类比 propose_verify 拒 echo/true/: 的平凡命令)。
# GUI:过短 → 拒登记;DOM:过短 → 当作未提供(走弱证据路径,最高 unverifiable,不产 passed)。
_PROBE_EXPECTED_MIN = 3
_DOM_URL_ALLOWED = re.compile(r"^https?://", re.I)
_DOM_PARAM_MAX = 500  # selector / expected_text 最大长度，防滥用

# ponytail: 2 consecutive identical (code,stdout) pairs = stuck; break + escalate.
STAGNATION_LIMIT = 2

# 反琐碎集 TRIVIAL_VERIFY_BINS 已上移 argos.core.types(canonical;Verifier 的 canonical 门、
# loop 的 propose_verify 门、workflow stage verify 校验共用同一份,杜绝多入口门不一致)。

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

# 单次工具输出回灌上限(head+tail 保留)。每个 CodeAct 步把整条工具 stdout 当 user 消息追加进
# messages,而 messages 每步全量重发 → 病态大输出(冗长 build log、run_command dump)会逐步累加、
# 每步重复计费(2026-06-22 真机:查天气 ↑77.7k)。此上限 > web_extract 自身 8000 截断,故正常
# 取页/搜索结果原样通过,只兜底真正病态的大输出。
_FEEDBACK_MAX_CHARS = 10000


def _clamp_feedback(out: str, limit: int = _FEEDBACK_MAX_CHARS) -> str:
    """大输出 head+tail 截断后回灌(报错/栈多在尾部,故首尾都保留);短输出原样返回。"""
    if len(out) <= limit:
        return out
    head = out[: limit * 2 // 3]
    tail = out[-(limit // 3):]
    elided = len(out) - len(head) - len(tail)
    return f"{head}\n…[{elided} chars elided]…\n{tail}"


def extract_code_block(text: str) -> str | None:
    """从模型输出抽第一个 Python 代码块;无则 None。"""
    m = _CODE_BLOCK.search(text)
    if not m:
        return None
    return m.group(1).strip()


# 0 动作守卫的"疑似偷懒"判定(2026-06-14):act 阶段模型无 ```python 代码块时,只有看起来
# "声称要做 / 已完成却没真做"(空 / 含将做或完成措辞)才催一轮防伪完成;实质对话答复(问候 /
# 问答 / 解释,不含这些措辞)→ 直接收尾,不白调一轮(对齐 Claude Code 等:对话理解即回)。
_LAZY_CLAIM_ZH: tuple[str, ...] = (
    "我来", "我先", "我会", "我将", "我去", "让我", "马上", "稍等", "正在", "接下来",
    "完成了", "已完成", "已经完成", "做完了", "修复了", "改好了", "搞定", "处理好了",
)
_LAZY_CLAIM_EN: tuple[str, ...] = (
    "i'll", "i will", "let me", "i'm going to", "i am going to", "i'll go",
    "i've ", "i have ", "now i ", "fixed", "done.", "completed", "finished",
)


def _looks_like_lazy_claim(text: str) -> bool:
    """模型无代码块时是否"疑似偷懒"(需催一轮)。

    True  → 空 / 含"将做或声称完成"措辞但 0 动作(可能"说了没做"伪完成)→ 催。
    False → 实质对话答复(问候 / 问答 / 解释)→ 直接收尾(对话秒回,不白调一轮)。
    """
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    return (any(kw in t for kw in _LAZY_CLAIM_ZH)
            or any(kw in low for kw in _LAZY_CLAIM_EN))


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
        limit = min(len(text), i + 65536)   # #10 防 O(n²):单次配平扫描钳 64KB 窗口,超窗口视为未配平
        while j < limit and depth > 0:
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
        limit = min(len(text), i + 65536)   # #10 防 O(n²):单次配平扫描钳 64KB 窗口,超窗口视为未配平
        while j < limit and depth > 0:
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
        "\n\n<environment>\n"
        f"- Working directory (relative paths resolve against it): {workspace}\n"
        f"- OS: {platform.system()} {platform.machine()}\n"
        f"- Today: {date.today().isoformat()}\n"
        "These are known facts — don't probe them at runtime (os.getcwd / pathlib.Path.cwd / pwd).\n"
        "</environment>"
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
    # #12 Context 可视化:主动压缩阈值(0-1;0 = 不主动压,只走既有 error 应急路径;
    # spec §9.5 锁 default=0.8,旧 config.json 缺字段不破)。整体压缩=高水位安全网,
    # safe_compact_threshold 钳制其绝不在 50% 以下触发(spec 2026-06-07 治 context rot)。
    compact_threshold: float = 0.8
    # context rot 持续相关性修剪激进度(0=不修剪;0<a<0.66 折叠过期工具输出;
    # a>=0.66 另折叠被取代旧计划/死路错误)。优先修剪而非整体压缩(spec 2026-06-07)。
    prune_aggressiveness: float = 0.5
    # Task 1.2: hard budget ceilings — None = no limit (pure-additive, behavior identical when unset).
    max_tokens_in: int | None = None    # cumulative input-token ceiling (works even for un-priced models)
    # 成本上限(USD)。仅当模型名存在于 PRICING 表时才会触发;不在表内时 cost 计算为 None,
    # 此分支被静默跳过,用户不会收到任何突破提示。对自部署/未定价模型应优先使用 max_tokens_in。
    max_cost_usd: float | None = None


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
        tool_allowlist: "list[str] | None" = None,  # 角色子 agent 的工具白名单(权威);None=旧 read_only 派生
        workflow_engine_factory: Callable[[], object] | None = None,
        router: Any = None,    # #11 per-task routing(契约 §11):ModelRouter | None
        mcp_manager: Any = None,  # per-session McpManager 实例(AppComponents 注入;None=模块级单例 fallback)
        capability_hints: dict[str, str] | None = None,  # P4 策略生成:registry verify_hint 聚合;None=空 dict
        dom_prober: Any = None,  # A2 L3 DOM 探针:DomProber | None;None=未接入,行为同现状(L3 跳过)
        gui_prober: Any = None,  # 2d GUI 探针:GuiProber | None;None=未接入,GUI 验证 lane 跳过
        manage_runtime_context: bool = False,  # inline 路径自建 runtime 上下文(daemon 在 worker 外部自设;此开关给 inline)
        project_mode: bool = False,  # managed 时建立的上下文是否 project 模式(verify_dir==workspace,篡改可见)
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
        self._tool_allowlist = tool_allowlist  # 角色白名单(权威):非 None 时 spawn 传给沙箱做 ∩
        self._mcp_manager = mcp_manager  # per-session MCP 管理器(None=fallback 到模块级单例)
        # 工作流引擎工厂:None=未接入(诚实回错,不崩 run);非 None=act 段抓到 propose_workflow 后
        # 在异步态校验+审批+异步跑引擎+结果回灌(每次提议 new 一个引擎,RAII 不复用状态)。
        self._workflow_engine_factory = workflow_engine_factory
        # P4 策略生成:registry verify_hint 聚合(app_factory 透传);None 退空 dict(零变更)。
        self._capability_hints: dict[str, str] = capability_hints or {}
        # A2 L3 DOM 探针:DomProber | None;None=未接入,_pick_strategy_cmd 跳过 L3(向后兼容)。
        self._dom_prober = dom_prober
        # A2 L3 挂起策略:_pick_strategy_cmd 选中 L3 时存此字段(verify_cmd 仍 None),
        # verify 阶段检测到此字段则走 DomProber 路径而非 run_verify_gate。每轮 reset。
        self._pending_l3_strategy: "Any | None" = None
        # A2 Major-2:propose_dom_verify 声明时附带的 expected_text（可为空串）。
        # 与 _pending_l3_strategy 同生命周期（一起 reset/消费）；覆盖 capability_hints['dom_expected_text']。
        self._pending_dom_expected_text: str = ""
        # 2d GUI 探针 + 挂起 expected_text(propose_gui_verify 声明时存;verify 阶段消费)。
        self._gui_prober = gui_prober
        self._pending_gui_expected_text: str = ""
        # P0 护城河:inline 路径(build_loop_factory)恒 verify_dir==workspace,却此前从不 set_context →
        # runtime.current() 落默认沙盒(project_mode=False)→ guard_project_tests 返 0、verify 跑错目录。
        # managed=True 时 run() 起始自建上下文,与 daemon worker.py 的 set_context 对称。daemon 路径
        # (build_run_stack)不开此开关 → worker 仍自管,行为零变更。
        self._manage_runtime_context = manage_runtime_context
        self._project_mode = project_mode
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
        # v6 §4 ACP PlanDecisionRequest:call_id → asyncio.Event 注册表。
        # daemon 路径通过 respond_plan_decision(call_id, action, feedback) 唤醒 loop;
        # TUI inline 路径仍走 ExitPlanMode(loop, ...)→ _plan_decision_event,二路均兼容。
        # 每次 _plan_phase_round 起手生成新 call_id,超时兜底默认 cancel。
        self._plan_call_registry: dict[str, asyncio.Event] = {}
        # #11 per-task routing(spec §10;契约 §11):router 不为 None 时每步按
        # (tool, code, phase) 选 tier;_current_tier 跟踪当前步实际 tier,CostUpdate 附
        # tier_name 字段(spec §15.2 可见性防线)。router=None 走原路径(零破坏既有 1507 测试)。
        self._router = router
        self._current_tier: str = config.model_tier
        # #12 Context 可视化(spec §9.2):主动压缩状态。
        # _last_compact_used:压前 used,用于 5% buffer 幂等(D9)。
        # _messages_override:压后 reload 的 messages 列表,while 顶部取一次后清空(D16)。
        from argos.context.threshold import LastCompactedAt as _LCA
        self._last_compact_used: _LCA | None = None
        self._messages_override: list[dict] | None = None
        # context rot 三层防线(spec 2026-06-07):
        # _compacted:本 run 是否发生过(有损)整体压缩;_reverified_since_compact:压缩之后
        # 是否真重跑过 verify。压缩后必须重验才认 passed(trust_passed_after_compaction 兜底)。
        self._compacted: bool = False
        self._reverified_since_compact: bool = True
        self._current_goal: str = ""    # 本轮任务目标(不可丢核心;run 起始写入,压缩后用于核心锚)
        self._user_goal: str = ""      # run() 起始写入,供收尾 capture_event("run_success") 记 goal;
                                         # 修过 bug:之前从未赋值,run_success 落库 goal 恒空,污染召回。

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
        # A2 L3:每轮重置挂起 L3 策略(防上轮残留泄漏)。
        self._pending_l3_strategy = None
        self._pending_dom_expected_text = ""
        self._pending_gui_expected_text = ""   # 2d:每轮重置 GUI 验证声明

    def _on_propose_verify(self, cmd: str) -> bool:
        """agent 调 propose_verify('<cmd>') 时登记验证命令(host 侧;真执行在 verify 阶段)。

        H1 防假绿:拒绝 echo/true/ls/pwd/cat 等【永远通过、什么都不验证】的伪命令 —— 否则弱模型
        可声明 `echo ok` 让 verify 门返 passed 谎报"已验证通过"。伪命令不登记 → 落回"未机检验证"
        的诚实路径(而非假绿)。返回是否登记成功(False=被拒,供调用方回灌反馈)。

        W5 默认开启(任务:TB 适配器):bridge 已配 verify(LoopConfig.verify_cmd)时,
        agent 的 propose_verify 一律拒登记 —— 否则弱模型会用 `cat /app/...` 或自造
        `python -c "import os; p=..."` 覆盖桥接的 docker verify,导致 verify 永远跑空。
        关掉(老 sandbox 流程用)设 ARGOS_BRIDGE_VERIFY_LOCK=0。
        """
        cmd = (cmd or "").strip()
        if not cmd:
            return False
        # #11 f-string 检测:host 侧独立跑验证、拿不到沙箱变量,无法求值 f-string 占位({...})。
        # 含占位的命令拒登记 + 回灌告知用普通字面量(否则 verify 跑字面 {x} 必失败/静默丢失)。
        if "{" in cmd and "}" in cmd:
            self._verify_rejected = cmd
            self._verify_rejected_fstring = True
            return False
        # #29:ARGSOS_BRIDGE_VERIFY_LOCK 是拼写错误;正确名是 ARGOS_BRIDGE_VERIFY_LOCK。
        # 向后兼容:接受旧名(ARGSOS_)或新名(ARGOS_),取其中任一为"0"则解锁。
        if (os.environ.get("ARGOS_BRIDGE_VERIFY_LOCK", "1") != "0"
                and os.environ.get("ARGSOS_BRIDGE_VERIFY_LOCK", "1") != "0") \
                and self._cfg.verify_cmd is not None and self._cfg.verify_cmd.strip():
            self._verify_rejected = cmd
            return False
        try:
            bin_name = Path(shlex.split(cmd)[0]).name
        except (ValueError, IndexError):
            return False
        if bin_name in TRIVIAL_VERIFY_BINS:
            self._verify_rejected = cmd   # 供 act 循环回灌一句"这不是验证命令"
            return False
        self._verify_cmd = cmd
        return True

    def _on_propose_dom_verify(self, raw_args: str) -> bool:
        """agent 调 propose_dom_verify(url=..., selector=..., expected_text=...) 时登记 L3 策略。

        与 propose_verify 同构：
          · host 侧解析代码文本（沙箱子进程拿不到回调）。
          · url 必须是 http(s)；拒 file:// 等协议（安全）。
          · selector / expected_text 各不超过 500 字符（防滥用）。
          · 有显式 expected_text 时走强证据路径（可产 passed/failed）；
            无 expected_text 时走弱证据路径（最高 unverifiable）。
          · 构造 L3 VerifyStrategy 存入 _pending_l3_strategy（等同
            _pick_strategy_cmd 的 L3 分支，但来自 agent 显式声明，更可靠）。
          · 只有 _dom_prober 已注入才生效；否则静默忽略（向后兼容）。
          · 若 _verify_cmd 已设（显式命令优先）→ 忽略（不覆盖）。

        返回是否登记成功（False=被拒/忽略，True=已写入 _pending_l3_strategy）。
        """
        # 显式 verify_cmd 优先 —— 已有命令不被 DOM 声明覆盖
        if self._verify_cmd is not None and self._verify_cmd.strip():
            return False
        # DomProber 未注入 → 静默忽略（向后兼容）
        if self._dom_prober is None:
            return False

        # 解析关键字参数
        url_m = _DOM_KW_URL.search(raw_args)
        sel_m = _DOM_KW_SEL.search(raw_args)
        exp_m = _DOM_KW_EXP.search(raw_args)

        url = url_m.group(1).strip() if url_m else ""
        selector = sel_m.group(1).strip() if sel_m else "body"
        expected_text = exp_m.group(1).strip() if exp_m else ""
        # 反平凡:过短的 expected_text 几乎必命中,会被用来伪造 passed → 当作未提供
        # (走弱证据路径,最高 unverifiable,不产 passed)。
        if expected_text and len(expected_text) < _PROBE_EXPECTED_MIN:
            expected_text = ""

        # url 校验：必须 http(s)，拒其余协议（file://, ftp://…）
        if not url or not _DOM_URL_ALLOWED.match(url):
            return False
        # 长度上限防滥用
        if len(selector) > _DOM_PARAM_MAX or len(expected_text) > _DOM_PARAM_MAX:
            return False

        # 构造 L3 VerifyStrategy 并存入 _pending_l3_strategy
        try:
            from argos.verify.strategy import VerifyStrategy
            hints: dict[str, str] = {
                "dom_url": url,
                "dom_selector": selector,
            }
            if expected_text:
                hints["dom_expected_text"] = expected_text
            # 通过已有的 _l3_dom_assert 构造器（重用 rationale 逻辑）
            from argos.verify.strategy import _l3_dom_assert
            strategy = _l3_dom_assert(hints)
            self._pending_l3_strategy = strategy
            # 与策略一起存 expected_text，供 _run_dom_probe_verdict 传给 DomProber
            self._pending_dom_expected_text = expected_text
            return True
        except Exception:  # noqa: BLE001 — fail-closed，任何异常静默忽略
            return False

    def _on_propose_gui_verify(self, raw_args: str) -> bool:
        """agent 调 propose_gui_verify(expected_text=...) 时登记 GUI 验证(2d,与 propose_dom_verify 同构)。

        - 显式 verify_cmd 优先 → 忽略(不覆盖)。
        - GuiProber 未注入(computer use 未开)→ 静默忽略(向后兼容,GUI lane 跳过)。
        - expected_text 必填、≤500 字符;存 _pending_gui_expected_text,verify 阶段由 GuiProber
          截图+OCR 独立断言(host 侧,沙箱碰不到)。
        返回是否登记成功(False=被拒/忽略)。
        """
        if self._verify_cmd is not None and self._verify_cmd.strip():
            return False
        if self._gui_prober is None:
            return False
        exp_m = _GUI_KW_EXP.search(raw_args)
        expected_text = exp_m.group(1).strip() if exp_m else ""
        # 反平凡 + 防滥用:过短(几乎必命中,可伪造 passed)或过长 → 拒登记。
        if (not expected_text or len(expected_text) < _PROBE_EXPECTED_MIN
                or len(expected_text) > _DOM_PARAM_MAX):
            return False
        self._pending_gui_expected_text = expected_text
        return True

    def respond_plan_decision(
        self, call_id: str, action: str, feedback: str | None = None,
    ) -> bool:
        """v6 §4 ACP:daemon 路径回传 plan 决策,唤醒挂起的 _run_plan_phase_loop。

        等同于 TUI 路径的 ExitPlanMode(loop, action, feedback):校验 action、写
        _plan_decision、set _plan_decision_event,同时清除 _plan_call_registry 中的条目。

        返回 True = 成功路由;False = call_id 不在注册表(超时已清理 / 非法 call_id)。
        超时兜底由 _run_plan_phase_loop 的 wait_for 处理(默认 cancel,诚实事件)。

        fail-closed:校验失败(无效 action / refine 无 feedback)→ 返 False,不唤醒 loop。
        """
        if call_id not in self._plan_call_registry:
            return False
        from argos.core.plan_mode import ExitPlanMode
        result = ExitPlanMode(self, action, feedback)
        # ExitPlanMode 失败(校验不过)→ 不清注册表,返 False 告知调用方。
        # 用 is_error_result(locale 无关):工具/plan 错误串切英文后以 "Error:" 起,绝不漏判。
        if is_error_result(result):
            return False
        # 清注册表条目(ExitPlanMode 已 set _plan_decision_event,loop 会唤醒)。
        self._plan_call_registry.pop(call_id, None)
        return True

    @staticmethod
    def _todos_summary(todos: list[dict]) -> str:
        """把当前 todos 摘成一行行的进度文本(回灌 messages 的锚,防长任务丢目标)。"""
        glyph = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}
        done = sum(1 for t in todos if t.get("status") == "completed")
        lines = [_i18n_t("loop.todos.header", done=done, total=len(todos))]
        for t in todos:
            mark = glyph.get(t.get("status", "pending"), "[ ]")
            lines.append(f"{mark} {t.get('content', '')}")
        return "\n".join(lines)

    def _pick_strategy_cmd(self, goal: str) -> str | None:
        """P4 策略生成:按验证梯子候选序列找首个通过校验的可执行命令。

        校验规则与 propose_verify 同款(同一道门):
          · 首 token 必须在 ALLOWED_CMDS(白名单,与 Verifier._run_verify 一致)。
          · 首 token 不能在 TRIVIAL_VERIFY_BINS(反琐碎,与 _on_propose_verify 一致)。
          · 被拒 → 跳下一候选(诚实降级链);所有候选都拒或只剩 L5 → 返 None(走旧路径)。

        L3(dom_assert,cmd=None)候选：若 DomProber 已接入则挂入 _pending_l3_strategy,
        返 None（verify_cmd 仍 None）；verify 阶段检测到 _pending_l3_strategy 后走探针路径。
        DomProber=None 时跳过 L3（向后兼容：行为同本期之前）。

        cmd=None 的 L2 候选继续跳过（具体文件名未知，接线层暂未实现）。
        L5 候选 → 直接返 None(维持现有 NO_TEST 路径,行为 100% 不变)。

        不修改任何外部状态（_pending_l3_strategy 除外）;绝不抛(fail-closed:任何异常 → 返 None 走旧路径)。
        """
        try:
            from argos.verify.strategy import generate, probe_workspace, WorkspaceFacts
            from argos.tools import ALLOWED_CMDS

            # 探测工作区(只读)
            ws = self._workspace
            facts = probe_workspace(ws) if ws and ws.is_dir() else WorkspaceFacts()

            strategies = generate(
                goal,
                workspace_facts=facts,
                capability_hints=self._capability_hints or {},
            )

            for s in strategies:
                if s.level == "L5":
                    # L5 退路 → 维持旧 NO_TEST 诚实路径,绝不假装有 cmd
                    return None
                if s.level == "L3" and s.kind == "dom_assert":
                    # A2 L3 dom_assert：接入了 DomProber 才挂起；否则跳过（向后兼容）。
                    if self._dom_prober is not None:
                        self._pending_l3_strategy = s
                        return None  # verify_cmd 仍 None；verify 阶段走 DOM 探针路径
                    continue  # DomProber=None → 跳过，继续找下一候选
                if s.cmd is None:
                    # L2 cmd=None 候选（具体文件名未知）→ 暂跳过
                    continue
                # L1/L2 且有 cmd → 过两道门校验(与 propose_verify 同款)
                try:
                    cmd_parts = shlex.split(s.cmd)
                except ValueError:
                    continue  # 解析失败 → 跳过此候选
                if not cmd_parts:
                    continue
                bin_name = Path(cmd_parts[0]).name
                if bin_name in TRIVIAL_VERIFY_BINS:
                    continue  # H1 反琐碎门:伪命令 → 跳过
                if bin_name not in ALLOWED_CMDS:
                    continue  # 白名单门 → 跳过
                # 通过校验 → 用此命令作为本轮 verify_cmd
                return s.cmd

            return None  # 所有候选都不满足 → 回退旧路径
        except Exception:  # noqa: BLE001 — 策略生成失败不挂 run(fail-closed 回退旧路径)
            return None

    async def _run_dom_probe_verdict(self, strategy: Any, *, attempt: int) -> "Verdict":
        """A2 L3 DOM 探针：调 DomProber，返回三态 Verdict，并通过 harness bus 投 VerifyVerdict。

        安全不变量：
          · error 非空 → unverifiable（浏览器不可用/超时/异常，绝不假装 passed）。
          · found=False + error 空 → failed（真实证据：元素不存在/文本不匹配，回灌 bounce）。
          · found=True → Verdict.passed（detail 含探针证据摘录，走既有 break/report 路径）。
          · 任何异常 → unverifiable（fail-closed，不挂 run）。

        此方法在 host 侧 verify 阶段调用（run() 的 async 上下文内），DomProber.probe 是同步的，
        用 asyncio.to_thread 包装避免阻塞事件循环。
        """
        import asyncio as _asyncio
        from argos.core.types import Verdict
        from argos.protocol.events import VerifyVerdict as _VV

        # 从策略解析 url / selector / expected_text
        target = strategy.target or ""
        # target 格式："{url}#{selector}"（见 strategy._l3_dom_assert）
        if "#" in target:
            url_part, selector = target.split("#", 1)
        else:
            url_part, selector = target, "body"
        url = url_part if url_part.startswith("http") else None

        # expected_text 来源优先级：
        #   1. _pending_dom_expected_text（propose_dom_verify 显式声明）
        #   2. capability_hints['dom_expected_text']（registry hint 路径，作为兜底）
        expected_text: str | None = (
            self._pending_dom_expected_text
            or self._capability_hints.get("dom_expected_text")
            or None
        )

        try:
            # DomProber.probe 是同步阻塞（Playwright queue），包进 thread 避免阻塞 event loop
            prober = self._dom_prober
            result = await _asyncio.to_thread(
                prober.probe, url, selector, expected_text=expected_text
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed
            result_type = type(exc).__name__
            result_err = _i18n_t("loop.dom_probe.thread_error", result_type=result_type, exc=exc)
            # 构造一个哨兵 result（不引入循环 import）
            class _R:  # noqa: N801 — 局部哨兵
                found = False
                text_excerpt = ""
                error = result_err
            result = _R()  # type: ignore[assignment]

        rationale = strategy.rationale_human
        label = f"dom_assert:{selector}"

        if result.error:
            # 浏览器不可用/异常 → unverifiable（诚实）
            detail = _i18n_t("loop.dom_probe.error_detail", rationale=rationale, error=result.error)
            verdict = Verdict(
                status="unverifiable",
                detail=detail,
                verify_cmd=label,
                attempts=attempt,
            )
        elif result.found:
            # 元素存在（且 expected_text 命中，若有）→ passed（带探针证据）
            excerpt = result.text_excerpt[:200] if result.text_excerpt else _i18n_t("loop.dom_probe.no_excerpt")
            detail = _i18n_t("loop.dom_probe.found_detail", rationale=rationale, selector=selector, excerpt=excerpt)
            verdict = Verdict.passed(detail=detail, verify_cmd=label, attempts=attempt)
        else:
            # 元素不存在/文本不匹配 → failed（真实证据，回灌 bounce）
            detail = _i18n_t("loop.dom_probe.not_found_detail", rationale=rationale, selector=selector)
            verdict = Verdict.failed(detail=detail, verify_cmd=label, attempts=attempt)

        # 投 VerifyVerdict 事件（走既有账本/TUI 路径）
        await self._harness.bus.emit(_VV(verdict=verdict))
        return verdict

    async def _run_gui_probe_verdict(self, expected_text: str, *, attempt: int) -> "Verdict":
        """2d GUI 探针:调 GuiProber(截图 + 独立 OCR),返三态 Verdict,投 VerifyVerdict。

        安全不变量(与 DOM 探针同构):
          · error 非空 → unverifiable(OCR/截图不可用/异常,绝不假装 passed)。
          · found=True → passed(屏上确认含 expected_text,带 OCR 摘录)。
          · found=False + error 空 → failed(真实证据:屏上未命中,回灌 bounce)。
        GuiProber.probe 同步(截图+OCR),用 to_thread 包避免阻塞 event loop。
        """
        import asyncio as _asyncio
        from argos.core.types import Verdict
        from argos.protocol.events import VerifyVerdict as _VV

        label = f"gui_assert:{expected_text[:40]}"
        try:
            result = await _asyncio.to_thread(self._gui_prober.probe, expected_text)
        except Exception as exc:  # noqa: BLE001 — fail-closed
            class _R:  # noqa: N801 — 局部哨兵
                found = False
                text_excerpt = ""
                error = _i18n_t("loop.gui_probe.thread_error", exc_type=type(exc).__name__, exc=exc)
            result = _R()  # type: ignore[assignment]

        if result.error:
            verdict = Verdict(
                status="unverifiable",
                detail=_i18n_t("loop.gui_probe.unverifiable_detail", error=result.error),
                verify_cmd=label, attempts=attempt,
            )
        elif result.found:
            excerpt = result.text_excerpt[:200] if result.text_excerpt else _i18n_t("loop.gui_probe.no_excerpt")
            verdict = Verdict.passed(
                detail=_i18n_t("loop.gui_probe.found_detail", expected_text=expected_text, excerpt=excerpt),
                verify_cmd=label, attempts=attempt,
            )
        else:
            verdict = Verdict.failed(
                detail=_i18n_t("loop.gui_probe.not_found_detail", expected_text=expected_text),
                verify_cmd=label, attempts=attempt,
            )
        await self._harness.bus.emit(_VV(verdict=verdict))
        return verdict

    async def run(self, goal: str, session_id: str,  # noqa: E501
                  attachments: "list | None" = None) -> AsyncIterator["Event"]:
        """驱动一次 run。plan→act→verify→report,投并持久化每个 Event(一份事件三用)。

        attachments: 可选图片附件列表(spec §5 方案 C)。
            - None / [] → 纯文本路径(零回归)。
            - 非空 + tier.multimodal=False → 诚实阻断(ValueError 经顶层兜底转 Error 事件)。
            - 非空 + tier.multimodal=True → 附件挂在首条 user 消息的 attachments 边车字段。

        顶层兜底:捕获 _drive 内任何未处理异常,挖异常链投 Error(spec §3.3 L5)。
        """
        # 视觉能力门(spec 2026-06-13):发请求前判定模型能否看图。能力靠"懒触发探针 + 缓存"
        # 自发现(override→缓存→探针),探不出/看不了 → 诚实阻断,不静默剥图、不假装看到。
        if attachments:
            tier = getattr(getattr(self, "_model", None), "tier", None)
            if tier is not None:
                from argos.core.vision_capability import (
                    resolve_vision_capability, VisionCapabilityCache,
                )
                ok = await resolve_vision_capability(tier, self._model, VisionCapabilityCache())
                if not ok:
                    model_name = getattr(tier, "model", "current model")
                    raise ValueError(
                        _i18n_t("loop.vision.unsupported", model_name=model_name)
                    )
        self._reset_run_state()
        # P0 护城河:inline 路径自建 runtime 上下文(daemon 在 worker.py 外部自设;inline 此前漏设 →
        # project_mode=False → guard_project_tests 返 0、verify 跑默认 ~/.argos/verify 而非用户项目)。
        # 必须早于下面的 guard_project_tests / spawn / verify(它们都读 runtime.current())。set-and-leave:
        # inline 单 session 每次 run 起始都重设,无跨 run 残留风险;daemon 不开此开关,行为零变更。
        if self._manage_runtime_context:
            from argos import runtime as _rt
            _rt.set_context(_rt.RunContext(
                workspace=self._workspace, verify_dir=self._verify_dir,
                project_mode=self._project_mode,
            ))
        # 拍 workspace 快照(供 /undo 还原);失败不阻断 run,仅 _last_snapshot = None 走"/undo
        # 不可用"诚实降级路径。延迟 import 避免 core.snapshot ↔ runtime 之间未来的循环风险。
        # #24:RunSnapshot.take 同步 tar 整个 workspace;大项目可阻塞事件循环几秒 → to_thread 解放主循环。
        self._last_snapshot = None
        try:
            from argos.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
            tar_path = SNAPSHOT_ROOT / f"{session_id}-{int(time.time() * 1000)}.tar"
            self._last_snapshot = await asyncio.to_thread(
                RunSnapshot.take, self._workspace, tar_path,
            )
        except Exception:  # noqa: BLE001 — 诚实:拍快照失败 = /undo 不可用,run 照常进行
            pass
        # M8:固定空命名空间的副本 —— 模型输出永不经此进入 __authorized_imports__。
        spawn_namespace = dict(_FIXED_SPAWN_NAMESPACE)
        assert "__authorized_imports__" not in spawn_namespace, (
            _i18n_t("core2.loop.m8_assert")
        )
        # tool_allowlist 仅在【角色子 agent】非 None 时传(它们走真后端,签名已支持);父 agent 恒 None
        # → 不传该 kwarg,保持对既有测试 FakeSandbox.spawn(无此参数)的兼容。对真后端而言
        # 不传 == 传 None(默认值),行为等价。
        _spawn_kwargs: dict = dict(
            workspace=self._workspace, namespace=spawn_namespace,
            allow_workflow=self._allow_workflow, read_only=self._read_only,
        )
        if self._tool_allowlist is not None:
            _spawn_kwargs["tool_allowlist"] = self._tool_allowlist
        self._sandbox.spawn(**_spawn_kwargs)
        # 头号护城河洞修复:project_mode 下 verify_dir==workspace,agent 技术上能改"评判自己的
        # 测试"。run 起始(agent 动手前)快照既有测试指纹 → detect_tampering 见改/删即判篡改,
        # verify 据此判 unverifiable(诚实)。沙箱模式靠 VERIFY_DIR 隔离,guard_project_tests 自返 0。
        # 与 propose_verify 时机无关(快照早于任何 agent 动作)→ 堵"先改弱测试再声明"那条绕过。
        try:
            from argos import runtime
            runtime.guard_project_tests()
        except Exception:  # noqa: BLE001 — 守护快照失败不阻断 run(诚实降级:此 run 无篡改检测)
            pass
        # 同步桥交互审批:注入本 run 的 host event loop。broker_handler 据此把沙箱工具调用的
        # request()(完整 gating + ②交互审批)提交回主循环;exec_code 已移进工作线程 → 主循环空闲。
        if self._broker is not None and hasattr(self._broker, "set_host_loop"):
            try:
                self._broker.set_host_loop(asyncio.get_running_loop())
            except RuntimeError:  # 理论上不会:run 必在运行中的 loop 内被 async for 消费
                pass
        try:
            async for ev in self._drive(goal, session_id, attachments=attachments):
                self._store.append_event(session_id, ev)
                yield ev
        except Exception as e:  # noqa: BLE001
            chain: list[str] = []
            cur: BaseException | None = e
            while cur is not None and len(chain) < 4:
                chain.append(f"{type(cur).__name__}: {cur}")
                cur = cur.__cause__ or cur.__context__
            # #2:429 限流 → 友好可操作提示(而非裸 httpx 字符串)。
            # #10:网络/DNS 故障 → 友好提示含原始错误。
            import httpx as _httpx
            _raw_msg = str(e)
            _friendly: str | None = None
            _status = getattr(getattr(e, "response", None), "status_code", None)
            if _status == 429 or (
                "429" in _raw_msg or "too many requests" in _raw_msg.lower()
                or "rate_limit" in _raw_msg.lower()
            ):
                _friendly = _i18n_t("loop.error.rate_limit", raw_msg=_raw_msg[:120])
            elif isinstance(e, _httpx.TransportError) or isinstance(
                e, (_httpx.ConnectError, _httpx.ConnectTimeout, _httpx.ReadTimeout)
            ):
                _friendly = _i18n_t("loop.error.network", raw_msg=_raw_msg[:200])
            msg = _friendly if _friendly is not None else _raw_msg
            err = Error(message=msg, chain=chain)
            self._store.append_event(session_id, err)
            yield err
        finally:
            if self._broker is not None and hasattr(self._broker, "set_host_loop"):
                self._broker.set_host_loop(None)   # 清空,避免跨 run 复用陈旧 loop 引用
                # cancel 中途断在审批上时,经 run_coroutine_threadsafe 起的 request() 是独立
                # task,不随 run 取消 → 孤儿审批会 pending 到 60s 超时。cancel_all 立即以 deny
                # 收尾本 run 残留挂起(per-run gate,不影响其它并发 run)。
                gate = getattr(self._broker, "gate", None)
                if gate is not None and hasattr(gate, "cancel_all"):
                    try:
                        gate.cancel_all()
                    except Exception:  # noqa: BLE001 — 收尾清理失败不掩盖主异常
                        pass
            self._sandbox.close()

    async def _enter_phase(self, phase: str) -> AsyncIterator["Event"]:
        """W2:经 Harness.enter_phase 推进阶段门(强制不可跳),drain 出 PhaseChange 走主路径。"""
        await self._harness.enter_phase(phase, actions=self._actions)  # type: ignore[arg-type]
        for ev in self._hbus.drain():
            yield ev

    def _maybe_attach_screenshot(self, fb_msg: dict, shot: "tuple | None") -> None:
        """计算机控制视觉回路:多模态模型 → 把本步截图(path, size)当图像挂到反馈消息
        (core.protocols.payload 逐消息物化为 image block)。非多模态 / 无截图 / 读图失败 →
        诚实降级为纯文本(不挂图、不改 content;提示词已要求模型看不清就说 unverifiable)。

        2c:成功挂图时,在 content 里告知截图像素尺寸 —— 模型按这张图的像素空间给点击坐标。
        """
        if shot is None:
            return
        tier = getattr(self._model, "tier", None)
        if tier is None or not getattr(tier, "multimodal", False):
            return
        try:
            from argos.input.attachments import load_from_path
            path, size = shot
            fb_msg["attachments"] = [load_from_path(path)]
            if size and tuple(size) != (0, 0):
                fb_msg["content"] = (
                    f"{fb_msg['content']}"
                    + _i18n_t("loop.screenshot.pixel_note", w=size[0], h=size[1])
                )
        except Exception as exc:  # noqa: BLE001 — 读图失败诚实降级纯文本(不阻断 run)
            __import__("logging").getLogger(__name__).debug("screenshot attach skipped: %s", exc)

    def _tool_signatures_block(self) -> str:
        """工具签名提示(本 PR 新增 3 工具的签名,模型调用时不会因签名漂移跑错)。

        spec §2.3.3:跟 _env_context 同位置(HONESTY 之后、untrusted 之前)。
        顺序锁死——若改了位置,先看 spec §12.1。
        """
        return (
            "\n\n<tool_signatures>\n"
            "- read_file(path, offset: int = 0, limit: int | None = None) "
            "— offset = start line (0-based), limit = how many lines (None = to EOF)\n"
            "- edit_file(path, old, new, all_occurrences: bool = False) "
            "— all_occurrences=False (default) = unique match; True = replace all (max 1000)\n"
            "- slash /undo reverts this run's file changes; /retry resends your last "
            "message (press Esc first if busy).\n"
            "</tool_signatures>"
        )

    async def _maybe_proactive_compact(self, session_id: str, step: int) -> AsyncIterator["Event"]:
        """#12 Context 可视化:主动压缩(spec §9.2)— 每步顶部 1 行 yield,条件不满足
        空生成器,既不崩也不假装压过(D12 锁)。

        流程:
          1) 读 model.last_usage(input+cache_read+cache_creation)= used
          2) 调 threshold._should_compact(...) 判定
          3) True → store.compact_messages + reload messages + 记 _last_compact_used
                    + yield CompactedEvent(before, after, reduction_pct, triggered_by="proactive")
          4) False → 空生成器
        """
        from argos.context.threshold import (
            _should_compact, LastCompactedAt as _LCA, safe_compact_threshold,
        )
        # threshold 字段可能不存在(老 LoopConfig 构造点);getattr 兜底。
        # safe_compact_threshold:整体压缩=高水位安全网,绝不在 50% 以下触发有损提前压。
        threshold = safe_compact_threshold(float(getattr(self._cfg, "compact_threshold", 0.8) or 0.0))
        if threshold <= 0:
            return
        # 读 used(API 真值;last_usage 不存在 → 0,自然不超阈值)
        usage = getattr(self._model, "last_usage", None) or {}
        used = (int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read") or 0)
                + int(usage.get("cache_creation") or 0))
        # window:model.tier.context_window;fallback 200_000
        try:
            window = int(self._model.tier.context_window or 0) or 200_000
        except Exception:  # noqa: BLE001 — model 缺 tier/context_window 兜底
            window = 200_000
        # 判定(spec §8 短路)
        if not _should_compact(
            used=used, window=window, threshold=threshold,
            phase="act",   # while 在 act 阶段;verify/plan 阶段不在此处
            compaction_enabled=bool(getattr(self._cfg, "compaction", True)),
            already_compacted_at=self._last_compact_used,
            last_verdict_fail_count=self._fail_count,
        ):
            return
        # 写盘失败不崩(下轮再试)
        if not hasattr(self._store, "compact_messages"):
            return
        pre_used = used
        try:
            self._store.compact_messages(session_id, keep_recent=5)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return
        new_messages = self._store.get_messages(session_id) if hasattr(self._store, "get_messages") else []  # type: ignore[attr-defined]
        # 不可丢核心:整体压缩可能把任务目标折进摘要 → 重新钉回(verify_cmd 是实例字段,天然不丢)。
        new_messages = self._anchor_core_messages(new_messages, self._current_goal)
        # 估压缩后 token(chars4;reload 后 store 不知 API 真 input;此处只给活动栏参考)
        new_total = sum(max(1, len(m.get("content") or "") // 4) for m in new_messages)
        self._messages_override = new_messages
        self._last_compact_used = _LCA(used=pre_used)
        # 压缩=有损:标记发生过压缩 + 压缩后尚未重验(passed 需重跑 verify 才可信)。
        self._compacted = True
        self._reverified_since_compact = False
        from argos.protocol.events import CompactedEvent
        yield CompactedEvent(
            before=pre_used, after=new_total,
            reduction_pct=max(0.0, (pre_used - new_total) / max(1, pre_used)),
            triggered_by="proactive", session_id=session_id,
        )

    def _anchor_core_messages(self, messages: list[dict], goal: str) -> list[dict]:
        """不可丢核心:确保任务目标【原样】在场。整体压缩/修剪可能把目标折进摘要里 ——
        若目标文本已不在 messages 中,则重新钉在最前(标注为核心锚)。verify_cmd 是实例
        字段,本就不入 messages,天然不丢,无需在此处理。绝不抛(坏输入返回原样)。"""
        if not goal:
            return messages
        try:
            if any((m.get("content") or "") == goal for m in messages):
                return messages
            return [{"role": "user", "content": goal}] + list(messages)
        except Exception:  # noqa: BLE001 — 核心锚是兜底,异常也绝不崩 run
            return messages

    def _maybe_prune(self, messages: list[dict], session_id: str = "") -> tuple[list[dict], "PrunedEvent | None"]:
        """持续相关性修剪(spec 2026-06-07)——在整体压缩之前就一直做、优先于压缩。
        折叠过期工具输出/被取代旧计划/死路错误,核心(目标+最近N+verify_cmd)原样保留。
        纯启发式、不依赖模型/store;无可折叠时返回原样 + None(零事件,不刷屏)。"""
        aggressiveness = float(getattr(self._cfg, "prune_aggressiveness", 0.5) or 0.0)
        if aggressiveness <= 0 or not messages:
            return messages, None
        try:
            from argos.context.prune import CoreKeep, prune_messages
            core = CoreKeep(recent_turns=6, verify_cmd=self._verify_cmd)
            result = prune_messages(messages, core=core, aggressiveness=aggressiveness)
        except Exception:  # noqa: BLE001 — 修剪是优化项,失败就不修剪(优雅降级)
            return messages, None
        if result.removed <= 0:
            return messages, None
        from argos.context.tokens import token_estimate
        before = sum(token_estimate(m.get("content") or "")[0] for m in messages)
        after = before - result.removed_tokens
        from argos.protocol.events import PrunedEvent
        ev = PrunedEvent(
            before=before, after=after, removed=result.removed,
            reduction_pct=max(0.0, result.removed_tokens / max(1, before)),
            aggressiveness=aggressiveness, session_id=session_id,
        )
        return result.messages, ev

    def _build_system(self, goal: str) -> str:
        """系统提示三段接线(顺序锁死,spec §12.1):
          · 安全段 = HONESTY_SYSTEM + 结构化任务契约(命中时注入我们自己的可信 checklist,
            便宜模型对齐形式约定的护城河;非结构化任务不注入)。
          · untrusted 段 = 召回的 skills(社区/导入,围栏隔离防注入) + 任务记忆。
        skills 召回零模型兜底、不依赖 store;memory 召回需 store.recall。任一失败都诚实降级
        (不假装召回发生过),绝不让 run 崩。

        本方法返单字符串(向后兼容,既有 caller / 测试用);调用方若想接 Anthropic
        cache_control 断点(任务:并行子 agent 共用稳定前缀),用 _build_system_pair 拿
        (stable, dynamic) 对传给 ModelClient.stream(system=stable, system_dynamic=dynamic)。
        """
        stable, dynamic = self._build_system_pair(goal)
        if not dynamic:
            return stable
        return compose_system(stable, untrusted=dynamic)

    def _build_system_pair(
        self, goal: str, *, _prefetched_memory_lines: list[str] | None = None,
    ) -> tuple[str, str]:
        """返 (stable, dynamic) 对(任务:Anthropic cache_control 拆段打稳定前缀)。

        stable = HONESTY + env + memory_context + tool_signatures + contract + mcp_summary
                 (无 recall;每步原样重发,适合 cache_control 缓存)
        dynamic = skill bodies + memory lines(有 recall;每步变化,污染前缀 → 不缓存)

        拆分语义(任务):stable 永远在 dynamic 之前(spec §12.1 顺序锁)。caller 据此
        把 stable 走 ModelClient.stream(system=...)、dynamic 走 system_dynamic=...,
        Anthropic 据此给 stable text block 打 cache_control.ephemeral,parallel 子 agent
        共享同一稳定前缀 → 第二步起 cache_read 命中,价钱降约 10x(spec §4 / 任务设计点)。

        _prefetched_memory_lines: #4 async 路径 — 调用方(如 _drive)已在异步上下文里
        通过 arecall/to_thread 预拉取好 recall 行,直接传入避免此方法同步阻塞事件循环。
        None = 同步路径(tests/_build_system 等)按旧逻辑调 store.recall(阻塞,但在测试/
        plan_mode 场景里无事件循环阻塞问题)。
        """
        # ── 安全段:运行环境块(cwd/OS/日期前置,免得模型现场探目录)+ 结构化工程任务契约 ──
        # spec §2.3.3:_tool_signatures_block 跟 _env_context 同位置(HONESTY 之后、untrusted 之前)
        safe = (
            HONESTY_SYSTEM
            + _env_context(self._workspace)
        )
        # #9 T6:<memory_context> 段(spec §5.3)— CLAUDE.md / AGENTS.md + 4 tier 召回
        try:
            from argos.memory import auto as _mem_auto
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
            from argos import contracts
            _dom, contract_text = contracts.contract_for(goal)
            if contract_text:
                safe = safe + contract_text
        except Exception:  # noqa: BLE001 — 契约分类失败不影响主流程
            pass

        # ── 安全段:可用 MCP 工具清单(配了 ~/.argos/mcp.json 才注入;默认零预配 → 空,不注入)──
        # 优先用注入的 per-session McpManager;无注入则 fallback 到模块级单例(向后兼容)。
        try:
            if self._mcp_manager is not None:
                _mcp_mgr = self._mcp_manager
            else:
                from argos import mcp_native
                _mcp_mgr = mcp_native.get_manager()
            mcp_summary = _mcp_mgr.tools_summary()
            if mcp_summary:
                safe = safe + "\n\n" + mcp_summary
        except Exception:  # noqa: BLE001 — MCP 连接/读取失败诚实降级为无 MCP
            pass

        # 计算机控制文档段:仅 ARGOS_COMPUTER_USE 开启时注入(默认不占预算,也不在未开能力时诱导盲点)。
        import os as _os_cu
        if _os_cu.environ.get("ARGOS_COMPUTER_USE"):
            from argos.core.honesty import COMPUTER_USE_PROMPT
            safe = safe + "\n\n" + COMPUTER_USE_PROMPT
        # 工作流段:Phase 5.3 起默认不进提示(重型编排,普通任务用不上);仅 ARGOS_WORKFLOWS=1 注入。
        if _os_cu.environ.get("ARGOS_WORKFLOWS"):
            from argos.core.honesty import WORKFLOW_PROMPT
            safe = safe + "\n\n" + WORKFLOW_PROMPT
        # LSP 工具段:仅当用户显式创建了 ~/.argos/lsp.json 且 servers 非空才注入 ——
        # load() 在文件不存在时返回内置默认(含 python server),所以必须先检查文件是否存在,
        # 否则对所有默认用户都会注入 LSP 段(与注释声称的"仅用户配置时"相悖)。
        try:
            from argos.lsp.config import LSP_CONFIG_PATH as _LSP_CONFIG_PATH, load as _load_lsp
            if _LSP_CONFIG_PATH.exists() and _load_lsp().servers:
                from argos.core.honesty import LSP_TOOLS
                safe = safe + "\n\n" + LSP_TOOLS
        except Exception:  # noqa: BLE001 — LSP 配置读取失败诚实降级为不注入(不阻断 run)
            pass

        if not self._cfg.recall:
            return (safe, "")

        # ── untrusted 段:skills(独立于 store,零模型兜底) + memory(需 store.recall)──
        skill_bodies: list[str] = []
        try:
            from argos import skills as _skills
            skill_bodies = [
                _i18n_t("core2.loop.skill_header", name=s.name, description=s.description, body=s.body.strip())
                for s in _skills.recall(goal)
            ]
        except Exception:  # noqa: BLE001 — skill 召回失败诚实降级为无 skill
            skill_bodies = []

        memory_lines: list[str] = []
        if _prefetched_memory_lines is not None:
            # #4 async 路径:调用方已在事件循环里非阻塞拉取,直接用 —— 无 httpx 阻塞。
            memory_lines = _prefetched_memory_lines
        elif hasattr(self._store, "recall"):
            try:
                hits = self._store.recall(goal)  # type: ignore[attr-defined]
                memory_lines = [
                    f"- {rec.goal} → {rec.verdict or '?'}（{reason}）" for rec, reason in hits
                ]
            except Exception:  # noqa: BLE001
                memory_lines = []

        dynamic = format_untrusted(skill_bodies=skill_bodies, memory_lines=memory_lines)
        return (safe, dynamic)

    async def _drive(self, goal: str, session_id: str,
                     attachments: "list | None" = None) -> AsyncIterator["Event"]:
        """四阶段驱动(不可跳):plan → act(CodeAct 循环) → verify(门禁) → report。

        attachments: 经 run() 多模态门禁后传入的合法附件列表(None = 纯文本路径)。
        """
        # 确保 session 行先于任何 event/message 落库(replay/resume 据 session_id 重建;幂等,
        # resume 时已存在则 no-op)。hasattr 守卫:最小 store 替身(无 session 概念)跳过。
        if hasattr(self._store, "ensure_session"):
            self._store.ensure_session(  # type: ignore[attr-defined]
                session_id, title=goal[:80], model=self._cfg.model_tier, system_snapshot="",
            )
        # ── hooks: SessionStart(spec §2.5 触发点表)──────────────────
        from argos import config as _config
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
        # 方案 C(spec §5):attachments 作边车字段挂在首条 user 消息;
        # content 仍是字符串 → store/压缩/诚实检查/coalesce 全部不动。
        _user_msg: dict = {"role": "user", "content": goal}
        if attachments:
            _user_msg["attachments"] = list(attachments)
        messages.append(_user_msg)
        self._store.append_message(session_id, role="user", content=goal)
        self._current_goal = goal   # 不可丢核心:压缩后核心锚据此把目标钉回(spec 2026-06-07)
        self._user_goal = goal      # 收尾 capture_event("run_success") 要记的 goal;修过 bug:之前从未赋值 → 永远空串
        # W3:系统提示在 run 起始算一次(召回的 untrusted 段在安全段之后)。
        # 任务:并行子 agent 共用稳定前缀 → 拆 (stable, dynamic) 对,Anthropic 据此给
        # stable text block 打 cache_control.ephemeral;plan 模式仍走单字符串 system
        # (plan 不重复 stream,缓存收益小;_run_plan_phase_loop 拿 system 串用)。
        # #4:在 async 上下文里先 arecall(非阻塞),再传 _prefetched_memory_lines 给
        # _build_system_pair,避免同步 httpx.Client(timeout=30) 阻塞事件循环。
        _prefetched_mem: list[str] = []
        if self._cfg.recall and hasattr(self._store, "recall"):
            try:
                if hasattr(self._store, "arecall"):
                    _mem_raw = await self._store.arecall(goal)  # type: ignore[attr-defined]
                else:
                    _mem_raw = await asyncio.to_thread(
                        self._store.recall, goal,  # type: ignore[attr-defined]
                    )
                _prefetched_mem = [
                    f"- {rec.goal} → {rec.verdict or '?'}（{reason}）"
                    for rec, reason in _mem_raw
                ]
            except Exception:  # noqa: BLE001 — recall 失败降级为空(不阻断 run)
                _prefetched_mem = []
        system_stable, system_dynamic = self._build_system_pair(
            goal, _prefetched_memory_lines=_prefetched_mem,
        )
        system = system_stable if not system_dynamic else compose_system(
            system_stable, untrusted=system_dynamic,
        )

        # v6 §4 ACP MemoryRecallEvent:run 起始把 store.recall 命中结果通过事件广播,
        # 消费侧(TUI/daemon client)据此渲染"记忆召回 N 条",不再 getattr(loop,'_store') 穿透。
        # 诚实:无 store / 无 recall 能力 / 0 命中 → 投空列表事件(hits=[]),消费侧不喧宾。
        # #4:复用上方 _prefetched_mem(已非阻塞拉取),不再重复 recall。
        # _prefetched_mem 格式 "- goal → verdict（reason）",MemoryRecallEvent.hits 用同格式。
        _recall_hits: list[str] = [line.lstrip("- ") for line in _prefetched_mem]
        yield MemoryRecallEvent(hits=_recall_hits)

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
        conversational_done = False  # 人性化:纯对话/纯读问答轮 → 跳过验证门展示(report 不加完成判决行)。
        verify_nudged = False     # H2:改了代码却没声明验证 → 只催一轮(防误催纯读/无限催)。
        compactions = 0           # 上下文压缩次数上限,防压缩仍溢出时无限重试。
        last_fp: str | None = None   # stagnation guard: fingerprint of last (code, stdout)
        fp_run: int = 0              # consecutive run-length of the same fingerprint
        escalation_reason: str = "max_rounds_exceeded"  # telemetry label; overwritten at each escalated=True site
        text = ""                 # 在 while 外初始化:max_steps=0 等边界下收尾仍能安全 text.strip()
        while step < self._cfg.max_steps:
            # context rot 第二层(spec 2026-06-07):持续相关性修剪,优先于整体压缩 ——
            # 每步顶部先折叠过期工具输出/被取代旧计划/死路错误(核心原样保留),再判要不要整体压。
            messages, _prune_ev = self._maybe_prune(messages, session_id)
            if _prune_ev is not None:
                yield _prune_ev
            # #12 Context 可视化(spec §9.3 / D16):主动压缩检查——每步顶部 1 行,
            # 阈值满足 → 调 store.compact_messages + reload messages + yield CompactedEvent。
            # 条件不满足 → 空生成器(零字节 yield),既有 while 流程零修改。
            async for ev in self._maybe_proactive_compact(session_id, step):
                yield ev
            # 消费压后 reload 的 messages 列表(本步仅一次;之后清空,fallback 走既有 get_messages 路径)
            if self._messages_override is not None:
                messages = self._messages_override
                self._messages_override = None
            # #11 per-task routing(spec §10):每步按 (tool, code, phase) 选 tier;router
            # 不存在时静默用既有 self._model(零破坏默认路径)。text 还没拿到,先按
            # 上一轮 code 抽;首轮 text=="" → primary_tool=None → 用 default 兜底。
            if self._router is not None:
                _code_so_far = text or ""
                _code_block = extract_code_block(_code_so_far) if _code_so_far else None
                _tool_names = extract_tool_names(_code_block) if _code_block else []
                _primary_tool = _tool_names[0] if _tool_names else None
                _phase = "act"
                try:
                    from argos.routing.categorizer import categorize as _categorize
                    _category = _categorize(
                        tool=_primary_tool, code=_code_block, phase=_phase, step=step,
                    )
                    _client, _decision = self._router.select(
                        category=_category, tool=_primary_tool, step=step,
                    )
                    self._model = _client
                    self._current_tier = _decision.tier
                    if self._router.routing.is_force_confirm(_decision.tier):
                        from argos.approval import ApprovalLevel as _AL
                        self._approval_level_override = _AL.CONFIRM
                except Exception:  # noqa: BLE001 — 路由失败不挂 run(走默认)
                    self._current_tier = self._cfg.model_tier
            # W3:流式 delta 过 StreamingContextScrubber,防模型把 untrusted 围栏吐回 UI 泄露。
            scrubber = StreamingContextScrubber()
            text = ""
            try:
                async for delta in self._model.stream(messages, system=system_stable,
                                                        system_dynamic=system_dynamic):
                    text += delta
                    clean = scrubber.feed(delta)
                    if clean:
                        yield TokenDelta(text=clean)
            except Exception as e:  # noqa: BLE001 — 上下文溢出 → 压缩重试;其余异常上抛给 run() 顶层兜底。
                from argos.core.recovery import classify_error
                ce = classify_error(e)
                if (ce.should_compress and self._cfg.compaction and compactions < 3
                        and hasattr(self._store, "compact_messages")):
                    compactions += 1
                    self._store.compact_messages(session_id, keep_recent=5)   # type: ignore[attr-defined]
                    messages = self._store.get_messages(session_id)           # 重载压缩后线程(含本轮 goal)
                    messages = self._anchor_core_messages(messages, self._current_goal)  # 不可丢核心
                    # 压缩=有损:标记发生过 + 压缩后尚未重验(passed 需重跑 verify 才可信)。
                    self._compacted = True
                    self._reverified_since_compact = False
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

            # A2 Major-2:抓 propose_dom_verify(url=..., selector=..., expected_text=...) →
            # 构造 L3 VerifyStrategy 存 _pending_l3_strategy(与 propose_verify 同构)。
            # host 侧解析:沙箱子进程拿不到回调;沙箱内同名函数只返回登记回执。
            for dm in _PROPOSE_DOM_VERIFY.finditer(text):
                self._on_propose_dom_verify(dm.group(1))

            # 2d:抓 propose_gui_verify(expected_text=...) → 存 _pending_gui_expected_text;
            # verify 阶段由 GuiProber 截图+OCR 独立断言(host 侧,沙箱碰不到)。
            for gm in _PROPOSE_GUI_VERIFY.finditer(text):
                self._on_propose_gui_verify(gm.group(1))

            # 拒登记回灌:H1 伪命令(永远是) + W5 桥接 verify 锁(默认开,关需 ARGOS_BRIDGE_VERIFY_LOCK=0)。
            if self._verify_rejected is not None:
                if getattr(self, "_verify_rejected_fstring", False):
                    # #11:f-string verify(含 {} 占位)—— 诚实告知用普通字面量,而非静默丢失。
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.verify_gate.fstring_rejected", cmd=self._verify_rejected)})
                    self._verify_rejected_fstring = False
                elif (os.environ.get("ARGOS_BRIDGE_VERIFY_LOCK", "1") != "0"
                        and os.environ.get("ARGSOS_BRIDGE_VERIFY_LOCK", "1") != "0") \
                        and self._cfg.verify_cmd is not None and self._cfg.verify_cmd.strip():
                    # W5:bridge 已配 verify,agent 不必再 propose(开锁时)
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.verify_gate.bridge_locked", cmd=self._verify_rejected)})
                else:
                    # H1:伪命令
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.verify_gate.trivial_rejected", cmd=self._verify_rejected)})
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
            # 上下文窗口占用 = 本次调用【输入侧】真实满 prompt token,是【当前窗口】真实占用
            # (对齐 Claude Code 口径),与上面 _tok_in 的【会话累计】是两个不同的数,不可混。
            # 优先用 protocol 写的 context_total(口径无关:OpenAI 的 prompt_tokens 已含缓存,不能再加;
            # Anthropic 的 input 不含缓存,需相加 —— 两者都在各自 capture_usage 算好)。缺则回退老式相加。
            _ctx_total = usage.get("context_total")
            if _ctx_total is not None:
                context_used = int(_ctx_total)
            else:
                context_used = (int(usage.get("input_tokens") or 0)
                                + int(usage.get("cache_read") or 0)
                                + int(usage.get("cache_creation") or 0))
            # 成本:用已就绪的定价表算【会话累计】成本(此前硬编码 None → 永远 $N/A 是 bug)。
            # 模型不在 PRICING(用户自带模型且未配单价)→ 回退 None,UI 诚实显 $N/A,
            # 而非 cost_of 对未知模型返回的 0.0(那会让 $N/A 变成失真的恒 $0.000)。
            from argos.core.observability import PRICING, cost_of
            _tier = getattr(self._model, "tier", None)
            model_name = getattr(_tier, "model", "") if _tier is not None else ""
            _sc = cost_of({"input_tokens": self._tok_in, "output_tokens": self._tok_out}, model=model_name)
            cost = _sc.cost_usd if model_name in PRICING else None
            yield CostUpdate(
                tokens_in=self._tok_in, tokens_out=self._tok_out,
                cost_usd=cost, elapsed_s=time.time() - self._started,
                cache_read=self._cache_read, context_used=context_used,
                # #11 per-task routing:实际跑这步的 profile 名(spec §15.2 可见性防线)。
                tier_name=self._current_tier,
            )

            # Task 1.2: hard budget circuit-breaker — checked after each step's accounting.
            # None ceiling = no limit; both guards use the same running counters as CostUpdate.
            _budget_msg: str | None = None
            if self._cfg.max_tokens_in is not None and self._tok_in > self._cfg.max_tokens_in:
                _budget_msg = (
                    f"budget exceeded: cumulative input tokens {self._tok_in} "
                    f"> max_tokens_in {self._cfg.max_tokens_in}"
                )
            elif (self._cfg.max_cost_usd is not None
                  and cost is not None
                  and cost > self._cfg.max_cost_usd):
                _budget_msg = (
                    f"budget exceeded: cumulative cost ${cost:.6f} "
                    f"> max_cost_usd ${self._cfg.max_cost_usd:.6f}"
                )
            if _budget_msg is not None:
                await self._hbus.emit(Escalation(
                    reason=_budget_msg,
                    attempts=step,
                    last_failure=_budget_msg,
                ))
                for ev in self._hbus.drain():
                    yield ev
                escalation_reason = "budget_exceeded"
                escalated = True
                break

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
                    reason = pre_result.stop_reason or _i18n_t("loop.hook.no_reason")
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.hook.pretooluse_rejected", reason=reason)})
                    step += 1
                    continue   # 不调 exec_code,走下一轮
                yield CodeAction(code=code, step=step)
                # exec_code 移进工作线程:释放事件循环,broker_handler 才能把工具调用的交互审批
                # request() 提交回主循环(主循环此刻空闲,gate 能 await 用户 + TUI 能渲染审批卡)。
                # 沙箱单 run 串行 exec(executor 非线程安全),to_thread 不引入并发。
                # review #4:本步若有 _approval_level_override(strong-tier 强制确认 / approve_accept_edits),
                # exec 期间把 gate 切到该语义,exec 后还原 —— 此前 override 只写不读(死写),强档强制确认
                # 等于没生效。gate 在 host(非沙箱),工具调用经 broker 同步桥提交回主循环的 gate.request。
                _ovr_gate = getattr(self._broker, "gate", None) if self._broker is not None else None
                _ovr_snap = None
                if _ovr_gate is not None and self._approval_level_override is not None \
                        and hasattr(_ovr_gate, "push_override_semantics"):
                    _ovr_snap = _ovr_gate.push_override_semantics(self._approval_level_override)
                try:
                    result = await asyncio.to_thread(self._sandbox.exec_code, code)
                finally:
                    if _ovr_snap is not None:
                        _ovr_gate.pop_override_semantics(_ovr_snap)
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
                        from argos import lsp as _lsp
                        from argos.lsp.trigger import (
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
                            from argos.lsp.manager import sync_file_sync
                            for rel_path, content in written.items():
                                abs_p = self._workspace / rel_path
                                sync_file_sync(_lsp_mgr, str(abs_p), content, timeout=3.0)
                    except Exception as _lsp_exc:  # noqa: BLE001
                        log.debug("LSP trigger skipped: %s", _lsp_exc)
                yield CodeResult(
                    step=step, stdout=result.stdout,
                    value_repr=result.value_repr, exc=result.exc, ok=result.ok,
                )
                # ── Stagnation guard (Task 1.1) ───────────────────
                # Same (code, stdout) pair repeated >= STAGNATION_LIMIT consecutive
                # times on a *failing* execution → model is stuck; break + escalate.
                # Successful execution resets: idempotent-but-ok code isn't stagnant.
                # ponytail: 只统计失败重复 —— 这才是真正的死循环信号。相同的成功块（如
                # 幂等初始化、_DoneModel 重复同一 `# act` 块）不累积，以 max_steps 兜顶。
                # 若成功路径也出现死循环（更高阈值），再把此守卫扩展到 ok=True 分支。
                if not result.ok:
                    _fp = hashlib.sha256(
                        (code + "\x00" + (result.stdout or "")).encode()
                    ).hexdigest()
                    if _fp == last_fp:
                        fp_run += 1
                    else:
                        last_fp = _fp
                        fp_run = 1
                else:
                    last_fp = None
                    fp_run = 0
                if fp_run >= STAGNATION_LIMIT:
                    _stag_msg = (
                        f"stagnant: identical (code, stdout) repeated "
                        f"{fp_run} consecutive times"
                    )
                    await self._hbus.emit(Escalation(
                        reason=_stag_msg,
                        attempts=fp_run,
                        last_failure=_stag_msg,
                    ))
                    for ev in self._hbus.drain():
                        yield ev
                    escalation_reason = "stagnation"
                    escalated = True
                    break
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
                        from argos.memory import auto as _mem_auto
                        from argos.memory.auto import project_id_for as _pid
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
                        from argos.memory import auto as _mem_auto
                        from argos.memory.auto import (
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
                # 计算机控制视觉回路:本步若新拍了截图,取工件(path, size)留给下方反馈消息挂成图像。
                if self._broker is not None and hasattr(self._broker, "take_computer_artifact"):
                    self._pending_screenshot = self._broker.take_computer_artifact()
                # 工作流提议:agent 本段调了 propose_workflow({...}) → 异步态校验+审批+引擎执行+结果回灌。
                # Phase 5.3(review #9):工作流默认 off,仅 ARGOS_WORKFLOWS=1 时才 dispatch —— 否则即便
                # 模型(训练先验/被污染的导入技能)凭空吐 propose_workflow,host 也不跑工作流机器(对称于
                # 提示词不再宣传它);未开时当普通无副作用文本走常规 feedback。
                _wf_on = bool(__import__("os").environ.get("ARGOS_WORKFLOWS"))
                _wf_spec = (extract_workflow_spec(text) if "propose_workflow" in text else None)
                if _wf_spec is not None and _wf_on:
                    async for ev in self._run_workflow(_wf_spec, messages):
                        yield ev
                    step += 1
                    continue   # 工作流结果已作为 feedback 回灌,跳过常规 exec feedback
                feedback = self._feedback(result)
                if _wf_spec is not None and not _wf_on:
                    # 诚实纠偏:工作流默认关闭时 host 不 dispatch,但沙箱 _propose_workflow_pure 回执仍说
                    # "待审批后执行"(沙箱子进程不知道 host 的开关)—— 不纠偏会让模型空等一个不会跑的工作流。
                    feedback = _i18n_t("loop.workflow.not_enabled") + "\n" + feedback
                if self._todos:
                    # 锚机制:每个 act step 把当前 todos 摘要回灌(随执行结果一起),
                    # 防长任务在多步后丢失目标/漏更状态。
                    feedback += "\n\n" + self._todos_summary(self._todos)
                _fb_msg: dict = {"role": "user", "content": feedback}
                _shot = getattr(self, "_pending_screenshot", None)
                self._pending_screenshot = None
                self._maybe_attach_screenshot(_fb_msg, _shot)
                messages.append(_fb_msg)
                step += 1
                continue

            # 无代码块。但若整轮还没有任何动作(_actions==0),说明模型只是口头说说没真做
            # —— 不得当"完成"收尾(防"说了没做"伪完成)。回灌催促,继续要它真执行。
            # 只催一轮(noaction_nudged 兜底):催过后第二次仍无代码块,允许它作为纯文字答复
            # 收尾(纯问答如"你好"本就无需动作;避免无限催促,max_steps 再兜底)。
            # 聪明催(2026-06-14):仅当本轮无代码块输出"疑似偷懒"(空/声称要做或完成却 0 动作)
            # 才催一轮防伪完成;实质对话答复(问候/问答/解释)直接收尾,不白调一轮(对话秒回)。
            if (self._actions == 0 and not noaction_nudged
                    and _looks_like_lazy_claim(text)):
                noaction_nudged = True
                messages.append({"role": "user", "content":
                    _i18n_t("loop.nudge.no_code_action")})
                step += 1
                continue

            # H2:改了代码却没声明【有效】验证命令 → 回灌一次催促它声明真验证(测试/编译/lint),
            # 再宣布完成。只催一轮(verify_nudged 兜底):仍不声明则照常走诚实"未机检验证"收尾,
            # 不无限催;纯读/问答任务(made_changes=False)不触发,避免误催。
            if made_changes and self._verify_cmd is None and not verify_nudged:
                verify_nudged = True
                messages.append({"role": "user", "content":
                    _i18n_t("loop.nudge.verify_missing")})
                step += 1
                continue

            # 有过动作(或已催过一轮)→ 模型宣布"完成" → 进 verify。
            # W1:先 enter_phase("verify")(投 PhaseChange),再 run_verify_gate(投 VerifyVerdict)。
            async for ev in self._enter_phase("verify"):
                yield ev

            # 人性化(2026-06-16 用户反馈):纯对话 / 纯读问答 —— 本轮没改任何东西
            # (made_changes=False)、没声明 verify_cmd、没探针 lane —— 像 Claude Code 一样直接
            # 好好答复,不走验证门那套:不跑 gate、不投 VerifyVerdict、report 也不显示
            # "完成。未机检验证"。验证门是给【工程改动】的护城河,没改东西就没什么可验;硬走一遍
            # 只会把"你好"渲染成带判决的任务(啰嗦、像把闲聊当活干)。
            # 安全不变量:任何真改动(write_file/edit_file → made_changes)、用户显式声明的
            # verify_cmd、或探针 lane(propose_dom/gui_verify)都会让 conversational=False →
            # 工程任务护城河分毫不减。四阶段铁律仍守:verify/report 两 phase 照常进(只是 verify 静默)。
            if (not made_changes and self._verify_cmd is None
                    and self._pending_l3_strategy is None
                    and not self._pending_gui_expected_text):
                conversational_done = True
                last_verdict = None
                report_note = ""
                break

            # P4 策略生成:verify_cmd is None 且未 propose_verify → 按确定性规则推断验证策略,
            # 取首个可执行候选走现有 run_verify_gate(白名单/verify_dir 隔离/篡改检测全保留)。
            # 显式 verify_cmd / propose_verify 永远优先于推断 —— 用户声明压倒推断。
            # ARGOS_NO_VERIFY_STRATEGY=1 关闭(回归旧行为)。
            # 策略推断只对【真改过代码】的任务(与上方 H2 verify_nudged 的 made_changes 守卫对齐)。
            # 对话 / 纯读 / 问答(made_changes=False)绝不推断 verify —— 否则"你好"会在有 pytest 的项目里
            # 被 _pick_strategy_cmd 推断成 pytest,跑空 verify 目录 no-tests 失败 → bounce → 模型被迫
            # "找测试",把一句问候变成跑 pytest+翻目录的任务(2026-06-14 真机 bug)。
            if (self._verify_cmd is None and made_changes
                    and not os.environ.get("ARGOS_NO_VERIFY_STRATEGY")):
                self._verify_cmd = self._pick_strategy_cmd(goal)

            # A2 L3 DOM 探针：_pick_strategy_cmd 若选中 L3 dom_assert 策略，
            # _pending_l3_strategy 已被设置且 _verify_cmd 仍为 None。
            # 此时不走 run_verify_gate（无 shell 命令），而是同步调 DomProber → 三态 Verdict。
            # 安全不变量：
            #   · 只有 _dom_prober 已注入才会有 _pending_l3_strategy（_pick_strategy_cmd 保证）。
            #   · error 非空 → unverifiable（诚实）；error 空 found=False → failed（真实证据）；
            #     found=True → passed（用户级，走既有 break/report 路径）。
            #   · 显式 verify_cmd 不会到达此分支（_verify_cmd is None 才走策略生成）。
            # 探针 lane 标记:DOM/GUI 探针产出的 passed 是用户级机检判决,但 verify_cmd 仍为 None,
            # 下方完成 break 原本要求 verify_cmd 非空 → 探针 passed 会被漏判而 bounce。此标记让
            # 探针 passed 也能正常收尾(failed/unverifiable 仍走既有 bounce / NO_TEST 路径)。
            _probe_lane_verdict = False
            if self._pending_l3_strategy is not None and self._verify_cmd is None:
                verdict = await self._run_dom_probe_verdict(
                    self._pending_l3_strategy, attempt=self._fail_count + 1
                )
                self._pending_l3_strategy = None  # 已消费，清空
                self._pending_dom_expected_text = ""  # 同步清空
                _probe_lane_verdict = True
            elif self._pending_gui_expected_text and self._verify_cmd is None:
                # 2d GUI 验证 lane:截图+OCR 独立断言屏上文本(无 shell 命令,与 DOM 探针同构)。
                verdict = await self._run_gui_probe_verdict(
                    self._pending_gui_expected_text, attempt=self._fail_count + 1
                )
                self._pending_gui_expected_text = ""  # 已消费，清空
                _probe_lane_verdict = True
            else:
                # W2:run_verify_gate 跑 verifier 出三态 Verdict,投 VerifyVerdict;真问题超
                # max_rounds 时它自己投 Escalation。loop 据返回的 verdict 决定 break / bounce。
                verdict = await self._harness.run_verify_gate(
                    self._verify_cmd, attempt=self._fail_count + 1
                )
            last_verdict = verdict
            # 压缩后的诚实兜底:这一刻真重跑过 verify(退出码为准)→ 标记已重验,
            # passed 才可信(trust_passed_after_compaction)。无论结局如何都置位:重验确实发生了。
            self._reverified_since_compact = True
            # autonomy 升级(任务):verdict=unverifiable + 有声明 verify_cmd → 不假装通过,
            # 走 ApprovalGate 问人(防 agent 篡改评判它的测试或 verifier 超时降级时蒙混)。
            # 关键护城河:unverifiable + 有声明 = 必须升级;verifier.py 已 fail-closed,
            # 不会返 passed,这里只是把 unverifiable 显式升级为 ask(避免悄悄 bounce 误判)。
            if verdict.status == "unverifiable" and self._verify_cmd is not None:
                try:
                    from argos.permissions.autonomy import (
                        AutonomyPolicy, on_unverifiable_completion,
                    )
                    from argos.permissions.config import get_config as _pc_get
                    _autonomy = on_unverifiable_completion(
                        verify_cmd=self._verify_cmd, verdict=verdict,
                        policy=AutonomyPolicy.from_permissions_config(_pc_get()),
                    )
                except Exception:  # noqa: BLE001 — autonomy 模块出错不阻断 run
                    _autonomy = None
                if _autonomy is not None:
                    zone, reason = _autonomy
                    if zone.value == "red" and self._broker is not None:
                        try:
                            desc = _i18n_t("loop.verify_gate.unverifiable_needs_confirmation", reason=reason)
                            decision = await self._broker.gate.request(
                                "autonomy_unverifiable", {"verify_cmd": self._verify_cmd},
                                description=desc, risk="high", timeout=120.0,
                            )
                            if not decision.approved:
                                # 用户拒绝升级 → 走既有 bounce/escalate 路径(不假装完成)
                                self._fail_count += 1
                                if self._fail_count > self._cfg.max_rounds:
                                    escalated = True
                                    break
                                bounce = _i18n_t(
                                    "loop.verify_gate.user_rejected_bounce",
                                    verify_cmd=self._verify_cmd,
                                    detail=verdict.detail,
                                )
                                messages.append({"role": "user", "content": bounce})
                                step += 1
                                continue
                            # 用户批准继续 → 收尾(降级为 unverifiable 完成,标 NO_TEST)
                            if self._compacted:
                                report_note = _i18n_t(
                                    "loop.report_note.unverifiable_user_confirmed_compacted",
                                    verdict_status=verdict.status,
                                )
                            else:
                                report_note = _i18n_t(
                                    "loop.report_note.unverifiable_user_confirmed",
                                    verdict_status=verdict.status,
                                )
                            break
                        except Exception:  # noqa: BLE001 — gate 异常不阻断 run
                            pass
            for ev in self._hbus.drain():
                yield ev

            # #9 T5:auto-capture verify fail(失败命令 + stderr hash + 200 字 snippet)
            if verdict.status == "failed" and self._verify_cmd:
                try:
                    from argos.memory import auto as _mem_auto
                    from argos.memory.auto import project_id_for as _pid
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
            # context rot 兜底(spec 2026-06-07):发生过(有损)压缩且压缩后没真重验过 → passed
            # 不可信,不在此 break(正常流程 run_verify_gate 刚跑过 → reverified=True,这是防御)。
            # E4 防火墙:必须用 is_user_verified 判,绝不能仅看 status=="passed" —— 自验证
            # 通过(系统按 reviewer + canary 守卫自造测试)status 也 "passed",但不是用户级
            # verify;若此 break 放它过,下游 run_success memory 会污染 + worker 透传给
            # learning hook 触发 distill/promote(reward-hacking)。落到下方 harness fallback
            # 路径走 unverifiable / bounce 才是真问题信号,而不是被"自验证"遮蔽。
            from argos.core.honesty import trust_passed_after_compaction
            if (getattr(verdict, "is_user_verified", False)
                    and (self._verify_cmd is not None or _probe_lane_verdict)
                    and trust_passed_after_compaction(
                        compacted=self._compacted,
                        reverified=self._reverified_since_compact)):
                if self._compacted:
                    report_note = _i18n_t("loop.report_note.compacted_reverified")
                break                        # 通过 → 收尾(用户级)
            if self._harness.is_honest_completion(verdict, verify_cmd=self._verify_cmd):
                # HONESTY CORRECTION:无测任务的诚实非阻塞完成 —— 收尾,report 标"未机检验证"。
                # 若发生过(有损)压缩且无可机检命令 → 诚实加注:记忆有损且无法机检确认进度,
                # 仍判 unverifiable(NO_TEST),绝不假装 passed(spec 2026-06-07)。
                if self._compacted:
                    report_note = _i18n_t("loop.report_note.no_test_compacted")
                else:
                    report_note = _i18n_t("loop.report_note.no_test")
                break
            # 到这里:failed,或配了 cmd 却 unverifiable(篡改/超时)→ 真问题 → bounce/escalate。
            self._fail_count += 1
            if self._fail_count > self._cfg.max_rounds:
                # 此刻 run_verify_gate 这一轮(attempt = 本次 _fail_count,即 max_rounds+1)已
                # 投出 Escalation —— 二者同一判据(attempt > max_rounds)同轮触发,诚实终止。
                escalated = True
                break
            bounce = _i18n_t(
                "loop.verify_gate.bounce",
                verify_cmd=self._verify_cmd,
                detail=verdict.detail,
            )
            messages.append({"role": "user", "content": bounce})
            step += 1

        # ── 阶段门补齐 + 真跑 verify(bailout 路径) ──
        # 历史 bug(2026-06-09,#1):while 自然退出(max_steps 耗尽)时,代码落到下方
        # enter_phase("report") → harness 还在 act(idx=1) → 跳到 report(idx=3) 触发
        # "阶段不可跳" ValueError。被 best_of_n 1/3 候选踩中。
        # 历史 bug(2026-06-09,#2,本修):只 enter_phase("verify") 不跑 verify_gate
        # → last_verdict=None → bridge winner.verdict=None → bench 把任务记为
        # failed(0% pass@1)。但 max_steps 耗尽≠"啥也没产出",模型可能真写了代码、装了
        # 包、产物可验 —— 必须复用真 verify 路径让 verifier 决定结局:
        #   · passed → last_verdict=passed(诚实反映产物真过了)
        #   · failed → last_verdict=failed(报告如实标"未通过",不假装通过)
        #   · unverifiable+verify_cmd=None → is_honest_completion(NO_TEST 收尾)
        #   · unverifiable+verify_cmd=... → last_verdict=unverifiable(报告如实标)
        # 不走 run_verify_gate 的 autonomy/escalation 侧路:已 bailout,无下一步可走,
        # 不再升级(没意义)也不再 bounce(会死循环)—— 只取 verdict 真值。
        from argos.core.harness import PHASE_ORDER
        if self._harness._phase_idx < PHASE_ORDER.index("verify"):
            async for ev in self._enter_phase("verify"):
                yield ev
            # 真跑一次 verify(同 run_verify_gate 的核心三行:验 + emit + 返 verdict),
            # 但省略 autonomy/escalation 侧路(已 bailout,无后续可走)。
            from argos.protocol.events import VerifyVerdict as _VV
            _bailout_verdict = self._harness.verifier.verify(
                self._verify_cmd, attempts=self._fail_count + 1,
            )
            await self._harness.bus.emit(_VV(verdict=_bailout_verdict))
            for ev in self._hbus.drain():
                yield ev
            last_verdict = _bailout_verdict
            # 跟正常 verify 路径一致:发生过 verify → 标记已重验(兜底压缩后用)。
            self._reverified_since_compact = True

        # 跨轮上下文:把本轮【最终 assistant 回答】持久化(get_messages 跨轮还原时带回)。
        # 否则历史只剩单边 user goal、agent 记不住自己上轮答了啥 → "好的/继续"接不上。
        # 只存最终答(非每个 act 步):内部代码步是 scratch,产物已落盘可 read_file 回看,
        # 跨轮上下文保持精简;增长由 compaction(批3)兜底。
        # 关键修复:即使最终段为空(模型用空 turn 宣布完成、或答复被 scrubber 清空),也必须落
        # 一条占位 assistant —— 否则本轮历史只剩单边 user(goal),连续多轮会在 DB 堆出
        # [user, user, user...],模型看不出是独立任务、也记不住自己做过啥(=用户看到的"没串上下文")。

        # #9 T5:auto-capture escalation / run_success(escalation 在 run 末尾,capture 一次)
        try:
            from argos.memory import auto as _mem_auto
            from argos.memory.auto import project_id_for as _pid
            if escalated:
                _mem_auto.capture_event(
                    "escalation_decision",
                    project_id=_pid(self._workspace),
                    reason=escalation_reason,
                    user_reply="escalated",
                )
            elif (not report_note and step >= 5
                  and last_verdict is not None
                  and getattr(last_verdict, "is_user_verified", False)):
                # run_success:用户级 passed 且 ≥5 步 → 记 goal + key_cmd
                # E4 防火墙:必须 is_user_verified 判,自验证通过绝不写 run_success —— 否则
                # 跨会话 memory graph 会被 reward-hacked 成功污染,后续 reflection / distill
                # 据此学"成功模式",放大自验证的死亡螺旋。
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
                persisted = _i18n_t("loop.persisted.escalated")
            elif report_note:
                persisted = _i18n_t("loop.persisted.with_note", report_note=report_note)
            else:
                persisted = _i18n_t("loop.persisted.done")
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
        if conversational_done:
            done = ""   # 纯对话/纯读问答:只给答复本身,不加任何完成判决行(像 Claude Code 直接答)
        elif escalated:
            done = _i18n_t("loop.done.escalated")
        elif report_note:
            done = _i18n_t("loop.done.with_note", report_note=report_note)
        elif last_verdict is not None and getattr(last_verdict, "is_user_verified", False):
            # E4 防火墙:必须用 is_user_verified 判,绝不能仅看 status=="passed" —
            # self_verified=True 的 passed 是系统自造测试"弱通过",与用户级 verify 同字会骗用户。
            done = _i18n_t("loop.done.verified")
        elif (last_verdict is not None
              and getattr(last_verdict, "status", None) == "passed"
              and getattr(last_verdict, "self_verified", False)):
            # 自验证"较弱"通过(系统按 reviewer + canary 守卫自造测试),显式标 weaker,绝不冒充强验证
            done = _i18n_t("loop.done.self_verified")
        elif last_verdict is not None and getattr(last_verdict, "status", None) != "passed":
            done = _i18n_t("loop.done.verdict_bad")
        else:
            done = _i18n_t("loop.done.generic")
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
        if done:   # 对话轮 done="" → 不投空完成行,答复本身已在 act 阶段流式给出
            yield TokenDelta(text=done)

    async def _run_workflow(self, raw_spec: dict, messages: list) -> "AsyncIterator[Event]":
        """校验 spec → WorkflowProposed(预览)→ 审批(await gate,异步态不死锁)→ 引擎异步跑 →
        WorkflowDone → 结果作 feedback 回灌 parent。校验失败/被拒/无引擎 → 诚实回错,不崩 run。"""
        from argos.protocol.events import WorkflowProposed, WorkflowDone
        from argos.workflow.result import render_preview
        from argos.workflow.spec import WorkflowSpecError, parse_spec
        import uuid as _uuid
        if self._workflow_engine_factory is None:
            messages.append({"role": "user", "content": _i18n_t("loop.workflow.no_engine")})
            return
        try:
            spec = parse_spec(raw_spec)
        except WorkflowSpecError as e:
            messages.append({"role": "user", "content": _i18n_t("loop.workflow.spec_invalid", error=e)})
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
                messages.append({"role": "user", "content": _i18n_t("loop.workflow.rejected")})
                return
        engine = self._workflow_engine_factory()
        async for ev in engine.run(spec):
            yield ev
        result = engine.last_result
        synth = result.synthesis if result else _i18n_t("loop.workflow.no_result")
        notes = result.notes if result else ()
        yield WorkflowDone(name=spec.name, synthesis=synth, notes=notes)
        summary = _i18n_t("loop.workflow.result_summary", name=spec.name, synthesis=synth)
        if notes:
            summary += _i18n_t("loop.workflow.result_notes", notes=" / ".join(notes))
        messages.append({"role": "user", "content": summary})

    # plan 决策超时(秒)。daemon 客户端断连/不应答时触发,fail-closed 默认取消。
    # TUI inline 路径响应极快,不受此超时影响(ExitPlanMode 直接 set event)。
    PLAN_DECISION_TIMEOUT_S: float = 300.0  # 5 分钟等待上限

    # ── Plan mode (spec §2.5) ──────────────────────────────────────────
    async def _run_plan_phase_loop(
        self, goal: str, messages: list[dict], system: str,
    ) -> "AsyncIterator[Event]":
        """Plan mode 子循环:流式模型一次 → 拼 markdown → 投 PlanRendered → 挂起等决策。

        退出条件:approve_start / approve_accept_edits(均跳出,后者切 _approval_level_override)。
        子循环条件:keep_planning(同 goal 再来一轮) / refine(feedback 注入 messages 再来一轮)。
        注:PlanUpdate (todos) 也在每个 plan 轮内同步 yield,活动栏进度随 plan 更新。

        fail-closed 语义(spec §6 信任面 + 审批回路铁律):
        · 超时(daemon 客户端断连/不应答) → 投诚实 Error 事件 + cancel run,不放行计划。
        · decision is None(不应发生,防御路径) → 同样 cancel,不自动 approve。
        """
        while True:
            async for ev in self._plan_phase_round(goal, messages, system):
                yield ev
            # 挂起等 TUI 弹 PlanModal 决策 —— ExitPlanMode 会 set event 唤醒。
            # wait_for 超时 → fail-closed:投诚实 Error + 终止循环(不继续 act 阶段)。
            try:
                await asyncio.wait_for(
                    self._plan_decision_event.wait(),
                    timeout=self.PLAN_DECISION_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                yield Error(
                    message=_i18n_t(
                        "loop.plan.timeout",
                        timeout=self.PLAN_DECISION_TIMEOUT_S,
                    ),
                    chain=["asyncio.TimeoutError: plan_decision_event.wait() timed out"],
                )
                # 清注册表(防止残留 call_id 被重复使用)
                self._plan_call_registry.clear()
                # 抛出 CancelledError 终止整个 run,由顶层 run() 捕获落盘 Error。
                raise asyncio.CancelledError("plan_decision_timeout")
            decision = self._plan_decision
            if decision is None:
                # 边界防御:正常路径 ExitPlanMode 必写 _plan_decision;None 不应发生。
                # fail-closed:不自动 approve,投诚实 Error 并取消。
                yield Error(
                    message=_i18n_t("loop.plan.decision_none"),
                    chain=["AssertionError: _plan_decision is None after event.wait()"],
                )
                self._plan_call_registry.clear()
                raise asyncio.CancelledError("plan_decision_none")
            if decision.action == "approve_start":
                # 跳出子循环 → _drive 继续走 act 阶段。
                return
            if decision.action == "approve_accept_edits":
                # 临时切 approval_level 到 ACCEPT_EDITS(act 阶段完了在 _reset_run_state 恢复)。
                from argos.approval import ApprovalLevel
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
        from argos.core.observability import PRICING, cost_of
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
            # #11 per-task routing:plan 阶段也带 tier_name(默认 = config.model_tier)。
            tier_name=self._current_tier,
        )

        # 拼 markdown → 投 PlanRendered 事件(TUI 弹 PlanModal 用此渲染)。
        # 工具调用序列在 plan 阶段空(plan 模式不执行);involves files 段也空,等 act 后回填。
        plan_md = PlanRenderer.render(
            goal=goal, todos=list(self._todos), tool_calls=[],
        )
        yield PlanRendered(plan_md=plan_md)

        # v6 §4 ACP:同步投 PlanDecisionRequest(与 PlanRendered 同构 call_id 路由)。
        # daemon 路径经 POST /runs/{id}/plan_decision?call_id=... 回传决策;
        # TUI inline 路径仍走 ExitPlanMode(loop, ...) 直接设 _plan_decision_event。
        # 注册 call_id → 当前 _plan_decision_event(本轮 wait 用的那个 Event),
        # respond_plan_decision 据此唤醒 loop。
        import secrets as _secrets
        _call_id = _secrets.token_hex(6)  # 12 hex,与 ApprovalRequest 格式一致
        self._plan_call_registry[_call_id] = self._plan_decision_event
        yield PlanDecisionRequest(call_id=_call_id, plan_md=plan_md)

    @staticmethod
    def _feedback(result: Any) -> str:
        """把 ExecResult 转成给模型回灌的文本。"""
        from argos.i18n import t as _t_fb
        if not result.ok:
            return _t_fb("loop.exec.exception", exc=result.exc)
        out = result.stdout
        if result.value_repr:
            out += _t_fb("loop.exec.value_repr", value_repr=result.value_repr)
        out = _clamp_feedback(out)   # 病态大输出 head+tail 截断,防每步全量回灌撑爆输入 token
        return _t_fb("loop.exec.result", out=out) if out.strip() else _t_fb("loop.exec.no_output")


# 运行时懒 import(避免顶层与 broker/receipts 形成 import 环;仅无 broker 占位用)。
from argos.tools.receipts import ReceiptSigner as _ReceiptSigner  # noqa: E402
