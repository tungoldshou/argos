"""#10 T4+T5 remove + smoke test 测试。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import argos.skills_curator.index as _idx


def _make_skill(*, name: str = "to-remove", enabled: bool = True) -> str:
    return (
        f"---\nname: {name}\nversion: 0.1.0\nauthor: t\n"
        f"description: x\ncapabilities: [read]\n"
        f"enabled: {str(enabled).lower()}\n---\n\n# {name}\n"
    )


# ── T4 remove ────────────────────────────────────────────────


def test_remove_builtin_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.skills_curator.install import InstallError
    from argos.skills_curator.remove import remove
    for n in ("verify", "security-review", "simplify"):
        with pytest.raises(InstallError, match="protected"):
            remove(n)


def test_remove_not_installed_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    from argos.skills_curator.install import InstallError
    from argos.skills_curator.remove import remove
    with pytest.raises(InstallError, match="not_installed"):
        remove("nope")


def test_remove_moves_to_trash(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    skill = tmp_path / "to-remove"
    skill.mkdir()
    (skill / "SKILL.md").write_text(_make_skill(), encoding="utf-8")
    from argos.skills_curator.remove import remove
    r = remove("to-remove")
    assert not (tmp_path / "to-remove").exists()
    assert r.trash_path.exists()
    assert r.trash_path.name.startswith("to-remove-")


def test_remove_recoverable_until_30_days(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    skill = tmp_path / "to-remove"
    skill.mkdir()
    (skill / "SKILL.md").write_text(_make_skill(), encoding="utf-8")
    from argos.skills_curator.remove import remove, TRASH_TTL_S
    before = time.time()
    r = remove("to-remove")
    after = time.time()
    # recoverable_until ∈ (before + 30d, after + 30d)
    assert r.recoverable_until >= before + TRASH_TTL_S - 1
    assert r.recoverable_until <= after + TRASH_TTL_S + 1


# ── T5 smoke test ────────────────────────────────────────────


def test_smoke_test_generic_probe_passes(tmp_path):
    """无 tests/smoke.md → 跑通用探针 → pass."""
    skill_dir = tmp_path / "no-smoke"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_make_skill(name="no-smoke"), encoding="utf-8")
    from argos.skills_curator.smoke import run_smoke_test
    r = run_smoke_test("no-smoke", skill_dir)
    assert r.startswith("pass")


def test_smoke_test_custom_python_block_passes(tmp_path):
    skill_dir = tmp_path / "with-smoke"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_make_skill(name="with-smoke"), encoding="utf-8")
    (skill_dir / "tests").mkdir()
    (skill_dir / "tests" / "smoke.md").write_text(
        "---\nname: with-smoke-smoke\n---\n\n# smoke\n\n```python\nprint('hi')\n```\n",
        encoding="utf-8",
    )
    from argos.skills_curator.smoke import run_smoke_test
    r = run_smoke_test("with-smoke", skill_dir)
    assert r.startswith("pass")


def test_smoke_test_custom_no_python_block_fails(tmp_path):
    skill_dir = tmp_path / "bad-smoke"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_make_skill(name="bad-smoke"), encoding="utf-8")
    (skill_dir / "tests").mkdir()
    (skill_dir / "tests" / "smoke.md").write_text(
        "no code block here\n", encoding="utf-8",
    )
    from argos.skills_curator.smoke import run_smoke_test
    r = run_smoke_test("bad-smoke", skill_dir)
    assert r.startswith("fail")
    assert "no python code block" in r


def test_smoke_test_custom_failing_python_fails(tmp_path):
    skill_dir = tmp_path / "fail-smoke"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_make_skill(name="fail-smoke"), encoding="utf-8")
    (skill_dir / "tests").mkdir()
    (skill_dir / "tests" / "smoke.md").write_text(
        "---\nname: fail-smoke\n---\n\n```python\nimport sys\nsys.exit(7)\n```\n",
        encoding="utf-8",
    )
    from argos.skills_curator.smoke import run_smoke_test
    r = run_smoke_test("fail-smoke", skill_dir)
    assert r.startswith("fail")
    assert "exit=7" in r


def test_smoke_test_timeout_returns_fail(tmp_path, monkeypatch):
    """timeout -> 'fail: timeout'."""
    import subprocess
    import argos.skills_curator.smoke as _smoke
    monkeypatch.setattr(_smoke, "SMOKE_TIMEOUT_S", 0.001)
    skill_dir = tmp_path / "slow-smoke"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(_make_skill(name="slow-smoke"), encoding="utf-8")
    from argos.skills_curator.smoke import run_smoke_test
    r = run_smoke_test("slow-smoke", skill_dir)
    assert r.startswith("fail")
    assert "timeout" in r
