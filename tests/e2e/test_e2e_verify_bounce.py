"""Internal documentation."""
import sys

import pytest

from argos.tui.events import VerifyVerdict
from argos.approval import ApprovalLevel
from tests.e2e.conftest import drain

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="真 Seatbelt 沙箱仅 macOS")


_TEST_FILE = "def test_add():\n    from solution import add\n    assert add(2, 3) == 5\n"

_WRONG = "```python\nwrite_file('solution.py', 'def add(a, b):\\n    return a - b\\n')\n```"
_RIGHT = "```python\nwrite_file('solution.py', 'def add(a, b):\\n    return a + b\\n')\n```"
_DONE = "已实现,完成。"


@pytest.mark.asyncio
async def test_wrong_fix_bounced_then_passes(build_real_loop, in_project, store):
    (in_project / "test_add.py").write_text(_TEST_FILE)
    loop = build_real_loop(
        [_WRONG, _DONE, _RIGHT, _DONE],
        verify_cmd="pytest -q test_add.py",
        level=ApprovalLevel.AUTO,
        max_rounds=3,
    )
    events = await drain(loop, "实现 solution.add 使 test_add.py 通过", "sess-bounce")

    verdicts = [e.verdict.status for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts, "应至少有一个 VerifyVerdict 事件"
    assert "failed" in verdicts, "第一轮错改必须被 verify 判 failed(没假绿灯)"
    assert verdicts[-1] == "passed", "修好后最后一次必须 passed"
    assert verdicts.index("passed") > verdicts.index("failed"), "passed 必须在 failed 之后(真修复才过)"

    assert "a + b" in (in_project / "solution.py").read_text()


@pytest.mark.asyncio
async def test_persisted_events_replay_same_verdict_sequence(build_real_loop, in_project, store):
    (in_project / "test_add.py").write_text(_TEST_FILE)
    loop = build_real_loop([_WRONG, _DONE, _RIGHT, _DONE], verify_cmd="pytest -q test_add.py",
                           level=ApprovalLevel.AUTO)
    await drain(loop, "实现 add", "sess-replay-verdict")
    rs = store.replay("sess-replay-verdict")
    replayed = [e.verdict.status for e in rs.events if isinstance(e, VerifyVerdict)]
    assert replayed and replayed[-1] == "passed"
    assert "failed" in replayed
