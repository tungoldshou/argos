"""Internal documentation."""
import inspect

from argos.core.loop import AgentLoop


def test_tool_signatures_block_contains_read_file_signature():
    """Internal documentation."""
    src = inspect.getsource(AgentLoop._tool_signatures_block)
    assert "read_file(path, offset" in src
    assert "edit_file(path, old, new, all_occurrences" in src
    assert "limit" in src
    assert "/undo" in src
    assert "/retry" in src


def test_build_system_calls_tool_signatures_block():
    """Internal documentation."""
    src = inspect.getsource(AgentLoop._build_system)
    pair_src = inspect.getsource(AgentLoop._build_system_pair)
    assert ("_tool_signatures_block" in src or "tool_signatures_block" in src
            or "_tool_signatures_block" in pair_src or "tool_signatures_block" in pair_src)
