# Argos — Coding Super-Agent

A standalone terminal (TUI) coding super-agent built on Textual. Drives cheap
models through an Anthropic-Messages-compatible endpoint with a verify hard-gate,
honesty protocol, and OS-sandboxed executor.

Soul of the project: make cheap models *reliable* — honesty protocol + verify
hard-gate, not just another model wrapper.

## 快速开始（开发）

需要 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run argos        # 启动 Argos TUI
uv run pytest -q    # 跑测试
```

## Architecture

- **`argos_agent/`** — agent brain: LangGraph ReAct loop, tools, honesty
  protocol, verify hard-gate, approval gate, skills, MCP adapters.
- **`argos_agent/tui/`** — Textual TUI shell.
- **`tests/`** — pytest test suite.
- **`pyproject.toml`** — single Python project; `argos` console entry point.
