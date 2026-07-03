"""Internal documentation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from argos.capability.manifest import Capability
from argos.i18n import t

if TYPE_CHECKING:
    from argos.capability.registry import CapabilityRegistry
    from argos.sandbox.egress import EgressPolicy


_LSP_ACTIONS: tuple[str, ...] = (
    "lsp_definition",
    "lsp_references",
    "lsp_hover",
    "lsp_document_symbols",
    "lsp_workspace_symbols",
    "lsp_diagnostics",
)

_SEARCH_EGRESS: tuple[str, ...] = (
    "api.tavily.com",
    "duckduckgo.com",
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
)


def _builtin_capabilities() -> tuple[Capability, ...]:
    """Internal documentation."""
    caps: list[Capability] = [
        Capability(
            name="read_file",
            kind="tool",
            risk="low",
            reversible=True,
            visibility="all",
            verify_hint=t("cap.hint.read_file"),
        ),
        Capability(
            name="write_file",
            kind="tool",
            risk="medium",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.write_file"),
        ),
        Capability(
            name="edit_file",
            kind="tool",
            risk="medium",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.edit_file"),
        ),
        Capability(
            name="search_files",
            kind="tool",
            risk="low",
            reversible=True,
            visibility="all",
        ),
        Capability(
            name="update_plan",
            kind="tool",
            risk="low",
            reversible=True,
            visibility="all",
            verify_hint=t("cap.hint.update_plan"),
        ),
        Capability(
            name="propose_verify",
            kind="tool",
            risk="low",
            reversible=True,
            visibility="all",
            verify_hint=t("cap.hint.propose_verify"),
        ),
        Capability(
            name="propose_dom_verify",
            kind="tool",
            risk="low",
            reversible=True,
            visibility="all",
            verify_hint=t("cap.hint.propose_dom_verify"),
        ),
        Capability(
            name="propose_gui_verify",
            kind="tool",
            risk="low",
            reversible=True,
            visibility="all",
            verify_hint=t("cap.hint.propose_gui_verify"),
        ),
        Capability(
            name="propose_workflow",
            kind="tool",
            risk="low",
            reversible=True,
            visibility="all",
            verify_hint=t("cap.hint.propose_workflow"),
        ),
        # ── shell ──────────────────────────────────────────────────────────
        Capability(
            name="run_command",
            kind="tool",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.run_command"),
        ),
        Capability(
            name="web_search",
            kind="tool",
            risk="low",
            reversible=True,
            egress_hosts=_SEARCH_EGRESS,
            visibility="all",
        ),
        Capability(
            name="web_extract",
            kind="tool",
            risk="low",
            reversible=True,
            egress_hosts=("*",),
            visibility="all",
        ),
        Capability(name="browser_navigate",   kind="browser", risk="low",  reversible=True,  visibility="all"),
        Capability(name="browser_snapshot",   kind="browser", risk="low",  reversible=True,  visibility="all"),
        Capability(name="browser_screenshot", kind="browser", risk="low",  reversible=True,  visibility="all"),
        Capability(name="browser_click",      kind="browser", risk="medium", reversible=False, visibility="all"),
        Capability(name="browser_type",       kind="browser", risk="medium", reversible=False, visibility="all"),
        # ── MCP ─────────────────────────────────────────────────────────────
        Capability(
            name="mcp_call",
            kind="mcp",
            risk="medium",
            reversible=None,
            visibility="all",
        ),
        Capability(
            name="computer_screenshot",
            kind="computer",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.computer_no_channel_screenshot"),
        ),
        Capability(
            name="computer_click",
            kind="computer",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.computer_no_channel"),
        ),
        Capability(
            name="computer_double_click",
            kind="computer",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.computer_no_channel"),
        ),
        Capability(
            name="computer_type_text",
            kind="computer",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.computer_type_text"),
        ),
        Capability(
            name="computer_key",
            kind="computer",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.computer_no_channel"),
        ),
        Capability(
            name="computer_scroll",
            kind="computer",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.computer_no_channel"),
        ),
        Capability(
            name="computer_open_app",
            kind="computer",
            risk="high",
            reversible=False,
            visibility="all",
            verify_hint=t("cap.hint.computer_open_app"),
        ),
    ]

    for lsp_name in _LSP_ACTIONS:
        caps.append(Capability(
            name=lsp_name,
            kind="lsp",
            risk="low",
            reversible=True,
            visibility="developer",
            verify_hint=t("cap.hint.lsp_readonly"),
        ))

    return tuple(caps)


def register_builtins(
    registry: "CapabilityRegistry",
    *,
    egress: "EgressPolicy | None" = None,
) -> None:
    """Internal documentation."""
    for cap in _builtin_capabilities():
        if cap.name in registry:
            continue
        registry.register(cap)
        if egress is not None and cap.egress_hosts:
            real_hosts = tuple(h for h in cap.egress_hosts if h != "*")
            if real_hosts:
                egress.add_hosts(real_hosts)


register_builtin_capabilities = register_builtins
