
CATALOG_MODULES: list[str] = [
    "common",
    "cli",
    "core",
    "sandbox",
    "daemon",
    "tools",
    "misc",
    "verify",       # verify/strategy / dom_probe / gui_probe / self_test
    "perception",   # perception/executor / actions
    "daemon2",      # daemon/server / worker / client / conductor_supervisor
    "workflow",     # workflow/spec / engine / result / subagent / worktree
    "infra",        # mcp_native / lsp / hooks / capability
    "permissions2", # permissions/evaluator / autonomy / config / hard_rules
    "conductor",    # conductor/cronlite / proposals / orders
    "data",         # memory / routing / context / skills_curator / skills_runtime / skills
    "evalx",        # eval/benchmarks / eval/runner / learning
    "core2",
]
