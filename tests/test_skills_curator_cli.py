"""#10 T1+T6 `argos skills` CLI 子命令测试。"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest


def _run_cli(argv: list[str], *, monkeypatch, env_setup=None) -> tuple[int, str, str]:
    """跑 `argos skills <argv>` 走 main(),返 (exit, stdout, stderr)."""
    from argos_agent.__main__ import main
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["argos", "skills", *argv])
    if env_setup:
        env_setup()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = main()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    except Exception as e:  # noqa: BLE001
        rc = 1
        print(f"EXC: {type(e).__name__}: {e}", file=err)
    return rc, out.getvalue(), err.getvalue()


def test_skills_refresh_writes_index(monkeypatch, tmp_path):
    """mock 远端 → 跑 refresh → 写 index.json."""
    from argos_agent.skills_curator.index import _skills_root

    monkeypatch.setattr(_skills_root.__module__ + "._skills_root", lambda: tmp_path)
    # 上面写法不工作,改用 module 级别 patch
    import argos_agent.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)

    payload = {
        "version": 1,
        "generated_at": 1717700000.0,
        "skills": [{
            "name": "python-lint", "version": "0.2.1", "author": "test",
            "sha256": "a" * 64, "description": "lint",
            "skill_md_url": "https://example.com/SKILL.md",
            "compatibility": ">=0.1.0",
            "capabilities": ["read", "execute"], "size_bytes": 100,
        }],
    }
    data = json.dumps(payload).encode("utf-8")

    class _Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): self.close()
        def read(self, *a, **k): return super().read(*a, **k)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=10.0: _Resp(data))

    rc, stdout, _ = _run_cli(["refresh"], monkeypatch=monkeypatch)
    assert rc == 0
    assert (tmp_path / "index.json").exists()
    assert "index updated" in stdout


def test_skills_refresh_handles_network_error(monkeypatch, tmp_path):
    import argos_agent.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    import urllib.request, urllib.error
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: (_ for _ in ()).throw(urllib.error.URLError("404")))
    rc, _, stderr = _run_cli(["refresh"], monkeypatch=monkeypatch)
    assert rc == 1
    assert "error" in stderr.lower() or "failed" in stderr.lower()


def test_skills_list_empty(tmp_path, monkeypatch):
    import argos_agent.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    rc, stdout, _ = _run_cli(["list"], monkeypatch=monkeypatch)
    assert rc == 0
    assert "no skills" in stdout.lower() or "installed" in stdout.lower()


def test_skills_list_with_installed(tmp_path, monkeypatch):
    import argos_agent.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    # 装一个 skill
    skill_dir = tmp_path / "user-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: user-skill\nversion: 0.1.0\nauthor: u\n"
        "capabilities: [read]\nenabled: true\ndescription: user\n---\n\nbody\n",
        encoding="utf-8",
    )
    rc, stdout, _ = _run_cli(["list"], monkeypatch=monkeypatch)
    assert rc == 0
    assert "user-skill" in stdout


def test_skills_install_unknown_errors(tmp_path, monkeypatch):
    import argos_agent.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    # 无 cache → 自动 refresh;mock refresh 失败
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: (_ for _ in ()).throw(TimeoutError("no net")))
    rc, _, stderr = _run_cli(["install", "no-such-skill"], monkeypatch=monkeypatch)
    assert rc == 1
    assert "error" in stderr.lower()


def test_skills_remove_protected_builtin_errors(tmp_path, monkeypatch):
    import argos_agent.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    rc, _, stderr = _run_cli(["remove", "verify"], monkeypatch=monkeypatch)
    assert rc == 1
    assert "protected" in stderr.lower() or "builtin" in stderr.lower()


def test_skills_test_not_installed(tmp_path, monkeypatch):
    import argos_agent.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    rc, _, stderr = _run_cli(["test", "no-such-skill"], monkeypatch=monkeypatch)
    assert rc == 1
    assert "not installed" in stderr.lower()


def test_skills_help_lists_subcommands(capsys):
    """`argos skills --help` 列子命令(解析层 sanity)."""
    from argos_agent.__main__ import _build_parser
    p = _build_parser()
    try:
        p.parse_args(["skills", "--help"])
    except SystemExit:
        pass
    captured = capsys.readouterr()
    assert "refresh" in captured.out or "refresh" in captured.err


def test_skills_subparser_registers_all_five():
    from argos_agent.__main__ import _build_parser
    p = _build_parser()
    # 直接 parse 5 个子命令
    for sub in ("refresh", "list", "install", "remove", "test"):
        args = p.parse_args(["skills", sub] if sub in ("refresh", "list") else ["skills", sub, "x"])
        assert args.skills_command == sub
