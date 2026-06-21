"""Infra cluster locale — MCP, LSP, hooks, capability strings.

key namespace: mcp.* / lsp.* / hooks.* / cap.*
ZH values = verbatim originals (so ARGOS_LANG=zh legacy assertions still match).
EN values = natural English equivalents; "Error:" prefix matches ZH "错误:" prefix.
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── argos/mcp_native.py ───────────────────────────────────────────────────

    # _StdioServer.connect: missing command field
    "mcp.server.missing_command": "missing command",
    # _StdioServer.connect: process failed to start
    "mcp.server.start_failed": "start failed: {exc_type}: {exc}",
    # _StdioServer.connect: initialize RPC failed
    "mcp.server.initialize_failed": "initialize failed: {error}",
    # _StdioServer.connect: handshake exception
    "mcp.server.handshake_error": "handshake exception: {exc_type}: {exc}",
    # _StdioServer.call: server not connected or exited
    "mcp.server.not_connected": "Error: MCP server {name!r} is not connected or has exited.",
    # _StdioServer.call: tool call exception
    "mcp.server.call_error": "Error: MCP call {name}/{tool} raised {exc_type}: {exc}",
    # _StdioServer.call: tool returned error
    "mcp.server.call_rpc_error": "Error: MCP {name}/{tool} returned error: {error}",
    # _StdioServer._rpc: timed out waiting for response
    "mcp.server.rpc_timeout": "{method} timed out ({timeout}s): server not responding",
    # _StdioServer._reader_loop: stdout closed
    "mcp.server.stdout_closed": "server stdout closed (process may have exited)",
    # _flatten_content: non-text content type placeholder
    "mcp.content.non_text": "[{content_type} content]",
    # _flatten_content: tool reported an error
    "mcp.content.tool_error": "[MCP tool error] {out}",
    # _flatten_content: tool returned empty result
    "mcp.content.empty_result": "(MCP tool returned empty result)",
    # McpManager.call: no MCP servers configured
    "mcp.manager.no_servers": (
        "Error: no MCP server configured"
        " (~/.argos/mcp.json does not exist or is empty)."
    ),
    # McpManager.call: unknown server name
    "mcp.manager.unknown_server": (
        "Error: unknown MCP server {server!r} (available: {available})."
    ),
    # McpManager.call: server exists but is unavailable
    "mcp.manager.server_unavailable": (
        "Error: MCP server {server!r} is unavailable ({error})."
    ),

    # ── argos/lsp/config.py ──────────────────────────────────────────────────

    # LspServerConfig.__post_init__: empty command
    "lsp.config.empty_command": (
        "LspServerConfig.command must not be empty (spawning an empty argv is invalid)"
    ),
    # LspServerConfig.__post_init__: filetype must start with dot
    "lsp.config.filetype_no_dot": (
        "LspServerConfig.filetypes entries must start with '.' (e.g. '.py'); got {ft!r}"
    ),
    # LspServerConfig.__post_init__: filetypes list is empty
    "lsp.config.empty_filetypes": (
        "LspServerConfig.filetypes must not be empty (0 served filetypes = dead code)"
    ),
    # _validate_server_name: invalid server name
    "lsp.config.invalid_server_name": (
        "server name {name!r} is invalid:"
        " only ASCII alphanumeric + _ + - are allowed (spec §2.2)"
    ),
    # _parse_server_config: server entry must be object
    "lsp.config.server_not_object": (
        "server {name!r} must be an object; got {type_name}"
    ),
    # _parse_server_config: missing 'command' field
    "lsp.config.missing_command_field": "server {name!r} is missing the 'command' field",
    # _parse_server_config: missing 'filetypes' field
    "lsp.config.missing_filetypes_field": "server {name!r} is missing the 'filetypes' field",
    # _parse_server_config: 'command' must be a non-empty array
    "lsp.config.command_not_array": (
        "server {name!r} 'command' must be a non-empty array (argv list, not a shell string);"
        " got {value!r}"
    ),
    # _parse_server_config: 'command' items must be non-empty strings
    "lsp.config.command_item_not_string": (
        "server {name!r} 'command' items must be non-empty strings"
    ),
    # _parse_server_config: 'filetypes' must be a non-empty array
    "lsp.config.filetypes_not_array": (
        "server {name!r} 'filetypes' must be a non-empty array"
    ),
    # _parse_server_config: 'filetypes' items must be strings
    "lsp.config.filetypes_item_not_string": (
        "server {name!r} 'filetypes' items must be strings"
    ),
    # _parse_server_config: 'init_options' must be object
    "lsp.config.init_options_not_object": (
        "server {name!r} 'init_options' must be an object"
    ),
    # _parse_server_config: 'env' must be object
    "lsp.config.env_not_object": "server {name!r} 'env' must be an object",
    # _parse_server_config: 'env' items must be string→string
    "lsp.config.env_not_string_map": (
        "server {name!r} 'env' items must be string→string mappings"
    ),
    # _parse_server_config: 'disabled' must be bool
    "lsp.config.disabled_not_bool": "server {name!r} 'disabled' must be a bool",
    # _parse_server_config: server config is invalid (wraps ValueError from __post_init__)
    "lsp.config.server_invalid": "server {name!r} is invalid: {exc}",
    # load: missing 'version' field
    "lsp.config.missing_version": "lsp.json is missing the 'version' field",
    # load: version mismatch
    "lsp.config.version_mismatch": (
        "lsp.json version={version} does not match (host only supports v1)"
    ),
    # load: 'servers' must be object
    "lsp.config.servers_not_object": (
        "'servers' must be an object (server name → config)"
    ),

    # ── argos/hooks/config.py ─────────────────────────────────────────────────

    # HookHandler.__post_init__: invalid handler type
    "hooks.config.handler_type_invalid": (
        "HookHandler.type must be one of {valid}; got {type_val!r}"
    ),
    # HookHandler.__post_init__: empty command
    "hooks.config.handler_command_empty": "HookHandler.command must not be empty",
    # HookHandler.__post_init__: non-positive timeout
    "hooks.config.handler_timeout_nonpositive": (
        "HookHandler.timeout must be > 0 ms; got {timeout}"
    ),
    # _validate_event_name: unknown event
    "hooks.config.unknown_event": (
        "unknown event name {event_name!r}; allowed: {allowed}"
    ),
    # _parse_handler: handler must be dict
    "hooks.config.handler_not_dict": (
        "hook handler must be a dict; got {type_name}"
    ),
    # _parse_handler: missing 'type' field
    "hooks.config.handler_missing_type": "hook handler is missing the 'type' field",
    # _parse_handler: missing 'command' field
    "hooks.config.handler_missing_command": "hook handler is missing the 'command' field",
    # _parse_handler: handler is invalid (wraps ValueError from __post_init__)
    "hooks.config.handler_invalid": "hook handler is invalid: {exc}",
    # _parse_entry: entry must be dict
    "hooks.config.entry_not_dict": (
        "matcher entry must be a dict; got {type_name}"
    ),
    # _parse_entry: missing 'hooks' field
    "hooks.config.entry_missing_hooks": "matcher entry is missing the 'hooks' field",
    # _parse_entry: 'hooks' must be a non-empty array
    "hooks.config.entry_hooks_not_array": (
        "matcher entry 'hooks' must be a non-empty array"
    ),
    # _parse_entry: matcher must be string or omitted
    "hooks.config.entry_matcher_not_string": (
        "matcher must be a string or omitted; got {type_name}"
    ),
    # load: missing 'version' field
    "hooks.config.missing_version": "hooks.json is missing the 'version' field",
    # load: version mismatch
    "hooks.config.version_mismatch": (
        "hooks.json version={version} does not match (host only supports v1)"
    ),
    # load: 'hooks' must be object
    "hooks.config.hooks_not_object": (
        "'hooks' must be an object (event name → matcher entries)"
    ),
    # load: event entries must be array
    "hooks.config.event_entries_not_array": (
        "entries for event {event_name!r} must be an array"
    ),

    # ── argos/hooks/matcher.py ────────────────────────────────────────────────

    # validate_matcher: length exceeds limit
    "hooks.matcher.too_long": (
        "matcher length {length} > {limit} (spec D14 upper bound)"
    ),
    # validate_matcher: nested quantifiers detected
    "hooks.matcher.nested_quantifiers": (
        "matcher {matcher!r} contains nested quantifiers"
        " (ReDoS-dangerous pattern, spec D14):"
        " patterns like (.*)* / (.+)+ etc."
    ),
    # validate_matcher: regex compilation failed
    "hooks.matcher.compile_error": (
        "matcher {matcher!r} failed to compile (re.error): {exc}"
    ),

    # ── argos/capability/manifest.py ──────────────────────────────────────────

    # Capability.__post_init__: name must not be empty
    "cap.manifest.empty_name": "Capability.name must not be an empty string",
    # Capability.__post_init__: invalid kind
    "cap.manifest.invalid_kind": "Capability.kind has invalid value: {kind!r}",
    # Capability.__post_init__: invalid visibility
    "cap.manifest.invalid_visibility": "Capability.visibility has invalid value: {visibility!r}",

    # ── argos/capability/registry.py ─────────────────────────────────────────

    # CapabilityRegistry.register: risk is None (fail-closed)
    "cap.registry.register_no_risk": (
        "capability {name!r} registration failed: risk not declared (fail-closed)."
        " Must explicitly specify risk='low'|'medium'|'high'."
    ),
    # CapabilityRegistry.register: duplicate name
    "cap.registry.register_duplicate": (
        "capability {name!r} registration failed: name already exists"
        " (global uniqueness constraint)."
    ),
    # CapabilityRegistry.get: not registered
    "cap.registry.not_found": "capability {name!r} is not registered.",

    # ── argos/capability/builtins.py (verify_hint strings) ───────────────────

    # verify_hint for read_file
    "cap.hint.read_file": "verify returned content matches expectations",
    # verify_hint for write_file
    "cap.hint.write_file": "verify file exists and content is correct",
    # verify_hint for edit_file
    "cap.hint.edit_file": "verify target fragment has been replaced",
    # verify_hint for update_plan
    "cap.hint.update_plan": "verify TODO list has been updated in the activity bar",
    # verify_hint for propose_verify
    "cap.hint.propose_verify": (
        "verify verify_cmd is registered (harness runs it independently at completion)"
    ),
    # verify_hint for propose_dom_verify
    "cap.hint.propose_dom_verify": (
        "verify L3 DOM validation strategy is registered"
        " (host-side DomProber runs three-state assertion at completion)"
    ),
    # verify_hint for propose_gui_verify
    "cap.hint.propose_gui_verify": (
        "verify GUI validation is registered"
        " (host-side GuiProber takes screenshot + OCR three-state assertion at completion)"
    ),
    # verify_hint for propose_workflow
    "cap.hint.propose_workflow": "verify workflow is registered and awaiting approval",
    # verify_hint for run_command
    "cap.hint.run_command": "verify exit_code=0 + expected output",
    # verify_hint for computer_screenshot (no machine-check channel)
    "cap.hint.computer_no_channel_screenshot": (
        "GUI actions have no machine-check channel; verification via L5 audit trail;"
        " screenshot must never independently produce 'passed'"
    ),
    # verify_hint for computer click/key/scroll etc. (no machine-check channel)
    "cap.hint.computer_no_channel": (
        "GUI actions have no machine-check channel; verification via L5 audit trail"
    ),
    # verify_hint for computer_type_text (financial/captcha forced CONFIRM)
    "cap.hint.computer_type_text": (
        "GUI actions have no machine-check channel; verification via L5 audit trail;"
        " financial/captcha patterns force CONFIRM"
    ),
    # verify_hint for computer_open_app (payment/banking apps forced CONFIRM)
    "cap.hint.computer_open_app": (
        "GUI actions have no machine-check channel; verification via L5 audit trail;"
        " payment/banking apps force CONFIRM"
    ),
    # verify_hint for LSP tools (read-only, no side effects)
    "cap.hint.lsp_readonly": "read-only query, no side effects",
}

ZH: dict[str, str] = {
    # ── argos/mcp_native.py ───────────────────────────────────────────────────

    "mcp.server.missing_command": "缺少 command",
    "mcp.server.start_failed": "启动失败:{exc_type}: {exc}",
    "mcp.server.initialize_failed": "initialize 失败:{error}",
    "mcp.server.handshake_error": "握手异常:{exc_type}: {exc}",
    "mcp.server.not_connected": "错误:MCP server {name!r} 未连接或已退出。",
    "mcp.server.call_error": "错误:MCP 调用 {name}/{tool} 异常:{exc_type}: {exc}",
    "mcp.server.call_rpc_error": "错误:MCP {name}/{tool} 返回错误:{error}",
    "mcp.server.rpc_timeout": "{method} 超时({timeout}s):server 无响应",
    "mcp.server.stdout_closed": "server stdout 关闭(进程可能已退出)",
    "mcp.content.non_text": "[{content_type} 内容]",
    "mcp.content.tool_error": "[MCP 工具报错] {out}",
    "mcp.content.empty_result": "(MCP 工具返回空)",
    "mcp.manager.no_servers": (
        "错误:未配置任何 MCP server(~/.argos/mcp.json 不存在或为空)。"
    ),
    "mcp.manager.unknown_server": (
        "错误:未知 MCP server {server!r}(可用:{available})。"
    ),
    "mcp.manager.server_unavailable": (
        "错误:MCP server {server!r} 不可用({error})。"
    ),

    # ── argos/lsp/config.py ──────────────────────────────────────────────────

    "lsp.config.empty_command": (
        "LspServerConfig.command 不能为空(否则 spawn 空 argv)"
    ),
    "lsp.config.filetype_no_dot": (
        "LspServerConfig.filetypes 项必须以 . 开头(如 '.py'),收到 {ft!r}"
    ),
    "lsp.config.empty_filetypes": (
        "LspServerConfig.filetypes 不能为空(0 server 服务 = 死代码)"
    ),
    "lsp.config.invalid_server_name": (
        "server name {name!r} 非法:仅允许 ASCII 字母数字 + _ + -(spec §2.2)"
    ),
    "lsp.config.server_not_object": (
        "server {name!r} 必须是 object,收到 {type_name}"
    ),
    "lsp.config.missing_command_field": "server {name!r} 缺 'command' 字段",
    "lsp.config.missing_filetypes_field": "server {name!r} 缺 'filetypes' 字段",
    "lsp.config.command_not_array": (
        "server {name!r} 'command' 必须是非空 array(argv 数组,不是 shell 字符串),收到 {value!r}"
    ),
    "lsp.config.command_item_not_string": (
        "server {name!r} 'command' 项必须是非空 string"
    ),
    "lsp.config.filetypes_not_array": (
        "server {name!r} 'filetypes' 必须是非空 array"
    ),
    "lsp.config.filetypes_item_not_string": (
        "server {name!r} 'filetypes' 项必须是 string"
    ),
    "lsp.config.init_options_not_object": (
        "server {name!r} 'init_options' 必须是 object"
    ),
    "lsp.config.env_not_object": "server {name!r} 'env' 必须是 object",
    "lsp.config.env_not_string_map": (
        "server {name!r} 'env' 项必须是 string→string 映射"
    ),
    "lsp.config.disabled_not_bool": "server {name!r} 'disabled' 必须是 bool",
    "lsp.config.server_invalid": "server {name!r} 非法: {exc}",
    "lsp.config.missing_version": "lsp.json 缺 'version' 字段",
    "lsp.config.version_mismatch": (
        "lsp.json version={version} 不匹配(host 仅支持 v1)"
    ),
    "lsp.config.servers_not_object": (
        "'servers' 必须是 object(server name → config)"
    ),

    # ── argos/hooks/config.py ─────────────────────────────────────────────────

    "hooks.config.handler_type_invalid": (
        "HookHandler.type 必须是 {valid} 之一,收到 {type_val!r}"
    ),
    "hooks.config.handler_command_empty": "HookHandler.command 不能为空",
    "hooks.config.handler_timeout_nonpositive": (
        "HookHandler.timeout 必须 > 0 ms,收到 {timeout}"
    ),
    "hooks.config.unknown_event": (
        "未知事件名 (event) {event_name!r};允许: {allowed}"
    ),
    "hooks.config.handler_not_dict": (
        "hook handler 必须是 dict,收到 {type_name}"
    ),
    "hooks.config.handler_missing_type": "hook handler 缺 'type' 字段",
    "hooks.config.handler_missing_command": "hook handler 缺 'command' 字段",
    "hooks.config.handler_invalid": "hook handler 非法: {exc}",
    "hooks.config.entry_not_dict": (
        "matcher entry 必须是 dict,收到 {type_name}"
    ),
    "hooks.config.entry_missing_hooks": "matcher entry 缺 'hooks' 字段",
    "hooks.config.entry_hooks_not_array": (
        "matcher entry 'hooks' 必须是非空 array"
    ),
    "hooks.config.entry_matcher_not_string": (
        "matcher 必须是 string 或省略,收到 {type_name}"
    ),
    "hooks.config.missing_version": "hooks.json 缺 'version' 字段",
    "hooks.config.version_mismatch": (
        "hooks.json version={version} 不匹配(host 仅支持 v1)"
    ),
    "hooks.config.hooks_not_object": (
        "'hooks' 必须是 object(事件名 → matcher entries)"
    ),
    "hooks.config.event_entries_not_array": (
        "事件 {event_name!r} 的 entries 必须是 array"
    ),

    # ── argos/hooks/matcher.py ────────────────────────────────────────────────

    "hooks.matcher.too_long": (
        "matcher 长度 {length} > {limit}(spec D14 上限)"
    ),
    "hooks.matcher.nested_quantifiers": (
        "matcher {matcher!r} 含嵌套量词(ReDoS 危险模式,spec D14):"
        "形如 (.*)* / (.+)+ 等"
    ),
    "hooks.matcher.compile_error": (
        "matcher {matcher!r} 编译失败(re.error): {exc}"
    ),

    # ── argos/capability/manifest.py ──────────────────────────────────────────

    "cap.manifest.empty_name": "Capability.name 不能为空串",
    "cap.manifest.invalid_kind": "Capability.kind 非法值：{kind!r}",
    "cap.manifest.invalid_visibility": "Capability.visibility 非法值：{visibility!r}",

    # ── argos/capability/registry.py ─────────────────────────────────────────

    "cap.registry.register_no_risk": (
        "能力 {name!r} 注册失败：risk 未声明（fail-closed）。"
        "必须显式指定 risk='low'|'medium'|'high'。"
    ),
    "cap.registry.register_duplicate": (
        "能力 {name!r} 注册失败：名称已存在（全局唯一约束）。"
    ),
    "cap.registry.not_found": "能力 {name!r} 未注册。",

    # ── argos/capability/builtins.py (verify_hint strings) ───────────────────

    "cap.hint.read_file": "检查返回内容是否符合预期",
    "cap.hint.write_file": "检查文件存在且内容正确",
    "cap.hint.edit_file": "检查目标片段已被替换",
    "cap.hint.update_plan": "检查 TODO 列表已更新至活动栏",
    "cap.hint.propose_verify": "检查 verify_cmd 已登记（harness 收尾独立运行）",
    "cap.hint.propose_dom_verify": (
        "检查 L3 DOM 验证策略已登记（host 侧 DomProber 收尾时执行三态断言）"
    ),
    "cap.hint.propose_gui_verify": (
        "检查 GUI 验证已登记（host 侧 GuiProber 收尾时截图+OCR 三态断言）"
    ),
    "cap.hint.propose_workflow": "检查工作流已登记待审批",
    "cap.hint.run_command": "检查 exit_code=0 + 预期输出",
    "cap.hint.computer_no_channel_screenshot": (
        "GUI 动作无机检通道,验证走 L5 留痕;screenshot 永不单独产出 passed"
    ),
    "cap.hint.computer_no_channel": "GUI 动作无机检通道,验证走 L5 留痕",
    "cap.hint.computer_type_text": (
        "GUI 动作无机检通道,验证走 L5 留痕;金融/验证码模式命中强制 CONFIRM"
    ),
    "cap.hint.computer_open_app": (
        "GUI 动作无机检通道,验证走 L5 留痕;支付/银行类 app 强制 CONFIRM"
    ),
    "cap.hint.lsp_readonly": "只读查询,无副作用",
}
