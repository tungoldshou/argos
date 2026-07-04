"""Application component factory.

Persistent state roots include ARGOS_CONFIG_DIR/snapshots, ARGOS_CONFIG_DIR/ledger,
ARGOS_CONFIG_DIR/argos.db, ARGOS_CONFIG_DIR/runs/index.json,
ARGOS_CONFIG_DIR/daemon.pid, and ARGOS_CONFIG_DIR/worktrees.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace as _dataclass_replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from argos import config
from argos.approval import ApprovalGate, ApprovalLevel
from argos.browser import BrowserController
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.models import CredentialPool, ModelClient
from argos.core.verify_gate import Verifier
from argos.memory.store import ArgosStore
from argos.mcp_native import McpManager
from argos.permissions.audit import AuditLog
from argos.permissions.config import PermissionsConfig, get_config as _permissions_get_config
from argos.capability import CapabilityRegistry, register_builtins
from argos.i18n import t
from argos.sandbox.broker import CapabilityBroker
from argos.sandbox.egress import EgressPolicy
from argos.sandbox.executor import SeatbeltExecutor, select_backend
from argos.tools.receipts import ReceiptSigner
from argos.ledger.store import LedgerStore
from argos.protocol.events import EventBus

# #11 per-task routing
from argos.routing.config import load_routing
from argos.routing.effort import EffortLevel, effort_settings
from argos.routing.router import ModelRouter

_HOST_SIGNING_KEY = os.urandom(32)

_SEARCH_HOSTS = {"api.tavily.com", "duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com"}


def _host_of(url: str) -> set[str]:
    h = urlparse(url).hostname
    return {h} if h else set()


@dataclass
class RunStack:
    sandbox: SeatbeltExecutor
    gate: ApprovalGate
    broker: CapabilityBroker
    loop_factory: "Callable[[], AgentLoop]"

    def close(self) -> None:
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
    router: ModelRouter | None = None
    mcp_manager: McpManager | None = None
    browser_controller: BrowserController | None = None
    permissions_config: PermissionsConfig | None = None
    audit_log: AuditLog | None = None
    registry: CapabilityRegistry | None = None
    capability_hints: dict[str, str] = field(default_factory=dict)
    ledger_store: LedgerStore | None = None

    def close(self) -> None:
        self.sandbox.close()
        self.store.close()
        if self.browser_controller is not None:
            try:
                self.browser_controller.close()
            except Exception:  # noqa: BLE001
                pass
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
    gate = ApprovalGate(approval_level, permissions_config=perm_config, audit_log=perm_audit)
    try:
        from argos.permissions.trust_dial import TrustLevel
        _al_to_trust = {
            ApprovalLevel.CONFIRM: TrustLevel.L1_DANGEROUS_ONLY,
            ApprovalLevel.ACCEPT_EDITS: TrustLevel.L3_SESSION_TRUSTED,
            ApprovalLevel.AUTO: TrustLevel.L4_AUTONOMOUS,
            ApprovalLevel.OBSERVE: TrustLevel.L0_EVERY_STEP,
            ApprovalLevel.PROPOSE: TrustLevel.L0_EVERY_STEP,
        }
        gate.set_trust_level(_al_to_trust.get(approval_level, TrustLevel.L1_DANGEROUS_ONLY))
    except Exception:  # noqa: BLE001
        pass
    broker = CapabilityBroker(
        gate=gate, egress=egress, signer=signer, workspace=workspace,
        mcp_manager=mcp_manager, browser_controller=browser_controller,
        registry=registry,
    )
    def broker_handler(action: str, args: dict) -> object:
        return broker.request_blocking(action, args)

    sandbox = select_backend()(broker_handler=broker_handler)
    return gate, broker, sandbox


def build_run_stack(
    c: "AppComponents",
    *,
    workspace: Path | None = None,
    session_id: str = "",
    verify_cmd: str | None = None,
) -> RunStack:
    ws = workspace if workspace is not None else c.workspace

    from argos.permissions.audit import AuditLog
    perm_config_run = _permissions_get_config()
    perm_audit_run = AuditLog(session_id=session_id)

    from argos import config as _cfg
    try:
        tier = _cfg.tier_for(c.config.model_tier)
        llm_hosts = _host_of(tier.base_url)
    except Exception:  # noqa: BLE001
        llm_hosts = set()
    egress = EgressPolicy(
        llm_hosts=llm_hosts,
        search_hosts=set(_SEARCH_HOSTS),
        mcp_hosts=set(),
    )
    if c.registry is not None:
        real_hosts = frozenset(h for h in c.registry.egress_hosts() if h != "*")
        if real_hosts:
            egress.add_hosts(real_hosts)
    signer = ReceiptSigner(key=_HOST_SIGNING_KEY)

    gate, broker, sandbox = _make_gate_broker_sandbox(
        approval_level=c.config.approval_level,
        perm_config=perm_config_run,
        perm_audit=perm_audit_run,
        egress=egress, signer=signer, workspace=ws,
        mcp_manager=c.mcp_manager,
        browser_controller=c.browser_controller,
        registry=c.registry,
    )
    if session_id:
        gate.set_session_id(session_id)
    if c.registry is not None:
        _reg = c.registry
        def _make_reversible_lookup(reg: "CapabilityRegistry") -> "Callable[[str], bool | None]":
            def _lookup(action: str) -> "bool | None":
                try:
                    return reg.get(action).reversible
                except KeyError:
                    return None
            return _lookup
        gate.set_reversible_lookup(_make_reversible_lookup(_reg))

    # ponytail: dataclass replace over full constructor — fewer fields to touch if LoopConfig grows
    _run_config = (
        _dataclass_replace(c.config, verify_cmd=verify_cmd) if verify_cmd is not None
        else c.config
    )

    def _loop_factory() -> "AgentLoop":
        _dom_prober = None
        if c.browser_controller is not None:
            try:
                from argos.verify.dom_probe import DomProber
                _dom_prober = DomProber(c.browser_controller)
            except Exception:  # noqa: BLE001
                pass
        _gui_prober = None
        import os as _os_gp
        if _os_gp.environ.get("ARGOS_COMPUTER_USE"):
            try:
                from argos.verify.gui_probe import GuiProber
                from argos.perception.executor import ComputerExecutor
                _gui_prober = GuiProber(ComputerExecutor())
            except Exception:  # noqa: BLE001
                pass
        return AgentLoop(
            store=c.store, bus=EventBus(), sandbox=sandbox,
            broker=broker, model=c.model, verifier=c.verifier, config=_run_config,
            workspace=ws, verify_dir=ws,
            workflow_engine_factory=c.workflow_engine_factory,
            router=c.router,
            mcp_manager=c.mcp_manager,
            dom_prober=_dom_prober,
            gui_prober=_gui_prober,
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
    default_ws = (
        os.environ.get("ARGOS_WORKSPACE")
        or str(config.config_dir() / "workspace")
    )
    ws = Path(workspace).expanduser().resolve() if workspace else Path(default_ws).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    store = ArgosStore(embedder=config.active_embedder())  # db_path=None → ARGOS_DB_PATH or ARGOS_CONFIG_DIR/argos.db

    if model_override:
        tier = config.tier_for(model_override)
        key = config.key_for(model_override)
    else:
        tier = config.active_tier()
        key = config.active_key()
    if not key:
        raise RuntimeError(t("core2.app_factory.no_api_key"))
    pool = CredentialPool([key])
    model = ModelClient(tier=tier, pool=pool)

    perm_config = _permissions_get_config()
    perm_audit = AuditLog(session_id="")

    egress = EgressPolicy(
        llm_hosts=_host_of(tier.base_url),
        search_hosts=set(_SEARCH_HOSTS),
        mcp_hosts=set(),
    )
    signer = ReceiptSigner(key=_HOST_SIGNING_KEY)

    registry = CapabilityRegistry()
    register_builtins(registry, egress=egress)

    mcp_mgr = McpManager()
    try:
        mcp_mgr.start_warming()
    except Exception:  # noqa: BLE001
        pass

    browser_ctrl = BrowserController()

    gate, broker, sandbox = _make_gate_broker_sandbox(
        approval_level=approval_level,
        perm_config=perm_config, perm_audit=perm_audit,
        egress=egress, signer=signer, workspace=ws,
        mcp_manager=mcp_mgr, browser_controller=browser_ctrl,
        registry=registry,
    )
    def _reversible_lookup_from_registry(action: str) -> "bool | None":
        try:
            return registry.get(action).reversible
        except KeyError:
            return None
    gate.set_reversible_lookup(_reversible_lookup_from_registry)

    # Wire reviewer-role test proposer when ARGOS_SELF_TEST is enabled.
    # The reviewer is an INDEPENDENT LLM call under a distinct system prompt — the coder
    # (maker) and the reviewer are separate calls; the coder never grades its own homework.
    # The exit-code gate + 3-state verdict are completely unchanged; this only adds a
    # proposer for the unverifiable (no verify_cmd) case behind the ARGOS_SELF_TEST flag.
    _test_generator = None
    if os.environ.get("ARGOS_SELF_TEST", "").strip().lower() in ("1", "true", "yes"):
        try:
            from argos.verify.self_test import TestGenerator, reviewer_llm_proposer
            # ponytail: reuse the model client that build_components already constructed (model)
            _test_generator = TestGenerator(proposer=reviewer_llm_proposer(model))
        except Exception:  # noqa: BLE001 — wiring failure must not break production Verifier
            pass
    verifier = Verifier(max_rounds=max_rounds, test_generator=_test_generator)

    from argos.workflow.engine import WorkflowEngine
    from argos.workflow.subagent import SubAgentFactory

    def _sub_model_factory(profile: str | None) -> ModelClient:
        try:
            t = config.tier_for(profile) if profile else tier
            k = config.key_for(profile) if profile else key
        except Exception:  # noqa: BLE001
            t, k = tier, key
        return ModelClient(tier=t, pool=CredentialPool([k]))

    def _workflow_engine_factory() -> WorkflowEngine:
        sub_factory = SubAgentFactory(
            base_workspace=ws, pool=pool, egress=egress, signer=signer, verifier=verifier,
            store_factory=lambda: ArgosStore(db_path=":memory:"), model_factory=_sub_model_factory,
        )
        return WorkflowEngine(sub_factory)

    preset = effort_settings(effort)
    loop_config = LoopConfig(
        model_tier=tier.name,
        verify_cmd=verify_cmd,
        max_rounds=max_rounds,
        max_steps=preset.max_steps,
        compaction=True,
        approval_level=preset.approval_level,
    )

    config_dir = config.config_dir()
    routing_cfg = load_routing(config_dir)

    def _router_client_factory(name: str) -> ModelClient:
        try:
            target_tier = config.tier_for(name)
        except Exception:  # noqa: BLE001
            target_tier, target_key = tier, key
        else:
            target_key = config.key_for(name)
            if not target_key:
                cfg = config.load_config()
                raise config.ConfigError(
                    t("route.profile_missing_key", tier=name, env=cfg.key_envs.get(name) or "")
                )
        return ModelClient(tier=target_tier, pool=CredentialPool([target_key]))

    router = (ModelRouter(routing=routing_cfg, client_factory=_router_client_factory)
              if routing_cfg.is_active() else None)

    _capability_hints: dict[str, str] = {
        cap.name: cap.verify_hint
        for cap in (registry._caps.values() if registry is not None else [])
        if cap.verify_hint
    }

    import logging as _logging
    from argos.external_surfaces import external_surface_warnings
    for _w in external_surface_warnings():
        _logging.getLogger("argos.sandbox").warning("[沙箱外执行面] %s", _w)

    ledger_store = LedgerStore()

    return AppComponents(
        store=store, broker=broker, verifier=verifier, model=model,
        sandbox=sandbox, gate=gate, config=loop_config, workspace=ws,
        workflow_engine_factory=_workflow_engine_factory,
        router=router,
        mcp_manager=mcp_mgr,
        browser_controller=browser_ctrl,
        permissions_config=perm_config,
        audit_log=perm_audit,
        registry=registry,
        capability_hints=_capability_hints,
        ledger_store=ledger_store,
    )


def build_loop_factory(c: AppComponents) -> "Callable[[str | None], AgentLoop]":
    def factory(verify_cmd: str | None = None) -> AgentLoop:
        # ponytail: same replace-over-shared-config pattern as build_run_stack ~L265
        run_config = (
            _dataclass_replace(c.config, verify_cmd=verify_cmd) if verify_cmd is not None
            else c.config
        )
        return AgentLoop(
            store=c.store, bus=EventBus(), sandbox=c.sandbox,
            broker=c.broker, model=c.model, verifier=c.verifier, config=run_config,
            workspace=c.workspace, verify_dir=c.workspace,
            workflow_engine_factory=c.workflow_engine_factory,
            router=c.router,
            mcp_manager=c.mcp_manager,
            capability_hints=c.capability_hints,
            manage_runtime_context=True, project_mode=True,
            ledger_store=c.ledger_store,
        )
    return factory
