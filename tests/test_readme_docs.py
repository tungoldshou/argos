from pathlib import Path

from argos.tui.commands import COMMAND_NAMES


README = Path(__file__).resolve().parents[1] / "README.md"
AGENTS = Path(__file__).resolve().parents[1] / "AGENTS.md"
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


def test_readme_does_not_mention_removed_daemon_flag():
    assert "--with-daemon" not in README.read_text()


def test_public_docs_do_not_mention_removed_daemon_flag():
    assert "--with-daemon" not in MULTIRUN_DOC.read_text()


def test_packaging_doc_does_not_claim_macos_binary_is_live():
    text = PACKAGING_DOC.read_text()
    assert "macOS arm64 已发布" not in text


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


def test_setup_doc_matches_current_wizard_defaults():
    text = (README.parent / "docs" / "setup-wizard.md").read_text()
    assert "price information" not in text
    assert "default: 4096" in text
    assert "claude-sonnet-4-6" in text
    assert "MiniMax-M3" in text
    assert "existing environment variable" in text
    assert "`~/.argos/config.json` and `~/.argos/.env` directly" not in text
    assert "writes `~/.argos/config.json` and\n`~/.argos/.env`" not in text


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
