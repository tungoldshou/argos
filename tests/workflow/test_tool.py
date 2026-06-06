"""tests/workflow/test_tool.py — propose_workflow 纯工具注册 + 深度护栏测试."""
from argos_agent import tools


def test_propose_workflow_in_namespace_and_returns_receipt():
    ns = tools.build_namespace(broker=None)
    assert "propose_workflow" in ns
    out = ns["propose_workflow"]({"name": "x", "stages": []})
    assert isinstance(out, str) and "工作流" in out


def test_propose_workflow_registered():
    assert "propose_workflow" in tools.ALL_TOOL_NAMES


def test_child_namespace_default_keeps_propose_workflow():
    # 父 agent(默认 allow_workflow=True)必须保留 propose_workflow,否则沙箱里调它 NameError
    assert "propose_workflow" in tools.build_child_namespace(broker=None)


def test_child_namespace_excludes_propose_workflow_when_disallowed():
    # 子 agent(allow_workflow=False):深度护栏去掉 propose_workflow(深度恒 1)
    assert "propose_workflow" not in tools.build_child_namespace(broker=None, allow_workflow=False)
