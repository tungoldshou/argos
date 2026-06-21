"""用户可见串 —— TUI 诚实护城河组件(verdict_badge / trust_dial / ledger_table /
hard_confirm_card / activity_panel / splash / top_bar / dream_report /
orders_panel / routing_table)。

key 命名空间: verdict.* / trust.* / ledger.* / hardconfirm.* / widget.*
ZH 值 = 现有中文字符逐字复制(verbatim);EN 值 = 自然英文翻译。
"""
from __future__ import annotations

# ── verdict_badge ─────────────────────────────────────────────────────────────

EN: dict[str, str] = {
    # verdict_badge — no_test state (CONTRACT A)
    "verdict.no_test_line": "○ no machine check · no verify command · {detail}",

    # verdict_badge — self-verified (weak pass, contract 10)
    "verdict.self_verified_line1": "◍ self-verified (weak) · {cmd} → {detail}",
    "verdict.self_verified_line2": "  ⤷ not a user-level verify · not promoted to a skill",

    # verdict_badge — passed (strong)
    "verdict.passed_attempts": "{attempts} attempt(s)",
    "verdict.passed_line": "◉ verify passed · {cmd} · {attempts_str} → {detail}",

    # verdict_badge — failed
    "verdict.failed_line1": "◉ verify failed · {cmd} → {detail}",
    "verdict.failed_line2": "  ⤷ still failing after {attempts} attempt(s)",

    # verdict_badge — unverifiable (tampered)
    "verdict.unverifiable_tampered": "◔ unverifiable · protected file(s) changed {tampered} → {detail}",
    # verdict_badge — unverifiable (plain)
    "verdict.unverifiable": "◔ unverifiable · {cmd} · {detail}",

    # ── trust_dial ────────────────────────────────────────────────────────────

    # title line
    "trust.title_prefix": "trust dial · current ",
    "trust.title_level_suffix": "（{short}）",

    # five dial rows: (label, hint)
    "trust.l0_label": "ask me at every step",
    "trust.l0_hint": "confirm everything (including reads)",
    "trust.l1_label": "ask only for risky actions",
    "trust.l1_hint": "pause on high-risk · allow low-risk",
    "trust.l2_label": "ask only for irreversible actions",
    "trust.l2_hint": "follows each capability's reversible flag",
    "trust.l3_label": "approve once, allow same kind this session",
    "trust.l3_hint": "= ACCEPT_EDITS, extended",
    "trust.l4_label": "fully autonomous",
    "trust.l4_hint_red": "⏻ red-light",
    "trust.l4_hint_rest": " · hard rules still enforced",

    # hard-rules footer line
    "trust.hard_rules_prefix": "hard rules, never downgraded:",
    "trust.hard_rules_shell": "dangerous shell",
    "trust.hard_rules_sep": " · ",
    "trust.hard_rules_path": "system paths",
    "trust.hard_rules_secret": "secret detection",

    # provenance footer
    "trust.footer_provenance": "raising the level always shows a warning · never auto-upgrades silently",
    "trust.footer_module": "permissions/trust_dial",

    # ── ledger_table ──────────────────────────────────────────────────────────

    # header
    "ledger.header": "behavior ledger · run {run_id} · {n} entries",

    # column headers (exact cell text)
    "ledger.col_seq": "seq ",
    "ledger.col_action": "action · plain summary",
    "ledger.col_risk": "  risk  ",
    "ledger.col_rev": "  rev   ",
    "ledger.col_undo": "  undo      ",
    "ledger.col_sig": "  sig",

    # ── hard_confirm_card ─────────────────────────────────────────────────────

    # title
    "hardconfirm.title": "⛔ computer control · hard confirm [high · irreversible]",

    # option labels
    "hardconfirm.option_once": "allow once",
    "hardconfirm.option_deny": "deny",

    # governance annotation
    "hardconfirm.governance": (
        "the sandbox cannot fence off the global screen and mouse — "
        "the approval gate, ledger, and audit trail are the only governance layer here"
    ),

    # footer invariant
    "hardconfirm.footer": (
        "every computer.* action is always risk=high and reversible=False · "
        "the trust dial cannot downgrade it"
    ),

    # finish summary line prefix  "◕ approved {action_label} → {value}"
    "hardconfirm.finish_summary": "◕ approved {action_label} → {value}",

    # ── activity_panel section titles ─────────────────────────────────────────

    "widget.section_model": "Model",
    "widget.section_progress": "Task Progress",
    "widget.section_tools": "Tools",
    "widget.section_receipt": "Receipts",
    "widget.section_run": "Run",
    "widget.section_skill_catalog": "Skill Catalog",
    "widget.section_mcp": "MCP",
    "widget.section_hook": "Hook",
    "widget.section_lsp": "LSP",
    "widget.section_skill": "Skill",
    "widget.section_approval": "Approval",
    "widget.section_verdict": "Verdict",
    "widget.section_cost": "Cost + Cache",
    "widget.section_context": "Context",

    # activity_panel body strings
    "widget.progress_pending": "(not started)",
    "widget.tools_zero": "0 calls this run",
    "widget.tools_this_run": "calls this run:\n{tools}",
    "widget.empty": "◌ (none)",
    "widget.progress_todo": "Progress {done}/{total}",
    "widget.skills_none": "none available",
    "widget.skills_available": "{n} available (recalled per task)",
    "widget.mcp_unconfigured": "not configured",
    "widget.mcp_configured": "{n} configured",
    "widget.cache_hit_line": "cache hit {cache_read} tok  {elapsed_s:.1f}s",
    "widget.compacted_line": "↯ compacted -{reduction_pct:.0f}% · {before}→{after} entries",
    "widget.pruned_line": "↯ pruned {removed} entries · {before}→{after}",
    "widget.memory_recall": "◌ recalled {hits} entries",
    "widget.run_suspended": "(suspended {suspended})",

    # activity_panel view header
    "widget.view_header": "── {view}{pin} ──",

    # ── splash ────────────────────────────────────────────────────────────────

    "widget.splash_subtitle": "hundred-eyed agent · v{version} · {model_label} · ",
    "widget.splash_hint": "type a goal to begin · / for commands · Esc to interrupt · ^C to quit",
    "widget.splash_badge_demo": "DEMO scripted",
    "widget.splash_badge_no_key": "no key · /setup",
    "widget.splash_badge_live": "LIVE",
    "widget.splash_bad_config_permissions": "permissions",
    "widget.splash_bad_config_lsp": "LSP",
    "widget.splash_bad_config_hooks": "hooks",
    "widget.splash_bad_config_suffix": " disabled ({reason})",

    # ── top_bar badges ────────────────────────────────────────────────────────

    "widget.badge_plan": "plan",
    "widget.badge_yolo": "YOLO",
    "widget.badge_demo": "DEMO scripted",
    "widget.badge_no_key": "no key",
    "widget.badge_live": "LIVE",

    # ── dream_report ──────────────────────────────────────────────────────────

    "widget.dream_echo": "› /dream",
    "widget.dream_caption": "executable content taken verbatim from runs · the model writes only the narrative",
    "widget.dream_footer": "fail-safe by design · every suggestion needs your confirmation · argos/learning/dream",
    "widget.dream_report_title": "─ report",
    "widget.dream_row_b": "consolidation units {units} · ",
    "widget.dream_promoted": "promoted {promoted}",
    "widget.dream_rejected": "rejected {rejected}",
    "widget.dream_skipped": "skipped {skipped}",
    "widget.dream_row_c": "memory merged {memory_merged} · archived {memory_archived}",
    "widget.dream_row_d": "promoted: {promoted_name} (synthesized from verified runs)",

    # dream stage labels
    "widget.dream_stage_scan": "candidates",
    "widget.dream_stage_cluster": "",
    "widget.dream_stage_synthesize": "",
    "widget.dream_stage_promote": "A/B promotion gate",
    "widget.dream_stage_memory": "memory consolidation",
    "widget.dream_stage_done": "",

    # ── orders_panel ──────────────────────────────────────────────────────────

    "widget.orders_empty": "no standing orders",
    "widget.orders_footer_left": "cron-lite scheduling · file-trigger watch",
    "widget.orders_footer_right": "argos/conductor",

    # conductor suggestion choice
    "widget.conductor_title": "◔ proactive suggestion · awaiting confirmation",
    "widget.conductor_body_suggest": "suggests → {goal}",
    "widget.conductor_body_confirm_invariant": "requires_confirmation = true · never runs on its own",
    "widget.conductor_option_confirm": "confirm  /confirm {sid8}",
    "widget.conductor_option_dismiss": "dismiss  /dismiss {sid8}",
    "widget.conductor_hint": "↑↓ select · ↵ confirm · digit to pick · Esc to dismiss",
    "widget.conductor_action_label": "proactive suggestion",

    # ── routing_table ─────────────────────────────────────────────────────────

    "widget.routing_caption": "per-task routing · 8 categories · cheap / default / strong",
    "widget.routing_set_hint": "/routing set <category> <tier> to change",
    "widget.routing_footer_left": "heuristic categorization · 0 tokens · falls back to simple_read",
    "widget.routing_footer_module": "argos/routing",
    "widget.routing_history_header": "[last 10 decisions]",
    "widget.routing_no_history": "(none yet; no model calls this run)",
    "widget.routing_force_confirm": "  ❂ force confirm",

    # ── workflow_panel ────────────────────────────────────────────────────────

    # phase labels (rendered as on-screen status text per sub-agent row)
    "widget.phase_plan": "planning",
    "widget.phase_act": "acting",
    "widget.phase_verify": "verifying",
    "widget.phase_report": "summarising",
    "widget.phase_done": "done",
    "widget.phase_error": "failed",

    # workflow panel title and completion suffix
    "widget.workflow_title": "workflow: {name}",
    "widget.workflow_title_done": "workflow: {name} (done)",
    "widget.workflow_synthesis_label": "\n  ─ synthesis:",

    # ── inline_choice ─────────────────────────────────────────────────────────

    # approval title base  ◓ approval request [{risk}]
    "widget.approval_title_base": "◓ approval request [{risk}]",
    # secret-hit sub-label  ⚠︎ secret pattern matched {key_name}
    "widget.approval_secret_hit": "{_WARNING_SIGN} secret pattern matched {key_name}",
    # error when options is empty
    "widget.choice_empty": "InlineChoice requires at least one option",
    # feedback input placeholder
    "widget.choice_input_placeholder": "add feedback, Enter to submit, Esc to cancel",
    # hint line fragments
    "widget.choice_hint_base": "↑↓ select · ↵ confirm · digit to pick",
    "widget.choice_hint_esc": " · Esc to deny",
    # decision summary line  ◕ approved {action} → {value}
    "widget.choice_summary": "◕ approved {action} → {value}",

    # ── code_action ───────────────────────────────────────────────────────────

    # code block fold indicator  … +N lines
    "widget.code_fold": "… +{n} lines",
    # initial running state
    "widget.code_running": "└ running…",
    # return value prefix in result
    "widget.code_return_value": "\n[return value] {repr}",
    # result text when no output
    "widget.code_done": "done",
    "widget.code_error": "error",
    # traceback internal frame fold  … (N lines of internal stack folded)
    "widget.code_stack_folded": "… ({n} lines of internal stack folded)",

    # ── ledger/summary ────────────────────────────────────────────────────────

    "ledger.summary_write_lines": "wrote {path} (+{lines} lines)",
    "ledger.summary_write": "wrote {path}",
    "ledger.summary_edit_diff": "edited {path} (+{added}/-{removed} lines)",
    "ledger.summary_edit": "edited {path}",
    "ledger.summary_read": "read {path}",
    "ledger.summary_delete": "deleted {path}",
    "ledger.summary_listdir": "listed directory {path}",
    "ledger.summary_mkdir": "created directory {path}",
    "ledger.summary_shell_cmd": "ran command: {cmd}",
    "ledger.summary_shell": "ran a shell command",
    "ledger.summary_get": "sent GET request: {url}",
    "ledger.summary_search_q": "searched: {q}",
    "ledger.summary_search": "sent a web search",
    "ledger.summary_post": "sent POST request: {url}",
    "ledger.summary_navigate": "browser navigated to: {url}",
    "ledger.summary_click_target": "clicked: {target}",
    "ledger.summary_click": "browser click",
    "ledger.summary_fill": "filled {selector}: {value}",
    "ledger.summary_fill_no_sel": "browser input",
    "ledger.summary_screenshot": "captured browser screenshot",
    "ledger.summary_unknown": "executed {action}",
    "ledger.summary_url_unknown": "(url unknown)",
    "ledger.summary_file_unknown": "file",
    "ledger.summary_dir_unknown": ".",
}

ZH: dict[str, str] = {
    # verdict_badge — no_test state (CONTRACT A)
    "verdict.no_test_line": "○ 未机检 · 无 verify · {detail}",

    # verdict_badge — self-verified (weak pass, contract 10)
    "verdict.self_verified_line1": "◍ 自验证通过(较弱) · {cmd} → {detail}",
    "verdict.self_verified_line2": "  ⤷ 非用户级 verify,未晋级技能",

    # verdict_badge — passed (strong)
    "verdict.passed_attempts": "{attempts} 次尝试",
    "verdict.passed_line": "◉ verify passed · {cmd} · {attempts_str} → {detail}",

    # verdict_badge — failed
    "verdict.failed_line1": "◉ verify FAILED · {cmd} → {detail}",
    "verdict.failed_line2": "  ⤷ 重试 {attempts} 次后仍 failed",

    # verdict_badge — unverifiable (tampered)
    "verdict.unverifiable_tampered": "◔ 无法验证 · 受保护文件被改 {tampered} → {detail}",
    # verdict_badge — unverifiable (plain)
    "verdict.unverifiable": "◔ 无法验证 · {cmd} · {detail}",

    # ── trust_dial ────────────────────────────────────────────────────────────

    # title line
    "trust.title_prefix": "信任拨盘 · 当前 ",
    "trust.title_level_suffix": "（{short}）",

    # five dial rows: (label, hint)
    "trust.l0_label": "每一步都问我",
    "trust.l0_hint": "全量确认(含只读)",
    "trust.l1_label": "只有危险操作才问",
    "trust.l1_hint": "高风险暂停 · 低风险放行",
    "trust.l2_label": "只有不可逆操作才问",
    "trust.l2_hint": "依赖能力 reversible 字段",
    "trust.l3_label": "同类批准后本会话放行",
    "trust.l3_hint": "= ACCEPT_EDITS 扩展",
    "trust.l4_label": "全自治",
    "trust.l4_hint_red": "⏻ 红灯",
    "trust.l4_hint_rest": " · HARD RULES 仍拦",

    # hard-rules footer line
    "trust.hard_rules_prefix": "HARD RULES 永不降级:",
    "trust.hard_rules_shell": "危险 shell",
    "trust.hard_rules_sep": " · ",
    "trust.hard_rules_path": "系统路径",
    "trust.hard_rules_secret": "secret 检测",

    # provenance footer
    "trust.footer_provenance": "升档必带警示 · 绝不静默自动升",
    "trust.footer_module": "permissions/trust_dial",

    # ── ledger_table ──────────────────────────────────────────────────────────

    # header
    "ledger.header": "行为账本 · run {run_id} · {n} 条",

    # column headers (exact cell text — verbatim from source)
    "ledger.col_seq": "seq ",
    "ledger.col_action": "动作 · 人话",
    "ledger.col_risk": "  风险 ",
    "ledger.col_rev": "  可逆  ",
    "ledger.col_undo": "  撤销      ",
    "ledger.col_sig": "  签名",

    # ── hard_confirm_card ─────────────────────────────────────────────────────

    # title
    "hardconfirm.title": "⛔ 计算机控制 · 硬确认 [high · 不可逆]",

    # option labels
    "hardconfirm.option_once": "仅此一次",
    "hardconfirm.option_deny": "拒绝",

    # governance annotation
    "hardconfirm.governance": (
        "Seatbelt 无法约束全局屏幕/鼠标资源 — 审批门、账本、审计是唯一治理层"
    ),

    # footer invariant
    "hardconfirm.footer": (
        "每个 computer.* 动作恒 risk=high + reversible=False · 不受 Trust Dial 降级"
    ),

    # finish summary line
    "hardconfirm.finish_summary": "◕ 审批 {action_label} → {value}",

    # ── activity_panel section titles ─────────────────────────────────────────

    "widget.section_model": "模型",
    "widget.section_progress": "任务进度",
    "widget.section_tools": "工具",
    "widget.section_receipt": "回执",
    "widget.section_run": "Run",
    "widget.section_skill_catalog": "Skill Catalog",
    "widget.section_mcp": "MCP",
    "widget.section_hook": "Hook",
    "widget.section_lsp": "LSP",
    "widget.section_skill": "Skill",
    "widget.section_approval": "Approval",
    "widget.section_verdict": "Verdict",
    "widget.section_cost": "成本 + 缓存",
    "widget.section_context": "上下文",

    # activity_panel body strings
    "widget.progress_pending": "(待开始)",
    "widget.tools_zero": "本轮 0 调用",
    "widget.tools_this_run": "本轮调用:\n{tools}",
    "widget.empty": "◌ (无)",
    "widget.progress_todo": "进度 {done}/{total}",
    "widget.skills_none": "无可用",
    "widget.skills_available": "{n} 个可用(按任务召回)",
    "widget.mcp_unconfigured": "未配置",
    "widget.mcp_configured": "{n} 个已配置",
    "widget.cache_hit_line": "缓存命中 {cache_read} tok  {elapsed_s:.1f}s",
    "widget.compacted_line": "↯ 已压缩 -{reduction_pct:.0f}% · {before}→{after} 条",
    "widget.pruned_line": "↯ 已修剪 {removed} 条 · {before}→{after}",
    "widget.memory_recall": "◌ 召回 {hits} 条",
    "widget.run_suspended": "(suspended {suspended})",

    # activity_panel view header
    "widget.view_header": "── {view}{pin} ──",

    # ── splash ────────────────────────────────────────────────────────────────

    "widget.splash_subtitle": "百眼智能体 · v{version} · {model_label} · ",
    "widget.splash_hint": "输入目标开始 · / 命令 · Esc 打断 · ^C 退出",
    "widget.splash_badge_demo": "DEMO 脚本演示",
    "widget.splash_badge_no_key": "未配 key · /setup",
    "widget.splash_badge_live": "LIVE",
    "widget.splash_bad_config_permissions": "permissions",
    "widget.splash_bad_config_lsp": "LSP",
    "widget.splash_bad_config_hooks": "hooks",
    "widget.splash_bad_config_suffix": " 已禁用({reason})",

    # ── top_bar badges ────────────────────────────────────────────────────────

    "widget.badge_plan": "plan",
    "widget.badge_yolo": "YOLO",
    "widget.badge_demo": "DEMO 脚本演示",
    "widget.badge_no_key": "未配 key",
    "widget.badge_live": "LIVE",

    # ── dream_report ──────────────────────────────────────────────────────────

    "widget.dream_echo": "› /dream",
    "widget.dream_caption": "可执行内容逐字来自源材料 · 模型只写叙述",
    "widget.dream_footer": "失败安全降级 · 全建议需用户确认 · argos/learning/dream",
    "widget.dream_report_title": "─ 报告",
    "widget.dream_row_b": "整合单元 {units} · ",
    "widget.dream_promoted": "晋升 {promoted}",
    "widget.dream_rejected": "驳回 {rejected}",
    "widget.dream_skipped": "跳过 {skipped}",
    "widget.dream_row_c": "记忆合并 {memory_merged} · 归档 {memory_archived}",
    "widget.dream_row_d": "晋升:{promoted_name}(综合自已验证 run)",

    # dream stage labels
    "widget.dream_stage_scan": "候选区",
    "widget.dream_stage_cluster": "",
    "widget.dream_stage_synthesize": "",
    "widget.dream_stage_promote": "A/B 晋升门",
    "widget.dream_stage_memory": "记忆整理",
    "widget.dream_stage_done": "",

    # ── orders_panel ──────────────────────────────────────────────────────────

    "widget.orders_empty": "无常驻指令",
    "widget.orders_footer_left": "cron-lite 调度 · 文件触发监视",
    "widget.orders_footer_right": "argos/conductor",

    # conductor suggestion choice
    "widget.conductor_title": "◔ 主动建议 · 待确认",
    "widget.conductor_body_suggest": "建议执行 → {goal}",
    "widget.conductor_body_confirm_invariant": "requires_confirmation = true · 绝不自动执行",
    "widget.conductor_option_confirm": "确认执行  /confirm {sid8}",
    "widget.conductor_option_dismiss": "忽略      /dismiss {sid8}",
    "widget.conductor_hint": "↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 忽略",
    "widget.conductor_action_label": "主动建议",

    # ── routing_table ─────────────────────────────────────────────────────────

    "widget.routing_caption": "按任务路由 · 8 类别 · cheap / default / strong",
    "widget.routing_set_hint": "/routing set <类别> <档位> 修改",
    "widget.routing_footer_left": "启发式分类 · 0 token · 异常兜底 simple_read",
    "widget.routing_footer_module": "argos/routing",
    "widget.routing_history_header": "[最近 10 步决策]",
    "widget.routing_no_history": "(无;本 run 尚未调模型)",
    "widget.routing_force_confirm": "  ❂ force confirm",

    # ── workflow_panel ────────────────────────────────────────────────────────

    "widget.phase_plan": "规划",
    "widget.phase_act": "执行",
    "widget.phase_verify": "验证",
    "widget.phase_report": "汇总",
    "widget.phase_done": "完成",
    "widget.phase_error": "失败",

    "widget.workflow_title": "工作流:{name}",
    "widget.workflow_title_done": "工作流:{name}(完成)",
    "widget.workflow_synthesis_label": "\n  ─ 综合结论:",

    # ── inline_choice ─────────────────────────────────────────────────────────

    "widget.approval_title_base": "◓ 审批请求 [{risk}]",
    "widget.approval_secret_hit": "{_WARNING_SIGN} 命中密钥模式 {key_name}",
    "widget.choice_empty": "InlineChoice 至少需要一个选项",
    "widget.choice_input_placeholder": "补充反馈,Enter 提交,Esc 返回",
    "widget.choice_hint_base": "↑↓ 选择 · ↵ 确认 · 数字直选",
    "widget.choice_hint_esc": " · Esc 拒绝",
    "widget.choice_summary": "◕ 审批 {action} → {value}",

    # ── code_action ───────────────────────────────────────────────────────────

    "widget.code_fold": "… +{n} 行",
    "widget.code_running": "└ 运行中…",
    "widget.code_return_value": "\n[返回值] {repr}",
    "widget.code_done": "执行完成",
    "widget.code_error": "执行异常",
    "widget.code_stack_folded": "… ({n} 行内部堆栈已折叠)",

    # ── ledger/summary ────────────────────────────────────────────────────────

    "ledger.summary_write_lines": "写入了 {path}(+{lines} 行)",
    "ledger.summary_write": "写入了 {path}",
    "ledger.summary_edit_diff": "编辑了 {path}(+{added}/-{removed} 行)",
    "ledger.summary_edit": "编辑了 {path}",
    "ledger.summary_read": "读取了 {path}",
    "ledger.summary_delete": "删除了 {path}",
    "ledger.summary_listdir": "列出了目录 {path}",
    "ledger.summary_mkdir": "创建了目录 {path}",
    "ledger.summary_shell_cmd": "跑了命令: {cmd}",
    "ledger.summary_shell": "跑了 shell 命令",
    "ledger.summary_get": "发出了 GET 请求: {url}",
    "ledger.summary_search_q": "搜索了: {q}",
    "ledger.summary_search": "发出了网络搜索",
    "ledger.summary_post": "发出了 POST 请求: {url}",
    "ledger.summary_navigate": "浏览器导航至: {url}",
    "ledger.summary_click_target": "点击了: {target}",
    "ledger.summary_click": "浏览器点击操作",
    "ledger.summary_fill": "填写了 {selector}: {value}",
    "ledger.summary_fill_no_sel": "浏览器输入操作",
    "ledger.summary_screenshot": "截取了浏览器截图",
    "ledger.summary_unknown": "执行了 {action}",
    "ledger.summary_url_unknown": "(url 未知)",
    "ledger.summary_file_unknown": "文件",
    "ledger.summary_dir_unknown": ".",
}
