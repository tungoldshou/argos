"""TUI app 用户可见串目录 —— TUIAPP lane (tui.* / cmd.* 命名空间)。

ZH 值必须与代码里原有中文字符**逐字相同**（verbatim contract），否则现有 zh 断言失绿。
EN 值为自然英文翻译，匹配 README 的平静、精确风格。
"""
from __future__ import annotations

# ── COMMAND_HELP ─────────────────────────────────────────────────────────────
# cmd.<name> = commands.py COMMAND_HELP 字典的每条描述

EN: dict[str, str] = {
    # ── COMMAND_HELP entries ──────────────────────────────────────────────────
    "cmd.help":             "Show all commands",
    "cmd.setup":            "Show config wizard entry (run argos setup after exiting TUI)",
    "cmd.tools":            "List callable tools",
    "cmd.skills":           "Manage skill ecosystem: list/install/remove/refresh/test (runs argos skills ...)",
    "cmd.mcp":              "List MCP external tools",
    "cmd.model":            "View / switch model",
    "cmd.status":           "Current run status",
    "cmd.cost":             "Current round cost + cache",
    "cmd.resume":           "Resume last session",
    "cmd.clear":            "Start new session (clear)",
    "cmd.yolo":             "Run without approval (legacy; same as /trust autonomous)",
    "cmd.trust":            "View / switch trust mode (/trust [cautious|trusted|autonomous|status]) — replaces /yolo",
    "cmd.undo":             "Undo file changes from this round (restore to run start)",
    "cmd.ledger":           "View behavior ledger for current run (plain-language entries + undo status)",
    "cmd.journal":          "Show ledger JSONL path (/journal [run_id])",
    "cmd.retry":            "Resend last user message",
    "cmd.plan":             "Enter plan mode (approve then continue act) — aligns with CC /plan",
    "cmd.hooks":            "List / reload hooks config (/hooks, /hooks reload)",
    "cmd.lsp":              "List / reload LSP config (/lsp, /lsp reload)",
    "cmd.permissions":      "View / reload permissions config (/permissions, /permissions reload)",
    "cmd.runs":             "List / background runs (/runs, /runs {id} resume/cancel) — daemon mode",
    "cmd.orders":           "List autonomous standing orders (/orders) — conductor autonomy panel",
    "cmd.confirm":          "Confirm conductor proactive suggestion (/confirm <suggestion_id>) — autonomy panel",
    "cmd.dismiss":          "Dismiss conductor proactive suggestion (/dismiss <suggestion_id>)",
    "cmd.dream":            "Nightly consolidation: run a Dream cycle (cluster + synthesize + memory tidy); /dream status shows the last report",
    "cmd.verify":           "Explicitly run verify_cmd (/verify [path]) — user review of verify gate",
    "cmd.security-review":  "Security audit (secrets + dependency vulnerabilities + dangerous APIs) (/security-review [path])",
    "cmd.simplify":         "Code duplication / complexity / dead code scan (/simplify [path])",
    "cmd.eval":             "Agent self-evaluation + A/B (/eval, /eval run <id>, /eval compare <a> <b>)",
    "cmd.routing":          "View / switch routing config (/routing, /routing set <cat> <tier>)",
    "cmd.context":          "View current LLM context buckets (/context, /context --json)",
    "cmd.loop":             "Run a task repeatedly until a condition is met (/loop <task> [until: <condition>])",
    "cmd.goal":             "Submit a goal with a verify exit condition (/goal <task> | verify: <cmd>)",
    "cmd.schedule":         "Create a timed standing order (/schedule <cron> <task>)",
    "cmd.watch":            "Watch for file changes and trigger a task (/watch <glob> <task>)",

    # ── prompt.py paste / image tokens ───────────────────────────────────────
    "tui.prompt.paste_token": "[pasted text #{n} +{lines} lines]",
    "tui.prompt.image_token": "[image #{n}]",

    # ── slash-menu nav hint (prompt.py SlashMenu._render_items) ──────────────
    "tui.slash_menu.nav_hint": "  ↑↓ select · ↹ complete · ↵ execute",

    # ── status_bar.py hints line ──────────────────────────────────────────────
    "tui.statusbar.hints":        "Esc interrupt · \\↵ newline · ^B background · ^O right panel · ^V paste image · ^C/^D quit",
    "tui.statusbar.blocked_label": "approval pending",
    "tui.statusbar.plan_mode":    "[plan mode]",
    "tui.statusbar.action":       "action {n}",

    # ── daemon / inline system notes (app.py _setup_daemon_mode) ─────────────
    "tui.daemon.unavailable": "daemon unavailable, switched to single-process mode (background / cross-session resume unavailable).",

    # ── /help command response ────────────────────────────────────────────────
    "tui.help.header":    "Commands (type / to list in-place, Tab to complete):",
    "tui.help.shortcuts": (
        "Shortcuts:\n"
        "  Esc / Ctrl+C   interrupt current task\n"
        "  Ctrl+C (idle)  press twice to quit\n"
        "  Ctrl+D         quit\n"
        "  Ctrl+B         background current run (daemon mode)\n"
        "  Ctrl+O         cycle right panel view\n"
        "  Ctrl+V         paste image from clipboard\n"
        "  \\ + Enter      insert newline (multi-line input)\n"
        "  ↑ / ↓          browse input history"
    ),

    # ── /model command ────────────────────────────────────────────────────────
    "tui.model.available":      "Available models: {list}",
    "tui.model.switched":       "Switched to '{name}' (restart argos to take effect).",
    "tui.model.switch_failed":  "Switch failed: {err}",

    # ── /status command ───────────────────────────────────────────────────────
    "tui.cost.header": "Cost + Cache",

    # ── /clear command ────────────────────────────────────────────────────────
    "tui.clear.done": "New session started (clear).",

    # ── unknown command ───────────────────────────────────────────────────────
    "tui.cmd.unknown": "Unknown command /{name}",
    "tui.cmd.unwired": "/{name} is not wired yet — coming in a future batch.",

    # ── /goal and /loop commands ──────────────────────────────────────────────
    "tui.goal.submitted": "Goal submitted with verify: {verify_cmd}",

    # ── /yolo command ────────────────────────────────────────────────────────
    "tui.yolo.activated": (
        "Switched to Autonomous (full autonomy/YOLO) — top bar shows ⏻ YOLO marker."
        " Tip: new usage is /trust autonomous (or /trust with no args to cycle)."
    ),

    # ── /trust command ────────────────────────────────────────────────────────
    "tui.trust.status":        "Current trust mode: {mode_name} ({label_human})\n{description}",
    "tui.trust.unknown_mode":  "Unknown mode '{arg}'. Usage: /trust [cautious|trusted|autonomous|paranoid|status] (no args to cycle)",
    "tui.trust.already":       "Already at {mode_name} ({label_human}), no change needed.",
    "tui.trust.downgraded":    "Switched to {mode_name} ({label_human}).",
    "tui.trust.upgraded":      "Upgraded to {mode_name} ({label_human}).{yolo_note}",
    "tui.trust.yolo_note":     " Top bar shows ⏻ red warning indicator.",
    "tui.trust.cancelled":     "Upgrade cancelled, staying at current level.",
    "tui.trust.confirm_title": "Escalation confirm — switch to {label_human}",
    "tui.trust.confirm_yes":   "Confirm escalation",
    "tui.trust.confirm_no":    "Cancel, stay at current level",

    # ── /undo command ────────────────────────────────────────────────────────
    "tui.undo.no_snapshot":   "Nothing to undo (no run started in this session, or snapshot has been cleaned up).",
    "tui.undo.partial":       "Partial restore (succeeded {ok} / failed {fail}):\n{head}{more}",
    "tui.undo.more":          "\n  …(more omitted)",
    "tui.undo.success":       "Restored {n} file(s) to run start.\nTo continue, /retry to resend the last goal, or enter a new goal.",

    # ── /ledger command ───────────────────────────────────────────────────────
    "tui.ledger.no_ledger":   "No behavior ledger in current session (ledger is only available in daemon mode, or no side-effect actions this run).",
    "tui.ledger.read_failed": "Ledger read failed: {err}",
    "tui.ledger.empty":       "run {run_id} has no ledger entries (no side-effect actions this run).",
    "tui.ledger.all_undone":  "run {run_id} ledger: all actions undone.",
    "tui.ledger.footer":      "Each entry is HMAC-signed · summary template generated without calling model\njournal: {path}  (/journal {run_id} to see path)",

    # ── /setup command ────────────────────────────────────────────────────────
    "tui.setup.hint": (
        "Config Wizard\n"
        "  After exiting TUI run:\n"
        "    argos setup\n"
        "  The wizard will guide you through provider, API key, and connectivity test,\n"
        "  writing results to ~/.argos/.env and ~/.argos/config.json.\n"
        "  You can also manually edit ~/.argos/.env to add ANTHROPIC_API_KEY=... etc."
    ),

    # ── /journal command ──────────────────────────────────────────────────────
    "tui.journal.with_id":   "Ledger JSONL: {path}\n  View: cat {path}\n  Live tail: tail -f {path}",
    "tui.journal.no_id":     "Ledger dir: {dir}\n  No run_id in current session (no run started or not in daemon mode).\n  Usage: /journal <run_id>",

    # ── /retry command ────────────────────────────────────────────────────────
    "tui.retry.busy":           "Press Esc to interrupt the current task first, then /retry.",
    "tui.retry.no_store":       "Current store does not support /retry (demo mode or not injected via build_components).",
    "tui.retry.read_failed":    "Failed to read history: {err}",
    "tui.retry.no_messages":    "No retryable message in current session.",

    # ── /hooks command ────────────────────────────────────────────────────────
    "tui.hooks.reloaded":       "Reloaded hooks config ({n} events).",
    "tui.hooks.reload_failed":  "/hooks reload failed (keeping old config): {err}",
    "tui.hooks.empty":          "No hooks configured (empty ~/.argos/hooks.json or not configured).",
    "tui.hooks.header":         "Current hooks config ({n} events):",
    "tui.hooks.all_match":      "(match all)",

    # ── /lsp command ─────────────────────────────────────────────────────────
    "tui.lsp.reloaded":       "Reloaded LSP config ({n} servers).",
    "tui.lsp.reload_failed":  "/lsp reload failed (keeping old config): {err}",
    "tui.lsp.empty":          "No LSP configured (empty ~/.argos/lsp.json or unreadable → using built-in defaults).",
    "tui.lsp.init_failed":    "LSP manager init failed: {err}",
    "tui.lsp.header":         "Current LSP config ({n} servers):",
    "tui.lsp.diag":           "     diagnostics: {n} entries",

    # ── /permissions command ──────────────────────────────────────────────────
    "tui.permissions.reloaded":     "Reloaded permissions config (allow {allow} / deny {deny} / ask {ask} / per-tool {tools} / default_level={level}).",
    "tui.permissions.reload_failed": "/permissions reload failed (keeping old config): {err}",
    "tui.permissions.read_failed":  "Failed to read permissions config: {err}",
    "tui.permissions.header":       "Current permissions config:",
    "tui.permissions.default_level": " · default_level: {level}",
    "tui.permissions.per_tool":      " · per-tool override: {n} entries",
    "tui.permissions.allow_rules":   " · allow rules: {n} entries",
    "tui.permissions.deny_rules":    " · deny rules: {n} entries",
    "tui.permissions.ask_rules":     " · ask rules: {n} entries",
    "tui.permissions.omitted":       "   …({total} total, {omitted} omitted)",
    "tui.permissions.default_gate":  "(follow gate.level)",

    # ── /tools command ────────────────────────────────────────────────────────
    "tui.tools.header":      "{n} tools in total:",
    "tui.tools.wf_off":      "orchestration (workflow, requires ARGOS_WORKFLOWS=1)",
    "tui.tools.wf_on":       "orchestration (workflow)",
    "tui.tools.group.file":          "File",
    "tui.tools.group.cmd":           "Command/Verify/Plan",
    "tui.tools.group.web":           "Web",
    "tui.tools.group.browser":       "Computer control (browser)",
    "tui.tools.group.external":      "External tools",
    "tui.tools.group.lsp":           "LSP language server",
    "tui.tools.group.os":            "OS-level control (P6a)",

    # ── /runs command ─────────────────────────────────────────────────────────
    "tui.runs.no_daemon":      "daemon not enabled (--with-daemon flag); /runs unavailable.",
    "tui.runs.list_failed":    "Failed to list runs: {err}",
    "tui.runs.empty":          "No runs.",
    "tui.runs.list_header":    "Run list (#5b extended: cost / worktree):",
    "tui.runs.list_footer":    "/runs {id} focus|resume|cancel — control",
    "tui.runs.focus_ok":       "Focused {run_id} (active switched to this run).",
    "tui.runs.focus_failed":   "focus failed: HTTP {status}",
    "tui.runs.focus_readonly": "READ-ONLY observer cannot focus (only owner TUI can switch active).",
    "tui.runs.focus_err":      "focus failed: {err}",
    "tui.runs.resume_ok":      "Resume requested for {run_id}.",
    "tui.runs.resume_failed":  "resume failed: {err}",
    "tui.runs.cancel_ok":      "Cancel requested for {run_id}.",
    "tui.runs.cancel_failed":  "cancel failed: {err}",
    "tui.runs.info_failed":    "Failed to query run: {err}",

    # ── /orders command ───────────────────────────────────────────────────────
    "tui.orders.request_failed": "/orders request failed (daemon): {err}",
    "tui.orders.local_failed":   "Failed to read local orders: {err}",

    # ── /confirm command ──────────────────────────────────────────────────────
    "tui.confirm.no_id":        "Usage: /confirm <suggestion_id>",
    "tui.confirm.no_daemon":    "confirm requires daemon mode (--with-daemon).",
    "tui.confirm.request_failed": "/confirm request failed: {err}",
    "tui.confirm.ok":           "Suggestion confirmed and run created: {run_id}\n  Isolation: worktree={wt}\n  Trust level: L1_DANGEROUS_ONLY (hard-coded, not upgradeable)\n  Use /runs to check run status.",
    "tui.confirm.not_found":    "Suggestion {id!r} not found or already processed (dismissed/confirmed).",
    "tui.confirm.unavailable":  "Cannot confirm: {err}",
    "tui.confirm.failed":       "/confirm failed (HTTP {status}): {err}",

    # ── /dismiss command ──────────────────────────────────────────────────────
    "tui.dismiss.no_id":          "Usage: /dismiss <suggestion_id>",
    "tui.dismiss.no_daemon":      "dismiss requires daemon mode (--with-daemon).",
    "tui.dismiss.request_failed": "/dismiss request failed: {err}",
    "tui.dismiss.ok":             "Suggestion {id!r} dismissed.",
    "tui.dismiss.not_found":      "Suggestion {id!r} not found or already processed.",
    "tui.dismiss.failed":         "/dismiss failed (HTTP {status}): {err}",

    # ── /routing command ──────────────────────────────────────────────────────
    "tui.routing.no_router":     "/routing unavailable (no router injected; demo/fake mode).",
    "tui.routing.set_usage":     "Usage: /routing set <category> <tier>  ({cats} valid categories)",
    "tui.routing.bad_category":  "category '{cat}' does not exist; valid values: {cats}",
    "tui.routing.set_failed":    "/routing set failed: {err}",
    "tui.routing.set_ok":        "Written to {dir}/config.json: routing.by_category.{cat} = {tier}",

    # ── /context command ──────────────────────────────────────────────────────
    "tui.context.failed": "/context failed: {err}",

    # ── /dream command ────────────────────────────────────────────────────────
    "tui.dream.no_daemon":        "Dream requires daemon mode (currently inline).\nHint: restart Argos to auto-connect daemon, or check ~/.argos/daemon.sock.",
    "tui.dream.report_failed":    "/dream report request failed: {err}",
    "tui.dream.no_report":        "No Dream report yet (nightly consolidation has not run).",
    "tui.dream.report_bad_type":  "Dream report format unexpected (expected dict, got {type})",
    "tui.dream.http_failed":      "/dream report failed (HTTP {status})",
    "tui.dream.run_failed":       "/dream/run request failed: {err}",
    "tui.dream.started":          "Dream started · consolidation progress below.",
    "tui.dream.already_running":  "Dream already running, please wait.",
    "tui.dream.start_failed":     "Dream start failed: {msg}",
    "tui.dream.unknown_status":   "/dream/run returned unknown status HTTP {status}: {body}",
    "tui.dream.fmt":              "Dream complete  units={units}  promoted={promoted}  rejected={rejected}  skipped={skipped}  memory_merged={merged}  memory_archived={archived}",

    # ── /remember command ────────────────────────────────────────────────────
    "tui.remember.usage":      "Usage: /remember <content to remember>",
    "tui.remember.duplicate":  "(already up to date — duplicate within 24h / empty / parse failed, skipped)",
    "tui.remember.ok":         "Remembered ({scope}): {value} (id={id}, conf={conf:.2f})",

    # ── /forget command ──────────────────────────────────────────────────────
    "tui.forget.usage":       "Usage: /forget <id or key or text>",
    "tui.forget.not_found":   "No memory matching '{query}' found.",
    "tui.forget.ok":          "Soft-deleted {n} entries:",

    # ── /resume command ───────────────────────────────────────────────────────
    "tui.resume.no_store":       "/resume unavailable (no persistent session).",
    "tui.resume.no_sessions":    "No history sessions available to resume.",
    "tui.resume.ok":             "Session '{title}' resumed, {n} history messages loaded — continue to pick up where you left off.",

    # ── /skills command ───────────────────────────────────────────────────────
    "tui.skills.side_effect_hint": "[skills] TUI does not install side effects directly. Run on host:\n        $ argos skills {sub} {arg}",
    "tui.skills.curator_failed":   "curator not loaded: {err}",

    # ── /mcp command ─────────────────────────────────────────────────────────
    "tui.mcp.query_failed":    "MCP query failed: {err}",
    "tui.mcp.empty":           "No MCP configured, or configured server not connected / no tools.\nConfigure stdio server in ~/.argos/mcp.json to extend tools (zero pre-configured by default).",
    "tui.mcp.header":          "Connected MCP tools: {n}, called via mcp_call(server, tool, arguments):",

    # ── /eval command ─────────────────────────────────────────────────────────
    "tui.eval.no_runs":        "No evals run yet. Try /eval run <task_id> or argos eval corpus",
    "tui.eval.usage":          "Usage: /eval [run <task_id> | compare <a> <b>]",
    "tui.eval.compare_usage":  "Usage: /eval compare <task_id>[:<model>] <task_id>[:<model>]",
    "tui.eval.task_mismatch":  "task_id mismatch: {a} vs {b}",
    "tui.eval.task_not_found": "Task not found: {err}",

    # ── /plan command ─────────────────────────────────────────────────────────
    "tui.plan.factory_failed": "/plan unavailable (loop factory failed): {err}",

    # ── inline / start_run ────────────────────────────────────────────────────
    "tui.run.demo_banner":     "⚠︎ Demo mode: the following is scripted fake data, not real execution/verification (real AgentLoop pending Phase 6).",
    "tui.run.thinking":        "Goal received, thinking…",
    "tui.run.interrupted":     "⎋ Current task interrupted.",
    "tui.run.create_failed":   "◉ daemon create_run failed: {err}",

    # ── Ctrl+C idle hint ──────────────────────────────────────────────────────
    "tui.ctrlc.hint":          "Press Ctrl+C again to quit (or Ctrl+D to quit immediately).",

    # ── background (Ctrl+B) ───────────────────────────────────────────────────
    "tui.background.suspended": "› Run {run_id} backgrounded (suspended). Use /resume {run_id} to continue.",

    # ── event-level render strings ────────────────────────────────────────────
    "tui.event.phase.plan":    "Planning…",
    "tui.event.phase.act":     "Executing…",
    "tui.event.phase.verify":  "Verifying…",
    "tui.event.phase.report":  "Summarizing…",
    "tui.event.phase.default": "Thinking…",

    "tui.event.compacted":     "◌ Compacted -{pct}% · {before}→{after} entries",
    "tui.event.pruned":        "◌ Pruned {n} entries",
    "tui.event.memory_recall": "◌ Memory recall: {n} entries",
    "tui.event.workflow_done": "◕ Workflow '{name}' complete: {synthesis}",
    "tui.event.escalation":    "⚠︎ Stuck ({attempts} rounds): {reason} — last failure: {failure}",
    "tui.event.error":         "◉ Error: {message}{chain}",
    "tui.event.approval_result": "Approval: {action} → {value}",
    "tui.event.plan_decision":   "Plan decision: {value}",
    "tui.event.workflow_approval": "Workflow approval: {name} → {value}",

    # ── approval / plan InlineChoice labels ───────────────────────────────────
    "tui.approval.once":          "Allow once",
    "tui.approval.session":       "Allow for this session",
    "tui.approval.always":        "Always allow",
    "tui.approval.deny":          "Deny",

    "tui.workflow.approval_title": "Workflow approval — will spawn multiple sub-agents for orchestration",
    "tui.workflow.once":           "Approve once",
    "tui.workflow.always":         "Always approve",
    "tui.workflow.deny":           "Deny",

    "tui.plan.modal_title":    "◓ Plan ready — how to proceed?",
    "tui.plan.approve_start":  "Approve, start executing",
    "tui.plan.approve_accept": "Approve + auto-accept edits",
    "tui.plan.keep_planning":  "Continue planning",
    "tui.plan.refine":         "Add feedback and re-plan",
    "tui.plan.refine_placeholder": "Add feedback on the plan, Enter to submit, Esc to cancel",

    # ── computer-action event lines ───────────────────────────────────────────
    "tui.computer.screenshot_ok":   "[computer] {mark} screenshot saved{path}",
    "tui.computer.screenshot_fail": "[computer] {mark} screenshot failed: {detail}",
    "tui.computer.click_ok":        "[computer] {mark} {label} {coord}",
    "tui.computer.click_fail":      "[computer] {mark} {label} {coord}: {detail}",
    "tui.computer.click_label":     "clicked",
    "tui.computer.dblclick_label":  "double-clicked",
    "tui.computer.type_ok":         "[computer] {mark} typed {preview!r}",
    "tui.computer.type_ok_nopreview": "[computer] {mark} typed text",
    "tui.computer.type_fail":       "[computer] {mark} type failed: {detail}",
    "tui.computer.key_line":        "[computer] {mark} key {preview!r}{detail}",
    "tui.computer.scroll_line":     "[computer] {mark} scrolled{coord}{detail}",
    "tui.computer.open_app_line":   "[computer] {mark} opened app {hint}{detail}",
    "tui.computer.generic_line":    "[computer] {mark} {kind}: {detail}",
    "tui.computer.unknown_coord":   "(unknown coordinates)",

    # ── app subtitle + demo banner ────────────────────────────────────────────
    "tui.app.subtitle":   "hundred-eyed agent",
    "tui.app.demo_banner": "DEMO scripted demo (real loop pending Phase 6)",

    # ── BINDINGS labels ───────────────────────────────────────────────────────
    "tui.bind.interrupt_quit": "interrupt/quit",
    "tui.bind.quit":           "quit",
    "tui.bind.interrupt":      "interrupt",
    "tui.bind.background":     "background",
    "tui.bind.right_panel":    "right panel",
    "tui.bind.paste_image":    "paste image",

    # ── prompt placeholder ────────────────────────────────────────────────────
    "tui.prompt.placeholder": "› Enter goal, or / to start a command",

    # ── kernel mode label ─────────────────────────────────────────────────────
    "tui.kernel.inline": "inline(single-process)",

    # ── status_bar plan mode label ────────────────────────────────────────────
    "tui.statusbar.plan_mode": "[plan mode]",

    # ── paste image failure ───────────────────────────────────────────────────
    "tui.paste.failed": "⚠︎ paste image failed: {err}",

    # ── run busy ─────────────────────────────────────────────────────────────
    "tui.run.busy": "› Task in progress — wait for it to finish before starting a new one.",

    # ── tab strip ────────────────────────────────────────────────────────────
    "tui.tab.focus_failed": "⚠︎ focus failed ({id}…): {err}",
    "tui.tab.switched":     "━━━ switched to run {id}… ━━━",

    # ── voice input ───────────────────────────────────────────────────────────
    "tui.voice.record_failed":     "⚠︎ recording failed: {err}",
    "tui.voice.recording":         "🎙 recording… (press space again to stop)",
    "tui.voice.transcribe_failed": "⚠︎ transcription failed: {err}",
    "tui.voice.transcribe_first":  "first use · loading voice model (may download ~hundreds MB if not cached, please wait)…",
    "tui.voice.transcribing":      "transcribing…",

    # ── skill run failure ─────────────────────────────────────────────────────
    "tui.skill.run_failed": "/{name} failed: {err}",

    # ── skills list ───────────────────────────────────────────────────────────
    "tui.skills.empty": "  (no skills installed; run `argos skills refresh` to fetch index)",

    # ── eval ──────────────────────────────────────────────────────────────────
    "tui.eval.list_header": "Recent eval runs (up to 20):",
    "tui.eval.truncated":   "\n\n... (truncated; full report: cat {path})",

    # ── approval action line ──────────────────────────────────────────────────
    "tui.approval.action_line": "Action: {action} · Args: {args}",

    # ── confirm 503 fallback ──────────────────────────────────────────────────
    "tui.confirm.service_unavailable": "service temporarily unavailable",

    # ── dream 503 fallback ────────────────────────────────────────────────────
    "tui.dream.no_worker_key": "no worker key",
}

ZH: dict[str, str] = {
    # ── COMMAND_HELP entries ──────────────────────────────────────────────────
    "cmd.help":             "显示所有命令",
    "cmd.setup":            "显示配置向导入口(退出 TUI 后运行 argos setup)",
    "cmd.tools":            "列出可调用的工具",
    "cmd.skills":           "管理 skill 生态:list/install/remove/refresh/test (跑 argos skills ...)",
    "cmd.mcp":              "列出 MCP 外部工具",
    "cmd.model":            "查看 / 切换模型",
    "cmd.status":           "当前运行状态",
    "cmd.cost":             "本轮成本 + 缓存",
    "cmd.resume":           "续上一次会话",
    "cmd.clear":            "开新会话(清空)",
    "cmd.yolo":             "放手执行(免审批；旧命令，同 /trust autonomous)",
    "cmd.trust":            "查看 / 切换信任档位(/trust [cautious|trusted|autonomous|status])—替代 /yolo",
    "cmd.undo":             "撤销本轮文件改动(还原到 run 起点)",
    "cmd.ledger":           "查看当前 run 的行为账本(人话条目 + 撤销状态)",
    "cmd.journal":          "显示账本 JSONL 路径(/journal [run_id])",
    "cmd.retry":            "重发上一条 user 消息",
    "cmd.plan":             "进入 plan mode(审批后继续 act)—对齐 CC /plan",
    "cmd.hooks":            "列出 / 重载 hooks 配置(/hooks, /hooks reload)",
    "cmd.lsp":              "列出 / 重载 LSP 配置(/lsp, /lsp reload)",
    "cmd.permissions":      "查看 / 重载权限配置(/permissions, /permissions reload)",
    "cmd.runs":             "列出 / 后台 run(/runs, /runs {id} resume/cancel)—daemon 模式",
    "cmd.orders":           "列出自治常驻指令(/orders)—conductor 自治面",
    "cmd.confirm":          "确认 conductor 主动建议(/confirm <suggestion_id>)—自治面通电",
    "cmd.dismiss":          "忽略 conductor 主动建议(/dismiss <suggestion_id>)",
    "cmd.dream":            "夜间整合:跑一轮 Dream(聚类综合+记忆整理);/dream status 看上次报告",
    "cmd.verify":           "显式跑 verify_cmd(/verify [path])—用户复核 verify 门",
    "cmd.security-review":  "安全审计(secrets + 依赖漏洞 + 危险 API)(/security-review [path])",
    "cmd.simplify":         "代码重复 / 复杂度 / 死代码扫描(/simplify [path])",
    "cmd.eval":             "Agent 自我评估 + A/B(/eval, /eval run <id>, /eval compare <a> <b>)",
    "cmd.routing":          "查看 / 切换路由配置(/routing, /routing set <cat> <tier>)",
    "cmd.context":          "查看当前 LLM 上下文分桶(/context, /context --json)",
    "cmd.loop":             "循环执行直到条件满足(/loop <任务> [until: <条件>])",
    "cmd.goal":             "提交带验证退出条件的目标(/goal <任务> | verify: <命令>)",
    "cmd.schedule":         "创建定时任务(standing order)(/schedule <cron> <任务>)",
    "cmd.watch":            "监视文件变更触发任务(/watch <glob> <任务>)",

    # ── prompt.py paste / image tokens ───────────────────────────────────────
    "tui.prompt.paste_token": "[粘贴文本 #{n} +{lines} 行]",
    "tui.prompt.image_token": "[图片 #{n}]",

    # ── slash-menu nav hint ───────────────────────────────────────────────────
    "tui.slash_menu.nav_hint": "  ↑↓ 选择 · ↹ 补全 · ↵ 执行",

    # ── status_bar.py ─────────────────────────────────────────────────────────
    "tui.statusbar.hints":        "Esc 打断 · \\↵ 换行 · ^B 后台 · ^O 右栏 · ^V 贴图 · ^C/^D 退出",
    "tui.statusbar.blocked_label": "审批挂起",
    "tui.statusbar.plan_mode":    "[plan mode]",
    "tui.statusbar.action":       "动作{n}",

    # ── daemon / inline system notes ──────────────────────────────────────────
    "tui.daemon.unavailable": "daemon 不可用,已切换到单进程模式(后台化 / 跨会话续跑不可用)。",

    # ── /help command response ────────────────────────────────────────────────
    "tui.help.header":    "命令(打 / 也会就地列出,Tab 补全):",
    "tui.help.shortcuts": (
        "快捷键:\n"
        "  Esc / Ctrl+C   打断当前任务\n"
        "  Ctrl+C (空闲)  连按两次退出\n"
        "  Ctrl+D         退出\n"
        "  Ctrl+B         后台化当前 run(daemon 模式)\n"
        "  Ctrl+O         循环切换右栏视图\n"
        "  Ctrl+V         从剪贴板粘贴图片\n"
        "  行尾 \\ + 回车  插入换行(多行输入)\n"
        "  ↑ / ↓          浏览输入历史"
    ),

    # ── /model command ────────────────────────────────────────────────────────
    "tui.model.available":      "可用模型:{list}",
    "tui.model.switched":       "已切到 '{name}'(重启 argos 后生效)。",
    "tui.model.switch_failed":  "切换失败:{err}",

    # ── /status / /cost command ───────────────────────────────────────────────
    "tui.cost.header": "成本 + 缓存",

    # ── /clear command ────────────────────────────────────────────────────────
    "tui.clear.done": "已开新会话(clear)。",

    # ── unknown command ───────────────────────────────────────────────────────
    "tui.cmd.unknown": "未知命令 /{name}",
    "tui.cmd.unwired": "/{name} 命令尚未接线，将在后续批次中实现。",

    # ── /goal and /loop commands ──────────────────────────────────────────────
    "tui.goal.submitted": "目标已提交，验证命令：{verify_cmd}",

    # ── /yolo command ────────────────────────────────────────────────────────
    "tui.yolo.activated": (
        "已切换到 Autonomous（全自治/YOLO）——顶栏显示 ⏻ YOLO 标记。"
        " 提示：新用法为 /trust autonomous（或无参数 /trust 循环切换）。"
    ),

    # ── /trust command ────────────────────────────────────────────────────────
    "tui.trust.status":        "当前信任模式：{mode_name}（{label_human}）\n{description}",
    "tui.trust.unknown_mode":  "未知模式 '{arg}'。用法：/trust [cautious|trusted|autonomous|paranoid|status]（无参数则循环切换）",
    "tui.trust.already":       "当前已是 {mode_name}（{label_human}），无需切换。",
    "tui.trust.downgraded":    "已切换到 {mode_name}（{label_human}）。",
    "tui.trust.upgraded":      "已升级到 {mode_name}（{label_human}）。{yolo_note}",
    "tui.trust.yolo_note":     " TUI 顶栏显示 ⏻ 红色警示灯。",
    "tui.trust.cancelled":     "已取消升档操作，保持当前档位。",
    "tui.trust.confirm_title": "升档确认 — 切换到 {label_human}",
    "tui.trust.confirm_yes":   "确认升档",
    "tui.trust.confirm_no":    "取消，保持当前档位",

    # ── /undo command ────────────────────────────────────────────────────────
    "tui.undo.no_snapshot":   "无可撤销的运行(本会话尚未启动 run,或快照已清理)。",
    "tui.undo.partial":       "部分还原(成功 {ok} / 失败 {fail}):\n{head}{more}",
    "tui.undo.more":          "\n  …(更多省略)",
    "tui.undo.success":       "已还原 {n} 个文件到 run 起点。\n如要继续,可 /retry 重发上一条 goal,或输入新 goal。",

    # ── /ledger command ───────────────────────────────────────────────────────
    "tui.ledger.no_ledger":   "当前会话无行为账本(账本仅在 daemon 模式下可用,或本轮 run 尚未产生副作用动作)。",
    "tui.ledger.read_failed": "账本读取失败:{err}",
    "tui.ledger.empty":       "run {run_id} 尚无账本记录(本轮 run 未产生副作用动作)。",
    "tui.ledger.all_undone":  "run {run_id} 账本:所有动作均已撤销。",
    "tui.ledger.footer":      "每条回执签名 · summary 模板生成不调模型\njournal: {path}  (/journal {run_id} 查路径)",

    # ── /setup command ────────────────────────────────────────────────────────
    "tui.setup.hint": (
        "配置向导\n"
        "  退出 TUI 后运行:\n"
        "    argos setup\n"
        "  向导会引导你填写 provider、API key,并做连通性测试,\n"
        "  结果写入 ~/.argos/.env 和 ~/.argos/config.json。\n"
        "  也可手动编辑 ~/.argos/.env 添加 ANTHROPIC_API_KEY=... 等环境变量。"
    ),

    # ── /journal command ──────────────────────────────────────────────────────
    "tui.journal.with_id":   "账本 JSONL: {path}\n  查看:cat {path}\n  实时跟踪:tail -f {path}",
    "tui.journal.no_id":     "账本目录: {dir}\n  当前会话暂无 run_id(未起 run 或非 daemon 模式)。\n  用法:/journal <run_id>",

    # ── /retry command ────────────────────────────────────────────────────────
    "tui.retry.busy":           "先 Esc 打断当前任务,再 /retry。",
    "tui.retry.no_store":       "当前 store 不支持 /retry(demo 模式或未通过 build_components 注入)。",
    "tui.retry.read_failed":    "读取历史失败:{err}",
    "tui.retry.no_messages":    "当前会话没有可重试的消息。",

    # ── /hooks command ────────────────────────────────────────────────────────
    "tui.hooks.reloaded":       "已重载 hooks 配置(共 {n} 个事件)。",
    "tui.hooks.reload_failed":  "/hooks reload 失败(保留旧配置):{err}",
    "tui.hooks.empty":          "当前无 hooks 配置(空 ~/.argos/hooks.json 或未配置)。",
    "tui.hooks.header":         "当前 hooks 配置({n} 个事件):",
    "tui.hooks.all_match":      "(全匹配)",

    # ── /lsp command ─────────────────────────────────────────────────────────
    "tui.lsp.reloaded":       "已重载 LSP 配置(共 {n} 个 server)。",
    "tui.lsp.reload_failed":  "/lsp reload 失败(保留旧配置):{err}",
    "tui.lsp.empty":          "当前无 LSP 配置(空 ~/.argos/lsp.json 或不可读 → 走 built-in 默认)。",
    "tui.lsp.init_failed":    "LSP manager 初始化失败:{err}",
    "tui.lsp.header":         "当前 LSP 配置({n} 个 server):",
    "tui.lsp.diag":           "     diagnostics: {n} 条",

    # ── /permissions command ──────────────────────────────────────────────────
    "tui.permissions.reloaded":      "已重载 permissions 配置(allow {allow} / deny {deny} / ask {ask} / per-tool {tools} / default_level={level})。",
    "tui.permissions.reload_failed": "/permissions reload 失败(保留旧配置):{err}",
    "tui.permissions.read_failed":   "读取 permissions 配置失败:{err}",
    "tui.permissions.header":        "当前 permissions 配置:",
    "tui.permissions.default_level": " · default_level: {level}",
    "tui.permissions.per_tool":      " · per-tool 覆盖: {n} 个",
    "tui.permissions.allow_rules":   " · allow rules: {n} 条",
    "tui.permissions.deny_rules":    " · deny rules: {n} 条",
    "tui.permissions.ask_rules":     " · ask rules: {n} 条",
    "tui.permissions.omitted":       "   …(共 {total} 条,省略 {omitted})",
    "tui.permissions.default_gate":  "(沿用 gate.level)",

    # ── /tools command ────────────────────────────────────────────────────────
    "tui.tools.header":      "共 {n} 个工具:",
    "tui.tools.wf_off":      "编排(工作流,需 ARGOS_WORKFLOWS=1 才执行)",
    "tui.tools.wf_on":       "编排(工作流)",
    "tui.tools.group.file":          "文件",
    "tui.tools.group.cmd":           "命令/验证/计划",
    "tui.tools.group.web":           "联网",
    "tui.tools.group.browser":       "计算机控制(浏览器)",
    "tui.tools.group.external":      "外部工具",
    "tui.tools.group.lsp":           "LSP 语言服务器",
    "tui.tools.group.os":            "OS 级控制(P6a)",

    # ── /runs command ─────────────────────────────────────────────────────────
    "tui.runs.no_daemon":      "未启用 daemon(--with-daemon flag);/runs 不可用。",
    "tui.runs.list_failed":    "列 run 失败:{err}",
    "tui.runs.empty":          "无 run。",
    "tui.runs.list_header":    "Run 列表(#5b 扩展:cost / worktree):",
    "tui.runs.list_footer":    "/runs {id} focus|resume|cancel — 控制",
    "tui.runs.focus_ok":       "已 focus {run_id}(active 切到该 run)。",
    "tui.runs.focus_failed":   "focus 失败:HTTP {status}",
    "tui.runs.focus_readonly": "READ-ONLY 观察者不能 focus(只有 owner TUI 能切 active)。",
    "tui.runs.focus_err":      "focus 失败:{err}",
    "tui.runs.resume_ok":      "已请求 resume {run_id}。",
    "tui.runs.resume_failed":  "resume 失败:{err}",
    "tui.runs.cancel_ok":      "已请求 cancel {run_id}。",
    "tui.runs.cancel_failed":  "cancel 失败:{err}",
    "tui.runs.info_failed":    "查 run 失败:{err}",

    # ── /orders command ───────────────────────────────────────────────────────
    "tui.orders.request_failed": "/orders 请求失败（daemon）:{err}",
    "tui.orders.local_failed":   "读取本地 orders 失败:{err}",

    # ── /confirm command ──────────────────────────────────────────────────────
    "tui.confirm.no_id":          "用法:/confirm <suggestion_id>",
    "tui.confirm.no_daemon":      "confirm 需要 daemon 模式（--with-daemon）。",
    "tui.confirm.request_failed": "/confirm 请求失败:{err}",
    "tui.confirm.ok":             "建议已确认并创建 run：{run_id}\n  隔离：worktree={wt}\n  信任档：L1_DANGEROUS_ONLY（写死，不可升级）\n  用 /runs 查看运行状态。",
    "tui.confirm.not_found":      "建议 {id!r} 未找到或已处理（dismissed/confirmed）。",
    "tui.confirm.unavailable":    "无法确认：{err}",
    "tui.confirm.failed":         "/confirm 失败（HTTP {status}）：{err}",

    # ── /dismiss command ──────────────────────────────────────────────────────
    "tui.dismiss.no_id":          "用法:/dismiss <suggestion_id>",
    "tui.dismiss.no_daemon":      "dismiss 需要 daemon 模式（--with-daemon）。",
    "tui.dismiss.request_failed": "/dismiss 请求失败:{err}",
    "tui.dismiss.ok":             "建议 {id!r} 已忽略。",
    "tui.dismiss.not_found":      "建议 {id!r} 未找到或已处理。",
    "tui.dismiss.failed":         "/dismiss 失败（HTTP {status}）：{err}",

    # ── /routing command ──────────────────────────────────────────────────────
    "tui.routing.no_router":     "/routing 不可用(无 router 注入;demo/fake 模式)。",
    "tui.routing.set_usage":     "用法:/routing set <category> <tier>  (8 个合法 category: {cats})",
    "tui.routing.bad_category":  "category '{cat}' 不存在;8 个合法值:{cats}",
    "tui.routing.set_failed":    "/routing set 失败:{err}",
    "tui.routing.set_ok":        "已写入 {dir}/config.json:routing.by_category.{cat} = {tier}",

    # ── /context command ──────────────────────────────────────────────────────
    "tui.context.failed": "/context 失败:{err}",

    # ── /dream command ────────────────────────────────────────────────────────
    "tui.dream.no_daemon":        "Dream 需要 daemon 模式(当前 inline)。\n提示:重启 Argos 让其自动连接 daemon,或检查 ~/.argos/daemon.sock。",
    "tui.dream.report_failed":    "/dream report 请求失败:{err}",
    "tui.dream.no_report":        "暂无 Dream 报告(还没跑过夜间整合)。",
    "tui.dream.report_bad_type":  "Dream 报告格式异常(期望 dict,收到 {type})",
    "tui.dream.http_failed":      "/dream report 失败(HTTP {status})",
    "tui.dream.run_failed":       "/dream/run 请求失败:{err}",
    "tui.dream.started":          "Dream 已启动 · 整合进度见下方。",
    "tui.dream.already_running":  "已有 Dream 在跑,请稍后再试。",
    "tui.dream.start_failed":     "Dream 启动失败:{msg}",
    "tui.dream.unknown_status":   "/dream/run 返回未知状态 HTTP {status}:{body}",
    "tui.dream.fmt":              "Dream 完成  units={units}  promoted={promoted}  rejected={rejected}  skipped={skipped}  memory_merged={merged}  memory_archived={archived}",

    # ── /remember command ────────────────────────────────────────────────────
    "tui.remember.usage":      "用法:/remember <要记住的内容>",
    "tui.remember.duplicate":  "(已是最新 — 24h 内重复 / 空内容 / 解析失败,跳过)",
    "tui.remember.ok":         "已记住 ({scope}): {value} (id={id}, conf={conf:.2f})",

    # ── /forget command ──────────────────────────────────────────────────────
    "tui.forget.usage":       "用法:/forget <id 或 key 或 文本>",
    "tui.forget.not_found":   "未找到匹配 '{query}' 的记忆。",
    "tui.forget.ok":          "已软删 {n} 条:",

    # ── /resume command ───────────────────────────────────────────────────────
    "tui.resume.no_store":       "/resume 不可用(当前无持久化会话)。",
    "tui.resume.no_sessions":    "没有可恢复的历史会话。",
    "tui.resume.ok":             "已恢复会话「{title}」,带回 {n} 条历史 —— 继续输入即接上文。",

    # ── /skills command ───────────────────────────────────────────────────────
    "tui.skills.side_effect_hint": "[skills] TUI 不直装副作用。请到 host 跑:\n        $ argos skills {sub} {arg}",
    "tui.skills.curator_failed":   "curator 未加载:{err}",

    # ── /mcp command ─────────────────────────────────────────────────────────
    "tui.mcp.query_failed":    "MCP 查询失败:{err}",
    "tui.mcp.empty":           "未配置 MCP,或配置的 server 未连上 / 无工具。\n在 ~/.argos/mcp.json 配置 stdio server 即可扩展工具(默认零预配)。",
    "tui.mcp.header":          "已连接 MCP 工具 {n} 个,经 mcp_call(server, tool, arguments) 调用:",

    # ── /eval command ─────────────────────────────────────────────────────────
    "tui.eval.no_runs":        "尚未跑过 eval。试试 /eval run <task_id> 或 argos eval corpus",
    "tui.eval.usage":          "用法:/eval [run <task_id> | compare <a> <b>]",
    "tui.eval.compare_usage":  "用法:/eval compare <task_id>[:<model>] <task_id>[:<model>]",
    "tui.eval.task_mismatch":  "task_id 不一致:{a} vs {b}",
    "tui.eval.task_not_found": "未找到 task: {err}",

    # ── /plan command ─────────────────────────────────────────────────────────
    "tui.plan.factory_failed": "/plan 不可用(loop factory 失败):{err}",

    # ── inline / start_run ────────────────────────────────────────────────────
    "tui.run.demo_banner":     "⚠︎ 演示模式:以下为脚本化假数据,非真实执行/验证(真 AgentLoop 待 Phase 6 接入)。",
    "tui.run.thinking":        "已收到目标,思考中…",
    "tui.run.interrupted":     "⎋ 已打断当前任务。",
    "tui.run.create_failed":   "◉ daemon create_run 失败:{err}",

    # ── Ctrl+C idle hint ──────────────────────────────────────────────────────
    "tui.ctrlc.hint":          "再按一次 Ctrl+C 退出(或 Ctrl+D 直接退出)。",

    # ── background (Ctrl+B) ───────────────────────────────────────────────────
    "tui.background.suspended": "› Run {run_id} 后台化(suspended)。可 /resume {run_id} 续。",

    # ── event-level render strings ────────────────────────────────────────────
    "tui.event.phase.plan":    "规划中…",
    "tui.event.phase.act":     "执行中…",
    "tui.event.phase.verify":  "验证中…",
    "tui.event.phase.report":  "汇总中…",
    "tui.event.phase.default": "思考中…",

    "tui.event.compacted":     "◌ 已压缩 -{pct}% · {before}→{after} 条",
    "tui.event.pruned":        "◌ 已修剪 {n} 条",
    "tui.event.memory_recall": "◌ 记忆召回 {n} 条",
    "tui.event.workflow_done": "◕ 工作流「{name}」完成:{synthesis}",
    "tui.event.escalation":    "⚠︎ 卡住({attempts} 轮):{reason} — 最后失败:{failure}",
    "tui.event.error":         "◉ 错误:{message}{chain}",
    "tui.event.approval_result": "审批结果:{action} → {value}",
    "tui.event.plan_decision":   "Plan 决策:{value}",
    "tui.event.workflow_approval": "工作流审批:{name} → {value}",

    # ── approval / plan InlineChoice labels ───────────────────────────────────
    "tui.approval.once":          "本次允许",
    "tui.approval.session":       "本会话允许",
    "tui.approval.always":        "总是允许",
    "tui.approval.deny":          "拒绝",

    "tui.workflow.approval_title": "工作流审批 — 将起多个子 agent 编排执行",
    "tui.workflow.once":           "本次批准",
    "tui.workflow.always":         "总是批准",
    "tui.workflow.deny":           "拒绝",

    "tui.plan.modal_title":    "◓ 计划已就绪 — 如何继续?",
    "tui.plan.approve_start":  "批准,开始执行",
    "tui.plan.approve_accept": "批准 + 自动接受编辑",
    "tui.plan.keep_planning":  "继续规划",
    "tui.plan.refine":         "补充反馈后再规划",
    "tui.plan.refine_placeholder": "补充对 plan 的反馈,Enter 提交,Esc 返回",

    # ── computer-action event lines ───────────────────────────────────────────
    "tui.computer.screenshot_ok":     "[computer] {mark} 截图已保存{path}",
    "tui.computer.screenshot_fail":   "[computer] {mark} 截图失败:{detail}",
    "tui.computer.click_ok":          "[computer] {mark} {label}了 {coord}",
    "tui.computer.click_fail":        "[computer] {mark} {label}了 {coord}:{detail}",
    "tui.computer.click_label":       "点击",
    "tui.computer.dblclick_label":    "双击",
    "tui.computer.type_ok":           "[computer] {mark} 输入了 {preview!r}",
    "tui.computer.type_ok_nopreview": "[computer] {mark} 键入文本",
    "tui.computer.type_fail":         "[computer] {mark} 键入失败:{detail}",
    "tui.computer.key_line":          "[computer] {mark} 按键 {preview!r}{detail}",
    "tui.computer.scroll_line":       "[computer] {mark} 滚动{coord}{detail}",
    "tui.computer.open_app_line":     "[computer] {mark} 启动应用 {hint}{detail}",
    "tui.computer.generic_line":      "[computer] {mark} {kind}:{detail}",
    "tui.computer.unknown_coord":     "(未知坐标)",

    # ── app subtitle + demo banner ────────────────────────────────────────────
    "tui.app.subtitle":   "百眼智能体",
    "tui.app.demo_banner": "DEMO 脚本演示(真 loop 待 Phase 6 接入)",

    # ── BINDINGS labels ───────────────────────────────────────────────────────
    "tui.bind.interrupt_quit": "打断/退出",
    "tui.bind.quit":           "退出",
    "tui.bind.interrupt":      "打断",
    "tui.bind.background":     "后台",
    "tui.bind.right_panel":    "右栏视图",
    "tui.bind.paste_image":    "贴图",

    # ── prompt placeholder ────────────────────────────────────────────────────
    "tui.prompt.placeholder": "› 输入目标,或 / 开始命令",

    # ── kernel mode label ─────────────────────────────────────────────────────
    "tui.kernel.inline": "inline(单进程)",

    # ── status_bar plan mode label ────────────────────────────────────────────
    "tui.statusbar.plan_mode": "[plan mode]",

    # ── paste image failure ───────────────────────────────────────────────────
    "tui.paste.failed": "⚠︎ 贴图失败:{err}",

    # ── run busy ─────────────────────────────────────────────────────────────
    "tui.run.busy": "› 当前任务进行中,请等它结束再起新任务。",

    # ── tab strip ────────────────────────────────────────────────────────────
    "tui.tab.focus_failed": "⚠︎ focus 失败({id}…):{err}",
    "tui.tab.switched":     "━━━ 切到 run {id}… ━━━",

    # ── voice input ───────────────────────────────────────────────────────────
    "tui.voice.record_failed":     "⚠︎ 录音失败:{err}",
    "tui.voice.recording":         "🎙 录音中…(再按空格停止)",
    "tui.voice.transcribe_failed": "⚠︎ 转写失败:{err}",
    "tui.voice.transcribe_first":  "首次使用·加载语音模型(若未缓存需下载约数百 MB,请稍候)…",
    "tui.voice.transcribing":      "转写中…",

    # ── skill run failure ─────────────────────────────────────────────────────
    "tui.skill.run_failed": "/{name} 失败:{err}",

    # ── skills list ───────────────────────────────────────────────────────────
    "tui.skills.empty": "  (no skills installed;跑 `argos skills refresh` 拉 index)",

    # ── eval ──────────────────────────────────────────────────────────────────
    "tui.eval.list_header": "最近 eval runs(最多 20):",
    "tui.eval.truncated":   "\n\n... (truncated; 完整报告看:cat {path})",

    # ── approval action line ──────────────────────────────────────────────────
    "tui.approval.action_line": "动作: {action} · 参数: {args}",

    # ── confirm 503 fallback ──────────────────────────────────────────────────
    "tui.confirm.service_unavailable": "服务暂不可用",

    # ── dream 503 fallback ────────────────────────────────────────────────────
    "tui.dream.no_worker_key": "无 worker key",
}
