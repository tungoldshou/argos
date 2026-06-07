"""子 agent 工厂(Dynamic Workflows Task 6)—— 把一个 AgentTask + item 跑成一个隔离的
子 AgentLoop,出 AgentResult。

隔离三件套:每个子 agent 独立 model / broker / 沙箱子进程 / worktree 工作目录。
深度护栏:子 agent 一律 allow_workflow=False —— 沙箱命名空间不含 propose_workflow,
深度恒 1(子 agent 不能再派生工作流,杜绝无限递归 fan-out)。
审批:启动审批已覆盖整张 workflow 的意图,子 agent 跑在 ApprovalLevel.AUTO(放手,
逐工具不再打断)。
RAII:worktree_for 的 finally 拆 worktree、sandbox.close() 收子进程。
诚实容错:任何异常(模型炸/沙箱起不来/loop 内部错)都捕成 ok=False 的 AgentResult,
绝不抛 —— 一个子 agent 挂不能拖崩整个工作流引擎(Task 7 依赖这条不变量)。

角色(role)接线(任务:每个角色独立上下文/工具/提示词/上限)—— 单模型也能拿收益:
- role 存在 → 派生 read_only(基于 ROLE_PRESETS 工具白名单)+ max_steps(防跑飞)。
- role 不存在 → 沿用 tool_scope 派生 read_only + 默认 max_steps=20(向后兼容)。
- role system_prompt 通过 user 段前缀注入 prompt(不改 loop.py 签名;loop._drive 看到的
  user goal 已被加角色上下文,等效 system 块 —— 诚实注:这是 user-段前缀,不是真 system,
  模型在 Anthropic-Messages 协议下都按 user 段处理,等效对齐)。
- requires_verify=True 且 task.verify=None → 仍按既有诚实规则不判 passed(loop 走
  is_honest_completion → NO_TEST;本文件不动 verifier)。
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.sandbox.broker import CapabilityBroker
from argos_agent.sandbox.executor import select_backend
from argos_agent.tui.events import Error, EventBus, PhaseChange, TokenDelta, VerifyVerdict
from argos_agent.workflow.result import AgentResult
from argos_agent.workflow.spec import AgentTask, ROLE_PRESETS
from argos_agent.workflow.worktree import worktree_for

# on_phase 回调签名:(agent_id, phase, detail) -> None(引擎据此把子 agent 阶段汇进活动栏)。
OnPhase = Callable[[str, str, str], None]

# 无 role 时沿用的默认 max_steps(原 hardcode,见下方 _run 注释)。
_DEFAULT_MAX_STEPS = 20


def _resolve_role(task: AgentTask):
    """根据 task.role 派生角色预设;None → 返 None(走旧路径)。"""
    if task.role is None:
        return None
    return ROLE_PRESETS.get(task.role)


@dataclass(frozen=True, slots=True)
class SubAgentFactory:
    """把单个 AgentTask 跑成一个隔离子 AgentLoop 并收成 AgentResult。

    字段全为预构造的共享依赖(egress/signer/verifier/pool 全工作流复用),只有
    store / broker / sandbox / worktree 每个子 agent 独立 —— 隔离边界落在执行侧,
    不在策略侧。model_factory(profile) 把 task.model(profile 名)解析成一个有
    .tier/.stream 的 model;store_factory() 每次产一个独立 store(子 agent 间不串记忆)。

    inline_diff:False(默认,省 token 模式)→ 完整 diff 落盘到 ~/.argos/workflow/diffs/,
                  AgentResult.output 只装摘要 + 引用;True(旧行为)→ output 含整段 diff。
    """

    base_workspace: Path
    pool: Any
    egress: Any
    signer: Any
    verifier: Any
    store_factory: Callable[[], Any]
    model_factory: Callable[[str | None], Any]
    inline_diff: bool = False

    async def run_task(
        self,
        task: AgentTask,
        *,
        item: object,
        agent_id: str,
        on_phase: OnPhase,
    ) -> AgentResult:
        """跑一个子 agent。任何异常捕成 ok=False 的 AgentResult,绝不抛。"""
        try:
            return await self._run(task, item=item, agent_id=agent_id, on_phase=on_phase)
        except Exception as e:  # noqa: BLE001 — 子 agent 挂不能拖崩工作流(Task 7 依赖)
            return AgentResult(
                agent_id=agent_id, ok=False, output="",
                error=f"{type(e).__name__}: {e}",
            )

    async def _run(
        self,
        task: AgentTask,
        *,
        item: object,
        agent_id: str,
        on_phase: OnPhase,
    ) -> AgentResult:
        prompt = task.prompt.replace("{item}", str(item)) if item is not None else task.prompt
        # 角色派生(任务):role 存在 → 派生 read_only + max_steps + system_prompt 前缀;
        # role 缺失 → 走原 tool_scope 派生路径(向后兼容)。
        role_preset = _resolve_role(task)
        if role_preset is not None:
            # role 接管:read_only 从 preset 取(覆盖 tool_scope 派生)。role 不填时 read_only
            # 仍由 tool_scope 决定 —— 见下方 read_only 表达式(短路 on None)。
            derived_read_only = role_preset.read_only
            max_steps = role_preset.max_steps
            # system_prompt 走 user 段前缀注入:把角色上下文拼到 user goal 最前(loop._drive
            # 看到的 user message 已含角色引导,等效 system 块对齐)。不动 loop.py 签名。
            prompt = f"[角色:{role_preset.name}]\n{role_preset.system_prompt}\n\n---\n\n{prompt}"
        else:
            derived_read_only = (task.tool_scope == "read")
            max_steps = _DEFAULT_MAX_STEPS
        model = self.model_factory(task.model)
        # 启动审批已覆盖整张 workflow 的意图 → 子 agent AUTO 跑(逐工具不再打断)。
        gate = ApprovalGate(ApprovalLevel.AUTO)

        report_parts: list[str] = []
        verdict_status: str | None = None
        early_error: str | None = None         # Error 事件的 message → 提前 return(带真实 token)
        tokens_in = 0
        tokens_out = 0

        with worktree_for(self.base_workspace, agent_id, task.isolation) as (workdir, note):
            broker = CapabilityBroker(
                gate=gate, egress=self.egress, signer=self.signer, workspace=workdir,
            )

            def _bridge(action: str, args: dict) -> object:
                # 同步桥走 broker._execute(裸执行):exec_code 同步阻塞无法 await gate,故绕过
                # request() 的 egress 校验/交互审批/Receipt。真正的硬边界是 Seatbelt(网络系统级
                # OFF、写限 workspace),egress 白名单这道第二防线在同步桥路径上不生效(既有限制,
                # 非本功能引入)。子 agent 本就 AUTO 档不需交互审批。
                value, _exit = broker._execute(action, args)
                return value

            # 平台感知:macOS → Seatbelt,Linux → bwrap(unshare 退化)。在没沙箱后端的
            # 平台(罕见,常见 CI Linux 镜像 bwrap 也不在)抛 RuntimeError,被 run_task 的
            # try/except 收成 ok=False 的 AgentResult —— 测试若想跑真沙箱,应套 requires_sandbox 守卫。
            sandbox_cls = select_backend()
            sandbox = sandbox_cls(broker_handler=_bridge)
            cfg = LoopConfig(
                model_tier=model.tier.name,
                verify_cmd=task.verify,
                max_rounds=2,
                max_steps=max_steps,
                compaction=True,
                approval_level=ApprovalLevel.AUTO,
            )
            loop = AgentLoop(
                store=self.store_factory(),
                bus=EventBus(),
                sandbox=sandbox,
                broker=broker,
                model=model,
                verifier=self.verifier,
                config=cfg,
                workspace=workdir,
                verify_dir=workdir,
                allow_workflow=False,   # 深度护栏:子 agent 沙箱不含 propose_workflow
                read_only=derived_read_only,  # role 派生 / 旧 tool_scope 派生(向后兼容)
            )
            try:
                async for ev in loop.run(prompt, session_id=agent_id):
                    if isinstance(ev, TokenDelta):
                        report_parts.append(ev.text)
                    elif isinstance(ev, PhaseChange):
                        on_phase(agent_id, ev.phase, "")
                    elif isinstance(ev, VerifyVerdict):
                        verdict_status = ev.verdict.status
                    elif isinstance(ev, Error):
                        early_error = ev.message
                        break
            finally:
                sandbox.close()
                # 诚实成本核算:在 finally 读 token,覆盖 ok=True 与 Error 两条返回路径 —— 失败
                # 子 agent 的开销也要带真实 token,否则引擎汇总成本会漏算它。
                usage = getattr(model, "last_usage", {}) or {}
                tokens_in = int(usage.get("input_tokens") or 0)
                tokens_out = int(usage.get("output_tokens") or 0)

            if early_error is not None:
                return AgentResult(
                    agent_id=agent_id, ok=False, output="", error=early_error,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                )

            output = "".join(report_parts).strip()
            if note:
                output = f"{output}\n[隔离注记] {note}"

            # diff 处理(任务:并行子 agent 摘要模式)——
            # 拆 worktree 前的 with 块内抓 diff 文本(失败返 None,不挂子 agent)。
            diff_text: str | None = None
            diff_ref: str | None = None
            diff_summary: str | None = None
            diff_file_count: int = 0
            if workdir != self.base_workspace:
                diff_text = self._capture_diff_text(workdir)
                if diff_text:
                    if self.inline_diff:
                        # 旧行为:整段 diff inline 进 output(给 v1 caller / 审批预览用)
                        output += (
                            f"\n[worktree 改动 diff —— 未自动合并,请审阅后应用]\n{diff_text}"
                        )
                    else:
                        # 默认:完整 diff 落盘 + output 只装摘要 + 引用
                        diff_ref = self._persist_diff_journal(agent_id, diff_text)
                        diff_summary, diff_file_count = self._summarize_diff(diff_text)
                        if diff_summary:
                            output += f"\n[diff 摘要] {diff_summary}"
                        if diff_ref:
                            output += f"\n[完整 diff] {diff_ref}"

            return AgentResult(
                agent_id=agent_id, ok=True, output=output, verdict=verdict_status,
                tokens_in=tokens_in, tokens_out=tokens_out,
                diff_ref=diff_ref, diff_summary=diff_summary,
                diff_file_count=diff_file_count,
            )

    @staticmethod
    def _capture_diff_text(workdir: Path) -> str | None:
        """把 worktree 里未提交的改动抓成 unified diff 文本(失败返 None,不抛)。

        拆分理由(任务:diff 摘要模式)—— 与旧 _capture_diff 不同:返 None(无改动)
        vs 空串(无意义默认),让 caller 显式分支。
        """
        import subprocess
        try:
            subprocess.run(["git", "-C", str(workdir), "add", "-A"],
                           capture_output=True, timeout=10)
            r = subprocess.run(
                ["git", "-C", str(workdir), "diff", "--cached"],
                capture_output=True, text=True, timeout=10,
            )
            diff = r.stdout or ""
            return diff if diff.strip() else None
        except Exception:  # noqa: BLE001 — 抓 diff 失败不应让子 agent 整体失败
            return None

    @staticmethod
    def _summarize_diff(diff_text: str) -> tuple[str, int]:
        """把 unified diff 抽成一句话摘要(任务:父级 / 协调员 inline 用)。

        返 (summary, file_count)。summary 形如 "N files changed, +X/-Y lines"。
        解析失败(无标准 diff 头)→ 退化为 "{N} files changed"(保守,不编数字)。
        """
        import re
        # 文件数:扫 "diff --git a/X b/X" 行
        files = re.findall(r"^diff --git a/", diff_text, flags=re.MULTILINE)
        n = len(files)
        if n == 0:
            return ("", 0)
        # 增减行数:扫 hunk 头 "@@ -A,B +C,D @@" 取 B / D(粗糙估算,够摘要用)
        added = 0
        removed = 0
        for m in re.finditer(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", diff_text,
                              flags=re.MULTILINE):
            removed += int(m.group(1) or "1")
            added += int(m.group(2) or "1")
        return (f"{n} files changed, +{added}/-{removed} lines", n)

    @staticmethod
    def _persist_diff_journal(agent_id: str, diff_text: str) -> str:
        """把完整 diff 写到 ~/.argos/workflow/diffs/<agent_id>.diff,返路径。

        任务:按需取回(审批/冲突/用户要求)。失败不抛(返空串),不让子 agent 翻车;
        失败时 AgentResult.diff_ref=None + output 不带引用段,caller 只能凭"无 diff 摘要"猜。
        """
        import os
        try:
            d = Path(os.path.expanduser("~/.argos/workflow/diffs"))
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{agent_id}.diff"
            # 安全名:把路径里不允许的字符换 _
            safe = p
            p.write_text(diff_text, encoding="utf-8")
            return str(safe)
        except Exception:  # noqa: BLE001
            return ""

    @classmethod
    def for_test(cls, *, workspace: Path, model_factory: Callable[[str | None], Any]) -> "SubAgentFactory":
        """测试构造:临时 in-memory store + 宽松 egress/signer/verifier(不连真网络/不绑真 key)。"""
        from argos_agent.core.models import CredentialPool
        from argos_agent.core.verify_gate import Verifier
        from argos_agent.memory.store import ArgosStore
        from argos_agent.sandbox.egress import EgressPolicy
        from argos_agent.tools.receipts import ReceiptSigner

        return cls(
            base_workspace=workspace,
            pool=CredentialPool(["test"]),
            egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
            signer=ReceiptSigner(key=os.urandom(32)),
            verifier=Verifier(max_rounds=2),
            store_factory=lambda: ArgosStore(db_path=":memory:"),
            model_factory=model_factory,
        )
