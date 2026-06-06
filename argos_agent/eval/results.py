"""#7 T4 Result JSONL 持久化 + list/load/summary。

存 `~/.argos/eval/runs/<YYYY-MM-DD>/<run_id>.jsonl`(每 run 1 文件,1 行)。

为什么每 run 一文件(而非一行一 run 全局):
  · 沿用 daemon/store.py 模式(锁粒度细)
  · 跑一半的 run 写文件,不污染别的
  · 错行易排查
  · 与 #5a / #5b daemon 区分(daemon 是事件流,eval 是单条结果聚合)

D2:JSONL(沿用 #5a)
D10:cost 字段精度 = float(spec §12 D10)
D20:用户态数据目录(同 #5a / #5b / #9 一致)
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from argos_agent.eval.runner import EvalResult

_RUNS_DIR = Path.home() / ".argos" / "eval" / "runs"
_WRITE_LOCK = threading.Lock()


def _runs_dir(base: Path | None = None) -> Path:
    """返 runs 目录(base 是 eval 根,加 /runs 子目录;不传则用模块默认)。"""
    return (base if base is not None else _RUNS_DIR.parent) / "runs"


def _date_str(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def append(result: EvalResult, *, base: Path | None = None) -> None:
    """追加 1 条结果。线程安全;IO 错误静默(不阻塞主流程)。"""
    d = _runs_dir(base) / _date_str(result.finished_at)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    p = d / f"{result.run_id}.jsonl"
    line = result.to_json() + "\n"
    with _WRITE_LOCK:
        try:
            with p.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


def list_runs(
    *, base: Path | None = None, date: str | None = None, limit: int = 50,
) -> list[EvalResult]:
    """列最近 run(默认跨所有日期,按 finished_at 倒序)。

    - date=None:扫所有日期目录(最新 → 最旧)
    - date="YYYY-MM-DD":只扫该天
    - limit:truncate,默认 50
    """
    out: list[EvalResult] = []
    root = _runs_dir(base)
    if not root.exists():
        return out
    if date is not None:
        dates = [date]
    else:
        try:
            dates = sorted(
                (d.name for d in root.iterdir() if d.is_dir()),
                reverse=True,
            )
        except OSError:
            return out
    for d in dates:
        day = root / d
        if not day.is_dir():
            continue
        try:
            files = sorted(day.glob("*.jsonl"), reverse=True)
        except OSError:
            continue
        for p in files:
            try:
                text = p.read_text("utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(EvalResult.from_json(line))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]


def load_run(run_id: str, *, base: Path | None = None) -> EvalResult | None:
    """按 run_id 扫所有日期目录,返第一个;不存在 → None。"""
    root = _runs_dir(base)
    if not root.exists():
        return None
    try:
        days = sorted(
            (d for d in root.iterdir() if d.is_dir()),
            key=lambda x: x.name,
            reverse=True,
        )
    except OSError:
        return None
    for day in days:
        p = day / f"{run_id}.jsonl"
        if not p.is_file():
            continue
        try:
            text = p.read_text("utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    return EvalResult.from_json(line)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
    return None


def summary(
    *, base: Path | None = None, since_days: int = 7,
) -> dict[str, dict[str, dict[str, Any]]]:
    """聚合 {model_tier: {category: {passed, total, pass_rate}}}。

    - 跑过的 run(按 finished_at 过滤 since_days,默认 7 天)
    - category 从 task_id 推断(取 "_" 前缀:bug_fix_001_off_by_one → "bug_fix")
    - 0 run → {}
    """
    cutoff = time.time() - since_days * 86400
    runs = [r for r in list_runs(base=base, limit=10000) if r.finished_at >= cutoff]
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        cat = _category_of(r.task_id)
        m = out.setdefault(r.model_tier, {}).setdefault(
            cat, {"passed": 0, "total": 0, "pass_rate": 0.0},
        )
        m["total"] += 1
        if r.pass_status == "passed":
            m["passed"] += 1
    for m in out.values():
        for c in m.values():
            if c["total"]:
                c["pass_rate"] = round(c["passed"] / c["total"], 4)
    return out


def _category_of(task_id: str) -> str:
    """从 task_id 推断 category(沿 corpus 命名约定)。

    规则:取开头连续的非数字段,用 _ 连。
      bug_fix_001_off_by_one     → bug_fix
      refactor_001_extract_helper → refactor
      test_write_001_corpus_loader → test_write
      doc_001_module_header      → doc
    """
    parts = task_id.split("_")
    cat_parts: list[str] = []
    for p in parts:
        if p.isdigit():
            break
        cat_parts.append(p)
    return "_".join(cat_parts) if cat_parts else task_id
