"""verify_gate 修复测试 (CONTRACT A §5 + CONTRACT C §17 + #29 env-var typo).

涵盖:
  - Verdict.no_check() 工厂经 Verifier.verify(verify_cmd=None) 返回
  - is_trivial_verify() 可导入谓词
  - ARGOS_BRIDGE_VERIFY_LOCK 新名(#29) + 旧名 ARGSOS_ 向后兼容
"""
from __future__ import annotations

import pytest

from argos.core.verify_gate import Verifier, is_trivial_verify
from argos.core.types import Verdict, TRIVIAL_VERIFY_BINS


# ── CONTRACT C §17: is_trivial_verify ─────────────────────────────────────

class TestIsTrivialVerify:
    def test_echo_is_trivial(self):
        assert is_trivial_verify("echo ok") is True

    def test_true_is_trivial(self):
        assert is_trivial_verify("true") is True

    def test_colon_is_trivial(self):
        assert is_trivial_verify(":") is True

    def test_ls_is_trivial(self):
        assert is_trivial_verify("ls -la") is True

    def test_pytest_is_not_trivial(self):
        assert is_trivial_verify("pytest -q tests/") is False

    def test_cargo_test_is_not_trivial(self):
        assert is_trivial_verify("cargo test") is False

    def test_empty_string_is_trivial(self):
        # 空命令 → 不是有效验证命令
        assert is_trivial_verify("") is False

    def test_all_trivial_bins_covered(self):
        """TRIVIAL_VERIFY_BINS 中每个命令都被 is_trivial_verify 识别为 trivial。"""
        for b in TRIVIAL_VERIFY_BINS:
            assert is_trivial_verify(b) is True, f"{b!r} 应该是 trivial"
            assert is_trivial_verify(f"{b} --some-flag arg") is True, (
                f"{b!r} + flags 应该是 trivial"
            )


# ── CONTRACT A §5: Verifier.verify(None) → Verdict.no_check ──────────────

class TestVerifierNoCheckPath:
    def _make_verifier(self) -> Verifier:
        return Verifier()

    def test_no_verify_cmd_returns_unverifiable(self, tmp_path, monkeypatch):
        """verify_cmd=None → status='unverifiable'(HONESTY 不变)。"""
        import argos.runtime as rt
        monkeypatch.setattr(rt, "detect_tampering", lambda: [])
        monkeypatch.setattr(rt, "current", lambda: type("ctx", (), {
            "workspace": tmp_path,
            "verify_dir": tmp_path / "vd",
        })())
        v = self._make_verifier()
        verdict = v.verify(None, attempts=1)
        assert verdict.status == "unverifiable"

    def test_no_verify_cmd_sets_no_test_true(self, tmp_path, monkeypatch):
        """verify_cmd=None → no_test=True(CONTRACT A §5 标记,供 UI 渲染中性色)。"""
        import argos.runtime as rt
        monkeypatch.setattr(rt, "detect_tampering", lambda: [])
        monkeypatch.setattr(rt, "current", lambda: type("ctx", (), {
            "workspace": tmp_path,
            "verify_dir": tmp_path / "vd",
        })())
        v = self._make_verifier()
        verdict = v.verify(None, attempts=1)
        assert verdict.no_test is True

    def test_tampering_returns_unverifiable_no_test_false(self, tmp_path, monkeypatch):
        """篡改检测 → no_test=False(这是真无法验证,不是无测任务)。"""
        import argos.runtime as rt
        monkeypatch.setattr(rt, "detect_tampering", lambda: ["tests/critical.py"])
        v = self._make_verifier()
        verdict = v.verify(None, attempts=1)
        assert verdict.status == "unverifiable"
        assert verdict.no_test is False
        assert "tests/critical.py" in verdict.tampered

    def test_trivial_verify_cmd_returns_unverifiable_no_test_false(self, tmp_path, monkeypatch):
        """trivial 命令(echo ok) → unverifiable 且 no_test=False(不是无测,是假命令)。"""
        import argos.runtime as rt
        monkeypatch.setattr(rt, "detect_tampering", lambda: [])
        monkeypatch.setattr(rt, "current", lambda: type("ctx", (), {
            "workspace": tmp_path,
            "verify_dir": tmp_path / "vd",
        })())
        v = self._make_verifier()
        verdict = v.verify("echo ok", attempts=1)
        assert verdict.status == "unverifiable"
        assert verdict.no_test is False


# ── #29: ARGOS_BRIDGE_VERIFY_LOCK env var rename + backward compat ─────────

class TestBridgeVerifyLockEnvVar:
    """_on_propose_verify 应同时接受新名(ARGOS_)和旧名(ARGSOS_)。"""

    def _make_loop(self, tmp_path, verify_cmd: str = "pytest"):
        """最小化 AgentLoop 替身,仅测 _on_propose_verify 逻辑。"""
        import types
        from argos.core.loop import AgentLoop, LoopConfig

        cfg = LoopConfig(model_tier="test", verify_cmd=verify_cmd)
        loop = AgentLoop.__new__(AgentLoop)
        # 只设 _on_propose_verify 需要的最小属性
        loop._cfg = cfg
        loop._verify_cmd = None
        loop._verify_rejected = None
        loop._verify_rejected_fstring = False
        loop._workspace = tmp_path
        return loop

    def test_new_env_name_locks_proposal(self, tmp_path, monkeypatch):
        """ARGOS_BRIDGE_VERIFY_LOCK=1(默认) → agent propose 被锁,自有 verify_cmd 时。"""
        monkeypatch.setenv("ARGOS_BRIDGE_VERIFY_LOCK", "1")
        monkeypatch.delenv("ARGSOS_BRIDGE_VERIFY_LOCK", raising=False)
        loop = self._make_loop(tmp_path, verify_cmd="pytest -q")
        accepted = loop._on_propose_verify("cargo test")
        assert accepted is False  # 锁住,agent 不能覆盖
        assert loop._verify_rejected is not None

    def test_new_env_name_unlocks_when_zero(self, tmp_path, monkeypatch):
        """ARGOS_BRIDGE_VERIFY_LOCK=0 → 解锁,agent propose 被接受。"""
        monkeypatch.setenv("ARGOS_BRIDGE_VERIFY_LOCK", "0")
        monkeypatch.delenv("ARGSOS_BRIDGE_VERIFY_LOCK", raising=False)
        loop = self._make_loop(tmp_path, verify_cmd="pytest -q")
        accepted = loop._on_propose_verify("cargo test")
        assert accepted is True
        assert loop._verify_cmd == "cargo test"

    def test_old_typo_env_name_still_unlocks(self, tmp_path, monkeypatch):
        """旧拼写 ARGSOS_BRIDGE_VERIFY_LOCK=0 → 向后兼容,仍解锁。"""
        monkeypatch.setenv("ARGOS_BRIDGE_VERIFY_LOCK", "1")   # 新名=锁住
        monkeypatch.setenv("ARGSOS_BRIDGE_VERIFY_LOCK", "0")  # 旧名=解锁 → 优先解锁
        loop = self._make_loop(tmp_path, verify_cmd="pytest -q")
        accepted = loop._on_propose_verify("cargo test")
        assert accepted is True
