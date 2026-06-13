# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities via public GitHub issues.**

Send security reports to: **tungoldshou@gmail.com** (encrypted email preferred
if sensitive; otherwise plain text is fine for non-critical issues).

Include:
- Description of the vulnerability
- Steps to reproduce
- Affected version(s)
- Impact assessment (your best guess)
- Suggested fix (if any)

We will:
- Acknowledge within 48 hours
- Provide an initial assessment within 5 business days
- Coordinate disclosure timing with you
- Credit you in the fix commit (unless you prefer anonymity)

## Security Architecture

Argos has several core moats (see [docs/argos-product-definition.md](docs/argos-product-definition.md)):

1. **propose_verify** — agent declares its verify command; we run it independently
2. **Verdict / VerdictStatus** — three-state result (`passed` / `failed` / `unverifiable`), fail-closed; defined in `argos/core/types.py`; Argos never fabricates a green result
3. **OS Seatbelt** — agent code runs in a subprocess under a macOS Seatbelt profile, no network by default
4. **CapabilityBroker + CapabilityRegistry** — every side effect passes egress-policy checks (derived from the per-process `CapabilityRegistry`) and receives an HMAC-signed receipt; each daemon run gets its own isolated `SeatbeltExecutor + ApprovalGate + CapabilityBroker` via `build_run_stack()`, so concurrent runs never share mutable state
5. **Approval Gate / Trust Dial** — levels L0 (OBSERVE) through L4 (AUTO / `/yolo`); HARD RULES enforced in `permissions/` cannot be bypassed at any trust level

## Threat Model

**In scope:**
- Malicious user-provided LLM model outputs
- Code execution that escapes the sandbox
- Verify gate bypass
- Approval gate bypass
- Computer-use abuse (`computer.*` tools, `perception/`) — OS-level screen/mouse/keyboard
  actions; requires `ARGOS_COMPUTER_USE=1` and Accessibility permission; all actions are
  broker-gated (risk=high, reversible=False, hard CONFIRM)

**Out of scope (by design):**
- User-installed hooks (`~/.argos/hooks.json`) — user code, user responsibility
- User-installed LSP servers — user code, user responsibility
- Models that ignore their system prompt

## Known Limitations

- **macOS only** for the packaged binary (Linux/Windows in #13)
- **Unsigned binary** — first launch requires right-click → Open, or
  `xattr -d com.apple.quarantine /Applications/Argos.app`. Code signing
  is on the roadmap (v0.x milestone).
- **No automatic updates** — `argos self-update` force-checks and prints the
  upgrade URL; it does not auto-install. The user runs the installer manually.
- **Desktop shell in progress** — `desktop/` is the Tauri 2 second client (v6
  P6b walking skeleton, not yet released). The Seatbelt sandbox guarantees
  described above apply to the daemon kernel (`argosd`); both the terminal TUI
  and the future desktop client attach to that same daemon as protocol clients,
  so the sandbox boundary does not change when the desktop client ships.

## Past Advisories

None yet.
