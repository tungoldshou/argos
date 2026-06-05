"""测试 tool_scope=read 时 build_child_namespace 真正剔除写工具(兑现审批「只读」承诺)。"""
from argos_agent import tools


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
    ns = tools.build_child_namespace(broker=None)  # 默认 read_only=False
    # broker=None 时 broker-gated 工具(run_command 等)不注入,但纯沙箱写工具(write_file/edit_file)仍在。
    assert "write_file" in ns and "edit_file" in ns
