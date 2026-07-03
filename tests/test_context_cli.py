from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from argos.cli import context as _cli_ctx


@dataclass
class _FakeTier:
    context_window: int = 200_000


@dataclass
class _FakeModel:
    tier: _FakeTier
    last_usage: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.last_usage is None:
            self.last_usage = {"input_tokens": 4200, "output_tokens": 100,
                                "cache_read": 0, "cache_creation": 0}


class _FakeStore:
    def get_messages(self, _sid: str) -> list:
        return [{"role": "user", "content": "hi"}]


@dataclass
class _FakeLoop:
    _model: _FakeModel
    store: _FakeStore

    def _build_system(self, _g: str) -> str:
        return "sys-prompt-content"

    def _tool_signatures_block(self) -> str:
        return "tool-sigs"


class _FakeRuntime:
    def __init__(self) -> None:
        self.store = _FakeStore()
        self.workspace = Path(".")
        self.loop = _FakeLoop(
            _FakeModel(_FakeTier(context_window=200_000)),
            self.store,
        )


def _install_fake_runtime(monkeypatch):
    import argos.app_factory as _af
    fake = _FakeRuntime()
    monkeypatch.setattr(_af, "_active_run", fake, raising=False)


def test_cli_context_show_text(monkeypatch, capsys):
    _install_fake_runtime(monkeypatch)
    args = _cli_ctx.argparse.Namespace(json=False, session=None)
    rc = _cli_ctx.cmd_show(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Argos Context Breakdown" in out
    assert "total" in out


def test_cli_context_show_json(monkeypatch, capsys):
    _install_fake_runtime(monkeypatch)
    args = _cli_ctx.argparse.Namespace(json=True, session=None)
    rc = _cli_ctx.cmd_show(args)
    out = capsys.readouterr().out
    assert rc == 0
    parsed = json.loads(out)
    assert "system" in parsed and "memory" in parsed and "tools" in parsed and "messages" in parsed
    assert "total" in parsed and "window" in parsed and "health" in parsed


def test_cli_context_show_with_session(monkeypatch, capsys):
    _install_fake_runtime(monkeypatch)
    args = _cli_ctx.argparse.Namespace(json=False, session="abc")
    rc = _cli_ctx.cmd_show(args)
    assert rc == 0
    assert "Argos Context Breakdown" in capsys.readouterr().out


def test_cli_context_show_no_runtime(monkeypatch, capsys):
    import argos.app_factory as _af
    monkeypatch.setattr(_af, "_active_run", None, raising=False)
    args = _cli_ctx.argparse.Namespace(json=False, session=None)
    rc = _cli_ctx.cmd_show(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "total" in out
