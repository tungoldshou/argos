# tests/test_cli_setup.py
def test_parser_has_setup_subcommand():
    from argos_agent.__main__ import _build_parser
    # setup 作为子命令或 --setup flag;约定:子命令 argv ["setup"]
    p = _build_parser()
    ns = p.parse_args(["setup"])
    assert getattr(ns, "command", None) == "setup" or getattr(ns, "setup", False)


def test_setup_subcommand_dispatches_to_wizard(monkeypatch):
    """argv ['setup'] 真的调到 setup_wizard.run(不只是 parser 能解析到子命令)。"""
    import argos_agent.__main__ as M
    called = {}

    async def fake_run(*, reader, writer, **kw):
        called["ran"] = True

    monkeypatch.setattr("argos_agent.setup_wizard.run", fake_run)
    monkeypatch.setattr("sys.argv", ["argos", "setup"])
    M.main()
    assert called.get("ran") is True
