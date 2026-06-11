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
from argos_agent.protocol.events import EventBus

# #11 per-task routing
from argos_agent.routing.config import load_routing
from argos_agent.routing.effort import EffortLevel, effort_settings
from argos_agent.routing.router import ModelRouter

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
    workflow_engine_factory: Callable[[], object]
    # #11 per-task routing:多个 ModelClient + RoutingConfig 注入 AgentLoop;None = 走原路径。
    router: ModelRouter | None = None

    def close(self) -> None:
        self.sandbox.close()
        self.store.close()
        # 收掉浏览器单例(若本会话用过计算机控制),不残留 chromium 子进程。
        try:
            from argos_agent import browser
            browser.shutdown()
        except Exception:  # noqa: BLE001 — 清理失败不应阻断关闭
            pass
        # 收掉 MCP 单例(关掉所有 stdio server 子进程)。
        try:
            from argos_agent import mcp_native
            mcp_native.shutdown()
        except Exception:  # noqa: BLE001
            pass


def build_components(
    *,
    workspace: str | None = None,
    model_override: str | None = None,
    verify_cmd: str | None = None,
    approval_level: ApprovalLevel = ApprovalLevel.CONFIRM,
    max_rounds: int = 3,
    effort: EffortLevel = EffortLevel.MEDIUM,
) -> AppComponents:
    """组装全栈(模型不绑定、无档位:用 config 的 active profile;model_override 指定别的 profile)。
    无 key → 诚实抛 RuntimeError(不假装能跑)。"""
    ws = Path(workspace).expanduser().resolve() if workspace else Path(
        os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace")
    ).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    # 沙箱子进程 files.py 模块级 WORKSPACE 读这个 env —— 必须在 spawn 前设好,文件才落对地方。
    os.environ["ARGOS_WORKSPACE"] = str(ws)

    # 记忆向量召回:复用 active profile 的 provider embeddings(配了 embedding_model 才有);
    # 未配 / 非 openai / 无 key → active_embedder 返 None → 记忆诚实走 FTS5 关键词,不调模型。
    store = ArgosStore(embedder=config.active_embedder())  # db_path=None → ARGOS_DB_PATH or ~/.argos/argos.db

    # 选模型:默认当前 active;`argos --model <name>` 指定某个具名 profile。无 key → 诚实抛 RuntimeError。
    if model_override:
        tier = config.tier_for(model_override)
        key = config.key_for(model_override)
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
    # workspace 传给 broker:host 侧 run_command 与沙箱子进程 write_file 用同一个 ws,
    # 杜绝 --project 模式下两者分叉(run_command 落默认 workspace、write_file 落项目目录)。
    broker = CapabilityBroker(gate=gate, egress=egress, signer=signer, workspace=ws)

    # 同步 broker_handler 桥走 broker._execute(裸执行):exec_code 阻塞等 broker_reply,
    # 无法 await gate,故绕过 request() 的 egress 校验/交互审批/Receipt。真正的硬边界是
    # Seatbelt(网络系统级 OFF、写限 workspace),egress 白名单这道第二防线在同步桥路径上
    # 不生效(既有限制,非本功能引入)。非 AUTO 档的交互式审批同样受此限,留 v1.1。
    def broker_handler(action: str, args: dict) -> object:
        value, _exit = broker._execute(action, args)
        return value

    # 沙箱由 loop.run() 自己 spawn/close(每轮一个子进程),此处只构造,不预 spawn。
    sandbox = SeatbeltExecutor(broker_handler=broker_handler)

    # MCP 后台预热:配了 ~/.argos/mcp.json 时,在后台线程连 stdio server(不阻塞 TUI 启动 /
    # 首轮响应)。默认零预配 → 秒回无 server。_build_system 用非阻塞的 tools_summary 读已就绪工具。
    try:
        from argos_agent import mcp_native
        mcp_native.get_manager().start_warming()
    except Exception:  # noqa: BLE001 — 预热失败不应阻断启动
        pass

    verifier = Verifier(max_rounds=max_rounds)

    # 工作流引擎工厂:子 agent 按 task.model profile 各自造 ModelClient(模型无关 per-agent);
    # 未知 profile / 无指定 → 退当前 active(诚实不崩)。子 agent 事件临时,用 in-memory store。
    from argos_agent.workflow.engine import WorkflowEngine  # 延迟 import 避免循环依赖
    from argos_agent.workflow.subagent import SubAgentFactory

    def _sub_model_factory(profile: str | None) -> ModelClient:
        try:
            t = config.tier_for(profile) if profile else tier
            k = config.key_for(profile) if profile else key
        except Exception:  # noqa: BLE001 — 未知 profile 退当前 active(诚实降级)
            t, k = tier, key
        return ModelClient(tier=t, pool=CredentialPool([k]))

    def _workflow_engine_factory() -> WorkflowEngine:
        sub_factory = SubAgentFactory(
            base_workspace=ws, pool=pool, egress=egress, signer=signer, verifier=verifier,
            store_factory=lambda: ArgosStore(db_path=":memory:"), model_factory=_sub_model_factory,
        )
        return WorkflowEngine(sub_factory)

    # #11 per-task routing(契约 §11;spec §10):effort 拆 preset 填既有 max_steps +
    # approval_level(spec D6 不引入新 LoopConfig 字段)。
    preset = effort_settings(effort)
    loop_config = LoopConfig(
        model_tier=tier.name,
        verify_cmd=verify_cmd,
        max_rounds=max_rounds,
        max_steps=preset.max_steps,
        compaction=True,
        approval_level=preset.approval_level,
    )

    # #11 per-task routing(契约 §11;spec §7):构造 ModelRouter。routing config 从
    # ~/.argos/config.json 读;client_factory 懒构造每个 tier 的 ModelClient(无 key
    # 的 tier 在 router.select 时才报,不阻断启动)。
    config_dir = Path(os.environ.get("ARGOS_CONFIG_DIR") or Path.home() / ".argos")
    routing_cfg = load_routing(config_dir)

    def _router_client_factory(name: str) -> ModelClient:
        try:
            t = config.tier_for(name)
            k = config.key_for(name) or ""   # key 缺时 tier_for 抛/此处留空让上层错
        except Exception:  # noqa: BLE001 — 未知 profile 退当前 active
            t, k = tier, key
        return ModelClient(tier=t, pool=CredentialPool([k] or ["_missing_"]))

    router = ModelRouter(routing=routing_cfg, client_factory=_router_client_factory)

    return AppComponents(
        store=store, broker=broker, verifier=verifier, model=model,
        sandbox=sandbox, gate=gate, config=loop_config, workspace=ws,
        workflow_engine_factory=_workflow_engine_factory,
        router=router,
    )


def build_loop_factory(c: AppComponents) -> Callable[[], AgentLoop]:
    """产 loop_factory:每轮 run 新建 EventBus,共享其余组件(契约 §3 AgentLoop.__init__)。"""
    def factory() -> AgentLoop:
        return AgentLoop(
            store=c.store, bus=EventBus(), sandbox=c.sandbox,
            broker=c.broker, model=c.model, verifier=c.verifier, config=c.config,
            workspace=c.workspace, verify_dir=c.workspace,
            workflow_engine_factory=c.workflow_engine_factory,
            router=c.router,    # #11 per-task routing 透传(spec §10)
        )
    return factory
