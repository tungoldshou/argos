"""Internal documentation."""

CATALOG_MODULES: list[str] = [
    "common",
    "cli",
    "tui_app",  # TUI app shell / commands / prompt / status_bar
    "widgets",
    "core",
    "sandbox",
    "daemon",
    "tools",
    "permissions",
    "misc",
    "verify",       # verify/strategy / dom_probe / gui_probe / self_test
    "perception",   # perception/executor / actions
    "daemon2",      # daemon/server / worker / client / conductor_supervisor / tui/daemon_source
    "workflow",     # workflow/spec / engine / result / subagent / worktree
    "infra",        # mcp_native / lsp / hooks / capability
    "permissions2", # permissions/evaluator / autonomy / config / hard_rules
    "conductor",    # conductor/cronlite / proposals / orders
    "data",         # memory / routing / context / skills_curator / skills_runtime / skills
    "evalx",        # eval/benchmarks / eval/runner / learning
    "core2",
]
