"""装配层:把 Phase 2-5 各块组装成 ArgosApp 注入的 loop_factory(契约 §3/§5/§6/§7)。

build_components():一次性建 store/sandbox/broker/model/verifier(持久,跨多轮 run 复用)。
build_loop_factory(c):产 Callable[[], AgentLoop] —— 每轮 run 新建 EventBus(一条事件流),
                      共享其余组件;真 AgentLoop 替换 Phase 5 的 FakeLoop。
build_run_stack(c):per-run 隔离栈 —— 每次 daemon 分配一个 run 时调用,产全新
                   SeatbeltExecutor + ApprovalGate + CapabilityBroker,避免并发 run 共享单例
                   (run2 spawn 顶掉 run1 子进程 / gate.set_workspace 竞态)。
                   RunStack.close() 在 run 终态时清理沙箱子进程,不留孤儿。
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
from typing import Any
from urllib.parse import urlparse

from argos_agent import config
from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.browser import BrowserController
from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.models import CredentialPool, ModelClient
from argos_agent.core.verify_gate import Verifier
from argos_agent.memory.store import ArgosStore
from argos_agent.mcp_native import McpManager
from argos_agent.permissions.audit import AuditLog
from argos_agent.permissions.config import PermissionsConfig, get_config as _permissions_get_config
from argos_agent.capability import CapabilityRegistry, register_builtins
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


@dataclass
class RunStack:
    """per-run 隔离组件栈:每个 daemon run 独享一套 sandbox/gate/broker。

    共享(从 AppComponents 拿):store, model, verifier, router, config,
    workflow_engine_factory, mcp_manager, browser_controller,
    permissions_config, audit_log(append-only,条目按 session_id 区分)。
    独占(本 run 私有):sandbox, gate, broker, loop_factory。
    close():关闭沙箱子进程,run 终态 finally 必须调(不留孤儿)。
    """
    sandbox: SeatbeltExecutor
    gate: ApprovalGate
    broker: CapabilityBroker
    loop_factory: "Callable[[], AgentLoop]"

    def close(self) -> None:
        """关闭沙箱子进程;gate/broker 无资源需释放。"""
        try:
            self.sandbox.close()
        except Exception:  # noqa: BLE001
            pass


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
    # per-session MCP 管理器与浏览器控制器(生命周期随 AppComponents;close() 负责清理)。
    # None = 未使用(测试 / headless 路径跳过实例化)。
    mcp_manager: McpManager | None = None
    browser_controller: BrowserController | None = None
    # per-session permissions 实例(为多 run 并发铺路;broker/gate/evaluator 走注入路径)。
    permissions_config: PermissionsConfig | None = None
    audit_log: AuditLog | None = None
    # P2 能力注册表:进程级单注册表,broker/run_stack 共享;None = 兼容旧路径。
    registry: CapabilityRegistry | None = None

    def close(self) -> None:
        self.sandbox.close()
        self.store.close()
        # 收掉浏览器控制器(若本会话用过计算机控制),不残留 chromium 子进程。
        if self.browser_controller is not None:
            try:
                self.browser_controller.close()
            except Exception:  # noqa: BLE001
                pass
        # 收掉 MCP 管理器(关掉所有 stdio server 子进程)。
        if self.mcp_manager is not None:
            try:
                self.mcp_manager.close()
            except Exception:  # noqa: BLE001
                pass


def _make_gate_broker_sandbox(
    *,
    approval_level: ApprovalLevel,
    perm_config: "Any",
    perm_audit: "Any",
    egress: "EgressPolicy",
    signer: "ReceiptSigner",
    workspace: Path,
    mcp_manager: "Any | None" = None,
    browser_controller: "Any | None" = None,
    registry: "CapabilityRegistry | None" = None,
) -> "tuple[ApprovalGate, CapabilityBroker, SeatbeltExecutor]":
    """私有 helper:构造一组独立的 gate + broker + sandbox。

    build_components 和 build_run_stack 共用,避免两处复制逻辑漂移。
    每次调用返回全新实例 —— caller 负责生命周期(close sandbox)。

    registry:进程级单注册表(build_components 构造,build_run_stack 共享)。
    None = 兼容旧路径,行为完全不变。
    """
    gate = ApprovalGate(approval_level, permissions_config=perm_config, audit_log=perm_audit)
    # broker 一次构造,包含全部依赖(mcp/browser/registry 随即传入)。
    # workspace 传给 broker:host 侧 run_command 与沙箱子进程 write_file 用同一个 ws,
    # 杜绝 --project 模式下两者分叉(run_command 落默认 workspace、write_file 落项目目录)。
    broker = CapabilityBroker(
        gate=gate, egress=egress, signer=signer, workspace=workspace,
        mcp_manager=mcp_manager, browser_controller=browser_controller,
        registry=registry,
    )
    # 同步 broker_handler 桥走 broker._execute(裸执行):exec_code 阻塞等 broker_reply,
    # 无法 await gate,故绕过 request() 的 egress 校验/交互审批/Receipt。真正的硬边界是
    # Seatbelt(网络系统级 OFF、写限 workspace),egress 白名单这道第二防线在同步桥路径上
    # 不生效(既有限制,非本功能引入)。非 AUTO 档的交互式审批同样受此限,留 v1.1。
    def broker_handler(action: str, args: dict) -> object:
        value, _exit = broker._execute(action, args)
        return value

    # 沙箱由 loop.run() 自己 spawn/close(每轮一个子进程),此处只构造,不预 spawn。
    sandbox = SeatbeltExecutor(broker_handler=broker_handler)
    return gate, broker, sandbox


def build_run_stack(
    c: "AppComponents",
    *,
    workspace: Path | None = None,
    session_id: str = "",
) -> RunStack:
    """per-run 隔离栈:每次 daemon 分配一个新 run 时调用。

    返回 RunStack,内含全新 SeatbeltExecutor + ApprovalGate + CapabilityBroker
    以及一个绑定该栈的 loop_factory。
    共享:store, model, verifier, router, config, workflow_engine_factory,
          mcp_manager, browser_controller, permissions_config, audit_log。
    调用者在 run 终态 finally 里必须调 RunStack.close() 释放沙箱子进程。
    """
    ws = workspace if workspace is not None else c.workspace

    # per-run 审计日志:复用 c 的 permissions_config;audit_log 是 append-only,
    # 条目按 session_id 区分 —— 共享同一文件,用 session_id 区分归属。
    from argos_agent.permissions.audit import AuditLog
    perm_audit_run = AuditLog(session_id=session_id)

    # per-run egress / signer:和 build_components 用相同签名 key(进程级常量),
    # egress 从 c.config.model_tier 恢复 llm_hosts。
    from argos_agent import config as _cfg
    try:
        tier = _cfg.tier_for(c.config.model_tier)
        llm_hosts = _host_of(tier.base_url)
    except Exception:  # noqa: BLE001 — 未知 tier 退空集
        llm_hosts = set()
    egress = EgressPolicy(
        llm_hosts=llm_hosts,
        search_hosts=set(_SEARCH_HOSTS),
        mcp_hosts=set(),
    )
    # P2 fix:per-run egress 从 registry 派生(消灭双真值表)。
    # registry.egress_hosts() 聚合所有声明出网主机;过滤 "*" 通配(动态 host 由 broker 逐次校验)。
    # 与 register_builtins 现行行为一致:通配类不进静态白名单。
    if c.registry is not None:
        real_hosts = frozenset(h for h in c.registry.egress_hosts() if h != "*")
        if real_hosts:
            egress.add_hosts(real_hosts)
    signer = ReceiptSigner(key=_HOST_SIGNING_KEY)

    gate, broker, sandbox = _make_gate_broker_sandbox(
        approval_level=c.config.approval_level,
        perm_config=c.permissions_config,
        perm_audit=perm_audit_run,
        egress=egress, signer=signer, workspace=ws,
        # per-run 栈不独占 mcp/browser/registry —— 这些是进程级共享资源;
        # broker 只需引用,不拥有生命周期(AppComponents.close 统一清理)。
        mcp_manager=c.mcp_manager,
        browser_controller=c.browser_controller,
        registry=c.registry,   # P2:共享进程级注册表(能力声明静态,run 间共享安全)
    )
    if session_id:
        gate.set_session_id(session_id)

    def _loop_factory() -> "AgentLoop":
        return AgentLoop(
            store=c.store, bus=EventBus(), sandbox=sandbox,
            broker=broker, model=c.model, verifier=c.verifier, config=c.config,
            workspace=ws, verify_dir=ws,
            workflow_engine_factory=c.workflow_engine_factory,
            router=c.router,
            mcp_manager=c.mcp_manager,
        )

    return RunStack(sandbox=sandbox, gate=gate, broker=broker, loop_factory=_loop_factory)


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
    # ARGOS_WORKSPACE 全局副作用已去除:executor.spawn() 按 run 注入 child_env(见 executor.py:48),
    # 沙箱子进程只从自己的 env 读 WORKSPACE,不依赖父进程 os.environ 全局写。
    # 注意:runtime.py 的 _DEFAULT_WS 仍在模块加载时从 env 读一次(进程启动前设好即可,无并发问题)。

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

    # per-session permissions 实例:独立于模块级单例,并发 run 不共享 config 状态。
    perm_config = _permissions_get_config()   # 加载(惰性,首次读文件);后续 reload 会更新模块级但不影响已建实例
    perm_audit = AuditLog(session_id="")      # session_id 由 gate.set_session_id 后补

    egress = EgressPolicy(
        llm_hosts=_host_of(tier.base_url),
        search_hosts=set(_SEARCH_HOSTS),
        mcp_hosts=set(),
    )
    signer = ReceiptSigner(key=_HOST_SIGNING_KEY)

    # P2 能力注册表:进程级单注册表,build_components 构造,build_run_stack 共享。
    # register_builtins 同时热更新 egress（注册网络类能力时补 egress_hosts 白名单）。
    registry = CapabilityRegistry()
    register_builtins(registry, egress=egress)

    # per-session MCP 管理器(生命周期随 AppComponents):
    # 构造实例 + 后台预热(不阻塞 TUI 启动 / 首轮响应)。默认零预配 → 秒回无 server。
    mcp_mgr = McpManager()
    try:
        mcp_mgr.start_warming()
    except Exception:  # noqa: BLE001 — 预热失败不应阻断启动
        pass

    # BrowserController 实例:懒启动,close() 由 AppComponents.close() 负责清理;
    # 此处只构造(不真正 launch chromium),broker._execute 首次 browser_* 调用时才 start()。
    browser_ctrl = BrowserController()

    # per-session permissions 实例(已在上面构造好):gate/broker 共用
    gate, broker, sandbox = _make_gate_broker_sandbox(
        approval_level=approval_level,
        perm_config=perm_config, perm_audit=perm_audit,
        egress=egress, signer=signer, workspace=ws,
        mcp_manager=mcp_mgr, browser_controller=browser_ctrl,
        registry=registry,   # P2:传给 broker
    )

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
        mcp_manager=mcp_mgr,
        browser_controller=browser_ctrl,
        permissions_config=perm_config,
        audit_log=perm_audit,
        registry=registry,   # P2 能力注册表(进程级单注册表)
    )


def build_loop_factory(c: AppComponents) -> Callable[[], AgentLoop]:
    """产 loop_factory:每轮 run 新建 EventBus,共享其余组件(契约 §3 AgentLoop.__init__)。"""
    def factory() -> AgentLoop:
        return AgentLoop(
            store=c.store, bus=EventBus(), sandbox=c.sandbox,
            broker=c.broker, model=c.model, verifier=c.verifier, config=c.config,
            workspace=c.workspace, verify_dir=c.workspace,
            workflow_engine_factory=c.workflow_engine_factory,
            router=c.router,          # #11 per-task routing 透传(spec §10)
            mcp_manager=c.mcp_manager,  # per-session McpManager 注入(P1 去全局)
        )
    return factory
