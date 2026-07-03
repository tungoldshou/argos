from pathlib import Path
import re

from argos.tui.commands import COMMAND_NAMES


ROOT = Path(__file__).resolve().parents[1]
README = Path(__file__).resolve().parents[1] / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
AGENTS = Path(__file__).resolve().parents[1] / "AGENTS.md"
CONTRIBUTING = Path(__file__).resolve().parents[1] / "CONTRIBUTING.md"
SECURITY = Path(__file__).resolve().parents[1] / "SECURITY.md"
AUTO_MEMORY_DOC = Path(__file__).resolve().parents[1] / "docs" / "auto-memory.md"
CONTEXT_DOC = Path(__file__).resolve().parents[1] / "docs" / "context-viz.md"
DREAM_DOC = Path(__file__).resolve().parents[1] / "docs" / "dream.md"
DREAM_DAEMON = Path(__file__).resolve().parents[1] / "argos" / "daemon" / "server.py"
CONDUCTOR_ORDERS = Path(__file__).resolve().parents[1] / "argos" / "conductor" / "orders.py"
EVAL_DOC = Path(__file__).resolve().parents[1] / "docs" / "eval.md"
EVAL_CLI = Path(__file__).resolve().parents[1] / "argos" / "cli" / "eval.py"
EVAL_COMPARE = Path(__file__).resolve().parents[1] / "argos" / "eval" / "compare.py"
EVAL_CORPUS = Path(__file__).resolve().parents[1] / "argos" / "eval" / "corpus.py"
EVAL_RESULTS = Path(__file__).resolve().parents[1] / "argos" / "eval" / "results.py"
EVAL_RUNNER = Path(__file__).resolve().parents[1] / "argos" / "eval" / "runner.py"
EXTERNAL_SURFACE_SOURCE_DOCS = (
    Path(__file__).resolve().parents[1] / "argos" / "core" / "honesty.py",
    Path(__file__).resolve().parents[1] / "argos" / "core" / "loop.py",
    Path(__file__).resolve().parents[1] / "argos" / "external_surfaces.py",
    Path(__file__).resolve().parents[1] / "argos" / "hooks" / "__init__.py",
    Path(__file__).resolve().parents[1] / "argos" / "hooks" / "config.py",
    Path(__file__).resolve().parents[1] / "argos" / "lsp" / "__init__.py",
    Path(__file__).resolve().parents[1] / "argos" / "lsp" / "config.py",
    Path(__file__).resolve().parents[1] / "argos" / "mcp_native.py",
    Path(__file__).resolve().parents[1] / "argos" / "tools" / "__init__.py",
    Path(__file__).resolve().parents[1] / "argos" / "tui" / "widgets" / "activity_panel.py",
)
CONFIG_SOURCE_DOCS = (
    Path(__file__).resolve().parents[1] / "argos" / "app_factory.py",
    Path(__file__).resolve().parents[1] / "argos" / "config.py",
    Path(__file__).resolve().parents[1] / "argos" / "routing" / "config.py",
    Path(__file__).resolve().parents[1] / "argos" / "setup_wizard.py",
    Path(__file__).resolve().parents[1] / "argos" / "skills_builtin" / "verify" / "SKILL.md",
    Path(__file__).resolve().parents[1] / "argos" / "skills_runtime" / "builtin" / "verify.py",
    Path(__file__).resolve().parents[1] / "argos" / "tui" / "app.py",
)
PERSISTENCE_SOURCE_DOCS = (
    Path(__file__).resolve().parents[1] / "argos" / "app_factory.py",
    Path(__file__).resolve().parents[1] / "argos" / "core" / "snapshot.py",
    Path(__file__).resolve().parents[1] / "argos" / "daemon" / "index.py",
    Path(__file__).resolve().parents[1] / "argos" / "daemon" / "pidfile.py",
    Path(__file__).resolve().parents[1] / "argos" / "daemon" / "registry.py",
    Path(__file__).resolve().parents[1] / "argos" / "isolation.py",
    Path(__file__).resolve().parents[1] / "argos" / "ledger" / "store.py",
    Path(__file__).resolve().parents[1] / "argos" / "memory" / "store.py",
)
RUNTIME_SOURCE_DOCS = (
    Path(__file__).resolve().parents[1] / "argos" / "__main__.py",
    Path(__file__).resolve().parents[1] / "argos" / "core" / "loop.py",
    Path(__file__).resolve().parents[1] / "argos" / "daemon" / "worker.py",
    Path(__file__).resolve().parents[1] / "argos" / "runtime.py",
    Path(__file__).resolve().parents[1] / "argos" / "sandbox" / "broker.py",
    Path(__file__).resolve().parents[1] / "argos" / "sandbox" / "executor.py",
)
LEARNING_SKILLS_SOURCE_DOCS = (
    Path(__file__).resolve().parents[1] / "argos" / "cli" / "dream.py",
    Path(__file__).resolve().parents[1] / "argos" / "core" / "vision_capability.py",
    Path(__file__).resolve().parents[1] / "argos" / "learning" / "candidates.py",
    Path(__file__).resolve().parents[1] / "argos" / "learning" / "dream.py",
    Path(__file__).resolve().parents[1] / "argos" / "learning" / "hook.py",
    Path(__file__).resolve().parents[1] / "argos" / "skills_curator" / "capabilities.py",
    Path(__file__).resolve().parents[1] / "argos" / "skills_curator" / "index.py",
)
PER_TASK_ROUTING_DOC = Path(__file__).resolve().parents[1] / "docs" / "per-task-routing.md"
SKILLS_CURATOR_DOC = Path(__file__).resolve().parents[1] / "docs" / "skills-curator.md"
VOICE_IMAGE_DOC = Path(__file__).resolve().parents[1] / "docs" / "voice-image-input.md"
PACKAGING_DOC = Path(__file__).resolve().parents[1] / "docs" / "packaging-c.md"
PRODUCT_DOC = Path(__file__).resolve().parents[1] / "docs" / "argos-product-definition.md"
ACCEPTANCE_DOC = Path(__file__).resolve().parents[1] / "docs" / "acceptance-checklist.md"
MULTIRUN_DOC = Path(__file__).resolve().parents[1] / "docs" / "multirun.md"
TUI_APP = Path(__file__).resolve().parents[1] / "argos" / "tui" / "app.py"


def _readme_command_rows() -> set[str]:
    rows = set()
    for line in README.read_text().splitlines():
        if line.startswith("| `/"):
            rows.add(line.split("`", 2)[1].lstrip("/"))
    return rows


def _project_version() -> str:
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    assert match
    return match.group(1)


def test_public_docs_use_current_fresh_version():
    """Internal documentation."""
    version = _project_version()
    readme = README.read_text()
    packaging = PACKAGING_DOC.read_text()
    assert f"**Current version: v{version}.**" in readme
    assert "**Current version: v0.1.0.**" not in readme
    assert "GitHub release `v0.1.0` 已存在" not in packaging


def test_readme_model_command_mentions_restart_required():
    row = next(line for line in README.read_text().splitlines() if line.startswith("| `/model` |"))
    assert "restart" in row.lower()


def test_readme_permissions_command_matches_reload_semantics():
    row = next(line for line in README.read_text().splitlines() if line.startswith("| `/permissions` |"))
    assert "reload" in row.lower()
    assert "change the current approval level" not in row


def test_readme_lists_setup_tui_command():
    row = next(line for line in README.read_text().splitlines() if line.startswith("| `/setup` |"))
    assert "status" in row.lower()


def test_readme_lists_public_tui_commands():
    missing = set(COMMAND_NAMES) - _readme_command_rows()
    assert missing == set()


def test_readme_keyboard_bindings_include_right_panel_cycle():
    text = README.read_text()
    assert "**`Ctrl+O`**" in text
    assert "right panel" in text.lower()


def test_readme_sandbox_docs_distinguish_codeact_from_broker_web():
    text = README.read_text()
    sandbox_section = text.split("### OS sandbox (opt-in)", 1)[1].split("\n### ", 1)[0]

    assert "CodeAct" in sandbox_section
    assert "web_search` / `web_extract" in sandbox_section
    assert "host-side broker" in sandbox_section


def test_public_security_docs_do_not_overclaim_broker_for_raw_codeact():
    """Default-off OS sandbox means docs must not imply raw Python is broker-contained."""
    readme = README.read_text()
    security = SECURITY.read_text()
    readme_flat = " ".join(readme.split())
    security_flat = " ".join(security.split())

    assert "broker is the *only*\n  path to side effects" not in readme
    assert "broker is the only path to\n   side effects" not in readme
    assert "every side effect passes egress-policy checks" not in security

    assert "Declared privileged tools cross the broker" in readme_flat
    assert "model-authored Python" in readme_flat
    assert "declared privileged tool calls" in security_flat.lower()


def test_readme_ctrl_c_binding_matches_tui_behavior():
    text = README.read_text()
    assert "**`Ctrl+C`** — quit the TUI." not in text
    assert "**`Ctrl+C`**" in text
    assert "interrupt" in text.lower()
    assert "press twice" in text.lower()


def test_readme_test_command_mentions_slow_tests_are_opt_in():
    text = README.read_text()
    assert "excludes slow tests" in text
    assert "uv run pytest -m slow -q --no-cov" in text


def test_agents_targeted_pytest_examples_disable_coverage_gate():
    text = AGENTS.read_text()
    assert "uv run pytest tests/test_loop.py::test_name --no-cov" in text
    assert "uv run pytest tests/test_verify_gate.py -q --no-cov" in text
    assert "uv run pytest tests/workflow/test_spec.py -q --no-cov" in text


def test_contributing_uses_agents_as_project_guide():
    text = CONTRIBUTING.read_text()
    assert "from CLAUDE.md" not in text
    assert "project CLAUDE.md conventions" not in text
    assert "AGENTS.md" in text


def test_daemon_docs_do_not_hardcode_default_socket_path():
    combined = CONTRIBUTING.read_text() + "\n" + PRODUCT_DOC.read_text()
    assert "~/.argos/daemon.sock" not in combined
    assert "Argos config directory" in combined


def test_security_doc_uses_config_dir_and_current_sandbox_names():
    text = SECURITY.read_text()
    assert "Argos config directory" in text
    assert "~/.argos/hooks.json" not in text
    assert "Seatbelt" in text
    assert "bwrap" in text


def test_security_doc_matches_current_binary_release_status():
    text = SECURITY.read_text()
    lower = text.lower()
    assert "no published binary assets" in lower
    assert "macOS only" not in text
    assert "Linux/Windows in #13" not in text


def test_readme_loop_command_matches_verify_semantics():
    row = next(line for line in README.read_text().splitlines() if line.startswith("| `/loop` |"))
    assert "repeatedly" not in row.lower()
    assert "verify" in row.lower()


def test_readme_eval_command_shows_compare_task_model_syntax():
    row = next(line for line in README.read_text().splitlines() if line.startswith("| `/eval` |"))
    assert "`/eval compare <task_id>[:<model>] <task_id>[:<model>]`" in row
    assert "`/eval compare <a> <b>`" not in row


def test_tui_eval_internal_docs_match_compare_syntax():
    text = TUI_APP.read_text()
    assert "compare <task_id>[:<model>] <task_id>[:<model>]" in text
    assert "compare <a> <b>" not in text


def test_readme_setup_mentions_existing_environment_variable():
    text = README.read_text()
    assert "existing environment variable" in text
    assert "paste a key" not in text


def test_readme_trust_summary_matches_current_modes():
    text = README.read_text()
    assert "No five-level dial" not in text
    assert "hidden `/trust paranoid`" in text


def test_readme_pypi_install_text_is_release_neutral():
    text = README.read_text()
    assert "`argos-agent` is not on PyPI yet" not in text
    assert "PyPI, and platform packages" not in text
    assert "will 404" not in text
    assert "pip install argos-agent" in text


def test_readme_launch_install_surface_is_small():
    """Internal documentation."""
    section = README.read_text().split("## Install", 1)[1].split("\n---", 1)[0]
    assert "uv tool install argos-agent" in section
    assert "curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/v0.1.1/install.sh | bash" in section
    assert "bootstraps" in section
    assert "uses `uv tool`" in section
    assert "uv tool update-shell" in section
    assert "### From source" in section
    assert "Deferred binary/package-manager channels" in section
    for term in ("Homebrew", "WinGet", "winget", "Nix", "AppImage", ".deb", ".rpm"):
        assert term not in section


def test_readme_does_not_mention_removed_daemon_flag():
    assert "--with-daemon" not in README.read_text()


def test_public_docs_do_not_mention_removed_daemon_flag():
    assert "--with-daemon" not in MULTIRUN_DOC.read_text()


def test_packaging_doc_does_not_claim_macos_binary_is_live():
    text = PACKAGING_DOC.read_text()
    assert "macOS arm64 已发布" not in text


def test_packaging_doc_marks_channel_commands_as_planned():
    text = PACKAGING_DOC.read_text()
    assert "首发安装面" in text
    assert "Deferred packaging backlog" in text
    assert "计划中的各通道命令" not in text
    assert "## 各通道安装命令(按推荐顺序)" not in text
    assert "用 pip install / brew install / AppImage 兜底" not in text
    assert "| `brew install argos` 报 404 | tap 仓没建好 | `brew tap tungoldshou/argos` 先建 |" not in text


def test_product_doc_does_not_claim_macos_binary_is_live():
    text = PRODUCT_DOC.read_text()
    assert "macOS arm64 已发布" not in text


def test_product_doc_test_gate_matches_default_slow_policy():
    text = PRODUCT_DOC.read_text()
    assert "≈3000" not in text
    assert "打包 binary smoke 全绿" not in text
    assert "uv run pytest -m slow -q --no-cov" in text


def test_setup_docs_do_not_imply_paste_key_is_required():
    combined = PRODUCT_DOC.read_text() + "\n" + ACCEPTANCE_DOC.read_text()
    assert "填 key" not in combined
    assert "provider+key" not in combined
    assert "key 来源" in combined


def test_acceptance_doc_uses_config_dir_for_mcp_path():
    text = ACCEPTANCE_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/mcp.json" not in text


def test_setup_doc_matches_current_wizard_defaults():
    text = (README.parent / "docs" / "setup-wizard.md").read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "price information" not in text
    assert "default: 4096" in text
    assert "claude-sonnet-4-6" in text
    assert "MiniMax-M3" in text
    assert "existing environment variable" in text
    assert "`~/.argos/config.json` and `~/.argos/.env` directly" not in text
    assert "writes `~/.argos/config.json` and\n`~/.argos/.env`" not in text


def test_setup_doc_mentions_env_local_status_fallback():
    text = (README.parent / "docs" / "setup-wizard.md").read_text()
    assert ".env.local" in text
    assert "development fallback" in text


def test_readme_memory_paths_follow_config_dir_wording():
    text = README.read_text()
    assert "Argos config directory" in text
    assert "`~/.argos/memory/{user,projects/<hash>,skills/<name>,sessions/<sid>}.jsonl`" not in text


def test_auto_memory_doc_uses_current_project_guide_and_config_dir():
    text = AUTO_MEMORY_DOC.read_text()
    assert "写 AGENTS.md" in text
    assert "### 1. 写 CLAUDE.md(项目根)" not in text
    assert "Argos config directory" in text
    assert "`~/.argos/memory/user.jsonl`" not in text
    assert "`~/.argos/CLAUDE.md`" not in text


def test_eval_doc_uses_config_dir_for_data_paths():
    text = EVAL_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/eval" not in text


def test_eval_source_docs_do_not_hardcode_default_eval_root():
    combined = "\n".join(
        path.read_text()
        for path in (EVAL_CLI, EVAL_COMPARE, EVAL_CORPUS, EVAL_RESULTS, EVAL_RUNNER)
    )
    assert "ARGOS_CONFIG_DIR/eval" in combined
    assert "~/.argos/eval" not in combined


def test_routing_doc_uses_config_dir_for_config_path():
    text = PER_TASK_ROUTING_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/config.json" not in text


def test_external_surface_source_docs_use_config_dir_for_config_paths():
    combined = "\n".join(path.read_text() for path in EXTERNAL_SURFACE_SOURCE_DOCS)
    assert "ARGOS_CONFIG_DIR/mcp.json" in combined
    assert "ARGOS_CONFIG_DIR/lsp.json" in combined
    assert "ARGOS_CONFIG_DIR/hooks.json" in combined
    assert "~/.argos/mcp.json" not in combined
    assert "~/.argos/lsp.json" not in combined
    assert "~/.argos/hooks.json" not in combined
    assert "~/.argos/{hooks,lsp,mcp}.json" not in combined


def test_tui_command_source_docs_use_config_dir_for_config_paths():
    text = TUI_APP.read_text()
    assert "ARGOS_CONFIG_DIR/hooks.json" in text
    assert "ARGOS_CONFIG_DIR/lsp.json" in text
    assert "ARGOS_CONFIG_DIR/permissions.json" in text
    assert "ARGOS_CONFIG_DIR/mcp.json" in text
    assert "~/.argos/hooks.json" not in text
    assert "~/.argos/lsp.json" not in text
    assert "~/.argos/permissions.json" not in text
    assert "~/.argos/mcp.json" not in text


def test_config_source_docs_use_config_dir_for_config_and_env_paths():
    combined = "\n".join(path.read_text() for path in CONFIG_SOURCE_DOCS)
    assert "ARGOS_CONFIG_DIR/config.json" in combined
    assert "ARGOS_CONFIG_DIR/.env" in combined
    assert "~/.argos/config.json" not in combined
    assert "~/.argos/.env" not in combined


def test_persistence_source_docs_use_config_dir_for_state_paths():
    combined = "\n".join(path.read_text() for path in PERSISTENCE_SOURCE_DOCS)
    assert "ARGOS_CONFIG_DIR/snapshots" in combined
    assert "ARGOS_CONFIG_DIR/ledger" in combined
    assert "ARGOS_CONFIG_DIR/argos.db" in combined
    assert "ARGOS_CONFIG_DIR/runs/index.json" in combined
    assert "ARGOS_CONFIG_DIR/daemon.pid" in combined
    assert "ARGOS_CONFIG_DIR/worktrees" in combined
    assert "~/.argos/snapshots" not in combined
    assert "~/.argos/ledger" not in combined
    assert "~/.argos/argos.db" not in combined
    assert "~/.argos/runs/index.json" not in combined
    assert "~/.argos/daemon.pid" not in combined
    assert "~/.argos/worktrees" not in combined


def test_runtime_source_docs_use_config_dir_for_workspace_and_verify_paths():
    combined = "\n".join(path.read_text() for path in RUNTIME_SOURCE_DOCS)
    assert "ARGOS_CONFIG_DIR/workspace" in combined
    assert "ARGOS_CONFIG_DIR/verify" in combined
    assert "ARGOS_CONFIG_DIR/mcp.json" in combined
    assert "~/.argos/workspace" not in combined
    assert "~/.argos/verify" not in combined
    assert "~/.argos/mcp.json" not in combined


def test_learning_and_skills_source_docs_use_config_dir_paths():
    combined = "\n".join(path.read_text() for path in LEARNING_SKILLS_SOURCE_DOCS)
    assert "ARGOS_CONFIG_DIR/vision_cache.json" in combined
    assert "ARGOS_CONFIG_DIR/learning/candidates" in combined
    assert "ARGOS_CONFIG_DIR/learning" in combined
    assert "ARGOS_CONFIG_DIR/skills/index.json" in combined
    assert "ARGOS_CONFIG_DIR/skills" in combined
    assert "~/.argos/vision_cache.json" not in combined
    assert "~/.argos/learning" not in combined
    assert "~/.argos/skills" not in combined


def test_context_doc_uses_config_dir_for_config_path():
    text = CONTEXT_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/config.json" not in text


def test_skills_curator_doc_uses_config_dir_for_skills_path():
    text = SKILLS_CURATOR_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/skills" not in text


def test_voice_image_doc_uses_config_dir_for_stt_paths():
    text = VOICE_IMAGE_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/config.json" not in text
    assert "~/.argos/.env" not in text


def test_dream_doc_uses_config_dir_for_state_paths():
    text = DREAM_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/dreams" not in text
    assert "~/.argos/conductor" not in text


def test_dream_source_docs_use_config_dir_for_state_paths():
    combined = DREAM_DAEMON.read_text() + "\n" + CONDUCTOR_ORDERS.read_text()
    assert "ARGOS_CONFIG_DIR/dreams" in combined
    assert "ARGOS_CONFIG_DIR/conductor" in combined
    assert "~/.argos/dreams" not in combined
    assert "~/.argos/conductor" not in combined


def test_multirun_doc_uses_config_dir_for_worktree_paths():
    text = MULTIRUN_DOC.read_text()
    assert "ARGOS_CONFIG_DIR" in text
    assert "~/.argos/worktrees" not in text


def test_setup_docs_and_help_use_pricing_per_million_tokens(capsys):
    from argos.__main__ import _build_parser

    text = (README.parent / "docs" / "setup-wizard.md").read_text()
    assert "per 1M input tokens" in text
    assert "per input token" not in text
    assert "0.000003" not in text

    parser = _build_parser()
    try:
        parser.parse_args(["setup", "--help"])
    except SystemExit as e:
        assert e.code == 0

    help_text = capsys.readouterr().out
    assert '"price_in": 3.00, "price_out": 15.00' in help_text
    assert "0.000003" not in help_text
