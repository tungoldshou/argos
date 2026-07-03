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
        assert is_trivial_verify("") is False

    def test_all_trivial_bins_covered(self):
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
        import argos.runtime as rt
        monkeypatch.setattr(rt, "detect_tampering", lambda: ["tests/critical.py"])
        v = self._make_verifier()
        verdict = v.verify(None, attempts=1)
        assert verdict.status == "unverifiable"
        assert verdict.no_test is False
        assert "tests/critical.py" in verdict.tampered

    def test_trivial_verify_cmd_returns_unverifiable_no_test_false(self, tmp_path, monkeypatch):
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

    def _make_loop(self, tmp_path, verify_cmd: str = "pytest"):
        import types
        from argos.core.loop import AgentLoop, LoopConfig

        cfg = LoopConfig(model_tier="test", verify_cmd=verify_cmd)
        loop = AgentLoop.__new__(AgentLoop)
        loop._cfg = cfg
        loop._verify_cmd = None
        loop._verify_rejected = None
        loop._verify_rejected_fstring = False
        loop._workspace = tmp_path
        return loop

    def test_new_env_name_locks_proposal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARGOS_BRIDGE_VERIFY_LOCK", "1")
        monkeypatch.delenv("ARGSOS_BRIDGE_VERIFY_LOCK", raising=False)
        loop = self._make_loop(tmp_path, verify_cmd="pytest -q")
        accepted = loop._on_propose_verify("cargo test")
        assert accepted is False
        assert loop._verify_rejected is not None

    def test_new_env_name_unlocks_when_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARGOS_BRIDGE_VERIFY_LOCK", "0")
        monkeypatch.delenv("ARGSOS_BRIDGE_VERIFY_LOCK", raising=False)
        loop = self._make_loop(tmp_path, verify_cmd="pytest -q")
        accepted = loop._on_propose_verify("cargo test")
        assert accepted is True
        assert loop._verify_cmd == "cargo test"

    def test_old_typo_env_name_still_unlocks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARGOS_BRIDGE_VERIFY_LOCK", "1")
        monkeypatch.setenv("ARGSOS_BRIDGE_VERIFY_LOCK", "0")
        loop = self._make_loop(tmp_path, verify_cmd="pytest -q")
        accepted = loop._on_propose_verify("cargo test")
        assert accepted is True
