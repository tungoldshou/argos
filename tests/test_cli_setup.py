# tests/test_cli_setup.py
def test_parser_has_setup_subcommand():
    from argos.__main__ import _build_parser
    p = _build_parser()
    ns = p.parse_args(["setup"])
    assert getattr(ns, "command", None) == "setup" or getattr(ns, "setup", False)


def test_parser_has_setup_status_subcommand():
    from argos.__main__ import _build_parser
    p = _build_parser()
    ns = p.parse_args(["setup", "status"])
    assert ns.command == "setup"
    assert ns.setup_action == "status"


def test_setup_help_example_matches_current_defaults(capsys):
    from argos.__main__ import _build_parser
    p = _build_parser()
    try:
        p.parse_args(["setup", "--help"])
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out
    assert "claude-sonnet-4-6" in out
    assert '"max_tokens": 4096' in out
    assert "8096" not in out


def test_setup_help_allows_existing_environment_variable(capsys):
    from argos.__main__ import _build_parser

    p = _build_parser()
    try:
        p.parse_args(["setup", "--help"])
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out
    assert "existing environment variable" in out or "已有环境变量" in out
    assert "writes ~/.argos/config.json (profile table + active pointer) and ~/.argos/.env" not in out


def test_setup_help_uses_configured_argos_dir(tmp_path, monkeypatch, capsys):
    from argos.__main__ import _build_parser

    cfg_dir = tmp_path / "custom-config"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    p = _build_parser()
    try:
        p.parse_args(["setup", "--help"])
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out
    assert str(cfg_dir / "config.json") in out
    assert str(cfg_dir / ".env") in out
    assert "~/.argos" not in out


def test_setup_help_advanced_mentions_image_input_override(capsys):
    from argos.__main__ import _build_parser

    p = _build_parser()
    try:
        p.parse_args(["setup", "--help"])
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out.lower()
    assert "image input" in out or "图片输入" in out


def test_top_level_help_setup_description_mentions_key_source(capsys):
    from argos.__main__ import _build_parser

    p = _build_parser()
    try:
        p.parse_args(["--help"])
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out
    assert "key source" in out or "key 来源" in out or "已有环境变量" in out


def test_top_level_help_sandbox_distinguishes_codeact_from_broker_web(capsys):
    from argos.__main__ import _build_parser

    p = _build_parser()
    try:
        p.parse_args(["--help"])
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out
    assert "CodeAct" in out
    assert "web_search/web_extract" in out
    assert "broker" in out


def test_bare_group_subcommands_print_help_instead_of_launching_tui(capsys):
    from argos.__main__ import _build_parser

    p = _build_parser()
    for command in ("skills", "eval", "context"):
        ns = p.parse_args([command])
        assert ns.command == command
        assert callable(getattr(ns, "func", None))
        rc = ns.func(ns)
        out = capsys.readouterr().out
        assert f"usage: argos {command}" in out
        assert rc != 0


def test_setup_subcommand_dispatches_to_wizard(monkeypatch):
    import argos.__main__ as M
    called = {}

    async def fake_run(*, reader, writer, **kw):
        called["ran"] = True

    monkeypatch.setattr("argos.setup_wizard.run", fake_run)
    monkeypatch.setattr("sys.argv", ["argos", "setup"])
    M.main()
    assert called.get("ran") is True


def test_setup_cli_reader_hides_pasted_api_key(monkeypatch):
    import argos.__main__ as M
    from argos.i18n import t

    seen: dict[str, str] = {}

    async def fake_run(*, reader, writer, **kw):
        seen["plain"] = reader("plain prompt:")
        seen["secret"] = reader(t("setup.prompt_paste_key"))

    monkeypatch.setattr("argos.setup_wizard.run", fake_run)
    monkeypatch.setattr("sys.argv", ["argos", "setup"])
    monkeypatch.setattr("builtins.input", lambda prompt="": "plain")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "secret")

    M.main()

    assert seen == {"plain": "plain", "secret": "secret"}


def test_setup_prints_next_steps_after_save(tmp_path, monkeypatch):
    import asyncio
    from argos import setup_wizard as sw

    monkeypatch.setenv("ARGOS_NO_ARROW_SELECT", "1")

    async def fake_probe(*args, **kwargs):
        return sw.ProbeResult(True, True, "ok", "connected")

    monkeypatch.setattr(sw, "_probe_with_status", fake_probe)

    answers = iter([
        "1",        # provider
        "",         # model default
        "",         # key method default paste
        "sk-test",  # key
        "",         # deep probe no
        "",         # profile name default
        "n",        # add another
    ])
    out: list[str] = []

    asyncio.run(sw.run(
        reader=lambda prompt="": next(answers),
        writer=out.append,
        config_dir=tmp_path / ".argos",
    ))

    text = "\n".join(out)
    assert "argos" in text
    assert "--model" in text


def test_setup_status_prints_active_profile(tmp_path, monkeypatch, capsys):
    from argos.setup_wizard import write_profile
    import argos.__main__ as M

    cfg_dir = tmp_path / ".argos"
    write_profile(
        config_dir=cfg_dir,
        name="fast",
        protocol="openai",
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key="sk-test",
        api_key_env="FAST_KEY",
        set_active=True,
    )
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr("sys.argv", ["argos", "setup", "status"])
    monkeypatch.setattr(M, "_spawn_update_check", lambda: None)

    try:
        M.main()
    except SystemExit as e:
        assert e.code == 0

    out = capsys.readouterr().out
    assert "fast" in out
    assert "test-model" in out
    assert "FAST_KEY" in out
    assert "found" in out or "可用" in out


def test_setup_status_skips_update_check(tmp_path, monkeypatch):
    import argos.__main__ as M

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / ".argos"))
    monkeypatch.setattr("sys.argv", ["argos", "setup", "status"])
    monkeypatch.setattr("argos.setup_wizard.print_status", lambda *, writer: writer("ok"))

    called = False

    def fake_update_check():
        nonlocal called
        called = True

    monkeypatch.setattr(M, "_spawn_update_check", fake_update_check)
    M.main()

    assert called is False


def test_selftest_skips_update_check(monkeypatch):
    import argos.__main__ as M

    monkeypatch.setattr("sys.argv", ["argos", "--selftest"])
    monkeypatch.setattr(M, "_run_selftest", lambda: 0)

    called = False

    def fake_update_check():
        nonlocal called
        called = True

    monkeypatch.setattr(M, "_spawn_update_check", fake_update_check)
    try:
        M.main()
    except SystemExit as e:
        assert e.code == 0

    assert called is False


def test_selftest_verify_cmd_uses_current_interpreter(monkeypatch):
    import shlex
    import sys
    import argos.__main__ as M

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/python3")
    cmd = M._selftest_verify_cmd()

    assert cmd.startswith(shlex.quote(sys.executable))


def test_selftest_verify_cmd_avoids_frozen_binary(monkeypatch):
    import sys
    import argos.__main__ as M

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/argos")

    assert M._selftest_verify_cmd().startswith("python3 ")


def test_subcommands_skip_startup_update_check(monkeypatch):
    import argos.__main__ as M

    monkeypatch.setattr("sys.argv", ["argos", "self-update"])
    monkeypatch.setattr(M, "_cmd_self_update", lambda _args: 0)

    called = False

    def fake_update_check():
        nonlocal called
        called = True

    monkeypatch.setattr(M, "_spawn_update_check", fake_update_check)
    try:
        M.main()
    except SystemExit as e:
        assert e.code == 0

    assert called is False


def test_default_startup_without_key_exits_with_setup_hint(tmp_path, monkeypatch, capsys):
    """No configured key should exit before TUI starts, with a setup hint."""
    import pytest
    import argos.__main__ as M
    import argos.app_factory as af
    from argos.tui.app import ArgosApp

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / ".argos"))
    monkeypatch.setenv("ARGOS_DB_PATH", str(tmp_path / "argos.db"))
    monkeypatch.setattr(af.config, "DEFAULT_KEYS", [])
    monkeypatch.setattr(M, "_spawn_update_check", lambda: None)
    monkeypatch.setattr("sys.argv", ["argos"])

    ran_tui = False

    def fake_run(self):  # noqa: ANN001
        nonlocal ran_tui
        ran_tui = True

    monkeypatch.setattr(ArgosApp, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        M.main()

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "argos setup" in err
    assert ran_tui is False


def test_setup_status_rejects_invalid_profile(tmp_path):
    import json
    from argos import setup_wizard

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({
        "active": "bad",
        "models": {
            "bad": {
                "protocol": "anthropc",
                "base_url": "https://api.example.com",
                "model": "test-model",
                "api_key_env": "BAD_KEY",
            },
        },
    }))

    out: list[str] = []
    setup_wizard.print_status(writer=out.append, config_dir=cfg_dir)

    text = "\n".join(out)
    assert "not configured" in text or "未配置" in text
    assert "test-model" not in text


def test_setup_status_handles_config_read_error(tmp_path, monkeypatch):
    import pathlib
    from argos import setup_wizard

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    config_path = cfg_dir / "config.json"
    config_path.write_text("{}")
    real_read_text = pathlib.Path.read_text

    def fail_config_read(self, *args, **kwargs):
        if self == config_path:
            raise OSError("permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", fail_config_read)

    out: list[str] = []
    setup_wizard.print_status(writer=out.append, config_dir=cfg_dir)

    text = "\n".join(out)
    assert "permission denied" in text
    assert "argos setup" in text


def test_setup_status_reports_env_fallback_without_config(tmp_path, monkeypatch):
    import importlib
    from argos import config as C
    from argos import setup_wizard

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / ".argos"))
    monkeypatch.setenv("ARGOS_LLM_KEY", "sk-env")
    monkeypatch.setenv("ARGOS_LLM_MODEL", "env-model")
    monkeypatch.setenv("ARGOS_LLM_BASE", "https://api.example.com/env")
    importlib.reload(C)

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert "env-model" in text
    assert "ARGOS_LLM_KEY" in text
    assert "found" in text or "可用" in text


def test_setup_status_missing_key_prints_next_step(tmp_path, monkeypatch):
    import importlib
    from argos import config as C
    from argos import setup_wizard

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / ".argos"))
    monkeypatch.delenv("ARGOS_LLM_KEY", raising=False)
    monkeypatch.delenv("VITE_LLM_KEY", raising=False)
    monkeypatch.delenv("VITE_MINIMAX_KEY", raising=False)
    importlib.reload(C)
    monkeypatch.setattr(C, "DEFAULT_KEYS", [])

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert "missing" in text or "缺失" in text
    assert "argos setup" in text


def test_setup_status_labels_env_local_fallback(tmp_path, monkeypatch):
    import importlib
    from argos import config as C
    from argos import setup_wizard

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / ".argos"))
    monkeypatch.delenv("ARGOS_LLM_KEY", raising=False)
    monkeypatch.delenv("VITE_LLM_KEY", raising=False)
    monkeypatch.delenv("VITE_MINIMAX_KEY", raising=False)
    importlib.reload(C)
    monkeypatch.setattr(C, "DEFAULT_KEYS", ["sk-local"])

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert ".env.local" in text
    assert "(environment)" not in text


def test_setup_status_config_path_honors_env_local_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos import setup_wizard

    home = tmp_path / "home"
    cfg_dir = tmp_path / "from-env-local"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ARGOS_CONFIG_DIR", raising=False)
    monkeypatch.setattr(C, "_ENV", {"ARGOS_CONFIG_DIR": str(cfg_dir)})
    setup_wizard.write_profile(
        config_dir=cfg_dir,
        name="local",
        protocol="openai",
        base_url="http://x/v1",
        model="m",
        api_key=None,
        api_key_env="K",
        set_active=True,
    )

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert str(cfg_dir / "config.json") in text
    assert str(home / ".argos" / "config.json") not in text


def test_setup_status_reports_embedding_model(tmp_path, monkeypatch):
    from argos import setup_wizard

    cfg_dir = tmp_path / ".argos"
    setup_wizard.write_profile(
        config_dir=cfg_dir,
        name="main",
        protocol="openai",
        base_url="https://api.example.com/v1",
        model="chat-model",
        api_key="sk-test",
        api_key_env="MAIN_KEY",
        embedding_model="text-embedding-3-small",
        set_active=True,
    )
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert "text-embedding-3-small" in text


def test_setup_status_reports_fts_fallback_without_embedding(tmp_path, monkeypatch):
    from argos import setup_wizard

    cfg_dir = tmp_path / ".argos"
    setup_wizard.write_profile(
        config_dir=cfg_dir,
        name="main",
        protocol="openai",
        base_url="https://api.example.com/v1",
        model="chat-model",
        api_key="sk-test",
        api_key_env="MAIN_KEY",
        set_active=True,
    )
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert "FTS5" in text


def test_setup_status_reports_image_input_auto_when_unset(tmp_path, monkeypatch):
    from argos import setup_wizard

    cfg_dir = tmp_path / ".argos"
    setup_wizard.write_profile(
        config_dir=cfg_dir,
        name="main",
        protocol="openai",
        base_url="https://api.example.com/v1",
        model="chat-model",
        api_key="sk-test",
        api_key_env="MAIN_KEY",
        set_active=True,
    )
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert "Image input" in text or "图片输入" in text
    assert "auto-detect" in text or "自动探测" in text


def test_setup_status_reports_image_input_disabled(tmp_path, monkeypatch):
    import json
    from argos import setup_wizard

    cfg_dir = tmp_path / ".argos"
    setup_wizard.write_profile(
        config_dir=cfg_dir,
        name="main",
        protocol="openai",
        base_url="https://api.example.com/v1",
        model="chat-model",
        api_key="sk-test",
        api_key_env="MAIN_KEY",
        set_active=True,
    )
    config_path = cfg_dir / "config.json"
    cfg = json.loads(config_path.read_text())
    cfg["models"]["main"]["multimodal"] = False
    config_path.write_text(json.dumps(cfg))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))

    out: list[str] = []
    setup_wizard.print_status(writer=out.append)

    text = "\n".join(out)
    assert "Image input" in text or "图片输入" in text
    assert "disabled" in text or "禁用" in text
