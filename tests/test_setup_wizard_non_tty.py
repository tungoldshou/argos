"""setup_wizard 在非 TTY(管道/CI)下 reader EOFError 时的友好兜底(2026-06-09)。

bug 复现:`argos setup` 在 stdin 是管道 / CI runner 跑时,`input()` 抛 EOFError,
setup_wizard.run() 没接,asyncio.run 把 traceback 打到 stderr 退出。用户看到的
是 Python 异常栈,完全不知道"setup 需要真终端"或"可以手工写 config"。

修法:setup_wizard.run 把 while True 包 try/except EOFError,捕到就写一条友好提示
(指明真终端 / 手工 config.json + .env)然后 return,不抛。
"""
from __future__ import annotations

import pytest


def _writer():
    return lambda *args, **kwargs: lines.append(" ".join(str(a) for a in args))


def test_setup_wizard_eof_returns_cleanly_with_friendly_message(tmp_path, monkeypatch):
    """非 TTY(管道/CI)→ reader EOFError → run() 不抛、写友好提示、正常 return。"""
    import asyncio
    from argos import setup_wizard

    lines: list[str] = []
    calls = {"n": 0}

    def reader(prompt=""):
        calls["n"] += 1
        raise EOFError  # 模拟 stdin 关掉(管道/CI runner)

    def writer(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    # tmp_path 隔离 config_dir,不污染 ~/.argos
    asyncio.run(setup_wizard.run(reader=reader, writer=writer, config_dir=tmp_path))

    assert calls["n"] == 1, f"reader 应被调 1 次(EOF 立即返),实际 {calls['n']}"
    msg = "\n".join(lines)
    # 友好兜底三条要素:解释原因 / 指去真终端 / 指手工 config
    assert "终端" in msg or "terminal" in msg.lower(), (
        f"应说明 stdin 不是真终端,实际 msg={msg!r}"
    )
    assert "config" in msg.lower() or "setup" in msg.lower(), (
        f"应指向手工 config.json/.env 或重新跑 setup,实际 msg={msg!r}"
    )


def test_setup_wizard_eof_mid_loop_also_handled(tmp_path):
    """中段 EOF(用户答了 provider 后 stdin 突然关)也走同一兜底。"""
    import asyncio
    from argos import setup_wizard

    lines: list[str] = []
    call_count = {"n": 0}

    def reader(prompt=""):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "1"  # provider = 第一个
        raise EOFError  # 第二个 reader 调用就 EOF

    def writer(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    asyncio.run(setup_wizard.run(reader=reader, writer=writer, config_dir=tmp_path))

    msg = "\n".join(lines)
    assert "终端" in msg or "terminal" in msg.lower(), (
        f"中途 EOF 也应走友好兜底,实际 msg={msg!r}"
    )
