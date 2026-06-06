"""铁证①(spec §9):便宜模型错改→verify bounce 拦住→修好后才翻 passed(可证伪)。

可证伪:VerifyVerdict.status 序列 = [failed..., passed],passed 只在真修复后出现。
若 loop 把第一轮的错改也判 passed(假绿灯)→ 本测试红,铁证生效。

脚本设计契合真 loop:act 阶段 stream 到"无代码块(宣布完成)"才进 verify(loop.py),
故每轮 = 一个 write_file 代码块 + 一句无代码块的"完成"触发 verify。
"""
import sys

import pytest

from argos_agent.tui.events import VerifyVerdict
from argos_agent.approval import ApprovalLevel
from tests.e2e.conftest import drain

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="真 Seatbelt 沙箱仅 macOS")


# 任务:实现 add(a,b);verify 跑 test_add.py。第一轮故意写错(返回 a-b),第二轮写对。
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

    # 文件真被改成正确解(外部判据,不信模型自报)。
    assert "a + b" in (in_project / "solution.py").read_text()


@pytest.mark.asyncio
async def test_persisted_events_replay_same_verdict_sequence(build_real_loop, in_project, store):
    (in_project / "test_add.py").write_text(_TEST_FILE)
    loop = build_real_loop([_WRONG, _DONE, _RIGHT, _DONE], verify_cmd="pytest -q test_add.py",
                           level=ApprovalLevel.AUTO)
    await drain(loop, "实现 add", "sess-replay-verdict")
    # 一份事件三用:replay 重建出的 verdict 序列 = run 时看到的(spec §12.6)。
    rs = store.replay("sess-replay-verdict")
    replayed = [e.verdict.status for e in rs.events if isinstance(e, VerifyVerdict)]
    assert replayed and replayed[-1] == "passed"
    assert "failed" in replayed
