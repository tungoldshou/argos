from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from argos.approval import ApprovalGate
from argos.i18n import t
from argos.tools import files as _files
from argos.tools import shell as _shell
from argos.tools import web as _web
from argos.tools.receipts import Receipt, ReceiptSigner
from .egress import EgressPolicy

if TYPE_CHECKING:
    from argos.capability.registry import CapabilityRegistry

_NETWORK_ACTIONS: set[str] = {"web_search", "web_extract", "browser_navigate"}


def _resolve_lsp_server(
    *,
    file: "str | None",
    manager: "Any",
) -> "str | None":
    try:
        cfg = manager.config
    except AttributeError:
        return None

    if file is not None:
        ext = Path(file).suffix  # e.g. ".py", ".rs", ""
        if ext:
            matches = cfg.get_servers_for_filetype(ext)
            if matches:
                return matches[0][0]
        return None
    else:
        for name, sc in cfg.servers.items():
            if not sc.disabled:
                return name
        return None
_RISK: dict[str, str] = {
    "run_command": "high",
    "web_search": "low",
    "web_extract": "low",
    "browser_navigate": "low",
    "browser_snapshot": "low",
    "browser_screenshot": "low",
    "browser_click": "medium",
    "browser_type": "medium",
    "mcp_call": "medium",
    "computer_screenshot": "high",
    "computer_click": "high",
    "computer_double_click": "high",
    "computer_type_text": "high",
    "computer_key": "high",
    "computer_scroll": "high",
    "computer_open_app": "high",
    "write_file": "medium",
    "edit_file": "medium",
}
_FILE_WRITE_ACTIONS: set[str] = {"write_file", "edit_file"}


@dataclass(frozen=True, slots=True)
class BrokerResult:
    value: Any
    receipt: Receipt


class CapabilityBroker:
    def __init__(self, *, gate: ApprovalGate, egress: EgressPolicy,
                 signer: ReceiptSigner, workspace: Path | None = None,
                 mcp_manager: Any = None, browser_controller: Any = None,
                 registry: "CapabilityRegistry | None" = None) -> None:
        self._gate = gate
        self._egress = egress
        self._signer = signer
        self._workspace = workspace
        self.last_receipt: Receipt | None = None
        self._mcp_manager = mcp_manager
        self._browser_controller = browser_controller
        self._registry = registry
        self._host_loop: Any = None
        self._bridge_timeout: float = 300.0
        self.last_computer_artifact: tuple[str, tuple | None] | None = None

    def _egress_deny_reason(self, action: str, args: dict[str, Any]) -> str | None:
        host = _web.host_for(action, args)
        if action in {"web_extract", "browser_navigate"}:
            url = args.get("url", "")
            if _web.extract_url_blocked(url):
                return t("sandbox.egress.ssrf_deny", host=host or url)
            return None
        if not self._egress.allowed(host):
            return t("sandbox.egress.host_not_allowed", host=host)
        return None

    def _preflight(self, action: str, args: dict[str, Any]
                   ) -> "tuple[tuple[Any, int | None] | None, dict[str, str]]":
        _reg = getattr(self, "_registry", None)
        registry_risk = _reg.risk_table() if _reg is not None else {}
        if action not in registry_risk and action not in _RISK:
            return (t("sandbox.broker.unknown_action", action=action), 1), registry_risk
        if getattr(self._gate, "is_full_access", lambda: False)():
            return None, registry_risk
        if action == "run_command":
            from argos.permissions.hard_rules import check_hard_shell
            _rule = check_hard_shell(str(args.get("command", "")))
            if _rule is not None:
                return (t("sandbox.broker.hard_shell_denied", rule=_rule), 1), registry_risk
        if action in _FILE_WRITE_ACTIONS:
            meta = self._gate.evaluate_sync(action, args)
            if meta is not None:
                if meta.decision == "approve":
                    self.last_receipt = self._signer.sign(
                        action=action, args=args,
                        result=_files.WRITE_APPROVED_SENTINEL, exit_code=0,
                    )
                    return (_files.WRITE_APPROVED_SENTINEL, 0), registry_risk
                if meta.decision == "deny":
                    return (meta.reason or t("sandbox.broker.write_hard_denied", action=action), 1), registry_risk
                if meta.secret_pattern or (meta.trigger or "").startswith("secret:"):
                    return (t("sandbox.broker.write_secret_detected",
                              pattern=meta.secret_pattern or "?"), 1), registry_risk
            return None, registry_risk
        if action == "browser_screenshot":
            ws = (self._workspace or (Path.cwd() / "workspace")).resolve()
            target = (ws / str(args.get("path") or "screenshot.png")).resolve()
            try:
                target.relative_to(ws)
            except ValueError:
                return (t("tools.files.write.outside_workspace", path=args.get("path", "")), 1), registry_risk
            args["path"] = str(target)
        if action in self._derive_network_actions():
            deny = self._egress_deny_reason(action, args)
            if deny is not None and not (
                getattr(self._gate, "is_full_access", lambda: False)()
                and action not in {"web_extract", "browser_navigate"}
            ):
                return (deny, 1), registry_risk
        return None, registry_risk

    async def request(self, action: str, args: dict[str, Any]) -> Any:
        terminal, _registry_risk = self._preflight(action, args)
        if terminal is not None:
            return terminal[0]
        if getattr(self._gate, "is_full_access", lambda: False)():
            value, exit_code = self._execute(
                action,
                args,
                run_ctx=None,
                _gated=True,
                allow_network=True,
            )
            self.last_receipt = self._signer.sign(
                action=action, args=args, result=value, exit_code=exit_code,
            )
            return value
        decision = await self._request_decision(action, args, registry_risk=_registry_risk)
        if not decision.approved:
            return t("sandbox.broker.user_denied",
                     reason=decision.reason or t("sandbox.broker.user_denied_no_reason"))
        _allow_net = (action == "run_command"
                      and _shell.command_needs_network(args.get("command", "")))
        value, exit_code = self._execute(action, args, run_ctx=None, _gated=True,
                                         allow_network=_allow_net)
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=value, exit_code=exit_code,
        )
        return value

    def execute_sync(self, action: str, args: dict[str, Any]) -> tuple[Any, int | None]:
        terminal, _registry_risk = self._preflight(action, args)
        if terminal is not None:
            return terminal
        if action.startswith("computer_"):
            if getattr(self._gate, "is_full_access", lambda: False)():
                value, exit_code = self._execute(action, args, run_ctx=None, _gated=True)
                self.last_receipt = self._signer.sign(
                    action=action, args=args, result=value, exit_code=exit_code,
                )
                return value, exit_code
            from argos.permissions.hard_rules import check_computer_hard_rules
            _rule = check_computer_hard_rules(action, args)
            if _rule:
                return (t("sandbox.broker.computer_hard_rule_denied", rule=_rule), 1)
        if action == "run_command":
            from argos import config as _argos_config
            cmd = str(args.get("command", ""))
            if not getattr(self._gate, "is_full_access", lambda: False)() and not _argos_config.sandbox_enabled() and not _shell.command_is_low_risk(cmd):
                return (t("sandbox.broker.sync_run_command_requires_sandbox"), 1)
        if not getattr(self._gate, "is_full_access", lambda: False)() and (
            action == "mcp_call" or action.startswith("browser_") or action.startswith("computer_")
        ):
            return (t("sandbox.broker.sync_interactive_requires_approval", action=action), 1)
        value, exit_code = self._execute(action, args, run_ctx=None)
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=value, exit_code=exit_code,
        )
        return value, exit_code

    def set_host_loop(self, loop: Any) -> None:
        self._host_loop = loop

    def request_blocking(self, action: str, args: dict[str, Any]) -> Any:
        loop = self._host_loop
        if loop is None:
            value, _exit = self.execute_sync(action, args)
            return value
        try:
            fut = asyncio.run_coroutine_threadsafe(self.request(action, args), loop)
            return fut.result(timeout=self._bridge_timeout)
        except Exception as exc:  # noqa: BLE001
            return t("sandbox.broker.bridge_exception", exc_type=type(exc).__name__)

    def _derive_network_actions(self) -> set[str]:
        _reg = getattr(self, "_registry", None)
        if _reg is None:
            return set(_NETWORK_ACTIONS)
        try:
            registry_egress: set[str] = set()
            for name in _reg.names():
                cap = _reg.get(name)
                if cap.egress_hosts:
                    registry_egress.add(name)
            return registry_egress | _NETWORK_ACTIONS
        except Exception:  # noqa: BLE001
            return set(_NETWORK_ACTIONS)

    async def _request_decision(self, action: str, args: dict[str, Any],
                                registry_risk: "dict[str, str] | None" = None):
        _merged = {**_RISK, **(registry_risk or {})}
        risk_val = _merged.get(action, "medium")
        return await self._gate.request(
            action, args, description=self._describe(action, args),
            risk=risk_val,
        )

    @property
    def gate(self) -> ApprovalGate:
        return self._gate

    @property
    def signer(self) -> ReceiptSigner:
        return self._signer

    def take_receipt(self) -> Receipt | None:
        rec = self.last_receipt
        self.last_receipt = None
        return rec

    def take_computer_artifact(self) -> "tuple[str, tuple | None] | None":
        art = self.last_computer_artifact
        self.last_computer_artifact = None
        return art

    def _gate_only_write(self, action: str, args: dict[str, Any]) -> Any:
        meta = self._gate.evaluate_sync(action, args)
        if meta is not None:
            if meta.decision == "deny":
                return meta.reason or t("sandbox.broker.write_hard_denied", action=action)
            if meta.secret_pattern or (meta.trigger or "").startswith("secret:"):
                return t("sandbox.broker.write_secret_detected",
                         pattern=meta.secret_pattern or "?")
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=_files.WRITE_APPROVED_SENTINEL, exit_code=0,
        )
        return _files.WRITE_APPROVED_SENTINEL

    def _execute(self, action: str, args: dict[str, Any],
                 run_ctx: Any = None, *, _gated: bool = False,
                 allow_network: bool = False) -> tuple[Any, int | None]:
        _registry = getattr(self, "_registry", None)
        if _registry is not None:
            try:
                cap = _registry.get(action)
                if cap.dispatch is not None:
                    if not _gated:
                        raise PermissionError(
                            t("sandbox.broker.dispatch_bypass", action=action)
                        )
                    result = cap.dispatch(args, run_ctx)
                    return result, None
            except KeyError:
                pass
        if action == "run_command":
            return _shell.run_command(args.get("command", ""), workspace=self._workspace,
                                      allow_network=allow_network)
        if action == "web_search":
            return _web.web_search(args.get("query", ""), int(args.get("limit", 5))), None
        if action == "web_extract":
            return _web.web_extract(args.get("url", "")), None
        if action.startswith("browser_"):
            if self._browser_controller is not None:
                ctrl = self._browser_controller
            else:
                from argos import browser as _browser
                ctrl = _browser.get_controller()
            if action == "browser_navigate":
                return ctrl.navigate(args.get("url", "")), None
            if action == "browser_snapshot":
                return ctrl.snapshot(int(args.get("max_chars", 4000))), None
            if action == "browser_click":
                return ctrl.click(args.get("selector", "")), None
            if action == "browser_type":
                return ctrl.type_text(args.get("selector", ""), args.get("text", "")), None
            if action == "browser_screenshot":
                return ctrl.screenshot(args.get("path", "screenshot.png")), None
        if action == "mcp_call":
            if self._mcp_manager is not None:
                mgr = self._mcp_manager
            else:
                from argos import mcp_native
                mgr = mcp_native.get_manager()
            arguments = args.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            return mgr.call(args.get("server", ""), args.get("tool", ""), arguments), None
        if action.startswith("computer_"):
            from argos.perception.actions import ComputerAction
            from argos.perception.executor import ComputerExecutor
            kind = action[len("computer_"):]   # "click" / "screenshot" / …
            try:
                ca = ComputerAction(
                    kind=kind,  # type: ignore[arg-type]
                    x=int(args["x"]) if "x" in args else None,
                    y=int(args["y"]) if "y" in args else None,
                    text=str(args["text"]) if "text" in args else None,
                    app=str(args["app"]) if "app" in args else None,
                )
            except (ValueError, TypeError) as exc:
                return t("sandbox.broker.computer_args_invalid", exc=exc), None
            result = ComputerExecutor(auto_detect_scale=True).dispatch(ca)
            if result.ok and getattr(result, "artifact_path", None):
                self.last_computer_artifact = (
                    result.artifact_path, getattr(result, "size", None),
                )
            return result.detail, (0 if result.ok else 1)
        if action.startswith("lsp_"):
            import json as _json
            from argos import lsp as _lsp
            from argos.lsp.tools import (
                lsp_definition_gated as _lsp_def,
                lsp_references_gated as _lsp_ref,
                lsp_hover_gated as _lsp_hov,
                lsp_document_symbols_gated as _lsp_dsym,
                lsp_workspace_symbols_gated as _lsp_wsym,
                lsp_diagnostics_gated as _lsp_diag,
            )
            mgr = _lsp.get_manager()
            workspace = self._workspace if self._workspace is not None else Path.cwd()
            kwargs: dict = {"manager": mgr, "workspace": workspace}
            if action == "lsp_definition":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_def(
                    server_name=sname,
                    file=file,
                    line=int(args.get("line", 1)),
                    col=int(args.get("col", 1)),
                    **kwargs,
                ), None
            if action == "lsp_references":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_ref(
                    server_name=sname,
                    file=file,
                    line=int(args.get("line", 1)),
                    col=int(args.get("col", 1)),
                    include_declaration=bool(args.get("include_declaration", True)),
                    **kwargs,
                ), None
            if action == "lsp_hover":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_hov(
                    server_name=sname,
                    file=file,
                    line=int(args.get("line", 1)),
                    col=int(args.get("col", 1)),
                    **kwargs,
                ), None
            if action == "lsp_document_symbols":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_dsym(
                    server_name=sname,
                    file=file,
                    **kwargs,
                ), None
            if action == "lsp_workspace_symbols":
                sname = _resolve_lsp_server(file=None, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": "no lsp server configured"}), None
                return _lsp_wsym(
                    server_name=sname,
                    query=args.get("query", ""),
                    **kwargs,
                ), None
            if action == "lsp_diagnostics":
                file = args.get("file", "")
                sname = _resolve_lsp_server(file=file, manager=mgr)
                if sname is None:
                    return _json.dumps({"error": f"no lsp server configured for {Path(file).suffix or file!r}"}), None
                return _lsp_diag(
                    server_name=sname,
                    file=file,
                    **kwargs,
                ), None
        if action in _FILE_WRITE_ACTIONS:
            return _files.WRITE_APPROVED_SENTINEL, 0
        return t("sandbox.broker.execute_unknown_action", action=action), None

    @staticmethod
    def _describe(action: str, args: dict[str, Any]) -> str:
        if action == "run_command":
            cmd = args.get("command", "")
            if _shell.command_needs_network(cmd):
                return t("sandbox.broker.describe_run_command_net", cmd=cmd)
            return t("sandbox.broker.describe_run_command", cmd=cmd)
        if action == "web_search":
            return t("sandbox.broker.describe_web_search", query=args.get("query", ""))
        if action == "web_extract":
            return t("sandbox.broker.describe_web_extract", url=args.get("url", ""))
        if action == "browser_navigate":
            return t("sandbox.broker.describe_browser_navigate", url=args.get("url", ""))
        if action == "browser_snapshot":
            return t("sandbox.broker.describe_browser_snapshot")
        if action == "browser_screenshot":
            return t("sandbox.broker.describe_browser_screenshot", path=args.get("path", "screenshot.png"))
        if action == "browser_click":
            return t("sandbox.broker.describe_browser_click", selector=args.get("selector", ""))
        if action == "browser_type":
            return t("sandbox.broker.describe_browser_type", selector=args.get("selector", ""))
        if action == "mcp_call":
            return t("sandbox.broker.describe_mcp_call",
                     server=args.get("server", ""), tool=args.get("tool", ""))
        return f"{action} {args}"
