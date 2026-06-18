"""测试 tool_scope=read 时 build_child_namespace 真正剔除写工具(兑现审批「只读」承诺)。"""
from argos import tools


def test_read_only_namespace_strips_mutating_tools():
    ns = tools.build_child_namespace(broker=None, read_only=True)
    for t in ("write_file", "edit_file", "run_command", "browser_click",
              "browser_type", "mcp_call"):
        assert t not in ns, f"read 作用域应剔除 {t}"
    # 只读纯沙箱工具仍在(broker=None 时 broker-gated 的 web_search/browser_snapshot 不注入,
    # 实际使用中 broker 非 None 时它们会在——此处用 broker=None 测最小集,只验纯沙箱工具)。
    for t in ("read_file", "search_files"):
        assert t in ns, f"read 作用域应保留 {t}"


def test_full_scope_keeps_mutating_tools():
    class _Stub:
        def request(self, action, args):
            return "ok"
    ns = tools.build_child_namespace(broker=_Stub())  # 默认 read_only=False
    # write_file/edit_file 现为 broker-gated(gate-only):broker 在场时注入(无 broker 不给写=诚实)。
    assert "write_file" in ns and "edit_file" in ns


class _Stub:
    def request(self, action, args):
        return "ok"


def test_role_allowlist_is_authority_intersection():
    """#6(2026-06-18):有角色白名单时,命名空间 = 可用 ∩ 白名单(物理剔除其余),兑现 spec.py:45 承诺。
    explorer(只读集)拿不到未声明的 web/浏览器/截屏;白名单是权威。"""
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
    """#6:reviewer 声明了 run_command,即便 read_only=True 也必须保留(白名单权威,不被 read_only 误剥)。
    此前 read_only 剥离会干掉 run_command → reviewer 调用即 NameError。"""
    from argos.workflow.spec import ROLE_PRESETS
    reviewer_allow = ROLE_PRESETS["reviewer"].tool_allowlist
    ns = tools.build_child_namespace(
        broker=_Stub(), allow_workflow=False, read_only=True, tool_allowlist=reviewer_allow,
    )
    assert "run_command" in ns, "reviewer 声明的 run_command 不应被 read_only 误剥(#6)"
    assert "lsp_diagnostics" in ns
    # 仍无写文件工具(白名单未含 → 物理剔除)
    assert "write_file" not in ns and "edit_file" not in ns
