"""Sandbox cluster locale — user-facing strings from broker and executor.

key namespace: sandbox.*
"""
from __future__ import annotations

EN: dict[str, str] = {
    # egress: SSRF private-network block (web_extract)
    "sandbox.egress.ssrf_deny": (
        "SSRF guard blocked private/reserved/internal address"
        " (web_extract only allows public URLs): {host!r}"
    ),
    # egress: host not in allowlist
    "sandbox.egress.host_not_allowed": (
        "egress denied — {host!r} is not in the allowed egress list."
        " Use /trust autonomous to open egress for this session,"
        " or add the host to the egress section in ~/.argos/config.json and restart."
    ),
    # unknown / unsupported privileged action
    "sandbox.broker.unknown_action": (
        "Error: unknown/unsupported privileged action {action!r}, denied."
    ),
    # hard shell rule hit on run_command
    "sandbox.broker.hard_shell_denied": (
        "Error: command matched dangerous hard rule ({rule}), execution denied."
    ),
    # user explicitly denied the action via approval gate
    "sandbox.broker.user_denied": (
        "User denied the operation ({reason})."
        " Please try a different approach or explain to the user why it is needed."
    ),
    # fallback when decision.reason is None
    "sandbox.broker.user_denied_no_reason": "no reason provided",
    # computer control hit non-developer-domain hard rule on sync bridge
    "sandbox.broker.computer_hard_rule_denied": (
        "Error: computer control matched a non-developer-domain hard rule ({rule}),"
        " requiring an in-person confirmation;"
        " the sync bridge (sub-agent AUTO) cannot interactively approve → fail-closed denied."
    ),
    # approval bridge raised an exception
    "sandbox.broker.bridge_exception": (
        "Error: approval bridge raised an exception ({exc_type}), denied by default."
    ),
    # file write blocked by hard-path deny rule
    "sandbox.broker.write_hard_denied": (
        "{action} blocked by hard rule."
    ),
    # file write blocked because secret detected
    "sandbox.broker.write_secret_detected": (
        "⚠ Possible secret detected ({pattern}) — write denied."
        " Remove the secret and retry, or ask the user to explicitly allow this write."
    ),
    # no broker context in executor
    "sandbox.executor.no_broker_context": (
        "Error: this tool requires broker authorization but no broker context is present, denied by default."
    ),
    # win32 unsupported platform
    "sandbox.executor.win32_unsupported": (
        "Argos's kernel-level sandbox currently supports only macOS (Seatbelt)"
        " and Linux (bubblewrap/unshare); Windows is not yet supported."
    ),
    # sandbox init failed (executor / linux)
    "sandbox.executor.init_failed": "sandbox init failed: {msg!r}; stderr={stderr}",
    # executor not yet spawned
    "sandbox.executor.not_spawned": "executor not spawned",
    # sandbox channel unexpectedly closed
    "sandbox.executor.channel_closed": "sandbox channel closed unexpectedly; stderr={stderr}",
    # unknown linux sandbox backend
    "sandbox.linux.unknown_backend": "unknown Linux sandbox backend: {backend!r}",
    # no available linux sandbox backend (spawn-time check)
    "sandbox.linux.no_backend_spawn": (
        "no Linux sandbox backend available (bwrap / unshare not in PATH);"
        " install bwrap or unshare and retry, or abandon isolation honestly"
    ),
    # no available linux sandbox backend (select_backend)
    "sandbox.linux.no_backend_select": (
        "no Linux sandbox backend available (bwrap / unshare not in PATH);"
        " install bwrap or unshare and retry, or abandon isolation honestly"
    ),
    # dispatch capability bypassed without going through request()
    "sandbox.broker.dispatch_bypass": (
        "dispatch capability {action!r} may only be executed via the broker.request() pipeline"
        " (egress / approval / receipt cannot be bypassed)"
    ),
    # computer action parameter validation failed
    "sandbox.broker.computer_args_invalid": "computer action parameter validation failed: {exc}",
    # unknown action in _execute (fallback honest return)
    "sandbox.broker.execute_unknown_action": "Error: action {action!r} not yet implemented for host execution.",
    # _describe: run_command with network
    "sandbox.broker.describe_run_command_net": "execute command (needs network, will temporarily open egress) {cmd}",
    # _describe: run_command without network
    "sandbox.broker.describe_run_command": "execute command {cmd}",
    # _describe: web_search
    "sandbox.broker.describe_web_search": "web search {query}",
    # _describe: web_extract
    "sandbox.broker.describe_web_extract": "fetch web page {url}",
    # _describe: browser_navigate
    "sandbox.broker.describe_browser_navigate": "browser open {url}",
    # _describe: browser_snapshot
    "sandbox.broker.describe_browser_snapshot": "read current browser page content",
    # _describe: browser_screenshot
    "sandbox.broker.describe_browser_screenshot": "browser screenshot to {path}",
    # _describe: browser_click
    "sandbox.broker.describe_browser_click": "browser click {selector}",
    # _describe: browser_type
    "sandbox.broker.describe_browser_type": "browser type text into {selector}",
    # _describe: mcp_call
    "sandbox.broker.describe_mcp_call": "call MCP tool {server}/{tool}",
}

ZH: dict[str, str] = {
    # egress: SSRF private-network block (web_extract)
    "sandbox.egress.ssrf_deny": (
        "SSRF 防护拒绝私网/保留/内网地址(web_extract 仅允许公网 URL):{host!r}"
    ),
    # egress: host not in allowlist
    "sandbox.egress.host_not_allowed": (
        "egress 拒绝 —— {host!r} 不在允许出网名单。"
        "用 /trust autonomous 放开本会话出网,或在 ~/.argos/config.json 的 egress 段"
        "加入该 host 后重启。"
    ),
    # unknown / unsupported privileged action
    "sandbox.broker.unknown_action": (
        "错误:未知/不支持的特权动作 {action!r},拒绝。"
    ),
    # hard shell rule hit on run_command
    "sandbox.broker.hard_shell_denied": (
        "错误:命令命中危险硬规则({rule}),拒绝执行。"
    ),
    # user explicitly denied the action via approval gate
    "sandbox.broker.user_denied": (
        "用户拒绝执行该操作({reason})。"
        "请尝试其他做法或向用户解释为什么需要它。"
    ),
    # fallback when decision.reason is None
    "sandbox.broker.user_denied_no_reason": "未提供原因",
    # computer control hit non-developer-domain hard rule on sync bridge
    "sandbox.broker.computer_hard_rule_denied": (
        "错误:计算机控制命中非开发者域硬规则({rule}),需人在场确认;"
        "同步桥(子 agent AUTO)无法交互审批 → fail-closed 拒绝。"
    ),
    # approval bridge raised an exception
    "sandbox.broker.bridge_exception": (
        "错误:审批桥异常({exc_type}),默认拒绝。"
    ),
    # file write blocked by hard-path deny rule
    "sandbox.broker.write_hard_denied": (
        "{action} 被硬规则拒绝。"
    ),
    # file write blocked because secret detected
    "sandbox.broker.write_secret_detected": (
        "⚠ 可能含密钥({pattern})—— 已拒绝写入。"
        "请去掉密钥后重试,或请用户显式放行该写入。"
    ),
    # no broker context in executor
    "sandbox.executor.no_broker_context": (
        "错误:该工具需要 broker 授权但当前没有 broker 上下文,默认拒绝。"
    ),
    # win32 unsupported platform
    "sandbox.executor.win32_unsupported": (
        "Argos 的内核级沙箱目前仅支持 macOS (Seatbelt) 与 Linux (bubblewrap/unshare);"
        " Windows is not yet supported."
    ),
    # sandbox init failed (executor / linux)
    "sandbox.executor.init_failed": "sandbox init 失败:{msg!r};stderr={stderr}",
    # executor not yet spawned
    "sandbox.executor.not_spawned": "executor 未 spawn",
    # sandbox channel unexpectedly closed
    "sandbox.executor.channel_closed": "沙箱通道意外关闭;stderr={stderr}",
    # unknown linux sandbox backend
    "sandbox.linux.unknown_backend": "未知 Linux 沙箱后端:{backend!r}",
    # no available linux sandbox backend (spawn-time check)
    "sandbox.linux.no_backend_spawn": (
        "无可用 Linux 沙箱后端(bwrap / unshare 都不在 PATH);"
        "装 bwrap 或 unshare 后重试,或不假装隔离地放弃"
    ),
    # no available linux sandbox backend (select_backend)
    "sandbox.linux.no_backend_select": (
        "无可用 Linux 沙箱后端(bwrap / unshare 都不在 PATH);"
        "装 bwrap 或 unshare 后重试,或不假装隔离地放弃"
    ),
    # dispatch capability bypassed without going through request()
    "sandbox.broker.dispatch_bypass": (
        "dispatch 能力 {action!r} 只允许经 broker.request() 管线执行"
        "(egress/审批/回执不可旁路)"
    ),
    # computer action parameter validation failed
    "sandbox.broker.computer_args_invalid": "computer 动作参数校验失败: {exc}",
    # unknown action in _execute (fallback honest return)
    "sandbox.broker.execute_unknown_action": "错误:动作 {action!r} 暂未实现 host 执行。",
    # _describe: run_command with network
    "sandbox.broker.describe_run_command_net": "执行命令(需联网,将临时开出网阀){cmd}",
    # _describe: run_command without network
    "sandbox.broker.describe_run_command": "执行命令 {cmd}",
    # _describe: web_search
    "sandbox.broker.describe_web_search": "联网搜索 {query}",
    # _describe: web_extract
    "sandbox.broker.describe_web_extract": "取网页 {url}",
    # _describe: browser_navigate
    "sandbox.broker.describe_browser_navigate": "浏览器打开 {url}",
    # _describe: browser_snapshot
    "sandbox.broker.describe_browser_snapshot": "读取当前浏览器页面内容",
    # _describe: browser_screenshot
    "sandbox.broker.describe_browser_screenshot": "浏览器截图到 {path}",
    # _describe: browser_click
    "sandbox.broker.describe_browser_click": "浏览器点击 {selector}",
    # _describe: browser_type
    "sandbox.broker.describe_browser_type": "浏览器在 {selector} 填入文本",
    # _describe: mcp_call
    "sandbox.broker.describe_mcp_call": "调用 MCP 工具 {server}/{tool}",
}
