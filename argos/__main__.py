"""`argos` 命令入口(Phase 6 整机集成)。

默认注入真 loop_factory(app_factory 组装的 AgentLoop);无 key → 诚实落 demo 态。
选项:
  --demo / --demo-fail   FakeLoop 演示(成功 / escalation 路径,沿用 Phase 5)
  --selftest             不连真模型自检:脚本模型跑一轮四阶段贯通,打印 verdict 退出
  --project PATH         在用户项目目录干活(runtime.use_project)
  --model NAME           本次启动用指定的 config profile(默认当前 active;模型不绑定、无档位)

子命令:
  exec "<任务>"          非交互 headless 执行(可脚本化 / CI;对标 claude -p / codex exec)
  setup / self-update / eval / skills / context / dream
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from argos.i18n import t


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="argos", description="Argos — the hundred-eyed agent")
    # 版本号从 argos.__version__ 读(importlib.metadata)
    import argos
    p.add_argument(
        "--version",
        action="version",
        version=f"argos {argos.__version__}",
    )
    p.add_argument("--demo", action="store_true", help=t("cli.demo.help"))
    p.add_argument("--demo-fail", action="store_true", help=t("cli.demo_fail.help"))
    p.add_argument("--selftest", action="store_true", help=t("cli.selftest.help"))
    p.add_argument("--project", metavar="PATH", help=t("cli.project.help"))
    p.add_argument("--model", metavar="NAME", help=t("cli.model.help"))
    # #11 per-task routing:effort 等级(契约 §11;spec §8)。effort 只控步数预算;审批档由
    # /trust 拨盘(Cautious/Trusted/Autonomous)独立控制(2026-06-20 重设后两者解耦)。
    from argos.routing.effort import EffortLevel
    p.add_argument("--effort", choices=[e.value for e in EffortLevel],
                   default=EffortLevel.MEDIUM.value,
                   help=t("cli.effort.help"))
    sub = p.add_subparsers(dest="command")
    # headless 非交互执行(可脚本化 / CI):argos exec "<任务>"
    from argos.cli import headless as _headless_cli
    _headless_cli.add_subparser(sub)
    sub.add_parser(
        "setup",
        help=t("cli.setup.help"),
        epilog=t("cli.setup.epilog"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp_update = sub.add_parser(
        "self-update",
        help=t("cli.self_update.help"),
    )
    sp_update.set_defaults(func=_cmd_self_update)
    # #7:argos eval 子命令
    from argos.cli import eval as _eval_cli
    _eval_cli.add_subparser(sub)
    # #10:argos skills 子命令
    from argos.cli import skills as _skills_cli
    _skills_cli.add_subparser(sub)
    # #12:argos context 子命令
    from argos.cli import context as _context_cli
    _context_cli.add_subparser(sub)
    # T10:argos dream 子命令(夜间整合 + 记忆整理)
    from argos.cli import dream as _dream_cli
    _dream_cli.add_subparser(sub)
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

    from argos import runtime
    from argos.approval import ApprovalGate, ApprovalLevel
    from argos.core.loop import AgentLoop, LoopConfig
    from argos.core.verify_gate import Verifier
    from argos.memory.store import ArgosStore
    from argos.sandbox.broker import CapabilityBroker
    from argos.sandbox.egress import EgressPolicy
    from argos.sandbox.executor import SeatbeltExecutor
    from argos.tools.receipts import ReceiptSigner
    from argos.protocol.events import VerifyVerdict
    from argos.protocol.events import EventBus

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
                value, _exit = broker.execute_sync(action, args)
                return value

            sandbox = SeatbeltExecutor(broker_handler=broker_handler)
            model = _SelftestModel([
                "```python\nwrite_file('st.py', 'def f():\\n    return 1\\n')\n```",
                t("cli.selftest.done"),
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
                async for ev in loop.run(t("cli.selftest.task"), "selftest"):
                    if isinstance(ev, VerifyVerdict):
                        vs.append(ev.verdict.status)
                return vs

            verdicts = asyncio.run(_go())
            ok = bool(verdicts) and verdicts[-1] == "passed"
            print(f"[selftest] verdicts={verdicts} → {'OK' if ok else 'FAIL'}")
            return 0 if ok else 1
        except Exception as e:  # noqa: BLE001 — 自检失败诚实返 1,不假装通过
            print(t("cli.selftest.assembly_failed", exc_type=type(e).__name__, exc=e), file=sys.stderr)
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
        from argos import __version__
        from argos.core.updater import check_github_release
        cache = Path.home() / ".argos" / ".last_update_check"
        newer = check_github_release(
            current_version=__version__,
            cache_path=cache,
            force=True,  # 主动命令跳过缓存
        )
    except Exception as e:  # noqa: BLE001
        print(t("cli.self_update.check_failed", err=e), file=sys.stderr)
        return 1
    if newer:
        print(f"🆕 Argos {newer} available (you have {__version__}).")
        # 检测 Homebrew Cask 安装痕迹(spec §2.6 友好提示)
        brew_cask = Path("/opt/homebrew/Caskroom/argos")
        if brew_cask.exists():
            print(t("cli.self_update.brew_hint"))
        else:
            print(t("cli.self_update.install_hint"))
        return 0
    print(t("cli.self_update.up_to_date", version=__version__))
    return 0


def _spawn_update_check() -> None:
    """启动时 background check update(仅查不下载,网络失败静默)。

    spec §2.5:缓存 7 天,启动不卡,user 主动跑 `argos self-update` 升级。
    """
    try:
        from argos import __version__
        from argos.core.updater import check_github_release
        cache = Path.home() / ".argos" / ".last_update_check"
        # 同步阻塞一次(短,网络 5s 超时,启动开销可接受)
        newer = check_github_release(
            repo="tungoldshou/argos",
            current_version=__version__,
            cache_path=cache,
        )
        if newer:
            print(
                t("cli.update_available_banner", newer=newer, current=__version__),
                file=sys.stderr,
            )
    except Exception:  # noqa: BLE001 — 任何失败都不阻断启动
        pass


def main() -> None:
    # 冻结 binary(PyInstaller)的沙箱子进程 re-exec:被哨兵 argv 调起时,直接跑沙箱子进程
    # RPC 循环并退出(此时 sys.executable=argos binary,无法 `-m`;见 seatbelt.python_child_argv)。
    # 必须在 argparse 之前 —— 否则未知 argv 会打印 usage 而非进子进程。
    from argos.sandbox.seatbelt import SANDBOX_CHILD_FLAG
    if SANDBOX_CHILD_FLAG in sys.argv[1:]:
        from argos.sandbox import _sandbox_child
        _sandbox_child.main()
        return

    args = _build_parser().parse_args()
    # 启动时查更新(同步,失败静默,stderr 提示)。headless `exec` 跳过 —— CI / 脚本化场景
    # 既不该被 5s 网络检查拖慢,也不该往 stderr 喷升级提示污染输出。
    if getattr(args, "command", None) != "exec":
        _spawn_update_check()

    # 子命令分发:func 子命令(exec / self-update / …)的返回值即进程退出码(sys.exit 真正传递,
    # 此前 `return args.func(args)` 被 main() 吞掉 → 退出码恒 0,headless / self-update 无法被脚本判别)。
    if hasattr(args, "func") and callable(getattr(args, "func", None)):
        sys.exit(args.func(args) or 0)

    if getattr(args, "command", None) == "setup":
        from argos import setup_wizard
        asyncio.run(setup_wizard.run(
            reader=lambda prompt="": input(prompt), writer=print))
        return

    if args.selftest:
        sys.exit(_run_selftest())

    from argos.tui.app import ArgosApp

    if args.demo_fail:
        from argos.tui.fakeloop import FailingFakeLoop
        ArgosApp(loop_factory=lambda: FailingFakeLoop()).run()
        return
    if args.demo:
        from argos.tui.fakeloop import FakeLoop
        ArgosApp(loop_factory=lambda: FakeLoop()).run()
        return

    # 真 loop:组装全栈;无 key 诚实落 demo 态(不假装能跑)。
    try:
        from argos.app_factory import build_components, build_loop_factory
        from argos.approval import ApprovalLevel
        from argos.config import ConfigError as _TuiConfigError
        from argos.routing.effort import EffortLevel
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
    except (RuntimeError, _TuiConfigError) as e:
        # ConfigError(config.py) subclasses Exception, not RuntimeError → 分开列举。
        # 无 key / 无效 profile → 诚实落 demo 态,不假装能跑。
        from argos.tui.fakeloop import FakeLoop
        print(t("cli.no_key_fallback", err=e), file=sys.stderr)
        ArgosApp(loop_factory=lambda: FakeLoop(), demo=True).run()


if __name__ == "__main__":
    main()
