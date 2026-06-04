"""装配层:把 Phase 2-5 各块组装成 ArgosApp 注入的 loop_factory(契约 §3/§5/§6/§7)。

build_components():一次性建 store/sandbox/broker/model/verifier(持久,跨多轮 run 复用)。
build_loop_factory(c):产 Callable[[], AgentLoop] —— 每轮 run 新建 EventBus(一条事件流),
                      共享其余组件;真 AgentLoop 替换 Phase 5 的 FakeLoop。
诚实(灵魂):无 worker key → 抛 RuntimeError(入口捕获落 demo 态,不假装能跑)。

接线要点(对齐 canonical,非计划正文的过时名):
  · 沙箱 = SeatbeltExecutor(executor.py),不存在 SeatbeltBackend。
  · EgressPolicy(*, llm_hosts, search_hosts, mcp_hosts) —— 无 from_config(),host 从 config 的
    tier base_url 推。
  · broker_handler 是同步桥(exec_code 阻塞等 broker_reply,handler 必须同步)→ broker._execute。
  · 沙箱由 loop.run() 自己 spawn/close(loop.py),装配层只构造 executor,不预 spawn。
  · 子进程 files.py 模块级 WORKSPACE 读 ARGOS_WORKSPACE env —— spawn 前必须设好。
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from argos_agent import config
from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.models import CredentialPool, ModelClient
from argos_agent.core.verify_gate import Verifier
from argos_agent.memory.store import ArgosStore
from argos_agent.sandbox.broker import CapabilityBroker
from argos_agent.sandbox.egress import EgressPolicy
from argos_agent.sandbox.executor import SeatbeltExecutor
from argos_agent.tools.receipts import ReceiptSigner
from argos_agent.tui.events import EventBus

# Receipt 签名 key:host 进程内随机一份(沙箱碰不到,spec §12.3)。回执只在单进程生命周期内核验。
_HOST_SIGNING_KEY = os.urandom(32)

# 默认搜索出口主机(web_search/web_extract 的 provider;非白名单一律拒,spec §6.4)。
_SEARCH_HOSTS = {"api.tavily.com", "duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com"}


def _host_of(url: str) -> set[str]:
    h = urlparse(url).hostname
    return {h} if h else set()


@dataclass(frozen=True, slots=True)
class AppComponents:
    store: ArgosStore
    broker: CapabilityBroker
    verifier: Verifier
    model: ModelClient
    sandbox: SeatbeltExecutor
    gate: ApprovalGate
    config: LoopConfig
    workspace: Path

    def close(self) -> None:
        self.sandbox.close()
        self.store.close()


def build_components(
    *,
    workspace: str | None = None,
    premium: bool = False,
    verify_cmd: str | None = None,
    approval_level: ApprovalLevel = ApprovalLevel.CONFIRM,
    max_rounds: int = 3,
) -> AppComponents:
    """组装全栈。无 worker key → 诚实抛 RuntimeError(不假装能跑)。"""
    ws = Path(workspace).expanduser().resolve() if workspace else Path(
        os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace")
    ).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    # 沙箱子进程 files.py 模块级 WORKSPACE 读这个 env —— 必须在 spawn 前设好,文件才落对地方。
    os.environ["ARGOS_WORKSPACE"] = str(ws)

    store = ArgosStore()  # db_path=None → ARGOS_DB_PATH or ~/.argos/argos.db

    # 无 key → 诚实抛 RuntimeError(入口引导 argos setup)。
    if premium:
        tier = config.PREMIUM_TIER
        key = config.PREMIUM_KEY
    else:
        tier = config.active_tier()
        key = config.active_key()
    if not key:
        raise RuntimeError(
            "未配置当前模型的 API key。请运行 `argos setup` 接入模型,或设置对应环境变量。"
            "Argos 不会假装能跑。"
        )
    pool = CredentialPool([key])
    model = ModelClient(tier=tier, pool=pool)

    gate = ApprovalGate(approval_level)
    egress = EgressPolicy(
        llm_hosts=_host_of(tier.base_url),
        search_hosts=set(_SEARCH_HOSTS),
        mcp_hosts=set(),
    )
    signer = ReceiptSigner(key=_HOST_SIGNING_KEY)
    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer)

    # 同步 broker_handler 桥:exec_code 阻塞等 broker_reply,故 handler 必须同步;走 _execute
    # (网络动作的 egress 校验在 _execute 内生效)。非 AUTO 档对 in-sandbox gated 工具的交互式
    # 审批受限于 exec_code 同步性(无法 await gate),留 v1.1;MVP 主路径(file/verify)不经此。
    def broker_handler(action: str, args: dict) -> object:
        value, _exit = broker._execute(action, args)
        return value

    # 沙箱由 loop.run() 自己 spawn/close(每轮一个子进程),此处只构造,不预 spawn。
    sandbox = SeatbeltExecutor(broker_handler=broker_handler)

    verifier = Verifier(max_rounds=max_rounds)

    loop_config = LoopConfig(
        model_tier=tier.name,
        verify_cmd=verify_cmd,
        max_rounds=max_rounds,
        max_steps=40,
        compaction=True,
        approval_level=approval_level,
    )
    return AppComponents(
        store=store, broker=broker, verifier=verifier, model=model,
        sandbox=sandbox, gate=gate, config=loop_config, workspace=ws,
    )


def build_loop_factory(c: AppComponents) -> Callable[[], AgentLoop]:
    """产 loop_factory:每轮 run 新建 EventBus,共享其余组件(契约 §3 AgentLoop.__init__)。"""
    def factory() -> AgentLoop:
        return AgentLoop(
            store=c.store, bus=EventBus(), sandbox=c.sandbox,
            broker=c.broker, model=c.model, verifier=c.verifier, config=c.config,
            workspace=c.workspace, verify_dir=c.workspace,
        )
    return factory
