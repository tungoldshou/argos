"""Workflow cluster i18n catalog — wf.* namespace.

Covers: argos/workflow/spec.py, engine.py, result.py, subagent.py, worktree.py.

ZH values = verbatim original Chinese strings (so ARGOS_LANG=zh legacy assertions pass).
EN values = natural, precise English matching the README tone.
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── spec.py: role system prompts ─────────────────────────────────────────
    "wf.role.explorer.system_prompt": (
        "You are in the explorer (read-only reconnaissance) role.\n"
        "- You may only read files, search, query the web, and inspect the browser; "
        "you may NOT write files, modify code, or run state-changing commands.\n"
        "- Your job is to gather intelligence and locate code — not to produce final changes.\n"
        "- If you need to write, tell the caller to give you the coder role "
        "(the sub-agent sandbox does not grant you write tools)."
    ),
    "wf.role.planner.system_prompt": (
        "You are in the planner role.\n"
        "- Produce a plan only — do not execute; "
        "sandbox tools in plan mode are intercepted by the dispatcher (see plan_mode.py).\n"
        "- Your output = a plan for the parent agent to review "
        "(plain text steps/trade-offs — do not call workflow tools).\n"
        "- Do not pretend you have executed anything — the sandbox is a separate subprocess; "
        "the parent cannot access your local state."
    ),
    "wf.role.coder.system_prompt": (
        "You are in the coder role.\n"
        "- You have all write tools (write_file/edit_file/run_command + browser writes + mcp_call).\n"
        "- Before finishing, you MUST call propose_verify('<test/compile/lint command>') "
        "to declare real verification; the host will run it independently.\n"
        "- Without a verify declaration the run is marked 'NO_TEST' (unverified) — never faked as passed.\n"
        "- Anti-tamper: verify runs in an isolated verify_dir you cannot touch; "
        "modifying the tests that judge you will not produce a false green."
    ),
    "wf.role.reviewer.system_prompt": (
        "You are in the reviewer role.\n"
        "- Tool set = explorer + run_command + lsp_diagnostics (read + run checks).\n"
        "- You may NOT write files or edit code; your output = a review report "
        "(specific file: line number + issue).\n"
        "- Goes through the verify gate: automatically includes detect_tampering "
        "(test modified → unverifiable, never faked as passed).\n"
        "- When running tests/lint, declare via propose_verify; "
        "the host runs it independently with exit code as verdict."
    ),

    # ── spec.py: _parse_agent errors ─────────────────────────────────────────
    "wf.spec.agent_missing_prompt": "agent is missing 'prompt'",
    "wf.spec.invalid_tool_scope": "invalid tool_scope: {scope!r} (allowed: {scopes})",
    "wf.spec.invalid_isolation": "invalid isolation: {iso!r}",
    "wf.spec.invalid_role": "invalid role: {role!r} (allowed: {roles})",
    "wf.spec.role_scope_conflict": (
        "role={role!r} conflicts with tool_scope={scope!r} "
        "(role implies read_only={role_read_only}, "
        "tool_scope=read implies read_only={scope_read_only})"
    ),
    "wf.spec.trivial_verify": (
        "stage verify cannot be a trivial command "
        "(always passes, verifies nothing): {verify!r}"
    ),

    # ── spec.py: parse_spec errors ────────────────────────────────────────────
    "wf.spec.not_a_dict": "spec must be a dict",
    "wf.spec.missing_name": "spec is missing 'name'",
    "wf.spec.missing_stages": "spec is missing non-empty 'stages'",
    "wf.spec.too_many_stages": "too many stages (> {max_stages})",
    "wf.spec.stage_not_a_dict": "stage must be a dict",
    "wf.spec.stage_missing_id": "stage is missing 'id'",
    "wf.spec.duplicate_stage_id": "duplicate stage id: {sid!r}",
    "wf.spec.invalid_op": "invalid op: {op!r} (allowed: {ops})",
    "wf.spec.invalid_over_ref": "over.from references a non-existent or non-earlier stage: {ref!r}",
    "wf.spec.invalid_over": "invalid over: {over!r}",
    "wf.spec.panel_threshold_exceeds_voters": (
        "panel threshold({threshold}) cannot exceed voters({voters})"
    ),
    "wf.spec.best_of_n_invalid": "stage \"{sid}\" best_of_n: invalid n: {n!r}",

    # ── engine.py: panel note ─────────────────────────────────────────────────
    "wf.engine.panel_note": (
        "panel \"{stage_id}\" {yes}/{voters} votes "
        "{op} threshold {threshold} → {verdict}"
    ),
    "wf.engine.panel_passed": "passed",
    "wf.engine.panel_failed": "failed",
    "wf.engine.panel_gte": ">=",
    "wf.engine.panel_lt": "<",

    # ── engine.py: loop_until capped note ────────────────────────────────────
    "wf.engine.loop_until_capped": (
        "loop_until \"{stage_id}\" hit hard round limit {max_rounds} and stopped "
        "(total successes: {ok_total}, target {target} not reached)"
    ),

    # ── engine.py: per-candidate timeout ─────────────────────────────────────
    "wf.engine.candidate_timeout": (
        "per_candidate_timeout: candidate c{idx} exceeded "
        "{timeout}s and was cancelled"
    ),

    # ── engine.py: best_of_n note ─────────────────────────────────────────────
    "wf.engine.best_of_n_note": (
        "best_of_n \"{stage_id}\" N={n} ran {n} candidates, "
        "passed={passed_n} → winner={winner_id}({winner_verdict})"
    ),

    # ── engine.py: _note_failures ─────────────────────────────────────────────
    "wf.engine.failures_note": (
        "stage \"{stage_id}\" {failed}/{total} agents failed "
        "(continuing with remaining results)"
    ),

    # ── engine.py: _synthesize ────────────────────────────────────────────────
    "wf.engine.synthesis_done": "Workflow complete.",
    "wf.engine.synthesis_stage_ok": "{ok}/{total} succeeded",

    # ── result.py: render_preview ─────────────────────────────────────────────
    "wf.result.preview_header": "Workflow \"{name}\" — {description}",
    "wf.result.preview_will_run": "Will execute:",
    "wf.result.preview_scope_write": "write+run",
    "wf.result.preview_scope_read": "read-only",
    "wf.result.preview_worktree_iso": " · worktree isolated",
    "wf.result.preview_stage_line": (
        " · [{op}] {stage_id}: spawn {n} agent(s) "
        "(model {model} · {scope}{iso})"
    ),
    "wf.result.preview_footer": (
        "Total ~{total} sub-agent(s). "
        "After approval, runs automatically within the OS sandbox "
        "(network OFF, writes confined to workspace)."
    ),

    # ── subagent.py: role prefix injected into prompt ─────────────────────────
    "wf.subagent.role_prefix": "[Role: {role_name}]",

    # ── subagent.py: isolation note appended to output ────────────────────────
    "wf.subagent.isolation_note": "\n[Isolation note] {note}",

    # ── subagent.py: diff sections ────────────────────────────────────────────
    "wf.subagent.diff_inline_header": (
        "\n[worktree diff — not auto-merged; please review before applying]\n"
    ),
    "wf.subagent.diff_summary_prefix": "\n[diff summary] {summary}",
    "wf.subagent.diff_ref_prefix": "\n[full diff] {ref}",

    # ── worktree.py: fallback notes ───────────────────────────────────────────
    "wf.worktree.not_git_repo": (
        "workspace is not a git repository; cannot use worktree hard-isolation "
        "→ falling back to shared workspace (parallel writes to the same file may conflict)"
    ),
    "wf.worktree.create_failed": (
        "git worktree creation failed ({error}) "
        "→ falling back to shared workspace"
    ),
}

ZH: dict[str, str] = {
    # ── spec.py: role system prompts ─────────────────────────────────────────
    "wf.role.explorer.system_prompt": (
        "你处于 explorer(只读侦察)角色。\n"
        "- 只能读文件、检索、查网络、看浏览器;不准写文件、不准改代码、不准跑会改状态的命令。\n"
        "- 任务是收集情报与定位代码,不产出最终代码改动。\n"
        "- 若需写,告诉调用方让你走 coder 角色(子 agent 沙箱不给你写工具)。"
    ),
    "wf.role.planner.system_prompt": (
        "你处于 planner(规划)角色。\n"
        "- 只产方案不执行;沙箱工具在 plan mode 会被 dispatcher 拦(plan mode 守卫见 plan_mode.py)。\n"
        "- 你的产出 = 一段可被父 agent 审阅的方案(纯文字步骤/取舍,不要调用工作流工具)。\n"
        "- 不要假装执行了什么 —— 沙箱是独立子进程,parent 拿不到你的本地状态。"
    ),
    "wf.role.coder.system_prompt": (
        "你处于 coder(编码)角色。\n"
        "- 拥有全部写工具(write_file/edit_file/run_command + 浏览器写 + mcp_call)。\n"
        "- 完成前必须 propose_verify('<测试/编译/lint 命令>') 声明真验证;host 会独立跑。\n"
        "- 没声明 verify → 走 'NO_TEST'(未机检验证)诚实路径,绝不会判 passed —— 不会撒谎。\n"
        "- 防篡改:verify 在隔离 verify_dir 跑,你碰不到执行,改了评判你的测试也救不了假绿。"
    ),
    "wf.role.reviewer.system_prompt": (
        "你处于 reviewer(审查)角色。\n"
        "- 工具集 = explorer + run_command + lsp_diagnostics(看 + 跑检查)。\n"
        "- 不准写文件/编辑代码;产出 = 一段审查意见(具体文件:行号 + 问题)。\n"
        "- 走 verify 门:自动接 detect_tampering(测试被改 → unverifiable,不假装通过)。\n"
        "- 跑测试/lint 时用 propose_verify 声明,host 独立跑退出码为准。"
    ),

    # ── spec.py: _parse_agent errors ─────────────────────────────────────────
    "wf.spec.agent_missing_prompt": "agent 缺 prompt",
    "wf.spec.invalid_tool_scope": "非法 tool_scope:{scope!r}(只允许 {scopes})",
    "wf.spec.invalid_isolation": "非法 isolation:{iso!r}",
    "wf.spec.invalid_role": "非法 role:{role!r}(只允许 {roles})",
    "wf.spec.role_scope_conflict": (
        "role={role!r} 与 tool_scope={scope!r} 矛盾"
        "(role 派生 read_only={role_read_only},"
        "tool_scope=read 派生 read_only={scope_read_only})"
    ),
    "wf.spec.trivial_verify": (
        "stage verify 不能是 trivial 命令(永远通过、什么都不验证):{verify!r}"
    ),

    # ── spec.py: parse_spec errors ────────────────────────────────────────────
    "wf.spec.not_a_dict": "spec 必须是 dict",
    "wf.spec.missing_name": "spec 缺 name",
    "wf.spec.missing_stages": "spec 缺非空 stages",
    "wf.spec.too_many_stages": "stages 过多(>{max_stages})",
    "wf.spec.stage_not_a_dict": "stage 必须是 dict",
    "wf.spec.stage_missing_id": "stage 缺 id",
    "wf.spec.duplicate_stage_id": "重复的 stage id:{sid!r}",
    "wf.spec.invalid_op": "非法 op:{op!r}(只允许 {ops})",
    "wf.spec.invalid_over_ref": "over.from 引用了不存在或非更早的 stage:{ref!r}",
    "wf.spec.invalid_over": "非法 over:{over!r}",
    "wf.spec.panel_threshold_exceeds_voters": (
        "panel threshold({threshold})不可大于 voters({voters})"
    ),
    "wf.spec.best_of_n_invalid": "stage「{sid}」best_of_n 的 n 非法:{n!r}",

    # ── engine.py: panel note ─────────────────────────────────────────────────
    "wf.engine.panel_note": (
        "panel「{stage_id}」{yes}/{voters} 票 "
        "{op} 阈值 {threshold} → {verdict}"
    ),
    "wf.engine.panel_passed": "通过",
    "wf.engine.panel_failed": "未通过",
    "wf.engine.panel_gte": "≥",
    "wf.engine.panel_lt": "<",

    # ── engine.py: loop_until capped note ────────────────────────────────────
    "wf.engine.loop_until_capped": (
        "loop_until「{stage_id}」触硬轮数上限 {max_rounds} 轮停止"
        "(累计成功 {ok_total} 个,未达 target {target})"
    ),

    # ── engine.py: per-candidate timeout ─────────────────────────────────────
    "wf.engine.candidate_timeout": (
        "per_candidate_timeout: 候选 c{idx} 超过 "
        "{timeout}s 未完成,被取消"
    ),

    # ── engine.py: best_of_n note ─────────────────────────────────────────────
    "wf.engine.best_of_n_note": (
        "best_of_n「{stage_id}」N={n} 跑了 {n} 个候选,"
        "passed={passed_n} → winner={winner_id}"
        "({winner_verdict})"
    ),

    # ── engine.py: _note_failures ─────────────────────────────────────────────
    "wf.engine.failures_note": (
        "stage「{stage_id}」{failed}/{total} 个 agent 失败(已带其余结果继续)"
    ),

    # ── engine.py: _synthesize ────────────────────────────────────────────────
    "wf.engine.synthesis_done": "工作流完成。",
    "wf.engine.synthesis_stage_ok": "{ok}/{total} 成功",

    # ── result.py: render_preview ─────────────────────────────────────────────
    "wf.result.preview_header": "工作流「{name}」—— {description}",
    "wf.result.preview_will_run": "将执行:",
    "wf.result.preview_scope_write": "写+跑",
    "wf.result.preview_scope_read": "只读",
    "wf.result.preview_worktree_iso": " · worktree 隔离",
    "wf.result.preview_stage_line": (
        " · [{op}] {stage_id}:起 {n} 个 agent(模型 {model} · {scope}{iso})"
    ),
    "wf.result.preview_footer": (
        "合计约 {total} 个子 agent。"
        "批准后在 OS 沙箱边界内自动执行(网络 OFF、写限工作区)。"
    ),

    # ── subagent.py: role prefix injected into prompt ─────────────────────────
    "wf.subagent.role_prefix": "[角色:{role_name}]",

    # ── subagent.py: isolation note appended to output ────────────────────────
    "wf.subagent.isolation_note": "\n[隔离注记] {note}",

    # ── subagent.py: diff sections ────────────────────────────────────────────
    "wf.subagent.diff_inline_header": (
        "\n[worktree 改动 diff —— 未自动合并,请审阅后应用]\n"
    ),
    "wf.subagent.diff_summary_prefix": "\n[diff 摘要] {summary}",
    "wf.subagent.diff_ref_prefix": "\n[完整 diff] {ref}",

    # ── worktree.py: fallback notes ───────────────────────────────────────────
    "wf.worktree.not_git_repo": (
        "工作区非 git 仓库,无法 worktree 硬隔离 → 退共享工作区(并行写同名文件有撞车风险)"
    ),
    "wf.worktree.create_failed": (
        "git worktree 创建失败({error})→ 退共享工作区"
    ),
}
