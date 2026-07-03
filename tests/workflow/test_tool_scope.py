"""Internal documentation."""
from argos import tools


def test_read_only_namespace_strips_mutating_tools():
    ns = tools.build_child_namespace(broker=None, read_only=True)
    for t in ("write_file", "edit_file", "run_command", "browser_click",
              "browser_type", "mcp_call"):
        assert t not in ns, f"read 作用域应剔除 {t}"
    for t in ("read_file", "search_files"):
        assert t in ns, f"read 作用域应保留 {t}"


def test_full_scope_keeps_mutating_tools():
    class _Stub:
        def request(self, action, args):
            return "ok"
    ns = tools.build_child_namespace(broker=_Stub())
    assert "write_file" in ns and "edit_file" in ns


class _Stub:
    def request(self, action, args):
        return "ok"


def test_role_allowlist_is_authority_intersection():
    """Internal documentation."""
    from argos.workflow.spec import ROLE_PRESETS
    explorer_allow = ROLE_PRESETS["explorer"].tool_allowlist
    ns = tools.build_child_namespace(
        broker=_Stub(), allow_workflow=False, read_only=True, tool_allowlist=explorer_allow,
    )
    assert set(ns) <= set(explorer_allow), f"命名空间应 ⊆ 白名单,多出:{set(ns) - set(explorer_allow)}"
    for leaked in ("web_search", "web_extract", "browser_navigate", "browser_snapshot",
                   "browser_screenshot", "computer_screenshot", "lsp_definition"):
        assert leaked not in ns, f"explorer 未声明 {leaked},不该泄漏进命名空间"
    assert "read_file" in ns and "search_files" in ns and "propose_verify" in ns


def test_reviewer_allowlist_keeps_run_command_despite_read_only():
    """Internal documentation."""
    from argos.workflow.spec import ROLE_PRESETS
    reviewer_allow = ROLE_PRESETS["reviewer"].tool_allowlist
    ns = tools.build_child_namespace(
        broker=_Stub(), allow_workflow=False, read_only=True, tool_allowlist=reviewer_allow,
    )
    assert "run_command" in ns, "reviewer 声明的 run_command 不应被 read_only 误剥(#6)"
    assert "lsp_diagnostics" in ns
    assert "write_file" not in ns and "edit_file" not in ns
