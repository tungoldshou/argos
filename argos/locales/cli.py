"""CLI + setup wizard 用户可见串目录。

key 命名空间:cli.* / setup.*。

ZH 值与重构前的**原始中文串逐字一致**,确保 ARGOS_LANG=zh 下旧测试断言不破。
EN 值是面向英文漏斗用户的默认文案(README/品牌基调:calm, precise)。
"""
from __future__ import annotations

# ── __main__.py 及 headless.py argparse help / description ─────────────────

EN: dict[str, str] = {
    # __main__.py argparse flags
    "cli.demo.help": "FakeLoop success demo",
    "cli.demo_fail.help": "FailingFakeLoop escalation demo",
    "cli.selftest.help": "Offline self-check (script model, four-phase run)",
    "cli.project.help": "Work inside the specified user project directory",
    "cli.model.help": "Use the specified config profile for this run (default: current active)",
    "cli.effort.help": "Task effort tier (step budget: low=8 / medium=40 / high=80; approval mode controlled by /trust)",
    # setup sub-command
    "cli.setup.help": "Interactive wizard to connect a model (choose provider → enter key → probe → save)",
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
    "cli.self_update.help": "Check for a newer version and print upgrade instructions (skips 7-day cache)",
    # headless exec sub-command
    "cli.exec.help": "Run a task non-interactively and exit (headless; scriptable / CI; equivalent to claude -p / codex exec)",
    "cli.exec.prompt.help": "Task description; omit or pass '-' to read from stdin",
    "cli.exec.json.help": "Output JSON envelope (result / verdict / session_id / cost_usd / is_error) instead of plain text",
    "cli.exec.auto.help": "Permissive: approve all side-effects (including network / out-of-cage); use only in trusted CI environments",
    "cli.exec.verify.help": "Declare a verification command (exit-code is authoritative; equivalent to agent's propose_verify)",
    "cli.exec.project.help": "Work inside the specified project directory (default: current directory)",
    "cli.exec.model.help": "Use the specified config profile for this run (default: current active)",
    "cli.exec.quiet.help": "Suppress progress output to stderr; only emit the final result (suitable for strict CI stdout capture)",
    # context sub-command
    "cli.context.help": "Context visualizer (#12: show buckets / JSON export)",
    "cli.context.show.help": "Show the current LLM context breakdown (system/memory/tools/messages)",
    "cli.context.json.help": "JSON output (machine-readable; for eval / custom integrations)",
    "cli.context.session.help": "Specify session_id (default: current active)",
    # ── runtime printed messages ──────────────────────────────────────────────
    # __main__.py _cmd_self_update
    "cli.self_update.check_failed": "argos self-update: check failed: {err}",
    "cli.self_update.brew_hint": "   Installed via Homebrew — upgrade with: brew upgrade --cask argos",
    "cli.self_update.install_hint": "   Reinstall latest: curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash",
    "cli.self_update.up_to_date": "✓ argos {version} is up to date.",
    # __main__.py _spawn_update_check (stderr banner)
    "cli.update_available_banner": (
        "🆕 Argos {newer} available (you have {current}). "
        "Run `argos self-update` to upgrade."
    ),
    # __main__.py main() — no-key fallback
    "cli.no_key_fallback": "[argos] {err}\n[argos] Run `argos setup` to connect a model, or set the environment variable and restart.",
    # headless.py — missing prompt
    "cli.exec.missing_prompt": "argos exec: missing task description (pass a positional argument or provide via stdin).",
    # headless.py — trivial verify rejection
    "cli.exec.trivial_verify": (
        "argos exec: --verify '{cmd}' is a trivial command"
        " (always passes, verifies nothing) — rejected, no fake green."
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
    "cli.exec.verdict_no_test": "· no declared verification (honest no-test)",
    # context CLI
    "cli.context.analysis_failed": "context: analysis failed: {err}",
    # ── setup_wizard.py interactive prompts / messages ────────────────────────
    "setup.choose_provider_title": "Choose a provider:",
    "setup.available_presets": "Available provider presets:",
    "setup.preset_item": "  {i}. {name}",
    "setup.invalid_choice": "Invalid choice, try again.",
    "setup.arrow_hint": "(↑↓ to select, Enter to confirm)\r\n",
    "setup.prompt_protocol": "Protocol (anthropic/openai):",
    "setup.prompt_base_url": "base_url:",
    "setup.prompt_model": "Model id [{default}]:",
    "setup.prompt_key_method": "API key method: paste / use existing environment variable (env):",
    "setup.prompt_env_var_name": "Environment variable name:",
    "setup.prompt_paste_key": "Paste API key:",
    "setup.prompt_max_tokens": "max_tokens [4096]:",
    "setup.prompt_context_window": "context_window [200000]:",
    "setup.prompt_price_in": "Price in (USD/1M, leave blank to skip):",
    "setup.prompt_price_out": "Price out (USD/1M, leave blank to skip):",
    "setup.prompt_embedding_model": "Embedding model (blank = keyword recall, no extra model call; e.g. text-embedding-3-small):",
    "setup.no_embeddings_note": "(This provider uses the Anthropic protocol — no /embeddings endpoint; memory uses keyword recall)",
    "setup.probing": "Running connection probe…",
    "setup.probe_rating": "[{rating}] {message}",
    "setup.reconnect_prompt": "Connection failed, reconfigure this model? (Y/n):",
    "setup.deep_probe_prompt": "Run a deep probe? (real write+verify, ~10-30s) [y/N]:",
    "setup.deep_probing": "Running deep probe (real write+verify)…",
    "setup.deep_probe_result": "Deep probe result [{rating}] {message}",
    "setup.prompt_profile_name": "Name for this model [{default}]:",
    "setup.set_active_prompt": "Set as current default model? (y/N):",
    "setup.warn_set_active_disconnected": "⚠️ This model failed the connection probe, but you chose to set it as current — confirm it is reachable before use.",
    "setup.save_failed": "Save failed (invalid configuration): {err} — please reconfigure this model.",
    "setup.saved_active": "Saved '{name}' and set as current model.",
    "setup.saved_inactive": "Saved '{name}' (current default model unchanged).",
    "setup.key_stored_warning": "Note: API key is stored in plain text in ~/.argos/.env (permissions 0600), not encrypted.",
    "setup.add_another_prompt": "Add another model? (y/N):",
    "setup.done": "Setup complete. Run `argos` to use the current model.",
    "setup.no_tty": (
        "\n⚠ stdin is closed (`argos setup` requires an interactive terminal).\n"
        "  • Run in a real terminal: `argos setup` (or `uv run argos setup`)\n"
        "  • For non-interactive environments (scripts/CI) write two files manually:\n"
        "      ~/.argos/config.json   ← provider / model / base_url declaration\n"
        "      ~/.argos/.env          ← API key (permissions 0600)\n"
        "    File schema: `argos setup --help` or docs/setup-wizard.md"
    ),
    # setup_wizard.py _ask_int / _ask_float_or_none fail-soft messages
    "setup.not_integer": "'{val}' is not an integer, using default {default}.",
    "setup.not_number": "'{val}' is not a number, skipping that price.",
    # setup_wizard.py probe ratings (ProbeResult.rating field)
    "setup.probe_rating_ok": "ok",
    "setup.probe_rating_marginal": "marginal",
    "setup.probe_rating_fail": "fail",
    # setup_wizard.py probe messages
    "setup.probe_timeout": (
        "Connection timed out ({timeout}s with no response): endpoint reachable but not responding, "
        "check that base_url is correct and the model is loaded."
    ),
    "setup.probe_connect_error": "Cannot connect / endpoint error: {detail}",
    "setup.probe_ok_message": "Connected successfully, CodeAct format compliant.",
    "setup.probe_marginal_message": (
        "Connected successfully, but this model does not emit ```python CodeAct fences by default "
        "(Argos has seen this with MiniMax-M3 and corrects it via the system-prompt contract) "
        "— usable but may need stronger prompting; you can still save."
    ),
    # deep_probe results
    "setup.deep_probe_pass_one": "End-to-end succeeded (verify {vs}).",
    "setup.deep_probe_pass_marginal": "End-to-end succeeded (verify {vs}).",
    "setup.deep_probe_fail": "Verification did not pass (verdicts={vs}).",
    "setup.deep_probe_error": "Deep probe could not run: {err}",
    # setup_wizard.py _probe_prompt / deep_probe task
    "setup.probe_prompt": "Output only a single ```python code block containing: print('ok'). No other text.",
    "setup.deep_probe_task": "Implement st.f returning 1 and verify",
    # __main__.py _run_selftest
    "cli.selftest.done": "Done.",
    "cli.selftest.task": "Implement st.f returning 1",
    "cli.selftest.assembly_failed": "[selftest] Assembly self-check failed: {exc_type}: {exc} → FAIL",
}

ZH: dict[str, str] = {
    # __main__.py argparse flags
    "cli.demo.help": "FakeLoop 成功演示",
    "cli.demo_fail.help": "FailingFakeLoop escalation 演示",
    "cli.selftest.help": "不连真模型自检(脚本模型跑四阶段)",
    "cli.project.help": "在用户项目目录干活",
    "cli.model.help": "本次启动用指定 config profile(默认当前 active)",
    "cli.effort.help": "任务努力档(步数预算:low=8 / medium=40 / high=80;审批档由 /trust 控制)",
    # setup sub-command
    "cli.setup.help": "接入模型的交互向导(选 provider→填 key→连通测试→保存)",
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
    "setup.prompt_protocol": "协议 (anthropic/openai):",
    "setup.prompt_base_url": "base_url:",
    "setup.prompt_model": "模型 id [{default}]:",
    "setup.prompt_key_method": "API key 方式:粘贴(paste) / 用已有环境变量(env):",
    "setup.prompt_env_var_name": "环境变量名:",
    "setup.prompt_paste_key": "粘贴 API key:",
    "setup.prompt_max_tokens": "max_tokens [4096]:",
    "setup.prompt_context_window": "context_window [200000]:",
    "setup.prompt_price_in": "价格 in (USD/1M, 留空跳过):",
    "setup.prompt_price_out": "价格 out (USD/1M, 留空跳过):",
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
    # setup_wizard.py _ask_int / _ask_float_or_none fail-soft messages
    "setup.not_integer": "'{val}' 不是整数,改用默认 {default}。",
    "setup.not_number": "'{val}' 不是数字,跳过该价格。",
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
}
