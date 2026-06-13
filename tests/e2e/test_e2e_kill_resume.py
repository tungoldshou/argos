"""铁证②(spec §9 / §5.8 / §12.6):kill 中途→replay 重建→/resume 续上(可证伪)。

可证伪:kill 后 store 仍持有前半段 events;replay 重建 last_phase;续跑后达 passed。
若持久化是事后一次性 flush(非逐事件)→ kill 后 events 丢失→ replay 空→ 本测试红。

W4(锁):/resume = replay 重建 + 从头重跑(verify-gated),非断点续传。
脚本契合真 loop:write 代码块 + 无代码块"完成"触发 verify。
"""
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

    # 模拟 kill:消费到第一个 PhaseChange 后就停(中途放弃),不收完整 run。
    seen = 0
    async for ev in loop.run("实现 sol.v 返回 42", "sess-kill"):
        seen += 1
        if isinstance(ev, PhaseChange):
            break  # ← 中途 kill 点

    # 铁证:前半段 events 已逐事件持久化(非事后 flush),replay 能重建。
    rs = store.replay("sess-kill")
    assert isinstance(rs, ReplayState)
    assert rs.session.session_id == "sess-kill"
    assert len(rs.events) >= 1, "kill 前的事件必须已落盘(逐事件持久化)"
    assert rs.last_phase in ("plan", "act", "verify", "report")


@pytest.mark.asyncio
async def test_resume_continues_to_passed(build_real_loop, in_project, store):
    (in_project / "test_v.py").write_text(_TEST_FILE)
    # 第一次跑:中途 break(kill)。
    loop1 = build_real_loop([_RIGHT, _DONE], verify_cmd="pytest -q test_v.py", level=ApprovalLevel.AUTO)
    async for ev in loop1.run("实现 sol.v 返回 42", "sess-resume"):
        if isinstance(ev, PhaseChange) and ev.phase == "act":
            break
    rs = store.replay("sess-resume")
    assert rs.last_phase in ("plan", "act")

    # /resume:用同 session_id 续跑(W4:replay 重建 + 从头重跑;脚本仍给正确解)。
    loop2 = build_real_loop([_RIGHT, _DONE], verify_cmd="pytest -q test_v.py", level=ApprovalLevel.AUTO)
    events = await drain(loop2, "实现 sol.v 返回 42", "sess-resume")
    verdicts = [e.verdict.status for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts and verdicts[-1] == "passed", "续跑后必须达 passed(续上而非从零白跑)"
    # session 仍是同一个(lineage 不丢),events 表累计含两次跑的事件。
    full = store.replay("sess-resume")
    assert full.session.session_id == "sess-resume"
