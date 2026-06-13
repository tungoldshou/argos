"""整机贯通(spec §3.3 / §12.6):goal→四阶段不可跳 + 事件三用(UI=store=replay)一致。"""
import sys

import pytest

from argos.tui.events import PhaseChange, VerifyVerdict
from argos.approval import ApprovalLevel
from tests.e2e.conftest import drain

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="真 Seatbelt 沙箱仅 macOS")

_TEST_FILE = "def test_g():\n    from g import greet\n    assert greet() == 'hi'\n"
_RIGHT = "```python\nwrite_file('g.py', \"def greet():\\n    return 'hi'\\n\")\n```"
_DONE = "完成。"


@pytest.mark.asyncio
async def test_full_run_four_phases_and_event_triplication(build_real_loop, in_project, store):
    (in_project / "test_g.py").write_text(_TEST_FILE)
    loop = build_real_loop([_RIGHT, _DONE], verify_cmd="pytest -q test_g.py", level=ApprovalLevel.AUTO)
    events = await drain(loop, "实现 g.greet 返回 hi", "sess-full")

    # 四阶段按序出现且不可跳(plan→act→verify→report)。
    phases = [e.phase for e in events if isinstance(e, PhaseChange)]
    for ph in ("plan", "act", "verify", "report"):
        assert ph in phases, f"缺阶段 {ph}(四阶段不可跳,spec §3.3 L3)"
    assert phases.index("plan") < phases.index("act") < phases.index("verify") < phases.index("report")

    # 事件三用:run 时收的事件 == store 持久化 == replay 重建(spec §12.6)。
    rs = store.replay("sess-full")
    run_kinds = [e.kind for e in events]
    replay_kinds = [e.kind for e in rs.events]
    assert run_kinds == replay_kinds, "一份事件三用:run==persist==replay 必须逐事件一致"

    # report 前一次全绿(spec §3.3:report 前必须 passed 或诚实标注)。
    verdicts = [e.verdict.status for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts[-1] == "passed"
