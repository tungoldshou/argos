"""Internal documentation."""
from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import sys
from pathlib import Path

from argos.i18n import t


def _setup_paths() -> dict[str, str]:
    from argos import config as C

    config_dir = Path(C.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
    return {
        "config_path": str(config_dir / "config.json"),
        "env_path": str(config_dir / ".env"),
    }


def _update_cache_path() -> Path:
    from argos import config as C

    return Path(C.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / ".last_update_check"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="argos", description="Argos — the hundred-eyed agent")
    import argos
    p.add_argument(
        "--version",
        action="version",
        version=f"argos {argos.__version__}",
    )
    p.add_argument("--selftest", action="store_true", help=t("cli.selftest.help"))
    p.add_argument("--project", metavar="PATH", help=t("cli.project.help"))
    p.add_argument("--model", metavar="NAME", help=t("cli.model.help"))
    from argos.routing.effort import EffortLevel
    p.add_argument("--effort", choices=[e.value for e in EffortLevel],
                   default=EffortLevel.MEDIUM.value,
                   help=t("cli.effort.help"))
    p.add_argument("--sandbox", action="store_true", help=t("cli.sandbox.help"))
    p.add_argument("--add-dir", action="append", metavar="PATH", dest="add_dir",
                   help=t("cli.add_dir.help"))
    sub = p.add_subparsers(dest="command")
    from argos.cli import headless as _headless_cli
    _headless_cli.add_subparser(sub)
    sp_setup = sub.add_parser(
        "setup",
        help=t("cli.setup.help"),
        epilog=t("cli.setup.epilog", **_setup_paths()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp_setup.add_argument("--advanced", action="store_true", help=t("cli.setup.advanced_help"))
    sp_setup.add_argument("setup_action", nargs="?", choices=["status"], help=t("cli.setup.status.help"))
    sp_update = sub.add_parser(
        "self-update",
        help=t("cli.self_update.help"),
    )
    sp_update.set_defaults(func=_cmd_self_update)
    from argos.cli import eval as _eval_cli
    _eval_cli.add_subparser(sub)
    from argos.cli import skills as _skills_cli
    _skills_cli.add_subparser(sub)
    from argos.cli import context as _context_cli
    _context_cli.add_subparser(sub)
    from argos.cli import dream as _dream_cli
    _dream_cli.add_subparser(sub)
    return p


class _SelftestModel:
    """Internal documentation."""

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


def _selftest_verify_cmd() -> str:
    from argos.tools import ALLOWED_CMDS

    executable = Path(sys.executable)
    if not getattr(sys, "frozen", False) and executable.name in ALLOWED_CMDS:
        python_cmd = shlex.quote(str(executable))
    else:
        python_cmd = "python3"
    return f"{python_cmd} -c \"import st; assert st.f() == 1\""


def resolve_workspace(project_arg: str | None) -> str | None:
    """Internal documentation."""
    if project_arg:
        return project_arg
    import os
    cwd = Path(os.getcwd()).resolve()
    if cwd == Path.home() or cwd == Path(cwd.anchor):
        return None
    return str(cwd)


def _run_selftest() -> int:
    """Internal documentation."""
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
                config=LoopConfig(verify_cmd=_selftest_verify_cmd(),
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
        except Exception as e:  # noqa: BLE001
            print(t("cli.selftest.assembly_failed", exc_type=type(e).__name__, exc=e), file=sys.stderr)
            return 1
        finally:
            if store is not None:
                store.close()
            runtime.reset(tok)


def _cmd_self_update(args) -> int:
    """Internal documentation."""
    try:
        from argos import __version__
        from argos.core.updater import check_github_release
        cache = _update_cache_path()
        newer = check_github_release(
            current_version=__version__,
            cache_path=cache,
            force=True,
        )
    except Exception as e:  # noqa: BLE001
        print(t("cli.self_update.check_failed", err=e), file=sys.stderr)
        return 1
    if newer:
        print(f"🆕 Argos {newer} available (you have {__version__}).")
        brew_cask = Path("/opt/homebrew/Caskroom/argos")
        if brew_cask.exists():
            print(t("cli.self_update.brew_hint"))
        else:
            print(t("cli.self_update.install_hint"))
        return 0
    print(t("cli.self_update.up_to_date", version=__version__))
    return 0


def _spawn_update_check() -> None:
    """Internal documentation."""
    try:
        from argos import __version__
        from argos.core.updater import check_github_release
        cache = _update_cache_path()
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
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    from argos.sandbox.seatbelt import SANDBOX_CHILD_FLAG
    if SANDBOX_CHILD_FLAG in sys.argv[1:]:
        from argos.sandbox import _sandbox_child
        _sandbox_child.main()
        return

    args = _build_parser().parse_args()
    if getattr(args, "sandbox", False):
        os.environ["ARGOS_SANDBOX"] = "1"
    if getattr(args, "add_dir", None):
        os.environ["ARGOS_ADD_DIRS"] = os.pathsep.join(args.add_dir)
    if getattr(args, "command", None) is None and not args.selftest:
        _spawn_update_check()

    if hasattr(args, "func") and callable(getattr(args, "func", None)):
        sys.exit(args.func(args) or 0)

    if getattr(args, "command", None) == "setup":
        from argos import setup_wizard
        if getattr(args, "setup_action", None) == "status":
            setup_wizard.print_status(writer=print)
            return
        _con = None
        if sys.stdout.isatty():
            from rich.console import Console
            _con = Console()
        def _setup_reader(prompt: str = "") -> str:
            if prompt == t("setup.prompt_paste_key"):
                import getpass
                return getpass.getpass(prompt)
            return input(prompt)
        asyncio.run(setup_wizard.run(
            reader=_setup_reader, writer=print,
            console=_con, advanced=getattr(args, "advanced", False)))
        return

    if args.selftest:
        sys.exit(_run_selftest())

    from argos.tui.app import ArgosApp

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
        ArgosApp(
            loop_factory=factory, gate=components.gate,
            workspace=effective_ws or components.workspace,
        ).run()
    except (RuntimeError, _TuiConfigError) as e:
        print(t("cli.no_key_fallback", err=e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
