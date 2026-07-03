import sys

import pytest

from argos.tui.events import VerifyVerdict, PhaseChange
from argos.memory.store import ReplayState
from argos.approval import ApprovalLevel
from tests.e2e.conftest import drain

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="真 Seatbelt 沙箱仅 macOS")


_TEST_FILE = "def test_v():\n    from sol import v\n    assert v() == 42\n"
_RIGHT = "```python\nwrite_file('sol.py', 'def v():\\n    return 42\\n')\n```"
_DONE = "完成。"


@pytest.mark.asyncio
async def test_kill_midrun_preserves_events_and_replay_reconstructs(build_real_loop, in_project, store):
    (in_project / "test_v.py").write_text(_TEST_FILE)
    loop = build_real_loop([_RIGHT, _DONE], verify_cmd="pytest -q test_v.py", level=ApprovalLevel.AUTO)

    seen = 0
    async for ev in loop.run("实现 sol.v 返回 42", "sess-kill"):
        seen += 1
        if isinstance(ev, PhaseChange):
            break

    rs = store.replay("sess-kill")
    assert isinstance(rs, ReplayState)
    assert rs.session.session_id == "sess-kill"
    assert len(rs.events) >= 1, "kill 前的事件必须已落盘(逐事件持久化)"
    assert rs.last_phase in ("plan", "act", "verify", "report")


@pytest.mark.asyncio
async def test_resume_continues_to_passed(build_real_loop, in_project, store):
    (in_project / "test_v.py").write_text(_TEST_FILE)
    loop1 = build_real_loop([_RIGHT, _DONE], verify_cmd="pytest -q test_v.py", level=ApprovalLevel.AUTO)
    async for ev in loop1.run("实现 sol.v 返回 42", "sess-resume"):
        if isinstance(ev, PhaseChange) and ev.phase == "act":
            break
    rs = store.replay("sess-resume")
    assert rs.last_phase in ("plan", "act")

    loop2 = build_real_loop([_RIGHT, _DONE], verify_cmd="pytest -q test_v.py", level=ApprovalLevel.AUTO)
    events = await drain(loop2, "实现 sol.v 返回 42", "sess-resume")
    verdicts = [e.verdict.status for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts and verdicts[-1] == "passed", "续跑后必须达 passed(续上而非从零白跑)"
    full = store.replay("sess-resume")
    assert full.session.session_id == "sess-resume"
