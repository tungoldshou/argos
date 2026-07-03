# CHANGELOG

All notable changes to Argos are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Public launch metadata now targets `v0.1.1`; the old GitHub `v0.1.0` release and remote tag were deleted and are not treated as a published version.
- README and packaging docs present PyPI / `uv tool` plus source checkout as the launch install surface, with binary and package-manager channels deferred.
- Root `install.sh` provides the `curl | bash` shortcut by bootstrapping `uv` when needed and then using `uv tool install/upgrade argos-agent`.
- Public `curl | bash` docs now point at the immutable `v0.1.1` raw tag URL instead of mutable `main`.
- Manual `publish.yml` dispatch publishes to TestPyPI only; formal PyPI publishing remains restricted to fresh `v*` tags.
- Binary release workflow is manual-only so tag pushes can publish the Python package without draft platform packaging blocking the release.
- Release and packaging automation now fail closed for missing artifacts, stale `dist/` contents, missing checksums, invalid WinGet digests, and missing manifest files.
- Public security wording now limits broker-governance claims to declared privileged tools and describes raw model-authored Python as OS-contained only when opt-in sandboxing is enabled.
- Project and setup docs now consistently describe runtime state under the Argos config directory, with `ARGOS_CONFIG_DIR` as the override.
- Project guidance keeps `AGENTS.md` as the instruction entry point and does not recreate deleted `CLAUDE.md` or `AGENTS.md.bak`.

### Fixed
- `argospkg info` no longer reads `packaging/VERSION` from the caller's current directory.
- `argospkg manifest` fails when required WinGet files are missing or when `InstallerSha256` is still placeholder or malformed.
- Root `install.sh` verifies the installed command through `uv tool dir --bin`, so first-time installs do not depend on the current shell `PATH`.
- Deferred binary installer scripts identify themselves as non-launch installers and point users back to the PyPI/uv/source path.
- Windows release packaging uses PowerShell `Compress-Archive` instead of assuming a bare `zip` command on `windows-latest`.
- GitHub release asset collection uses an exact release manifest and checksum list instead of suffix-wide discovery.
- Runtime defaults, TUI hints, setup paths, MCP/LSP/hooks/permissions paths, Dream paths, eval paths, memory paths, and sandbox secret masks now follow the active Argos config directory where applicable.
- Permission, hook, and sync-bridge failures now fail closed instead of silently allowing high-risk operations.
- CodeAct now executes only explicit ` ```python` fenced blocks, waits on confirmation requests, and nudges research promises into real tool use.
- TUI transcript review, cache metric display, context pressure display, and daemon multi-turn session continuity were hardened.

### Verified
- `uv build` produces `dist/argos_agent-0.1.1.tar.gz` and `dist/argos_agent-0.1.1-py3-none-any.whl`.
- `twine check dist/*` passes for the current wheel and sdist.
- Installed-wheel smoke coverage verifies `argos --version` against the current project version.
- Packaging, README, WinGet, PyPI workflow, and release workflow tests cover the current launch path.

[Unreleased]: https://github.com/tungoldshou/argos/compare/v0.1.1...HEAD
