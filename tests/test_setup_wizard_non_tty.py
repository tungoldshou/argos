from __future__ import annotations

import pytest


def _writer():
    return lambda *args, **kwargs: lines.append(" ".join(str(a) for a in args))


def test_setup_wizard_eof_returns_cleanly_with_friendly_message(tmp_path, monkeypatch):
    import asyncio
    from argos import setup_wizard

    lines: list[str] = []
    calls = {"n": 0}

    def reader(prompt=""):
        calls["n"] += 1
        raise EOFError

    def writer(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    asyncio.run(setup_wizard.run(reader=reader, writer=writer, config_dir=tmp_path))

    assert calls["n"] == 1, f"reader 应被调 1 次(EOF 立即返),实际 {calls['n']}"
    msg = "\n".join(lines)
    assert "终端" in msg or "terminal" in msg.lower(), (
        f"应说明 stdin 不是真终端,实际 msg={msg!r}"
    )
    assert "config" in msg.lower() or "setup" in msg.lower(), (
        f"应指向手工 config.json/.env 或重新跑 setup,实际 msg={msg!r}"
    )
    assert "existing environment variable" in msg or "已有环境变量" in msg


def test_setup_wizard_eof_mid_loop_also_handled(tmp_path):
    import asyncio
    from argos import setup_wizard

    lines: list[str] = []
    call_count = {"n": 0}

    def reader(prompt=""):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "1"
        raise EOFError

    def writer(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    asyncio.run(setup_wizard.run(reader=reader, writer=writer, config_dir=tmp_path))

    msg = "\n".join(lines)
    assert "终端" in msg or "terminal" in msg.lower(), (
        f"中途 EOF 也应走友好兜底,实际 msg={msg!r}"
    )


def test_setup_wizard_keyboard_interrupt_returns_cleanly(tmp_path):
    """Ctrl+C during setup should not leak a Python traceback."""
    import asyncio
    from argos import setup_wizard

    lines: list[str] = []

    def reader(prompt=""):
        raise KeyboardInterrupt

    def writer(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    asyncio.run(setup_wizard.run(reader=reader, writer=writer, config_dir=tmp_path))

    msg = "\n".join(lines)
    assert "cancel" in msg.lower() or "取消" in msg
