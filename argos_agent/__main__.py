"""`argos` 命令入口(Phase 6 整机集成)。

默认注入真 loop_factory(app_factory 组装的 AgentLoop);无 key → 诚实落 demo 态。
选项:
  --demo / --demo-fail   FakeLoop 演示(成功 / escalation 路径,沿用 Phase 5)
  --selftest             不连真模型自检:脚本模型跑一轮四阶段贯通,打印 verdict 退出
  --project PATH         在用户项目目录干活(runtime.use_project)
  --premium              用 premium(Claude)档(需 ARGOS_PREMIUM_KEY)
  --resume SESSION_ID    续跑历史会话(占位透传;真续跑走 TUI 内 /resume,Phase 5)
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="argos", description="诚实可靠的终端编码超级智能体")
    p.add_argument("--demo", action="store_true", help="FakeLoop 成功演示")
    p.add_argument("--demo-fail", action="store_true", help="FailingFakeLoop escalation 演示")
    p.add_argument("--selftest", action="store_true", help="不连真模型自检(脚本模型跑四阶段)")
    p.add_argument("--project", metavar="PATH", help="在用户项目目录干活")
    p.add_argument("--premium", action="store_true", help="用 premium(Claude)档")
    p.add_argument("--resume", metavar="SESSION_ID", help="续跑历史会话(占位:真续跑走 TUI /resume)")
    return p


class _SelftestModel:
    """selftest 内联脚本模型(不依赖 tests/,打包态可用)。按脚本逐 stream 吐文本。"""

    def __init__(self, scripts: list[str]) -> None:
        self._s = scripts
        self._i = 0

    def _next(self) -> str:
        t = self._s[min(self._i, len(self._s) - 1)]
        self._i += 1
        return t

    async def stream(self, messages, *, system):
        for ch in self._next():
            yield ch

    async def complete(self, messages, *, system) -> str:
        return self._next()


def _run_selftest() -> int:
    """不连真模型自检:脚本模型在 tmp 项目跑一轮四阶段贯通,打印 verdict(整机装配布尔)。

    用真 sandbox/broker/verifier/store + 内联脚本模型(canonical 装配,对齐 app_factory)。
    真 Seatbelt 需 macOS;非 macOS 上 spawn 失败 → 捕获返 1(诚实失败,不假装通过)。
    """
    import os
    import tempfile
    from pathlib import Path

    from argos_agent import runtime
    from argos_agent.approval import ApprovalGate, ApprovalLevel
    from argos_agent.core.loop import AgentLoop, LoopConfig
    from argos_agent.core.verify_gate import Verifier
    from argos_agent.memory.store import ArgosStore
    from argos_agent.sandbox.broker import CapabilityBroker
    from argos_agent.sandbox.egress import EgressPolicy
    from argos_agent.sandbox.executor import SeatbeltExecutor
    from argos_agent.tools.receipts import ReceiptSigner
    from argos_agent.tui.events import EventBus, VerifyVerdict

    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "proj"
        proj.mkdir()
        # selftest 用系统 python3 自包含验证 —— 不依赖 pytest 在 PATH(裸 binary 运行时
        # shell PATH 常无 pytest;真实用户在自己项目里 pytest 在其 venv,不受影响)。
        os.environ["ARGOS_WORKSPACE"] = str(proj)
        tok = runtime.use_project(str(proj))
        store = None
        try:
            gate = ApprovalGate(level=ApprovalLevel.AUTO)
            broker = CapabilityBroker(
                gate=gate,
                egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
                signer=ReceiptSigner(key=b"selftest"),
            )

            def broker_handler(action, args):
                value, _exit = broker._execute(action, args)
                return value

            sandbox = SeatbeltExecutor(broker_handler=broker_handler)
            model = _SelftestModel([
                "```python\nwrite_file('st.py', 'def f():\\n    return 1\\n')\n```",
                "完成。",
            ])
            store = ArgosStore(db_path=str(Path(td) / "argos.db"))
            loop = AgentLoop(
                store=store, bus=EventBus(), sandbox=sandbox, broker=broker, model=model,
                verifier=Verifier(max_rounds=3),
                config=LoopConfig(verify_cmd='python3 -c "import st; assert st.f() == 1"',
                                  approval_level=ApprovalLevel.AUTO, compaction=False),
                workspace=proj, verify_dir=proj,
            )

            async def _go() -> list[str]:
                vs: list[str] = []
                async for ev in loop.run("实现 st.f 返回 1", "selftest"):
                    if isinstance(ev, VerifyVerdict):
                        vs.append(ev.verdict.status)
                return vs

            verdicts = asyncio.run(_go())
            ok = bool(verdicts) and verdicts[-1] == "passed"
            print(f"[selftest] verdicts={verdicts} → {'OK' if ok else 'FAIL'}")
            return 0 if ok else 1
        except Exception as e:  # noqa: BLE001 — 自检失败诚实返 1,不假装通过
            print(f"[selftest] 装配自检失败:{type(e).__name__}: {e} → FAIL", file=sys.stderr)
            return 1
        finally:
            if store is not None:
                store.close()
            runtime.reset(tok)


def main() -> None:
    # 冻结 binary(PyInstaller)的沙箱子进程 re-exec:被哨兵 argv 调起时,直接跑沙箱子进程
    # RPC 循环并退出(此时 sys.executable=argos binary,无法 `-m`;见 seatbelt.python_child_argv)。
    # 必须在 argparse 之前 —— 否则未知 argv 会打印 usage 而非进子进程。
    from argos_agent.sandbox.seatbelt import SANDBOX_CHILD_FLAG
    if SANDBOX_CHILD_FLAG in sys.argv[1:]:
        from argos_agent.sandbox import _sandbox_child
        _sandbox_child.main()
        return

    args = _build_parser().parse_args()

    if args.selftest:
        sys.exit(_run_selftest())

    from argos_agent.tui.app import ArgosApp

    if args.demo_fail:
        from argos_agent.tui.fakeloop import FailingFakeLoop
        ArgosApp(loop_factory=lambda: FailingFakeLoop()).run()
        return
    if args.demo:
        from argos_agent.tui.fakeloop import FakeLoop
        ArgosApp(loop_factory=lambda: FakeLoop()).run()
        return

    # 真 loop:组装全栈;无 key 诚实落 demo 态(不假装能跑)。
    try:
        from argos_agent.app_factory import build_components, build_loop_factory
        from argos_agent.approval import ApprovalLevel
        components = build_components(
            workspace=args.project, premium=args.premium, approval_level=ApprovalLevel.CONFIRM,
        )
        factory = build_loop_factory(components)
        ArgosApp(loop_factory=factory, demo=False).run()
    except RuntimeError as e:
        from argos_agent.tui.fakeloop import FakeLoop
        print(f"[argos] {e}\n[argos] 落演示态(FakeLoop)——配好 key 后重启即接真模型。", file=sys.stderr)
        ArgosApp(loop_factory=lambda: FakeLoop(), demo=True).run()


if __name__ == "__main__":
    main()
