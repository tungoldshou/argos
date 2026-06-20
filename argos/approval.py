"""审批闸 —— 工具调用前同步等用户决定,默认 deny。

架构选择:用工具自声明(@requires_approval)而非黑盒 middleware,原因:
  · 工具自己最清楚自己副作用的语义,弹窗能展示'人类可读描述'(如"将写入 app.py")。
  · 与 LangChain 解耦,LangChain 升级不破坏审批层。
  · 1 个工具 1 个声明,比'全局按名字拦截'更精确。
  · 弹窗是可选 UI:headless / 测试 / agent loop 模式可注入自己的 ApprovalGate。

Phase 3 Task 9 迁移(契约 §6.3 锁#3):
  · Decision: (approved, scope) → (kind: DecisionKind, reason) frozen dataclass;approved 改为 property。
  · ApprovalLevel: 新增 OBSERVE/PROPOSE/CONFIRM/AUTO 四档枚举。
  · ApprovalGate.request: 新签名 request(action, args, *, description, risk, timeout)。
  · ApprovalGate.respond: 新方法,对应旧 approve()+deny();旧方法保留 backward-compat。
  · guarded_call: 新签名 guarded_call(action, args, run, *, description, risk, timeout)。
"""
from __future__ import annotations

import asyncio
import contextvars
import enum
import functools
import inspect
import json
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:
    from argos.permissions.evaluator import DecisionMeta  # noqa: F401


RiskLevel = Literal["low", "medium", "high"]
DecisionKind = Literal["deny", "once", "session", "always"]


class ApprovalLevel(enum.Enum):
    OBSERVE = "observe"   # 只看,不执行副作用
    PROPOSE = "propose"   # 出方案待批
    CONFIRM = "confirm"   # 逐个批(默认)
    AUTO = "auto"         # 放手(YOLO;TUI 头部亮红 ⏻)
    ACCEPT_EDITS = "accept_edits"   # plan mode 选项 2(approve and accept edits):写/编辑工具自动批


@dataclass(frozen=True, slots=True)
class Decision:
    """契约 §6.3 锁#3:kind 字段 + approved property,无 scope 字段。"""
    kind: DecisionKind               # deny | once | session | always
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.kind != "deny"


@dataclass
class _Pending:
    call_id: str
    payload: dict[str, Any]
    created_at: float  # 留作 UI 排序/超时提示用,目前未消费
    future: asyncio.Future[Decision]
    # future 绑定在「创建它的那个事件循环」上。被审批的工具可能跑在 langchain 的执行线程
    # (有自己的 loop),而 approve/deny 来自主 loop —— 跨 loop 直接 set_result 不会唤醒
    # 工具所在的 loop。记下该 loop,统一用 call_soon_threadsafe 调度,两种情况都对。
    loop: asyncio.AbstractEventLoop


def _resolve(fut: asyncio.Future, decision: "Decision") -> None:
    """在 future 所属 loop 上安全收尾:可能已超时/取消,先查 done 再 set。"""
    if not fut.done():
        fut.set_result(decision)


@dataclass
class _SessionApproval:
    """session-scope 缓存:同一 payload 整个 session 都被默许。"""
    payload_hash: str
    approved_at: float


def _hash_payload(payload: dict[str, Any]) -> str:
    """稳定 hash —— 顺序无关,便于同 payload 命中缓存。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _derive_allow_matcher(action: str, args: dict[str, Any]) -> tuple[str, str]:
    """从一次「总是允许」派生持久 allow 规则的 (tool, matcher)。matcher 走 re.search 语义。
    - run_command → 锚定的【二进制 + 子命令】:'git status' → '^git\\s+status(\\s|$)';
      'pip install x' → '^pip\\s+install(\\s|$)';'pytest -q'(次词是 flag)→ '^pytest(\\s|$)'。
      为什么不只取首词(2026-06-20 review #2/#6):裸 'git' 子串会让"总是允许 git status"悄悄放行
      'git push'(外泄)/ 'git config'(改身份)/ 'git remote add'(指向攻击者),且这些联网子命令会
      被自动开出网阀——授权范围远超用户看到的 'git status'。check_hard_shell 也不拦 git 子命令。
      锚定到二进制+子命令把授权收窄到用户真正批准的那类命令;子串误配('mygit' 命中 'git')也一并堵死。
    - 其它工具 → matcher='*'(整工具放行 = 用户'别再问这个工具了')。"""
    import re as _re
    if action == "run_command":
        cmd = str((args or {}).get("command", "")).strip()
        toks = cmd.split()
        if toks:
            parts = [_re.escape(toks[0])]
            # 多路复用二进制(git/npm/pip/docker/…)按"二进制+首个非 flag 子命令"锚定;次词是 flag
            # (-x)或无次词 → 仅锚定二进制(pytest/ls 这类非多路复用,放行同二进制各调用是合理的)。
            if len(toks) > 1 and not toks[1].startswith("-"):
                parts.append(_re.escape(toks[1]))
            return action, "^" + r"\s+".join(parts) + r"(\s|$)"
    return action, "*"


class ApprovalGate:
    """每个 session 一个实例。契约 §6.3:level 拨盘 + respond 速选(1=deny 2=once 3=session 4=always)。
    保留旧的跨 loop 唤醒、超时 fail-closed、session 缓存语义。
    旧 approve()/deny() 方法保留 backward-compat(server.py 旧路径使用中)。

    Smart approval(spec 2026-06-06 §2.6):request() 在 gate.level 短路前先跑 evaluator
    串联 hard → soft → level,把决策来源贴上 trigger 标签;deny / approve 都写 AuditLog;
    ask 仍走原弹窗等用户。set_workspace 让 evaluator 拿到 workspace 边界(workspace 内文件
    不走系统路径 deny)。"""

    def __init__(
        self,
        level: ApprovalLevel = ApprovalLevel.CONFIRM,
        *,
        permissions_config: "Any | None" = None,
        audit_log: "Any | None" = None,
    ) -> None:
        self.level = level
        self._pending: dict[str, _Pending] = {}
        self._session_approvals: dict[str, _SessionApproval] = {}
        # Smart approval(spec 2026-06-06):workspace 边界,evaluator 据它跑 system_path check。
        # None = 不知(测试 / headless 默认),evaluator 走原 system path 系统前缀 deny 路径。
        self._workspace: str | None = None
        # session_id 供 AuditLog 关联(诚实:无 id 时落空串而非编造)。
        self._session_id: str = ""
        # 决策回调(TUI ActivityPanel 接入):接 (action, decision_str, trigger)。
        # 默认空 lambda(headless / 测试无 UI)→ 不抛。
        self._decision_listener: Callable[[str, str, str], None] | None = None
        # 「需要交互审批」带外回调(2026-06-18 修):gate 进 ask 路径时同步调 fn(call_id, ask_payload)。
        # inline 模式下,broker-gated 工具的审批在 exec_code(已挪进 to_thread)中经桥发起,此刻
        # loop 的事件生成器正阻塞在 await,yield 不出 ApprovalRequest → TUI 收不到、永远不 mount
        # 审批卡 → 工具干等到超时。此回调是带外通道:让 TUI 直接 mount 卡。仅对【gate 自生成 call_id】
        # 的 ask 触发(工具桥);调用方预传 call_id 的(workflow/plan/intent)已由 loop 自投事件,不重复。
        self._ask_listener: Callable[[str, dict[str, Any]], None] | None = None
        # per-session 注入实例(为多 run 并发铺路):由 build_components 传入;
        # None = fallback 到模块级单例(向后兼容测试/headless 路径)。
        self._permissions_config: Any | None = permissions_config
        self._audit_log: Any | None = audit_log
        # L0/L2 Trust Dial 语义标志(由 set_trust_level 写入):
        # _ask_readonly  : L0 → True,让 evaluator 把 approve 升格 ask(含只读动作)。
        # _reversible_check: L2 → True,让 evaluator 走 reversible_lookup 路径。
        # _reversible_lookup: app_factory 从 CapabilityRegistry manifest 构造并注入;
        #   None = 保守退化(L2 时所有动作均保守 ask)。
        self._ask_readonly: bool = False
        self._reversible_check: bool = False
        self._reversible_lookup: "Callable[[str], bool | None] | None" = None
        # L1「只有危险操作才问」语义:低危(registry risk=low)动作在默认决策处自动放行。
        # 仅 set_trust_level(L1) 置 True;普通 CONFIRM 档(未走 trust dial)保持 False → 行为不变。
        self._low_risk_auto: bool = False

    def set_level(self, level: ApprovalLevel) -> None:
        self.level = level

    def set_trust_level(self, trust: "Any") -> None:
        """将 TrustLevel 映射到 ApprovalLevel 并写入 gate（Trust Dial 接线入口）。

        接受 TrustLevel 枚举实例。映射规则来自 trust_dial.to_approval_semantics()：
          L0_EVERY_STEP        → CONFIRM（ask_readonly=True：只读也问，evaluator 升格 approve→ask）
          L1_DANGEROUS_ONLY    → CONFIRM（仅高风险问；默认行为）
          L2_IRREVERSIBLE_ONLY → CONFIRM（不可逆才问；依赖 reversible_lookup；
                                          lookup 返回 True → 放行；False/None → 保守 ask）
          L3_SESSION_TRUSTED   → ACCEPT_EDITS（同类批过后本会话放行）
          L4_AUTONOMOUS        → AUTO（全自治；TUI 显红灯）

        HARD RULES 在任何档位继续生效（由 evaluator hard 层强制；不经此方法绕过）。
        L2 reversible_lookup 来自注入的 _reversible_lookup;未注入时退化保守 ask（不问任何 False/None 也问）。
        """
        from argos.permissions.trust_dial import TrustLevel, to_approval_semantics
        sem = to_approval_semantics(trust)
        al_str = sem["approval_level"]
        self.set_level(ApprovalLevel(al_str))
        # L0 ask_readonly 语义：True → evaluator 把 approve 升格为 ask（含只读动作）。
        self._ask_readonly: bool = bool(sem.get("ask_readonly", False))
        # L2 reversible_check 语义：True → evaluator 调用 _reversible_lookup 查表。
        self._reversible_check: bool = bool(sem.get("reversible_check", False))
        # L1 low_risk_auto 语义：True → evaluator 默认决策处对低危动作自动放行（中/高危仍 ask）。
        self._low_risk_auto: bool = bool(sem.get("low_risk_auto", False))
        # 存原始档位供 /trust status 精确回读(反向映射 ApprovalLevel→TrustLevel 有损:
        # L0/L1/L2 都落在 CONFIRM,status 会把 L2 误报成 L1 —— 对用户撒谎,不允许)。
        self._trust_level = trust

    def set_workspace(self, workspace: str | None) -> None:
        """Smart approval(spec 2026-06-06 §2.3 / D14):host 启动时把当前 workspace 注入
        gate,evaluator 据此跑 workspace 边界 check(workspace 内写文件不算系统路径)。"""
        self._workspace = workspace

    def set_reversible_lookup(self, fn: "Callable[[str], bool | None] | None") -> None:
        """注入 L2 可逆性查表函数(Trust Dial §6.2)。

        L2_IRREVERSIBLE_ONLY 档位下,evaluator 调用 fn(action) 查询动作是否可逆：
          fn 返回 True  → 可逆,自动放行(trigger="trust:L2 可逆放行")。
          fn 返回 False → 不可逆,保守 ask。
          fn 返回 None  → reversible 未知,保守 ask。
          fn 抛异常     → 保守 ask(fail-closed)。

        由 app_factory 从 CapabilityRegistry.get(action).reversible 构造并注入；
        未注入（None）= 保守退化（L2 下所有动作均 ask）。
        HARD RULES/secret/soft deny 路径不受此函数影响。
        """
        self._reversible_lookup = fn

    def set_session_id(self, session_id: str) -> None:
        """绑定 AuditLog 的 session_id(供 jsonl 行携带 session 关联)。"""
        self._session_id = session_id or ""

    def set_decision_listener(self, fn: Callable[[str, str, str], None] | None) -> None:
        """TUI ActivityPanel 接入:每次 evaluator 出结论 → 调 fn(action, decision_str, trigger)。
        decision_str ∈ {approved, denied, asked}。None = 取消监听(headless / 测试默认)。"""
        self._decision_listener = fn

    def set_ask_listener(self, fn: "Callable[[str, dict[str, Any]], None] | None") -> None:
        """带外「需交互审批」回调:gate 进 ask 路径且 call_id 为本 gate 自生成(= 工具桥,
        非 workflow/plan/intent 预传)时,同步调 fn(call_id, ask_payload)。inline 模式 TUI 据此
        mount 审批卡(exec_code 在 to_thread 中,loop 生成器阻塞、yield 不出 ApprovalRequest)。
        None = 取消(headless / daemon 路径不用此通道,走 SSE)。"""
        self._ask_listener = fn

    def pending(self) -> list[_Pending]:
        return list(self._pending.values())

    async def request(self, action: str, args: dict[str, Any], *, description: str,
                      risk: RiskLevel, timeout: float = 60.0,
                      call_id: str | None = None) -> Decision:
        """阻塞等用户决定(契约 §6.3 签名 + spec 2026-06-06 §2.6 Smart approval 接入)。

        Smart approval 评估顺序(D15 锁):
          1. evaluator 跑 hard → soft deny → soft allow → soft ask → per-tool → default
          2. evaluator → "approve" → Decision(kind=once) + AuditLog 写 approved
          3. evaluator → "deny" → Decision(kind=deny, reason=evaluator.reason) + AuditLog 写 denied
          4. evaluator → "ask" → 走原弹窗等用户 respond,respond 时再写一次 AuditLog
        gate.level=AUTO/OBSERVE 仍走原快捷路径(短路在 evaluator 决策后),
        session 缓存继续在 ask 之上作用(用户已 session-allow 同 payload → 不再弹窗)。

        evaluator 调用包 try/except:Smart approval 模块出错 → 退回原审批语义(legacy
        fast-path),不让 evaluator bug 阻塞调用方。
        """
        # 1) Smart approval 评估(spec 2026-06-06 §2.6)。risk 透传:L1 低危自动放行据此判定。
        eval_meta = self._evaluate(action, args, risk=risk)
        if eval_meta is not None:
            if eval_meta.decision == "approve":
                self._audit(
                    action=action, args=args, decision="approved",
                    trigger=eval_meta.trigger, by="rule" if eval_meta.rule_name else "level",
                    risk=risk, secret_pattern=eval_meta.secret_pattern,
                )
                self._notify("approved", action, eval_meta.trigger)
                return Decision(kind="once", reason=eval_meta.reason or eval_meta.trigger)
            if eval_meta.decision == "deny":
                self._audit(
                    action=action, args=args, decision="denied",
                    trigger=eval_meta.trigger, by="rule",
                    risk=risk, secret_pattern=eval_meta.secret_pattern,
                )
                self._notify("denied", action, eval_meta.trigger)
                return Decision(kind="deny", reason=eval_meta.reason or eval_meta.trigger)
            # decision == "ask" → fallthrough 到原弹窗等用户 respond 路径
        # 2) legacy fast-path(gate.level 短路;Smart 评估 ask 也走到这里)
        if self.level is ApprovalLevel.AUTO and (eval_meta is None or eval_meta.decision != "ask"):
            self._audit(
                action=action, args=args, decision="approved",
                trigger="level:auto", by="level", risk=risk,
            )
            self._notify("approved", action, "level:auto")
            return Decision(kind="once", reason="AUTO 档放手")
        if self.level is ApprovalLevel.OBSERVE and (eval_meta is None or eval_meta.decision != "ask"):
            self._audit(
                action=action, args=args, decision="denied",
                trigger="level:observe", by="level", risk=risk,
            )
            self._notify("denied", action, "level:observe")
            return Decision(kind="deny", reason="OBSERVE 档:只看不执行副作用")
        # 3) session 缓存命中:同 payload 整 session 已批 → 不再弹窗
        payload = {"action": action, "args": args}
        key = _hash_payload(payload)
        if self._session_approvals.get(key) is not None:
            self._notify("approved", action, "session:cached")
            return Decision(kind="session", reason="session 已批准")
        # 4) ask:挂起等 respond
        # call_id 可由调用方预生成(如工作流提议先投 WorkflowProposed 携带 call_id,TUI 据它放行);
        # 未传则自生成,向后兼容。
        _caller_supplied_call_id = call_id is not None   # workflow/plan/intent 预传 → loop 已自投事件
        call_id = call_id or uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Decision] = loop.create_future()
        ask_trigger = eval_meta.trigger if eval_meta is not None else (
            f"level:{self.level.value}"
        )
        ask_payload: dict[str, Any] = {
            **payload, "description": description, "risk": risk,
            "trigger": ask_trigger,
        }
        if eval_meta is not None and eval_meta.secret_pattern:
            ask_payload["secret_pattern"] = eval_meta.secret_pattern
        self._pending[call_id] = _Pending(
            call_id=call_id, payload=ask_payload,
            created_at=time.time(), future=fut, loop=loop,
        )
        self._notify("asked", action, ask_trigger)
        # 带外 mount 审批卡:仅对 gate 自生成 call_id 的 ask(= broker 工具桥)触发 —— 调用方预传
        # call_id 的(workflow/plan/intent)已由 loop 自投事件 mount 过,避免重复弹卡(2026-06-18 修)。
        if not _caller_supplied_call_id and self._ask_listener is not None:
            try:
                self._ask_listener(call_id, dict(ask_payload))
            except Exception:  # noqa: BLE001 — 监听器(UI)出错不得阻塞 gate 决策
                pass
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(call_id, None)
            return Decision(kind="deny", reason="审批超时,默认拒绝")

    # ── Smart approval 内部 helper(spec 2026-06-06 §2.6) ──────────────
    def _evaluate(self, action: str, args: dict[str, Any],
                  risk: str = "medium") -> "DecisionMeta | None":
        """跑 evaluator;模块出错(import / config 坏)→ 返 None 退回 legacy 语义。
        优先使用注入的 permissions_config(per-session);无注入则 fallback 到模块级单例。
        L0/L1/L2 语义标志(ask_readonly / low_risk_auto / _reversible_check / _reversible_lookup)经参数透传。
        risk:动作风险(broker 从 registry/_RISK 查得后传入)——L1 低危自动放行据此判定。
        """
        try:
            from argos.permissions import evaluate, get_config
            cfg = self._permissions_config if self._permissions_config is not None else get_config()
            # L2:仅在 _reversible_check=True 时传入 reversible_lookup;否则传 None(保守/L1)。
            rl = self._reversible_lookup if getattr(self, "_reversible_check", False) else None
            return evaluate(
                action, args, gate_level=self.level, config=cfg,
                workspace=self._workspace,
                ask_readonly=getattr(self, "_ask_readonly", False),
                reversible_lookup=rl,
                low_risk_auto=getattr(self, "_low_risk_auto", False),
                risk=risk,
            )
        except Exception:  # noqa: BLE001 — Smart approval 出错绝不阻塞调用方
            return None

    def evaluate_sync(self, action: str, args: dict[str, Any]) -> "DecisionMeta | None":
        """同步暴露 evaluator 决策(hard → secret → soft → level),供 broker 对文件写做
        gate-only 治理(hard-path 系统路径拒 + 密钥检测),无需 await。
        None = evaluator 不可用(import/config 坏)→ 调用方退回既有语义,绝不阻塞。"""
        return self._evaluate(action, args)

    def _audit(
        self, *, action: str, args: dict[str, Any], decision: str, trigger: str,
        by: str, risk: str, secret_pattern: str | None = None,
    ) -> None:
        """写 AuditLog;模块出错(权限 / IO / import)→ 静默(spec §2.7 锁不抛)。
        优先使用注入的 audit_log(per-session);无注入则 fallback 到模块级单例。"""
        try:
            if self._audit_log is not None:
                log = self._audit_log
            else:
                from argos.permissions import get_audit_log
                log = get_audit_log()
            # session_id 通过 set_session_id 注入;未注入则落空串(诚实)
            log.session_id = self._session_id or log.session_id
            args_str = json.dumps(args, ensure_ascii=False, sort_keys=True)
            log.log(
                tool=action, args=args_str, decision=decision, trigger=trigger,
                by=by, secret_pattern=secret_pattern, risk=str(risk),
            )
        except Exception:  # noqa: BLE001 — audit 失败永不阻塞审批主路
            pass

    def _notify(self, decision: str, action: str, trigger: str) -> None:
        """触发 decision listener(TUI ActivityPanel 更新);未设监听 → 静默。"""
        fn = self._decision_listener
        if fn is None:
            return
        try:
            fn(action, decision, trigger)
        except Exception:  # noqa: BLE001 — UI 侧异常绝不阻塞审批
            pass

    def respond(self, call_id: str, decision: DecisionKind) -> bool:
        """TUI ApprovalModal 速选(1=deny 2=once 3=session 4=always)回灌。
        session → 加 session 缓存(本 session 不再问);always → 额外【持久化】一条 pattern allow 规则
        到 permissions.json,跨 session 再不问(像 Claude Code 的'总是允许';此前 always==session 是假持久,
        点了下次还问 —— 2026-06-20 修)。"""
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        if decision in ("session", "always"):
            payload = {"action": p.payload.get("action"), "args": p.payload.get("args")}
            key = _hash_payload(payload)
            self._session_approvals[key] = _SessionApproval(
                payload_hash=key, approved_at=time.time(),
            )
        if decision == "always":
            try:
                from argos.permissions import config as _pcfg
                tool, matcher = _derive_allow_matcher(
                    str(p.payload.get("action", "")), p.payload.get("args") or {},
                )
                if _pcfg.save_allow_rule(tool, matcher):
                    # 热更新本 gate 的 config,让持久规则【本 session】就立即生效(评估器 soft_allow 命中)。
                    self._permissions_config = _pcfg.get_config()
            except Exception:  # noqa: BLE001 — 持久化失败不阻塞审批(session 缓存仍覆盖本 session)
                pass
        self._settle(p, Decision(kind=decision))
        return True

    # ── backward-compat: 旧 approve()/deny() —— server.py 使用中,勿删 ──────────
    def approve(self, call_id: str, scope: Literal["once", "session"] = "once") -> bool:
        """backward-compat:把 scope 映射到新 respond。server.py 旧路径使用中。"""
        kind: DecisionKind = "session" if scope == "session" else "once"
        return self.respond(call_id, kind)

    def deny(self, call_id: str, reason: str = "") -> bool:
        """backward-compat:对应新 respond(call_id, "deny")。server.py 旧路径使用中。"""
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        self._settle(p, Decision(kind="deny", reason=reason))
        return True

    def cancel_all(self) -> int:
        """session 终止时调用,把所有挂着的请求以 deny 收尾(避免挂死)。"""
        n = 0
        for p in list(self._pending.values()):
            self._settle(p, Decision(kind="deny", reason="session 终止"))
            n += 1
        self._pending.clear()
        return n

    @staticmethod
    def _settle(p: _Pending, decision: "Decision") -> None:
        """把 decision 投递到 future 所属 loop。跨 loop 用 call_soon_threadsafe 唤醒;
        loop 已关闭(run 早退后才来的迟到决定)则安全忽略。"""
        try:
            p.loop.call_soon_threadsafe(_resolve, p.future, decision)
        except RuntimeError:
            pass  # event loop is closed


def requires_approval(description: str, risk: RiskLevel = "medium") -> Callable:
    """装饰器:标记该工具调用前需用户审批。description 里的 {arg_name} 会被替换。
    工具本体用字符串返回错误(同其他工具约定),让模型看到并换路,而不抛异常。"""

    def deco(fn: Callable) -> Callable:
        # 用 inspect 拿参数名,这样 _serialize_args 能闭包到 fn
        try:
            sig = inspect.signature(fn)
            param_names = list(sig.parameters.keys())
            var_positional = {n for n, p in sig.parameters.items()
                              if p.kind == inspect.Parameter.VAR_POSITIONAL}
            var_keyword = {n for n, p in sig.parameters.items()
                           if p.kind == inspect.Parameter.VAR_KEYWORD}
        except Exception:
            param_names = []
            var_positional = set()
            var_keyword = set()

        def _serialize(args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            extra_pos: list[Any] = []
            for i, a in enumerate(args):
                if i < len(param_names) and param_names[i] in var_positional:
                    extra_pos.append(a)
                    continue
                if i < len(param_names) and param_names[i] not in var_keyword:
                    key = param_names[i]
                else:
                    extra_pos.append(a)
                    continue
                try:
                    json.dumps(a)
                    out[key] = a
                except (TypeError, ValueError):
                    out[key] = repr(a)
            if extra_pos:
                try:
                    json.dumps(extra_pos)
                    out["*args"] = extra_pos
                except (TypeError, ValueError):
                    out["*args"] = repr(extra_pos)
            extra_kw: dict[str, Any] = {}
            for k, v in kwargs.items():
                if k in var_keyword:
                    extra_kw[k] = v
                    continue
                try:
                    json.dumps(v)
                    out[k] = v
                except (TypeError, ValueError):
                    out[k] = repr(v)
            if extra_kw:
                out["**kwargs"] = extra_kw
            return out

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> str:
            gate = _current_gate()
            if gate is None:
                # 无 gate 上下文(测试 / headless)→ fail-closed 拒绝,绝不放行
                return "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
            tool_name = getattr(fn, "__name__", str(fn))
            serialized_args = _serialize(args, kwargs)
            decision = await gate.request(
                tool_name, serialized_args,
                description=description,
                risk=risk,
            )
            if not decision.approved:
                return (
                    f"用户拒绝执行该操作({decision.reason or '未提供原因'})。"
                    f"请尝试其他做法或向用户解释为什么需要它。"
                )
            return await _call_original(fn, args, kwargs)

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> str:
            gate = _current_gate()
            if gate is None:
                return "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
            if asyncio.iscoroutinefunction(fn):
                return "错误:同步工具包装器收到了异步调用路径,这是内部错误。"
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False
            if in_loop:
                return "错误:同步工具不能在事件循环中等待审批,请改用异步版本。"
            return asyncio.run(async_wrapper(*args, **kwargs))

        # functools.wraps 已复制 __name__/__doc__/__wrapped__ —— __wrapped__ 让
        # inspect.signature(wrapper) 透传原签名,langchain @tool 才能建出正确的 args schema
        # (否则模型看到的是 (*args, **kwargs) 而非具名参数)。
        wrapper = async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper
        wrapper._approval_required = True  # type: ignore[attr-defined]
        wrapper._approval_description = description  # type: ignore[attr-defined]
        wrapper._approval_risk = risk  # type: ignore[attr-defined]
        return wrapper

    return deco


# ── gate 上下文(per-session,ContextVar 避免并发污染)──────────────────────────
_current_gate_var: contextvars.ContextVar["ApprovalGate | None"] = contextvars.ContextVar(
    "argos_approval_gate", default=None,
)


def set_current_gate(gate: "ApprovalGate | None") -> contextvars.Token:
    return _current_gate_var.set(gate)


def reset_current_gate(token: contextvars.Token) -> None:
    _current_gate_var.reset(token)


def _current_gate() -> "ApprovalGate | None":
    return _current_gate_var.get()


async def guarded_call(
    action: str,
    args: dict[str, Any],
    run: Callable[[], Any],
    *,
    description: str,
    risk: RiskLevel,
    timeout: float = 60.0,
) -> Any:
    """审批守卫(装饰器与 MCP 工具包装共用,契约 §6.3 新签名):
    · 无 gate 上下文 → fail-closed 返回拒绝串;
    · gate 拒绝 → 返回拒绝串(模型看到换路,不抛异常);
    · 批准 → await run()(run 是个返回 awaitable 的零参可调用)。"""
    gate = _current_gate()
    if gate is None:
        return "错误:该工具需要用户审批但当前没有审批上下文,默认拒绝。"
    decision = await gate.request(action, args, description=description, risk=risk, timeout=timeout)
    if not decision.approved:
        return (
            f"用户拒绝执行该操作({decision.reason or '未提供原因'})。"
            f"请尝试其他做法或向用户解释为什么需要它。"
        )
    return await run()


async def _call_original(fn: Callable, args: tuple, kwargs: dict[str, Any]) -> Any:
    """调用原工具(同步/异步都支持)。"""
    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res
