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

Argos has three core moats (see [docs/argos-product-definition.md](docs/argos-product-definition.md)):

1. **propose_verify** — agent declares its verify command; we run it independently
2. **parseTrusted** — three-state Verdict (passed / failed / unverifiable); never lies
3. **OS Seatbelt** — agent code runs in sandbox, no network by default

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
- **No automatic updates** — `argos self-update` only checks; user runs the
  installer.

## Past Advisories

None yet.
