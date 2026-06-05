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
from argos_agent.sandbox.executor import SeatbeltExecutor
from argos_agent.tui.events import Error, EventBus, PhaseChange, TokenDelta, VerifyVerdict
from argos_agent.workflow.result import AgentResult
from argos_agent.workflow.spec import AgentTask
from argos_agent.workflow.worktree import worktree_for

# on_phase 回调签名:(agent_id, phase, detail) -> None(引擎据此把子 agent 阶段汇进活动栏)。
OnPhase = Callable[[str, str, str], None]


@dataclass(frozen=True, slots=True)
class SubAgentFactory:
    """把单个 AgentTask 跑成一个隔离子 AgentLoop 并收成 AgentResult。

    字段全为预构造的共享依赖(egress/signer/verifier/pool 全工作流复用),只有
    store / broker / sandbox / worktree 每个子 agent 独立 —— 隔离边界落在执行侧,
    不在策略侧。model_factory(profile) 把 task.model(profile 名)解析成一个有
    .tier/.stream 的 model;store_factory() 每次产一个独立 store(子 agent 间不串记忆)。
    """

    base_workspace: Path
    pool: Any
    egress: Any
    signer: Any
    verifier: Any
    store_factory: Callable[[], Any]
    model_factory: Callable[[str | None], Any]

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
                # 同步桥(与 app_factory.py 一致):exec_code 同步阻塞,无法 await gate,故走
                # _execute —— 网络动作的 egress 白名单校验在 _execute 内仍生效(仍受出网约束),
                # 只是交互式审批受同步性限制;子 agent 本就 AUTO 档,不需交互审批,无影响。
                value, _exit = broker._execute(action, args)
                return value

            sandbox = SeatbeltExecutor(broker_handler=_bridge)
            cfg = LoopConfig(
                model_tier=model.tier.name,
                verify_cmd=task.verify,
                max_rounds=2,
                max_steps=20,
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
            return AgentResult(
                agent_id=agent_id, ok=True, output=output, verdict=verdict_status,
                tokens_in=tokens_in, tokens_out=tokens_out,
            )

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
