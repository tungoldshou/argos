"""真 LLM 端到端烟测 —— 连真 MiniMax,运行时手动跑(不连 CI)。

跑法:`uv run pytest tests/e2e/probe_real_llm.py -v -s`(需 .env.local 配 ARGOS_LLM_KEY)。
验证:真模型经真栈跑一个可验证小任务,VerifyVerdict 达 passed(整机连真模型贯通)。
失败不阻塞 CI(本文件 skip);它是'真模型在真栈上能跑'的离线人工铁证。
"""
import pytest

pytestmark = pytest.mark.skip(reason="真 LLM 烟测,运行时手动跑(连真 MiniMax)")


@pytest.mark.asyncio
async def test_real_minimax_implements_and_verifies(tmp_path):
    import os
    from argos import runtime
    from argos.app_factory import build_components, build_loop_factory
    from argos.approval import ApprovalLevel
    from argos.tui.events import VerifyVerdict

    os.environ["ARGOS_DB_PATH"] = str(tmp_path / "argos.db")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "test_sq.py").write_text("def test_sq():\n    from sq import square\n    assert square(4) == 16\n")
    tok = runtime.use_project(str(proj))
    try:
        c = build_components(workspace=str(proj), verify_cmd="pytest -q test_sq.py",
                             approval_level=ApprovalLevel.AUTO)
        loop = build_loop_factory(c)()
        verdicts = []
        async for ev in loop.run("实现 sq.square(n) 返回 n 的平方,使 test_sq.py 通过", "probe-real"):
            if isinstance(ev, VerifyVerdict):
                verdicts.append(ev.verdict.status)
        print(f"\n[real-llm] verdicts={verdicts}")
        assert verdicts and verdicts[-1] == "passed"
        c.close()
    finally:
        runtime.reset(tok)
