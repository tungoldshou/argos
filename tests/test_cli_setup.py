# tests/test_cli_setup.py
def test_parser_has_setup_subcommand():
    from argos_agent.__main__ import _build_parser
    # setup 作为子命令或 --setup flag;约定:子命令 argv ["setup"]
    p = _build_parser()
    ns = p.parse_args(["setup"])
    assert getattr(ns, "command", None) == "setup" or getattr(ns, "setup", False)
