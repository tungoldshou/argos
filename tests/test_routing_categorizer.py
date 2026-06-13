"""#11 T1 任务分类启发式测试。"""
from argos.routing.categorizer import TaskCategory, categorize


def test_categorize_plan_phase_returns_plan():
    assert categorize(tool=None, code=None, phase="plan", step=0) == TaskCategory.PLAN


def test_categorize_verify_phase_returns_verify():
    assert categorize(tool=None, code=None, phase="verify", step=0) == TaskCategory.VERIFY


def test_categorize_long_step_returns_long_run():
    assert categorize(tool=None, code=None, phase="act", step=25) == TaskCategory.LONG_RUN


def test_categorize_run_command_returns_auto_capture():
    assert categorize(tool="run_command", code=None, phase="act", step=2) == TaskCategory.AUTO_CAPTURE


def test_categorize_test_marker_returns_test_write():
    code = "def test_foo():\n    assert x == 1\n"
    assert categorize(tool=None, code=code, phase="act", step=1) == TaskCategory.TEST_WRITE


def test_categorize_edit_small_returns_file_edit():
    code = """edit_file('app.py', 'old line', 'new line', all_occurrences=False)"""
    assert categorize(tool="edit_file", code=code, phase="act", step=1) == TaskCategory.FILE_EDIT


def test_categorize_edit_large_returns_refactor():
    # new has 10 lines, old has 2 lines -> diff 8 (>= 5)
    old = "old1\nold2"
    new = "\n".join(f"line{i}" for i in range(10))
    code = f"""edit_file('app.py', '{old}', '{new}', all_occurrences=False)"""
    assert categorize(tool="edit_file", code=code, phase="act", step=1) == TaskCategory.REFACTOR


def test_categorize_read_tool_returns_simple_read():
    assert categorize(tool="read_file", code=None, phase="act", step=1) == TaskCategory.SIMPLE_READ
    assert categorize(tool="search_files", code=None, phase="act", step=1) == TaskCategory.SIMPLE_READ


def test_categorize_no_code_no_tool_returns_simple_read():
    # default fallback
    assert categorize(tool=None, code=None, phase="act", step=1) == TaskCategory.SIMPLE_READ


def test_categorize_garbage_input_returns_simple_read():
    # doesn't raise, returns simple_read
    assert categorize(tool=None, code="this is just text", phase="act", step=1) == TaskCategory.SIMPLE_READ


def test_categorize_write_file_returns_file_edit():
    code = "write_file('a.py', 'hello')"
    assert categorize(tool=None, code=code, phase="act", step=1) == TaskCategory.FILE_EDIT


def test_categorize_8_categories_unique_values():
    vals = {c.value for c in TaskCategory}
    assert len(vals) == 8
