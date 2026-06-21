"""内置能力 manifest 声明 —— 向 CapabilityRegistry 注册所有 broker 内置动作。

用途：
- 将现有全部内置能力（文件工具/shell/计划/验证/联网/浏览器/MCP/LSP）登记为 manifest，
  registry.risk_table() 可作为权威 risk 来源，ALL_TOOL_NAMES 可从 registry.names() 动态派生。
- LSP 动作（lsp_definition 等）以 kind="lsp" 注册，修复 broker.request 在 registry
  模式下将其 fail-closed 拒绝的 bug（旧路径：lsp_* 在 _RISK 中缺席 → 被拒）。
- dispatch=None 表示由 broker 既有 if/elif 内置路径执行，registry 只提供 manifest 元数据。
  纯沙箱工具（read_file/write_file 等）同样 dispatch=None，沙箱直接执行，broker.request
  路径不经过它们（不在 _RISK 里）。
- 注册网络类能力时附带 egress_hosts，供 EgressPolicy.add_hosts() 热更新白名单。

调用方式::

    from argos.capability.builtins import register_builtins
    register_builtins(registry, egress=egress_policy)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from argos.capability.manifest import Capability
from argos.i18n import t

if TYPE_CHECKING:
    from argos.capability.registry import CapabilityRegistry
    from argos.sandbox.egress import EgressPolicy


# LSP 动作列表（与 broker._execute lsp_ 分支一一对应）
_LSP_ACTIONS: tuple[str, ...] = (
    "lsp_definition",
    "lsp_references",
    "lsp_hover",
    "lsp_document_symbols",
    "lsp_workspace_symbols",
    "lsp_diagnostics",
)

# 内置搜索/提取出网 host（对齐 app_factory._SEARCH_HOSTS）
_SEARCH_EGRESS: tuple[str, ...] = (
    "api.tavily.com",
    "duckduckgo.com",
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
)

# 云端 STT 出网 host(spec §7:注册进 egress 白名单作单一真值表;
# 注:本地 STT 无 egress;云端 STT 在宿主进程跑,egress 主要为审计/一致性)。
_STT_EGRESS: tuple[str, ...] = (
    "api.openai.com",
    "api.deepgram.com",
    "api.groq.com",
)


def _builtin_capabilities() -> tuple[Capability, ...]:
    """返回所有内置能力 manifest（dispatch=None → 由 broker 既有 if/elif 执行）。

    包含：
    - 只读纯沙箱工具（read_file/search_files）—— risk=low，沙箱内直接跑，不经 broker.request。
    - 文件写（write_file/edit_file）—— risk=medium，broker gate-only：host 跑 hard-path/密钥 +
      签回执后返回放行哨兵,真正落盘留在 Seatbelt 子进程(item 3)。
    - 计划/验证/工作流（update_plan/propose_verify/propose_workflow）—— 沙箱内登记回执，
      host loop 解析后在 host 侧处理；dispatch=None。
    - shell/网络/浏览器/MCP/LSP —— broker-gated，经 broker.request gating 管线。
    """
    caps: list[Capability] = [
        # ── 纯沙箱文件工具（沙箱内直接跑，不经 broker.request）─────────────────
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
        # ── 计划/验证/工作流（沙箱内登记回执，host loop 解析处理）──────────────
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
        # ── 网络 ────────────────────────────────────────────────────────────
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
            egress_hosts=("*",),    # 目标 url 动态,egress check 由 broker 直接校验
            visibility="all",
        ),
        Capability(
            name="stt_transcribe",
            kind="tool",
            risk="medium",
            reversible=True,
            egress_hosts=_STT_EGRESS,
            visibility="all",
            sandbox_callable=False,   # 宿主进程语音转写,沙箱外跑、无命名空间包装 → 不计入 /tools 可调用数
        ),
        # ── 浏览器（计算机控制）────────────────────────────────────────────
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
            reversible=None,   # 第三方 server 能力不可预知
            visibility="all",
        ),
        # ── computer use(OS 级控制,P6a §10)──────────────────────────────────
        # 诚实性约定:屏幕/鼠标是全局资源,Seatbelt 关不住;
        # 用"审批 + Ledger + high risk + reversible=False"治理,绝不假装隔离。
        # verify_hint 诚实写:GUI 动作无机检通道,验证走 L5 留痕;
        #   screenshot 不得单独产出 "passed"(spec §10 VLM 红线)。
        # computer.* 全部 risk="high" + reversible=False:
        #   屏幕/鼠标是全局资源,Seatbelt 关不住;用"审批+Ledger+high risk"治理,绝不假装隔离。
        #   verify_hint 诚实写"GUI 动作无机检通道,验证走 L5 留痕"——
        #   截图/VLM 永不单独产出 passed(spec §10 红线)。
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

    # ── LSP（开发者只读工具;修 bug:lsp_* 在旧 _RISK 中缺席 → broker.request 拒）──
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
    """向 registry 注册所有内置能力 manifest，并可选地热更新 egress 白名单。

    Args:
        registry: 目标注册表（进程级单注册表）。
        egress:   若提供，注册网络类能力时调 egress.add_hosts() 热更新出网白名单。
                  fail-closed 不变：未声明的 host 仍被拒。

    重入安全：若注册表已含同名能力则跳过（幂等，允许测试多次调用）。
    """
    for cap in _builtin_capabilities():
        if cap.name in registry:
            continue   # 幂等：已注册则跳过
        registry.register(cap)
        # 热更新 egress：只对声明了 egress_hosts 且 host 不是通配 "*" 的能力
        if egress is not None and cap.egress_hosts:
            real_hosts = tuple(h for h in cap.egress_hosts if h != "*")
            if real_hosts:
                egress.add_hosts(real_hosts)


# ── 任务规格使用名称别名（register_builtin_capabilities）──────────────────────
# P3 任务规格要求以 register_builtin_capabilities 为入口名；
# register_builtins 保留为兼容别名，两者指向同一实现。
register_builtin_capabilities = register_builtins
