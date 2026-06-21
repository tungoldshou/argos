"""Sandbox shell fixes — failing tests first (TDD).

Fix 1 (P0): run_command on non-darwin must NOT run uncaged.
  - When a Linux bwrap/unshare backend is available → route through it.
  - When NO backend available → honest-refuse (ok=False, no subprocess).

Network valve (P1, honesty fix 2026-06-21): the run_command network valve is an
all-or-nothing approval gate, NOT a per-host filter (the OS sandbox can't host-filter
a subprocess). Tests pin that honest behavior — no faked per-host containment.

Linux cage argv (P1, 2026-06-21): bwrap must mount `--ro-bind / /` BEFORE the writable
`--bind $WS $WS` (so the workspace stays writable), and must thread allow_network so the
valve actually works on Linux.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_egress(**kw):
    from argos.sandbox.egress import EgressPolicy
    return EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set(), **kw)


# ══════════════════════════════════════════════════════════════════════════════
# Fix 1 — non-darwin honest-refuse
# ══════════════════════════════════════════════════════════════════════════════

class TestNonDarwinHonestRefuse:
    """run_command on non-darwin must refuse when no sandbox backend is available."""

    def test_non_darwin_no_backend_returns_error_not_bare_run(
        self, monkeypatch, tmp_path
    ):
        """Simulating non-darwin + no bwrap/unshare: must return honest error, NOT execute."""
        from argos.tools import shell
        monkeypatch.setattr(sys, "platform", "linux")
        # No backend available
        monkeypatch.setattr("argos.tools.shell._linux_available_backend", lambda: None)

        executed = []

        import subprocess
        orig_run = subprocess.run

        def spy_run(*args, **kwargs):
            executed.append(args[0])
            return orig_run(*args, **kwargs)

        monkeypatch.setattr(subprocess, "run", spy_run)

        result, code = shell.run_command("echo hello", workspace=tmp_path)

        # Must NOT have run the bare command
        assert len(executed) == 0, (
            f"run_command ran uncaged subprocess on non-darwin with no backend: {executed}"
        )
        # Must return an honest error message
        assert "错误" in result or "no sandbox" in result.lower() or "sandbox" in result.lower()

    def test_non_darwin_with_bwrap_routes_through_bwrap(self, monkeypatch, tmp_path):
        """When bwrap is available on Linux, run_command should wrap command with bwrap."""
        from argos.tools import shell

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("argos.tools.shell._linux_available_backend", lambda: "bwrap")

        captured_argv = []

        import subprocess

        def fake_run(argv, **kwargs):
            captured_argv.extend(argv)
            m = MagicMock()
            m.returncode = 0
            m.stdout = "hello"
            m.stderr = ""
            return m

        monkeypatch.setattr(subprocess, "run", fake_run)

        result, code = shell.run_command("echo hello", workspace=tmp_path)

        # bwrap must appear in the argv
        assert "bwrap" in captured_argv, (
            f"Expected bwrap in argv, got: {captured_argv}"
        )
        assert code == 0

    def test_non_darwin_with_unshare_routes_through_unshare(self, monkeypatch, tmp_path):
        """When only unshare is available on Linux, run_command should wrap with unshare."""
        from argos.tools import shell

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("argos.tools.shell._linux_available_backend", lambda: "unshare")

        captured_argv = []

        import subprocess

        def fake_run(argv, **kwargs):
            captured_argv.extend(argv)
            m = MagicMock()
            m.returncode = 0
            m.stdout = "out"
            m.stderr = ""
            return m

        monkeypatch.setattr(subprocess, "run", fake_run)

        shell.run_command("echo hello", workspace=tmp_path)

        assert "unshare" in captured_argv, (
            f"Expected unshare in argv, got: {captured_argv}"
        )

    def test_non_darwin_no_backend_error_contains_honest_message(
        self, monkeypatch, tmp_path
    ):
        """The honest-refuse message must explain WHY (no sandbox backend available)."""
        from argos.tools import shell

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("argos.tools.shell._linux_available_backend", lambda: None)

        result, code = shell.run_command("echo hi", workspace=tmp_path)

        # Must be an error result, not a successful run
        assert code != 0 or "错误" in result, (
            "Expected non-zero exit code or error string in result"
        )
        # Must mention sandbox / backend unavailability
        lowered = result.lower()
        assert any(
            kw in lowered for kw in ("sandbox", "沙箱", "bwrap", "unshare", "backend", "后端")
        ), f"Error message does not explain sandbox unavailability: {result!r}"

    def test_darwin_path_unchanged(self, monkeypatch, tmp_path):
        """macOS path must still use Seatbelt (no regression)."""
        from argos.tools import shell

        monkeypatch.setattr(sys, "platform", "darwin")

        captured_argv = []

        import subprocess

        def fake_run(argv, **kwargs):
            captured_argv.extend(argv)
            m = MagicMock()
            m.returncode = 0
            m.stdout = "hi"
            m.stderr = ""
            return m

        monkeypatch.setattr(subprocess, "run", fake_run)

        # Must not crash; macOS path uses seatbelt (sandbox-exec)
        shell.run_command("echo hello", workspace=tmp_path)

        assert "/usr/bin/sandbox-exec" in captured_argv, (
            "macOS must still use sandbox-exec (Seatbelt)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Network valve for run_command — HONEST semantics (2026-06-21)
#
# The valve is an ALL-OR-NOTHING approval gate, NOT a per-host filter. The OS
# sandbox (Seatbelt `(allow network*)` / bwrap net ns) can only turn networking
# on or off for a child — it cannot host-filter a subprocess's outbound
# connections. So approving a network run_command grants the child FULL network
# (write-cage + credential-read-deny still apply; it can reach any host). These
# tests pin that honest behavior — they do NOT claim a per-host containment that
# the OS layer cannot provide.
# ══════════════════════════════════════════════════════════════════════════════

class TestNetworkValveForRunCommand:
    """run_command network valve = on/off approval gate (honest, not per-host)."""

    @pytest.mark.asyncio
    async def test_network_command_runs_with_network_on_after_approval(self, monkeypatch):
        """Approved network command → run_command receives allow_network=True (valve opens)."""
        from argos.approval import ApprovalGate, ApprovalLevel
        from argos.sandbox.broker import CapabilityBroker
        from argos.sandbox.egress import EgressPolicy
        from argos.tools.receipts import ReceiptSigner

        captured: dict = {}

        def fake_run(command, *, workspace=None, allow_network=False):
            captured["allow_network"] = allow_network
            return ("ok", 0)

        monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

        egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
        gate = ApprovalGate(level=ApprovalLevel.AUTO)
        br = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))

        await br.request("run_command", {"command": "curl https://a.com/data"})
        assert captured.get("allow_network") is True, (
            "approved network command must open the valve (allow_network=True)"
        )

    @pytest.mark.asyncio
    async def test_local_command_runs_with_network_off(self, monkeypatch):
        """Local command (pytest) → run_command receives allow_network=False (valve stays shut)."""
        from argos.approval import ApprovalGate, ApprovalLevel
        from argos.sandbox.broker import CapabilityBroker
        from argos.sandbox.egress import EgressPolicy
        from argos.tools.receipts import ReceiptSigner

        captured: dict = {}

        def fake_run(command, *, workspace=None, allow_network=False):
            captured["allow_network"] = allow_network
            return ("ok", 0)

        monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

        egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
        gate = ApprovalGate(level=ApprovalLevel.AUTO)
        br = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))

        await br.request("run_command", {"command": "pytest -q"})
        assert captured.get("allow_network") is False, (
            "local command must not open the network valve"
        )

    @pytest.mark.asyncio
    async def test_run_command_never_touches_egress_allowlist(self, monkeypatch):
        """HONESTY pin: run_command must NOT mutate the egress allowlist — the valve is
        all-or-nothing at the OS layer, so faking per-host entries would be security theater.
        Approving 'curl a.com' records NO host (the prior parse_network_host→allow() was removed)."""
        from argos.approval import ApprovalGate, ApprovalLevel
        from argos.sandbox.broker import CapabilityBroker
        from argos.sandbox.egress import EgressPolicy
        from argos.tools.receipts import ReceiptSigner

        def fake_run(command, *, workspace=None, allow_network=False):
            return ("ok", 0)

        monkeypatch.setattr("argos.tools.shell.run_command", fake_run)

        egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
        gate = ApprovalGate(level=ApprovalLevel.AUTO)
        br = CapabilityBroker(gate=gate, egress=egress, signer=ReceiptSigner(key=b"k"))

        before = set(egress._user)
        await br.request("run_command", {"command": "curl https://a.com/data"})
        after = set(egress._user)
        assert before == after, (
            "run_command must not add hosts to the egress allowlist (no per-host theater); "
            f"before={before} after={after}"
        )
        # And it certainly must not create a false sense that a.com is 'allowed' while evil.com isn't.
        assert egress.allowed("a.com") == egress.allowed("evil.com"), (
            "run_command egress is all-or-nothing; a.com and evil.com must be treated identically"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Linux cage argv — bwrap mount order + allow_network threading (pure-structure,
# runs on macOS dev host: asserts argv shape, no real bwrap needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestLinuxCageArgv:
    """_bwrap_argv / _unshare_argv build a correct cage (mount order + network valve)."""

    def test_bwrap_ro_root_mounts_before_writable_workspace(self, tmp_path):
        """bwrap applies fs ops in argv order — '--ro-bind / /' MUST precede '--bind $WS $WS'
        or the read-only root re-shadows the workspace read-only → writes EROFS."""
        from argos.sandbox.linux import _bwrap_argv

        argv = _bwrap_argv(tmp_path, ["echo", "hi"])
        ro_idx = argv.index("--ro-bind")
        bind_idx = argv.index("--bind")
        assert ro_idx < bind_idx, (
            f"--ro-bind / / (idx {ro_idx}) must come BEFORE --bind $WS (idx {bind_idx}) "
            f"so the writable workspace bind wins; argv={argv}"
        )
        # the writable bind must target the workspace
        assert argv[bind_idx + 1] == str(tmp_path.resolve())

    def test_bwrap_network_off_by_default(self, tmp_path):
        from argos.sandbox.linux import _bwrap_argv
        assert "--unshare-net" in _bwrap_argv(tmp_path, ["echo"])

    def test_bwrap_network_on_when_allowed(self, tmp_path):
        """allow_network=True (valve approved) → drop --unshare-net so the child can reach the net."""
        from argos.sandbox.linux import _bwrap_argv
        assert "--unshare-net" not in _bwrap_argv(tmp_path, ["echo"], allow_network=True)

    def test_unshare_network_off_by_default(self, tmp_path):
        from argos.sandbox.linux import _unshare_argv
        assert "--net" in _unshare_argv(tmp_path, ["echo"])

    def test_unshare_network_on_when_allowed(self, tmp_path):
        from argos.sandbox.linux import _unshare_argv
        assert "--net" not in _unshare_argv(tmp_path, ["echo"], allow_network=True)

    def test_shell_threads_allow_network_into_linux_cage(self, monkeypatch, tmp_path):
        """run_command(allow_network=True) on Linux+bwrap → argv has NO --unshare-net (valve works)."""
        import subprocess
        from argos.tools import shell

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("argos.tools.shell._linux_available_backend", lambda: "bwrap")
        captured: list = []

        def fake_run(argv, **kwargs):
            captured.extend(argv)
            m = MagicMock(); m.returncode = 0; m.stdout = ""; m.stderr = ""
            return m
        monkeypatch.setattr(subprocess, "run", fake_run)

        shell.run_command("curl https://a.com", workspace=tmp_path, allow_network=True)
        assert "bwrap" in captured and "--unshare-net" not in captured, (
            f"approved network run_command must open the Linux valve; argv={captured}"
        )
