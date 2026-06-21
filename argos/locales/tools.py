"""tools/* + plan_mode 用户可见文案 (Wave 2c).

key 命名空间: tools.* / plan.*
ZH 值 = 重构前的原始串 verbatim (一字不差)。
EN 值 = 语义对等的自然英文,以 "Error:" 开头对应 ZH "错误:" 开头。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── tools/__init__.py ─────────────────────────────────────────────────────

    # propose_workflow
    "tools.propose_workflow.registered": (
        "[Workflow \"{name}\" registered: {n} stage(s), pending approval and execution]"
    ),

    # propose_verify
    "tools.propose_verify.registered": (
        "Verification command registered: {command}"
        " (will be run independently by harness at wrap-up, exit code is verdict)"
    ),

    # propose_dom_verify
    "tools.propose_dom_verify.registered": (
        "[DOM verification registered: {parts}"
        " (host-side DomProber asserts at wrap-up; three-state verdict)]"
    ),

    # propose_gui_verify
    "tools.propose_gui_verify.registered": (
        "[GUI verification registered: expected_text={expected_text!r}"
        " (host-side GuiProber takes screenshot+OCR at wrap-up; three-state verdict)]"
    ),

    # update_plan
    "tools.update_plan.registered": (
        "Task list updated ({n} item(s); activity panel will render progress)."
    ),

    # plan-mode guard (module-level dispatcher)
    "tools.plan_mode.blocked": (
        "Error: sandbox tools are not allowed in plan mode"
        " (use ExitPlanMode first)."
    ),

    # broker not initialized
    "tools.broker.uninitialized": (
        "Error: broker not initialized"
        " (module-level dispatcher is only for plan_mode unit tests)."
    ),

    # ── tools/shell.py ────────────────────────────────────────────────────────

    "tools.shell.parse_error": "Error: command parse failed {exc}",
    "tools.shell.empty_command": "Error: empty command.",
    "tools.shell.no_backend_linux": (
        "Error: no sandbox backend available on this platform"
        " (bwrap / unshare not found in PATH)"
        " — refusing to run shell command uncaged."
        " Install bwrap (bubblewrap) or unshare and retry."
    ),
    "tools.shell.no_backend_platform": (
        "Error: no sandbox backend available on platform {platform!r}"
        " — refusing to run shell command uncaged."
        " Argos supports macOS (Seatbelt) and Linux (bwrap/unshare) only."
    ),
    "tools.shell.timeout": "Error: command timed out (60s).",
    "tools.shell.exec_failed": "Error: execution failed {exc}",

    # ── tools/files.py ────────────────────────────────────────────────────────

    # read_file errors
    "tools.files.read.outside_workspace": (
        "Error: path {path!r} escapes the workspace; access denied."
    ),
    "tools.files.read.not_found": "Error: file {path!r} does not exist.",
    "tools.files.read.offset_negative": (
        "Error: offset must be ≥ 0 (got {offset})."
    ),
    "tools.files.read.limit_invalid": (
        "Error: limit must be a positive integer or None (got {limit})."
    ),
    "tools.files.read.failed": "Error: read failed {exc}",
    "tools.files.read.offset_oob": (
        "Error: offset out of bounds (file has {total} lines, offset={offset})."
    ),
    "tools.files.read.header": "{path}: lines {start}–{end} / {total} total\n{chunk}",

    # write_file
    "tools.files.write.outside_workspace": (
        "Error: path {path!r} escapes the workspace; write denied."
    ),
    "tools.files.write.failed": "Error: write failed {exc}",
    "tools.files.write.ok": "Written {path} ({nbytes} chars).",

    # edit_file errors
    "tools.files.edit.outside_workspace": (
        "Error: path {path!r} escapes the workspace; edit denied."
    ),
    "tools.files.edit.not_found": "Error: file {path!r} does not exist.",
    "tools.files.edit.ambiguous": (
        "Error: old string matched {count} times (must be unique);"
        " provide more context."
    ),
    "tools.files.edit.too_many": (
        "Error: too many matches ({count}>{cap}); provide more context."
    ),
    "tools.files.edit.ok_n": "Edited {path} ({count} occurrence(s)).",
    "tools.files.edit.ok_1_all": "Edited {path} (1 occurrence).",
    "tools.files.edit.ok_unique": "Edited {path}.",
    "tools.files.edit.not_found_fuzzy": (
        "Error: replacement target not found."
    ),
    "tools.files.edit.ambiguous_fuzzy": (
        "Error: old string fuzzy-matched {count} time(s) (must be unique);"
        " provide more context."
    ),
    "tools.files.edit.too_many_fuzzy": (
        "Error: too many fuzzy matches ({count}>{cap}); provide more context."
    ),
    "tools.files.edit.ok_n_fuzzy": "Edited {path} ({count} occurrence(s), fuzzy match).",
    "tools.files.edit.ok_1_fuzzy": "Edited {path} (1 occurrence, fuzzy match).",

    # search_files
    "tools.files.search.regex_error": "Error: invalid regex {exc}",
    "tools.files.search.no_match_timeout": (
        "Search timed out (some directories not fully scanned, no matches)."
    ),
    "tools.files.search.no_match": "No matches.",
    "tools.files.search.truncated_suffix": "first {limit}",
    "tools.files.search.timeout_suffix": "timed out {deadline}s, results may be incomplete",

    # ── tools/web.py ──────────────────────────────────────────────────────────

    "tools.web.unknown_error": "unknown error",
    "tools.web.search_failed": "Search failed: {error}",
    "tools.web.search_no_results": "No search results.",
    "tools.web.extract_failed": "Fetch failed: {error}",
    "tools.web.extract_empty": "(page has no extractable body text)",
    "tools.web.extract_truncated": "\n…(body text is {total} chars, truncated)",

    # ── plan_mode.py ──────────────────────────────────────────────────────────

    "plan.enter.busy": (
        "Error: a run is currently active — press Esc to interrupt, then /plan."
    ),
    "plan.enter.already": "Already in plan mode.",
    "plan.enter.ok": "Switched to plan mode.",

    "plan.decision.invalid_action": (
        "PlanExitDecision.action must be one of {valid}, got {action!r}"
    ),
    "plan.exit.not_in_plan": "Error: not currently in plan mode.",
    "plan.exit.refine_no_feedback": "Error: refine requires feedback.",
    "plan.exit.invalid_action": "Error: {exc}",
    "plan.exit.ok": "Exited plan mode, action={action}.",

    # PlanRenderer section headers / approval labels
    "plan.render.tasks": "## Task Breakdown",
    "plan.render.no_tasks": "- (no specific task breakdown)",
    "plan.render.files": "## Files Involved",
    "plan.render.risks": "## Risks",
    "plan.render.tool_calls": "## Tool Call Sequence",
    "plan.render.approval": "## Approval",
    "plan.render.approval_prompt": "Choose next step:",
    "plan.render.approve_start": (
        "- ✅ **Approve and start** — full permissions, continue act"
    ),
    "plan.render.approve_edits": (
        "- ✏️ **Approve and accept edits**"
        " — write/edit tools auto-approved, others follow current approval"
    ),
    "plan.render.keep_planning": (
        "- \U0001f504 **Keep planning** — stay in plan phase"
    ),
    "plan.render.refine": (
        "- \U0001f4dd **Refine with feedback**"
        " — provide extra context and re-plan"
    ),
}

ZH: dict[str, str] = {
    # ── tools/__init__.py ─────────────────────────────────────────────────────

    "tools.propose_workflow.registered": (
        "[已登记工作流「{name}」:{n} 个 stage,待审批后执行]"
    ),

    "tools.propose_verify.registered": (
        "已登记验证命令:{command}(收尾时由 harness 独立运行,以退出码为准)"
    ),

    "tools.propose_dom_verify.registered": (
        "[已登记 DOM 验证: {parts}（host 侧 DomProber 收尾时断言，以三态为准）]"
    ),

    "tools.propose_gui_verify.registered": (
        "[已登记 GUI 验证: expected_text={expected_text!r}（host 侧 GuiProber 收尾时截图+OCR 断言，以三态为准）]"
    ),

    "tools.update_plan.registered": (
        "已更新任务清单({n} 项,活动栏将渲染进度)。"
    ),

    "tools.plan_mode.blocked": (
        "错误:plan mode 不允许调沙箱工具(请先 ExitPlanMode 退出)。"
    ),

    "tools.broker.uninitialized": (
        "错误:broker 未初始化(模块级 dispatcher 仅供 plan_mode 单测直调)。"
    ),

    # ── tools/shell.py ────────────────────────────────────────────────────────

    "tools.shell.parse_error": "错误:命令解析失败 {exc}",
    "tools.shell.empty_command": "错误:空命令。",
    "tools.shell.no_backend_linux": (
        "错误:no sandbox backend available on this platform"
        " (bwrap / unshare not found in PATH)"
        " — refusing to run shell command uncaged."
        " Install bwrap (bubblewrap) or unshare and retry."
    ),
    "tools.shell.no_backend_platform": (
        "错误:no sandbox backend available on platform {platform!r}"
        " — refusing to run shell command uncaged."
        " Argos supports macOS (Seatbelt) and Linux (bwrap/unshare) only."
    ),
    "tools.shell.timeout": "错误:命令超时(60s)。",
    "tools.shell.exec_failed": "错误:执行失败 {exc}",

    # ── tools/files.py ────────────────────────────────────────────────────────

    "tools.files.read.outside_workspace": (
        "错误:路径 {path!r} 越出 workspace,拒绝访问。"
    ),
    "tools.files.read.not_found": "错误:文件 {path!r} 不存在。",
    "tools.files.read.offset_negative": (
        "错误:offset 须 ≥ 0(收到 {offset})。"
    ),
    "tools.files.read.limit_invalid": (
        "错误:limit 须为正整数或 None(收到 {limit})。"
    ),
    "tools.files.read.failed": "错误:读取失败 {exc}",
    "tools.files.read.offset_oob": (
        "错误:offset 越界(文件共 {total} 行,offset={offset})。"
    ),
    "tools.files.read.header": "{path}: 第 {start}–{end} 行 / 共 {total} 行\n{chunk}",

    # write_file
    "tools.files.write.outside_workspace": (
        "错误:路径 {path!r} 越出 workspace,拒绝写入。"
    ),
    "tools.files.write.failed": "错误:写入失败 {exc}",
    "tools.files.write.ok": "已写入 {path}({nbytes} 字符)。",

    # edit_file errors
    "tools.files.edit.outside_workspace": (
        "错误:路径 {path!r} 越出 workspace,拒绝编辑。"
    ),
    "tools.files.edit.not_found": "错误:文件 {path!r} 不存在。",
    "tools.files.edit.ambiguous": (
        "错误:old 串多次匹配({count} 次,需唯一),请给更多上下文。"
    ),
    "tools.files.edit.too_many": (
        "错误:匹配过多({count}>{cap}),请给更多上下文。"
    ),
    "tools.files.edit.ok_n": "已编辑 {path}({count} 处)。",
    "tools.files.edit.ok_1_all": "已编辑 {path}(1 处)。",
    "tools.files.edit.ok_unique": "已编辑 {path}。",
    "tools.files.edit.not_found_fuzzy": "错误:未找到要替换的内容。",
    "tools.files.edit.ambiguous_fuzzy": (
        "错误:old 串模糊匹配了 {count} 次(需唯一),请给更多上下文。"
    ),
    "tools.files.edit.too_many_fuzzy": (
        "错误:匹配过多({count}>{cap}),请给更多上下文。"
    ),
    "tools.files.edit.ok_n_fuzzy": "已编辑 {path}({count} 处,模糊匹配)。",
    "tools.files.edit.ok_1_fuzzy": "已编辑 {path}(1 处,模糊匹配)。",

    # search_files
    "tools.files.search.regex_error": "错误:正则非法 {exc}",
    "tools.files.search.no_match_timeout": (
        "搜索超时(部分目录未扫完,无匹配)。"
    ),
    "tools.files.search.no_match": "没有匹配。",
    "tools.files.search.truncated_suffix": "已截断前 {limit}",
    "tools.files.search.timeout_suffix": "超时 {deadline}s,结果可能不完整",

    # ── tools/web.py ──────────────────────────────────────────────────────────

    "tools.web.unknown_error": "未知错误",
    "tools.web.search_failed": "搜索失败:{error}",
    "tools.web.search_no_results": "没有搜到结果。",
    "tools.web.extract_failed": "取页失败:{error}",
    "tools.web.extract_empty": "(页面无可提取正文)",
    "tools.web.extract_truncated": "\n…(正文共 {total} 字符,已截断)",

    # ── plan_mode.py ──────────────────────────────────────────────────────────

    "plan.enter.busy": (
        "错误:当前 run 正在跑,请先 Esc 打断,再 /plan。"
    ),
    "plan.enter.already": "已在 plan mode。",
    "plan.enter.ok": "已切到 plan mode。",

    "plan.decision.invalid_action": (
        "PlanExitDecision.action 必须是 {valid} 之一,收到 {action!r}"
    ),
    "plan.exit.not_in_plan": "错误:当前不在 plan mode。",
    "plan.exit.refine_no_feedback": "错误:refine 需要 feedback。",
    "plan.exit.invalid_action": "错误:{exc}",
    "plan.exit.ok": "已退出 plan mode,action={action}。",

    # PlanRenderer section headers / approval labels
    "plan.render.tasks": "## 任务分解",
    "plan.render.no_tasks": "- (无具体任务分解)",
    "plan.render.files": "## 涉及文件",
    "plan.render.risks": "## 风险",
    "plan.render.tool_calls": "## 工具调用序列",
    "plan.render.approval": "## 审批",
    "plan.render.approval_prompt": "请选择下一步:",
    "plan.render.approve_start": (
        "- ✅ **Approve and start** — 全权限,继续 act"
    ),
    "plan.render.approve_edits": (
        "- ✏️ **Approve and accept edits** — 写/编辑工具自动批,其他按现有审批"
    ),
    "plan.render.keep_planning": (
        "- \U0001f504 **Keep planning** — 继续 plan 阶段"
    ),
    "plan.render.refine": (
        "- \U0001f4dd **Refine with feedback** — 提供补充上下文后重新 plan"
    ),
}
