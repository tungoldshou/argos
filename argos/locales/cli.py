"""CLI + setup wizard 用户可见串目录。

key 命名空间:cli.* / setup.*。

ZH 值与重构前的**原始中文串逐字一致**,确保 ARGOS_LANG=zh 下旧测试断言不破。
EN 值是面向英文漏斗用户的默认文案(README/品牌基调:calm, precise)。
"""
from __future__ import annotations

# ── __main__.py 及 headless.py argparse help / description ─────────────────

EN: dict[str, str] = {
    # __main__.py argparse flags
    "cli.selftest.help": "Offline self-check (scripted model, four-phase run)",
    "cli.project.help": "Work inside the given project directory",
    "cli.model.help": "Use the named config profile for this run (default: the active one)",
    "cli.effort.help": "Effort tier (step budget: low=8 / medium=40 / high=80; approval mode is set by /trust)",
    "cli.sandbox.help": "Enable the OS sandbox (Seatbelt/bwrap kernel cage: no network, writes caged to the workspace). Opt-in, off by default; governance (approval + egress + AST limits) applies either way. Or set ARGOS_SANDBOX=1.",
    "cli.add_dir.help": "Grant write access to a directory outside the workspace (repeatable). The file tools and the write-cage treat it as writable; under --sandbox it's also added to the kernel cage. Or set ARGOS_ADD_DIRS (path-separated).",
    # setup sub-command
    "cli.setup.help": "Interactive wizard to connect a model (choose provider → enter key → probe → save)",
    "cli.setup.advanced_help": "Also prompt for max_tokens / context_window / embedding model (defaults used otherwise)",
    "cli.setup.epilog": (
        "The wizard writes ~/.argos/config.json (profile table + active pointer)"
        " and ~/.argos/.env (key, 0600).\n\n"
        "Minimal config.json example:\n"
        '  { "active": "default",\n'
        '    "models": { "default": {\n'
        '      "protocol": "anthropic",   # or "openai"\n'
        '      "base_url": "https://api.anthropic.com",\n'
        '      "model": "claude-sonnet-4-5",\n'
        '      "api_key_env": "ANTHROPIC_API_KEY",\n'
        '      "max_tokens": 8096, "context_window": 200000,\n'
        '      "price_in": 0.000003, "price_out": 0.000015 } } }\n\n'
        "Full field reference: docs/setup-wizard.md\n"
        "For non-TTY environments (Docker/CI) write the files above manually or mount a secret."
    ),
    # self-update sub-command
    "cli.self_update.help": "Check for a newer version and print upgrade instructions (skips the 7-day cache)",
    # headless exec sub-command
    "cli.exec.help": "Run a task non-interactively and exit (headless; scriptable / CI; like claude -p / codex exec)",
    "cli.exec.prompt.help": "Task description; omit it or pass '-' to read from stdin",
    "cli.exec.json.help": "Emit a JSON envelope (result / verdict / session_id / cost_usd / is_error) instead of plain text",
    "cli.exec.auto.help": "Permissive: approve every side effect (including network and writes outside the workspace); use only in trusted CI",
    "cli.exec.verify.help": "Declare a verify command (its exit code is authoritative; the same as the agent's propose_verify)",
    "cli.exec.project.help": "Work inside the given project directory (default: the current directory)",
    "cli.exec.model.help": "Use the named config profile for this run (default: the active one)",
    "cli.exec.quiet.help": "Don't write progress to stderr; emit only the final result (for strict CI stdout capture)",
    # context sub-command
    "cli.context.help": "Context visualizer (#12: show buckets / export JSON)",
    "cli.context.show.help": "Show the current LLM context breakdown (system / memory / tools / messages)",
    "cli.context.json.help": "JSON output (machine-readable; for eval and custom integrations)",
    "cli.context.session.help": "Use the given session_id (default: the active one)",
    # ── runtime printed messages ──────────────────────────────────────────────
    # __main__.py _cmd_self_update
    "cli.self_update.check_failed": "argos self-update: check failed: {err}",
    "cli.self_update.brew_hint": "   Installed via Homebrew — upgrade with: brew upgrade --cask argos",
    "cli.self_update.install_hint": "   Reinstall the latest: curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash",
    "cli.self_update.up_to_date": "✓ argos {version} is up to date.",
    # __main__.py _spawn_update_check (stderr banner)
    "cli.update_available_banner": (
        "🆕 Argos {newer} available (you have {current}). "
        "Run `argos self-update` to upgrade."
    ),
    # __main__.py main() — no-key fallback
    "cli.no_key_fallback": "[argos] {err}\n[argos] Run `argos setup` to connect a model, or set the environment variable and restart.",
    # headless.py — missing prompt
    "cli.exec.missing_prompt": "argos exec: no task description (pass it as an argument or pipe it in on stdin).",
    # headless.py — trivial verify rejection
    "cli.exec.trivial_verify": (
        "argos exec: --verify '{cmd}' is a trivial command"
        " (it always passes and verifies nothing) — rejected, no fake green."
        " Use a real test command (e.g. pytest / cargo test / tsc --noEmit)."
    ),
    # headless.py — build_components failure
    "cli.exec.no_key": "argos exec: {err}",
    "cli.exec.run_setup_hint": "argos exec: run `argos setup` to connect a model, or set the environment variable.",
    # headless.py progress lines
    "cli.exec.progress_start": "[argos exec] starting: {prompt}",
    "cli.exec.progress_phase": "[argos exec] phase → {label}",
    "cli.exec.progress_verify": "[argos exec] verify → {status}",
    "cli.exec.progress_escalation": "[argos exec] escalation: {msg}",
    "cli.exec.progress_error": "[argos exec] error: {msg}",
    # headless.py — verdict label (printed to stderr at end)
    "cli.exec.verdict_passed": "✓ passed",
    "cli.exec.verdict_passed_self": "✓ passed (self-verified / weak)",
    "cli.exec.verdict_failed": "✗ failed",
    "cli.exec.verdict_unverifiable": "? unverifiable",
    "cli.exec.verdict_no_test": "· no verify command declared (honest no-test)",
    # context CLI
    "cli.context.analysis_failed": "context: analysis failed: {err}",
    # ── setup_wizard.py interactive prompts / messages ────────────────────────
    "setup.choose_provider_title": "Choose a provider:",
    "setup.available_presets": "Available provider presets:",
    "setup.preset_item": "  {i}. {name}",
    "setup.invalid_choice": "Invalid choice, try again.",
    "setup.arrow_hint": "(↑↓ to select, Enter to confirm)\r\n",
    "setup.banner": "✦ Argos setup — connect a model",
    "setup.section_provider": "Provider",
    "setup.section_apikey": "API key",
    "setup.section_advanced": "Advanced (optional)",
    "setup.section_connect": "Connection test",
    "setup.key_method_paste": "Paste an API key",
    "setup.key_method_env": "Use an existing environment variable",
    "setup.prompt_protocol": "Protocol (anthropic/openai):",
    "setup.prompt_base_url": "base_url:",
    "setup.prompt_model": "Model id [{default}]:",
    "setup.prompt_key_method": "API key method — paste a key, or use an existing environment variable (env):",
    "setup.prompt_env_var_name": "Environment variable name:",
    "setup.prompt_paste_key": "Paste API key:",
    "setup.prompt_max_tokens": "max_tokens [4096]:",
    "setup.prompt_context_window": "context_window [200000]:",
    "setup.prompt_embedding_model": "Embedding model (blank = keyword recall, no extra model call; e.g. text-embedding-3-small):",
    "setup.no_embeddings_note": "(This provider uses the Anthropic protocol — no /embeddings endpoint; memory falls back to keyword recall.)",
    "setup.probing": "Running connection probe…",
    "setup.probe_rating": "[{rating}] {message}",
    "setup.reconnect_prompt": "Connection failed — reconfigure this model? (Y/n):",
    "setup.deep_probe_prompt": "Run a deep probe? (real write + verify, ~10-30s) [y/N]:",
    "setup.deep_probing": "Running deep probe (real write + verify)…",
    "setup.deep_probe_result": "Deep probe result [{rating}] {message}",
    "setup.prompt_profile_name": "Name for this model [{default}]:",
    "setup.set_active_prompt": "Make this the active model? (y/N):",
    "setup.warn_set_active_disconnected": "⚠️ This model failed the connection probe, but you chose to make it active — confirm it is reachable before you use it.",
    "setup.save_failed": "Save failed (invalid configuration): {err} — please reconfigure this model.",
    "setup.saved_active": "Saved '{name}' and made it the active model.",
    "setup.saved_inactive": "Saved '{name}' (active model unchanged).",
    "setup.key_stored_warning": "Note: the API key is stored in plain text in ~/.argos/.env (permissions 0600), not encrypted.",
    "setup.key_empty": "No key entered — leaving the key blank can't connect. Re-enter this model (or pick the env-var method if your key lives in the environment).",
    "setup.add_another_prompt": "Add another model? (y/N):",
    "setup.done": "Setup complete. Run `argos` to use the active model.",
    "setup.no_tty": (
        "\n⚠ stdin is closed (`argos setup` needs an interactive terminal).\n"
        "  • Run it in a real terminal: `argos setup` (or `uv run argos setup`)\n"
        "  • For non-interactive environments (scripts / CI), write two files by hand:\n"
        "      ~/.argos/config.json   ← provider / model / base_url declaration\n"
        "      ~/.argos/.env          ← API key (permissions 0600)\n"
        "    File schema: `argos setup --help` or docs/setup-wizard.md"
    ),
    # setup_wizard.py _ask_int fail-soft message
    "setup.not_integer": "'{val}' is not an integer; using the default {default}.",
    # setup_wizard.py probe ratings (ProbeResult.rating field)
    "setup.probe_rating_ok": "ok",
    "setup.probe_rating_marginal": "marginal",
    "setup.probe_rating_fail": "fail",
    # setup_wizard.py probe messages
    "setup.probe_timeout": (
        "Connection timed out (no response in {timeout}s): the endpoint is reachable but not responding. "
        "Check that base_url is correct and the model is loaded."
    ),
    "setup.probe_connect_error": "Cannot connect / endpoint error: {detail}",
    "setup.probe_ok_message": "Connected; CodeAct format looks good.",
    "setup.probe_marginal_message": (
        "Connected, but this model does not emit ```python CodeAct fences by default "
        "(Argos has seen this with MiniMax-M3 and corrects it through the system-prompt contract) "
        "— usable, but it may need stronger prompting; you can still save it."
    ),
    # deep_probe results
    "setup.deep_probe_pass_one": "End-to-end run succeeded (verify {vs}).",
    "setup.deep_probe_pass_marginal": "End-to-end run succeeded (verify {vs}).",
    "setup.deep_probe_fail": "Verify did not pass (verdicts={vs}).",
    "setup.deep_probe_error": "Deep probe could not run: {err}",
    # setup_wizard.py _probe_prompt / deep_probe task
    "setup.probe_prompt": "Output only a single ```python code block containing: print('ok'). No other text.",
    "setup.deep_probe_task": "Implement st.f returning 1 and verify",
    # __main__.py _run_selftest
    "cli.selftest.done": "Done.",
    "cli.selftest.task": "Implement st.f returning 1",
    "cli.selftest.assembly_failed": "[selftest] Assembly self-check failed: {exc_type}: {exc} → FAIL",

    # ── argos/cli/eval.py ────────────────────────────────────────────────────
    "cli.eval.help": "Agent self-eval + A/B comparison (#7)",
    "cli.eval.list.help": "List recent eval runs",
    "cli.eval.run.help": "Run a single task",
    "cli.eval.run.task_id.help": "Task id (see `argos eval corpus`)",
    "cli.eval.run.model.help": "Model profile name (default = active)",
    "cli.eval.run.keep_worktree.help": "Debug: keep worktree after run",
    "cli.eval.compare.help": "A/B compare two model tiers",
    "cli.eval.corpus.help": "List corpus task catalog",
    "cli.eval.no_runs": "No eval runs yet. Try `argos eval corpus` to see the task list.",
    "cli.eval.task_not_found": "未找到 task: {err}",

    # ── argos/cli/skills.py ──────────────────────────────────────────────────
    "cli.skills.help": "Skill ecosystem management (#10: refresh / list / install / remove / test)",
    "cli.skills.refresh.help": "Fetch remote index.json and refresh local cache",
    "cli.skills.refresh.url.help": "Custom index URL (for testing)",
    "cli.skills.list.help": "List installed + index remote available",
    "cli.skills.install.help": "Install a skill (default enabled=false)",
    "cli.skills.install.name.help": "Skill name (see `argos skills list`)",
    "cli.skills.remove.help": "Remove a skill (moved to .trash; recoverable for 30 days)",
    "cli.skills.test.help": "Run the skill's own smoke test (or generic probe if none)",
    "cli.skills.no_skills_hint": "\n(no skills installed; run `argos skills refresh` to pull index)",
    "cli.skills.network_confirm": "[skills] {name!r} declares network traffic — install? [y/N] ",

    # ── argos/cli/dream.py ───────────────────────────────────────────────────
    "cli.dream.help": "Nightly consolidation: cross-run distillation + memory tidy (--report to view last report)",
    "cli.dream.report.help": "Show the latest Dream report without running a new cycle",
    "cli.dream.report_fmt": (
        "Dream report  "
        "units_total={units_total}  "
        "promoted={promoted}  "
        "rejected={rejected}  "
        "skipped={skipped}  "
        "memory_merged={memory_merged}  "
        "memory_archived={memory_archived}"
    ),
    "cli.dream.no_report": "No Dream report yet (candidate pool empty or Dream has never run).",
    "cli.dream.report_bad_type": "Dream report format unexpected (expected dict, got {type_name}).",
    "cli.dream.no_key_notice": "No API key: running memory tidy and candidate inventory only (A/B promotion skipped).",
    "cli.dream.no_key_setup_hint": "For full Dream promotion, run `argos setup` to configure a model.",
    "cli.dream.memory_tidy": "Memory tidy: merged={merged} archived={archived}",
    "cli.dream.memory_tidy_failed": "Memory tidy failed (degraded/skipped): {err}",
    "cli.dream.candidates_count": "Candidate pool unconsumed: {n} item(s) (configure a key to trigger promotion)",
    "cli.dream.no_runner_warning": "Warning: could not initialize eval runner, skipping A/B promotion.",
    "cli.dream.starting": "Dream starting (cross-run cluster synthesis + A/B promotion + memory tidy)…",
    "cli.dream.pipeline_failed": "Dream pipeline failed: {err}",
    "cli.dream.already_running": "Another Dream is already running (possibly the daemon nightly consolidation) — skipping.",
    "cli.dream.report_written": "Report written to: {path}",

    # ── argos/cli/pkg.py ─────────────────────────────────────────────────────
    "cli.pkg.usage_info": "  info      — print project metadata + packaging/VERSION + git tag",
    "cli.pkg.usage_check": "  check     — verify self + argos entry-point import succeeds",
    "cli.pkg.usage_manifest": "  manifest  — dry-run winget manifest generation (real in v0.2.0)",
    "cli.pkg.check_import_failed": "argospkg check: import failed: {exc_type}: {err}",
    "cli.pkg.manifest_placeholder": "argospkg manifest: v0.1.0 placeholder only; v0.2.0 will wire wingetcreate for auto-generation",
}

ZH: dict[str, str] = {
    # __main__.py argparse flags
    "cli.selftest.help": "不连真模型自检(脚本模型跑四阶段)",
    "cli.project.help": "在用户项目目录干活",
    "cli.model.help": "本次启动用指定 config profile(默认当前 active)",
    "cli.effort.help": "任务努力档(步数预算:low=8 / medium=40 / high=80;审批档由 /trust 控制)",
    "cli.sandbox.help": "启用 OS 沙箱(Seatbelt/bwrap 内核牢笼:断网、写牢笼 workspace)。opt-in、默认关;无论开关,治理(审批+egress+AST 限制)都在。也可设 ARGOS_SANDBOX=1。",
    "cli.add_dir.help": "授权 workspace 之外的一个目录可写(可重复)。文件工具与写牢笼视其为可写;开 --sandbox 时也加进内核牢笼。也可设 ARGOS_ADD_DIRS(路径分隔符分隔)。",
    # setup sub-command
    "cli.setup.help": "接入模型的交互向导(选 provider→填 key→连通测试→保存)",
    "cli.setup.advanced_help": "额外询问 max_tokens / context_window / embedding 模型(否则用缺省值)",
    "cli.setup.epilog": (
        "向导写入 ~/.argos/config.json(profile 表 + active 指针)和 ~/.argos/.env(key, 0600)。\n\n"
        "config.json 最小示例:\n"
        '  { "active": "default",\n'
        '    "models": { "default": {\n'
        '      "protocol": "anthropic",   # 或 "openai"\n'
        '      "base_url": "https://api.anthropic.com",\n'
        '      "model": "claude-sonnet-4-5",\n'
        '      "api_key_env": "ANTHROPIC_API_KEY",\n'
        '      "max_tokens": 8096, "context_window": 200000,\n'
        '      "price_in": 0.000003, "price_out": 0.000015 } } }\n\n'
        "完整字段说明见 docs/setup-wizard.md 。\n"
        "非 TTY 场景(Docker/CI)请手动写上述文件或挂载 secret。"
    ),
    # self-update sub-command
    "cli.self_update.help": "检查并提示新版本(不自动下载;跳过 7 天缓存)",
    # headless exec sub-command
    "cli.exec.help": "非交互执行一个任务并退出(headless;可脚本化 / CI;对标 claude -p / codex exec)",
    "cli.exec.prompt.help": "任务描述;省略或传 '-' 时从 stdin 读",
    "cli.exec.json.help": "输出 JSON envelope(result / verdict / session_id / cost_usd / is_error)而非纯文本",
    "cli.exec.auto.help": "放手:批准一切副作用(含出网 / 越界);仅在信任的 CI 环境用",
    "cli.exec.verify.help": "声明验证命令(退出码裁决;等价 agent 的 propose_verify)",
    "cli.exec.project.help": "在指定项目目录干活(默认当前目录)",
    "cli.exec.model.help": "本次用指定 config profile(默认当前 active)",
    "cli.exec.quiet.help": "不向 stderr 打印进度;仅输出最终结果(适合严格的 CI stdout 捕获)",
    # context sub-command
    "cli.context.help": "Context 可视化 (#12: show 看分桶 / JSON 导出)",
    "cli.context.show.help": "看当前 LLM 上下文分桶(system/memory/tools/messages)",
    "cli.context.json.help": "JSON 输出(机读,接 eval/二次开发)",
    "cli.context.session.help": "指定 session_id(本期默认当前 active)",
    # ── runtime printed messages ──────────────────────────────────────────────
    # __main__.py _cmd_self_update
    "cli.self_update.check_failed": "argos self-update: 检查失败:{err}",
    "cli.self_update.brew_hint": "   您通过 Homebrew 装的,请用:brew upgrade --cask argos",
    "cli.self_update.install_hint": "   重装最新版:curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash",
    "cli.self_update.up_to_date": "✓ argos {version} 已是最新 (up to date)。",
    # __main__.py _spawn_update_check (stderr banner)
    "cli.update_available_banner": (
        "🆕 Argos {newer} available (you have {current}). "
        "Run `argos self-update` to upgrade."
    ),
    # __main__.py main() — no-key fallback
    "cli.no_key_fallback": "[argos] {err}\n[argos] 运行 `argos setup` 接入模型,或配置环境变量后重启。",
    # headless.py — missing prompt
    "cli.exec.missing_prompt": "argos exec: 缺少任务描述(传 positional 参数或经 stdin 提供)。",
    # headless.py — trivial verify rejection
    "cli.exec.trivial_verify": (
        "argos exec: --verify '{cmd}' 是 trivial 命令"
        "(永远通过,不验证任何事)—— 拒绝受理,绝不假绿。"
        " 请改用真实测试命令(如 pytest / cargo test / tsc --noEmit)。"
    ),
    # headless.py — build_components failure
    "cli.exec.no_key": "argos exec: {err}",
    "cli.exec.run_setup_hint": "argos exec: 运行 `argos setup` 接入模型,或配置环境变量。",
    # headless.py progress lines
    "cli.exec.progress_start": "[argos exec] 开始: {prompt}",
    "cli.exec.progress_phase": "[argos exec] phase → {label}",
    "cli.exec.progress_verify": "[argos exec] verify → {status}",
    "cli.exec.progress_escalation": "[argos exec] escalation: {msg}",
    "cli.exec.progress_error": "[argos exec] error: {msg}",
    # headless.py — verdict label (printed to stderr at end)
    "cli.exec.verdict_passed": "✓ passed",
    "cli.exec.verdict_passed_self": "✓ passed (自验证/较弱)",
    "cli.exec.verdict_failed": "✗ failed",
    "cli.exec.verdict_unverifiable": "? unverifiable",
    "cli.exec.verdict_no_test": "· 无声明验证(honest no-test)",
    # context CLI
    "cli.context.analysis_failed": "context: 分析失败:{err}",
    # ── setup_wizard.py interactive prompts / messages ────────────────────────
    "setup.choose_provider_title": "选择 provider:",
    "setup.available_presets": "可选 provider 预设:",
    "setup.preset_item": "  {i}. {name}",
    "setup.invalid_choice": "无效编号,重来。",
    "setup.arrow_hint": "(↑↓ 选,回车确认)\r\n",
    "setup.banner": "✦ Argos 配置向导 —— 接入一个模型",
    "setup.section_provider": "模型提供方",
    "setup.section_apikey": "API 密钥",
    "setup.section_advanced": "高级(可选)",
    "setup.section_connect": "连通测试",
    "setup.key_method_paste": "粘贴一个 API 密钥",
    "setup.key_method_env": "使用已有的环境变量",
    "setup.prompt_protocol": "协议 (anthropic/openai):",
    "setup.prompt_base_url": "base_url:",
    "setup.prompt_model": "模型 id [{default}]:",
    "setup.prompt_key_method": "API key 方式:粘贴(paste) / 用已有环境变量(env):",
    "setup.prompt_env_var_name": "环境变量名:",
    "setup.prompt_paste_key": "粘贴 API key:",
    "setup.prompt_max_tokens": "max_tokens [4096]:",
    "setup.prompt_context_window": "context_window [200000]:",
    "setup.prompt_embedding_model": "embedding 模型(留空=记忆走关键词,不额外调模型;如 text-embedding-3-small):",
    "setup.no_embeddings_note": "(此 provider 是 Anthropic 端,无 embeddings;记忆走关键词召回)",
    "setup.probing": "正在连通测试…",
    "setup.probe_rating": "[{rating}] {message}",
    "setup.reconnect_prompt": "连不上,重配这个模型?(Y/n):",
    "setup.deep_probe_prompt": "要顺手深测一下吗?(真跑 write+verify, ~10-30s) [y/N]:",
    "setup.deep_probing": "正在深度探针(真跑 write+verify)…",
    "setup.deep_probe_result": "深测结果 [{rating}] {message}",
    "setup.prompt_profile_name": "给这个模型起个名 [{default}]:",
    "setup.set_active_prompt": "设为当前默认模型?(y/N):",
    "setup.warn_set_active_disconnected": "⚠️ 此模型连通测试未通过,仍按你的选择设为当前模型——下次使用前请确认它可用。",
    "setup.save_failed": "保存失败(配置不合法):{err} —— 请重新配置这个模型。",
    "setup.saved_active": "已保存 '{name}'并设为当前模型。",
    "setup.saved_inactive": "已保存 '{name}'(未改当前默认模型)。",
    "setup.key_stored_warning": "注意:API key 以明文存于 ~/.argos/.env(权限 0600),不加密。",
    "setup.key_empty": "没输入 key —— 留空连不上。请重配这个模型(或改用环境变量方式,如果 key 在环境里)。",
    "setup.add_another_prompt": "再配一个模型?(y/N):",
    "setup.done": "setup 完成。运行 `argos` 即用当前模型。",
    "setup.no_tty": (
        "\n⚠ 检测到 stdin 关闭(`argos setup` 需交互终端)。\n"
        "  • 在真终端直接跑:`argos setup`(或 `uv run argos setup`)\n"
        "  • 非交互场景(脚本/CI)手工写两份文件:\n"
        "      ~/.argos/config.json   ← provider / model / base_url 声明\n"
        "      ~/.argos/.env          ← API key(权限 0600)\n"
        "    文件 schema 见 `argos setup --help` 或 docs/setup-wizard.md"
    ),
    # setup_wizard.py _ask_int fail-soft message
    "setup.not_integer": "'{val}' 不是整数,改用默认 {default}。",
    # setup_wizard.py probe ratings (ProbeResult.rating field)
    "setup.probe_rating_ok": "行",
    "setup.probe_rating_marginal": "勉强",
    "setup.probe_rating_fail": "不行",
    # setup_wizard.py probe messages
    "setup.probe_timeout": (
        "连接超时({timeout}s 无回流):端点可达但未响应,"
        "检查 base_url 是否正确、模型是否已加载。"
    ),
    "setup.probe_connect_error": "连不上 / 端点报错:{detail}",
    "setup.probe_ok_message": "连通正常,CodeAct 格式合规。",
    "setup.probe_marginal_message": (
        "连通正常,但此模型默认不吐 ```python 围栏(Argos 实测 MiniMax-M3 也曾如此,"
        "靠系统提示契约掰正)——能用但可能需要更强提示;仍可保存。"
    ),
    # deep_probe results
    "setup.deep_probe_pass_one": "端到端跑通(verify {vs})。",
    "setup.deep_probe_pass_marginal": "端到端跑通(verify {vs})。",
    "setup.deep_probe_fail": "未跑通验证(verdicts={vs})。",
    "setup.deep_probe_error": "深度探针无法运行:{err}",
    # setup_wizard.py _probe_prompt / deep_probe task
    "setup.probe_prompt": "请只用一个 ```python 代码块输出:print('ok')。不要任何其它文字。",
    "setup.deep_probe_task": "写 st.f 返回 1 并验证",
    # __main__.py _run_selftest
    "cli.selftest.done": "完成。",
    "cli.selftest.task": "实现 st.f 返回 1",
    "cli.selftest.assembly_failed": "[selftest] 装配自检失败:{exc_type}: {exc} → FAIL",

    # ── argos/cli/eval.py ────────────────────────────────────────────────────
    "cli.eval.help": "Agent 自我评估 + A/B 对比 (#7)",
    "cli.eval.list.help": "列最近 eval run",
    "cli.eval.run.help": "跑单个 task",
    "cli.eval.run.task_id.help": "task id (见 `argos eval corpus`)",
    "cli.eval.run.model.help": "model profile name(默认 = active)",
    "cli.eval.run.keep_worktree.help": "调试:不删 worktree",
    "cli.eval.compare.help": "A/B 对比两个 model tier",
    "cli.eval.corpus.help": "列 corpus 任务清单",
    "cli.eval.no_runs": "尚未跑过 eval。试试 argos eval corpus 看任务清单。",
    "cli.eval.task_not_found": "未找到 task: {err}",

    # ── argos/cli/skills.py ──────────────────────────────────────────────────
    "cli.skills.help": "Skill 生态管理 (#10: refresh / list / install / remove / test)",
    "cli.skills.refresh.help": "拉远端 index.json 刷新本地 cache",
    "cli.skills.refresh.url.help": "自定义 index URL(测试用)",
    "cli.skills.list.help": "列已装 + index 远端可用",
    "cli.skills.install.help": "装一个 skill(默认 enabled=false)",
    "cli.skills.install.name.help": "skill name(见 `argos skills list`)",
    "cli.skills.remove.help": "卸一个 skill(进 .trash 30d 可恢复)",
    "cli.skills.test.help": "跑 skill 自带 smoke test(无则跑通用探针)",
    "cli.skills.no_skills_hint": "\n(no skills installed; 跑 `argos skills refresh` 拉 index)",
    "cli.skills.network_confirm": "[skills] {name!r} 声明会发网络流量,装? [y/N] ",

    # ── argos/cli/dream.py ───────────────────────────────────────────────────
    "cli.dream.help": "夜间整合:跨 run 综合蒸馏 + 记忆整理(--report 看上次报告)",
    "cli.dream.report.help": "只读最新 Dream 报告(不跑新一轮)",
    "cli.dream.report_fmt": (
        "Dream 报告  "
        "units_total={units_total}  "
        "promoted={promoted}  "
        "rejected={rejected}  "
        "skipped={skipped}  "
        "memory_merged={memory_merged}  "
        "memory_archived={memory_archived}"
    ),
    "cli.dream.no_report": "暂无 Dream 报告(候选区空或从未跑过 Dream)。",
    "cli.dream.report_bad_type": "Dream 报告格式异常(期望 dict,收到 {type_name})。",
    "cli.dream.no_key_notice": "无 API key:仅做记忆整理与候选区盘点(A/B 晋升跳过)。",
    "cli.dream.no_key_setup_hint": "若要完整 Dream 晋升,请先运行 `argos setup` 配置模型。",
    "cli.dream.memory_tidy": "记忆整理:merged={merged} archived={archived}",
    "cli.dream.memory_tidy_failed": "记忆整理失败(降级跳过): {err}",
    "cli.dream.candidates_count": "候选区未消费材料: {n} 条(配置 key 后可触发晋升)",
    "cli.dream.no_runner_warning": "警告: 无法初始化 eval runner,跳过 A/B 晋升。",
    "cli.dream.starting": "Dream 启动(跨 run 聚类综合 + A/B 晋升 + 记忆整理)…",
    "cli.dream.pipeline_failed": "Dream 管道执行失败: {err}",
    "cli.dream.already_running": "另一个 Dream 正在运行(可能是 daemon 夜间整合),本次跳过。",
    "cli.dream.report_written": "报告已写入: {path}",

    # ── argos/cli/pkg.py ─────────────────────────────────────────────────────
    "cli.pkg.usage_info": "  info      — 打印项目元数据 + packaging/VERSION + git tag",
    "cli.pkg.usage_check": "  check     — 校验 self + argos 入口 import 成功",
    "cli.pkg.usage_manifest": "  manifest  — 预演生成 winget manifest(v0.2.0 真出)",
    "cli.pkg.check_import_failed": "argospkg check: import 失败:{exc_type}: {err}",
    "cli.pkg.manifest_placeholder": "argospkg manifest: v0.1.0 仅占位;v0.2.0 接 wingetcreate 自动生成",
}
