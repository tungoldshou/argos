# Contributing to Argos

First off, thank you for considering contributing to Argos! 🎉

Argos is a single-process Python TUI coding super-agent. We're a small project
with a big ambition: make cheap models reliable through a verify hard-gate,
honesty protocol, and OS-sandboxed executor.

This guide covers how to file issues, submit PRs, run tests, and add new
tools/skills.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Filing Issues](#filing-issues)
- [Submitting Pull Requests](#submitting-pull-requests)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Conventions](#coding-conventions)
- [Testing Requirements](#testing-requirements)
- [Adding New Tools](#adding-new-tools)
- [Adding New Skills](#adding-new-skills)
- [Adding New Slash Commands](#adding-new-slash-commands)
- [Documentation Conventions](#documentation-conventions)
- [Release Process](#release-process)

## Code of Conduct

This project and everyone participating in it is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected
to uphold this code.

## Filing Issues

Use the [issue templates](../../issues/new/choose) — they help us
triage faster. If the template doesn't fit, open a blank issue and we'll
route it.

Good bug reports include:
- Argos version (`argos --version`)
- OS + arch (`uname -a`)
- Reproducible steps (paste the goal that triggered the bug)
- Expected vs actual behavior
- Relevant log lines (if any)

## Submitting Pull Requests

1. Fork the repo and create a branch from `main`:
   `git checkout -b feat/your-feature main`
2. Make your changes following the conventions below.
3. Add tests. PRs without tests are unlikely to be merged.
4. Run the full test suite: `uv run pytest` — must be green.
5. Update CHANGELOG.md under `[Unreleased]` (we follow Keep a Changelog).
6. Open the PR. CI will run; we review within 1-3 days.

PR titles follow [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `build:`, `ci:`.

## Development Setup

```bash
# Install uv (if not already)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and set up
git clone https://github.com/tungoldshou/argos.git
cd argos
uv sync                    # installs all deps
uv run argos --selftest    # smoke test (no LLM)
uv run pytest              # run all tests
```

Test categories:
- `uv run pytest` — full suite (excludes slow)
- `uv run pytest -m slow` — slow tests (real subprocess, real pyright)
- `uv run pytest --cov=argos_agent` — with coverage (≥80% threshold)

## Project Structure

```
argos_agent/                # Main package
├── __init__.py            # version (importlib.metadata + _MEIPASS fallback)
├── __main__.py            # CLI entry, daemon spawn, self-update check
├── approval.py            # ApprovalLevel + ApprovalGate
├── core/                  # AgentLoop, harness, plan/act/verify/report phases
├── sandbox/               # OS Seatbelt profiles, sandbox child
├── tools/                 # 22 broker-gated tools (write_file, run_command, lsp_*)
├── tui/                   # Textual UI (app, widgets, commands, events)
│   ├── widgets/           # ModalScreen widgets
│   └── events.py          # Frozen Event union
├── hooks/                 # Hooks system (5 events: PreToolUse, PostToolUse, ...)
├── lsp/                   # LSP integration (pygls adapter + 6 lsp_* tools)
├── skills_runtime/        # AnalysisSkill runtime + 3 builtins (verify, security-review, simplify)
├── permissions/           # Smart approval (12 hard rules + soft rules)
├── daemon/                # Long-running daemon + RunStore + 7 state machine
├── web.py                 # web_search / web_extract
├── memory/                # Persistent memory
├── workflow/              # Dynamic workflows (subagents, fanout)
└── skills.py              # Built-in skill recipes (markdown)

docs/                       # Specs + plans
├── superpowers/specs/      # Feature design specs (one per PR)
├── superpowers/plans/      # Implementation plans (TDD tasks)
└── argos-product-definition.md  # Product north star

tests/                      # Mirror argos_agent/ structure
.github/                    # CI workflows (release.yml)
packaging/                  # PyInstaller + install.sh + Homebrew Cask
```

## Coding Conventions

(from CLAUDE.md)

- **Immutability:** frozen dataclasses for value objects. Never mutate in place.
- **Files:** 200-400 lines typical, 800 max. Extract utilities aggressively.
- **Errors:** always handle explicitly. Never silently swallow.
- **Input validation:** at system boundaries. Fail fast with clear messages.
- **Type hints:** all public functions.
- **frozen + `__post_init__` validation** for dataclasses.
- **Module-level singletons** for shared state (e.g. `plan_mode._plan_mode_active`).
- **No co-author trailer** in commits.
- **Conventional commits** (feat/fix/refactor/docs/test/chore/perf/build/ci).
- **English first** in code, comments, commit messages.
- **Bilingual docs**: English primary, Chinese supplementary (in `.zh-CN.md`).

## Testing Requirements

Per the project CLAUDE.md and `/rootfs/rules/common/testing.md`:

- 80%+ coverage for new code
- TDD: write failing test → impl → green
- Use `unittest.mock.AsyncMock` for async, `monkeypatch` for FS/clock
- Slow tests (real subprocess, real pyright) mark with `@pytest.mark.slow`
- Each PR adds at least 5-10 new tests for meaningful features

## Adding New Tools

Tools live in `argos_agent/tools/` and are registered in `__init__.py`:

1. Define a frozen dataclass: `@dataclass(frozen=True) class YourTool: name: ClassVar[str] = "your_tool"; ...`
2. Implement the `gated` version (e.g. `your_tool_gated`) with Seatbelt + approval gate
3. Add to `ALL_TOOL_NAMES` constant
4. Add tests in `tests/test_tools_*.py`
5. Document in spec (`docs/superpowers/specs/YYYY-MM-DD-your-tool-design.md`)

## Adding New Skills

Skills are runtime analyzers in `argos_agent/skills_runtime/`. To add a new slash skill:

1. Write a spec under `docs/superpowers/specs/`
2. Implement `AnalysisSkill` in `skills_runtime/builtin/<name>/`
3. Register in `skills_runtime/builtin/__init__.py`
4. Add to `tui/commands.py:COMMAND_HELP`
5. Add tests

See `docs/superpowers/specs/2026-06-06-skills-verify-review-simplify-design.md`
for the canonical pattern.

## Adding New Slash Commands

Slash commands are user-facing TUI features. To add one:

1. Add the description to `tui/commands.py:COMMAND_HELP`
2. Add the dispatch case in `tui/app.py:_dispatch_slash`
3. Write tests in `tests/test_tui_commands.py`
4. Update README usage section

## Documentation Conventions

- Specs: `docs/superpowers/specs/YYYY-MM-DD-<name>-design.md`
- Plans: `docs/superpowers/plans/YYYY-MM-DD-<name>.md`
- User docs: `docs/<filename>.md` (English primary)
- CHANGELOG: `CHANGELOG.md` (Keep a Changelog format)
- All design decisions are explicit in spec §8 (Decisions table)

## Release Process

We follow [Semantic Versioning](https://semver.org/). Releases are cut by the
maintainer via `/ship`:

1. Bump version in `pyproject.toml` + `CHANGELOG.md`
2. Tag `vX.Y.Z` on main
3. GitHub Actions builds macOS arm64 binary + tarball
4. Auto-publishes to GitHub Releases
5. Homebrew Cask is updated automatically

`/ship` is the one-shot release command. Contributors don't need to do
releases — just open PRs.

## Getting Help

- 💬 [GitHub Discussions](../../discussions) — questions, ideas, show & tell
- 🐛 [GitHub Issues](../../issues) — bug reports
- 📖 [Documentation](../) — specs, plans, READMEs
- ✉️ Email: tungoldshou@gmail.com — security issues only (see SECURITY.md)

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).
