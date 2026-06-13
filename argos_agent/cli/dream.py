"""T10 argos dream CLI 子命令。

- 无参数:跑一轮完整 DreamPipeline(有 key)或仅做记忆整理盘点(无 key)。
- --report:只读最新报告文件最后一行,打印摘要;无报告则诚实输出"暂无 Dream 报告"。

退出码:成功 0,异常 1。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ARGOS_DREAMS_DIR 环境变量覆盖(测试/CI 用)
_DEFAULT_DREAMS_DIR = Path.home() / ".argos" / "dreams"
_DEFAULT_MEMORY_DIR = Path.home() / ".argos" / "memory"
_DEFAULT_CANDIDATES_DIR = Path.home() / ".argos" / "learning" / "candidates"
_DEFAULT_SKILLS_DIR = Path.home() / ".argos" / "learning" / "skills"


def _dreams_dir() -> Path:
    """返回 dreams 报告目录(ARGOS_DREAMS_DIR 覆盖,测试友好)。"""
    env = os.environ.get("ARGOS_DREAMS_DIR")
    return Path(env) if env else _DEFAULT_DREAMS_DIR


def _memory_dir() -> Path:
    """返回 memory 目录(ARGOS_MEMORY_DIR 覆盖,测试友好)。"""
    env = os.environ.get("ARGOS_MEMORY_DIR")
    return Path(env) if env else _DEFAULT_MEMORY_DIR


def _latest_report() -> dict | None:
    """读最新 dreams JSONL 文件的最后一行(dict);无文件 → None。

    最新 = 按文件名 sorted 最大(文件名格式 YYYY-MM-DD.jsonl,字典序=时间序)。
    """
    d = _dreams_dir()
    if not d.exists():
        return None
    files = sorted(d.glob("*.jsonl"))
    if not files:
        return None
    latest = files[-1]
    # 读最后一行(非空)
    last_line = None
    try:
        for line in latest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                last_line = line
    except Exception as e:  # noqa: BLE001
        log.warning("dream CLI: 读报告文件失败: %s", e)
        return None
    if not last_line:
        return None
    try:
        return json.loads(last_line)
    except json.JSONDecodeError as e:  # noqa: BLE001
        log.warning("dream CLI: 报告行 JSON 解析失败: %s", e)
        return None


def _fmt_report(r: dict) -> str:
    """把报告 dict 格式化成一行摘要。"""
    return (
        f"Dream 报告  "
        f"units_total={r.get('units_total', 0)}  "
        f"promoted={r.get('promoted', 0)}  "
        f"rejected={r.get('rejected', 0)}  "
        f"skipped={r.get('skipped', 0)}  "
        f"memory_merged={r.get('memory_merged', 0)}  "
        f"memory_archived={r.get('memory_archived', 0)}"
    )


def run_dream(args: Any) -> int:
    """argos dream 主入口。args.report=True → 只读报告;否则跑一轮。"""
    # ── --report 路径 ──────────────────────────────────────────────────
    if getattr(args, "report", False):
        report = _latest_report()
        if report is None:
            print("暂无 Dream 报告(候选区空或从未跑过 Dream)。")
            return 0
        print(_fmt_report(report))
        return 0

    # ── 跑一轮 ────────────────────────────────────────────────────────
    # 尝试构建 components(有 key 才能跑 A/B 晋升)
    has_key = True
    try:
        from argos_agent.app_factory import build_components
        build_components()          # 仅检测 key 是否配好;RuntimeError → 无 key
    except RuntimeError:
        has_key = False
    except Exception:  # noqa: BLE001 — 其他初始化失败也视为无法跑完整 pipeline
        has_key = False

    if not has_key:
        # 无 key:仅做记忆整理 + 候选区盘点,诚实告知晋升需要模型
        print("无 API key:仅做记忆整理与候选区盘点(A/B 晋升跳过)。")
        print("若要完整 Dream 晋升,请先运行 `argos setup` 配置模型。")
        mem_dir = _memory_dir()
        try:
            from argos_agent.memory.consolidate import consolidate
            rep = consolidate(mem_dir)
            print(f"记忆整理:merged={rep.merged} archived={rep.archived}")
        except Exception as e:  # noqa: BLE001
            log.warning("dream CLI: 记忆整理失败: %s", e)
            print(f"记忆整理失败(降级跳过): {e}")
        # 候选区盘点
        try:
            from argos_agent.learning.candidates import list_unconsumed, DEFAULT_ROOT
            cands = list_unconsumed(DEFAULT_ROOT)
            print(f"候选区未消费材料: {len(cands)} 条(配置 key 后可触发晋升)")
        except Exception as e:  # noqa: BLE001
            log.warning("dream CLI: 候选区盘点失败: %s", e)
        return 0

    # 有 key:跑完整 DreamPipeline
    import asyncio

    dreams_dir = _dreams_dir()
    dreams_dir.mkdir(parents=True, exist_ok=True)
    mem_dir = _memory_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)

    candidates_root = _DEFAULT_CANDIDATES_DIR
    skills_root = _DEFAULT_SKILLS_DIR

    # 构建 narrate fn(调 model.complete)
    try:
        from argos_agent.app_factory import build_components
        comps = build_components()
        model = comps.model

        def _narrate(prompt: str) -> str:
            """同步叙述调用(pipeline 的 narrate 可以是同步或 async)。"""
            import asyncio as _aio
            return _aio.run(model.complete(
                [{"role": "user", "content": prompt}],
                system="你是知识提炼助手,只输出纯文字摘要,不输出代码。",
            ))
    except Exception:  # noqa: BLE001
        _narrate = None

    # 构建 runner_factory(用于 A/B 晋升)
    try:
        from argos_agent.app_factory import build_components, build_loop_factory
        from argos_agent.eval.runner import EvalRunner
        from argos_agent.daemon.worktree import WorktreeManager
        base = Path.home() / ".argos" / "eval"
        wm = WorktreeManager(base_dir=base / "worktrees")

        def _runner_factory(hint: str | None):
            return EvalRunner(worktree=wm, base_dir=base)
    except Exception:  # noqa: BLE001
        _runner_factory = None

    if _runner_factory is None:
        print("警告: 无法初始化 eval runner,跳过 A/B 晋升。")
        return 0

    from argos_agent.learning.dream import DreamPipeline

    pipeline = DreamPipeline(
        candidates_root=candidates_root,
        skills_root=skills_root,
        memory_dir=mem_dir,
        dreams_dir=dreams_dir,
        runner_factory=_runner_factory,
        narrate=_narrate,
        broadcast_fn=None,
    )

    print("Dream 启动(跨 run 聚类综合 + A/B 晋升 + 记忆整理)…")
    try:
        report = asyncio.run(pipeline.run())
    except Exception as e:  # noqa: BLE001
        print(f"Dream 管道执行失败: {e}", file=__import__("sys").stderr)
        return 1

    if report is None:
        print("Dream 已在运行(单飞),跳过本次。")
        return 0

    print(_fmt_report({
        "units_total": report.units_total,
        "promoted": report.promoted,
        "rejected": report.rejected,
        "skipped": report.skipped,
        "memory_merged": report.memory_merged,
        "memory_archived": report.memory_archived,
    }))
    if report.report_path:
        print(f"报告已写入: {report.report_path}")
    return 0


def add_subparser(sub: Any) -> None:
    """注册 dream 子命令到 argparse subparsers。"""
    p = sub.add_parser(
        "dream",
        help="夜间整合:跨 run 综合蒸馏 + 记忆整理(--report 看上次报告)",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="只读最新 Dream 报告(不跑新一轮)",
    )
    p.set_defaults(func=run_dream)
