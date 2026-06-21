"""Sandbox shell fixes — failing tests first (TDD).

Fix 1 (P0): run_command on non-darwin must NOT run uncaged.
  - When a Linux bwrap/unshare backend is available → route through it.
  - When NO backend available → honest-refuse (ok=False, no subprocess).

Fix 2 (P1): run_command network valve is all-or-nothing.
  - Approving 'curl a.com' must NOT silently add evil.com to the egress set.
  - Only the parsed target host should be recorded on the egress policy.
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
# Fix 2 — egress scoping: approved 'curl a.com' must not let evil.com through
# ══════════════════════════════════════════════════════════════════════════════

class TestEgressScopingForRunCommand:
    """After approving a network run_command, only the parsed host enters egress."""

    @pytest.mark.asyncio
    async def test_approved_curl_a_com_does_not_add_evil_com(self, monkeypatch):
        """Approving 'curl a.com' must NOT add evil.com to the egress allowlist."""
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

        # Approve 'curl a.com'
        await br.request("run_command", {"command": "curl https://a.com/data"})

        # evil.com must NOT be in the egress allowlist
        assert not egress.allowed("evil.com"), (
            "evil.com should NOT be in the egress set after approving curl a.com"
        )
        # a.com SHOULD be recorded (scoped grant)
        assert egress.allowed("a.com"), (
            "a.com SHOULD be recorded in egress after approving curl a.com"
        )

    @pytest.mark.asyncio
    async def test_approved_pip_install_records_pypi_not_all_hosts(self, monkeypatch):
        """Approving 'pip install requests' records pypi.org, not a blanket wildcard."""
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

        await br.request("run_command", {"command": "pip install requests"})

        # After pip install, evil.com must still NOT be allowed
        assert not egress.allowed("evil.com"), (
            "evil.com must not be reachable after approving pip install"
        )

    @pytest.mark.asyncio
    async def test_non_network_command_does_not_alter_egress(self, monkeypatch):
        """A local command (pytest) must not touch the egress allowlist at all."""
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

        # snapshot user egress set before
        before = set(egress._user)
        await br.request("run_command", {"command": "pytest -q"})
        after = set(egress._user)

        assert before == after, (
            f"Local command must not alter egress. Before: {before}, after: {after}"
        )

    def test_parse_egress_host_from_curl(self):
        """Utility: host can be parsed from curl/wget commands."""
        from argos.tools.shell import parse_network_host

        assert parse_network_host("curl https://a.com/data") == "a.com"
        assert parse_network_host("curl http://b.org/path?q=1") == "b.org"
        assert parse_network_host("wget https://files.example.com/x.zip") == "files.example.com"

    def test_parse_egress_host_from_pip_returns_none(self):
        """pip install has no explicit URL — parse_network_host returns None."""
        from argos.tools.shell import parse_network_host

        # pip doesn't have a parseable target URL in the command string
        result = parse_network_host("pip install requests")
        # None is acceptable — no host to record
        assert result is None

    def test_parse_egress_host_from_git_push_returns_none(self):
        """git push doesn't have a URL in argv — returns None."""
        from argos.tools.shell import parse_network_host

        result = parse_network_host("git push origin main")
        assert result is None

    def test_parse_egress_host_from_unknown_returns_none(self):
        """Commands with no parseable URL return None."""
        from argos.tools.shell import parse_network_host

        assert parse_network_host("pytest -q") is None
        assert parse_network_host("npm install") is None
