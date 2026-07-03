from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from argos.i18n import t


def _active_components():
    try:
        from argos import app_factory
        active = getattr(app_factory, "_active_run", None)
        if active is None:
            return None, None, Path.cwd()
        return (getattr(active, "store", None),
                getattr(active, "loop", None),
                getattr(active, "workspace", None) or Path.cwd())
    except Exception:  # noqa: BLE001
        return None, None, Path.cwd()


def cmd_show(args: argparse.Namespace) -> int:
    from argos.context.analyzer import analyze
    from argos.context.render import format_json, format_table_plain
    store, loop, workspace = _active_components()
    try:
        b = analyze(loop, store=store, workspace=workspace)  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001
        print(t("cli.context.analysis_failed", err=e))
        return 1
    if args.json:
        print(format_json(b))
    else:
        print(format_table_plain(b))
    return 0


def add_subparser(sub: Any) -> None:
    p = sub.add_parser(
        "context",
        help=t("cli.context.help"),
    )
    p.set_defaults(func=lambda _args, parser=p: (parser.print_help(), 2)[1])
    sp = p.add_subparsers(dest="context_command")
    p_show = sp.add_parser("show", help=t("cli.context.show.help"))
    p_show.add_argument("--json", action="store_true", help=t("cli.context.json.help"))
    p_show.add_argument("--session", default=None,
                         help=t("cli.context.session.help"))
    p_show.set_defaults(func=cmd_show)
