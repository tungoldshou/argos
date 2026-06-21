"""#10 T1+T6 `argos skills` CLI 子命令(refresh/list/install/remove/test)。

沿用 cli/eval.py 风格:__main__.py 加 subparser,具体 handler 在这里。

D7:builtin 3 名硬拒(install/remove)
D8:user 装后 enabled=false,需手动改 frontmatter
D10:TUI 不直接 install(沿 transcript 提示)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from argos.skills_curator.index import BUILTIN_NAMES
from argos.i18n import t


def cmd_refresh(args: argparse.Namespace) -> int:
    from argos.skills_curator.index import (
        DEFAULT_INDEX_URL,
        IndexFetchError,
        fetch_remote,
        save_cache,
    )
    url = args.url or DEFAULT_INDEX_URL
    print(f"[skills] fetching {url} ...")
    try:
        cache = fetch_remote(url=url)
    except IndexFetchError as e:
        print(f"[skills] error: {e}", file=sys.stderr)
        return 1
    target = save_cache(cache)
    print(f"[skills] received {target.stat().st_size} bytes")
    print(f"[skills] index updated: {len(cache.skills)} skills")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    from argos.skills_curator.capabilities import list_installed
    from argos.skills_curator.index import cache_age_days, load_cache

    installed = list_installed()
    by_name = {s.name: s for s in installed}
    cache = load_cache()

    header = (f"{'name':<20} {'version':<10} {'author':<14} {'capabilities':<28} "
              f"{'status':<12} {'enabled':<8}")
    print(header)
    print("-" * 90)
    for s in installed:
        caps = "[" + ", ".join(s.capabilities) + "]"
        flag = "✓"
        if not s.enabled:
            flag = "✗ (unreviewed)" if s.name not in BUILTIN_NAMES else "✗ (builtin off)"
        print(f"{s.name:<20} {s.version:<10} {s.author:<14} {caps:<28} "
              f"installed   {flag:<8}")
    if cache is not None:
        for e in cache.skills:
            if e.name in by_name:
                continue
            caps = "[" + ", ".join(e.capabilities) + "]"
            print(f"{e.name:<20} {e.version:<10} {e.author:<14} {caps:<28} "
                  f"available   {'-':<8}")
    age = cache_age_days()
    if age is not None:
        print(f"\n(last index refresh: {age:.1f}d ago; "
              f"{len(installed)} installed)")
    elif not installed:
        print(t("cli.skills.no_skills_hint"))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    from argos.skills_curator.index import load_cache
    from argos.skills_curator.install import InstallError, install

    name = args.name
    # 网络 skill 二次确认(spec §6.1 防线 3)
    cache = load_cache()
    if cache:
        entry = cache.find(name)
        if entry and "network" in entry.capabilities:
            ans = input(t("cli.skills.network_confirm", name=name)).strip().lower()
            if ans != "y":
                print("[skills] cancelled")
                return 1
            os.environ["ARGOS_SKILLS_NETWORK_OK"] = "1"

    try:
        r = install(name, run_smoke=True)
    except InstallError as e:
        print(f"[skills] error: {e}", file=sys.stderr)
        return 1
    print(f"[skills] installed to {r.path}")
    if r.warnings:
        for w in r.warnings:
            print(f"[skills] WARNING: {w}")
    if r.smoke:
        print(f"[skills] smoke test: {r.smoke}")
    print("[skills] NOTE: installed with enabled=false")
    print("[skills] review before enabling:")
    print(f"        $ cat {r.path}")
    print("        $ edit frontmatter: enabled: true")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    from argos.skills_curator.install import InstallError
    from argos.skills_curator.remove import remove

    try:
        r = remove(args.name)
    except InstallError as e:
        print(f"[skills] error: {e}", file=sys.stderr)
        return 1
    until = time.strftime("%Y-%m-%d", time.localtime(r.recoverable_until))
    print(f"[skills] moved to {r.trash_path} (recoverable until {until})")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    from argos.skills_curator.index import _skills_root
    from argos.skills_curator.smoke import run_smoke_test

    root = _skills_root()
    skill_dir = root / args.name
    if not skill_dir.exists():
        print(f"[skills] not installed: {args.name}", file=sys.stderr)
        return 1
    result = run_smoke_test(args.name, skill_dir)
    print(f"[skills] {args.name}: {result}")
    return 0 if result.startswith("pass") else 1


def add_subparser(sub: Any) -> None:
    p = sub.add_parser(
        "skills",
        help=t("cli.skills.help"),
    )
    sp = p.add_subparsers(dest="skills_command")

    p_refresh = sp.add_parser("refresh", help=t("cli.skills.refresh.help"))
    p_refresh.add_argument("--url", default=None, help=t("cli.skills.refresh.url.help"))
    p_refresh.set_defaults(func=cmd_refresh)

    p_list = sp.add_parser("list", help=t("cli.skills.list.help"))
    p_list.set_defaults(func=cmd_list)

    p_install = sp.add_parser("install", help=t("cli.skills.install.help"))
    p_install.add_argument("name", help=t("cli.skills.install.name.help"))
    p_install.set_defaults(func=cmd_install)

    p_remove = sp.add_parser("remove", help=t("cli.skills.remove.help"))
    p_remove.add_argument("name", help="skill name")
    p_remove.set_defaults(func=cmd_remove)

    p_test = sp.add_parser("test", help=t("cli.skills.test.help"))
    p_test.add_argument("name", help="skill name")
    p_test.set_defaults(func=cmd_test)
