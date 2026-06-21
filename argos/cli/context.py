"""#12 Context 可视化 CLI:argos context show [--json] [--session=<id>]
(契约 §12;spec §11)。

单一 `ContextAnalyzer.analyze(...)` + format_table/format_json 渲染,跟 TUI /context
走同一路径(spec §12.5 锁:CLI/TUI 数字一致)。
子命令极简:只 `show`(本期无 `clear` / `set` / `drop` 等动作)。"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def _active_components():
    """从 app_factory 拿当前 active run 的 store / loop / workspace(若有);无则全 None。
    走 contextvars / 模块状态(同一进程 active run),测试可 monkeypatch。"""
    try:
        from argos import app_factory
        # app_factory 没有显式 active 容器;我们走 _active_run 全局(本期新增,后续 TUI 用同一)
        active = getattr(app_factory, "_active_run", None)
        if active is None:
            return None, None, Path.cwd()
        return (getattr(active, "store", None),
                getattr(active, "loop", None),
                getattr(active, "workspace", None) or Path.cwd())
    except Exception:  # noqa: BLE001
        return None, None, Path.cwd()


def cmd_show(args: argparse.Namespace) -> int:
    """`argos context show [--json] [--session=<id>]` — 走 ContextAnalyzer 出文本/JSON。
    无 active run 也能跑(空分析返全空桶,不崩;spec §13 错误处理)。"""
    from argos.context.analyzer import analyze
    from argos.context.render import format_json, format_table_plain
    store, loop, workspace = _active_components()
    try:
        b = analyze(loop, store=store, workspace=workspace)  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001
        print(f"context: 分析失败:{e}")
        return 1
    if args.json:
        print(format_json(b))
    else:
        # format_table_plain 已剥 Rich/Textual markup → 不会向终端泄漏裸 [green]…[/green] 标签
        print(format_table_plain(b))
    return 0


def add_subparser(sub: Any) -> None:
    p = sub.add_parser(
        "context",
        help="Context 可视化 (#12: show 看分桶 / JSON 导出)",
    )
    sp = p.add_subparsers(dest="context_command")
    p_show = sp.add_parser("show", help="看当前 LLM 上下文分桶(system/memory/tools/messages)")
    p_show.add_argument("--json", action="store_true", help="JSON 输出(机读,接 eval/二次开发)")
    p_show.add_argument("--session", default=None,
                         help="指定 session_id(本期默认当前 active)")
    p_show.set_defaults(func=cmd_show)
