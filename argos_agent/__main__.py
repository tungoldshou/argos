"""`argos` 命令入口(Phase 6 整机集成)。

默认注入真 loop_factory(app_factory 组装的 AgentLoop);无 key → 诚实落 demo 态。
选项:
  --demo / --demo-fail   FakeLoop 演示(成功 / escalation 路径,沿用 Phase 5)
  --selftest             不连真模型自检:脚本模型跑一轮四阶段贯通,打印 verdict 退出
  --project PATH         在用户项目目录干活(runtime.use_project)
  --model NAME           本次启动用指定的 config profile(默认当前 active;模型不绑定、无档位)
  --resume SESSION_ID    续跑历史会话(占位透传;真续跑走 TUI 内 /resume)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="argos", description="终端超级智能体")
    # 版本号从 argos_agent.__version__ 读(importlib.metadata)
    import argos_agent
    p.add_argument(
        "--version",
        action="version",
        version=f"argos {argos_agent.__version__}",
    )
    p.add_argument("--demo", action="store_true", help="FakeLoop 成功演示")
    p.add_argument("--demo-fail", action="store_true", help="FailingFakeLoop escalation 演示")
    p.add_argument("--selftest", action="store_true", help="不连真模型自检(脚本模型跑四阶段)")
    p.add_argument("--project", metavar="PATH", help="在用户项目目录干活")
    p.add_argument("--model", metavar="NAME", help="本次启动用指定 config profile(默认当前 active)")
    p.add_argument("--resume", metavar="SESSION_ID", help="续跑历史会话(占位:真续跑走 TUI /resume)")
    # #11 per-task routing:effort 等级(契约 §11;spec §8):low/medium/high 映射到
    # max_steps + approval_level;CLI 默认 medium。
    from argos_agent.routing.effort import EffortLevel
    p.add_argument("--effort", choices=[e.value for e in EffortLevel],
                   default=EffortLevel.MEDIUM.value,
                   help="任务努力档(low=8 步+AUTO;medium=40+CONFIRM;high=80+CONFIRM)")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("setup", help="接入模型的交互向导(选 provider→填 key→连通测试→保存)")
    sp_update = sub.add_parser(
        "self-update",
        help="检查并提示新版本(不自动下载;跳过 7 天缓存)",
    )
    sp_update.set_defaults(func=_cmd_self_update)
    # #7:argos eval 子命令
    from argos_agent.cli import eval as _eval_cli
    _eval_cli.add_subparser(sub)
    # #10:argos skills 子命令
    from argos_agent.cli import skills as _skills_cli
    _skills_cli.add_subparser(sub)
    # #12:argos context 子命令
    from argos_agent.cli import context as _context_cli
    _context_cli.add_subparser(sub)
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

    async def stream(self, messages, *, system, system_dynamic=None):
        for ch in self._next():
            yield ch

    async def complete(self, messages, *, system) -> str:
        return self._next()


def resolve_workspace(project_arg: str | None) -> str | None:
    """解析有效 workspace(实测 bug 修复:不传 --project 时默认【当前目录】)。

    「所有人」UX 契约:用户在自己的文件夹里启动 argos,agent 就该在那个文件夹干活
    ——否则任务会落到隐藏的默认工作区,用户的文件一个都看不见(2026-06-12 实测)。
    护栏:cwd 是 home 目录或文件系统根时不默认(整个家目录当 workspace 危险面太大),
    返回 None 走旧默认 ~/.argos/workspace,用户可用 --project 显式指定。
    """
    if project_arg:
        return project_arg
    import os
    cwd = Path(os.getcwd()).resolve()
    if cwd == Path.home() or cwd == Path(cwd.anchor):
        return None
    return str(cwd)


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
    from argos_agent.protocol.events import VerifyVerdict
    from argos_agent.protocol.events import EventBus

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


def _cmd_self_update(args) -> int:
    """`argos self-update`:force 检查 + 提示如何升级。

    不下载(用户拍)。Homebrew Cask 用户提示用 brew upgrade。
    """
    try:
        from argos_agent import __version__
        from argos_agent.core.updater import check_github_release
        cache = Path.home() / ".argos" / ".last_update_check"
        newer = check_github_release(
            current_version=__version__,
            cache_path=cache,
            force=True,  # 主动命令跳过缓存
        )
    except Exception as e:  # noqa: BLE001
        print(f"argos self-update: 检查失败:{e}", file=sys.stderr)
        return 1
    if newer:
        print(f"🆕 Argos {newer} available (you have {__version__}).")
        # 检测 Homebrew Cask 安装痕迹(spec §2.6 友好提示)
        brew_cask = Path("/opt/homebrew/Caskroom/argos")
        if brew_cask.exists():
            print("   您通过 Homebrew 装的,请用:brew upgrade --cask argos")
        else:
            print("   重装最新版:curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash")
        return 0
    print(f"✓ argos {__version__} 已是最新 (up to date)。")
    return 0


def _spawn_update_check() -> None:
    """启动时 background check update(仅查不下载,网络失败静默)。

    spec §2.5:缓存 7 天,启动不卡,user 主动跑 `argos self-update` 升级。
    """
    try:
        from argos_agent import __version__
        from argos_agent.core.updater import check_github_release
        cache = Path.home() / ".argos" / ".last_update_check"
        # 同步阻塞一次(短,网络 5s 超时,启动开销可接受)
        newer = check_github_release(
            repo="tungoldshou/argos",
            current_version=__version__,
            cache_path=cache,
        )
        if newer:
            print(
                f"🆕 Argos {newer} available (you have {__version__}). "
                f"Run `argos self-update` to upgrade.",
                file=sys.stderr,
            )
    except Exception:  # noqa: BLE001 — 任何失败都不阻断启动
        pass


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
    # 启动时查更新(同步,失败静默,stderr 提示)。在 parse_args 之后 → future
    # `argos self-update` 子命令自身的执行不会被这条通知逻辑干扰。
    _spawn_update_check()

    # 子命令分发:`setup` 走交互向导,`self-update` 走 _cmd_self_update(force 检查)
    if hasattr(args, "func") and callable(getattr(args, "func", None)):
        return args.func(args)

    if getattr(args, "command", None) == "setup":
        from argos_agent import setup_wizard
        asyncio.run(setup_wizard.run(
            reader=lambda prompt="": input(prompt), writer=print))
        return

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
        from argos_agent.routing.effort import EffortLevel
        effective_ws = resolve_workspace(args.project)
        components = build_components(
            workspace=effective_ws, model_override=args.model, approval_level=ApprovalLevel.CONFIRM,
            effort=EffortLevel(args.effort),
        )
        factory = build_loop_factory(components)
        # 用 broker 的 gate 作 app.gate(同一实例)→ 工作流/工具审批 respond 落在 loop 真正
        # await 的那个 gate 上;顺带让 /yolo 对真 gate 生效(不再是 app 自建的孤儿 gate)。
        ArgosApp(
            loop_factory=factory, gate=components.gate, demo=False,
            workspace=effective_ws or components.workspace,
        ).run()
    except RuntimeError as e:
        from argos_agent.tui.fakeloop import FakeLoop
        print(f"[argos] {e}\n[argos] 运行 `argos setup` 接入模型,或配置环境变量后重启。", file=sys.stderr)
        ArgosApp(loop_factory=lambda: FakeLoop(), demo=True).run()


if __name__ == "__main__":
    main()
